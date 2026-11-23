from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .claude_cli import ClaudeError, ask_json
from .leaseweb_ops import load_operations
from .diffcheck import folder_prefixes
from .models import Assessment, CodeChange, Plan, Resource
from .prompt import Prompt


# Code and the manifests that say which SDKs it uses. Config files that tend to hold secrets
# (.env, *.tfvars, local.settings.json) are left out on purpose.
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".tf", ".ps1", ".sh", ".toml", ".yaml", ".yml"}
SOURCE_NAMES = {"requirements.txt", "package.json", "host.json"}
SKIP_DIRS = {".venv", "venv", "env", "node_modules", ".git", "__pycache__", ".terraform", "dist", "build",
             ".pytest_cache", ".mypy_cache", ".tox", "site-packages", ".idea", ".vscode"}
MAX_FILE_BYTES = 60_000  # one generated or vendored file must not take the whole budget


def _is_source(p: Path) -> bool:
    return p.suffix.lower() in SOURCE_SUFFIXES or p.name.lower() in SOURCE_NAMES


def read_source(source_dir: Path | None, max_bytes: int = 200_000) -> dict[str, str]:
    """Return {relative path: text} for code files under source_dir (capped in total size).

    Dependency and build folders are skipped, and a file too big for what is left of the budget is
    skipped rather than ending the scan, so the files that come after it still get read."""
    if source_dir is None or not Path(source_dir).is_dir():
        return {}
    root = Path(source_dir)
    files: dict[str, str] = {}
    total = 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts[:-1]) or not p.is_file() or not _is_source(p):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if total + len(text) > max_bytes:
            continue
        total += len(text)
        files[rel.as_posix()] = text
    return files


def read_sources(dirs: list[Path], max_bytes: int = 200_000) -> dict[str, str]:
    """Like read_source over several folders; keys are prefixed with the folder name (made unique)."""
    out: dict[str, str] = {}
    used = 0
    for prefix, d in folder_prefixes([Path(d) for d in dirs]).items():
        for rel, text in read_source(d, max_bytes - used).items():
            out[f"{prefix}/{rel}"] = text
            used += len(text)
    return out


# Above this much code, a first AI pass picks the files that matter to each resource, so every
# plan prompt does not carry the whole source.
SELECT_ABOVE = 40_000


def select_sources(items: list[tuple[Assessment, Resource]], source: dict[str, str], ask: Callable = ask_json,
                   preview: int = 400) -> dict[str, dict[str, str]]:
    """{resource name: the subset of `source` its plan needs}. Any problem: every plan gets everything."""
    everything = {r.name: source for _, r in items}
    listing = "\n".join(f"- {name}: {text[:preview]!r}" for name, text in source.items())
    try:
        ans = ask(Prompt(
            "These Azure resources are being replaced on Leaseweb, and the application code that uses them may need changes.\n"
            + "\n".join(f"- {r.name} ({r.type}), becomes: {a.target}" for a, r in items) +
            "\nFor each resource, list the source files that use it or configure it (SDK calls, settings, "
            "infrastructure code, dependency manifests). Use only the file names below.\n" + listing +
            '\nReply JSON: {"files": {"<resource name>": ["<file name>"]}}',
            "select_sources", items=items, files=list(source)))
    except ClaudeError:
        return everything
    picked = ans.get("files") if isinstance(ans, dict) else None
    if not isinstance(picked, dict):
        return everything
    out = {}
    for _, r in items:
        names = [n for n in picked.get(r.name) or [] if isinstance(n, str) and n in source]
        out[r.name] = {n: source[n] for n in names} if names else source  # none named: keep all, never send nothing
    return out


FAILED_PREFIX = "Plan failed: "


def build_plans(
    items: list[tuple[Assessment, Resource]],
    source: dict[str, str],
    ask: Callable = ask_json,
    ops: dict | None = None,
    workers: int = 4,
    on_progress: Callable[[str, str], None] | None = None,
    per_resource: dict[str, dict[str, str]] | None = None,
) -> list[Plan]:
    """Build one plan per (assessment, resource) in parallel, keeping input order.

    A failed resource gets a placeholder plan whose first warning starts with FAILED_PREFIX,
    so one slow or failing call never discards the others.
    """
    ops = ops if ops is not None else load_operations()

    def one(item: tuple[Assessment, Resource]) -> Plan:
        assessment, resource = item
        if on_progress:
            on_progress(resource.name, "running")
        try:
            plan = build_plan(assessment, resource, (per_resource or {}).get(resource.name, source), ask=ask, ops=ops)
        except ClaudeError as e:
            if on_progress:
                on_progress(resource.name, "failed")
            return Plan(resource.name, "", [], [], [], [FAILED_PREFIX + str(e)])
        if on_progress:
            on_progress(resource.name, "done")
        return plan

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items) or 1))) as pool:
        return list(pool.map(one, items))


def build_plan(
    assessment: Assessment,
    resource: Resource,
    source: dict[str, str],
    ask: Callable = ask_json,
    ops: dict | None = None,
) -> Plan:
    ops = ops if ops is not None else load_operations()
    code = "\n\n".join(f"### {name}\n{text}" for name, text in source.items()) or "(none supplied)"
    ans = ask(Prompt(
        f"Azure resource {resource.name} ({resource.type}) has no direct Leaseweb equivalent.\n"
        f"Proposed target: {assessment.target}. Reason: {assessment.rationale}\n"
        + (f"It can only be created after these resources exist on Leaseweb: "
           + "; ".join(f"{d['name']} ({d['reason']})" for d in assessment.dependencies)
           + ". Order the steps accordingly.\n" if assessment.dependencies else "") +
        f"Propose the Leaseweb infrastructure replacement, using ONLY these Leaseweb operationIds: "
        f"{', '.join(sorted(ops))}.\n"
        f"Then list the application code changes needed, as unified diffs, for this Python source. "
        f"Only list files that need a change; leave out files that need none. Each diff must be a unified diff "
        f"with --- a/<file> and +++ b/<file> headers and @@ hunks, using the file name exactly as given after ###.\n{code}\n"
        'Keep "proposal" to 1-2 sentences and put the migration procedure in "steps", one short action per item. '
        'Reply JSON: {"proposal": str, "steps": [str], "lw_operations": [str], "code_changes": '
        '[{"file": str, "summary": str, "diff": str}]}',
        "plan", assessment=assessment, resource=resource, source=source, ops=sorted(ops)))
    warnings: list[str] = []
    valid = []
    for op in ans.get("lw_operations", []):
        if op in ops:
            valid.append(op)
        else:
            warnings.append(f"Dropped unknown Leaseweb operation '{op}'")
    try:
        changes = [CodeChange(c["file"], c["summary"], c["diff"]) for c in ans.get("code_changes", [])]
    except (KeyError, TypeError):
        raise ClaudeError("claude returned a malformed code change") from None
    if not source:
        warnings.append("no code to analyse")
    steps = [x for x in ans.get("steps", []) if isinstance(x, str)]
    return Plan(resource.name, ans.get("proposal", ""), valid, steps, changes, warnings)
