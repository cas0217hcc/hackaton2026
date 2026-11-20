from pathlib import Path

import yaml

SPEC_DIRS = ("publicCloud", "objectStorage", "privateNetworks")
METHODS = ("get", "post", "put", "patch", "delete")


def load_operations(specs_dir: Path = Path("leaseweb-api")) -> dict[str, tuple[str, str]]:
    """Map operationId -> (HTTP method, path) across the Leaseweb OpenAPI specs."""
    ops: dict[str, tuple[str, str]] = {}
    for name in SPEC_DIRS:
        root = specs_dir / name
        spec = yaml.safe_load((root / "openapi.yaml").read_text())
        for path, item in spec.get("paths", {}).items():
            ref = item.get("$ref") if isinstance(item, dict) else None
            if ref:
                item = yaml.safe_load((root / ref).read_text())
            for method in METHODS:
                op = item.get(method)
                if op and op.get("operationId"):
                    ops[op["operationId"]] = (method.upper(), path)
    return ops
