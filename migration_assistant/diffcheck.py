"""Check whether the AI's code changes apply to the source they were written for.

`git apply --check` runs in the source folder (it also works outside a git repository) and changes
nothing. The diff's file names may carry the a/ b/ prefixes and the folder prefix the prompt used,
so several strip levels are tried.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .models import CodeChange, Plan


def folder_prefixes(dirs: list[Path]) -> dict[str, Path]:
    """The prefix read_sources gives each folder's files, mapped back to the folder."""
    out: dict[str, Path] = {}
    seen: list[str] = []
    for d in dirs:
        d = Path(d)
        base = d.name or "src"
        prefix = base if base not in seen else f"{base}-{seen.count(base) + 1}"
        seen.append(base)
        out[prefix] = d
    return out


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run([shutil.which(cmd[0]) or cmd[0], *cmd[1:]], **kw)


def check_change(change: CodeChange, folders: dict[str, Path], runner: Callable = _run) -> tuple[str, str]:
    """("applies" | "conflicts" | "unchecked", note)."""
    prefix = change.file.split("/", 1)[0]
    folder = folders.get(prefix)
    if folder is None or not folder.is_dir():
        return "unchecked", "The source folder of this file is not known."
    if "@@" not in change.diff:
        return "unchecked", "The AI did not return a unified diff for this file."
    text = change.diff if change.diff.endswith("\n") else change.diff + "\n"
    # a/<prefix>/file, a/file or <prefix>/file, file: use the strip level that names a file in the folder
    # (a new file, --- /dev/null, is checked at every level until one works).
    old = next((ln[4:].split("\t")[0].strip() for ln in text.splitlines() if ln.startswith("--- ")), "")
    levels = [n for n in (2, 1, 0) if old == "/dev/null" or (folder / Path(*old.split("/")[n:] or ["."])).is_file()]
    if not levels:
        return "conflicts", f"The file named in the diff ({old or 'none'}) is not in {folder}."
    with tempfile.TemporaryDirectory(prefix="migration-assistant-") as tmp:
        patch = Path(tmp) / "change.patch"
        patch.write_text(text)
        first_error = ""
        for strip in levels:
            try:
                proc = runner(["git", "apply", "--check", f"-p{strip}", str(patch)], cwd=str(folder),
                              capture_output=True, text=True, timeout=30)
            except FileNotFoundError:
                return "unchecked", "git is not installed, so the diff was not checked."
            except subprocess.TimeoutExpired:
                return "unchecked", "git apply --check took too long."
            if proc.returncode == 0:
                return "applies", f"Applies cleanly with git apply -p{strip} in {folder}."
            lines = [ln for ln in (proc.stderr or proc.stdout).strip().splitlines() if ln.strip()]
            first_error = first_error or "; ".join(lines[:2])
    return "conflicts", f"Does not apply to the current source: {first_error}" if first_error else "Does not apply to the current source."


def check_plans(plans: list[Plan], dirs: list[Path], runner: Callable = _run) -> None:
    """Fill `check` and `check_note` on every code change, in place."""
    folders = folder_prefixes(dirs)
    for p in plans:
        for c in p.code_changes:
            c.check, c.check_note = check_change(c, folders, runner)


def patch_text(plans: list[Plan]) -> str:
    """Every code change as one patch file, each diff headed by the plan it belongs to."""
    parts = []
    for p in plans:
        for c in p.code_changes:
            if c.diff.strip():
                parts.append(f"# {p.resource_name}: {c.file} - {c.summary}\n{c.diff.rstrip()}\n")
    return "\n".join(parts)
