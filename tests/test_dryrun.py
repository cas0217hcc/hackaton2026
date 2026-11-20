import socket

from migration_assistant.assess import RULES
from migration_assistant.dryrun import DryRunExecutor, build_calls
from migration_assistant.models import Assessment


def a(name, rule_type):
    r = RULES[rule_type]
    return Assessment(name, r.route, r.target, r.rationale, list(r.lw_operations))


def test_rebuild_resources_excluded():
    calls = build_calls([a("kv", "Microsoft.KeyVault/vaults")])
    assert calls == []


def test_calls_use_spec_method_and_path():
    calls = build_calls([a("st", "Microsoft.Storage/storageAccounts")])
    assert calls[0].method == "POST"
    assert calls[0].path.startswith("/objectStorage/v1/")
    assert calls[0].operation_id == "createObjectStorageBucket"


def test_dry_run_executor_sends_nothing(monkeypatch):
    def boom(*args, **kw):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", boom)
    call = build_calls([a("st", "Microsoft.Storage/storageAccounts")])[0]
    result = DryRunExecutor().execute(call)
    assert result["sent"] is False and result["dry_run"] is True


def test_calls_that_take_a_body_have_one():
    from migration_assistant.assess import RULES
    calls = build_calls([a("vnet", "Microsoft.Network/virtualNetworks"), a("nsg", "Microsoft.Network/networkSecurityGroups")])
    bodies = {c.operation_id: c.body for c in calls}
    assert bodies["post/privateNetworks"] == {"name": "vnet"}
    assert bodies["authorizeSecurityGroupFirewallRules"]["rules"][0]["protocol"] == "TCP"
    assert bodies["addToPrivateNetwork"] == {}  # spec: this operation takes no body


from migration_assistant.dryrun import LeasewebExecutor, path_matches, unresolved
from migration_assistant.models import DryRunCall

KEY = "sk-super-secret-key-123"


class FakeHttp:
    def __init__(self, status=201, payload=None, exc=None):
        self.calls, self.status, self.payload, self.exc = [], status, payload or {"id": "abc"}, exc

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.exc:
            raise self.exc

        class R:
            status_code = self.status
            text = "ok"
            def json(_):
                return self.payload
        return R()


def test_unresolved_finds_path_params_and_body_placeholders():
    call = DryRunCall("POST", "/x/{instanceId}/y", "op", {"name": "<bucket-name>", "n": {"k": ["<a>"]}})
    assert unresolved(call) == ["{instanceId}", "<bucket-name>", "<a>"]
    assert unresolved(DryRunCall("GET", "/x/1", "op", {"name": "ok"})) == []


def test_live_executor_skips_unresolved_without_sending():
    http = FakeHttp()
    res = LeasewebExecutor(KEY, http).execute(DryRunCall("POST", "/x/{id}", "op", {}))
    assert res["sent"] is False and res["skipped"] is True and "{id}" in res["reason"]
    assert http.calls == []


def test_live_executor_sends_with_auth_header_and_hides_key():
    http = FakeHttp()
    res = LeasewebExecutor(KEY, http).execute(DryRunCall("POST", "/publicCloud/v1/instances", "launchInstance", {"a": 1}))
    method, url, kw = http.calls[0]
    assert method == "POST" and url == "https://api.leaseweb.com/publicCloud/v1/instances"
    assert kw["headers"]["X-LSW-Auth"] == KEY and kw["json"] == {"a": 1}
    assert res["sent"] is True and res["dry_run"] is False and res["status"] == 201
    assert KEY not in repr(res)


def test_live_executor_error_never_leaks_key():
    http = FakeHttp(exc=RuntimeError(f"connection failed for header {KEY}"))
    res = LeasewebExecutor(KEY, http).execute(DryRunCall("GET", "/x", "op", {}))
    assert res["sent"] is False and "error" in res and KEY not in repr(res)


def test_live_executor_get_sends_no_body():
    http = FakeHttp()
    LeasewebExecutor(KEY, http).execute(DryRunCall("GET", "/x", "op", {}))
    assert "json" not in http.calls[0][2]


