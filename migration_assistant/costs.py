"""Rough monthly compute cost: Azure VMs today against the Leaseweb instances the migration launches.

Compute only. Storage, traffic, licences and managed-service fees are not included, and the UI says so.
Leaseweb prices come live from getInstanceTypeList when a key is set, else from the spec example (which
covers only some instance types). Azure prices come from the public Azure Retail Prices API, which needs
no login: only the VM size and region are sent.
"""
import re
from pathlib import Path
from typing import Any

import yaml

from .models import Resource

AZURE_PRICES_URL = "https://prices.azure.com/api/retail/prices"
HOURS_PER_MONTH = 730


def _num(v: Any) -> float | None:
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _types(entries: list) -> dict[str, dict]:
    out = {}
    for t in entries or []:
        prices = (t or {}).get("prices") or {}
        monthly, hourly = _num(prices.get("monthly")), _num(prices.get("hourly"))
        if t.get("name") and monthly is not None:
            out[str(t["name"])] = {"monthly": monthly, "hourly": hourly}
    return out


def spec_prices(specs_dir: Path = Path("leaseweb-api")) -> dict[str, dict]:
    doc = yaml.safe_load((specs_dir / "publicCloud" / "paths" / "publicCloud_v1_instanceTypes.yaml").read_text())
    example = doc["get"]["responses"]["200"]["content"]["application/json"]["example"]
    return _types(example.get("instanceTypes"))


def leaseweb_prices(region: str, api_key: str | None, client: Any, base_url: str,
                    specs_dir: Path = Path("leaseweb-api")) -> dict:
    """{"source": "live"|"spec", "types": {name: {"monthly", "hourly"}}} for one region."""
    if api_key:
        try:
            resp = client.request("GET", base_url + "/publicCloud/v1/instanceTypes",
                                  params={"region": region, "limit": 100},
                                  headers={"X-LSW-Auth": api_key, "Accept": "application/json"}, timeout=15)
            live = _types(resp.json().get("instanceTypes")) if resp.status_code == 200 else {}
            if live:
                return {"source": "live", "types": live}
        except Exception:  # any lookup problem: fall back to the spec example
            pass
    return {"source": "spec", "types": spec_prices(specs_dir)}


def _vm_size(r: Resource) -> str:
    try:
        return str(r.properties["properties"]["hardwareProfile"]["vmSize"])
    except (KeyError, TypeError):
        return ""


def azure_vm_prices(resources: list[Resource], client: Any, currency: str = "EUR") -> dict[str, dict]:
    """{vm name: {"size", "region", "monthly"}} for the VMs whose Linux pay-as-you-go price was found."""
    out: dict[str, dict] = {}
    cache: dict[tuple[str, str], float | None] = {}
    for r in resources:
        if r.type.lower() != "microsoft.compute/virtualmachines":
            continue
        size, region = _vm_size(r), (r.location or "").lower()
        if not re.fullmatch(r"[\w-]+", size) or not re.fullmatch(r"[a-z0-9]+", region):
            continue  # both go into an OData filter: only plain names
        if (size, region) not in cache:
            cache[(size, region)] = _azure_hourly(size, region, client, currency)
        hourly = cache[(size, region)]
        if hourly is not None:
            out[r.name] = {"size": size, "region": region, "monthly": round(hourly * HOURS_PER_MONTH, 2)}
    return out


def _azure_hourly(size: str, region: str, client: Any, currency: str) -> float | None:
    flt = (f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' and armSkuName eq '{size}' "
           "and priceType eq 'Consumption'")
    try:
        resp = client.request("GET", AZURE_PRICES_URL, params={"currencyCode": currency, "$filter": flt}, timeout=15)
        items = resp.json().get("Items", []) if resp.status_code == 200 else []
    except Exception:
        return None
    linux = [i for i in items if "windows" not in str(i.get("productName", "")).lower()
             and not any(w in str(i.get("skuName", "")).lower() for w in ("spot", "low priority"))
             and str(i.get("unitOfMeasure", "")) == "1 Hour"]
    prices = [p for p in (_num(i.get("retailPrice")) for i in linux) if p is not None]
    return min(prices) if prices else None
