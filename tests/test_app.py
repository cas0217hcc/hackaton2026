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
    assert c.post("/api/plan", data={"source_dirs": ""}).status_code == 200
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
    r = c.post("/api/plan", data={"source_dirs": ""})
    assert r.status_code == 200 and r.json()["plans"] == [] and "nothing to plan" in r.json()["message"].lower()


def test_claude_error_returns_502_message():
    def fail(prompt):
        raise ClaudeError("claude timed out after 180s")
    c = client([VM, KV], ask=fail)
    run_to_assess(c)
    r = c.post("/api/plan", data={"source_dirs": ""})
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
    c.post("/api/plan", data={"source_dirs": ""})
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
    assert c2.post("/api/plan", data={"source_dirs": ""}).status_code == 200


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


def test_plan_accepts_up_to_five_folders(tmp_path):
    dirs = []
    for i in range(5):
        d = tmp_path / f"app{i}"; d.mkdir(); (d / "m.py").write_text("x"); dirs.append(str(d))
    c = client([VM, KV]); run_to_assess(c)
    assert c.post("/api/plan", data={"source_dirs": dirs}).status_code == 200


def test_plan_rejects_more_than_five_folders(tmp_path):
    c = client([VM, KV]); run_to_assess(c)
    r = c.post("/api/plan", data={"source_dirs": [str(tmp_path)] * 6})
    assert r.status_code == 400 and "5" in r.json()["error"]


def test_plan_rejects_missing_folder(tmp_path):
    c = client([VM, KV]); run_to_assess(c)
    r = c.post("/api/plan", data={"source_dirs": [str(tmp_path / "nope")]})
    assert r.status_code == 400 and "nope" in r.json()["error"]


def test_source_dirs_persist_and_old_single_dir_state_loads(tmp_path):
    import json
    d = tmp_path / "app"; d.mkdir(); (d / "m.py").write_text("x")
    f = tmp_path / "s.json"
    c = persistent_client([VM, KV], f); run_to_assess(c)
    c.post("/api/plan", data={"source_dirs": [str(d)]})
    assert persistent_client([], f).get("/api/state").json()["source_dirs"] == [str(d)]
    f.write_text(json.dumps({"source_dir": "/old/app"}))
    assert persistent_client([], f).get("/api/state").json()["source_dirs"] == ["/old/app"]


def test_static_urls_are_versioned_to_defeat_browser_cache():
    html = client([VM]).get("/").text
    assert "/static/app.js?v=" in html and "/static/style.css?v=" in html


def test_reset_clears_state_and_saved_file(tmp_path):
    f = tmp_path / "s.json"
    c = persistent_client([VM, KV], f)
    run_to_assess(c)
    assert f.exists()
    r = c.post("/api/reset")
    assert r.status_code == 200
    s = c.get("/api/state").json()
    assert s["resources"] == [] and s["assessments"] == [] and s["plans"] == [] and s["calls"] == []
    assert s["resource_group"] == "hackaton-2026-rg" and s["source_dirs"] == []
    assert not f.exists()
    assert persistent_client([], f).get("/api/state").json()["resources"] == []


def test_reset_without_persistence_and_when_nothing_saved():
    c = client([VM])
    run_to_assess(c)
    assert c.post("/api/reset").status_code == 200
    assert c.post("/api/reset").status_code == 200  # idempotent
    assert c.get("/export").text.strip().startswith("# Azure to Leaseweb")


from tests.test_dryrun import FakeHttp, KEY


def live_client(resources=(VM, KV), http=None, state_file=None):
    http = http or FakeHttp()
    c = TestClient(create_app(discover=lambda rg: list(resources), ask=plan_answer, state_file=state_file, http=http))
    return c, http


def good_call(**over):
    call = {"method": "POST", "path": "/objectStorage/v1/objectStorages/abc/buckets",
            "operation_id": "createObjectStorageBucket", "body": {"name": "my-bucket", "region": "nl-01"}}
    call.update(over)
    return call


def test_set_key_never_echoed_anywhere():
    c, _ = live_client()
    r = c.post("/api/key", data={"api_key": KEY})
    assert r.status_code == 200 and KEY not in r.text
    s = c.get("/api/state")
    assert s.json()["api_key_set"] is True and KEY not in s.text
    assert KEY not in c.get("/export").text


def test_empty_key_rejected_and_key_can_be_removed():
    c, _ = live_client()
    assert c.post("/api/key", data={"api_key": "   "}).status_code == 400
    c.post("/api/key", data={"api_key": KEY})
    assert c.delete("/api/key").status_code == 200
    assert c.get("/api/state").json()["api_key_set"] is False


