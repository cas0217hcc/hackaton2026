from typing import Protocol

from .leaseweb_ops import load_operations
from .models import Assessment, DryRunCall

# Placeholder request values until a real Leaseweb account and API key exist.
PLACEHOLDER_BODIES = {
    "launchInstance": {"regionName": "eu-west-3", "typeName": "lsw.c3.large", "imageId": "UBUNTU_22_04_64BIT", "rootDiskSize": 50},
    "createObjectStorageBucket": {"name": "<bucket-name>", "region": "nl-01"},
    "createSecurityGroup": {"name": "<security-group-name>"},
}


def build_calls(assessments: list[Assessment], ops: dict | None = None) -> list[DryRunCall]:
    """One DryRunCall per Leaseweb operation of each Direct resource."""
    ops = ops if ops is not None else load_operations()
    calls = []
    for a in assessments:
        if a.route != "direct":
            continue
        for op in a.lw_operations:
            method, path = ops[op]
            calls.append(DryRunCall(method, path, op, dict(PLACEHOLDER_BODIES.get(op, {}))))
    return calls


class Executor(Protocol):
    def execute(self, call: DryRunCall) -> dict: ...


class DryRunExecutor:
    """Default executor: records what would be sent, sends nothing."""

    def execute(self, call: DryRunCall) -> dict:
        return {"dry_run": True, "sent": False, "method": call.method, "path": call.path,
                "operation_id": call.operation_id, "body": call.body}
