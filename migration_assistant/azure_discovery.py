import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .models import Resource


class DiscoveryError(Exception):
    pass


def _run(cmd: list[str], **kwargs):
    """subprocess.run, but resolves `az` through PATH so Windows finds az.cmd."""
    return subprocess.run([shutil.which(cmd[0]) or cmd[0], *cmd[1:]], **kwargs)


# Values under keys like these are replaced before anything is shown or saved.
SENSITIVE = re.compile(r"password|secret|token|customdata|connectionstring|accesskey|sharedkey|primarykey|secondarykey|\bkeys?\b", re.I)
HEADER_KEYS = {"id", "name", "type", "location"}  # already shown as columns


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if SENSITIVE.search(k) and not isinstance(v, bool) else _redact(v)) for k, v in value.items()}  # flags are not secrets
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _details(resource_id: str, runner: Callable) -> dict:
    """Configured values of one resource (`az resource show`); {} if unavailable."""
    try:
        proc = runner(["az", "resource", "show", "--ids", resource_id, "-o", "json"], capture_output=True, text=True)
        data = json.loads(proc.stdout) if proc.returncode == 0 else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_resources(resource_group: str, runner: Callable = _run) -> list[Resource]:
    """Read-only: list resources of an Azure resource group via the az CLI."""
    try:
        proc = runner(
            ["az", "resource", "list", "-g", resource_group, "-o", "json"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise DiscoveryError("az CLI not found on PATH") from None
    if proc.returncode != 0:
        raise DiscoveryError(proc.stderr.strip() or "az resource list failed")
    items = json.loads(proc.stdout or "[]")
    if not items:
        raise DiscoveryError(f"No resources found in resource group '{resource_group}'")
    with ThreadPoolExecutor(max_workers=8) as pool:
        details = list(pool.map(lambda i: _details(i["id"], runner), items))
    return [
        Resource(i["id"], i["name"], i["type"], i.get("location", ""),
                 _redact({k: v for k, v in {**i, **d}.items() if k not in HEADER_KEYS}))
        for i, d in zip(items, details)
    ]


def list_resource_groups(runner: Callable = _run) -> list[dict]:
    """Resource groups the az login can see, sorted by name (case-insensitive). Read-only."""
    try:
        proc = runner(["az", "group", "list", "--query", "[].{name:name,location:location}", "-o", "json"],
                      capture_output=True, text=True)
    except FileNotFoundError:
        raise DiscoveryError("az CLI not found on PATH") from None
    if proc.returncode != 0:
        raise DiscoveryError(proc.stderr.strip() or "az group list failed")
    groups = json.loads(proc.stdout or "[]")
    return sorted(({"name": g["name"], "location": g.get("location", "")} for g in groups), key=lambda g: g["name"].lower())
