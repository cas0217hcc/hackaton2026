import subprocess

import pytest

from migration_assistant.claude_cli import ClaudeError, ask_json


def fake(stdout="", code=0, exc=None):
    def run(cmd, **kw):
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, code, stdout, "boom" if code else "")
    return run


def test_plain_json():
    assert ask_json("p", runner=fake('{"a": 1}')) == {"a": 1}


def test_fenced_json():
    assert ask_json("p", runner=fake('```json\n{"a": 1}\n```')) == {"a": 1}


def test_non_json_raises():
    with pytest.raises(ClaudeError):
        ask_json("p", runner=fake("sorry, no"))


def test_timeout_raises():
    with pytest.raises(ClaudeError, match="timed out"):
        ask_json("p", runner=fake(exc=subprocess.TimeoutExpired("claude", 1)))


def test_nonzero_exit_raises():
    with pytest.raises(ClaudeError, match="boom"):
        ask_json("p", runner=fake(code=1))


def test_json_surrounded_by_prose():
    out = 'Here is the plan:\n{"a": {"b": 2}}\nHope that helps.'
    assert ask_json("p", runner=fake(out)) == {"a": {"b": 2}}