def test_key_is_not_written_to_state_file(tmp_path):
    f = tmp_path / "s.json"
    c, _ = live_client(state_file=f)
    run_to_assess(c)
    c.post("/api/key", data={"api_key": KEY})
    c.post("/api/migrate")
    assert KEY not in f.read_text()


def test_no_key_means_dry_run_and_nothing_sent():
    import json as _json
    c, http = live_client()
    run_to_assess(c)
    r = c.post("/api/migrate", data={"calls": _json.dumps([good_call()])}).json()
    assert r["live"] is False and r["results"][0]["sent"] is False and r["results"][0]["dry_run"] is True
    assert http.calls == []


def test_key_set_means_live_and_sends_resolved_calls_only():
    import json as _json
    c, http = live_client()
    run_to_assess(c)
    c.post("/api/key", data={"api_key": KEY})
    calls = [good_call(), good_call(body={"name": "<bucket-name>", "region": "nl-01"})]
    r = c.post("/api/migrate", data={"calls": _json.dumps(calls)}).json()
    assert r["live"] is True
    assert r["results"][0]["sent"] is True and r["results"][1]["skipped"] is True
    assert len(http.calls) == 1 and http.calls[0][2]["headers"]["X-LSW-Auth"] == KEY
    assert KEY not in _json.dumps(r)


def test_migrate_rejects_calls_not_matching_the_specs():
    import json as _json
    c, http = live_client()
    run_to_assess(c)
    c.post("/api/key", data={"api_key": KEY})
    for bad in (good_call(operation_id="deleteEverything"),
                good_call(path="/publicCloud/v1/instances"),
                good_call(method="DELETE")):
        r = c.post("/api/migrate", data={"calls": _json.dumps([bad])})
        assert r.status_code == 400
    assert http.calls == []


def test_calls_endpoint_returns_prepared_calls_and_mode():
    c, _ = live_client()
    run_to_assess(c)
    r = c.get("/api/migrate/calls").json()
    assert r["live"] is False and r["calls"][0]["operation_id"] == "launchInstance"
    c.post("/api/key", data={"api_key": KEY})
    assert c.get("/api/migrate/calls").json()["live"] is True


def test_reset_keeps_key_in_memory_only():
    c, _ = live_client()
    c.post("/api/key", data={"api_key": KEY})
    c.post("/api/reset")
    assert c.get("/api/state").json()["api_key_set"] is True


def test_plan_progress_endpoint_reports_completion():
    c = client([VM, KV]); run_to_assess(c)
    idle = c.get("/api/plan/progress").json()
    assert idle["running"] is False and idle["total"] == 0
    c.post("/api/plan", data={"source_dirs": ""})
    p = c.get("/api/plan/progress").json()
    assert p["running"] is False and p["total"] == 1 and p["done"] == 1
    assert p["items"] == [{"name": "kv-hack", "status": "done"}]


def test_plan_with_one_failed_resource_still_returns_the_others():
    from migration_assistant.models import Resource as R
    kv2 = R("/x/kv2", "kv-two", "Microsoft.KeyVault/vaults", "westeurope")

    def ask(prompt):
        if "kv-two" in prompt:
            raise ClaudeError("claude timed out after 180s")
        return plan_answer(prompt)
    c = client([VM, KV, kv2], ask=ask); run_to_assess(c)
    r = c.post("/api/plan", data={"source_dirs": ""})
    assert r.status_code == 200
    plans = {p["resource_name"]: p for p in r.json()["plans"]}
    assert plans["kv-hack"]["proposal"] and plans["kv-two"]["warnings"][0].startswith("Plan failed")


def test_options_endpoint_serves_spec_regions_without_a_key():
    c, _ = live_client()
    r = c.get("/api/migrate/options").json()
    assert r["source"] == "spec"
    regions = {x["value"]: x["description"] for x in r["options"]["launchInstance"]["region"]}
    assert regions["eu-west-3"] == "Amsterdam"
    assert "HOURLY" in [x["value"] for x in r["options"]["launchInstance"]["contractType"]]


def test_options_endpoint_uses_live_regions_when_a_key_is_set():
    http = FakeHttp(status=200, payload={"regions": [{"name": "eu-west-3", "location": "Amsterdam (live)"}, {"name": "xx-new-1", "location": "Newtown"}]})
    c, _ = live_client(http=http)
    c.post("/api/key", data={"api_key": KEY})
    r = c.get("/api/migrate/options").json()
    assert r["source"] == "live"
    assert {x["value"]: x["description"] for x in r["options"]["launchInstance"]["region"]} == {"eu-west-3": "Amsterdam (live)", "xx-new-1": "Newtown"}
    assert http.calls[0][1].endswith("/publicCloud/v1/regions") and http.calls[0][2]["headers"]["X-LSW-Auth"] == KEY
    assert KEY not in str(r)


