import json
import subprocess
from typing import Callable

from .models import Resource


class DiscoveryError(Exception):
    pass


def list_resources(resource_group: str, runner: Callable = subprocess.run) -> list[Resource]:
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
    return [
        Resource(i["id"], i["name"], i["type"], i.get("location", ""), i)
        for i in items
    ]
