import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .models import Resource


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess.run with the executable resolved first, so Windows finds az.cmd (subprocess ignores PATHEXT)."""
    return subprocess.run([shutil.which(cmd[0]) or cmd[0], *cmd[1:]], **kw)


class DiscoveryError(Exception):
    pass


# Values under keys like these are replaced before anything is shown or saved.
SENSITIVE = re.compile(r"password|secret|token|customdata|connectionstring|accesskey|sharedkey|primarykey|secondarykey|\bkeys?\b", re.I)
HEADER_KEYS = {"id", "name", "type", "location"}  # already shown as columns


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {k: ("***" if SENSITIVE.search(k) and not isinstance(v, bool) else _redact(v)) for k, v in value.items()}  # flags are not secrets
        # Settings as name/value pairs (app settings, container env vars): the name says whether the value is secret.
        name = value.get("name")
        if isinstance(name, str) and SENSITIVE.search(name) and "value" in out and not isinstance(out["value"], bool):
            out["value"] = "***"
        return out
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


STORAGE_SERVICES = {  # what a storage account holds besides its configuration (management plane, Reader is enough)
    "containers": "blobServices/default/containers",
    "queues": "queueServices/default/queues",
    "tables": "tableServices/default/tables",
    "shares": "fileServices/default/shares",
}
STORAGE_API = "2023-05-01"


def _storage_services(resource_id: str, runner: Callable) -> dict:
    """Names of the blob containers, queues, tables and file shares in a storage account.
    A kind that cannot be read is left out, so an unknown never looks like 'none'."""
    found: dict[str, list[str]] = {}
    for kind, sub in STORAGE_SERVICES.items():
        url = f"https://management.azure.com{resource_id}/{sub}?api-version={STORAGE_API}"
        try:
            proc = runner(["az", "rest", "--method", "get", "--url", url, "-o", "json"], capture_output=True, text=True)
            data = json.loads(proc.stdout) if proc.returncode == 0 else None
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("value"), list):
            found[kind] = sorted(str(v.get("name", "")) for v in data["value"] if isinstance(v, dict))
    return found


def _details_of(item: dict, runner: Callable) -> dict:
    d = _details(item["id"], runner)
    if item.get("type", "").lower() == "microsoft.storage/storageaccounts":
        services = _storage_services(item["id"], runner)
        if services:
            d = {**d, "services": services}
    return d


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
        details = list(pool.map(lambda i: _details_of(i, runner), items))
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