def test_path_matches_template():
    assert path_matches("/a/{id}/b", "/a/123/b")
    assert not path_matches("/a/{id}/b", "/a/123/c")
    assert not path_matches("/a/{id}", "/a/1/2")


from migration_assistant.dryrun import run_calls


def full_flow_assessments():
    return [a("vnet", "Microsoft.Network/virtualNetworks"), a("nsg", "Microsoft.Network/networkSecurityGroups"),
            a("vm", "Microsoft.Compute/virtualMachines")]


def test_calls_are_ordered_so_producers_run_before_consumers():
    ids = [c.operation_id for c in build_calls(full_flow_assessments())]
    assert ids.index("createSecurityGroup") < ids.index("authorizeSecurityGroupFirewallRules")
    assert ids.index("launchInstance") < ids.index("addToPrivateNetwork")
    assert ids.index("post/privateNetworks") < ids.index("addToPrivateNetwork")


def test_consumer_calls_declare_where_their_params_come_from():
    by_op = {c.operation_id: c for c in build_calls(full_flow_assessments())}
    assert by_op["addToPrivateNetwork"].chained == {"instanceId": "launchInstance"}
    assert by_op["authorizeSecurityGroupFirewallRules"].chained == {"securityGroupId": "createSecurityGroup"}
    assert by_op["launchInstance"].chained == {}


class SeqHttp(FakeHttp):
    """Returns a different id per call so chaining can be observed."""
    def request(self, method, url, **kw):
        self.payload = {"id": f"id-{len(self.calls) + 1}"}
        return super().request(method, url, **kw)


def resolved(calls):
    out = []
    for c in calls:
        body = {k: ("x" if isinstance(v, str) and v.startswith("<") else v) for k, v in c.body.items()}
        out.append(DryRunCall(c.method, c.path, c.operation_id, body, c.chained))
    return out


def test_run_calls_fills_instance_id_from_the_launch_response():
    http = SeqHttp()
    calls = resolved(build_calls([a("vm", "Microsoft.Compute/virtualMachines"), a("vnet", "Microsoft.Network/virtualNetworks")]))
    results = run_calls(calls, LeasewebExecutor(KEY, http))
    urls = [u for _, u, _ in http.calls]
    launch_n = [c.operation_id for c in calls].index("launchInstance") + 1
    assert any(u.endswith(f"/instances/id-{launch_n}/addToPrivateNetwork") for u in urls)
    assert all(r["sent"] for r in results)


def test_dependents_are_skipped_when_their_producer_fails():
    http = FakeHttp(status=500, payload={"errorMessage": "no"})
    calls = resolved(build_calls([a("vm", "Microsoft.Compute/virtualMachines"), a("vnet", "Microsoft.Network/virtualNetworks")]))
    results = {r["operation_id"]: r for r in run_calls(calls, LeasewebExecutor(KEY, http))}
    assert results["addToPrivateNetwork"]["skipped"] is True
    assert "instanceId" in results["addToPrivateNetwork"]["reason"]


def test_run_calls_with_dry_run_executor_sends_nothing_and_keeps_all_calls():
    results = run_calls(build_calls(full_flow_assessments()), DryRunExecutor())
    assert len(results) == len(build_calls(full_flow_assessments()))
    assert all(r["sent"] is False and r["dry_run"] is True for r in results)


def test_placeholder_bodies_match_the_spec_request_schemas():
    import yaml
    from pathlib import Path
    from migration_assistant.dryrun import PLACEHOLDER_BODIES
    schemas = {"launchInstance": "publicCloud/components/schemas/launchInstanceOpts.yaml",
               "createObjectStorageBucket": "objectStorage/components/schemas/createObjectStorageBucketOpts.yaml",
               "createSecurityGroup": "publicCloud/components/schemas/createSecurityGroupOpts.yaml"}
    for op, rel in schemas.items():
        spec = yaml.safe_load((Path("leaseweb-api") / rel).read_text())
        body = PLACEHOLDER_BODIES[op]
        assert set(body) <= set(spec["properties"]), f"{op}: unknown fields {set(body) - set(spec['properties'])}"
        assert set(spec.get("required", [])) <= set(body), f"{op}: missing {set(spec.get('required', [])) - set(body)}"


