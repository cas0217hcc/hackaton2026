import re
from typing import Any, Protocol

import httpx

from .leaseweb_ops import load_operations
from .models import Assessment, DryRunCall

# Placeholder request values until a real Leaseweb account and API key exist.
PLACEHOLDER_BODIES = {
    "launchInstance": {"region": "eu-west-3", "type": "lsw.c3.large", "imageId": "UBUNTU_22_04_64BIT", "contractType": "HOURLY", "rootDiskSize": 50, "rootDiskStorageType": "CENTRAL", "reference": "<instance-name>"},
    "createObjectStorageBucket": {"name": "<bucket-name>", "isVersioningEnabled": False},
    "createSecurityGroup": {"name": "<security-group-name>"},
    "post/privateNetworks": {"name": "<network-name>"},
    "authorizeSecurityGroupFirewallRules": {"rules": [{"protocol": "TCP", "startPort": 443, "endPort": 443, "source": "0.0.0.0/0"}]},
}


# Operations whose response `id` feeds a path parameter of later calls. Order = run order.
PRODUCES = {"post/privateNetworks": "privateNetworkId", "createSecurityGroup": "securityGroupId", "launchInstance": "instanceId"}
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+")


def annotate_chain(calls: list[DryRunCall]) -> list[DryRunCall]:
    """Record, per call, which earlier operation will supply each of its {path params}."""
    for i, c in enumerate(calls):
        c.chained = {}
        for param in re.findall(r"\{([^}/]+)\}", c.path):
            for earlier in calls[:i]:
                if PRODUCES.get(earlier.operation_id) == param:
                    c.chained[param] = earlier.operation_id
    return calls


def build_calls(assessments: list[Assessment], ops: dict | None = None) -> list[DryRunCall]:
    """One DryRunCall per Leaseweb operation of each Direct resource, producers first."""
    ops = ops if ops is not None else load_operations()
    calls = []
    for a in assessments:
        if a.route != "direct":
            continue
        for op in a.lw_operations:
            method, path = ops[op]
            calls.append(DryRunCall(method, path, op, dict(PLACEHOLDER_BODIES.get(op, {}))))
    order = list(PRODUCES)
    calls.sort(key=lambda c: order.index(c.operation_id) if c.operation_id in order else len(order))
    return annotate_chain(calls)


class Executor(Protocol):
    def execute(self, call: DryRunCall) -> dict: ...


class DryRunExecutor:
    """Default executor: records what would be sent, sends nothing."""

    def execute(self, call: DryRunCall) -> dict:
        return {"dry_run": True, "sent": False, "method": call.method, "path": call.path,
                "operation_id": call.operation_id, "body": call.body}


BASE_URL = "https://api.leaseweb.com"


def unresolved(call: DryRunCall) -> list[str]:
    """Placeholders still left in a call: {pathParam} in the path and <value> inside the body."""
    found = re.findall(r"\{[^}/]+\}", call.path)

    def walk(v: Any) -> None:
        if isinstance(v, str):
            found.extend(re.findall(r"<[^<>]+>", v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(call.body)
    return found


def path_matches(template: str, path: str) -> bool:
    """True if `path` is `template` with every {param} filled by one non-empty segment."""
    parts = re.split(r"\{[^}/]+\}", template)
    return re.fullmatch("[^/]+".join(re.escape(p) for p in parts), path) is not None


class LeasewebExecutor:
    """Live executor: sends calls to the Leaseweb API with the user's key.

    Calls that still contain placeholders are skipped, never guessed. The key is
    only ever put in the request header and is masked out of any error text.
    """

    def __init__(self, api_key: str, http: Any = None, base_url: str = BASE_URL, timeout: int = 30):
        self._key = api_key
        self._http = http if http is not None else httpx.Client()
        self._base = base_url
        self._timeout = timeout

    def execute(self, call: DryRunCall) -> dict:
        base = {"dry_run": False, "method": call.method, "path": call.path, "operation_id": call.operation_id}
        missing = unresolved(call)
        if missing:
            return {**base, "sent": False, "skipped": True, "reason": "needs values: " + ", ".join(missing)}
        kwargs: dict = {"headers": {"X-LSW-Auth": self._key, "Accept": "application/json"}, "timeout": self._timeout}
        if call.body:
            kwargs["json"] = call.body
        try:
            resp = self._http.request(call.method, self._base + call.path, **kwargs)
        except Exception as e:  # network/TLS errors: report, never raise, never leak the key
            return {**base, "sent": False, "error": str(e).replace(self._key, "***")}
        try:
            payload = resp.json()
        except Exception:
            payload = resp.text[:500]
        return {**base, "sent": True, "status": resp.status_code, "response": payload}


def run_calls(calls: list[DryRunCall], executor: Executor) -> list[dict]:
    """Run calls in order, filling {path params} from earlier responses (live runs only produce ids)."""
    ids: dict[str, str] = {}
    results = []
    for c in calls:
        path = c.path
        for param, value in ids.items():
            path = path.replace("{" + param + "}", value)
        result = executor.execute(DryRunCall(c.method, path, c.operation_id, c.body, c.chained))
        if result.get("skipped"):
            for param, producer in c.chained.items():
                if "{" + param + "}" in path:
                    result["reason"] += f" ({param} comes from {producer}, which did not succeed)"
        resp = result.get("response")
        if (result.get("sent") and 200 <= result.get("status", 0) < 300 and isinstance(resp, dict)
                and c.operation_id in PRODUCES and _SAFE_ID.fullmatch(str(resp.get("id", "")))):
            ids[PRODUCES[c.operation_id]] = str(resp["id"])
        results.append(result)
    return results
