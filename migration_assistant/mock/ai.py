"""Mock AI: canned answers, no tokens. Each request is a prompt.Prompt, so the inputs are read from its data,
never parsed from its text. A request it does not know is an error, so a new or untagged prompt fails loudly."""
import json
import re
from pathlib import Path

from ..claude_cli import ClaudeError
from ..models import Assessment, Resource
from ..prompt import TASKS
from ._pause import pause

MOCK_PROVIDER = {"id": "mock", "label": "Mock AI", "available": True, "detail": "canned answers, no tokens spent"}

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
_ARM_ID = re.compile(r"/subscriptions/[^\"\s]+")  # links by id are found from the configuration already


def _assess_type(resource: Resource) -> dict:
    route, target, why = ASSESS_ANSWERS.get(resource.type.lower(), (
        "rebuild", "Self-hosted service on a Public Cloud instance",
        "No managed equivalent on Leaseweb, so it runs on its own instance."))
    return {"route": route, "target": target, "rationale": f"{why} (mock answer)", "lw_operations": ["launchInstance"]}


def _dependencies(resources: list[Resource], routes: dict[str, str]) -> dict:
    """What a careful reader would find: a resource needs another when its settings name it (an endpoint, a vault
    URI, an account name). Names inside ARM ids are skipped: the configuration links already cover those."""
    live = [r for r in resources if routes.get(r.name) != "included"]
    text = {r.name: _ARM_ID.sub("", json.dumps(r.properties, default=str).lower()) for r in live}
    out = []
    for r in live:
        for other in live:
            if other.name != r.name and len(other.name) > 5 and other.name.lower() in text[r.name]:
                out.append({"resource": r.name, "depends_on": other.name,
                            "reason": f"its settings name {other.name} ({other.type.split('/')[-1]}) (mock answer)"})
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
    match = next((f for f in files if _comment(f) and any(w in files[f].lower() for w in words)), None)
    if not match:
        return []
    lines = files[match].split("\n")
    # Context on both sides of the new line: with none after it, git apply expects the end of the file.
    after = f" {lines[1]}\n" if len(lines) > 2 or (len(lines) == 2 and lines[1]) else ""
    diff = (f"--- a/{match}\n+++ b/{match}\n@@ -1,{1 + bool(after)} +1,{2 + bool(after)} @@\n {lines[0]}\n"
            f"+{_comment(match)} TODO(migration): point this at the {target} on Leaseweb (mock change)\n{after}")
    return [{"file": match, "summary": f"Mock change: mark where {match} must use the {target}.", "diff": diff}]


def _plan(assessment: Assessment, resource: Resource, source: dict[str, str], ops: list[str]) -> dict:
    target, name = assessment.target, resource.name
    steps = []
    if assessment.dependencies:
        steps.append("Check that these exist on Leaseweb first: " + ", ".join(d["name"] for d in assessment.dependencies) + ".")
    steps += [s for s, op in [
        ("Create a security group that allows only the ports this service needs (createSecurityGroup).", "createSecurityGroup"),
        (f"Launch a Public Cloud instance for the {target} (launchInstance).", "launchInstance"),
        ("Attach the instance to the private network (addToPrivateNetwork).", "addToPrivateNetwork"),
    ] if op in ops]
    steps += [f"Install and configure the {target} with cloud-init.",
              f"Copy the data from {name} and switch the application's settings to the new endpoint.",
              f"Check the application end to end, then remove {name} from Azure."]
    return {"proposal": f"Replace {name} with a {target}. This is a mock plan: no AI was called.", "steps": steps,
            "lw_operations": [op for op in ("createSecurityGroup", "launchInstance", "addToPrivateNetwork") if op in ops],
            "code_changes": _code_change(resource.type, target, source)}


ANSWERS = {  # task -> (pause in seconds, answer from the prompt's data)
    "test": (0.3, lambda d: {"ok": True}),
    "assess_type": (0.6, lambda d: _assess_type(d["resource"])),
    "dependencies": (0.8, lambda d: _dependencies(d["resources"], d["routes"])),
    "select_sources": (0.5, lambda d: {"files": {}}),  # no selection: every plan sees all the code
    "plan": (1.5, lambda d: _plan(d["assessment"], d["resource"], d["source"], d["ops"])),
}
assert set(ANSWERS) == set(TASKS), "every AI task needs a mock answer"


class MockAI:
    def __init__(self, delay: float = 0.0):
        self.delay = delay

    def ask(self, prompt) -> dict:
        task = getattr(prompt, "task", None)
        if task not in ANSWERS:
            raise ClaudeError(f"The mock AI has no answer for this request (task {task!r}). Tag the prompt with "
                              "prompt.Prompt and add an answer in mock/ai.py.")
        seconds, answer = ANSWERS[task]
        pause(self.delay, seconds)
        return answer(prompt.data)

    def models(self, provider: str, settings) -> dict:
        return {"models": [{"id": "", "label": "Canned answers", "group": ""}], "source": "static"}
