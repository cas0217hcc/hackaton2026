import json
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SCRIPT = """
const d = require('./migration_assistant/static/portal.js');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(d[input.fn](...input.args)));
"""


def run(fn, *args):
    out = subprocess.run(["node", "-e", SCRIPT], input=json.dumps({"fn": fn, "args": list(args)}), capture_output=True, text=True, check=True, env={**os.environ, "TZ": "UTC"})
    return json.loads(out.stdout)


def res(type_, name, props=None, location="westeurope"):
    return {"id": f"/x/{name}", "name": name, "type": type_, "location": location, "properties": props or {}}


def test_location_names():
    assert run("locationName", "westeurope") == "West Europe"
    assert run("locationName", "global") == "Global"
    assert run("locationName", "eastus2") == "East US 2"
    assert run("locationName", "mars1") == "mars1"  # unknown regions stay as Azure reports them


def test_dates_are_human_and_utc_when_zone_is_missing():
    assert run("formatDate", "2026-11-20T12:25:21.3709434Z") == "20 Nov 2026 12:25"
    assert run("formatDate", "2026-11-12T21:10:13.914496+00:00") == "12 Nov 2026 21:10"
    assert run("formatDate", "2026-11-20T10:51:13.9166667") == "20 Nov 2026 10:51"


def test_default_order_is_by_layer_with_children_after_their_parent():
    names = lambda rs: [r["name"] for r in run("resourceOrder", rs)]  # noqa: E731
    rs = [
        res("Microsoft.App/containerApps", "ca"),
        res("Microsoft.Insights/components", "appi"),
        res("Microsoft.Network/networkInterfaces", "pe-a.nic.123"),
        res("Microsoft.Network/privateEndpoints", "pe-a"),
        res("Microsoft.Network/privateEndpoints", "pe-b"),
        res("Microsoft.Network/privateDnsZones/virtualNetworkLinks", "zone-a/link"),
        res("Microsoft.Network/privateDnsZones", "zone-b"),
        res("Microsoft.Network/privateDnsZones", "zone-a"),
        res("Microsoft.Network/virtualNetworks", "vnet"),
        res("Microsoft.KeyVault/vaults", "kv"),
        res("Microsoft.Storage/storageAccounts", "st"),
        res("Microsoft.Unknown/things", "thing"),
    ]
    assert names(rs) == ["vnet", "zone-a", "zone-a/link", "zone-b", "pe-a", "pe-a.nic.123", "pe-b", "kv", "st", "ca", "appi", "thing"]


def test_humanize_key():
    assert run("humanizeKey", "properties.siteConfig.alwaysOn") == "Site config › Always on"
    assert run("humanizeKey", "clientId") == "Client ID"
    assert run("humanizeKey", "properties.subnets[0].name") == "Subnets 1 › Name"


def test_portal_fields_use_portal_labels_for_known_types():
    r = res("Microsoft.KeyVault/vaults", "kv", {
        "resourceGroup": "rg", "createdTime": "2026-11-20T10:51:03.109844+00:00", "provisioningState": "Succeeded",
        "tags": {"component": "security"},
        "properties": {"vaultUri": "https://kv.vault.azure.net/", "enableRbacAuthorization": True, "enableSoftDelete": True, "sku": {"name": "standard"}},
    })
    out = run("portalFields", r)
    rows = dict(out["rows"])
    assert out["curated"] is True
    assert rows["Created"] == "20 Nov 2026 10:51"
    assert rows["Permission model"] == "Azure role-based access control"
    assert rows["Soft-delete"] == "Yes"
    assert rows["SKU"] == "standard"
    assert rows["Tags"] == "component: security"
    assert "properties.vaultUri" not in rows


def test_portal_fields_for_an_unknown_type_are_not_curated():
    out = run("portalFields", res("Microsoft.Unknown/things", "t", {"resourceGroup": "rg", "properties": {"fooBar": 1}}))
    assert out["curated"] is False
    assert dict(out["rows"]) == {"Resource group": "rg"}
