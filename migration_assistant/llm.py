"""AI providers. Everything that needs an answer calls `ask(prompt) -> dict`; this module decides who answers.

Providers: Claude Code CLI (`claude -p`), the Anthropic API (SDK), and opencode (`opencode run`).
"""
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .claude_cli import JSON_ONLY, ClaudeError, ask_json, parse_json

DEFAULT_API_MODEL = "claude-opus-5-5"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class AiSettings:
    provider: str = "claude-cli"
    model: str = ""            # api: Claude model id; opencode: provider/model; claude-cli: unused
    api_key: str | None = None  # Anthropic API key. Memory only: never saved, never returned.


def _clean(text: str) -> str:
    return ANSI.sub("", text)


def ask_api(prompt: str, api_key: str | None = None, model: str = "", timeout: int = 180, client=None) -> dict:
    """Ask the Anthropic API. `client` is injectable for tests."""
    import anthropic

    secret = api_key or ""
    mask = lambda s: str(s).replace(secret, "***") if secret else str(s)
    try:
        client = client or anthropic.Anthropic(api_key=api_key or None, timeout=timeout)
        msg = client.messages.create(
            model=model or DEFAULT_API_MODEL, max_tokens=16000,
            messages=[{"role": "user", "content": prompt + JSON_ONLY}])
    except TypeError:  # the SDK found no credentials at all
        raise ClaudeError("No Anthropic API key found. Paste one in the AI settings or set ANTHROPIC_API_KEY.") from None
    except anthropic.AuthenticationError:
        raise ClaudeError("The Anthropic API key was rejected. Check it in the AI settings.") from None
    except anthropic.PermissionDeniedError:
        raise ClaudeError("The Anthropic API key is not allowed to use this model.") from None
    except anthropic.NotFoundError:
        raise ClaudeError(f"The model '{model or DEFAULT_API_MODEL}' was not found. Check the model name.") from None
    except anthropic.RateLimitError:
        raise ClaudeError("Anthropic API rate limit reached. Wait a moment and retry.") from None
    except anthropic.APITimeoutError:
        raise ClaudeError(f"The Anthropic API timed out after {timeout}s.") from None
    except anthropic.APIConnectionError:
        raise ClaudeError("Could not reach the Anthropic API. Check the network.") from None
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Anthropic API error {e.status_code}: {mask(getattr(e, 'message', e))}") from None
    if msg.stop_reason == "refusal":
        raise ClaudeError("The model declined this request.")
    if msg.stop_reason == "max_tokens":
        raise ClaudeError("The model's answer was cut off. Try again, or use fewer or smaller source folders.")
    return parse_json("".join(b.text for b in msg.content if b.type == "text"))


