import json
import re
import shlex
import time
from typing import Any, Callable, Protocol

import httpx

from .cloudinit import user_data_for
from .leaseweb_ops import load_operations
from .models import Assessment, DryRunCall, Plan, Resource

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


# Azure location -> nearest Leaseweb Public Cloud region. Unknown locations keep the default region.
REGION_BY_AZURE_LOCATION = {
    "westeurope": "eu-west-3",            # Netherlands -> Amsterdam
    "germanywestcentral": "eu-central-1",  # Frankfurt
    "uksouth": "eu-west-2", "ukwest": "eu-west-2", "northeurope": "eu-west-2",  # London
    "eastus": "us-east-1", "eastus2": "us-east-1",  # Virginia -> Washington
    "westus": "us-west-1", "westus2": "us-west-1",  # San Francisco
    "southeastasia": "ap-southeast-1",    # Singapore
    "canadacentral": "ca-central-1", "canadaeast": "ca-central-1",  # Montreal
    "japaneast": "ap-northeast-1",
}


def _prefill(op: str, body: dict, name: str, resource: Resource | None) -> None:
    """Fill what Discover already knows, so the user does not retype it: names, region, disk size."""
    for key, value in body.items():
        if isinstance(value, str) and value.startswith("<") and value.endswith("-name>"):
            body[key] = name
    if op != "launchInstance" or resource is None:
        return
    region = REGION_BY_AZURE_LOCATION.get((resource.location or "").lower())
    if region:
        body["region"] = region
    try:
        size = resource.properties["properties"]["storageProfile"]["osDisk"]["diskSizeGB"]
    except (KeyError, TypeError):
        size = None
    if isinstance(size, int) and 5 <= size <= 1000:  # the range the Leaseweb spec allows
        body["rootDiskSize"] = size


def _usable_plan(p: Plan) -> bool:
    return bool(p.proposal) or not (p.warnings and p.warnings[0].startswith("Plan failed: "))


def build_calls(assessments: list[Assessment], ops: dict | None = None,
                resources: list[Resource] | None = None, plans: list[Plan] | None = None) -> list[DryRunCall]:
    """One DryRunCall per Leaseweb operation of each Direct resource, producers first.

    Rebuild resources with a plan add the creating calls of that plan (the instance that hosts the
    replacement, a bucket, ...), so the infrastructure part of a rebuild is automated too. Only
    operations this module knows how to fill are taken; everything else in a plan stays manual."""
    ops = ops if ops is not None else load_operations()
    by_name = {r.name: r for r in resources or []}
    plan_of = {p.resource_name: p for p in plans or [] if _usable_plan(p)}
    calls = []
    for a in assessments:
        if a.route == "direct":
            wanted = list(a.lw_operations)
        elif a.route == "rebuild" and a.resource_name in plan_of:
            wanted = [op for op in dict.fromkeys(plan_of[a.resource_name].lw_operations) if op in PLACEHOLDER_BODIES]
        else:
            continue
        for op in wanted:
            if op not in ops:
                continue
            method, path = ops[op]
            body = json.loads(json.dumps(PLACEHOLDER_BODIES.get(op, {})))  # deep copy: the nested lists are shared
            _prefill(op, body, a.resource_name, by_name.get(a.resource_name))
            if op == "launchInstance" and a.route == "rebuild":
                script = user_data_for(a.target)
                if script:
                    body["userData"] = script
            calls.append(DryRunCall(method, path, op, body, source=a.resource_name))
    return annotate_chain(order_calls(calls, assessments))