def test_options_endpoint_falls_back_to_spec_when_live_lookup_fails():
    c, _ = live_client(http=FakeHttp(exc=RuntimeError("down")))
    c.post("/api/key", data={"api_key": KEY})
    r = c.get("/api/migrate/options").json()
    assert r["source"] == "spec" and r["options"]["launchInstance"]["region"]


LAUNCH = {"method": "POST", "path": "/publicCloud/v1/instances", "operation_id": "launchInstance",
          "body": {"region": "eu-west-3", "type": "lsw.c3.large", "imageId": "UBUNTU_22_04_64BIT", "contractType": "HOURLY",
                   "rootDiskSize": 50, "rootDiskStorageType": "CENTRAL", "reference": "web"}}
ATTACH = {"method": "PUT", "path": "/publicCloud/v1/instances/{instanceId}/addToPrivateNetwork",
          "operation_id": "addToPrivateNetwork", "body": {}}


def run_one(c, call):
    import json as _json
    return c.post("/api/migrate/run-one", data={"call": _json.dumps(call)})


def seq_client():
    from tests.test_dryrun import SeqHttp
    c, http = live_client(http=SeqHttp())
    run_to_assess(c)
    return c, http


def test_run_one_in_dry_run_mode_sends_nothing():
    c, http = seq_client()
    r = run_one(c, LAUNCH).json()
    assert r["live"] is False and r["result"]["dry_run"] is True and r["result"]["sent"] is False
    assert http.calls == []


def test_run_one_remembers_ids_for_later_single_runs():
    c, http = seq_client()
    c.post("/api/key", data={"api_key": KEY})
    first = run_one(c, LAUNCH).json()
    assert first["result"]["sent"] is True and first["chain"] == {"instanceId": "id-1"}
    second = run_one(c, ATTACH).json()
    assert second["result"]["sent"] is True
    assert http.calls[1][1].endswith("/instances/id-1/addToPrivateNetwork")


def test_run_one_skips_when_the_needed_id_does_not_exist_yet():
    c, http = seq_client()
    c.post("/api/key", data={"api_key": KEY})
    r = run_one(c, ATTACH).json()["result"]
    assert r["sent"] is False and r["skipped"] is True and "instanceId" in r["reason"]
    assert http.calls == []


def test_run_one_rejects_calls_that_do_not_match_the_specs():
    c, http = seq_client()
    c.post("/api/key", data={"api_key": KEY})
    assert run_one(c, {**LAUNCH, "operation_id": "deleteEverything"}).status_code == 400
    assert run_one(c, {**LAUNCH, "method": "DELETE"}).status_code == 400
    assert http.calls == []


def test_start_over_forgets_remembered_ids():
    c, http = seq_client()
    c.post("/api/key", data={"api_key": KEY})
    run_one(c, LAUNCH)
    c.post("/api/reset")
    run_to_assess(c)
    assert run_one(c, ATTACH).json()["result"]["skipped"] is True


def test_state_endpoint_exposes_remembered_ids():
    c, _ = seq_client()
    c.post("/api/key", data={"api_key": KEY})
    run_one(c, LAUNCH)
    assert c.get("/api/state").json()["chain"] == {"instanceId": "id-1"}


def test_full_run_uses_ids_remembered_from_single_runs():
    import json as _json
    c, http = seq_client()
    c.post("/api/key", data={"api_key": KEY})
    run_one(c, LAUNCH)
    r = c.post("/api/migrate", data={"calls": _json.dumps([ATTACH])}).json()
    assert r["results"][0]["sent"] is True
    assert http.calls[1][1].endswith("/instances/id-1/addToPrivateNetwork")


def test_calls_carry_their_azure_resource_through_the_api():
    import json as _json
    c, _ = live_client()
    run_to_assess(c)
    prepared = c.get("/api/migrate/calls").json()["calls"]
    assert prepared[0]["source"] == "vm-web-01"
    r = c.post("/api/migrate", data={"calls": _json.dumps([{**good_call(), "source": "sthack"}])}).json()
    assert r["calls"][0]["source"] == "sthack"


# ---- AI provider settings

SECRET = "sk-ant-secret-key-123"


