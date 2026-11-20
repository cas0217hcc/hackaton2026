import json
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
from .claude_cli import ClaudeError, ask_json
from .dryrun import DryRunExecutor, build_calls
from .models import Assessment, CodeChange, DryRunCall, Plan, Resource
from .leaseweb_ops import load_operations
from .plan import build_plan, read_sources

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


def create_app(discover: Callable = list_resources, ask: Callable = ask_json,
               state_file: Path | None = DEFAULT_STATE_FILE) -> FastAPI:
    app = FastAPI(title="Azure to Leaseweb Migration Assistant")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    state = _load(state_file)
    ops = load_operations()

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
            state["assessments"] = assess(state["resources"], ask=ask, ops=ops)
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
        try:
            state["plans"] = [build_plan(a, by_name[a.resource_name], source, ask=ask, ops=ops) for a in rebuild]
        except ClaudeError as e:
            return error(str(e))
        save()
        return {"plans": [asdict(p) for p in state["plans"]], "message": ""}

    @app.post("/api/migrate")
    def api_migrate():
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        executor = DryRunExecutor()
        calls = build_calls(state["assessments"], ops)
        state["calls"] = calls
        save()
        return {"calls": [asdict(c) for c in calls], "results": [executor.execute(c) for c in calls]}

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
