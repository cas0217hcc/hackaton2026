import re
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


def _load_ref(node: dict, base: Path) -> tuple[dict, Path]:
    """Follow one `$ref` (a path relative to `base`); returns the target node and its folder."""
    ref = node.get("$ref") if isinstance(node, dict) else None
    if not ref:
        return node or {}, base
    target = (base / ref).resolve()
    return yaml.safe_load(target.read_text()) or {}, target.parent


def _first_paragraph(text: str, limit: int = 400) -> str:
    para = (text or "").strip().split("\n\n")[0].replace("\n", " ").strip()
    return para if len(para) <= limit else para[: limit - 1].rstrip() + "…"


def _body_fields(op: dict, base: Path) -> list[dict]:
    """Request body fields of an operation: name, type, description, required, allowed values."""
    schema_node = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")
    if not schema_node:
        return []
    schema, schema_dir = _load_ref(schema_node, base)
    required = set(schema.get("required") or [])
    fields = []
    for name, prop in (schema.get("properties") or {}).items():
        node, _ = _load_ref(prop, schema_dir)
        kind = node.get("type", "")
        if kind == "array":
            kind = f"array of {(node.get('items') or {}).get('type', 'values')}"
        fields.append({"name": name, "type": kind, "description": _first_paragraph(node.get("description", ""), 300),
                       "required": name in required, "enum": [str(v) for v in node.get("enum") or []]})
    return fields


def load_operation_docs(specs_dir: Path = Path("leaseweb-api")) -> dict[str, dict]:
    """operationId -> what the spec says about the call: method, path, summary, description,
    path parameters and request body fields."""
    docs: dict[str, dict] = {}
    for name in SPEC_DIRS:
        root = specs_dir / name
        spec = yaml.safe_load((root / "openapi.yaml").read_text())
        for path, item in spec.get("paths", {}).items():
            ref = item.get("$ref") if isinstance(item, dict) else None
            base = root
            if ref:
                base = (root / ref).resolve().parent
                item = yaml.safe_load((root / ref).read_text())
            for method in METHODS:
                op = item.get(method)
                if op and op.get("operationId"):
                    docs[op["operationId"]] = {
                        "id": op["operationId"], "method": method.upper(), "path": path,
                        "summary": op.get("summary", ""), "description": _first_paragraph(op.get("description", "")),
                        "path_params": re.findall(r"\{([^}/]+)\}", path), "body_fields": _body_fields(op, base),
                    }
    return docs


def load_responses(specs_dir: Path = Path("leaseweb-api")) -> dict[str, dict]:
    """operationId -> its success response in the specs: {"status": int, "example": JSON or None,
    "schema": node or None, "base": folder its $refs are relative to}. Used by the fake Leaseweb API (mock/leaseweb.py),
    so what it answers has the shape Leaseweb documents."""
    out: dict[str, dict] = {}
    for name in SPEC_DIRS:
        root = specs_dir / name
        spec = yaml.safe_load((root / "openapi.yaml").read_text())
        for path, item in spec.get("paths", {}).items():
            ref = item.get("$ref") if isinstance(item, dict) else None
            base = root
            if ref:
                base = (root / ref).resolve().parent
                item = yaml.safe_load((root / ref).read_text())
            for method in METHODS:
                op = item.get(method)
                if not (op and op.get("operationId")):
                    continue
                codes = sorted(c for c in (op.get("responses") or {}) if str(c).isdigit() and 200 <= int(c) < 300)
                if not codes:
                    continue
                resp, resp_base = _load_ref(op["responses"][codes[0]], base)
                media = ((resp.get("content") or {}).get("application/json") or {})
                out[op["operationId"]] = {"status": int(codes[0]), "example": media.get("example"),
                                          "schema": media.get("schema"), "base": resp_base}
    return out


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}


def schema_errors(value, node, base: Path, where: str = "$", depth: int = 0) -> list[str]:
    """Where `value` breaks an OpenAPI 3.0 schema. Covers what the Leaseweb specs use: $ref, type, nullable,
    enum, required, properties, items and allOf. Unknown keywords are ignored, so this errs on accepting."""
    if node is None or depth > 40:
        return []
    node, base = _load_ref(node, base)
    if value is None:
        return [] if node.get("nullable") or not node.get("type") else [f"{where}: null is not allowed"]
    errors: list[str] = []
    for part in node.get("allOf") or []:
        errors += schema_errors(value, part, base, where, depth + 1)
    kind = node.get("type")
    expected = _TYPES.get(kind)
    if expected and (not isinstance(value, expected) or (kind in ("integer", "number") and isinstance(value, bool))):
        return errors + [f"{where}: expected {kind}, got {type(value).__name__}"]
    if node.get("enum") and value not in node["enum"]:
        errors.append(f"{where}: {value!r} is not one of {node['enum']}")
    if isinstance(value, dict):
        errors += [f"{where}: missing {k}" for k in node.get("required") or [] if k not in value]
        for k, sub in (node.get("properties") or {}).items():
            if k in value:
                errors += schema_errors(value[k], sub, base, f"{where}.{k}", depth + 1)
    if isinstance(value, list) and node.get("items"):
        for i, v in enumerate(value):
            errors += schema_errors(v, node["items"], base, f"{where}[{i}]", depth + 1)
    return errors


def find_operations(text: str, op_ids) -> list[str]:
    """Operation ids named in free text, in order of first appearance (whole words only)."""
    if not text or not op_ids:
        return []
    pattern = "(?<![\\w/])(?:" + "|".join(re.escape(i) for i in sorted(op_ids, key=len, reverse=True)) + ")(?![\\w/])"
    found: list[str] = []
    for m in re.finditer(pattern, text):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found