def order_calls(calls: list[DryRunCall], assessments: list[Assessment]) -> list[DryRunCall]:
    """Topological order: a call runs after the calls producing its {path params} and after the
    creating calls of every resource its source depends on (found at Assess). Ties: earlier wave,
    then producers in PRODUCES order, then input order. A cycle falls back to the PRODUCES order."""
    kinds = list(PRODUCES)
    wave = {a.resource_name: a.wave or 0 for a in assessments}
    needs = {a.resource_name: {d["name"] for d in a.dependencies} for a in assessments}
    before: list[set[int]] = [set() for _ in calls]
    for i, c in enumerate(calls):
        params = set(re.findall(r"\{([^}/]+)\}", c.path))
        for j, d in enumerate(calls):
            if j != i and d.operation_id in PRODUCES and (
                    PRODUCES[d.operation_id] in params or d.source in needs.get(c.source, ())):
                before[i].add(j)
    key = lambda i: (wave.get(calls[i].source, 0),
                     kinds.index(calls[i].operation_id) if calls[i].operation_id in kinds else len(kinds), i)
    out: list[int] = []
    while len(out) < len(calls):
        ready = [i for i in range(len(calls)) if i not in out and before[i] <= set(out)]
        if not ready:
            return sorted(calls, key=lambda c: kinds.index(c.operation_id) if c.operation_id in kinds else len(kinds))
        out.append(min(ready, key=key))
    return [calls[i] for i in out]


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

    def __init__(self, api_key: str, http: Any = None, base_url: str = BASE_URL, timeout: int = 30,
                 wait_timeout: float = 0, poll_every: float = 10, sleep: Callable[[float], None] = time.sleep):
        self._key = api_key
        self._http = http if http is not None else httpx.Client()
        self._base = base_url
        self._timeout = timeout
        self._wait_timeout = wait_timeout  # 0: never wait for an instance to come up
        self._poll_every = poll_every
        self._sleep = sleep

    def wait_ready(self, instance_id: str) -> str | None:
        """Poll getInstance until the instance is RUNNING. None when it is, else why not.
        launchInstance answers while the instance is still CREATING, and calls that attach it to a
        network or security group fail until it runs."""
        if self._wait_timeout <= 0:
            return None
        waited, state = 0.0, "unknown"
        while True:
            try:
                resp = self._http.request("GET", f"{self._base}/publicCloud/v1/instances/{instance_id}",
                                          headers={"X-LSW-Auth": self._key, "Accept": "application/json"},
                                          timeout=self._timeout)
                state = (str((resp.json() or {}).get("state", "unknown")) if resp.status_code == 200
                         else f"HTTP {resp.status_code}")
            except Exception as e:  # keep polling through a network blip, never leak the key
                state = str(e).replace(self._key, "***")
            if state == "RUNNING":
                return None
            if state in ("FAILED", "DESTROYED", "DESTROYING"):
                return f"instance {instance_id} is {state}"
            if waited >= self._wait_timeout:
                return f"instance {instance_id} was still {state} after {int(waited)}s"
            self._sleep(self._poll_every)
            waited += self._poll_every

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


# What removes a resource a call created (all of these are operations in the specs).
TEARDOWN = {
    "launchInstance": "terminateInstance",
    "createSecurityGroup": "deleteSecurityGroup",
    "post/privateNetworks": "delete/privateNetworks/{privateNetworkId}",
    "createObjectStorageBucket": "deleteObjectStorageBucket",
}
_PARAM = re.compile(r"\{([^}/]+)\}")


def path_params(template: str, path: str) -> dict[str, str]:
    """{param: value} read from a path that fills `template`; {} if it does not match."""
    names = _PARAM.findall(template)
    parts = _PARAM.split(template)[::2]
    m = re.fullmatch("([^/]+)".join(re.escape(p) for p in parts), path)
    return dict(zip(names, m.groups())) if m else {}


def _created(c: DryRunCall, sent_path: str, resp: Any) -> dict | None:
    """What a successful creating call made, with the values its delete call needs."""
    if c.operation_id not in TEARDOWN:
        return None
    params = path_params(c.path, sent_path)
    if c.operation_id in PRODUCES:
        if not (isinstance(resp, dict) and _SAFE_ID.fullmatch(str(resp.get("id", "")))):
            return None
        params[PRODUCES[c.operation_id]] = str(resp["id"])
    if c.operation_id == "createObjectStorageBucket":
        m = re.search(r"/objectStorages/([^/]+)/buckets$", sent_path)  # the UI fills this in before sending
        if m:
            params["objectStorageId"] = m.group(1)
        name = str((c.body or {}).get("name", ""))
        if not _SAFE_ID.fullmatch(name) or not _SAFE_ID.fullmatch(params.get("objectStorageId", "")):
            return None
        params["bucketName"] = name
    return {"operation_id": c.operation_id, "source": c.source, "params": params}


