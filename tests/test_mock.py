import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from migration_assistant import app as app_module
from migration_assistant.app import create_app
from migration_assistant.assess import assess
from migration_assistant.azure_discovery import DiscoveryError
from migration_assistant.claude_cli import ClaudeError
from migration_assistant.dependencies import add_dependencies
from migration_assistant.envfile import parse_env
from migration_assistant.mock import (FIXTURE, MOCK_PROVIDER, PARTS, MockAI, MockAzure, MockHttp, MockResponse,
                                      describe, mock_overrides, mock_parts)

mock_ask = MockAI().ask
mock_discover = MockAzure().discover
from migration_assistant.plan import build_plans, select_sources
from migration_assistant.prompt import TASKS, Prompt

ROOT = Path(__file__).resolve().parent.parent
RG = "hackaton-2026-rg"


def make(*parts, **extra):
    return TestClient(create_app(**{**mock_overrides(parts), "state_file": None, **extra}))


@pytest.fixture
def client():
    return make(*PARTS)


def run_to_plan(client, dirs=()):
    client.post("/api/discover", data={"resource_group": RG})
    assessed = client.post("/api/assess").json()
    planned = client.post("/api/plan", data={"source_dirs": [str(d) for d in dirs]}).json()
    return assessed, planned


# ---- switches

@pytest.mark.parametrize("env, parts", [
    ({}, set()),
    ({"MOCK_MODE": "1"}, {"azure", "ai", "leaseweb"}),
    ({"MOCK_AI": "true", "MOCK_LEASEWEB": "yes"}, {"ai", "leaseweb"}),
    ({"MOCK_AZURE": "1", "MOCK_AI": "0"}, {"azure"}),
])
def test_each_part_has_its_own_switch(env, parts):
    assert mock_parts(env) == parts


def test_the_notice_says_what_is_mocked_and_what_is_real():
    assert "Real: Azure." in describe({"ai", "leaseweb"})
    assert "Nothing leaves this machine" in describe(set(PARTS))


