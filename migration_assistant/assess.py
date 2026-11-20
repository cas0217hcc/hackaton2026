import re
from concurrent.futures import ThreadPoolExecutor
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
    "Microsoft.OperationalInsights/workspaces": Rule("rebuild", "Grafana with Loki and Prometheus on a Public Cloud instance", "Leaseweb has no managed log analytics service.", ["launchInstance"]),
    "Microsoft.Insights/components": Rule("rebuild", "Grafana with Loki and Prometheus on a Public Cloud instance", "Leaseweb has no managed application monitoring service.", ["launchInstance"]),
}

# A storage account that holds more than blobs: a bucket alone would lose its queues, tables or shares.
STORAGE_TYPE = "Microsoft.Storage/storageAccounts"
NON_BLOB = {"queues": "queues", "tables": "tables", "shares": "file shares"}

# Nothing to create on Leaseweb on their own: they come with, or are replaced inside, another resource.
INCLUDED_RULES: dict[str, tuple[str, str]] = {
    "Microsoft.Web/serverFarms": ("Part of the app that runs on it", "The plan's compute becomes the app's Public Cloud instance."),
    "Microsoft.ManagedIdentity/userAssignedIdentities": ("Replaced by credentials stored in Vault", "Leaseweb has no managed identities; apps read their credentials from Vault instead."),
    "Microsoft.Network/privateEndpoints": ("Part of the private network", "Services on a Leaseweb private network are reached directly; no endpoint is needed."),
    "Microsoft.Network/privateDnsZones": ("Part of the private network", "Use the instances' private IPs, or a DNS server on the private network."),
    "Microsoft.Network/privateDnsZones/virtualNetworkLinks": ("Part of the private network", "Comes with its private DNS zone; nothing to migrate separately."),
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


def _last(resource_id: str, kind: str) -> str:
    """Name that follows `/<kind>/` in an Azure resource id, or ''."""
    m = re.search(rf"/{kind}/([^/]+)", resource_id or "", re.I)
    return m.group(1) if m else ""


def owner_name(r: Resource) -> str:
    """Name of the resource a folded NIC, disk or public IP belongs to, or ''."""
    return _owner_ref(r)[1]


def _owner(r: Resource) -> str:
    """What a folded NIC, disk or public IP belongs to, read from its configuration."""
    kind, name = _owner_ref(r)
    return f"{kind} {name}" if name else ""


def _owner_ref(r: Resource) -> tuple[str, str]:
    props = r.properties or {}
    inner = props.get("properties") or {}
    candidates = [
        ("virtual machine", _last((inner.get("virtualMachine") or {}).get("id", ""), "virtualMachines")),
        ("private endpoint", _last((inner.get("privateEndpoint") or {}).get("id", ""), "privateEndpoints")),
        ("virtual machine", _last(props.get("managedBy") or "", "virtualMachines")),
        ("network interface", _last((inner.get("ipConfiguration") or {}).get("id", ""), "networkInterfaces")),
    ]
    for kind, name in candidates:
        if name:
            return kind, name
    return "", ""


def _storage_rule(r: Resource) -> Rule | None:
    """Rebuild for a storage account that uses queues, tables or file shares; None for blobs only (or unknown)."""
    services = (r.properties or {}).get("services") or {}
    used = [label for kind, label in NON_BLOB.items() if services.get(kind)]
    if not used:
        return None
    target = ("Object Storage for the blobs, plus RabbitMQ on a Public Cloud instance for the queues" if services.get("queues")
              else "Object Storage for the blobs, plus self-hosted services on a Public Cloud instance")
    return Rule("rebuild", target,
                f"Object Storage replaces blobs only; this account also holds {' and '.join(used)}, "
                "which need their own service.",
                ["createObjectStorageBucket", "launchInstance"])


def _known_rule(r: Resource) -> Rule | None:
    if r.type == STORAGE_TYPE:
        return _storage_rule(r) or RULES[STORAGE_TYPE]
    return RULES.get(r.type)


def assess(resources: list[Resource], ask: Callable = ask_json, ops: dict | None = None, workers: int = 4) -> list[Assessment]:
    ops = ops if ops is not None else load_operations()

    def ask_type(r: Resource) -> Rule:
        ans = ask(
            f"Azure resource type {r.type} (name {r.name}). Can it migrate directly to Leaseweb "
            "(Public Cloud, Object Storage, private networks)? Reply JSON: "
            '{"route": "direct"|"rebuild", "target": str, "rationale": str, "lw_operations": [str]}'
        )
        return _rule_from_answer(ans, ops)

    # One AI question per unknown type, asked in parallel (the first resource of each type is the example).
    unknown: dict[str, Resource] = {}
    for r in resources:
        if r.type not in FOLDED and r.type not in INCLUDED_RULES and _known_rule(r) is None:
            unknown.setdefault(r.type, r)
    cache: dict[str, Rule] = {}
    if unknown:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(unknown)))) as pool:
            cache = dict(zip(unknown, pool.map(ask_type, unknown.values())))

    results: list[Assessment] = []
    for r in resources:
        if r.type in FOLDED:
            owner = _owner(r)
            results.append(Assessment(
                r.name, "included", f"Part of {owner}" if owner else "Part of the resource it is attached to",
                "Comes with its owner on Leaseweb; nothing to migrate separately.", []))
            continue
        if r.type in INCLUDED_RULES:
            target, rationale = INCLUDED_RULES[r.type]
            results.append(Assessment(r.name, "included", target, rationale, []))
            continue
        rule = _known_rule(r) or cache[r.type]
        results.append(Assessment(r.name, rule.route, rule.target, rule.rationale, list(rule.lw_operations)))
    return results
