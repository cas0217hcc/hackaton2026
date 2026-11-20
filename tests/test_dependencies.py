from migration_assistant.assess import assess
from migration_assistant.claude_cli import ClaudeError
from migration_assistant.dependencies import add_dependencies
from migration_assistant.dryrun import build_calls
from migration_assistant.models import Resource

RG = "/subscriptions/s/resourceGroups/rg/providers"
VNET = f"{RG}/Microsoft.Network/virtualNetworks/vnet1"
NSG = f"{RG}/Microsoft.Network/networkSecurityGroups/nsg1"
NIC = f"{RG}/Microsoft.Network/networkInterfaces/nic1"
VM = f"{RG}/Microsoft.Compute/virtualMachines/vm1"


def resources():
    return [
        Resource(VM, "vm1", "Microsoft.Compute/virtualMachines", "westeurope",
                 {"properties": {"networkProfile": {"networkInterfaces": [{"id": NIC}]}}}),
        Resource(NIC, "nic1", "Microsoft.Network/networkInterfaces", "westeurope",
                 {"properties": {"virtualMachine": {"id": VM},
                                 "ipConfigurations": [{"properties": {"subnet": {"id": VNET + "/subnets/default"}}}]}}),
        Resource(VNET, "vnet1", "Microsoft.Network/virtualNetworks", "westeurope",
                 {"properties": {"subnets": [{"id": VNET + "/subnets/default",
                                              "properties": {"networkSecurityGroup": {"id": NSG}}}]}}),
        Resource(NSG, "nsg1", "Microsoft.Network/networkSecurityGroups", "westeurope", {}),
        Resource(f"{RG}/Microsoft.KeyVault/vaults/kv1", "kv1", "Microsoft.KeyVault/vaults", "westeurope", {}),
        Resource(f"{RG}/Microsoft.Web/sites/app1", "app1", "Microsoft.Web/sites", "westeurope",
                 {"properties": {"siteConfig": {"appSettings": [{"name": "VAULT", "value": "https://kv1.vault.azure.net"}]}}}),
    ]


def run(ask=None):
    rs = resources()
    assessments = assess(rs, ask=lambda p: {})
    note = add_dependencies(rs, assessments, ask=ask)
    return {a.resource_name: a for a in assessments}, note


def names(a):
    return [d["name"] for d in a.dependencies]


def test_config_links_fold_the_nic_into_its_vm_and_follow_subnets_to_the_vnet():
    by, note = run()
    assert names(by["vm1"]) == ["vnet1"]
    assert names(by["vnet1"]) == ["nsg1"]
    assert by["nic1"].dependencies == [] and by["nic1"].wave is None
    assert (by["nsg1"].wave, by["vnet1"].wave, by["vm1"].wave) == (0, 1, 2)
    assert note == ""


def test_ai_adds_links_and_unknown_names_self_links_and_cycles_are_dropped():
    ans = {"dependencies": [
        {"resource": "app1", "depends_on": "kv1", "reason": "reads secrets from kv1"},
        {"resource": "app1", "depends_on": "ghost", "reason": "x"},
        {"resource": "kv1", "depends_on": "kv1", "reason": "x"},
        {"resource": "nsg1", "depends_on": "vm1", "reason": "would loop"},
        "garbage",
    ]}
    by, note = run(lambda p: ans)
    assert by["app1"].dependencies == [{"name": "kv1", "reason": "reads secrets from kv1", "source": "ai"}]
    assert by["app1"].wave == 1 and by["kv1"].wave == 0
    assert names(by["nsg1"]) == []
    assert "ghost" in note and "nsg1 -> vm1" in note


def test_ai_failure_keeps_config_links():
    def boom(prompt):
        raise ClaudeError("offline")

    by, note = run(boom)
    assert names(by["vm1"]) == ["vnet1"]
    assert "offline" in note


def test_migrate_calls_follow_the_dependencies():
    rs = resources()
    assessments = assess(rs, ask=lambda p: {})
    add_dependencies(rs, assessments)
    ops = [c.operation_id for c in build_calls(assessments, resources=rs)]
    assert ops.index("createSecurityGroup") < ops.index("post/privateNetworks") < ops.index("launchInstance")
    assert ops.index("launchInstance") < ops.index("addToPrivateNetwork")
