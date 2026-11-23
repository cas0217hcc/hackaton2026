"""Rebuild migration_assistant/mock_data/hackaton-2026-rg.json, the Azure data of mock mode (MOCK_AZURE).

1. Run a real Discover of hackaton-2026-rg in the app, so data/state.json holds it (that file is git-ignored).
2. python scripts/make_mock_fixture.py

What it does: keeps names, types, locations, tags and storage contents; replaces the subscription id, every other
GUID and e-mail addresses; drops systemData; and adds the settings Terraform configures (demo_app/infra), because a
discovery does not always return them. Edit INNER below when the Terraform changes. The script refuses to write a
fixture that still holds the real subscription id or an e-mail address.
"""
import json
import re
import sys
import uuid
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
source = root / "data/state.json"
if not source.exists():
    sys.exit("data/state.json not found: run a real Discover of hackaton-2026-rg in the app first.")
state = json.loads(source.read_text())
if state.get("resource_group") != "hackaton-2026-rg" or not state.get("resources"):
    sys.exit("data/state.json does not hold a discovery of hackaton-2026-rg.")
REAL_SUB = state["subscription"]
MOCK_SUB = "00000000-0000-4000-8000-000000000000"
RG = "hackaton-2026-rg"
NS = uuid.UUID("6f1c2b1e-5d4a-4c1e-9a43-0d5f2f9e7a10")
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def scrub(text: str) -> str:
    text = text.replace(REAL_SUB, MOCK_SUB)
    text = GUID.sub(lambda m: m.group(0) if m.group(0) == MOCK_SUB else str(uuid.uuid5(NS, m.group(0).lower())), text)
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "someone@example.com", text)


def rid(provider: str, name: str) -> str:
    return f"/subscriptions/{MOCK_SUB}/resourceGroups/{RG}/providers/{provider}/{name}"


VNET = rid("Microsoft.Network/virtualNetworks", "vnet-hack")
NSG = rid("Microsoft.Network/networkSecurityGroups", "nsg-hack2026-r8l54-apps")
SUBNET = {k: f"{VNET}/subnets/snet-hack2026-r8l54-{k}" for k in ("cae", "func", "pe")}
ST_APP = rid("Microsoft.Storage/storageAccounts", "sthack2026r8l54app")
ST_FUNC = rid("Microsoft.Storage/storageAccounts", "sthack2026r8l54func")
COSMOS = rid("Microsoft.DocumentDB/databaseAccounts", "cosmos-hack2026-r8l54")
KV = rid("Microsoft.KeyVault/vaults", "kv-hack2026-r8l54")
LOG = rid("Microsoft.OperationalInsights/workspaces", "log-hack2026-r8l54")
APPI = rid("Microsoft.Insights/components", "appi-hack2026-r8l54")
CAE = rid("Microsoft.App/managedEnvironments", "cae-hack2026-r8l54")
ASP = rid("Microsoft.Web/serverFarms", "asp-hack2026-r8l54-func")
ID_API = rid("Microsoft.ManagedIdentity/userAssignedIdentities", "id-hack2026-r8l54-api")
ID_WORKER = rid("Microsoft.ManagedIdentity/userAssignedIdentities", "id-hack2026-r8l54-worker")
API_CLIENT = str(uuid.uuid5(NS, "api-client"))
WORKER_CLIENT = str(uuid.uuid5(NS, "worker-client"))


def ep(account: str, svc: str) -> str:
    return f"https://{account}.{svc}.core.windows.net/"


COSMOS_EP = "https://cosmos-hack2026-r8l54.documents.azure.com:443/"
KV_URI = "https://kv-hack2026-r8l54.vault.azure.net/"
APPI_CS = "InstrumentationKey=<redacted>;IngestionEndpoint=https://westeurope-5.in.applicationinsights.azure.com/"


def storage(account: str) -> dict:
    return {"primaryEndpoints": {s: ep(account, s) for s in ("blob", "queue", "table", "file")},
            "publicNetworkAccess": "Disabled", "allowSharedKeyAccess": False, "minimumTlsVersion": "TLS1_2",
            "supportsHttpsTrafficOnly": True}


