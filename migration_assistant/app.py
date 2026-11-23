import ipaddress
import json
import os
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .assess import assess
from .dependencies import add_dependencies
from .azure_discovery import (DiscoveryError, azure_status as default_azure_status, list_resource_groups, list_resources,
                              list_subscriptions as default_list_subscriptions)
from .claude_cli import ClaudeError
from .claude_cli import MODEL_RE
from .llm import DEFAULT_API_MODEL, AiSettings, available_providers, list_models as default_list_models, make_ask as default_make_ask
from .folder_picker import FolderPickerError, pick_folder as default_pick_folder
from .costs import azure_vm_prices, leaseweb_prices
from .datamove import data_steps
from .envfile import ENV_FILE, load_env
from .diffcheck import check_plans, patch_text
from .dryrun import (BASE_URL, DryRunExecutor, default_http, network_hint, LeasewebExecutor, annotate_chain, build_calls, curl_script, path_matches,
                     run_calls, teardown_calls)
from .models import Assessment, CodeChange, DryRunCall, Plan, Resource
from .leaseweb_ops import find_operations, load_launch_options, load_operation_docs, load_operations
from .plan import FAILED_PREFIX, SELECT_ABOVE, build_plans, read_sources, select_sources

HERE = Path(__file__).parent
DEFAULT_RG = "hackaton-2026-rg"
MAX_FOLDERS = 5
DEFAULT_STATE_FILE = Path("data/state.json")


def _empty_state() -> dict:
    return {"resource_group": DEFAULT_RG, "subscription": "", "source_dirs": [], "resources": [], "assessments": [], "plans": [],
            "calls": [], "saved_at": ""}


def _dump(state: dict) -> dict:
    return {k: ([asdict(x) if is_dataclass(x) else x for x in v] if isinstance(v, list) else v) for k, v in state.items()}


def _load(path: Path | None) -> dict:
    """Restore saved state; a missing or corrupt file means a fresh start."""
    state = _empty_state()
    if path is None or not path.exists():
        return state
    try:
        raw = json.loads(path.read_text())
        state["resource_group"] = raw.get("resource_group", DEFAULT_RG)
        state["subscription"] = str(raw.get("subscription") or "")
        state["saved_at"] = str(raw.get("saved_at") or "")
        old = [raw["source_dir"]] if raw.get("source_dir") else []
        state["source_dirs"] = list(raw.get("source_dirs") or old)
        state["resources"] = [Resource(**r) for r in raw.get("resources", [])]
        state["assessments"] = [Assessment(**a) for a in raw.get("assessments", [])]
        state["plans"] = [
            Plan(**{**p, "code_changes": [CodeChange(**c) for c in p.get("code_changes", [])]})
            for p in raw.get("plans", [])
        ]
        state["calls"] = [DryRunCall(**c) for c in raw.get("calls", [])]
    except (ValueError, TypeError, KeyError, OSError):
        return _empty_state()
    return state


LOCAL_NAMES = {"localhost", "testserver"}  # testserver: what Starlette's TestClient sends


def _hostname(netloc: str) -> str:
    return (urlsplit("//" + netloc).hostname or "").lower()


def host_allowed(host_header: str, extra: set[str] | None = None) -> bool:
    """Only IP literals, localhost and names from ALLOWED_HOSTS. A DNS-rebinding page arrives with
    its own domain name in Host, so it is refused even though it reached this server."""
    name = _hostname(host_header)
    if not name:
        return False
    if name in LOCAL_NAMES or name in (extra or set()):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def origin_allowed(origin: str | None, host_header: str) -> bool:
    """A browser names the page that sent a request in Origin. Changing requests are only accepted from
    this app's own pages (or from clients that send no Origin, such as curl and the tests)."""
    if not origin:
        return True
    parts = urlsplit(origin)
    return bool(parts.netloc) and parts.netloc.lower() == host_header.lower()


