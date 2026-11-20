from pathlib import Path
from typing import Callable

from .claude_cli import ask_json
from .leaseweb_ops import load_operations
from .models import Assessment, CodeChange, Plan, Resource


def read_source(source_dir: Path | None, max_bytes: int = 200_000) -> dict[str, str]:
    """Return {relative path: text} for .py files under source_dir (capped in total size)."""
    if source_dir is None or not Path(source_dir).is_dir():
        return {}
    files: dict[str, str] = {}
    total = 0
    for p in sorted(Path(source_dir).rglob("*.py")):
        text = p.read_text(errors="replace")
        total += len(text)
        if total > max_bytes:
            break
        files[str(p.relative_to(source_dir))] = text
    return files


def build_plan(
    assessment: Assessment,
    resource: Resource,
    source: dict[str, str],
    ask: Callable = ask_json,
    ops: dict | None = None,
) -> Plan:
    ops = ops if ops is not None else load_operations()
    code = "\n\n".join(f"### {name}\n{text}" for name, text in source.items()) or "(none supplied)"
    ans = ask(
        f"Azure resource {resource.name} ({resource.type}) has no direct Leaseweb equivalent.\n"
        f"Proposed target: {assessment.target}. Reason: {assessment.rationale}\n"
        f"Propose the Leaseweb infrastructure replacement, using ONLY these Leaseweb operationIds: "
        f"{', '.join(sorted(ops))}.\n"
        f"Then list the application code changes needed, as unified diffs, for this Python source:\n{code}\n"
        'Reply JSON: {"proposal": str, "lw_operations": [str], "code_changes": '
        '[{"file": str, "summary": str, "diff": str}]}'
    )
    warnings: list[str] = []
    valid = []
    for op in ans.get("lw_operations", []):
        if op in ops:
            valid.append(op)
        else:
            warnings.append(f"Dropped unknown Leaseweb operation '{op}'")
    changes = [CodeChange(c["file"], c["summary"], c["diff"]) for c in ans.get("code_changes", [])]
    if not source:
        warnings.append("no code to analyse")
    return Plan(resource.name, ans.get("proposal", ""), valid, changes, warnings)
