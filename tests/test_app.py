import pytest
from fastapi.testclient import TestClient

from migration_assistant.azure_discovery import DiscoveryError
from migration_assistant.claude_cli import ClaudeError
from migration_assistant.app import create_app
from migration_assistant.models import Resource

VM = Resource("/x/vm", "vm-web-01", "Microsoft.Compute/virtualMachines", "westeurope")
KV = Resource("/x/kv", "kv-hack", "Microsoft.KeyVault/vaults", "westeurope")


def plan_answer(prompt):
    return {"proposal": "Run Vault.", "lw_operations": ["launchInstance"],
            "code_changes": [{"file": "secrets.py", "summary": "use hvac", "diff": "-a\n+b"}]}


def client(resources, ask=plan_answer):
    return TestClient(create_app(discover=lambda rg: resources, ask=ask, state_file=None))


def run_to_assess(c):
    assert c.post("/api/discover", data={"resource_group": "rg"}).status_code == 200
    assert c.post("/api/assess").status_code == 200


def test_full_flow():
    c = client([VM, KV])
    run_to_assess(c)
    assert c.post("/api/plan", data={"source_dir": ""}).status_code == 200
    mig = c.post("/api/migrate")
    assert mig.status_code == 200 and mig.json()["calls"][0]["operation_id"] == "launchInstance"
    assert "kv-hack" in c.get("/export").text


def test_discover_error_returns_502_message():
    def fail(rg):
        raise DiscoveryError("Please run 'az login'")
    c = TestClient(create_app(discover=fail, ask=plan_answer, state_file=None))
    r = c.post("/api/discover", data={"resource_group": "rg"})
    assert r.status_code == 502 and "az login" in r.json()["error"]


def test_plan_when_all_direct_says_nothing_to_plan():
    c = client([VM])
    run_to_assess(c)
    r = c.post("/api/plan", data={"source_dir": ""})
    assert r.status_code == 200 and r.json()["plans"] == [] and "nothing to plan" in r.json()["message"].lower()


def test_claude_error_returns_502_message():
    def fail(prompt):
        raise ClaudeError("claude timed out after 180s")
    c = client([VM, KV], ask=fail)
    run_to_assess(c)
    r = c.post("/api/plan", data={"source_dir": ""})
    assert r.status_code == 502 and "timed out" in r.json()["error"]


def persistent_client(resources, state_file, ask=plan_answer):
    return TestClient(create_app(discover=lambda rg: resources, ask=ask, state_file=state_file))


def test_state_empty_by_default(tmp_path):
    c = persistent_client([VM, KV], tmp_path / "s.json")
    s = c.get("/api/state").json()
    assert s["resources"] == [] and s["assessments"] == [] and s["plans"] == [] and s["calls"] == []


def test_state_survives_app_restart(tmp_path):
    f = tmp_path / "s.json"
    c = persistent_client([VM, KV], f)
    c.post("/api/discover", data={"resource_group": "my-rg"})
    c.post("/api/assess")
    c.post("/api/plan", data={"source_dir": ""})
    c.post("/api/migrate")
    s = persistent_client([], f).get("/api/state").json()
    assert s["resource_group"] == "my-rg"
    assert [r["name"] for r in s["resources"]] == ["vm-web-01", "kv-hack"]
    assert {a["route"] for a in s["assessments"]} == {"direct", "rebuild"}
    assert s["plans"][0]["code_changes"][0]["file"] == "secrets.py"
    assert s["calls"][0]["operation_id"] == "launchInstance"


def test_restored_state_allows_export_and_replan(tmp_path):
    f = tmp_path / "s.json"
    c = persistent_client([VM, KV], f)
    run_to_assess(c)
    c2 = persistent_client([], f)
    assert "kv-hack" in c2.get("/export").text
    assert c2.post("/api/plan", data={"source_dir": ""}).status_code == 200


def test_corrupt_state_file_is_ignored(tmp_path):
    f = tmp_path / "s.json"
    f.write_text("{not json")
    s = persistent_client([VM], f).get("/api/state").json()
    assert s["resources"] == []


def test_rediscover_clears_downstream_state(tmp_path):
    c = persistent_client([VM, KV], tmp_path / "s.json")
    run_to_assess(c)
    c.post("/api/discover", data={"resource_group": "rg"})
    s = c.get("/api/state").json()
    assert s["assessments"] == [] and s["plans"] == [] and s["calls"] == []