def test_mock_switches_can_come_from_the_env_file(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(app_module, "create_app", lambda **kw: seen.update(kw) or "app")
    env = tmp_path / ".env"
    env.write_text("MOCK_AI=1      # canned answers\nMOCK_LEASEWEB=1\n")
    app_module._app_from_env(env)
    assert isinstance(seen["ask"].__self__, MockAI) and isinstance(seen["http"], MockHttp) and "discover" not in seen
    assert seen["notice"] == describe({"ai", "leaseweb"})


def test_no_switch_means_the_real_app(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(app_module, "create_app", lambda **kw: seen.update(kw) or "app")
    app_module._app_from_env(tmp_path / "missing.env")
    assert seen == {}


def test_importing_the_app_reads_no_env_file_and_builds_nothing(tmp_path):
    """A developer's .env must not leak into whatever imports the module (the tests do)."""
    code = ("import os, migration_assistant.app as a; "
            "print(sorted(k for k in os.environ if k.startswith('MOCK_')), '_built' in vars(a) and bool(a._built))")
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOCK_")}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[] False"


def test_the_example_env_file_switches_work_when_uncommented():
    lines = [l[2:] for l in (ROOT / ".env.example").read_text().splitlines() if l.startswith("# MOCK_")]
    values = parse_env("\n".join(lines))
    assert mock_parts(values) == set(PARTS) and values["MOCK_AZURE"] == "1"


def test_the_start_scripts_offer_every_switch():
    sh, ps1 = (ROOT / "start.sh").read_text(), (ROOT / "start.ps1").read_text()
    for flag in ("--mock)", "--mock-azure)", "--mock-ai)", "--mock-leaseweb)"):
        assert flag in sh
    for switch in ("$Mock,", "$MockAzure", "$MockAi", "$MockLeaseweb"):
        assert switch in ps1


# ---- Azure

def test_the_fixture_is_hackaton_2026_rg_without_private_data():
    text = FIXTURE.read_text()
    data = json.loads(text)
    assert data["resource_group"] == RG and len(data["resources"]) == 33
    assert "@" not in text.replace("someone@example.com", "") and "systemData" not in text
    assert all("/subscriptions/00000000-0000-4000-8000-000000000000/" in r["id"] for r in data["resources"])


def test_the_fixture_generator_is_in_the_repo():
    script = (ROOT / "scripts" / "make_mock_fixture.py").read_text()
    assert "hackaton-2026-rg.json" in script and "Refusing to write" in script


def test_mock_azure_only_knows_its_resource_group():
    assert len(mock_discover(RG)) == 33
    with pytest.raises(DiscoveryError):
        mock_discover("some-other-rg")


def test_only_azure_mocked_keeps_the_real_ai_and_no_key():
    c = make("azure", ask=lambda p: {"ok": True})
    assert c.get("/api/azure").json()["signed_in"] is True
    assert c.get("/api/resource-groups").json()["groups"][0]["name"] == RG
    assert "mock" not in {p["id"] for p in c.get("/api/ai").json()["providers"]}
    state = c.get("/api/state").json()
    assert state["notice"].startswith("Mock mode: Azure") and state["api_key_set"] is False and not state["fake_leaseweb"]


# ---- AI

def test_every_ai_request_the_app_makes_is_tagged_and_answered():
    """Run each AI step with a recorder: every prompt must be a tagged Prompt the mock can answer."""
    seen = []

    def record(prompt):
        assert isinstance(prompt, Prompt), f"untagged prompt: {str(prompt)[:80]}"
        seen.append(prompt.task)
        return mock_ask(prompt)

    resources = mock_discover(RG)
    assessments = assess(resources, ask=record)
    add_dependencies(resources, assessments, ask=record)
    items = [(a, next(r for r in resources if r.name == a.resource_name)) for a in assessments if a.route == "rebuild"]
    source = {f"f{i}.py": "import x\n" * 3 for i in range(5)}
    select_sources(items, source, ask=record)
    build_plans(items, source, ask=record)
    TestClient(create_app(ask=record, state_file=None)).post("/api/ai/test")
    assert set(seen) == set(TASKS)


def test_the_mock_ai_refuses_requests_it_does_not_know():
    with pytest.raises(ClaudeError, match="no answer"):
        mock_ask("a plain string prompt")
    with pytest.raises(ValueError):
        Prompt("x", "not-a-task")


def test_only_ai_mocked_uses_the_real_azure_helpers():
    calls = []
    c = make("ai", discover=lambda rg: calls.append(rg) or mock_discover(RG), azure_status_fn=lambda: {"signed_in": False})
    assert c.get("/api/azure").json()["signed_in"] is False  # the real check, not the mock one
    ai = c.get("/api/ai").json()
    assert ai["provider"] == "mock" and [p["id"] for p in ai["providers"]] == ["mock"] and ai["problem"] == ""
    assert c.post("/api/ai/test").json() == {"ok": True}
    c.post("/api/discover", data={"resource_group": RG})
    assert calls == [RG]


def test_the_mock_ai_gives_hackaton_answers(client):
    assessed, planned = run_to_plan(client, [ROOT / "demo_app" / "api", ROOT / "demo_app" / "worker"])
    by = {a["resource_name"]: a for a in assessed["assessments"]}
    assert assessed["message"] == ""
    assert by["ca-hack2026-r8l54-api"]["route"] == "rebuild" and "Caddy" in by["ca-hack2026-r8l54-api"]["target"]
    assert by["pe-hack2026-r8l54-app-queue"]["route"] == "included"
    needs = lambda name: {d["name"] for d in by[name]["dependencies"]}
    assert {"kv-hack2026-r8l54", "cosmos-hack2026-r8l54", "sthack2026r8l54app"} <= needs("ca-hack2026-r8l54-api")
    assert {"sthack2026r8l54func", "sthack2026r8l54app", "cosmos-hack2026-r8l54"} <= needs("func-hack2026-r8l54-worker")
    assert "kv-hack2026-r8l54" not in needs("func-hack2026-r8l54-worker")  # the worker never reads the vault
    plans = planned["plans"]
    assert {p["resource_name"] for p in plans} == {n for n, a in by.items() if a["route"] == "rebuild"}
    assert all(p["steps"] and not any(w.startswith("Plan failed") for w in p["warnings"]) for p in plans)
    changes = [c for p in plans for c in p["code_changes"]]
    assert changes and all(c["check"] == "applies" for c in changes)


def test_mock_code_changes_apply_to_the_code_they_were_made_for(client, tmp_path):
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "store.py").write_text("from azure.cosmos import CosmosClient\n\nclient = CosmosClient(URL)\n", newline="\n")
    _, planned = run_to_plan(client, [tmp_path / "svc"])
    cosmos = next(p for p in planned["plans"] if p["resource_name"] == "cosmos-hack2026-r8l54")
    assert [(c["file"], c["check"]) for c in cosmos["code_changes"]] == [("svc/store.py", "applies")]


# ---- Leaseweb

def test_mock_leaseweb_starts_with_a_working_mock_key():
    c = make("leaseweb", ask=lambda p: {})
    state = c.get("/api/state").json()
    assert state["api_key_set"] is True and state["key_verified"] is True and state["fake_leaseweb"] is True
    assert c.post("/api/key/test").json()["key_verified"] is True
    assert c.get("/api/migrate/options").json()["source"] == "live"
    assert 'data-fake-leaseweb="1"' in c.get("/").text


def test_a_preset_key_needs_a_fake_client():
    with pytest.raises(ValueError):
        create_app(state_file=None, api_key="made-up")
    with pytest.raises(ValueError):
        create_app(state_file=None, api_key="made-up", http=object())


def test_live_runs_and_teardown_go_to_the_fake_api(client):
    run_to_plan(client)
    run = client.post("/api/migrate").json()
    assert run["live"] is True and any(r.get("sent") and r.get("status") == 201 for r in run["results"])
    assert "mock-leaseweb-key" not in json.dumps(client.get("/api/state").json())
    if run["created"]:
        assert client.post("/api/migrate/teardown").json()["created"] == []


def test_the_fake_api_only_answers_for_leaseweb():
    class Real:
        def request(self, method, url, **kw):
            return MockResponse(299, {"url": url})
    assert MockHttp(Real()).request("GET", "https://prices.azure.com/api/retail/prices").status_code == 299
    assert MockHttp(Real()).request("GET", "https://api.leaseweb.com/publicCloud/v1/regions").status_code == 200
    assert MockHttp().request("GET", "https://prices.azure.com/api/retail/prices").status_code == 404
    assert MockHttp().request("GET", "https://api.leaseweb.com.evil.example/x").status_code == 404


# ---- mock results are never mistaken for real ones

def test_every_export_says_it_was_made_in_mock_mode(client):
    run_to_plan(client, [ROOT / "demo_app" / "api"])
    notice = describe(set(PARTS))
    plan = client.get("/export")
    assert notice in plan.text
    for path, name in (("/export/calls.json", "mock-leaseweb-calls.json"), ("/export/calls.sh", "mock-leaseweb-calls.sh"),
                       ("/export/patch", "mock-migration-code-changes.patch")):
        r = client.get(path)
        assert name in r.headers["content-disposition"] and r.headers["x-mock-notice"] == notice
    assert client.get("/export/calls.sh").text.splitlines()[:2] == ["#!/usr/bin/env bash", f"# {notice}"]
    assert client.get("/export/patch").text.startswith(f"# {notice}\n")
    assert "mock" in client.get("/").text and notice in client.get("/").text


def test_the_real_app_mocks_nothing_and_labels_nothing():
    real = TestClient(create_app(ask=lambda p: {}, state_file=None))
    state = real.get("/api/state").json()
    assert state["notice"] == "" and state["fake_leaseweb"] is False and state["api_key_set"] is False
    assert "mock-banner" not in real.get("/").text
    r = real.get("/export/calls.json")
    assert "mock-" not in r.headers["content-disposition"] and "x-mock-notice" not in r.headers
    assert [p for p in real.get("/api/ai").json()["providers"] if p == MOCK_PROVIDER] == []


# ---- the fake Leaseweb API: follows the specs and keeps what it creates

from migration_assistant.leaseweb_ops import load_responses, schema_errors  # noqa: E402
from migration_assistant.mock import FakeLeaseweb  # noqa: E402

LAUNCH = {"region": "eu-west-3", "type": "lsw.c3.large", "imageId": "UBUNTU_22_04_64BIT", "contractType": "HOURLY",
          "rootDiskSize": 50, "rootDiskStorageType": "CENTRAL", "reference": "api"}


def test_the_schema_check_catches_a_wrong_shape():
    spec = load_responses()["launchInstance"]
    assert schema_errors(spec["example"], spec["schema"], spec["base"]) == []
    assert schema_errors({**spec["example"], "state": "FLYING"}, spec["schema"], spec["base"])
    assert schema_errors({**spec["example"], "rootDiskSize": "big"}, spec["schema"], spec["base"])
    assert schema_errors({k: v for k, v in spec["example"].items() if k != "id"}, spec["schema"], spec["base"])


def test_every_fake_answer_matches_the_spec():
    """Drive the whole lifecycle and check each answer against its operation's response schema and status."""
    api, specs = FakeLeaseweb(), load_responses()
    checked = []

    def call(method, path, body=None):
        op, _ = api.route(method, path)
        status, payload = api.handle(method, path, body)
        assert status == specs[op]["status"], (op, status)
        if payload is not None and specs[op]["schema"]:
            assert schema_errors(payload, specs[op]["schema"], specs[op]["base"]) == [], op
        checked.append(op)
        return payload

    inst = call("POST", "/publicCloud/v1/instances", LAUNCH)
    call("GET", f"/publicCloud/v1/instances/{inst['id']}")
    call("GET", "/publicCloud/v1/instances")
    group = call("POST", "/publicCloud/v1/securityGroups", {"name": "apps"})
    call("POST", f"/publicCloud/v1/securityGroups/{group['id']}/authorizeFirewallRules", {"rules": []})
    net = call("POST", "/bareMetals/v2/privateNetworks", {"name": "vnet-hack"})
    call("PUT", f"/publicCloud/v1/instances/{inst['id']}/addToPrivateNetwork", {})
    call("POST", "/objectStorage/v1/objectStorages/os-1/buckets", {"name": "product-images"})
    call("GET", "/publicCloud/v1/regions")
    call("GET", "/publicCloud/v1/instanceTypes")
    call("DELETE", "/objectStorage/v1/objectStorages/os-1/buckets/product-images")
    call("DELETE", f"/bareMetals/v2/privateNetworks/{net['id']}")
    call("DELETE", f"/publicCloud/v1/securityGroups/{group['id']}")
    call("DELETE", f"/publicCloud/v1/instances/{inst['id']}")
    assert len(set(checked)) == 14


def test_the_fake_api_keeps_state_like_leaseweb():
    api = FakeLeaseweb()
    _, inst = api.handle("POST", "/publicCloud/v1/instances", LAUNCH)
    assert inst["state"] == "CREATING" and inst["reference"] == "api" and inst["image"]["id"] == "UBUNTU_22_04_64BIT"
    assert api.handle("PUT", f"/publicCloud/v1/instances/{inst['id']}/addToPrivateNetwork", {})[0] == 409  # not up yet
    _, listed = api.handle("GET", "/publicCloud/v1/instances")
    assert [i["id"] for i in listed["instances"]] == [inst["id"]] and listed["_metadata"]["totalCount"] == 1
    assert api.handle("GET", f"/publicCloud/v1/instances/{inst['id']}")[1]["state"] == "RUNNING"
    assert api.handle("PUT", f"/publicCloud/v1/instances/{inst['id']}/addToPrivateNetwork", {})[0] == 202
    assert api.handle("DELETE", f"/publicCloud/v1/instances/{inst['id']}")[0] == 200
    assert api.handle("DELETE", f"/publicCloud/v1/instances/{inst['id']}")[0] == 404  # already gone
    assert api.handle("GET", f"/publicCloud/v1/instances/{inst['id']}")[0] == 404
    assert api.handle("POST", "/objectStorage/v1/objectStorages/os-1/buckets", {"name": "b"})[0] == 201
    assert api.handle("POST", "/objectStorage/v1/objectStorages/os-1/buckets", {"name": "b"})[0] == 409
    assert api.handle("GET", "/publicCloud/v1/notAnOperation")[0] == 404


def test_an_app_run_leaves_the_fake_api_clean_after_teardown(client):
    run_to_plan(client)
    run = client.post("/api/migrate").json()
    launched = [r for r in run["results"] if r["operation_id"] == "launchInstance" and r.get("status") == 201]
    listed = client.get("/api/state").json()["created"]
    assert launched and len([c for c in listed if c["operation_id"] == "launchInstance"]) == len(launched)
    assert client.post("/api/migrate/teardown").json()["created"] == []


# ---- settings, the environment and delays

def test_the_subscription_is_shared_by_real_and_mock_runs(tmp_path):
    subs = lambda: [{"id": "sub-1", "name": "Hackathon", "is_default": False}]
    real = TestClient(create_app(state_file=tmp_path / "state.json", ask=lambda p: {}, subscriptions_fn=subs))
    real.post("/api/azure/subscription", data={"subscription_id": "sub-1"})
    mock_ai_only = TestClient(create_app(**{**mock_overrides({"ai"}), "state_file": tmp_path / "mock-state.json",
                                            "subscriptions_fn": subs}))
    assert mock_ai_only.get("/api/azure/subscriptions").json()["selected"] == "sub-1"
    mock_azure = TestClient(create_app(**{**mock_overrides({"azure"}), "state_file": tmp_path / "mock-state.json"}))
    mock_azure.post("/api/azure/subscription", data={"subscription_id": "00000000-0000-4000-8000-000000000000"})
    assert json.loads((tmp_path / "settings.json").read_text())["subscription"] == "sub-1"  # the fake one is not kept
    real.post("/api/reset")
    assert real.get("/api/azure/subscriptions").json()["selected"] == "sub-1"


def test_the_mock_package_never_reads_the_environment():
    for f in (ROOT / "migration_assistant" / "mock").glob("*.py"):
        assert "os.environ" not in f.read_text(), f.name


def test_the_delay_is_passed_in(monkeypatch):
    from migration_assistant.mock import _pause, delay_from
    waits = []
    monkeypatch.setattr(_pause.time, "sleep", waits.append)
    assert delay_from({"MOCK_DELAY": "0.5"}) == 0.5 and delay_from({}) == 1.0 and delay_from({"MOCK_DELAY": "x"}) == 1.0
    MockAI(delay=2).ask(Prompt("ok?", "test"))
    MockAI(delay=0).ask(Prompt("ok?", "test"))
    assert waits == [0.6]
