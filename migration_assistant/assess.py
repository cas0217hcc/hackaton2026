from dataclasses import dataclass, field
from typing import Callable

from .claude_cli import ClaudeError, ask_json
from .leaseweb_ops import load_operations
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

# Part of their VM in Leaseweb: shown as 'included', nothing to migrate separately.
FOLDED = {
    "Microsoft.Network/networkInterfaces",
    "Microsoft.Compute/disks",
    "Microsoft.Network/publicIPAddresses",
}


def _rule_from_answer(ans: dict, ops: dict) -> Rule:
    """Validate Claude's verdict for an unknown type; never trust its shape or operation names."""
    try:
        route = str(ans["route"]).strip().lower()
        target, rationale = ans["target"], ans["rationale"]
    except KeyError as e:
        raise ClaudeError(f"claude answer missing field {e}") from None
    if route not in ("direct", "rebuild"):
        raise ClaudeError(f"claude returned invalid route '{ans['route']}'")
    claimed = ans.get("lw_operations", [])
    valid = [o for o in claimed if o in ops]
    dropped = [o for o in claimed if o not in ops]
    if dropped:
        rationale += f" (dropped unknown Leaseweb operations: {', '.join(dropped)})"
    return Rule(route, target, rationale, valid)


def assess(resources: list[Resource], ask: Callable = ask_json, ops: dict | None = None) -> list[Assessment]:
    ops = ops if ops is not None else load_operations()
    results: list[Assessment] = []
    cache: dict[str, Rule] = {}
    for r in resources:
        if r.type in FOLDED:
            results.append(Assessment(r.name, "included", "Included with the Public Cloud instance",
                                      "Created with the Leaseweb instance; nothing to migrate separately.", []))
            continue
        rule = RULES.get(r.type) or cache.get(r.type)
        if rule is None:
            ans = ask(
                f"Azure resource type {r.type} (name {r.name}). Can it migrate directly to Leaseweb "
                "(Public Cloud, Object Storage, private networks)? Reply JSON: "
                '{"route": "direct"|"rebuild", "target": str, "rationale": str, "lw_operations": [str]}'
            )
            rule = cache[r.type] = _rule_from_answer(ans, ops)
        results.append(Assessment(r.name, rule.route, rule.target, rule.rationale, list(rule.lw_operations)))
    return results