def ai_client(**kw):
    made = []

    def make_ask(settings):
        made.append((settings.provider, settings.model, settings.api_key))
        return lambda prompt: {"ok": True} if '"ok"' in prompt else plan_answer(prompt)
    kw.setdefault("discover", lambda rg: [VM, KV])
    return TestClient(create_app(state_file=None, make_ask=make_ask, **kw)), made


def test_ai_settings_default_to_claude_code():
    c, _ = ai_client()
    s = c.get("/api/ai").json()
    assert s["provider"] == "claude-cli" and s["model"] == ""
    assert {p["id"] for p in s["providers"]} == {"claude-cli", "anthropic-api", "opencode"}


def test_ai_provider_can_be_switched_and_the_key_is_never_returned():
    c, _ = ai_client()
    r = c.post("/api/ai", data={"provider": "anthropic-api", "model": "claude-sonnet-5-5", "api_key": SECRET})
    assert r.status_code == 200 and SECRET not in r.text
    s = c.get("/api/ai")
    assert SECRET not in s.text
    body = s.json()
    assert body["provider"] == "anthropic-api" and body["model"] == "claude-sonnet-5-5" and body["api_key_set"] is True
    assert SECRET not in c.get("/api/state").text and SECRET not in c.get("/export").text


def test_ai_key_is_kept_when_only_the_provider_changes_and_can_be_removed():
    c, _ = ai_client()
    c.post("/api/ai", data={"provider": "anthropic-api", "api_key": SECRET})
    c.post("/api/ai", data={"provider": "opencode", "model": "anthropic/claude-sonnet-5-5"})
    assert c.get("/api/ai").json()["api_key_set"] is True
    assert c.delete("/api/ai/key").status_code == 200
    assert c.get("/api/ai").json()["api_key_set"] is False


def test_unknown_provider_and_bad_opencode_model_are_rejected():
    c, _ = ai_client()
    assert c.post("/api/ai", data={"provider": "nope"}).status_code == 400
    r = c.post("/api/ai", data={"provider": "opencode", "model": "--auto"})
    assert r.status_code == 400 and "provider/model" in r.json()["error"]
    assert c.get("/api/ai").json()["provider"] == "claude-cli"


def test_plan_uses_the_selected_provider():
    c, made = ai_client()
    c.post("/api/ai", data={"provider": "opencode", "model": "anthropic/claude-sonnet-5-5"})
    c.post("/api/discover", data={"resource_group": "rg"})
    c.post("/api/assess")
    assert c.post("/api/plan", data={"source_dirs": ""}).status_code == 200
    assert ("opencode", "anthropic/claude-sonnet-5-5", None) in made


def test_connection_test_reports_success_and_failure():
    c, _ = ai_client()
    assert c.post("/api/ai/test").json() == {"ok": True}

    def failing(settings):
        def ask(prompt):
            raise ClaudeError("opencode failed: no credentials")
        return ask
    bad = TestClient(create_app(state_file=None, make_ask=failing))
    r = bad.post("/api/ai/test")
    assert r.status_code == 502 and "no credentials" in r.json()["error"]


def test_connection_test_checks_that_the_answer_is_json_with_ok():
    wrong = TestClient(create_app(state_file=None, make_ask=lambda s: (lambda prompt: {"hello": 1})))
    assert wrong.post("/api/ai/test").status_code == 502


def test_models_endpoint_serves_the_list_for_the_requested_provider():
    asked = []

    def models_fn(provider, settings):
        asked.append((provider, settings.api_key))
        return {"models": [{"id": "", "label": "Default", "group": "default"}], "source": "live"}
    c = TestClient(create_app(state_file=None, models_fn=models_fn))
    c.post("/api/ai", data={"provider": "anthropic-api", "api_key": SECRET})
    r = c.get("/api/ai/models", params={"provider": "anthropic-api"})
    assert r.status_code == 200 and r.json()["source"] == "live" and SECRET not in r.text
    assert asked == [("anthropic-api", SECRET)]
    assert c.get("/api/ai/models", params={"provider": "nope"}).status_code == 400


def test_claude_cli_model_must_be_an_alias_or_a_claude_model_id():
    c, _ = ai_client()
    assert c.post("/api/ai", data={"provider": "claude-cli", "model": "sonnet"}).status_code == 200
    assert c.post("/api/ai", data={"provider": "claude-cli", "model": "claude-sonnet-5-5"}).status_code == 200
    assert c.post("/api/ai", data={"provider": "claude-cli", "model": "--auto"}).status_code == 400


