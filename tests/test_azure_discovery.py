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
