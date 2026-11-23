from pathlib import Path

from migration_assistant.envfile import ENV_FILE, load_env, parse_env

ROOT = Path(__file__).resolve().parent.parent


def test_parses_comments_quotes_and_export():
    text = """
# a comment
MOCK_MODE=1
export AI_PROVIDER = anthropic-api
AI_MODEL="claude-sonnet-5-5"
ALLOWED_HOSTS='a.lan,b.lan'
MOCK_DELAY=0   # no pauses
EMPTY=
not a setting
"""
    assert parse_env(text) == {"MOCK_MODE": "1", "AI_PROVIDER": "anthropic-api", "AI_MODEL": "claude-sonnet-5-5",
                               "ALLOWED_HOSTS": "a.lan,b.lan", "MOCK_DELAY": "0", "EMPTY": ""}


def test_the_environment_wins_over_the_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("MOCK_MODE=1\nAI_MODEL=opus\n")
    environ = {"MOCK_MODE": "0"}
    assert load_env(f, environ) == {"AI_MODEL": "opus"}
    assert environ == {"MOCK_MODE": "0", "AI_MODEL": "opus"}


def test_a_missing_file_changes_nothing(tmp_path):
    environ = {}
    assert load_env(tmp_path / "nope.env", environ) == {} and environ == {}


def test_a_file_saved_with_a_bom_still_reads(tmp_path):
    f = tmp_path / ".env"
    f.write_bytes("﻿MOCK_MODE=1\n".encode("utf-8"))
    assert parse_env(f.read_text(encoding="utf-8-sig")) == {"MOCK_MODE": "1"}
    assert load_env(f, {}) == {"MOCK_MODE": "1"}


def test_the_env_file_is_in_the_repo_root_and_git_ignored_while_the_example_is_not():
    assert ENV_FILE == ROOT / ".env"
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignored and ".env.example" not in ignored
    example = parse_env("\n".join(l.lstrip("# ") for l in (ROOT / ".env.example").read_text().splitlines()))
    assert {"MOCK_MODE", "MOCK_DELAY", "AI_PROVIDER", "ALLOWED_HOSTS"} <= set(example)