INNER = {
    "Microsoft.Network/virtualNetworks": lambda n: {
        "addressSpace": {"addressPrefixes": ["10.20.0.0/16"]},
        "subnets": [{"name": SUBNET[k].rsplit("/", 1)[1], "id": SUBNET[k], "properties": {
            "addressPrefix": p, "networkSecurityGroup": {"id": NSG},
            **({"delegations": [{"name": d, "properties": {"serviceName": "Microsoft.App/environments"}}]} if d else {})}}
            for k, p, d in (("cae", "10.20.2.0/24", "containerapps"), ("func", "10.20.3.0/24", "flexconsumption"),
                            ("pe", "10.20.4.0/24", None))]},
    "Microsoft.Network/networkSecurityGroups": lambda n: {
        "securityRules": []},  # Azure also lists the subnets here; left out so vnet <-> nsg is not a cycle
    "Microsoft.Storage/storageAccounts": lambda n: storage(n),
    "Microsoft.DocumentDB/databaseAccounts": lambda n: {
        "documentEndpoint": COSMOS_EP, "disableLocalAuth": True, "databaseAccountOfferType": "Standard",
        "consistencyPolicy": {"defaultConsistencyLevel": "Session"}, "capabilities": [{"name": "EnableServerless"}],
        "locations": [{"locationName": "West Europe", "failoverPriority": 0}]},
    "Microsoft.KeyVault/vaults": lambda n: {
        "vaultUri": KV_URI, "enableRbacAuthorization": True, "enableSoftDelete": True, "softDeleteRetentionInDays": 7,
        "sku": {"family": "A", "name": "standard"}},
    "Microsoft.OperationalInsights/workspaces": lambda n: {"retentionInDays": 30, "sku": {"name": "PerGB2018"}},
    "Microsoft.Insights/components": lambda n: {"WorkspaceResourceId": LOG, "Application_Type": "web",
                                                "ConnectionString": APPI_CS},
    "Microsoft.App/managedEnvironments": lambda n: {
        "vnetConfiguration": {"infrastructureSubnetId": SUBNET["cae"], "internal": False},
        "workloadProfiles": [{"name": "Consumption", "workloadProfileType": "Consumption"}],
        "appLogsConfiguration": {"destination": "log-analytics", "logAnalyticsConfiguration": {"customerId": "log-hack2026-r8l54"}}},
    "Microsoft.App/containerApps": lambda n: {
        "managedEnvironmentId": CAE, "workloadProfileName": "Consumption",
        "configuration": {"ingress": {"external": True, "targetPort": 8000, "transport": "auto"}},
        "template": {"containers": [{"name": "api", "image": "products-api:latest", "resources": {"cpu": 0.5, "memory": "1Gi"},
                                     "env": [{"name": k, "value": v} for k, v in (
                                         ("AZURE_CLIENT_ID", API_CLIENT),
                                         ("STORAGE_QUEUE_ENDPOINT", ep("sthack2026r8l54app", "queue")),
                                         ("PRODUCTS_QUEUE", "products"),
                                         ("STORAGE_BLOB_ENDPOINT", ep("sthack2026r8l54app", "blob")),
                                         ("IMAGES_CONTAINER", "product-images"),
                                         ("KEYVAULT_URI", KV_URI), ("API_KEY_SECRET_NAME", "products-api-key"),
                                         ("COSMOS_ENDPOINT", COSMOS_EP), ("COSMOS_DATABASE", "shop"),
                                         ("COSMOS_CONTAINER", "products"),
                                         ("APPLICATIONINSIGHTS_CONNECTION_STRING", APPI_CS))]}],
                     "scale": {"minReplicas": 1, "maxReplicas": 3}}},
    "Microsoft.Web/serverFarms": lambda n: {"reserved": True},
    "Microsoft.Web/sites": lambda n: {
        "serverFarmId": ASP, "virtualNetworkSubnetId": SUBNET["func"], "httpsOnly": True,
        "defaultHostName": "func-hack2026-r8l54-worker.azurewebsites.net",
        "siteConfig": {"linuxFxVersion": "", "vnetRouteAllEnabled": True, "appSettings": [{"name": k, "value": v} for k, v in (
            ("AZURE_CLIENT_ID", WORKER_CLIENT),
            ("AzureWebJobsStorage__accountName", "sthack2026r8l54func"), ("AzureWebJobsStorage__credential", "managedidentity"),
            ("ProductsQueue__queueServiceUri", "https://sthack2026r8l54app.queue.core.windows.net"),
            ("PRODUCTS_QUEUE", "products"), ("STORAGE_BLOB_ENDPOINT", ep("sthack2026r8l54app", "blob")),
            ("IMAGES_CONTAINER", "product-images"),
            ("CosmosDBConnection__accountEndpoint", COSMOS_EP), ("COSMOS_ENDPOINT", COSMOS_EP),
            ("COSMOS_DATABASE", "shop"), ("COSMOS_CONTAINER", "products"),
            ("MAX_SCHEDULED_RETRIES", "3"), ("RETRY_BASE_SECONDS", "10"))]},
        "functionAppConfig": {"runtime": {"name": "python", "version": "3.11"},
                              "scaleAndConcurrency": {"maximumInstanceCount": 40, "instanceMemoryMB": 2048},
                              "deployment": {"storage": {"type": "blobContainer",
                                                         "value": ep("sthack2026r8l54func", "blob") + "deployments"}}}},
    "Microsoft.Network/privateDnsZones": lambda n: {"numberOfRecordSets": 3},
    "Microsoft.Network/privateDnsZones/virtualNetworkLinks": lambda n: {
        "virtualNetwork": {"id": VNET}, "registrationEnabled": False},
    "microsoft.insights/actiongroups": lambda n: {
        "groupShortName": "SmartDetect", "enabled": True,
        "armRoleReceivers": [{"name": "Monitoring Contributor", "useCommonAlertSchema": True},
                             {"name": "Monitoring Reader", "useCommonAlertSchema": True}]},
}


