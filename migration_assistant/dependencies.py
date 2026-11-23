"""Which resources must exist on Leaseweb before another one can be created.

Two sources, merged at the Assess stage:
- config: an Azure resource id of another discovered resource inside a resource's configuration
  (a VM's NIC -> subnet -> vnet, a vnet subnet -> its NSG). Certain.
- ai: links only visible in app settings or naming (an app reading a Key Vault, a function
  consuming a storage queue). Validated: unknown names, self-links and cycles are dropped.
Included resources (NIC, disk, public IP) are folded into their owner, both as source and target.
"""
import json

from .prompt import Prompt
import re
from typing import Any, Callable

from .assess import owner_name
from .claude_cli import ClaudeError
from .models import Assessment, Resource

_ARM_ID = re.compile(r"/subscriptions/[^/\"]+/resourceGroups/[^/\"]+/providers/[^\"]+", re.I)
MAX_PROPS = 2500  # per resource in the AI prompt


def _ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(m.group(0).lower() for m in _ARM_ID.finditer(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _ids(v)
    elif isinstance(value, list):
        for v in value:
            found |= _ids(v)
    return found


def _resolver(resources: list[Resource]) -> Callable[[str], str | None]:
    """Map an ARM id (possibly of a child, e.g. a subnet) to the discovered resource it belongs to."""
    by_id = sorted(((r.id.lower(), r.name) for r in resources if r.id), key=lambda x: -len(x[0]))

    def resolve(arm_id: str) -> str | None:
        for rid, name in by_id:
            if arm_id == rid or arm_id.startswith(rid + "/"):
                return name
        return None

    return resolve


def config_links(resources: list[Resource]) -> list[tuple[str, str]]:
    """(resource, depends_on) pairs read from configurations."""
    resolve = _resolver(resources)
    links = []
    for r in resources:
        for arm_id in sorted(_ids(r.properties)):
            target = resolve(arm_id)
            if target and target != r.name:
                links.append((r.name, target))
    return links


def ai_links(resources: list[Resource], assessments: list[Assessment], ask: Callable) -> list[tuple[str, str, str]]:
    """(resource, depends_on, reason) proposed by the AI; shape is checked, names are checked by the caller."""
    routes = {a.resource_name: a.route for a in assessments}
    lines = []
    for r in resources:
        props = json.dumps(r.properties, default=str)[:MAX_PROPS]
        lines.append(f"- {r.name} ({r.type}, route {routes.get(r.name, '?')}): {props}")
    ans = ask(Prompt(
        "These Azure resources are being migrated to Leaseweb. On Leaseweb they are created one by one, "
        "so a resource can only be created after the resources it needs exist (a VM needs its network, "
        "an app needs the database, vault, storage or queue it connects to).\n"
        "Using the configurations below (ids, app settings, endpoints, names), list every dependency "
        "between these resources. Only use the resource names given. Do not list a resource as depending "
        "on itself, and never make a cycle.\n" + "\n".join(lines) + "\n"
        'Reply JSON: {"dependencies": [{"resource": str, "depends_on": str, "reason": str}]}',
        "dependencies", resources=resources, routes=routes))
    out = []
    for d in ans.get("dependencies") or [] if isinstance(ans, dict) else []:
        if isinstance(d, dict) and isinstance(d.get("resource"), str) and isinstance(d.get("depends_on"), str):
            out.append((d["resource"], d["depends_on"], str(d.get("reason") or "")))
    return out


def _reaches(graph: dict[str, set[str]], start: str, goal: str) -> bool:
    seen, todo = set(), [start]
    while todo:
        n = todo.pop()
        if n == goal:
            return True
        if n not in seen:
            seen.add(n)
            todo.extend(graph.get(n, ()))
    return False


def waves(names: list[str], graph: dict[str, set[str]]) -> dict[str, int]:
    """0 for resources that need nothing, else 1 + the highest wave they depend on. Graph must be acyclic."""
    memo: dict[str, int] = {}

    def wave(n: str) -> int:
        if n not in memo:
            memo[n] = 1 + max((wave(d) for d in graph.get(n, ())), default=-1)
        return memo[n]

    return {n: wave(n) for n in names}


def add_dependencies(resources: list[Resource], assessments: list[Assessment],
                     ask: Callable | None = None) -> str:
    """Fill `dependencies` and `wave` on each non-included assessment. Returns a note for the user
    ('' when all went well). An AI failure is not fatal: the config links are kept."""
    names = {a.resource_name for a in assessments}
    included = {a.resource_name for a in assessments if a.route == "included"}
    by_name = {r.name: r for r in resources}

    def fold(name: str) -> str | None:
        seen = set()
        while name in included and name not in seen:  # NIC -> VM, public IP -> NIC -> VM
            seen.add(name)
            owner = owner_name(by_name[name]) if name in by_name else ""
            if not owner or owner not in names:
                return None
            name = owner
        return None if name in included else name

    candidates = [(a, b, "", "config") for a, b in config_links(resources)]
    note = ""
    if ask is not None:
        try:
            ai = ai_links(resources, assessments, ask)
            unknown = sorted({n for a, b, _ in ai for n in (a, b) if n not in names})
            candidates += [(a, b, why, "ai") for a, b, why in ai if a in names and b in names]
            if unknown:
                note = f"Ignored AI dependencies on unknown resources: {', '.join(unknown)}."
        except ClaudeError as e:
            note = f"AI dependency check failed ({e}); only dependencies found in the configuration are shown."

    graph: dict[str, set[str]] = {}
    found: dict[str, dict[str, dict]] = {}
    dropped = []
    for a, b, why, src in candidates:
        a, b = fold(a), fold(b)
        if not a or not b or a == b:
            continue
        if b in graph.get(a, set()):  # config links come first and win
            continue
        if _reaches(graph, b, a):
            dropped.append(f"{a} -> {b}")
            continue
        graph.setdefault(a, set()).add(b)
        reason = why or f"its configuration references {b}"
        found.setdefault(a, {})[b] = {"name": b, "reason": reason, "source": src}
    if dropped:
        note = (note + " " if note else "") + f"Dropped dependencies that would form a cycle: {', '.join(dropped)}."

    order = waves(sorted(names - included), graph)
    for a in assessments:
        if a.route == "included":
            a.dependencies, a.wave = [], None
        else:
            a.dependencies = sorted(found.get(a.resource_name, {}).values(), key=lambda d: d["name"])
            a.wave = order[a.resource_name]
    return note
