import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from migration_assistant import claude_cli
from migration_assistant.claude_cli import ClaudeError
from migration_assistant.llm import AiSettings, ask_api, ask_opencode, available_providers, make_ask

KEY = "sk-ant-secret-key-123"


def proc(stdout="", stderr="", code=0):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout, stderr)


# ---- Claude Code CLI

def test_claude_cli_sends_the_prompt_on_stdin_not_argv():
    seen = {}

    def runner(cmd, **kw):
        seen.update(cmd=cmd, input=kw.get("input"))
        return subprocess.CompletedProcess(cmd, 0, '{"a": 1}', "")
    big = "x" * 300_000  # an argv entry this large would fail with "Argument list too long"
    assert claude_cli.ask_json(big, runner=runner) == {"a": 1}
    assert big in seen["input"] and all(big not in part for part in seen["cmd"])


# ---- Anthropic API

def fake_client(text='{"ok": true}', stop="end_turn", exc=None):
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            if exc:
                raise exc
            return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])
    return SimpleNamespace(messages=Messages()), calls


def status_error(cls, code):
    resp = httpx2.Response(code, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls("boom", response=resp, body=None)


def test_api_returns_parsed_json_and_uses_the_default_model():
    client, calls = fake_client('Here you go:\n{"ok": true}')
    assert ask_api("hi", api_key=KEY, client=client) == {"ok": True}
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["max_tokens"] >= 16000
    assert "JSON" in calls[0]["messages"][0]["content"]


def test_api_uses_the_chosen_model():
    client, calls = fake_client()
    ask_api("hi", api_key=KEY, model="claude-sonnet-5-5", client=client)
    assert calls[0]["model"] == "claude-sonnet-5-5"


def test_api_refusal_and_truncation_are_errors():
    with pytest.raises(ClaudeError, match="declined"):
        ask_api("hi", api_key=KEY, client=fake_client(stop="refusal")[0])
    with pytest.raises(ClaudeError, match="cut off"):
        ask_api("hi", api_key=KEY, client=fake_client(stop="max_tokens")[0])


@pytest.mark.parametrize("exc,expected", [
    (status_error(anthropic.AuthenticationError, 401), "rejected"),
    (status_error(anthropic.RateLimitError, 429), "rate limit"),
    (status_error(anthropic.NotFoundError, 404), "model"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "reach"),
    (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), "timed out"),
])
def test_api_errors_become_clear_claude_errors(exc, expected):
    with pytest.raises(ClaudeError, match=expected):
        ask_api("hi", api_key=KEY, client=fake_client(exc=exc)[0])


def test_api_error_text_never_contains_the_key():
    exc = status_error(anthropic.APIStatusError, 500)
    exc.message = f"server said {KEY}"
    with pytest.raises(ClaudeError) as e:
        ask_api("hi", api_key=KEY, client=fake_client(exc=exc)[0])
    assert KEY not in str(e.value)


def test_api_without_any_credentials_says_how_to_fix_it(monkeypatch):
    for k in list(os.environ):
        if k.startswith("ANTHROPIC_"):
            monkeypatch.delenv(k)
    with pytest.raises(ClaudeError, match="API key"):
        ask_api("hi", api_key=None)  # real SDK client: refuses to send without credentials


# ---- opencode

def test_opencode_gets_the_prompt_as_an_attached_file_in_a_scratch_dir():
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        seen["attached"] = Path(cmd[cmd.index("-f") + 1]).read_text()  # the temp dir is deleted afterwards
        return subprocess.CompletedProcess(cmd, 0, '\x1b[0m\n> build · m\n\x1b[0m{"ok": true}\n', "")
    big = "y" * 300_000
    assert ask_opencode(big, model="anthropic/claude-sonnet-5-5", runner=runner) == {"ok": True}
    assert big in seen["attached"]
    assert seen["cmd"][:2] == ["opencode", "run"] and seen["cmd"][seen["cmd"].index("-m") + 1] == "anthropic/claude-sonnet-5-5"
    assert all(big not in part for part in seen["cmd"])
    assert seen["cwd"] and Path(seen["cwd"]) != Path.cwd()  # never run in the project folder


def test_opencode_without_a_model_uses_its_own_default():
    seen = {}
    ask_opencode("hi", runner=lambda cmd, **kw: seen.setdefault("cmd", cmd) and subprocess.CompletedProcess(cmd, 0, '{"ok": 1}', ""))
    assert "-m" not in seen["cmd"]


@pytest.mark.parametrize("model", ["claude-sonnet", "--auto", "a b/c", "-x/y"])
def test_opencode_rejects_a_model_that_is_not_provider_slash_model(model):
    with pytest.raises(ClaudeError, match="provider/model"):
        ask_opencode("hi", model=model, runner=proc('{"a": 1}'))


def test_opencode_failure_shows_the_last_error_line_without_colour_codes():
    err = "\n> build · gpt-5-mini\n\n\x1b[31mError: The API deployment for this resource does not exist.\x1b[0m\n"
    with pytest.raises(ClaudeError, match="deployment for this resource does not exist") as e:
        ask_opencode("hi", runner=proc(stderr=err, code=1))
    assert "\x1b" not in str(e.value)


def test_opencode_missing_and_timeout():
    def missing(cmd, **kw):
        raise FileNotFoundError
    with pytest.raises(ClaudeError, match="not found"):
        ask_opencode("hi", runner=missing)

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired("opencode", 1)
    with pytest.raises(ClaudeError, match="timed out"):
        ask_opencode("hi", runner=slow)


# ---- dispatcher and availability

def test_make_ask_routes_to_the_chosen_provider():
    seen = []
    backends = {name: (lambda n: lambda prompt, s: seen.append((n, prompt, s.model)) or {"via": n})(name)
                for name in ("claude-cli", "anthropic-api", "opencode")}
    for name in backends:
        assert make_ask(AiSettings(provider=name, model="m"), backends=backends)("p") == {"via": name}
    assert seen == [("claude-cli", "p", "m"), ("anthropic-api", "p", "m"), ("opencode", "p", "m")]


def test_unknown_provider_is_a_clear_error():
    with pytest.raises(ClaudeError, match="provider"):
        make_ask(AiSettings(provider="nope"))("p")


def test_availability_reports_what_is_installed_and_whether_a_key_exists(monkeypatch):
    for k in list(os.environ):
        if k.startswith("ANTHROPIC_"):
            monkeypatch.delenv(k)
    which = {"claude": "/bin/claude", "opencode": None}
    got = {p["id"]: p for p in available_providers(AiSettings(), which=which.get)}
    assert got["claude-cli"]["available"] is True and got["opencode"]["available"] is False
    assert got["anthropic-api"]["available"] is True and "no key" in got["anthropic-api"]["detail"].lower()
    got = {p["id"]: p for p in available_providers(AiSettings(api_key=KEY), which=which.get)}
    assert "key set" in got["anthropic-api"]["detail"].lower()
    assert KEY not in str(got)