def test_run_calls_shares_ids_across_separate_runs():
    http = SeqHttp()
    ex = LeasewebExecutor(KEY, http)
    ids: dict = {}
    launch = DryRunCall("POST", "/publicCloud/v1/instances", "launchInstance",
                        {"region": "eu-west-3", "type": "t", "imageId": "i", "contractType": "HOURLY", "rootDiskSize": 50, "rootDiskStorageType": "CENTRAL", "reference": "x"})
    run_calls([launch], ex, ids)
    assert ids == {"instanceId": "id-1"}
    attach = DryRunCall("PUT", "/publicCloud/v1/instances/{instanceId}/addToPrivateNetwork", "addToPrivateNetwork", {})
    [res] = run_calls([attach], ex, ids)
    assert res["sent"] is True and res["path"] == "/publicCloud/v1/instances/id-1/addToPrivateNetwork"


LAUNCH_CALL = DryRunCall("POST", "/publicCloud/v1/instances", "launchInstance",
                         {"region": "eu-west-3", "type": "t", "imageId": "i", "contractType": "HOURLY", "rootDiskSize": 50, "rootDiskStorageType": "CENTRAL", "reference": "x"})
ATTACH_CALL = DryRunCall("PUT", "/publicCloud/v1/instances/{instanceId}/addToPrivateNetwork", "addToPrivateNetwork", {})


def test_failed_live_producer_forgets_its_stale_id():
    # Otherwise a dependent call would act on an instance from an older run.
    http = FakeHttp(status=500, payload={"errorMessage": "no"})
    ids = {"instanceId": "old-instance"}
    results = run_calls([LAUNCH_CALL, ATTACH_CALL], LeasewebExecutor(KEY, http), ids)
    assert "instanceId" not in ids
    assert results[1]["skipped"] is True and len(http.calls) == 1


def test_dry_run_never_forgets_remembered_ids():
    ids = {"instanceId": "real-instance"}
    run_calls([LAUNCH_CALL], DryRunExecutor(), ids)
    assert ids == {"instanceId": "real-instance"}


def test_calls_name_their_azure_resource():
    calls = build_calls([a("sthack", "Microsoft.Storage/storageAccounts"), a("vm-web-01", "Microsoft.Compute/virtualMachines")])
    assert {c.operation_id: c.source for c in calls} == {"createObjectStorageBucket": "sthack", "launchInstance": "vm-web-01"}


def test_names_are_prefilled_from_the_azure_resource_names():
    calls = build_calls([a("sthack", "Microsoft.Storage/storageAccounts"), a("vm-web-01", "Microsoft.Compute/virtualMachines"),
                         a("nsg-web", "Microsoft.Network/networkSecurityGroups"), a("vnet-hack", "Microsoft.Network/virtualNetworks")])
    body = {c.operation_id: c.body for c in calls}
    assert body["createObjectStorageBucket"]["name"] == "sthack"
    assert body["launchInstance"]["reference"] == "vm-web-01"
    assert body["createSecurityGroup"]["name"] == "nsg-web"
    assert body["post/privateNetworks"]["name"] == "vnet-hack"
    assert all(unresolved(DryRunCall(c.method, "/x", c.operation_id, c.body)) == [] for c in calls)


def test_region_and_disk_size_come_from_the_azure_vm():
    from migration_assistant.models import Resource
    vm = Resource("/x/vm", "vm-web-01", "Microsoft.Compute/virtualMachines", "germanywestcentral",
                  {"properties": {"storageProfile": {"osDisk": {"diskSizeGB": 64}}}})
    [launch] = build_calls([a("vm-web-01", "Microsoft.Compute/virtualMachines")], resources=[vm])
    assert launch.body["region"] == "eu-central-1" and launch.body["rootDiskSize"] == 64


def test_unknown_azure_location_keeps_the_default_region():
    from migration_assistant.models import Resource
    vm = Resource("/x/vm", "vm", "Microsoft.Compute/virtualMachines", "brazilsouth", {})
    [launch] = build_calls([a("vm", "Microsoft.Compute/virtualMachines")], resources=[vm])
    assert launch.body["region"] == "eu-west-3" and launch.body["rootDiskSize"] == 50