def private_endpoint(name: str) -> dict:
    which, svc = name.removeprefix("pe-hack2026-r8l54-").split("-")
    account = ST_APP if which == "app" else ST_FUNC
    nic = next(r["name"] for r in state["resources"] if r["name"].startswith(name + ".nic."))
    return {"subnet": {"id": SUBNET["pe"]},
            "privateLinkServiceConnections": [{"name": f"psc-hack2026-r8l54-{which}-{svc}", "properties": {
                "privateLinkServiceId": account, "groupIds": [svc]}}],
            "networkInterfaces": [{"id": rid("Microsoft.Network/networkInterfaces", nic)}]}


def nic(name: str) -> dict:
    pe = name.split(".nic.")[0]
    return {"privateEndpoint": {"id": rid("Microsoft.Network/privateEndpoints", pe)},
            "ipConfigurations": [{"name": "privateEndpointIpConfig", "properties": {"subnet": {"id": SUBNET["pe"]}}}]}


def system_topic(name: str) -> dict:
    account = ST_APP if name.startswith("sthack2026r8l54app") else ST_FUNC
    return {"source": account, "topicType": "Microsoft.Storage.StorageAccounts"}


EXTRA = {
    "Microsoft.Storage/storageAccounts": {"kind": "StorageV2", "sku": {"name": "Standard_LRS", "tier": "Standard"}},
    "Microsoft.DocumentDB/databaseAccounts": {"kind": "GlobalDocumentDB"},
    "Microsoft.Web/serverFarms": {"kind": "functionapp", "sku": {"name": "FC1", "tier": "FlexConsumption"}},
    "Microsoft.Web/sites": {"kind": "functionapp,linux"},
    "Microsoft.Insights/components": {"kind": "web"},
}

out = []
for r in state["resources"]:
    props = {k: v for k, v in (r["properties"] or {}).items() if k not in ("systemData",)}
    name, rtype = r["name"], r["type"]
    if rtype == "Microsoft.Network/privateEndpoints":
        inner = private_endpoint(name)
    elif rtype == "Microsoft.Network/networkInterfaces":
        inner = nic(name)
    elif rtype == "Microsoft.EventGrid/systemTopics":
        inner = system_topic(name)
    else:
        inner = INNER.get(rtype, lambda n: None)(name)
    if inner is not None:
        props["properties"] = inner
    for k, v in EXTRA.get(rtype, {}).items():
        props[k] = v
    if rtype == "Microsoft.App/containerApps":
        props["identity"] = {"type": "UserAssigned", "userAssignedIdentities": {ID_API: {"clientId": API_CLIENT}}}
    if rtype == "Microsoft.Web/sites":
        props["identity"] = {"type": "UserAssigned", "userAssignedIdentities": {ID_WORKER: {"clientId": WORKER_CLIENT}}}
    if rtype == "Microsoft.ManagedIdentity/userAssignedIdentities":
        props["properties"] = {"clientId": API_CLIENT if name.endswith("-api") else WORKER_CLIENT,
                               "tenantId": str(uuid.uuid5(NS, "tenant"))}
    out.append({"id": r["id"], "name": name, "type": rtype, "location": r["location"], "properties": props})

text = scrub(json.dumps({"resource_group": RG, "location": "westeurope", "resources": out}, indent=1))
dest = root / "migration_assistant/mock_data/hackaton-2026-rg.json"
dest.parent.mkdir(exist_ok=True)
dest.write_text(text + "\n", encoding="utf-8", newline="\n")
if REAL_SUB in text or re.search(r"[\w.+-]+@(?!example\.com)[\w-]+\.[\w.]+", text):
    sys.exit("Refusing to write: the fixture still holds the real subscription id or an e-mail address.")
print(dest, len(out), "resources,", len(text), "bytes")
