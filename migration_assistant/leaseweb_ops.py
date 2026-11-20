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


def load_launch_options(specs_dir: Path = Path("leaseweb-api")) -> dict[str, list[dict]]:
    """Allowed values for the launchInstance dropdowns, straight from the specs.

    Regions carry their location (e.g. eu-west-3 -> Amsterdam) taken from the getRegionList example.
    """
    cloud = specs_dir / "publicCloud"

    def enum(name: str) -> list:
        return yaml.safe_load((cloud / "components" / "schemas" / f"{name}.yaml").read_text())["enum"]

    regions_doc = yaml.safe_load((cloud / "paths" / "publicCloud_v1_regions.yaml").read_text())
    example = regions_doc["get"]["responses"]["200"]["content"]["application/json"]["example"]["regions"]
    locations = {r["name"]: r["location"] for r in example}

    def options(values: list, described: dict | None = None) -> list[dict]:
        return [{"value": str(v), "description": (described or {}).get(v, "")} for v in values]

    return {
        "region": options(enum("regionName"), locations),
        "type": options(enum("typeName")),
        "contractType": options(enum("contractType")),
        "rootDiskStorageType": options(enum("storageType")),
    }