def create_app(discover: Callable = list_resources, ask: Callable | None = None,
               state_file: Path | None = DEFAULT_STATE_FILE, http=None, make_ask: Callable = default_make_ask,
               models_fn: Callable = default_list_models, groups_fn: Callable = list_resource_groups,
               pick_folder: Callable = default_pick_folder, git_runner: Callable | None = None,
               wait_timeout: float = 600, azure_status_fn: Callable = default_azure_status,
               subscriptions_fn: Callable = default_list_subscriptions, mock=()) -> FastAPI:
    """`mock`: the mocked parts ("azure", "ai", "leaseweb"; True means all). The page then says so, a mocked AI is the
    only provider offered, and a mocked Leaseweb starts with a mock key. mock.py supplies the fakes themselves."""
    app = FastAPI(title="Azure to Leaseweb Migration Assistant")
    extra_hosts = {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        # The app has no login and can send live Leaseweb calls, so another site open in the same browser
        # must not be able to drive it (cross-site form posts) or read it (DNS rebinding).
        host = request.headers.get("host", "")
        if not host_allowed(host, extra_hosts):
            return JSONResponse({"error": "Host not allowed. Add it to ALLOWED_HOSTS to use this name."}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not origin_allowed(request.headers.get("origin"), host):
            return JSONResponse({"error": "Cross-site request refused."}, status_code=403)
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    state = _load(state_file)
    progress: dict = {"running": False, "items": []}  # live status of the current plan run
    progress_lock = threading.Lock()
    chain: dict[str, str] = {}  # ids returned by earlier live calls, e.g. instanceId (memory only)
    created: list[dict] = []  # what live calls created, newest last, so it can be torn down (memory only)
    from .mock import MOCK_KEY, MOCK_PROVIDER, PARTS, describe
    mocked = set(PARTS) if mock is True else set(mock or ())
    mock_ai = "ai" in mocked
    ai = AiSettings(provider="mock" if mock_ai else os.environ.get("AI_PROVIDER", "claude-cli"),
                    model="" if mock_ai else os.environ.get("AI_MODEL", ""))

    def providers() -> list[dict]:
        if mock_ai:
            return [dict(MOCK_PROVIDER)]
        return available_providers(ai)

    # The provider and model are remembered next to the saved results; the API key never is.
    ai_file = state_file.parent / "ai.json" if state_file is not None and not mock_ai else None
    if ai_file is not None and ai_file.exists():
        try:
            saved = json.loads(ai_file.read_text())
            if saved["provider"] in {p["id"] for p in providers()} and isinstance(saved.get("model", ""), str):
                ai.provider, ai.model = saved["provider"], saved.get("model", "")
        except (ValueError, KeyError, TypeError, OSError):
            pass  # a damaged file just means the default

    def ask_ai(prompt: str) -> dict:
        """Answer with whichever provider is selected right now (tests can pass a fixed `ask`)."""
        return (ask or make_ask(ai))(prompt)

    secrets: dict = {"api_key": None}  # memory only: never saved, never returned
    key_check: dict = {"verified": None, "detail": ""}  # result of the last /api/key/test (True, False, None = unknown)
    if "leaseweb" in mocked:  # a fake key for the fake API, so runs are "live" against it from the start
        secrets["api_key"] = MOCK_KEY
        key_check.update(verified=True, detail="Mock Leaseweb API: any key works, and nothing is sent to Leaseweb.")
    ops = load_operations()
    launch_options = load_launch_options()

    save_lock = threading.Lock()
    client = http if http is not None else default_http()  # one connection pool for every outbound request

    def save() -> None:
        if state_file is None:
            return
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")  # shown when the session is restored
        with save_lock:  # write a temp file, then swap it in: a crash mid-write never leaves half a file
            tmp = state_file.with_name(state_file.name + ".tmp")
            tmp.write_text(json.dumps(_dump(state)))
            os.replace(tmp, state_file)

    def error(message: str, status: int = 502):
        return JSONResponse({"error": message}, status_code=status)

    @app.get("/")
    def index(request: Request):
        # Version static URLs by file mtime so browsers never reuse stale JS/CSS.
        v = int(max(f.stat().st_mtime for f in (HERE / "static").iterdir()))
        return templates.TemplateResponse(request, "index.html", {"default_rg": DEFAULT_RG, "v": v, "mock": sorted(mocked),
                                                                   "mock_text": describe(mocked) if mocked else ""})

    @app.get("/api/state")
    def api_state():
        return {**_dump(state), "mock": sorted(mocked), "api_key_set": bool(secrets["api_key"]), "key_verified": key_check["verified"],
                "chain": dict(chain), "created": list(created)}

    @app.post("/api/key")
    def api_set_key(api_key: str = Form("")):
        key = api_key.strip()
        if not key:
            return error("API key is empty.", 400)
        secrets["api_key"] = key
        key_check.update(verified=None, detail="")
        return {"api_key_set": True, "key_verified": None}

    @app.delete("/api/key")
    def api_clear_key():
        secrets["api_key"] = None
        key_check.update(verified=None, detail="")
        return {"api_key_set": False, "key_verified": None}

    @app.post("/api/key/test")
    def api_test_key():
        """Check the key with one harmless read (list one instance). A key Leaseweb rejects is removed again,
        so a wrong key can never leave the app in live mode."""
        key = secrets["api_key"]
        if not key:
            return error("No Leaseweb API key is set.", 409)
        try:
            resp = client.request("GET", BASE_URL + "/publicCloud/v1/instances", params={"limit": 1},
                                  headers={"X-LSW-Auth": key, "Accept": "application/json"}, timeout=15)
            status = resp.status_code
        except Exception as e:
            key_check.update(verified=None, detail="Could not reach the Leaseweb API to check the key, so it is kept but not verified. "
                                                   + network_hint(e, key))
            return {"api_key_set": True, "key_verified": None, "detail": key_check["detail"]}
        if status == 401:
            secrets["api_key"] = None
            key_check.update(verified=None, detail="")
            return error("Leaseweb rejected this key (HTTP 401). It was not kept, so the app stays in dry run.", 400)
        if status == 403:  # a real key without access to the Public Cloud API: say so instead of calling it wrong
            key_check.update(verified=False, detail="Leaseweb knows this key, but it may not use the Public Cloud API (HTTP 403), "
                                                    "so launching instances will fail. Check the key's permissions in the Customer Portal.")
            return {"api_key_set": True, "key_verified": False, "detail": key_check["detail"]}
        if 200 <= status < 300:
            key_check.update(verified=True, detail="Leaseweb accepted the key.")
        else:
            key_check.update(verified=None, detail=f"Leaseweb answered HTTP {status}, so the key could not be confirmed. It is kept.")
        return {"api_key_set": True, "key_verified": key_check["verified"], "detail": key_check["detail"]}

    @app.post("/api/reset")
    def api_reset():
        sub_id = state.get("subscription", "")  # a setting, not a result: it survives Start over
        state.clear()
        state.update(_empty_state(), subscription=sub_id)
        chain.clear()
        created.clear()
        if state_file is not None:
            state_file.unlink(missing_ok=True)
        return _dump(state)

    def with_sub(fn: Callable, *args):
        """Call an az helper for the chosen subscription (helpers that take none, like test fakes, get none)."""
        return fn(*args, subscription=state["subscription"]) if state["subscription"] else fn(*args)

    @app.get("/api/azure")
    def api_azure():
        status = azure_status_fn()
        return {**status, "selected_subscription": state["subscription"]}

    @app.get("/api/azure/subscriptions")
    def api_azure_subscriptions():
        try:
            return {"subscriptions": subscriptions_fn(), "selected": state["subscription"]}
        except DiscoveryError as e:
            return error(str(e))

    @app.post("/api/azure/subscription")
    def api_azure_set_subscription(subscription_id: str = Form("")):
        wanted = subscription_id.strip()
        if wanted:
            try:
                known = {x["id"] for x in subscriptions_fn()}
            except DiscoveryError as e:
                return error(str(e))
            if wanted not in known:
                return error("That subscription is not available to your Azure account.", 400)
        state["subscription"] = wanted
        save()
        return {"selected": wanted}

    @app.get("/api/resource-groups")
    def api_resource_groups():
        try:
            return {"groups": with_sub(groups_fn), "default": DEFAULT_RG}
        except DiscoveryError as e:
            return error(str(e))

    @app.post("/api/pick-folder")
    def api_pick_folder(initial: str = Form("")):
        try:
            return {"path": pick_folder(initial)}
        except FolderPickerError as e:
            return error(str(e), 500)

    @app.post("/api/discover")
    def api_discover(resource_group: str = Form(DEFAULT_RG)):
        resource_group = resource_group.strip()
        if not re.fullmatch(r"[\w.()-]{1,90}", resource_group) or resource_group.endswith("."):
            return error("Enter a valid resource group name (letters, digits, - _ . ( ), up to 90 characters).", 400)
        try:
            state["resources"] = with_sub(discover, resource_group)
        except DiscoveryError as e:
            return error(str(e))
        state.update(resource_group=resource_group, assessments=[], plans=[], calls=[])
        save()
        return {"resources": [asdict(r) for r in state["resources"]]}

    @app.post("/api/assess")
    def api_assess():
        if not state["resources"]:
            return error("Run Discover first.", 409)
        try:
            assessments = assess(state["resources"], ask=ask_ai, ops=ops)
        except ClaudeError as e:
            return error(str(e))
        note = add_dependencies(state["resources"], assessments, ask=ask_ai)
        state.update(assessments=assessments, plans=[], calls=[])
        save()
        return {"assessments": [asdict(a) for a in assessments], "message": note}

    @app.post("/api/plan")
    def api_plan(source_dirs: list[str] = Form(default=[])):
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        rebuild = [a for a in state["assessments"] if a.route == "rebuild"]
        problem = ai_problem()
        if rebuild and problem:
            return error(problem, 409)
        if not rebuild:
            state["plans"] = []
            save()
            return {"plans": [], "message": "Nothing to plan: every resource migrates directly."}
        dirs = [d.strip() for d in source_dirs if d.strip()]
        if len(dirs) > MAX_FOLDERS:
            return error(f"Provide at most {MAX_FOLDERS} source folders.", 400)
        missing = [d for d in dirs if not Path(d).is_dir()]
        if missing:
            return error(f"Folder not found: {', '.join(missing)}", 400)
        state["source_dirs"] = dirs
        source = read_sources([Path(d) for d in dirs])
        by_name = {r.name: r for r in state["resources"]}

        def on_progress(name: str, status: str) -> None:
            with progress_lock:
                for item in progress["items"]:
                    if item["name"] == name:
                        item["status"] = status

        with progress_lock:
            if progress["running"]:
                return error("A plan is already being generated. Wait for it to finish.", 409)
            progress["running"] = True
            progress["items"] = [{"name": a.resource_name, "status": "pending"} for a in rebuild]
        items = [(a, by_name[a.resource_name]) for a in rebuild]
        try:
            per_resource = (select_sources(items, source, ask=ask_ai)
                            if sum(map(len, source.values())) > SELECT_ABOVE and len(source) > 3 else None)
            plans = build_plans(items, source, ask=ask_ai, ops=ops, on_progress=on_progress, per_resource=per_resource)
        finally:
            with progress_lock:
                progress["running"] = False
        failed = [p for p in plans if p.warnings and p.warnings[0].startswith(FAILED_PREFIX)]
        if len(failed) == len(plans):  # nothing usable: report the problem and allow retry
            return error(failed[0].warnings[0][len(FAILED_PREFIX):])
        if dirs:
            check_plans(plans, [Path(d) for d in dirs], **({"runner": git_runner} if git_runner else {}))
        state["plans"] = plans
        save()
        return {"plans": [asdict(p) for p in plans], "message": ""}

    op_docs: dict = {}  # filled on first use: parsing every spec file takes a moment

    @app.get("/api/plan/detail")
    def api_plan_detail(resource: str):
        """Side by side: the Azure resource today, and each migration step with the Leaseweb calls it uses."""
        plan = next((p for p in state["plans"] if p.resource_name == resource), None)
        source = next((r for r in state["resources"] if r.name == resource), None)
        if plan is None or source is None:
            return error(f"No plan for '{resource}'.", 404)
        if not op_docs:
            op_docs.update(load_operation_docs())
        steps, mentioned = [], set()
        for text in plan.steps:
            ids = find_operations(text, op_docs.keys())
            mentioned.update(ids)
            steps.append({"text": text, "operations": [op_docs[i] for i in ids]})
        return {"resource": asdict(source), "proposal": plan.proposal, "steps": steps,
                "unassigned": [op_docs[i] for i in plan.lw_operations if i in op_docs and i not in mentioned],
                "code_changes": [asdict(c) for c in plan.code_changes], "warnings": plan.warnings}

    @app.get("/api/plan/progress")
    def api_plan_progress():
        with progress_lock:
            items = [dict(i) for i in progress["items"]]
            running = progress["running"]
        return {"running": running, "total": len(items),
                "done": sum(1 for i in items if i["status"] in ("done", "failed")), "items": items}

    def executor():
        key = secrets["api_key"]
        return LeasewebExecutor(key, client, wait_timeout=wait_timeout) if key else DryRunExecutor()

    def current_calls() -> list[DryRunCall]:
        return build_calls(state["assessments"], ops, state["resources"], state["plans"])

    @app.get("/api/migrate/calls")
    def api_migrate_calls():
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        return {"calls": [asdict(c) for c in current_calls()], "live": bool(secrets["api_key"])}

    def ai_problem() -> str:
        """Why the selected AI provider cannot answer, or ''. Only the built-in providers are checked:
        an injected `ask` or `make_ask` (as in tests) brings its own backends."""
        if ask is not None or make_ask is not default_make_ask:
            return ""
        chosen = next((p for p in providers() if p["id"] == ai.provider), None)
        if chosen is None or not chosen["available"]:
            return f"The AI provider is not ready: {chosen['detail'] if chosen else ai.provider}. Choose a working one in the AI settings."
        if ai.provider == "anthropic-api" and not ai.api_key and not any(
                os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")):
            return "The Anthropic API needs a key. Paste one in the AI settings."
        return ""

    def ai_state() -> dict:
        effective = ai.model or (DEFAULT_API_MODEL if ai.provider == "anthropic-api" else "")
        return {"provider": ai.provider, "model": ai.model, "effective_model": effective, "api_key_set": bool(ai.api_key),
                "providers": providers(), "problem": ai_problem()}

    @app.get("/api/ai")
    def api_ai():
        return ai_state()

    @app.post("/api/ai")
    def api_ai_set(provider: str = Form(...), model: str = Form(""), api_key: str = Form("")):
        provider, model = provider.strip(), model.strip()
        if provider not in {p["id"] for p in providers()}:
            return error(f"Unknown AI provider '{provider}'.", 400)
        if provider == "opencode" and model and not re.fullmatch(r"[A-Za-z0-9][\w.\-]*/[\w.\-:/]+", model):
            return error("opencode model must look like provider/model, for example anthropic/claude-sonnet-5-5.", 400)
        if provider == "claude-cli" and model and not MODEL_RE.fullmatch(model):
            return error("Claude Code model must be opus, sonnet, haiku or a claude-... model id.", 400)
        ai.provider, ai.model = provider, model
        if ai_file is not None:
            ai_file.parent.mkdir(parents=True, exist_ok=True)
            ai_file.write_text(json.dumps({"provider": ai.provider, "model": ai.model}))
        if api_key.strip():  # an empty field keeps the key that is already set
            ai.api_key = api_key.strip()
        return ai_state()

    @app.delete("/api/ai/key")
    def api_ai_clear_key():
        ai.api_key = None
        return ai_state()

    @app.get("/api/ai/models")
    def api_ai_models(provider: str):
        if provider not in {p["id"] for p in providers()}:
            return error(f"Unknown AI provider '{provider}'.", 400)
        return models_fn(provider, ai)

    @app.post("/api/ai/test")
    def api_ai_test():
        """Send a tiny request through the selected provider so a bad setup shows up before a long run."""
        try:
            answer = ask_ai('Reply with this JSON object and nothing else: {"ok": true}')
        except ClaudeError as e:
            return error(str(e))
        if answer.get("ok") is not True:
            return error("The AI answered, but not with the expected JSON.")
        return {"ok": True}

    @app.get("/api/migrate/options")
    def api_migrate_options():
        """Dropdown values for call fields. Regions come live from Leaseweb when a key is set, else from the specs."""
        regions, source = launch_options["region"], "spec"
        key = secrets["api_key"]
        if key:
            try:
                resp = client.request("GET", BASE_URL + "/publicCloud/v1/regions",
                                      headers={"X-LSW-Auth": key, "Accept": "application/json"}, timeout=15)
                live = ([{"value": r["name"], "description": r.get("location", "")} for r in resp.json()["regions"]]
                        if resp.status_code == 200 else [])
                if live:
                    regions, source = live, "live"
            except Exception:  # any lookup problem: keep the spec list
                pass
        if not op_docs:
            op_docs.update(load_operation_docs())
        return {"options": {"launchInstance": {**launch_options, "region": regions}}, "source": source,
                "summaries": {i: d["summary"] for i, d in op_docs.items() if d.get("summary")}}

    def spec_error(calls: list[DryRunCall]) -> str | None:
        """Only spec operations may be sent, with the spec's method and path shape."""
        for c in calls:
            spec = ops.get(c.operation_id)
            if not spec or spec[0] != c.method or not path_matches(spec[1], c.path):
                return f"Call {c.operation_id} does not match the Leaseweb specs."
        return None

    def to_calls(raw: list) -> list[DryRunCall]:
        return [DryRunCall(c["method"], c["path"], c["operation_id"], dict(c.get("body") or {}), source=str(c.get("source") or ""))
                for c in raw]

    @app.post("/api/migrate")
    def api_migrate(calls: str = Form("")):
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        if calls:
            try:
                prepared = to_calls(json.loads(calls))
            except (ValueError, TypeError, KeyError):
                return error("Invalid calls.", 400)
            problem = spec_error(prepared)
            if problem:
                return error(problem, 400)
        else:
            prepared = current_calls()
        annotate_chain(prepared)
        state["calls"] = prepared
        save()
        results = run_calls(prepared, executor(), chain, created)  # ids from earlier single runs stay usable
        return {"live": bool(secrets["api_key"]), "calls": [asdict(c) for c in prepared], "results": results,
                "chain": dict(chain), "created": list(created)}

    @app.post("/api/migrate/run-one")
    def api_migrate_run_one(call: str = Form("")):
        """Run a single call, using ids remembered from earlier runs for its {path params}."""
        try:
            prepared = to_calls([json.loads(call)])
        except (ValueError, TypeError, KeyError):
            return error("Invalid call.", 400)
        problem = spec_error(prepared)
        if problem:
            return error(problem, 400)
        [result] = run_calls(prepared, executor(), chain, created)
        return {"live": bool(secrets["api_key"]), "result": result, "chain": dict(chain), "created": list(created)}

    @app.post("/api/migrate/teardown")
    def api_migrate_teardown():
        """Delete what live runs created, newest first. Live only: a dry run never created anything."""
        key = secrets["api_key"]
        if not key:
            return error("Set the Leaseweb API key to remove live resources.", 409)
        if not created:
            return {"results": [], "created": [], "chain": dict(chain)}
        live_exec = LeasewebExecutor(key, client)
        results = []
        for item, call in teardown_calls(created, ops):
            r = live_exec.execute(call)
            r["source"] = item.get("source", "")
            gone = r.get("sent") and (200 <= r.get("status", 0) < 300 or r.get("status") == 404)
            if gone:
                created.remove(item)
                for param, value in (item.get("params") or {}).items():
                    if chain.get(param) == value:
                        chain.pop(param)
            results.append(r)
        return {"results": results, "created": list(created), "chain": dict(chain)}

    @app.get("/api/costs")
    def api_costs(region: str = "eu-west-3"):
        """Monthly compute estimate: Leaseweb instance prices for a region, and Azure VM prices today."""
        if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region):
            return error("Unknown region.", 400)
        lsw = leaseweb_prices(region, secrets["api_key"], client, BASE_URL)
        return {"leaseweb": lsw, "azure": azure_vm_prices(state["resources"], client),
                "note": "Compute only. Storage, traffic, licences and managed-service fees are not included."}

    @app.get("/api/data-steps")
    def api_data_steps():
        return {"steps": data_steps(state["resources"], state["assessments"])}

    @app.get("/export", response_class=PlainTextResponse)
    def export():
        lines = ["# Azure to Leaseweb migration plan", "", "## Assessment", ""]
        for a in state["assessments"]:
            needs = f" Needs first: {', '.join(d['name'] for d in a.dependencies)}." if a.dependencies else ""
            lines.append(f"- **{a.resource_name}**: {a.route} -> {a.target}. {a.rationale}{needs}")
        for p in state["plans"]:
            lines += ["", f"## Plan: {p.resource_name}", "", p.proposal, ""]
            lines += [f"{i}. {st}" for i, st in enumerate(p.steps, 1)] + [""] if p.steps else []
            lines += [f"Leaseweb operations: {', '.join(p.lw_operations) or 'none'}", ""]
            for c in p.code_changes:
                lines += [f"### {c.file}", c.summary, "```diff", c.diff, "```", ""]
            lines += [f"> {w}" for w in p.warnings]
        if state["calls"]:
            lines += ["", "## Dry-run calls", ""]
            lines += [f"- {c.method} {c.path} ({c.operation_id})" for c in state["calls"]]
        steps = data_steps(state["resources"], state["assessments"])
        if steps:
            lines += ["", "## Data migration", ""]
            for d in steps:
                lines += [f"### {d['resource']}: {d['title']}", ""]
                if d["commands"]:
                    lines += ["```bash", *d["commands"], "```", ""]
                lines += [f"- {n}" for n in d["notes"]] + [""]
        return "\n".join(lines) + "\n"

    def export_calls() -> list[DryRunCall]:
        return state["calls"] or (current_calls() if state["assessments"] else [])

    @app.get("/export/calls.json")
    def export_calls_json():
        return Response(json.dumps([asdict(c) for c in export_calls()], indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="leaseweb-calls.json"'})

    @app.get("/export/calls.sh")
    def export_calls_sh():
        return Response(curl_script(export_calls()), media_type="text/x-shellscript",
                        headers={"Content-Disposition": 'attachment; filename="leaseweb-calls.sh"'})

    @app.get("/export/patch")
    def export_patch():
        return Response(patch_text(state["plans"]), media_type="text/x-diff",
                        headers={"Content-Disposition": 'attachment; filename="migration-code-changes.patch"'})

    return app


def _app_from_env(env_file: Path = ENV_FILE) -> FastAPI:
    """Settings come from the environment, then from .env in the repo root (see .env.example).
    MOCK_AZURE, MOCK_AI and MOCK_LEASEWEB mock one part each, MOCK_MODE all three (see mock.py)."""
    load_env(env_file)
    from .mock import describe, mock_overrides, mock_parts
    parts = mock_parts()
    if parts:
        print(describe(parts), flush=True)
        return create_app(**mock_overrides(parts))
    return create_app()


app = _app_from_env()
