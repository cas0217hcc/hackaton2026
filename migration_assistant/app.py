import json
import os
import re
import threading

import httpx
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .assess import assess
from .azure_discovery import DiscoveryError, list_resources
from .claude_cli import ClaudeError
from .llm import AiSettings, available_providers, make_ask as default_make_ask
from .dryrun import BASE_URL, DryRunExecutor, LeasewebExecutor, annotate_chain, build_calls, path_matches, run_calls
from .models import Assessment, CodeChange, DryRunCall, Plan, Resource
from .leaseweb_ops import load_launch_options, load_operations
from .plan import FAILED_PREFIX, build_plans, read_sources

HERE = Path(__file__).parent
DEFAULT_RG = "hackaton-2026-rg"
MAX_FOLDERS = 5
DEFAULT_STATE_FILE = Path("data/state.json")


def _empty_state() -> dict:
    return {"resource_group": DEFAULT_RG, "source_dirs": [], "resources": [], "assessments": [], "plans": [], "calls": []}


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


def create_app(discover: Callable = list_resources, ask: Callable | None = None,
               state_file: Path | None = DEFAULT_STATE_FILE, http=None, make_ask: Callable = default_make_ask) -> FastAPI:
    app = FastAPI(title="Azure to Leaseweb Migration Assistant")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    state = _load(state_file)
    progress: dict = {"running": False, "items": []}  # live status of the current plan run
    progress_lock = threading.Lock()
    chain: dict[str, str] = {}  # ids returned by earlier live calls, e.g. instanceId (memory only)
    ai = AiSettings(provider=os.environ.get("AI_PROVIDER", "claude-cli"), model=os.environ.get("AI_MODEL", ""))  # memory only

    def ask_ai(prompt: str) -> dict:
        """Answer with whichever provider is selected right now (tests can pass a fixed `ask`)."""
        return (ask or make_ask(ai))(prompt)

    secrets: dict = {"api_key": None}  # memory only: never saved, never returned
    ops = load_operations()
    launch_options = load_launch_options()

    def save() -> None:
        if state_file is None:
            return
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(_dump(state)))

    def error(message: str, status: int = 502):
        return JSONResponse({"error": message}, status_code=status)

    @app.get("/")
    def index(request: Request):
        # Version static URLs by file mtime so browsers never reuse stale JS/CSS.
        v = int(max(f.stat().st_mtime for f in (HERE / "static").iterdir()))
        return templates.TemplateResponse(request, "index.html", {"default_rg": DEFAULT_RG, "v": v})

    @app.get("/api/state")
    def api_state():
        return {**_dump(state), "api_key_set": bool(secrets["api_key"]), "chain": dict(chain)}

    @app.post("/api/key")
    def api_set_key(api_key: str = Form("")):
        key = api_key.strip()
        if not key:
            return error("API key is empty.", 400)
        secrets["api_key"] = key
        return {"api_key_set": True}

    @app.delete("/api/key")
    def api_clear_key():
        secrets["api_key"] = None
        return {"api_key_set": False}

    @app.post("/api/reset")
    def api_reset():
        state.clear()
        state.update(_empty_state())
        chain.clear()
        if state_file is not None:
            state_file.unlink(missing_ok=True)
        return _dump(state)

    @app.post("/api/discover")
    def api_discover(resource_group: str = Form(DEFAULT_RG)):
        try:
            state["resources"] = discover(resource_group)
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
            state["assessments"] = assess(state["resources"], ask=ask_ai, ops=ops)
        except ClaudeError as e:
            return error(str(e))
        state.update(plans=[], calls=[])
        save()
        return {"assessments": [asdict(a) for a in state["assessments"]]}

    @app.post("/api/plan")
    def api_plan(source_dirs: list[str] = Form(default=[])):
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        rebuild = [a for a in state["assessments"] if a.route == "rebuild"]
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
            progress["running"] = True
            progress["items"] = [{"name": a.resource_name, "status": "pending"} for a in rebuild]
        try:
            plans = build_plans([(a, by_name[a.resource_name]) for a in rebuild], source, ask=ask_ai, ops=ops,
                                on_progress=on_progress)
        finally:
            with progress_lock:
                progress["running"] = False
        failed = [p for p in plans if p.warnings and p.warnings[0].startswith(FAILED_PREFIX)]
        if len(failed) == len(plans):  # nothing usable: report the problem and allow retry
            return error(failed[0].warnings[0][len(FAILED_PREFIX):])
        state["plans"] = plans
        save()
        return {"plans": [asdict(p) for p in plans], "message": ""}

    @app.get("/api/plan/progress")
    def api_plan_progress():
        with progress_lock:
            items = [dict(i) for i in progress["items"]]
            running = progress["running"]
        return {"running": running, "total": len(items),
                "done": sum(1 for i in items if i["status"] in ("done", "failed")), "items": items}

    def executor():
        key = secrets["api_key"]
        return LeasewebExecutor(key, http) if key else DryRunExecutor()

    @app.get("/api/migrate/calls")
    def api_migrate_calls():
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        return {"calls": [asdict(c) for c in build_calls(state["assessments"], ops, state["resources"])],
                "live": bool(secrets["api_key"])}

    def ai_state() -> dict:
        return {"provider": ai.provider, "model": ai.model, "api_key_set": bool(ai.api_key),
                "providers": available_providers(ai)}

    @app.get("/api/ai")
    def api_ai():
        return ai_state()

    @app.post("/api/ai")
    def api_ai_set(provider: str = Form(...), model: str = Form(""), api_key: str = Form("")):
        provider, model = provider.strip(), model.strip()
        if provider not in {p["id"] for p in available_providers(ai)}:
            return error(f"Unknown AI provider '{provider}'.", 400)
        if provider == "opencode" and model and not re.fullmatch(r"[A-Za-z0-9][\w.\-]*/[\w.\-:/]+", model):
            return error("opencode model must look like provider/model, for example anthropic/claude-sonnet-5-5.", 400)
        ai.provider, ai.model = provider, model
        if api_key.strip():  # an empty field keeps the key that is already set
            ai.api_key = api_key.strip()
        return ai_state()

    @app.delete("/api/ai/key")
    def api_ai_clear_key():
        ai.api_key = None
        return ai_state()

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
                client = http if http is not None else httpx.Client()
                resp = client.request("GET", BASE_URL + "/publicCloud/v1/regions",
                                      headers={"X-LSW-Auth": key, "Accept": "application/json"}, timeout=15)
                live = [{"value": r["name"], "description": r.get("location", "")} for r in resp.json()["regions"]]
                if resp.status_code == 200 and live:
                    regions, source = live, "live"
            except Exception:  # any lookup problem: keep the spec list
                pass
        return {"options": {"launchInstance": {**launch_options, "region": regions}}, "source": source}

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
            prepared = build_calls(state["assessments"], ops, state["resources"])
        annotate_chain(prepared)
        state["calls"] = prepared
        save()
        results = run_calls(prepared, executor(), chain)  # ids from earlier single runs stay usable
        return {"live": bool(secrets["api_key"]), "calls": [asdict(c) for c in prepared], "results": results,
                "chain": dict(chain)}

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
        [result] = run_calls(prepared, executor(), chain)
        return {"live": bool(secrets["api_key"]), "result": result, "chain": dict(chain)}

    @app.get("/export", response_class=PlainTextResponse)
    def export():
        lines = ["# Azure to Leaseweb migration plan", "", "## Assessment", ""]
        for a in state["assessments"]:
            lines.append(f"- **{a.resource_name}**: {a.route} -> {a.target}. {a.rationale}")
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
        return "\n".join(lines) + "\n"

    return app


app = create_app()
