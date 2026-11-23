"""Mock mode: try the app without some or all of its outside services. Each part is switched on by itself:

- MOCK_AZURE=1     Discover reads mock_data/hackaton-2026-rg.json (a scrubbed copy of the real group) instead of `az`.
- MOCK_AI=1        Every AI question gets a canned answer from `mock_ask`, shaped like the real prompts expect. No tokens.
- MOCK_LEASEWEB=1  A mock key is set, and calls go to `MockHttp`, a fake Leaseweb API. Nothing is sent to Leaseweb.
- MOCK_MODE=1      All three.

They can be set in the environment, in .env, or with the start scripts (--mock, --mock-azure, ...). Results are saved
to data/mock-state.json, so real results are not overwritten.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .azure_discovery import DiscoveryError
from .models import Resource

PARTS = ("azure", "ai", "leaseweb")
TRUE = ("1", "true", "yes", "on")
MOCK_STATE_FILE = Path("data/mock-state.json")
FIXTURE = Path(__file__).parent / "mock_data" / "hackaton-2026-rg.json"
MOCK_SUB = "00000000-0000-4000-8000-000000000000"
MOCK_PROVIDER = {"id": "mock", "label": "Mock AI", "available": True, "detail": "canned answers, no tokens spent"}
MOCK_KEY = "mock-leaseweb-key"
DESCRIBE = {"azure": "Azure is a saved copy of hackaton-2026-rg (az is not used)",
            "ai": "the AI gives canned answers (no tokens are spent)",
            "leaseweb": "Leaseweb is a fake API with a mock key (nothing is sent)"}


def mock_parts(environ=None) -> set[str]:
    """Which parts are mocked: MOCK_MODE turns on all of them, MOCK_AZURE / MOCK_AI / MOCK_LEASEWEB one each."""
    environ = os.environ if environ is None else environ
    on = lambda name: str(environ.get(name, "")).strip().lower() in TRUE
    return set(PARTS) if on("MOCK_MODE") else {p for p in PARTS if on(f"MOCK_{p.upper()}")}


def describe(parts) -> str:
    """One sentence for the banner and the console."""
    mocked = [DESCRIBE[p] for p in PARTS if p in parts]
    real = [p.capitalize() if p != "ai" else "AI" for p in PARTS if p not in parts]
    text = "Mock mode: " + "; ".join(mocked) + "."
    return text + (f" Real: {', '.join(real)}." if real else " Nothing leaves this machine.")


def _delay(seconds: float) -> None:
    """Short pauses so the loading states are visible. MOCK_DELAY scales them (0 turns them off)."""
    try:
        scale = float(os.environ.get("MOCK_DELAY", "1"))
    except ValueError:
        scale = 1.0
    if scale > 0:
        time.sleep(seconds * scale)


# ---- Azure: the saved resource group

def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def mock_discover(resource_group: str, subscription: str | None = None) -> list[Resource]:
    data = _fixture()
    if resource_group != data["resource_group"]:
        raise DiscoveryError(f"Mock Azure only has the resource group '{data['resource_group']}'.")
    _delay(0.8)
    return [Resource(**r) for r in data["resources"]]


def mock_groups(subscription: str | None = None) -> list[dict]:
    data = _fixture()
    return [{"name": data["resource_group"], "location": data["location"]}]


def mock_azure_status() -> dict:
    return {"installed": True, "signed_in": True, "user": "mock.user@example.com",
            "subscription": {"id": MOCK_SUB, "name": "Mock subscription"}, "tenant": "mock-tenant", "message": ""}


def mock_subscriptions() -> list[dict]:
    return [{"id": MOCK_SUB, "name": "Mock subscription", "is_default": True}]


# ---- AI: canned answers, shaped like what each prompt asks for

ASSESS_ANSWERS = {  # lower-case Azure type -> (route, target, rationale) for types the rules do not cover
    "microsoft.app/containerapps": ("rebuild", "Container on a Public Cloud instance behind Caddy",
                                    "Leaseweb has no managed container hosting, so the API runs as a Docker container on an "
                                    "instance, with Caddy for HTTPS."),
    "microsoft.app/managedenvironments": ("rebuild", "Docker host on a Public Cloud instance",
                                          "A Container Apps environment has no Leaseweb equivalent; one Docker host on the "
                                          "private network runs the containers."),
    "microsoft.insights/actiongroups": ("rebuild", "Alert rules in Grafana on the monitoring instance",
                                        "Leaseweb has no managed alerting; the Smart Detection receivers become Grafana "
                                        "alert contact points."),
    "microsoft.eventgrid/systemtopics": ("rebuild", "Bucket notifications, or polling, on a Public Cloud instance",
                                         "Event Grid system topics forward storage events. Leaseweb Object Storage has no "
                                         "Event Grid, so a small consumer on an instance takes their place."),
    "microsoft.containerregistry/registries": ("rebuild", "Harbor registry on a Public Cloud instance",
                                               "Leaseweb has no managed container registry, so images move to a "
                                               "self-hosted Harbor."),
}


def _assess_answer(prompt: str) -> dict:
    m = re.search(r"Azure resource type (\S+) \(name", prompt)
    rtype = (m.group(1) if m else "").lower()
    route, target, why = ASSESS_ANSWERS.get(rtype, ("rebuild", "Self-hosted service on a Public Cloud instance",
                                                    "No managed equivalent on Leaseweb, so it runs on its own instance."))
    return {"route": route, "target": target, "rationale": f"{why} (mock answer)", "lw_operations": ["launchInstance"]}


_DEP_LINE = re.compile(r"^- (.+?) \(([^,()]+), route (\w+)\): (.*)$", re.M)
_ARM_ID = re.compile(r"/subscriptions/[^\"\s]+")  # links by id come from the configuration already


def _dependencies_answer(prompt: str) -> dict:
    """What a careful reader would find: a resource needs another when its settings name it (an endpoint, a vault
    URI, an account name). Links by ARM id are already found from the configuration, so only names are added."""
    rows = [(name, rtype, route, _ARM_ID.sub("", props.lower())) for name, rtype, route, props in _DEP_LINE.findall(prompt)]
    live = [r for r in rows if r[2] != "included"]
    out = []
    for name, _, _, props in live:
        for other, otype, _, _ in live:
            if other != name and len(other) > 5 and other.lower() in props:
                kind = otype.split("/")[-1]
                out.append({"resource": name, "depends_on": other,
                            "reason": f"its settings name {other} ({kind}) (mock answer)"})
    return {"dependencies": out}


def _comment(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        return "//"
    if suffix in {".py", ".sh", ".ps1", ".tf", ".toml", ".yaml", ".yml"} or path.endswith("requirements.txt"):
        return "#"
    return None


# (word in the type) -> words that mark the file using it; the first file that has one gets the change.
_KEYWORDS = {"documentdb": ("cosmosclient", "cosmos"), "keyvault": ("secretclient", "keyvault"),
             "storage": ("queueclient", "queue_name", "queue"), "containerapps": ("fastapi",),
             "web/sites": ("azure.functions",), "insights/components": ("applicationinsights", "opentelemetry"),
             "eventgrid": ("eventgrid", "blob_trigger")}


def _code_change(rtype: str, target: str, files: dict[str, str]) -> list[dict]:
    """One small diff that really applies: a TODO comment after the first line of the best matching file."""
    words = next((w for k, w in _KEYWORDS.items() if k in rtype.lower()), ())
    candidates = [f for f in files if _comment(f)]
    match = next((f for f in candidates if any(w in files[f].lower() for w in words)), None)
    if not match:
        return []
    lines = files[match].split("\n")
    mark = _comment(match)
    # Context on both sides of the new line: with none after it, git apply expects the end of the file.
    after = f" {lines[1]}\n" if len(lines) > 2 or (len(lines) == 2 and lines[1]) else ""
    diff = (f"--- a/{match}\n+++ b/{match}\n@@ -1,{1 + bool(after)} +1,{2 + bool(after)} @@\n {lines[0]}\n"
            f"+{mark} TODO(migration): point this at the {target} on Leaseweb (mock change)\n{after}")
    return [{"file": match, "summary": f"Mock change: mark where {match} must use the {target}.", "diff": diff}]


def _plan_answer(prompt: str) -> dict:
    m = re.search(r"Azure resource (.+?) \(([^)]+)\) has no direct", prompt)
    name, rtype = (m.group(1), m.group(2)) if m else ("resource", "")
    t = re.search(r"Proposed target: (.+?)\. Reason:", prompt)
    target = t.group(1) if t else "Public Cloud instance"
    needs = re.search(r"exist on Leaseweb: (.+?)\. Order the steps", prompt)
    ops_m = re.search(r"Leaseweb operationIds: (.+?)\.\n", prompt)
    ops = set(ops_m.group(1).split(", ")) if ops_m else set()
    code = prompt.split("using the file name exactly as given after ###.\n", 1)[-1].split('\nKeep "proposal"', 1)[0]
    files = {}
    for block in re.split(r"^### ", code, flags=re.M)[1:]:
        path, _, text = block.partition("\n")
        files[path.strip()] = text
    steps = []
    if needs:
        steps.append("Check that these exist on Leaseweb first: " + ", ".join(re.findall(r"(\S+) \(", needs.group(1))) + ".")
    steps += [s for s, op in [
        ("Create a security group that allows only the ports this service needs (createSecurityGroup).", "createSecurityGroup"),
        (f"Launch a Public Cloud instance for the {target} (launchInstance).", "launchInstance"),
        ("Attach the instance to the private network (addToPrivateNetwork).", "addToPrivateNetwork"),
    ] if op in ops]
    steps += [f"Install and configure the {target} with cloud-init.",
              f"Copy the data from {name} and switch the application's settings to the new endpoint.",
              f"Check the application end to end, then remove {name} from Azure."]
    used = [op for op in ("createSecurityGroup", "launchInstance", "addToPrivateNetwork") if op in ops]
    return {"proposal": f"Replace {name} with a {target}. This is a mock plan: no AI was called.",
            "steps": steps, "lw_operations": used, "code_changes": _code_change(rtype, target, files)}


def mock_ask(prompt: str) -> dict:
    """Stands in for the AI: recognises each prompt the app sends by how it starts (the source code inside
    a prompt can contain anything) and answers in its JSON shape."""
    if prompt.startswith("Reply with this JSON object"):
        _delay(0.3)
        return {"ok": True}
    if prompt.startswith("Azure resource type "):
        _delay(0.6)
        return _assess_answer(prompt)
    if re.match(r"Azure resource .+? \([^)]+\) has no direct Leaseweb equivalent", prompt):
        _delay(1.5)
        return _plan_answer(prompt)
    if prompt.startswith("These Azure resources are being replaced"):
        _delay(0.5)
        return {"files": {}}  # no selection: every plan sees all the code
    if prompt.startswith("These Azure resources are being migrated"):
        _delay(0.8)
        return _dependencies_answer(prompt)
    return {}


def mock_models(provider: str, settings) -> dict:
    return {"models": [{"id": "", "label": "Canned answers", "group": ""}], "source": "static"}


# ---- Leaseweb: a fake HTTP client that accepts any key

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
    """Answers Leaseweb API requests like Leaseweb would; instances are RUNNING as soon as they are asked about.
    Other requests (the Azure price list) go to `fallback`, or get a 404 when there is none."""

    REGIONS = [{"name": "eu-west-3", "location": "Amsterdam"}, {"name": "eu-central-1", "location": "Frankfurt"},
               {"name": "us-east-1", "location": "Washington"}, {"name": "ap-southeast-1", "location": "Singapore"}]

    def __init__(self, fallback=None):
        self._fallback = fallback

    def request(self, method: str, url: str, **kwargs):
        host = (urlsplit(url).hostname or "").lower()
        if host != "leaseweb.com" and not host.endswith(".leaseweb.com"):
            if self._fallback is not None:
                return self._fallback.request(method, url, **kwargs)
            return MockResponse(404, {"errorMessage": "Not available in mock mode."})
        _delay(0.2)
        path = re.sub(r"^https?://[^/]+", "", url).split("?", 1)[0]
        body = kwargs.get("json") or {}
        if method == "GET":
            if path.endswith("/publicCloud/v1/instances"):
                return MockResponse(200, {"instances": [], "_metadata": {"totalCount": 0, "limit": 1, "offset": 0}})
            m = re.fullmatch(r".*/publicCloud/v1/instances/([^/]+)", path)
            if m:
                return MockResponse(200, {"id": m.group(1), "state": "RUNNING"})
            if path.endswith("/publicCloud/v1/regions"):
                return MockResponse(200, {"regions": self.REGIONS})
            return MockResponse(404, {"errorMessage": "Not available in mock mode."})  # e.g. prices: the app falls back
        if method == "DELETE":
            return MockResponse(204)
        new_id = str(uuid.uuid4())
        if path.endswith("/publicCloud/v1/instances"):
            return MockResponse(201, {"id": new_id, "state": "CREATING", "region": body.get("region", ""),
                                      "type": body.get("type", ""), "reference": body.get("reference", "")})
        if method == "POST":
            return MockResponse(201, {"id": new_id, **{k: v for k, v in body.items() if isinstance(v, (str, int, bool))}})
        return MockResponse(200, {"id": new_id})


def mock_overrides(parts) -> dict:
    """create_app() keyword arguments for the mocked parts."""
    parts = set(parts)
    kw: dict = {"mock": parts, "state_file": MOCK_STATE_FILE}
    if "azure" in parts:
        kw.update(discover=mock_discover, groups_fn=mock_groups, azure_status_fn=mock_azure_status,
                  subscriptions_fn=mock_subscriptions)
    if "ai" in parts:
        kw.update(ask=mock_ask, models_fn=mock_models)
    if "leaseweb" in parts:
        from .dryrun import default_http
        # The public Azure price list stays real unless Azure is mocked too (then nothing leaves the machine).
        kw.update(http=MockHttp(None if "azure" in parts else default_http()), wait_timeout=30)
    return kw
