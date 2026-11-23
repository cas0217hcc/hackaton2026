"""Mock Leaseweb: a fake Leaseweb API that follows the vendored specs (leaseweb-api/).

Requests are matched to spec operations by method and path, so an operation the specs do not have gets a 404,
as from Leaseweb. Answers are built from the spec's example responses, so they have the documented shape (a test
checks them against the response schemas). What is created is kept in memory: a launched instance shows up in the
instance list, starts CREATING and is RUNNING when next asked about, and deleting something unknown is a 404.
Operations without a handler below answer with their spec example.
"""
import copy
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from ..dryrun import path_matches, path_params
from ..leaseweb_ops import load_operations, load_responses
from ._pause import pause

SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "leaseweb-api"


@lru_cache(maxsize=4)
def _specs(specs_dir: Path) -> tuple[tuple, dict]:
    """Routes and responses from the specs, parsed once per folder (examples are deep-copied before use)."""
    # Templates without {params} first, so /instances is not taken for /instances/{instanceId}.
    routes = tuple(sorted(((m, t, op) for op, (m, t) in load_operations(specs_dir).items()),
                          key=lambda r: (r[1].count("{"), r[1])))
    return routes, load_responses(specs_dir)


def _error(status: int, message: str) -> tuple[int, dict]:
    return status, {"errorCode": str(status), "errorMessage": message, "correlationId": str(uuid.uuid4())}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FakeLeaseweb:
    """The fake API itself: handle(method, path, body) -> (status, JSON body or None). Thread-safe."""

    def __init__(self, specs_dir: Path = SPECS_DIR):
        self.routes, self.responses = _specs(Path(specs_dir))
        self.instances: dict[str, dict] = {}
        self.security_groups: dict[str, dict] = {}
        self.networks: dict[str, dict] = {}
        self.buckets: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def route(self, method: str, path: str) -> tuple[str | None, dict]:
        for m, template, op in self.routes:
            if m == method and path_matches(template, path):
                return op, path_params(template, path)
        return None, {}

    def example(self, op: str) -> tuple[int, object]:
        spec = self.responses.get(op) or {"status": 200, "example": None}
        return spec["status"], copy.deepcopy(spec["example"])

    def handle(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        op, params = self.route(method, path)
        if op is None:
            return _error(404, f"No Leaseweb operation for {method} {path}.")
        handler = getattr(self, "_" + re.sub(r"\W", "_", op), None)
        with self._lock:
            return handler(params, body or {}) if handler else self.example(op)

    # ---- instances

    def _launchInstance(self, p, body):
        status, inst = self.example("launchInstance")
        inst.update(id=str(uuid.uuid4()), state="CREATING", startedAt=None, hasPrivateNetwork=False, privateNetwork=None,
                    **{k: body[k] for k in ("region", "type", "reference", "rootDiskSize", "rootDiskStorageType") if k in body})
        if body.get("imageId"):
            inst["image"] = {**inst["image"], "id": body["imageId"]}
        self.instances[inst["id"]] = inst
        return status, copy.deepcopy(inst)

    def _getInstance(self, p, body):
        inst = self.instances.get(p["instanceId"])
        if inst is None:
            return _error(404, "Instance not found.")
        if inst["state"] == "CREATING":  # the first look after the launch finds it up, like a real launch a bit later
            inst.update(state="RUNNING", startedAt=_now())
        return 200, copy.deepcopy(inst)

    def _getInstanceList(self, p, body):
        status, page = self.example("getInstanceList")
        page["instances"] = [copy.deepcopy(i) for i in self.instances.values()]
        page["_metadata"] = {**page.get("_metadata", {}), "totalCount": len(self.instances), "offset": 0}
        return status, page

    def _terminateInstance(self, p, body):
        if self.instances.pop(p["instanceId"], None) is None:
            return _error(404, "Instance not found.")
        return self.example("terminateInstance")

    def _addToPrivateNetwork(self, p, body):
        inst = self.instances.get(p["instanceId"])
        if inst is None:
            return _error(404, "Instance not found.")
        if inst["state"] != "RUNNING":
            return _error(409, f"Instance is {inst['state']}; it can join a private network once it is RUNNING.")
        inst["hasPrivateNetwork"] = True
        return self.example("addToPrivateNetwork")

    # ---- security groups

    def _createSecurityGroup(self, p, body):
        status, group = self.example("createSecurityGroup")
        group.update(id=str(uuid.uuid4()), name=body.get("name", group.get("name", "")), state="ACTIVE")
        self.security_groups[group["id"]] = {**group, "rules": []}
        return status, group

    def _deleteSecurityGroup(self, p, body):
        if self.security_groups.pop(p["securityGroupId"], None) is None:
            return _error(404, "Security group not found.")
        return self.example("deleteSecurityGroup")

    def _authorizeSecurityGroupFirewallRules(self, p, body):
        group = self.security_groups.get(p["securityGroupId"])
        if group is None:
            return _error(404, "Security group not found.")
        group["rules"] += list(body.get("rules") or [])
        return self.example("authorizeSecurityGroupFirewallRules")

    # ---- private networks (no example in the spec: built from its schema's fields)

    def _post_privateNetworks(self, p, body):
        net = {"id": str(uuid.uuid4().int % 10**8), "name": body.get("name", ""), "createdAt": _now(), "updatedAt": _now(),
               "equipmentCount": 0, "servers": []}
        self.networks[net["id"]] = net
        return self.example("post/privateNetworks")[0], copy.deepcopy(net)

    def _delete_privateNetworks__privateNetworkId_(self, p, body):
        if self.networks.pop(p["privateNetworkId"], None) is None:
            return _error(404, "Private network not found.")
        return self.example("delete/privateNetworks/{privateNetworkId}")

    # ---- object storage

    def _createObjectStorageBucket(self, p, body):
        key = (p["objectStorageId"], str(body.get("name", "")))
        if key in self.buckets:
            return _error(409, f"Bucket {key[1]} already exists.")
        status, bucket = self.example("createObjectStorageBucket")
        bucket.update(name=key[1], isVersioningEnabled=bool(body.get("isVersioningEnabled", False)), creationTime=_now(),
                      objectCount=0)
        self.buckets[key] = bucket
        return status, copy.deepcopy(bucket)

    def _deleteObjectStorageBucket(self, p, body):
        if self.buckets.pop((p["objectStorageId"], p["bucketName"]), None) is None:
            return _error(404, "Bucket not found.")
        return self.example("deleteObjectStorageBucket")


class MockResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class MockHttp:
    """An HTTP client (the `request` method the app uses) that sends Leaseweb requests to a FakeLeaseweb.
    Other requests (the public Azure price list) go to `fallback`, or get a 404 when there is none."""

    fake = True  # create_app only accepts a preset key together with a client that says this

    def __init__(self, fallback=None, delay: float = 0.0, api: FakeLeaseweb | None = None):
        self._fallback, self.delay = fallback, delay
        self.api = api if api is not None else FakeLeaseweb()

    def request(self, method: str, url: str, **kwargs):
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host != "leaseweb.com" and not host.endswith(".leaseweb.com"):
            if self._fallback is not None:
                return self._fallback.request(method, url, **kwargs)
            return MockResponse(*_error(404, "Not available in mock mode."))
        pause(self.delay, 0.2)
        status, payload = self.api.handle(method.upper(), parts.path, kwargs.get("json"))
        return MockResponse(status, payload)
