from dataclasses import asdict
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
from .leaseweb_ops import load_operations
from .plan import build_plan, read_source

HERE = Path(__file__).parent
DEFAULT_RG = "hackaton-2026-rg"


def create_app(discover: Callable = list_resources, ask: Callable = ask_json) -> FastAPI:
    app = FastAPI(title="Azure to Leaseweb Migration Assistant")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    state: dict = {"resources": [], "assessments": [], "plans": [], "calls": []}
    ops = load_operations()

    def error(message: str, status: int = 502):
        return JSONResponse({"error": message}, status_code=status)

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"default_rg": DEFAULT_RG})

    @app.post("/api/discover")
    def api_discover(resource_group: str = Form(DEFAULT_RG)):
        try:
            state["resources"] = discover(resource_group)
        except DiscoveryError as e:
            return error(str(e))
        state.update(assessments=[], plans=[], calls=[])
        return {"resources": [asdict(r) for r in state["resources"]]}

    @app.post("/api/assess")
    def api_assess():
        if not state["resources"]:
            return error("Run Discover first.", 409)
        try:
            state["assessments"] = assess(state["resources"], ask=ask, ops=ops)
        except ClaudeError as e:
            return error(str(e))
        return {"assessments": [asdict(a) for a in state["assessments"]]}

    @app.post("/api/plan")
    def api_plan(source_dir: str = Form("")):
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        rebuild = [a for a in state["assessments"] if a.route == "rebuild"]
        if not rebuild:
            state["plans"] = []
            return {"plans": [], "message": "Nothing to plan: every resource migrates directly."}
        source = read_source(Path(source_dir) if source_dir.strip() else None)
        by_name = {r.name: r for r in state["resources"]}
        try:
            state["plans"] = [build_plan(a, by_name[a.resource_name], source, ask=ask, ops=ops) for a in rebuild]
        except ClaudeError as e:
            return error(str(e))
        return {"plans": [asdict(p) for p in state["plans"]], "message": ""}

    @app.post("/api/migrate")
    def api_migrate():
        if not state["assessments"]:
            return error("Run Assess first.", 409)
        executor = DryRunExecutor()
        calls = build_calls(state["assessments"], ops)
        state["calls"] = calls
        return {"calls": [asdict(c) for c in calls], "results": [executor.execute(c) for c in calls]}

    @app.get("/export", response_class=PlainTextResponse)
    def export():
        lines = ["# Azure to Leaseweb migration plan", "", "## Assessment", ""]
        for a in state["assessments"]:
            lines.append(f"- **{a.resource_name}**: {a.route} -> {a.target}. {a.rationale}")
        for p in state["plans"]:
            lines += ["", f"## Plan: {p.resource_name}", "", p.proposal, ""]
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
