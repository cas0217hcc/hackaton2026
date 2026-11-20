from pathlib import Path

from migration_assistant.models import Assessment, Resource
from migration_assistant.plan import build_plan, read_source

KV = Assessment("kv", "rebuild", "Vault on a Public Cloud instance", "no managed secrets", ["launchInstance"])
KV_RES = Resource("/x/kv", "kv", "Microsoft.KeyVault/vaults", "westeurope")


def answer(ops=("launchInstance",), changes=()):
    return lambda prompt: {"proposal": "Run Vault.", "lw_operations": list(ops), "code_changes": list(changes)}


def test_read_source_python_only(tmp_path: Path):
    (tmp_path / "a.py").write_text("print(1)")
    (tmp_path / "b.txt").write_text("nope")
    assert read_source(tmp_path) == {"a.py": "print(1)"}


def test_read_source_missing_folder_returns_empty(tmp_path: Path):
    assert read_source(tmp_path / "nope") == {}
    assert read_source(None) == {}


def test_plan_without_source_has_no_code_changes_and_notes_it():
    plan = build_plan(KV, KV_RES, {}, ask=answer())
    assert plan.code_changes == []
    assert any("no code to analyse" in w for w in plan.warnings)


def test_unknown_operation_dropped_with_warning():
    plan = build_plan(KV, KV_RES, {}, ask=answer(ops=["createObjectStorageBucket", "launchQuantumVault"]))
    assert plan.lw_operations == ["createObjectStorageBucket"]
    assert any("launchQuantumVault" in w for w in plan.warnings)


def test_code_changes_parsed():
    change = {"file": "secrets.py", "summary": "use hvac", "diff": "-a\n+b"}
    plan = build_plan(KV, KV_RES, {"secrets.py": "x"}, ask=answer(changes=[change]))
    assert plan.code_changes[0].file == "secrets.py"
    assert plan.code_changes[0].diff == "-a\n+b"
    assert not any("no code" in w for w in plan.warnings)


import pytest

from migration_assistant.claude_cli import ClaudeError


def test_malformed_code_change_raises_claude_error():
    with pytest.raises(ClaudeError):
        build_plan(KV, KV_RES, {"a.py": "x"}, ask=answer(changes=[{"file": "a.py"}]))
