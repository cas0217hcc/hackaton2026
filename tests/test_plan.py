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


def test_steps_parsed():
    ask = lambda p: {"proposal": "Run Vault.", "steps": ["Create SG", "Launch VM"], "lw_operations": [], "code_changes": []}
    assert build_plan(KV, KV_RES, {}, ask=ask).steps == ["Create SG", "Launch VM"]


def test_missing_steps_defaults_to_empty():
    assert build_plan(KV, KV_RES, {}, ask=answer()).steps == []


from migration_assistant.plan import read_sources


def test_read_sources_combines_folders_with_prefix(tmp_path: Path):
    a, b = tmp_path / "api", tmp_path / "web"
    a.mkdir(); b.mkdir()
    (a / "x.py").write_text("1")
    (b / "x.py").write_text("2")
    assert read_sources([a, b]) == {"api/x.py": "1", "web/x.py": "2"}


def test_read_sources_same_folder_name_stays_distinct(tmp_path: Path):
    a, b = tmp_path / "one" / "app", tmp_path / "two" / "app"
    a.mkdir(parents=True); b.mkdir(parents=True)
    (a / "x.py").write_text("1")
    (b / "x.py").write_text("2")
    got = read_sources([a, b])
    assert len(got) == 2 and set(got.values()) == {"1", "2"}


def test_read_sources_empty_list():
    assert read_sources([]) == {}


import time

from migration_assistant.plan import FAILED_PREFIX, build_plans


def items(n):
    return [(Assessment(f"r{i}", "rebuild", "T", "why", []), Resource(f"/x/r{i}", f"r{i}", "Microsoft.Foo/bars", "westeurope"))
            for i in range(n)]


def slow_ask(prompt):
    time.sleep(0.3)
    return {"proposal": "ok", "lw_operations": [], "code_changes": []}


def test_build_plans_runs_in_parallel_and_keeps_order():
    start = time.time()
    plans = build_plans(items(4), {}, ask=slow_ask, ops={}, workers=4)
    assert time.time() - start < 0.9  # serial would take 1.2s
    assert [p.resource_name for p in plans] == ["r0", "r1", "r2", "r3"]


def test_build_plans_partial_failure_keeps_the_rest():
    def ask(prompt):
        if "r1" in prompt:
            raise ClaudeError("claude timed out after 180s")
        return {"proposal": "ok", "lw_operations": [], "code_changes": []}
    plans = build_plans(items(3), {}, ask=ask, workers=3)
    assert [p.proposal for p in plans] == ["ok", "", "ok"]
    assert plans[1].warnings[0].startswith(FAILED_PREFIX) and "timed out" in plans[1].warnings[0]


def test_build_plans_reports_progress_for_every_resource():
    events = []
    build_plans(items(3), {}, ask=slow_ask, workers=3, on_progress=lambda name, status: events.append((name, status)))
    for name in ("r0", "r1", "r2"):
        assert (name, "running") in events and (name, "done") in events


def test_prompt_tells_the_ai_to_list_only_files_that_change():
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return {"proposal": "x", "lw_operations": [], "code_changes": []}
    build_plan(KV, KV_RES, {"a.py": "x"}, ask=ask, ops={})
    assert "Only list files that need a change" in seen[0]
