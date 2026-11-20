from migration_assistant.assess import RULES, assess
from migration_assistant.leaseweb_ops import load_operations
from migration_assistant.models import Resource


def res(name, type_):
    return Resource(f"/x/{name}", name, type_, "westeurope")


def no_claude(prompt):
    raise AssertionError("claude should not be called for known types")


def by_name(assessments):
    return {a.resource_name: a for a in assessments}


def test_vm_is_direct():
    a = by_name(assess([res("vm1", "Microsoft.Compute/virtualMachines")], ask=no_claude))["vm1"]
    assert a.route == "direct" and "launchInstance" in a.lw_operations


def test_keyvault_is_rebuild():
    a = by_name(assess([res("kv", "Microsoft.KeyVault/vaults")], ask=no_claude))["kv"]
    assert a.route == "rebuild" and "Vault" in a.target


def test_every_rule_operation_exists_in_specs():
    ops = load_operations()
    for rule in RULES.values():
        for op in rule.lw_operations:
            assert op in ops, op


def test_nic_disk_and_public_ip_not_listed():
    rs = [
        res("vm1", "Microsoft.Compute/virtualMachines"),
        res("nic", "Microsoft.Network/networkInterfaces"),
        res("disk", "Microsoft.Compute/disks"),
        res("pip", "Microsoft.Network/publicIPAddresses"),
    ]
    assert [a.resource_name for a in assess(rs, ask=no_claude)] == ["vm1"]


def test_unknown_type_uses_claude():
    def ask(prompt):
        return {"route": "rebuild", "target": "Self-hosted bar", "rationale": "no equivalent", "lw_operations": []}
    a = assess([res("b", "Microsoft.Foo/bars")], ask=ask)[0]
    assert a.route == "rebuild" and a.target == "Self-hosted bar"


import pytest

from migration_assistant.claude_cli import ClaudeError


def test_unknown_claude_operation_dropped():
    def ask(prompt):
        return {"route": "direct", "target": "T", "rationale": "r", "lw_operations": ["launchInstance", "madeUpOp"]}
    a = assess([res("b", "Microsoft.Foo/bars")], ask=ask)[0]
    assert a.lw_operations == ["launchInstance"]
    assert "madeUpOp" in a.rationale


def test_malformed_claude_answer_raises_claude_error():
    with pytest.raises(ClaudeError):
        assess([res("b", "Microsoft.Foo/bars")], ask=lambda p: {"route": "direct"})


def test_invalid_route_raises_claude_error():
    bad = {"route": "maybe", "target": "T", "rationale": "r"}
    with pytest.raises(ClaudeError):
        assess([res("b", "Microsoft.Foo/bars")], ask=lambda p: bad)


def test_route_is_normalised():
    ok = {"route": "Direct", "target": "T", "rationale": "r"}
    assert assess([res("b", "Microsoft.Foo/bars")], ask=lambda p: ok)[0].route == "direct"