def run_calls(calls: list[DryRunCall], executor: Executor, ids: dict[str, str] | None = None,
              created: list[dict] | None = None) -> list[dict]:
    """Run calls in order, filling {path params} from earlier responses (live runs only produce ids).

    `ids` can be shared between runs so a single call can use ids produced by an earlier run.
    `created` collects what live calls made, so it can be torn down later.
    """
    ids = {} if ids is None else ids
    results = []
    for i, c in enumerate(calls):
        path = c.path
        for param, value in ids.items():
            path = path.replace("{" + param + "}", value)
        result = executor.execute(DryRunCall(c.method, path, c.operation_id, c.body, c.chained, c.source))
        if result.get("skipped"):
            for param, producer in c.chained.items():
                if "{" + param + "}" in path:
                    result["reason"] += f" ({param} comes from {producer}, which has not succeeded yet)"
        resp = result.get("response")
        ok = bool(result.get("sent")) and 200 <= result.get("status", 0) < 300
        if ok and not result.get("dry_run") and created is not None:
            made = _created(c, path, resp)
            if made:
                created.append(made)
        if c.operation_id in PRODUCES and not result.get("dry_run"):
            if ok and isinstance(resp, dict) and _SAFE_ID.fullmatch(str(resp.get("id", ""))):
                param = PRODUCES[c.operation_id]
                ids[param] = str(resp["id"])
                # An instance must be running before later calls in this run attach things to it.
                later = any("{" + param + "}" in d.path for d in calls[i + 1:])
                if param == "instanceId" and later and hasattr(executor, "wait_ready"):
                    problem = executor.wait_ready(ids[param])
                    if problem:
                        result["ready_error"] = problem
                        ids.pop(param, None)  # its dependents are then skipped instead of failing on it
            else:
                # A producer that did not succeed now must not leave an id from an older run behind:
                # its dependents would act on the wrong resource.
                ids.pop(PRODUCES[c.operation_id], None)
        results.append(result)
    return results


def teardown_calls(created: list[dict], ops: dict) -> list[tuple[dict, DryRunCall]]:
    """Delete calls for what live runs created, newest first (instances go before their networks)."""
    out = []
    for item in reversed(created):
        op = TEARDOWN.get(item.get("operation_id", ""))
        if not op or op not in ops:
            continue
        method, path = ops[op]
        params = item.get("params") or {}
        for name in _PARAM.findall(path):
            if name in params:
                path = path.replace("{" + name + "}", params[name])
        out.append((item, DryRunCall(method, path, op, {}, source=item.get("source", ""))))
    return out


def curl_script(calls: list[DryRunCall]) -> str:
    """A bash script that sends the calls with curl. The key comes from $LSW_API_KEY, never from here.
    Ids flow between calls through shell variables; a call that still needs values is commented out."""
    lines = ["#!/usr/bin/env bash",
             "# Leaseweb calls exported by the Azure to Leaseweb Migration Assistant.",
             "# Usage: LSW_API_KEY=... bash leaseweb-calls.sh   (needs curl and jq)",
             "set -euo pipefail",
             ': "${LSW_API_KEY:?Set LSW_API_KEY to your Leaseweb API key}"',
             f'BASE="{BASE_URL}"', ""]
    produced: set[str] = set()
    for n, c in enumerate(calls, 1):
        path = _PARAM.sub(lambda m: "${" + m.group(1) + "}", c.path)
        cmd = [f'curl -sS --fail-with-body -X {c.method} "$BASE{path}"', '-H "X-LSW-Auth: $LSW_API_KEY"',
               "-H 'Accept: application/json'"]
        if c.body:
            cmd += ["-H 'Content-Type: application/json'", "--data " + shlex.quote(json.dumps(c.body))]
        text = " \\\n  ".join(cmd)
        out = PRODUCES.get(c.operation_id)
        if out:
            text = f"{out}=$({text} | jq -r .id)\necho \"{out}=${{{out}}}\""
        title = f"# {n}. {c.operation_id}" + (f" for {c.source}" if c.source else "")
        needs = [v for v in unresolved(c) if v.startswith("<")]
        needs += ["{" + p + "}" for p in _PARAM.findall(c.path) if p not in produced]
        if needs:
            text = "\n".join("# " + x for x in text.splitlines())
            title += f"  (fill in {', '.join(needs)}, then uncomment)"
        elif out:
            produced.add(out)
        lines += [title, text, ""]
    return "\n".join(lines)
