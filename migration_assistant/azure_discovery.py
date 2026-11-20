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


NOT_INSTALLED = "The Azure CLI (az) was not found on PATH. Install it, run `az login`, then check again."
SIGN_IN = "You are not signed in to Azure, or the sign-in has expired. Run `az login` in a terminal, then check again."


def friendly_error(stderr: str, resource_group: str = "") -> str:
    """Turn az CLI error output into one sentence that says what to do."""
    text = (stderr or "").strip()
    low = text.lower()
    if "az login" in low or "aadsts" in low or "expired" in low or "no subscription found" in low:
        return SIGN_IN
    if "resourcegroupnotfound" in low or ("resource group" in low and "could not be found" in low):
        return (f"Resource group '{resource_group}' was not found in the selected subscription. "
                "Check the name, or pick another subscription in the Azure settings.")
    if "authorizationfailed" in low or "does not have authorization" in low:
        return "Your Azure account may not read this resource group. It needs at least the Reader role on it."
    if "subscription" in low and ("not found" in low or "doesn't exist" in low or "could not be found" in low):
        return "The selected subscription is not available to your Azure account. Pick another one in the Azure settings."
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first = next((ln for ln in lines if ln.upper().startswith("ERROR")), lines[0] if lines else "")
    return first.removeprefix("ERROR:").strip() or "The Azure CLI failed without a message."


def _sub(subscription: str | None) -> list[str]:
    return ["--subscription", subscription] if subscription else []


def list_resources(resource_group: str, runner: Callable = _run, subscription: str | None = None) -> list[Resource]:
    """Read-only: list resources of an Azure resource group via the az CLI."""
    try:
        proc = runner(
            ["az", "resource", "list", "-g", resource_group, "-o", "json", *_sub(subscription)],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise DiscoveryError(NOT_INSTALLED) from None
    if proc.returncode != 0:
        raise DiscoveryError(friendly_error(proc.stderr, resource_group))
    items = json.loads(proc.stdout or "[]")
    if not items:
        raise DiscoveryError(f"Resource group '{resource_group}' has no resources to migrate.")
    with ThreadPoolExecutor(max_workers=8) as pool:
        details = list(pool.map(lambda i: _details_of(i, runner), items))
    return [
        Resource(i["id"], i["name"], i["type"], i.get("location", ""),
                 _redact({k: v for k, v in {**i, **d}.items() if k not in HEADER_KEYS}))
        for i, d in zip(items, details)
    ]


def list_resource_groups(runner: Callable = _run, subscription: str | None = None) -> list[dict]:
    """Resource groups the az login can see, sorted by name (case-insensitive). Read-only."""
    try:
        proc = runner(["az", "group", "list", "--query", "[].{name:name,location:location}", "-o", "json",
                       *_sub(subscription)], capture_output=True, text=True)
    except FileNotFoundError:
        raise DiscoveryError(NOT_INSTALLED) from None
    if proc.returncode != 0:
        raise DiscoveryError(friendly_error(proc.stderr))
    groups = json.loads(proc.stdout or "[]")
    return sorted(({"name": g["name"], "location": g.get("location", "")} for g in groups), key=lambda g: g["name"].lower())


def azure_status(runner: Callable = _run) -> dict:
    """Is az installed and signed in, and as whom? Never raises.
    {"installed", "signed_in", "user", "subscription": {"id", "name"}, "tenant", "message"}"""
    out = {"installed": False, "signed_in": False, "user": "", "subscription": None, "tenant": "", "message": ""}
    try:
        proc = runner(["az", "account", "show", "-o", "json"], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return {**out, "message": NOT_INSTALLED}
    except Exception as e:  # a hung az or similar: report, never break the page
        return {**out, "installed": True, "message": f"Could not ask the Azure CLI for its sign-in: {e}"}
    out["installed"] = True
    if proc.returncode != 0:
        return {**out, "message": friendly_error(proc.stderr)}
    try:
        acct = json.loads(proc.stdout or "{}")
    except ValueError:
        return {**out, "message": "The Azure CLI answered with something unexpected. Run `az account show` to check it."}
    return {**out, "signed_in": True, "user": str((acct.get("user") or {}).get("name", "")),
            "subscription": {"id": str(acct.get("id", "")), "name": str(acct.get("name", ""))},
            "tenant": str(acct.get("tenantId", ""))}


def list_subscriptions(runner: Callable = _run) -> list[dict]:
    """Enabled subscriptions of the signed-in account: [{"id", "name", "is_default"}], sorted by name."""
    try:
        proc = runner(["az", "account", "list", "--query",
                       "[?state=='Enabled'].{id:id,name:name,isDefault:isDefault}", "-o", "json"],
                      capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise DiscoveryError(NOT_INSTALLED) from None
    if proc.returncode != 0:
        raise DiscoveryError(friendly_error(proc.stderr))
    subs = json.loads(proc.stdout or "[]")
    return sorted(({"id": str(x.get("id", "")), "name": str(x.get("name", "")), "is_default": bool(x.get("isDefault"))}
                   for x in subs if x.get("id")), key=lambda x: x["name"].lower())
