// Pure helpers that make discovered Azure resources read like the Azure Portal (no DOM):
// default ordering, display names for locations, readable dates and Portal field labels.
// Loaded by the page before app.js; also loadable from Node for tests.
(function (root) {
  // ---- locations: "westeurope" -> "West Europe"
  const LOCATIONS = {
    global: "Global", westeurope: "West Europe", northeurope: "North Europe", uksouth: "UK South", ukwest: "UK West",
    francecentral: "France Central", francesouth: "France South", germanywestcentral: "Germany West Central",
    germanynorth: "Germany North", switzerlandnorth: "Switzerland North", switzerlandwest: "Switzerland West",
    norwayeast: "Norway East", norwaywest: "Norway West", swedencentral: "Sweden Central", polandcentral: "Poland Central",
    italynorth: "Italy North", spaincentral: "Spain Central", eastus: "East US", eastus2: "East US 2", centralus: "Central US",
    northcentralus: "North Central US", southcentralus: "South Central US", westus: "West US", westus2: "West US 2",
    westus3: "West US 3", westcentralus: "West Central US", canadacentral: "Canada Central", canadaeast: "Canada East",
    brazilsouth: "Brazil South", southeastasia: "Southeast Asia", eastasia: "East Asia", japaneast: "Japan East",
    japanwest: "Japan West", koreacentral: "Korea Central", koreasouth: "Korea South", australiaeast: "Australia East",
    australiasoutheast: "Australia Southeast", australiacentral: "Australia Central", centralindia: "Central India",
    southindia: "South India", westindia: "West India", uaenorth: "UAE North", qatarcentral: "Qatar Central",
    israelcentral: "Israel Central", southafricanorth: "South Africa North",
  };

  function locationName(loc) {
    if (!loc) return "";
    return LOCATIONS[String(loc).toLowerCase().replace(/\s+/g, "")] || loc;
  }

  // ---- dates: "2026-11-20T12:25:21.37Z" -> "20 Nov 2026, 12:25" (viewer's time zone)
  const ISO_DATE = /^\d{4}-\d\d-\d\dT\d\d:\d\d/;
  const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

  const isDate = (v) => typeof v === "string" && ISO_DATE.test(v);

  function formatDate(v) {
    // Azure sometimes omits the zone ("2026-11-20T10:51:13.9166667"); those values are UTC.
    const d = new Date(/(Z|[+-]\d\d:\d\d)$/.test(v) ? v : v + "Z");
    if (isNaN(d)) return v;
    return DATE_FMT.format(d).replace(",", "");
  }

  // ---- default order: by layer (network, identity, data, compute, monitoring), children right after their parent
  const LAYERS = [
    [["microsoft.network/virtualnetworks"], ["microsoft.network/networksecuritygroups"], ["microsoft.network/publicipaddresses"],
      ["microsoft.network/privatednszones", "microsoft.network/privatednszones/virtualnetworklinks"],
      ["microsoft.network/privateendpoints", "microsoft.network/networkinterfaces"]],
    [["microsoft.managedidentity/userassignedidentities"], ["microsoft.keyvault/vaults"]],
    [["microsoft.storage/storageaccounts"], ["microsoft.documentdb/databaseaccounts"], ["microsoft.containerregistry/registries"],
      ["microsoft.sql/servers"], ["microsoft.servicebus/namespaces"]],
    [["microsoft.compute/virtualmachines", "microsoft.compute/disks"], ["microsoft.web/serverfarms"], ["microsoft.web/sites"],
      ["microsoft.app/managedenvironments"], ["microsoft.app/containerapps"]],
    [["microsoft.operationalinsights/workspaces"], ["microsoft.insights/components"], ["microsoft.insights/actiongroups"]],
  ];
  const RANK = {};
  LAYERS.forEach((slots, layer) => slots.forEach((types, slot) => types.forEach((t) => { RANK[t] = [layer, slot]; })));

  // "zone/link" and "pe-x.nic.<guid>" belong to the parent "zone" / "pe-x".
  const parentName = (name) => name.split("/")[0].split(".nic.")[0];

  function resourceOrder(resources) {
    const key = (r) => {
      const t = r.type.toLowerCase();
      const [layer, slot] = RANK[t] || [LAYERS.length, 0];
      const base = parentName(r.name).toLowerCase();
      return [layer, slot, RANK[t] ? "" : t, base, base === r.name.toLowerCase() ? 0 : 1, r.name.toLowerCase()];
    };
    const cmp = (a, b) => { const x = key(a), y = key(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; return 0; };
    return resources.slice().sort(cmp);
  }

  // ---- labels
  const ACRONYMS = new Set(["id", "ids", "ip", "ips", "vm", "dns", "tls", "sku", "url", "uri", "nic", "os", "ssh", "http", "https", "ftp", "ftps", "sas", "acl", "acls", "ddos", "fqdn", "sql", "api"]);

  // "properties.siteConfig.alwaysOn" -> "Site config › Always on"; "clientId" -> "Client ID"
  function humanizeKey(key) {
    const seg = key.replace(/^properties\./, "").split(".").map((s) => s
      .replace(/\[(\d+)\]/g, (_, n) => " " + (+n + 1))
      .replace(/([a-z\d])([A-Z])/g, "$1 $2").replace(/[-_]+/g, " ").toLowerCase()
      .split(" ").map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w)).join(" "));
    return seg.map((t) => t.charAt(0).toUpperCase() + t.slice(1)).join(" › ");
  }

  // ---- Portal fields. A spec is a path into the resource's values, or a function of them.
  const get = (o, path) => path.split(".").reduce((x, k) => (x === null || x === undefined ? undefined : x[k]), o);
  const last = (id) => (id ? String(id).split("/").pop() : undefined);
  const list = (arr, fn) => (Array.isArray(arr) ? arr.map(fn) : undefined);
  const lastOf = (path) => (p) => last(get(p, path));

  const COMMON = [
    ["Resource group", "resourceGroup"],
    ["Created", "createdTime"],
    ["Last modified", "changedTime"],
    ["Provisioning state", "provisioningState"],
    ["Tags", (p) => (p.tags && Object.keys(p.tags).length ? Object.entries(p.tags).map(([k, v]) => `${k}: ${v}`) : undefined)],
  ];

  const FIELDS = {
    "microsoft.network/virtualnetworks": [
      ["Address space", "properties.addressSpace.addressPrefixes"],
      ["Subnets", (p) => list(get(p, "properties.subnets"), (s) => `${s.name} (${get(s, "properties.addressPrefix")})`)],
      ["DDoS protection", "properties.enableDdosProtection"],
    ],
    "microsoft.network/networksecuritygroups": [
      ["Custom security rules", (p) => (get(p, "properties.securityRules") || []).length],
      ["Associated subnets", (p) => list(get(p, "properties.subnets"), (s) => last(s.id))],
    ],
    "microsoft.network/privatednszones": [
      ["Record sets", "properties.numberOfRecordSets"],
      ["Virtual network links", "properties.numberOfVirtualNetworkLinks"],
    ],
    "microsoft.network/privatednszones/virtualnetworklinks": [
      ["Virtual network", lastOf("properties.virtualNetwork.id")],
      ["Link status", "properties.virtualNetworkLinkState"],
      ["Auto-registration", "properties.registrationEnabled"],
    ],
    "microsoft.network/privateendpoints": [
      ["Subnet", lastOf("properties.subnet.id")],
      ["Target resource", (p) => last(get(p, "properties.privateLinkServiceConnections.0.properties.privateLinkServiceId"))],
      ["Target sub-resource", (p) => get(p, "properties.privateLinkServiceConnections.0.properties.groupIds"),],
      ["Connection status", "properties.privateLinkServiceConnections.0.properties.privateLinkServiceConnectionState.status"],
      ["Network interface", (p) => last(get(p, "properties.networkInterfaces.0.id"))],
    ],
    "microsoft.network/networkinterfaces": [
      ["Private endpoint", lastOf("properties.privateEndpoint.id")],
      ["Private IP address", "properties.ipConfigurations.0.properties.privateIPAddress"],
      ["Accelerated networking", "properties.enableAcceleratedNetworking"],
      ["IP forwarding", "properties.enableIPForwarding"],
    ],
    "microsoft.managedidentity/userassignedidentities": [
      ["Client ID", "properties.clientId"],
      ["Object (principal) ID", "properties.principalId"],
      ["Tenant ID", "properties.tenantId"],
    ],
    "microsoft.keyvault/vaults": [
      ["Vault URI", "properties.vaultUri"],
      ["SKU", "properties.sku.name"],
      ["Permission model", (p) => (get(p, "properties.enableRbacAuthorization") ? "Azure role-based access control" : "Vault access policy")],
      ["Soft-delete", "properties.enableSoftDelete"],
      ["Days to retain deleted vaults", "properties.softDeleteRetentionInDays"],
      ["Public network access", "properties.publicNetworkAccess"],
      ["Directory ID", "properties.tenantId"],
    ],
    "microsoft.storage/storageaccounts": [
      ["Account kind", "kind"],
      ["SKU", "sku.name"],
      ["Access tier", "properties.accessTier"],
      ["Public network access", "properties.publicNetworkAccess"],
      ["Secure transfer required", "properties.supportsHttpsTrafficOnly"],
      ["Minimum TLS version", "properties.minimumTlsVersion"],
      ["Allow blob anonymous access", "properties.allowBlobPublicAccess"],
      ["Allow storage account key access", "properties.allowSharedKeyAccess"],
      ["Hierarchical namespace", "properties.isHnsEnabled"],
      ["Blob service endpoint", "properties.primaryEndpoints.blob"],
    ],
    "microsoft.documentdb/databaseaccounts": [
      ["Account kind", "kind"],
      ["API", "properties.EnabledApiTypes"],
      ["Capacity mode", "properties.capacityMode"],
      ["URI", "properties.documentEndpoint"],
      ["Default consistency", "properties.consistencyPolicy.defaultConsistencyLevel"],
      ["Backup policy", "properties.backupPolicy.type"],
      ["Disable local authentication", "properties.disableLocalAuth"],
      ["Public network access", "properties.publicNetworkAccess"],
      ["Free tier", "properties.enableFreeTier"],
    ],
    "microsoft.containerregistry/registries": [
      ["Login server", "properties.loginServer"],
      ["SKU", "sku.name"],
      ["Admin user", "properties.adminUserEnabled"],
      ["Public network access", "properties.publicNetworkAccess"],
      ["Anonymous pull", "properties.anonymousPullEnabled"],
      ["Zone redundancy", "properties.zoneRedundancy"],
    ],
    "microsoft.web/serverfarms": [
      ["Pricing plan", (p) => [get(p, "sku.name"), get(p, "sku.tier") && `(${get(p, "sku.tier")})`].filter(Boolean).join(" ")],
      ["Operating system", (p) => (get(p, "properties.reserved") === undefined ? undefined : get(p, "properties.reserved") ? "Linux" : "Windows")],
      ["Status", "properties.status"],
      ["Number of apps", "properties.numberOfSites"],
      ["Zone redundancy", "properties.zoneRedundant"],
    ],
    "microsoft.web/sites": [
      ["Kind", "kind"],
      ["Status", "properties.state"],
      ["Default domain", "properties.defaultHostName"],
      ["App Service plan", lastOf("properties.serverFarmId")],
      ["Runtime stack", (p) => [get(p, "properties.functionAppConfig.runtime.name"), get(p, "properties.functionAppConfig.runtime.version")].filter(Boolean).join(" ")],
      ["Operating system", (p) => (get(p, "properties.reserved") === undefined ? undefined : get(p, "properties.reserved") ? "Linux" : "Windows")],
      ["HTTPS only", "properties.httpsOnly"],
      ["Public network access", "properties.publicNetworkAccess"],
      ["Virtual network integration", lastOf("properties.virtualNetworkSubnetId")],
    ],
    "microsoft.app/managedenvironments": [
      ["Environment type", "properties.environmentMode"],
      ["Default domain", "properties.defaultDomain"],
      ["Static IP", "properties.staticIp"],
      ["Public network access", "properties.publicNetworkAccess"],
      ["Zone redundancy", "properties.zoneRedundant"],
      ["Infrastructure resource group", "properties.infrastructureResourceGroup"],
    ],
    "microsoft.app/containerapps": [
      ["Status", "properties.runningStatus"],
      ["Application URL", (p) => (get(p, "properties.configuration.ingress.fqdn") ? "https://" + get(p, "properties.configuration.ingress.fqdn") : undefined)],
      ["Container Apps environment", lastOf("properties.managedEnvironmentId")],
      ["Ingress traffic", (p) => (get(p, "properties.configuration.ingress.external") === undefined ? undefined : get(p, "properties.configuration.ingress.external") ? "Accepting traffic from anywhere" : "Limited to the environment")],
      ["Target port", "properties.configuration.ingress.targetPort"],
      ["Revision mode", "properties.configuration.activeRevisionsMode"],
      ["Latest revision", "properties.latestRevisionName"],
      ["Replicas (min - max)", (p) => (get(p, "properties.template.scale.maxReplicas") === undefined ? undefined : `${get(p, "properties.template.scale.minReplicas") || 0} - ${get(p, "properties.template.scale.maxReplicas")}`)],
      ["Workload profile", "properties.workloadProfileName"],
    ],
    "microsoft.operationalinsights/workspaces": [
      ["Workspace ID", "properties.customerId"],
      ["Pricing tier", "properties.sku.name"],
      ["Data retention (days)", "properties.retentionInDays"],
      ["Daily cap (GB)", (p) => (get(p, "properties.workspaceCapping.dailyQuotaGb") === -1 ? "No limit" : get(p, "properties.workspaceCapping.dailyQuotaGb"))],
      ["Public network access for ingestion", "properties.publicNetworkAccessForIngestion"],
      ["Public network access for query", "properties.publicNetworkAccessForQuery"],
    ],
    "microsoft.insights/components": [
      ["Application type", "properties.Application_Type"],
      ["Application ID", "properties.AppId"],
      ["Instrumentation key", "properties.InstrumentationKey"],
      ["Workspace", lastOf("properties.WorkspaceResourceId")],
      ["Ingestion mode", "properties.IngestionMode"],
      ["Retention (days)", "properties.RetentionInDays"],
    ],
    "microsoft.insights/actiongroups": [
      ["Display name", "properties.groupShortName"],
      ["Enabled", "properties.enabled"],
    ],
  };

  const fmt = (v) => (typeof v === "boolean" ? (v ? "Yes" : "No") : isDate(v) ? formatDate(v) : Array.isArray(v) ? v.map(fmt).join(", ") : String(v));
  const present = (v) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length);

  // -> { rows: [[label, text]], curated }. curated is false for types without a Portal field list;
  // the caller then adds the remaining values with humanized labels.
  function portalFields(r) {
    const p = r.properties || {};
    const specs = FIELDS[r.type.toLowerCase()];
    const rows = [];
    COMMON.concat(specs || []).forEach(([label, spec]) => {
      const v = typeof spec === "function" ? spec(p) : get(p, spec);
      if (present(v)) rows.push([label, fmt(v)]);
    });
    return { rows, curated: !!specs };
  }

  const COMMON_KEYS = new Set(["resourceGroup", "createdTime", "changedTime", "provisioningState", "etag", "properties.provisioningState"]);
  const isCommonKey = (k) => COMMON_KEYS.has(k) || k === "tags" || k.startsWith("tags.");

  const api = { locationName, isDate, formatDate, resourceOrder, humanizeKey, portalFields, isCommonKey, fmt };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PortalLib = api;
})(typeof window !== "undefined" ? window : globalThis);
