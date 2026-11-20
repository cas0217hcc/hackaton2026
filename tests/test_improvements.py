"""Tests for storage routing, extra rules, rebuild automation, readiness, teardown, exports, costs,
data steps and diff checks."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from migration_assistant.app import create_app
from migration_assistant.assess import assess
from migration_assistant.azure_discovery import list_resources
from migration_assistant.costs import azure_vm_prices, leaseweb_prices, spec_prices
from migration_assistant.datamove import data_steps
from migration_assistant.diffcheck import check_change, check_plans, folder_prefixes, patch_text
from migration_assistant.dryrun import (LeasewebExecutor, build_calls, curl_script, path_params, run_calls,
                                        teardown_calls)
from migration_assistant.leaseweb_ops import load_operations
from migration_assistant.models import Assessment, CodeChange, DryRunCall, Plan, Resource
from migration_assistant.plan import select_sources

OPS = load_operations()
KEY = "sk-secret-123"


def res(name, type_, props=None, location="westeurope"):
    return Resource(f"/subscriptions/s/resourceGroups/rg/providers/{type_}/{name}", name, type_, location, props or {})


def no_ai(prompt):
    raise AssertionError("AI must not be asked")


# ---- discovery

def test_storage_services_are_discovered_and_name_value_secrets_redacted():
    items = [{"id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/st", "name": "st",
              "type": "Microsoft.Storage/storageAccounts", "location": "westeurope"},
             {"id": "/x/app", "name": "app", "type": "Microsoft.App/containerApps", "location": "westeurope"}]
    show_app = {"properties": {"template": {"containers": [{"env": [
        {"name": "STORAGE_QUEUE_ENDPOINT", "value": "https://st.queue"}, {"name": "DB_PASSWORD", "value": "hunter2"}]}]}}}

    def run(cmd, **kw):
        if cmd[1:3] == ["resource", "list"]:
            out = json.dumps(items)
        elif cmd[1:3] == ["resource", "show"]:
            out = json.dumps(show_app if cmd[4] == "/x/app" else {})
        elif cmd[1] == "rest":
            url = cmd[cmd.index("--url") + 1]
            out = json.dumps({"value": [{"name": "products"}]} if "queueServices" in url else {"value": []})
        else:
            raise AssertionError(cmd)
        return subprocess.CompletedProcess(cmd, 0, out, "")

    st, app = list_resources("rg", runner=run)
    assert st.properties["services"] == {"containers": [], "queues": ["products"], "tables": [], "shares": []}
    env = app.properties["properties"]["template"]["containers"][0]["env"]
    assert env[0]["value"] == "https://st.queue" and env[1]["value"] == "***"


# ---- assess

def test_storage_account_with_queues_is_rebuilt_and_blob_only_stays_direct():
    queues = res("stapp", "Microsoft.Storage/storageAccounts", {"services": {"queues": ["products"], "containers": []}})
    blobs = res("stfunc", "Microsoft.Storage/storageAccounts", {"services": {"queues": [], "containers": ["deploy"]}})
    unknown = res("stold", "Microsoft.Storage/storageAccounts")
    a = {x.resource_name: x for x in assess([queues, blobs, unknown], ask=no_ai, ops=OPS)}
    assert a["stapp"].route == "rebuild" and "RabbitMQ" in a["stapp"].target and "queues" in a["stapp"].rationale
    assert a["stfunc"].route == "direct" and a["stold"].route == "direct"


def test_demo_types_need_no_ai():
    types = ["Microsoft.Web/serverFarms", "Microsoft.ManagedIdentity/userAssignedIdentities", "Microsoft.Network/privateEndpoints",
             "Microsoft.Network/privateDnsZones", "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
             "Microsoft.OperationalInsights/workspaces", "Microsoft.Insights/components"]
    out = assess([res(f"r{i}", t) for i, t in enumerate(types)], ask=no_ai, ops=OPS)
    assert [x.route for x in out] == ["included"] * 5 + ["rebuild"] * 2


def test_unknown_types_are_asked_once_each():
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return {"route": "rebuild", "target": "t", "rationale": "r", "lw_operations": []}

    assess([res("a", "Foo/bars"), res("b", "Foo/bars"), res("c", "Foo/bazs")], ask=ask, ops=OPS)
    assert len(asked) == 2


# ---- rebuild automation

def test_rebuild_plans_add_their_creating_calls_with_cloud_init():
    a = Assessment("kv", "rebuild", "HashiCorp Vault on a Public Cloud instance", "", ["launchInstance"])
    plan = Plan("kv", "Run Vault.", ["launchInstance", "launchInstance", "getInstanceList", "deleteInstance"])
    calls = build_calls([a], OPS, [res("kv", "Microsoft.KeyVault/vaults")], [plan])
    assert [c.operation_id for c in calls] == ["launchInstance"]
    assert calls[0].body["userData"].startswith("#cloud-config") and "vault" in calls[0].body["userData"]
    assert calls[0].body["reference"] == "kv" and calls[0].body["region"] == "eu-west-3"


def test_failed_plans_add_no_calls():
    a = Assessment("kv", "rebuild", "Vault", "", ["launchInstance"])
    failed = Plan("kv", "", [], [], [], ["Plan failed: timeout"])
    assert build_calls([a], OPS, [], [failed]) == []


# ---- readiness and teardown

class Http:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        status, payload = self.responses.pop(0)

        class R:
            status_code = status
            text = ""

            @staticmethod
            def json():
                return payload
        return R()


LAUNCH = DryRunCall("POST", "/publicCloud/v1/instances", "launchInstance", {"region": "eu-west-3"}, source="vm")
ATTACH = DryRunCall("POST", "/publicCloud/v1/instances/{instanceId}/attachSecurityGroups", "attachSecurityGroups", {},
                    {"instanceId": "launchInstance"}, source="vm")


def test_waits_for_running_before_dependents():
    http = Http([(201, {"id": "i1"}), (200, {"state": "CREATING"}), (200, {"state": "RUNNING"}), (204, {})])
    ex = LeasewebExecutor(KEY, http, wait_timeout=60, poll_every=1, sleep=lambda s: None)
    results = run_calls([LAUNCH, ATTACH], ex)
    assert [m for m, _ in http.calls] == ["POST", "GET", "GET", "POST"]
    assert results[1]["sent"] and "ready_error" not in results[0]


def test_failed_instance_skips_its_dependents():
    http = Http([(201, {"id": "i1"}), (200, {"state": "FAILED"})])
    ex = LeasewebExecutor(KEY, http, wait_timeout=60, poll_every=1, sleep=lambda s: None)
    results = run_calls([LAUNCH, ATTACH], ex)
    assert "FAILED" in results[0]["ready_error"] and results[1]["skipped"]


def test_created_resources_are_recorded_and_torn_down_newest_first():
    created = []
    bucket = DryRunCall("POST", "/objectStorage/v1/objectStorages/os1/buckets", "createObjectStorageBucket", {"name": "st"}, source="st")
    http = Http([(201, {"id": "i1"}), (201, {"name": "st"})])
    run_calls([LAUNCH, bucket], LeasewebExecutor(KEY, http), created=created)
    assert [c["operation_id"] for c in created] == ["launchInstance", "createObjectStorageBucket"]
    calls = [c for _, c in teardown_calls(created, OPS)]
    assert [(c.method, c.path) for c in calls] == [("DELETE", "/objectStorage/v1/objectStorages/os1/buckets/st"),
                                                  ("DELETE", "/publicCloud/v1/instances/i1")]


def test_path_params():
    assert path_params("/a/{x}/b/{y}", "/a/1/b/2") == {"x": "1", "y": "2"}
    assert path_params("/a/{x}", "/b/1") == {}


# ---- exports

def test_curl_script_chains_ids_and_comments_out_unfilled_calls():
    bucket = DryRunCall("POST", "/objectStorage/v1/objectStorages/{objectStorageId}/buckets", "createObjectStorageBucket", {"name": "<bucket-name>"})
    text = curl_script([LAUNCH, ATTACH, bucket])
    assert "instanceId=$(curl" in text and "${instanceId}/attachSecurityGroups" in text
    assert "$LSW_API_KEY" in text and KEY not in text
    assert "# curl" in text and "fill in <bucket-name>, {objectStorageId}" in text


def test_export_endpoints():
    vm = res("vm1", "Microsoft.Compute/virtualMachines")
    kv = res("kv1", "Microsoft.KeyVault/vaults")
    plan = lambda p: {"proposal": "Vault.", "lw_operations": ["launchInstance"],
                      "code_changes": [{"file": "app/a.py", "summary": "s", "diff": "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"}]}
    c = TestClient(create_app(discover=lambda rg: [vm, kv], ask=plan, state_file=None))
    c.post("/api/discover", data={"resource_group": "rg"})
    c.post("/api/assess")
    c.post("/api/plan", data={"source_dirs": ""})
    calls = c.get("/export/calls.json").json()
    assert {x["source"] for x in calls} == {"vm1", "kv1"}  # the rebuilt vault gets its instance too
    assert "attachment" in c.get("/export/calls.sh").headers["content-disposition"]
    assert "+++ b/a.py" in c.get("/export/patch").text
    assert "Copy the secrets into HashiCorp Vault" in c.get("/export").text


def test_teardown_needs_a_key():
    c = TestClient(create_app(discover=lambda rg: [], ask=no_ai, state_file=None))
    assert c.post("/api/migrate/teardown").status_code == 409


# ---- costs

def test_spec_prices_and_live_fallback():
    prices = spec_prices()
    assert prices["lsw.c3.large"]["monthly"] == 26.02
    broken = Http([(500, {})])
    assert leaseweb_prices("eu-west-3", KEY, broken, "https://x")["source"] == "spec"
    live = Http([(200, {"instanceTypes": [{"name": "lsw.m3.large", "prices": {"hourly": "0.1", "monthly": "70"}}]})])
    assert leaseweb_prices("eu-west-3", KEY, live, "https://x") == {"source": "live", "types": {"lsw.m3.large": {"monthly": 70.0, "hourly": 0.1}}}


def test_azure_vm_prices_pick_linux_pay_as_you_go():
    vm = res("vm1", "Microsoft.Compute/virtualMachines", {"properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})
    http = Http([(200, {"Items": [
        {"productName": "Virtual Machines BS Series Windows", "skuName": "B1s", "retailPrice": 0.02, "unitOfMeasure": "1 Hour"},
        {"productName": "Virtual Machines BS Series", "skuName": "B1s Spot", "retailPrice": 0.002, "unitOfMeasure": "1 Hour"},
        {"productName": "Virtual Machines BS Series", "skuName": "B1s", "retailPrice": 0.01, "unitOfMeasure": "1 Hour"}]})])
    assert azure_vm_prices([vm, res("kv", "Microsoft.KeyVault/vaults")], http) == {
        "vm1": {"size": "Standard_B1s", "region": "westeurope", "monthly": 7.3}}


def test_costs_endpoint_rejects_odd_regions():
    c = TestClient(create_app(discover=lambda rg: [], ask=no_ai, state_file=None))
    assert c.get("/api/costs", params={"region": "x' or 1=1"}).status_code == 400
    assert c.get("/api/costs", params={"region": "eu-west-3"}).json()["leaseweb"]["source"] == "spec"


# ---- data steps

def test_data_steps_cover_data_holding_resources():
    st = res("stapp", "Microsoft.Storage/storageAccounts", {"services": {"containers": ["images"], "queues": ["products"]}})
    cosmos = res("cosmos1", "Microsoft.DocumentDB/databaseAccounts")
    nic = res("nic", "Microsoft.Network/networkInterfaces")
    steps = data_steps([st, cosmos, nic], [Assessment("stapp", "rebuild", "", ""), Assessment("cosmos1", "rebuild", "", ""),
                                           Assessment("nic", "included", "", "")])
    assert [s["resource"] for s in steps] == ["stapp", "cosmos1"]
    assert "rclone sync azure:images leaseweb:stapp/images --progress --checksum" in steps[0]["commands"]
    assert any("products" in n for n in steps[0]["notes"])


# ---- diff checks

@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_diff_check_with_real_git(tmp_path: Path):
    src = tmp_path / "app"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    good = CodeChange("app/a.py", "s", "--- a/app/a.py\n+++ b/app/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n")
    bad = CodeChange("app/a.py", "s", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-y = 1\n+y = 2\n")
    plans = [Plan("kv", "p", code_changes=[good, bad])]
    check_plans(plans, [src])
    assert good.check == "applies" and bad.check == "conflicts"
    assert (src / "a.py").read_text() == "x = 1\n"  # --check changes nothing


def test_diff_check_without_hunks_or_folder():
    folders = folder_prefixes([Path("sample_app")])
    assert check_change(CodeChange("sample_app/x.py", "s", "-a\n+b"), folders)[0] == "unchecked"
    assert check_change(CodeChange("other/x.py", "s", "@@"), folders)[0] == "unchecked"


def test_patch_text_skips_empty_diffs():
    plans = [Plan("kv", "p", code_changes=[CodeChange("a", "s", "diff1"), CodeChange("b", "s", "  ")])]
    assert patch_text(plans) == "# kv: a - s\ndiff1\n"


# ---- source selection

def test_select_sources_narrows_and_falls_back():
    items = [(Assessment("kv", "rebuild", "Vault", ""), res("kv", "Microsoft.KeyVault/vaults"))]
    source = {"app/secrets.py": "kv", "app/other.py": "x"}
    assert select_sources(items, source, ask=lambda p: {"files": {"kv": ["app/secrets.py", "made-up.py"]}}) == {
        "kv": {"app/secrets.py": "kv"}}
    assert select_sources(items, source, ask=lambda p: {"nope": 1}) == {"kv": source}
