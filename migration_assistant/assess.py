from dataclasses import dataclass, field
from typing import Callable

from .claude_cli import ask_json
from .models import Assessment, Resource


@dataclass
class Rule:
    route: str
    target: str
    rationale: str
    lw_operations: list[str] = field(default_factory=list)


RULES: dict[str, Rule] = {
    "Microsoft.Compute/virtualMachines": Rule("direct", "Public Cloud instance", "Leaseweb Public Cloud launches instances.", ["launchInstance"]),
    "Microsoft.Network/networkSecurityGroups": Rule("direct", "Public Cloud security group", "Maps to Leaseweb security groups and firewall rules.", ["createSecurityGroup", "authorizeSecurityGroupFirewallRules"]),
    "Microsoft.Storage/storageAccounts": Rule("direct", "Object Storage bucket", "S3-compatible Object Storage replaces blob storage.", ["createObjectStorageBucket"]),
    "Microsoft.Network/virtualNetworks": Rule("direct", "Private network", "Leaseweb private networks replace vnets.", ["post/privateNetworks", "addToPrivateNetwork"]),
    "Microsoft.KeyVault/vaults": Rule("rebuild", "HashiCorp Vault on a Public Cloud instance", "Leaseweb has no managed secrets service.", ["launchInstance"]),
    "Microsoft.Web/sites": Rule("rebuild", "App on a Public Cloud instance", "No managed app hosting or Functions equivalent.", ["launchInstance"]),
    "Microsoft.DocumentDB/databaseAccounts": Rule("rebuild", "Self-hosted MongoDB on a Public Cloud instance", "No managed Cosmos DB equivalent.", ["launchInstance"]),
    "Microsoft.ServiceBus/namespaces": Rule("rebuild", "Self-hosted RabbitMQ on a Public Cloud instance", "No managed messaging service.", ["launchInstance"]),
    "Microsoft.Sql/servers": Rule("rebuild", "Self-hosted database on a Public Cloud instance", "No managed Azure SQL equivalent.", ["launchInstance"]),
}

# Part of their VM in Leaseweb: no standalone resource to migrate.
FOLDED = {
    "Microsoft.Network/networkInterfaces",
    "Microsoft.Compute/disks",
    "Microsoft.Network/publicIPAddresses",
}


def assess(resources: list[Resource], ask: Callable = ask_json, ops: dict | None = None) -> list[Assessment]:
    results: list[Assessment] = []
    cache: dict[str, Rule] = {}
    for r in resources:
        if r.type in FOLDED:
            continue
        rule = RULES.get(r.type) or cache.get(r.type)
        if rule is None:
            ans = ask(
                f"Azure resource type {r.type} (name {r.name}). Can it migrate directly to Leaseweb "
                "(Public Cloud, Object Storage, private networks)? Reply JSON: "
                '{"route": "direct"|"rebuild", "target": str, "rationale": str, "lw_operations": [str]}'
            )
            rule = cache[r.type] = Rule(ans["route"], ans["target"], ans["rationale"], ans.get("lw_operations", []))
        results.append(Assessment(r.name, rule.route, rule.target, rule.rationale, list(rule.lw_operations)))
    return results