def ask_opencode(prompt: str, model: str = "", timeout: int = 180, runner: Callable = subprocess.run) -> dict:
    """Ask opencode (`opencode run`). The prompt travels as an attached file, and opencode runs in an
    empty scratch folder, so it can neither hit the argument-size limit nor touch the project."""
    if model and not re.fullmatch(r"[A-Za-z0-9][\w.\-]*/[\w.\-:/]+", model):
        raise ClaudeError("opencode model must look like provider/model, for example anthropic/claude-sonnet-5-5.")
    with tempfile.TemporaryDirectory(prefix="migration-assistant-") as scratch:
        request = Path(scratch) / "request.md"
        request.write_text(prompt + JSON_ONLY)
        cmd = ["opencode", "run", "-f", str(request)]
        if model:
            cmd += ["-m", model]
        cmd.append("Follow the instructions in the attached file. Answer with the JSON object only.")
        try:
            proc = runner(cmd, cwd=scratch, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ClaudeError(f"opencode timed out after {timeout}s") from None
        except FileNotFoundError:
            raise ClaudeError("opencode not found on PATH") from None
    if proc.returncode != 0:
        lines = [ln.strip() for ln in _clean(proc.stderr or proc.stdout).splitlines() if ln.strip() and not ln.startswith(">")]
        raise ClaudeError(f"opencode failed: {lines[-1] if lines else 'unknown error'}")
    return parse_json(_clean(proc.stdout))


BACKENDS: dict[str, Callable[[str, AiSettings], dict]] = {
    "claude-cli": lambda prompt, s: ask_json(prompt, model=s.model),
    "anthropic-api": lambda prompt, s: ask_api(prompt, api_key=s.api_key, model=s.model),
    "opencode": lambda prompt, s: ask_opencode(prompt, model=s.model),
}


def make_ask(settings: AiSettings, backends: dict | None = None) -> Callable[[str], dict]:
    """The `ask(prompt) -> dict` function for the provider chosen in `settings`."""
    backends = backends if backends is not None else BACKENDS

    def ask(prompt: str) -> dict:
        backend = backends.get(settings.provider)
        if backend is None:
            raise ClaudeError(f"Unknown AI provider '{settings.provider}'.")
        return backend(prompt, settings)

    return ask


def available_providers(settings: AiSettings, which: Callable = shutil.which) -> list[dict]:
    """What the UI shows for each provider. Never includes the key."""
    env_key = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    return [
        {"id": "claude-cli", "label": "Claude Code (CLI)", "available": bool(which("claude")),
         "detail": "uses your Claude Code login" if which("claude") else "`claude` not found on PATH"},
        {"id": "anthropic-api", "label": "Anthropic API", "available": True,
         "detail": "key set" if settings.api_key else "key from ANTHROPIC_API_KEY" if env_key else "no key yet: paste one below"},
        {"id": "opencode", "label": "opencode", "available": bool(which("opencode")),
         "detail": "uses your opencode setup" if which("opencode") else "`opencode` not found on PATH"},
    ]


# ---- model lists for the settings dropdowns

CLI_MODELS = [("", "Default (your Claude Code setting)"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")]
# Used when the Models API cannot be reached (no key yet, offline).
API_FALLBACK_MODELS = [("claude-fable-5-2", "Claude Fable 5.2"), ("claude-opus-5-5", "Claude Opus 5.5"),
                       ("claude-sonnet-5-5", "Claude Sonnet 5.5"), ("claude-haiku-5-5", "Claude Haiku 5.5")]
OPENCODE_LINE = re.compile(r"[A-Za-z0-9][\w.\-]*/[\w.\-:/]+")


def _entry(model_id: str, label: str, group: str = "") -> dict:
    return {"id": model_id, "label": label, "group": group}


def list_models(provider: str, settings: AiSettings, client=None, runner: Callable = subprocess.run, timeout: int = 30) -> dict:
    """Models to offer for a provider: {"models": [{id, label, group}], "source": "live"|"fallback"|"static", "error"?}.
    The first entry has id "" and means the provider's own default."""
    if provider == "claude-cli":
        return {"models": [_entry(i, label) for i, label in CLI_MODELS], "source": "static"}
    if provider == "anthropic-api":
        default = _entry("", f"Default ({DEFAULT_API_MODEL})")
        try:
            import anthropic
            client = client or anthropic.Anthropic(api_key=settings.api_key or None, timeout=timeout)
            live = [_entry(m.id, f"{m.display_name} ({m.id})") for m in client.models.list(limit=100) if str(m.id).startswith("claude-")]
            if live:
                return {"models": [default] + live, "source": "live"}
        except Exception:  # no key, offline, or an error: fall through to the built-in list
            pass
        return {"models": [default] + [_entry(i, f"{label} ({i})") for i, label in API_FALLBACK_MODELS], "source": "fallback"}
    if provider == "opencode":
        default = _entry("", "Default (opencode's own setting)", "default")
        try:
            proc = runner(["opencode", "models"], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return {"models": [default], "source": "fallback", "error": "opencode not found on PATH"}
        except subprocess.TimeoutExpired:
            return {"models": [default], "source": "fallback", "error": "opencode took too long to list its models"}
        if proc.returncode != 0:
            return {"models": [default], "source": "fallback", "error": "opencode could not list its models"}
        seen, models = set(), [default]
        for line in _clean(proc.stdout).splitlines():
            line = line.strip()
            if OPENCODE_LINE.fullmatch(line) and line not in seen:
                seen.add(line)
                models.append(_entry(line, line.split("/", 1)[1], line.split("/", 1)[0]))
        return {"models": models, "source": "live"}
    raise ClaudeError(f"Unknown AI provider '{provider}'.")
