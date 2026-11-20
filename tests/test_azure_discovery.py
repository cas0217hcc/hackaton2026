import json
import subprocess

import pytest

from migration_assistant.azure_discovery import DiscoveryError, list_resources

SAMPLE = [
    {"id": "/s/rg/vm-web-01", "name": "vm-web-01", "type": "Microsoft.Compute/virtualMachines", "location": "westeurope"},
    {"id": "/s/rg/kv-hack", "name": "kv-hack", "type": "Microsoft.KeyVault/vaults", "location": "westeurope"},
]


def fake(stdout="", stderr="", code=0):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, code, stdout, stderr)
    return run


def test_parses_resources():
    res = list_resources("rg", runner=fake(json.dumps(SAMPLE)))
    assert [r.name for r in res] == ["vm-web-01", "kv-hack"]
    assert res[1].type == "Microsoft.KeyVault/vaults"


def test_az_failure_raises():
    with pytest.raises(DiscoveryError, match="az login"):
        list_resources("rg", runner=fake(stderr="Please run 'az login'", code=1))


def test_empty_group_raises():
    with pytest.raises(DiscoveryError):
        list_resources("rg", runner=fake("[]"))


def dispatch(show_stdout="{}", show_code=0):
    """Fake az: `list` returns SAMPLE, `show` returns show_stdout."""
    def run(cmd, **kw):
        if cmd[2] == "show":
            return subprocess.CompletedProcess(cmd, show_code, show_stdout, "boom" if show_code else "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(SAMPLE), "")
    return run


def test_configured_values_come_from_az_resource_show():
    show = json.dumps({"sku": {"name": "Standard_LRS"}, "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})
    res = list_resources("rg", runner=dispatch(show))
    assert res[0].properties["properties"]["hardwareProfile"]["vmSize"] == "Standard_B1s"
    assert res[0].properties["sku"] == {"name": "Standard_LRS"}


def test_sensitive_values_are_redacted():
    show = json.dumps({"properties": {"osProfile": {"adminUsername": "azureuser", "adminPassword": "hunter2", "customData": "c2VjcmV0"},
                                      "keys": [{"primaryKey": "abc"}], "connectionString": "Endpoint=sb://x;SharedAccessKey=zzz"}})
    res = list_resources("rg", runner=dispatch(show))
    text = json.dumps(res[0].properties)
    for leaked in ("hunter2", "c2VjcmV0", "abc", "SharedAccessKey=zzz"):
        assert leaked not in text
    assert res[0].properties["properties"]["osProfile"]["adminUsername"] == "azureuser"


def test_show_failure_does_not_fail_discovery():
    res = list_resources("rg", runner=dispatch(show_code=1))
    assert [r.name for r in res] == ["vm-web-01", "kv-hack"]


def test_show_returning_non_object_is_ignored():
    res = list_resources("rg", runner=dispatch("[1, 2]"))
    assert len(res) == 2


def test_boolean_flags_with_sensitive_looking_names_stay_visible():
    show = json.dumps({"properties": {"disablePasswordAuthentication": True, "allowSharedKeyAccess": False, "adminPassword": "x"}})
    props = list_resources("rg", runner=dispatch(show))[0].properties["properties"]
    assert props["disablePasswordAuthentication"] is True and props["allowSharedKeyAccess"] is False
    assert props["adminPassword"] == "***"


from migration_assistant.azure_discovery import list_resource_groups

GROUPS = [{"name": "rg-b", "location": "westeurope"}, {"name": "hackaton-2026-rg", "location": "westeurope"}, {"name": "Rg-a", "location": "northeurope"}]


def test_resource_groups_are_listed_sorted_by_name():
    got = list_resource_groups(runner=fake(json.dumps(GROUPS)))
    assert [g["name"] for g in got] == ["hackaton-2026-rg", "Rg-a", "rg-b"]
    assert got[0] == {"name": "hackaton-2026-rg", "location": "westeurope"}


def test_resource_group_listing_asks_az_for_groups_only():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "[]", "")
    list_resource_groups(runner=run)
    assert seen["cmd"][:3] == ["az", "group", "list"]


def test_resource_group_listing_failure_is_a_clear_error():
    with pytest.raises(DiscoveryError, match="az login"):
        list_resource_groups(runner=fake(stderr="Please run 'az login'", code=1))
    with pytest.raises(DiscoveryError, match="not found"):
        def missing(cmd, **kw):
            raise FileNotFoundError
        list_resource_groups(runner=missing)