def test_resource_groups_endpoint_lists_groups_and_the_default():
    groups = [{"name": "hackaton-2026-rg", "location": "westeurope"}, {"name": "other", "location": "northeurope"}]
    c = TestClient(create_app(state_file=None, groups_fn=lambda: groups))
    r = c.get("/api/resource-groups").json()
    assert r["groups"] == groups and r["default"] == "hackaton-2026-rg"


def test_resource_groups_endpoint_reports_az_problems():
    def fail():
        raise DiscoveryError("Please run 'az login'")
    r = TestClient(create_app(state_file=None, groups_fn=fail)).get("/api/resource-groups")
    assert r.status_code == 502 and "az login" in r.json()["error"]


def detail_client():
    plan = {"proposal": "Run Vault.", "steps": ["Launch the VM with launchInstance.", "Copy the secrets by hand."],
            "lw_operations": ["launchInstance", "createSecurityGroup"],
            "code_changes": [{"file": "a.py", "summary": "s", "diff": "-a\n+b"}]}
    c = client([VM, KV], ask=lambda p: plan)
    run_to_assess(c)
    c.post("/api/plan", data={"source_dirs": ""})
    return c


def test_plan_detail_pairs_each_step_with_its_technical_implementation():
    d = detail_client().get("/api/plan/detail", params={"resource": "kv-hack"}).json()
    assert d["resource"]["name"] == "kv-hack" and d["resource"]["type"] == "Microsoft.KeyVault/vaults"
    first, second = d["steps"]
    assert first["text"].startswith("Launch the VM") and [o["id"] for o in first["operations"]] == ["launchInstance"]
    launch = first["operations"][0]
    assert launch["method"] == "POST" and launch["path"] == "/publicCloud/v1/instances" and launch["summary"] == "Launch instance"
    assert {f["name"] for f in launch["body_fields"]} >= {"region", "type", "imageId"}
    assert second["operations"] == []


def test_plan_detail_lists_operations_that_no_step_names():
    d = detail_client().get("/api/plan/detail", params={"resource": "kv-hack"}).json()
    assert [o["id"] for o in d["unassigned"]] == ["createSecurityGroup"]
    assert d["code_changes"][0]["file"] == "a.py"


def test_plan_detail_for_an_unknown_resource_is_404():
    assert detail_client().get("/api/plan/detail", params={"resource": "nope"}).status_code == 404


# ---- the AI choice survives a restart (the key does not)

def ai_app(tmp_path, **kw):
    return TestClient(create_app(state_file=tmp_path / "s.json", discover=lambda rg: [VM, KV], **kw))


def test_ai_choice_is_remembered_across_a_restart(tmp_path):
    c = ai_app(tmp_path)
    c.post("/api/ai", data={"provider": "opencode", "model": "anthropic/claude-sonnet-5-5"})
    again = ai_app(tmp_path).get("/api/ai").json()
    assert again["provider"] == "opencode" and again["model"] == "anthropic/claude-sonnet-5-5"


def test_the_api_key_is_never_written_to_disk(tmp_path):
    c = ai_app(tmp_path)
    c.post("/api/ai", data={"provider": "anthropic-api", "model": "claude-sonnet-5-5", "api_key": SECRET})
    saved = (tmp_path / "ai.json").read_text()
    assert SECRET not in saved and "api_key" not in saved
    assert ai_app(tmp_path).get("/api/ai").json()["api_key_set"] is False


def test_a_damaged_ai_settings_file_falls_back_to_the_default(tmp_path):
    (tmp_path / "ai.json").write_text("{not json")
    assert ai_app(tmp_path).get("/api/ai").json()["provider"] == "claude-cli"
    (tmp_path / "ai.json").write_text('{"provider": "nope", "model": 5}')
    assert ai_app(tmp_path).get("/api/ai").json()["provider"] == "claude-cli"


def test_start_over_keeps_the_ai_choice(tmp_path):
    c = ai_app(tmp_path)
    c.post("/api/ai", data={"provider": "opencode", "model": ""})
    c.post("/api/reset")
    assert ai_app(tmp_path).get("/api/ai").json()["provider"] == "opencode"


def test_the_effective_model_is_reported_for_the_header():
    c, _ = ai_client()
    c.post("/api/ai", data={"provider": "anthropic-api", "model": ""})
    assert c.get("/api/ai").json()["effective_model"] == "claude-opus-5-5"
    c.post("/api/ai", data={"provider": "anthropic-api", "model": "claude-sonnet-5-5"})
    assert c.get("/api/ai").json()["effective_model"] == "claude-sonnet-5-5"
    c.post("/api/ai", data={"provider": "claude-cli", "model": ""})
    assert c.get("/api/ai").json()["effective_model"] == ""
