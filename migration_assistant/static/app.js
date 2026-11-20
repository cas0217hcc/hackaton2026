const STAGES = ["discover", "assess", "plan", "migrate"];
const $ = (id) => document.getElementById(id);
const done = {};
let lastAction = null;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else e.setAttribute(k, v);
  }
  for (const kid of kids) e.append(kid);
  return e;
}

// Authored line icons (static strings, no user data), keyed by Azure resource type.
const ICON_PATHS = {
  server: '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/>',
  disk: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.8"/>',
  bucket: '<ellipse cx="12" cy="7.5" rx="8" ry="2.5"/><path d="M4 7.5l1.6 11a2 2 0 0 0 2 1.7h8.8a2 2 0 0 0 2-1.7L20 7.5"/>',
  network: '<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="19" r="2.2"/><circle cx="19" cy="19" r="2.2"/><path d="M12 7.2v4.3M12 11.5l-5.8 5.5M12 11.5l5.8 5.5"/>',
  shield: '<path d="M12 3l7 3v5.5c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6l7-3z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
  globe: '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  plug: '<rect x="5" y="8" width="14" height="8" rx="2"/><path d="M9 8V4M15 8V4M12 16v4"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12L20 3M16 7l3 3"/>',
  bolt: '<path d="M13 2L5 13h6l-1 9 8-11h-6l1-9z"/>',
  window: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
  database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  queue: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12L4 7.5M12 12v9"/>',
};
const TYPE_ICONS = {
  "microsoft.compute/virtualmachines": "server", "microsoft.compute/disks": "disk",
  "microsoft.storage/storageaccounts": "bucket", "microsoft.network/virtualnetworks": "network",
  "microsoft.network/networksecuritygroups": "shield", "microsoft.network/publicipaddresses": "globe",
  "microsoft.network/networkinterfaces": "plug", "microsoft.keyvault/vaults": "key",
  "microsoft.eventgrid/systemtopics": "bolt", "microsoft.web/sites": "window",
  "microsoft.documentdb/databaseaccounts": "database", "microsoft.sql/servers": "database",
  "microsoft.servicebus/namespaces": "queue",
};
// Official Microsoft Azure service icons (static/azure-icons), keyed by resource type.
const AZURE_ICONS = {
  "microsoft.compute/virtualmachines": "virtual-machine", "microsoft.compute/disks": "disks",
  "microsoft.storage/storageaccounts": "storage-accounts", "microsoft.network/virtualnetworks": "virtual-networks",
  "microsoft.network/networksecuritygroups": "network-security-groups", "microsoft.network/publicipaddresses": "public-ip-addresses",
  "microsoft.network/networkinterfaces": "network-interfaces", "microsoft.network/privateendpoints": "private-endpoints",
  "microsoft.network/privatednszones": "dns-zones", "microsoft.network/privatednszones/virtualnetworklinks": "dns-zones",
  "microsoft.keyvault/vaults": "key-vaults", "microsoft.eventgrid/systemtopics": "system-topic",
  "microsoft.web/sites": "app-services", "microsoft.web/serverfarms": "app-service-plans",
  "microsoft.documentdb/databaseaccounts": "cosmos-db", "microsoft.servicebus/namespaces": "service-bus",
  "microsoft.sql/servers": "sql-server", "microsoft.managedidentity/userassignedidentities": "managed-identities",
  "microsoft.containerregistry/registries": "container-registries", "microsoft.operationalinsights/workspaces": "log-analytics-workspaces",
  "microsoft.insights/components": "application-insights", "microsoft.app/managedenvironments": "container-apps-environments",
  "microsoft.app/containerapps": "container-apps",
};
const resourceTypes = {};
const resourceKinds = {};

function icon(type, kind) {
  const t = (type || "").toLowerCase();
  const official = t === "microsoft.web/sites" && /functionapp/i.test(kind || "") ? "function-apps" : AZURE_ICONS[t];
  if (official) {
    const span = el("span", { class: "ico az" });
    span.append(el("img", { src: `/static/azure-icons/${official}.svg`, alt: "", width: "24", height: "24" }));
    return span;
  }
  const name = TYPE_ICONS[t] || "cube";
  const span = el("span", { class: "ico" });
  span.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
  return span;
}

const resCell = (name) => el("span", { class: "res" }, icon(resourceTypes[name], resourceKinds[name]), el("span", { class: "id" }, name));

function show(stage) {
  STAGES.forEach((s) => {
    $("stage-" + s).hidden = s !== stage;
    const b = document.querySelector(`[data-stage="${s}"]`);
    b.classList.toggle("on", s === stage);
    b.classList.toggle("done", !!done[s]);
    if (s === stage) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    b.setAttribute("aria-label", `Step ${STAGES.indexOf(s) + 1}: ${s}${done[s] ? ", done" : ""}`);
  });
  const i = STAGES.indexOf(stage);
  const next = $("next");
  next.hidden = i === STAGES.length - 1 || !done[stage];
  next.textContent = "Continue to " + STAGES[i + 1];
  next.dataset.to = STAGES[i + 1] || "";
  $("export").hidden = !(stage === "plan" || stage === "migrate");
  if (stage === "migrate" && !$("migrate-out").childElementCount) prepareMigrate();
}

function setLocked(stage, locked) {
  document.querySelector(`[data-stage="${stage}"]`).disabled = locked;
}

// Everything after `stage` is stale once `stage` is re-run.
function invalidateAfter(stage) {
  STAGES.slice(STAGES.indexOf(stage) + 1).forEach((s) => {
    done[s] = false;
    if (s === "migrate") migrateRows = [];
    $(s + "-out").replaceChildren();
    setLocked(s, true);
  });
}

function setError(msg, retry) {
  $("error").hidden = !msg;
  $("error-text").textContent = msg || "";
  lastAction = retry || null;
}

// One inline confirmation at a time: a panel with explicit Confirm and Cancel, no timers.
// `mount(panel)` puts the panel on the page and returns the node to remove afterwards.
let closeConfirm = null;
function askInline(mount, { message, details = [], confirmLabel, danger = false, returnFocus = null }) {
  if (closeConfirm) closeConfirm(false);
  return new Promise((resolve) => {
    const yes = el("button", { type: "button", class: "btn" + (danger ? " danger" : "") }, confirmLabel);
    const no = el("button", { type: "button", class: "btn secondary" }, "Cancel");
    const panel = el("div", { class: "confirm-panel" + (danger ? " danger" : ""), role: "group", "aria-label": message },
      el("p", { class: "confirm-msg" }, message),
      ...(details.length ? [el("ul", { class: "confirm-list" }, ...details.map((d) => el("li", {}, d)))] : []),
      el("div", { class: "confirm-actions" }, no, yes));
    const node = mount(panel);
    const onKey = (e) => { if (e.key === "Escape") finish(false); };
    function finish(ok) {
      document.removeEventListener("keydown", onKey);
      node.remove();
      closeConfirm = null;
      if (returnFocus) returnFocus.focus();
      resolve(ok);
    }
    closeConfirm = finish;
    yes.addEventListener("click", () => finish(true));
    no.addEventListener("click", () => finish(false));
    document.addEventListener("keydown", onKey);
    no.focus();  // the safe choice gets focus
  });
}

// "a", "a and b", "a, b and c"
const listOf = (items) => (items.length < 2 ? items.join("") : items.slice(0, -1).join(", ") + " and " + items[items.length - 1]);

const STAGE_RESULTS = { assess: "the assessment", plan: "the plans", migrate: "the migration values" };

// Re-running a stage clears everything after it. Ask first when there is something to lose.
async function confirmWipe(stage, anchor, verb, trigger) {
  // Migration values count only once the user has typed or run something there.
  const later = STAGES.slice(STAGES.indexOf(stage) + 1).filter((s) => done[s] || (s === "migrate" && migrateRows.some((r) => r.ran || r.dirty)));
  if (!later.length) return true;
  return askInline((p) => { anchor.after(p); return p; }, {
    message: `${verb} again clears ${listOf(later.map((s) => STAGE_RESULTS[s]))}.`,
    confirmLabel: `${verb} again`, returnFocus: trigger });
}

async function call(path, form, outEl, action, method = "POST") {
  setError("");
  outEl.replaceChildren(el("div", { class: "skeleton" }), el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
  let res, data;
  try {
    res = await fetch(path, { method, body: form ? (form instanceof URLSearchParams ? form : new URLSearchParams(form)) : undefined });
    data = await res.json();
  } catch (e) {
    outEl.replaceChildren();
    setError("Request failed. Check the server and retry.", action);
    return null;
  }
  if (!res.ok) {
    outEl.replaceChildren();
    setError(data.error || "Request failed", action);
    return null;
  }
  return data;
}

function table(headers, rows) {
  const t = el("table");
  t.append(el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", {}, h)))));
  t.append(el("tbody", {}, ...rows));
  return el("div", { class: "scroll" }, t);
}

const TYPE_NAMES = {
  "microsoft.network/virtualnetworks": "Virtual network",
  "microsoft.network/networksecuritygroups": "Network security group (firewall)",
  "microsoft.network/publicipaddresses": "Public IP address",
  "microsoft.network/networkinterfaces": "Network interface (NIC)",
  "microsoft.compute/virtualmachines": "Virtual machine",
  "microsoft.compute/disks": "Managed disk",
  "microsoft.storage/storageaccounts": "Storage account (blobs, files)",
  "microsoft.keyvault/vaults": "Key Vault (secrets and keys)",
  "microsoft.eventgrid/systemtopics": "Event Grid system topic (event routing)",
  "microsoft.web/sites": "App Service / Function App",
  "microsoft.documentdb/databaseaccounts": "Cosmos DB account",
  "microsoft.servicebus/namespaces": "Service Bus namespace (messaging)",
  "microsoft.sql/servers": "Azure SQL server",
};

// Unknown types fall back to the readable last segment, e.g. "fooBars" -> "Foo bars".
function typeName(type) {
  const known = TYPE_NAMES[type.toLowerCase()];
  if (known) return known;
  const last = type.split("/").pop().replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
  return last.charAt(0).toUpperCase() + last.slice(1);
}

const LABELS = { direct: "Direct", rebuild: "Rebuild", included: "Included" };
const pill = (route) => el("span", { class: "pill " + route }, LABELS[route] || route);

function diffBlock(text) {
  const pre = el("pre");
  text.split("\n").forEach((line) => {
    const cls = line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    pre.append(el("span", cls ? { class: cls } : {}, line + "\n"));
  });
  return pre;
}

// Turn nested configuration into [dotted.key, text] pairs, skipping empty values.
function flatten(value, prefix = "", out = [], depth = 0) {
  if (value === null || value === undefined || value === "") return out;
  if (Array.isArray(value)) {
    if (!value.length) return out;
    if (value.every((v) => v === null || typeof v !== "object")) { out.push([prefix, value.join(", ")]); return out; }
    value.forEach((v, i) => flatten(v, `${prefix}[${i}]`, out, depth + 1));
  } else if (typeof value === "object") {
    if (depth > 6) { out.push([prefix, "(nested)"]); return out; }
    Object.entries(value).forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out, depth + 1));
  } else {
    out.push([prefix, String(value)]);
  }
  return out;
}

const MAX_CONFIG_ROWS = 80;

function configPanel(r) {
  const rows = flatten(r.properties || {});
  const box = el("div", { class: "config" });
  if (!rows.length) { box.append(el("p", { class: "empty" }, "No configured values available for this resource.")); return box; }
  const dl = el("dl", { class: "kv" });
  rows.slice(0, MAX_CONFIG_ROWS).forEach(([k, v]) => dl.append(el("dt", { class: "code" }, k), el("dd", {}, v)));
  box.append(dl);
  if (rows.length > MAX_CONFIG_ROWS) box.append(el("p", { class: "note" }, `${rows.length - MAX_CONFIG_ROWS} more values not shown.`));
  return box;
}

// One short line of the most telling configured value, shown under the type.
function headline(r) {
  const p = r.properties || {};
  const inner = p.properties || {};
  const t = r.type.toLowerCase();
  if (t === "microsoft.compute/virtualmachines" && inner.hardwareProfile && inner.hardwareProfile.vmSize) return "Size: " + inner.hardwareProfile.vmSize;
  if (t === "microsoft.compute/disks") return [inner.diskSizeGB && inner.diskSizeGB + " GB", p.sku && p.sku.name].filter(Boolean).join(", ");
  if (t === "microsoft.network/virtualnetworks" && inner.addressSpace) return "Address space: " + (inner.addressSpace.addressPrefixes || []).join(", ");
  if (p.sku && p.sku.name) return "SKU: " + p.sku.name + (p.sku.tier ? " (" + p.sku.tier + ")" : "");
  return "";
}

function renderDiscover(resources) {
  const body = [];
  resources.forEach((r, i) => {
    resourceTypes[r.name] = r.type;
    resourceKinds[r.name] = (r.properties || {}).kind || "";
    const panelId = "config-" + i;
    const toggle = el("button", { type: "button", class: "expander", "aria-expanded": "false", "aria-controls": panelId, "aria-label": `Show configured values of ${r.name}` }, el("span", { class: "chev", "aria-hidden": "true" }));
    const detail = el("tr", { class: "detail", id: panelId, hidden: "" }, el("td", { colspan: "3" }, configPanel(r)));
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      detail.hidden = !open;
    });
    body.push(el("tr", { class: "item" }, el("td", {}, el("span", { class: "res" }, toggle, icon(r.type, resourceKinds[r.name]), el("span", { class: "id" }, r.name))),
      el("td", { title: r.type }, typeName(r.type), ...(headline(r) ? [el("div", { class: "headline" }, headline(r))] : [])), el("td", {}, r.location)), detail);
  });
  $("discover-out").replaceChildren(el("p", { class: "count" }, `${resources.length} resources found. Expand a row to see its configured values.`),
    table(["Resource", "Type", "Location"], body));
  done.discover = true;
  setLocked("assess", false);
}

function renderAssess(assessments) {
  const stat = (route) => {
    const n = assessments.filter((a) => a.route === route).length;
    return el("span", { class: "stat " + route }, el("b", {}, String(n)), LABELS[route]);
  };
  $("assess-out").replaceChildren(
    el("div", { class: "summary-bar" }, stat("direct"), stat("rebuild"), stat("included")),
    el("p", { class: "legend" }, el("b", {}, "Direct"), " migrates as it is. ", el("b", {}, "Rebuild"), " has no Leaseweb equivalent and needs a plan. ",
      el("b", {}, "Included"), " comes with the Leaseweb instance (network interface, disk, public IP), so there is nothing to migrate separately."),
    table(["Resource", "Leaseweb target", "Route", "Why"], assessments.map((a) =>
      el("tr", {}, el("td", {}, resCell(a.resource_name)), el("td", {}, a.target), el("td", {}, pill(a.route)), el("td", { class: "sub" }, a.rationale)))));
  done.assess = true;
  setLocked("plan", false);
}

const failedPlan = (p) => !p.proposal && p.warnings.length > 0 && p.warnings[0].startsWith("Plan failed");

function renderPlan(plans, message) {
  const out = $("plan-out");
  if (!plans.length) {
    out.replaceChildren(el("p", { class: "empty" }, message));
  } else {
    const toggleAll = el("button", { type: "button", class: "btn secondary toggle-all" }, "Expand all");
    const syncToggle = () => {
      const cards = [...out.querySelectorAll("details.plan")];
      toggleAll.textContent = cards.length && cards.every((d) => d.open) ? "Collapse all" : "Expand all";
    };
    toggleAll.addEventListener("click", () => {
      const open = toggleAll.textContent === "Expand all";
      out.querySelectorAll("details.plan").forEach((d) => { d.open = open; });
      syncToggle();
    });
    out.addEventListener("toggle", syncToggle, true);  // a card opened or closed by hand
    out.replaceChildren(el("div", { class: "plan-tools" }, el("span", { class: "note" }, `${plans.length} plan${plans.length > 1 ? "s" : ""}`), toggleAll), ...plans.map((p) => {
      const card = el("details", { class: "plan" },
        el("summary", { class: "plan-head" }, icon(resourceTypes[p.resource_name], resourceKinds[p.resource_name]), el("h3", { class: "id" }, p.resource_name), failedPlan(p) ? el("span", { class: "pill bad" }, "Failed") : el("span", { class: "pill rebuild" }, "Rebuild"), el("span", { class: "chev", "aria-hidden": "true" })));
      const box = el("div", { class: "plan-body" }, failedPlan(p) ? el("p", { class: "note" }, "This plan could not be generated. Click Generate plan to try again.") : el("p", { class: "summary" }, p.proposal));
      card.append(box);
      // Steps on the left; operations and code changes on the right (stacked on narrow screens).
      const main = el("div", { class: "plan-col" });
      const side = el("div", { class: "plan-col" });
      if (p.steps.length) {
        main.append(el("h4", {}, "Migration steps"), el("ol", { class: "steps-list" }, ...p.steps.map((t) => el("li", {}, t))));
      }
      if (p.lw_operations.length) {
        side.append(el("h4", {}, "Leaseweb operations"), el("div", { class: "chips" }, ...p.lw_operations.map((o) => el("span", { class: "chip" }, o))));
      }
      p.code_changes.forEach((c) => {
        side.append(el("details", { class: "change", open: "" }, el("summary", {}, el("span", { class: "id" }, c.file), " - " + c.summary), diffBlock(c.diff)));
      });
      const cols = [main, side].filter((c) => c.childElementCount);
      if (cols.length) box.append(el("div", { class: "plan-grid" + (cols.length === 1 ? " single" : "") }, ...cols));
      p.warnings.forEach((w) => box.append(el("p", { class: "warning" }, w)));
      return card;
    }));
  }
  done.plan = true;
  setLocked("migrate", false);
}

let live = false;
let migrateRows = [];
let chainIds = {};  // ids returned by earlier live calls, e.g. instanceId

function refreshMode() {
  $("mode-text").textContent = live ? "LIVE: calls are sent to Leaseweb" : "Dry run: nothing is sent to Leaseweb";
  $("mode").classList.toggle("live", live);
  $("liveband").hidden = !live;
  $("key-btn").textContent = live ? "Leaseweb key set" : "Leaseweb key";
  $("key-remove").hidden = !live;
  $("migrate-btn").textContent = live ? "Run LIVE migration" : "Run dry-run migration";
  $("migrate-btn").classList.toggle("danger", live);
  $("migrate-title").textContent = live ? "Live migration" : "Dry-run migration";
  $("migrate-desc").textContent = live
    ? "These Leaseweb API calls are sent in the order shown and can create billable resources. IDs from earlier responses are filled into later calls. A call that still needs values is skipped."
    : "The Leaseweb API calls that would migrate the direct resources, in the order they would run. Nothing is sent.";
  refreshRows();
}

// The server may have lost its key (it is kept in memory only). Follow what the server says.
function syncLive(serverLive) {
  if (serverLive === live) return;
  const wasLive = live;
  live = serverLive;
  refreshMode();
  if (wasLive) setError("The server no longer has the API key, so this ran as a dry run and nothing was sent. Set the key again to go live.", null);
}

const PLACEHOLDER = /<([^<>]+)>/;

// Allowed values (with descriptions) for fields that are a fixed list in the Leaseweb specs.
let optionsCache = null;
async function ensureOptions() {
  if (!optionsCache) {
    try { optionsCache = await (await fetch("/api/migrate/options")).json(); } catch (e) { optionsCache = { options: {}, source: "spec" }; }
  }
  return optionsCache;
}

// One labelled input per value a call takes. Required = still a <placeholder> or an unfilled {path param}
// (params an earlier response fills in, "chained", are not asked for).
function buildFields(c, idPrefix) {
  const chained = c.chained || {};
  const fields = [];
  (c.path.match(/\{[^}/]+\}/g) || []).forEach((token) => {
    const key = token.slice(1, -1);
    if (!(key in chained)) fields.push({ where: "path", key, token, required: true, kind: "string", initial: "", hint: "required" });
  });
  const listed = ((optionsCache && optionsCache.options) || {})[c.operation_id] || {};
  Object.entries(c.body || {}).forEach(([key, v]) => {
    if (typeof v === "string" && listed[key] && !PLACEHOLDER.test(v)) {
      const choices = listed[key].some((o) => o.value === v) ? listed[key] : [{ value: v, description: "" }, ...listed[key]];
      fields.push({ where: "body", key, required: false, kind: "select", initial: v, choices, hint: "" });
    } else if (typeof v === "boolean") {
      fields.push({ where: "body", key, required: false, kind: "bool", initial: String(v), choices: [{ value: "true", description: "" }, { value: "false", description: "" }], hint: "" });
    } else if (typeof v === "string") {
      const ph = PLACEHOLDER.test(v);
      fields.push({ where: "body", key, required: ph, kind: "string", initial: ph ? "" : v, hint: ph ? v.match(PLACEHOLDER)[1] : "", original: v });
    } else if (typeof v === "number") {
      fields.push({ where: "body", key, required: false, kind: "number", initial: String(v), hint: "" });
    } else {
      const text = JSON.stringify(v, null, 1);
      fields.push({ where: "body", key, required: PLACEHOLDER.test(text), kind: "json", initial: text, hint: "" });
    }
  });
  fields.forEach((f) => {
    const attrs = { id: `${idPrefix}-${f.key}`, spellcheck: "false", autocomplete: "off", class: "value-input" };
    if (f.kind === "select" || f.kind === "bool") {
      f.input = el("select", attrs, ...f.choices.map((o) => el("option", { value: o.value }, o.description ? `${o.value} - ${o.description}` : o.value)));
    } else {
      f.input = f.kind === "json" ? el("textarea", { ...attrs, rows: "4" }) : el("input", { ...attrs, placeholder: f.hint });
    }
    f.input.value = f.initial;
    if (f.required) f.input.setAttribute("aria-required", "true");
    f.help = f.where === "path" ? PARAM_HELP[f.key] || "" : "";
  });
  return fields;
}

// Where to find a value the tool cannot know.
const PARAM_HELP = {
  objectStorageId: "ID of an Object Storage product in your Leaseweb account. Order one in the Leaseweb portal if you have none.",
};

const missingField = (f) => (f.kind === "json" ? PLACEHOLDER.test(f.input.value) : f.required && !f.input.value.trim());

// Turn the filled-in form back into a call. Empty required values keep their placeholder, so the
// server skips that call instead of ever sending a guess.
function collectCall(row) {
  let path = row.pathTemplate;
  const body = { ...row.baseBody };
  for (const f of row.fields) {
    const v = f.input.value.trim();
    if (f.where === "path") { if (v) path = path.replace(f.token, encodeURIComponent(v)); continue; }
    if (f.kind === "select") {
      body[f.key] = f.input.value;
    } else if (f.kind === "bool") {
      body[f.key] = f.input.value === "true";
    } else if (f.kind === "json") {
      try { body[f.key] = JSON.parse(f.input.value); } catch (e) { throw new Error(`${f.key} is not valid JSON`); }
    } else if (f.kind === "number") {
      body[f.key] = v !== "" && !isNaN(Number(v)) ? Number(v) : v;
    } else if (v === "" && !f.required) {
      delete body[f.key];
    } else {
      body[f.key] = v === "" ? f.original : v;
    }
  }
  return { method: row.method, path, operation_id: row.operation_id, body, source: row.source };
}

// What a run-all would do with each row, in order. A row is sent only when its values are filled in
// and every id it needs either exists already or comes from a row that is itself being sent.
function runPlan() {
  const have = new Set(Object.keys(chainIds));
  const supplies = (row) => {
    const out = new Set();
    migrateRows.forEach((r) => Object.entries(r.chained).forEach(([param, op]) => { if (op === row.operation_id) out.add(param); }));
    return out;
  };
  return migrateRows.map((row) => {
    const gives = supplies(row);
    if (row.sent) { gives.forEach((p) => have.add(p)); return { row, action: "done" }; }
    const missing = row.fields.filter(missingField).length;
    const waiting = Object.entries(row.chained).filter(([param]) => !have.has(param)).map(([, op]) => op);
    if (missing || waiting.length) {
      gives.forEach((p) => have.delete(p));
      return { row, action: "skip", missing, waiting, why: missing ? `needs ${missing} value${missing > 1 ? "s" : ""}` : `waits for ${waiting.join(", ")}` };
    }
    gives.forEach((p) => have.add(p));
    return { row, action: "send" };
  });
}

function updateRowStatus(row, planned) {
  const missing = row.fields.filter(missingField).length;
  const noId = Object.keys(row.chained).filter((p) => !chainIds[p]);
  row.tr.classList.toggle("needs", missing > 0);
  // Single runs: in LIVE a call cannot run before the call that supplies its id has succeeded.
  row.runBtn.disabled = busy || missing > 0 || (live && noId.length > 0);  // also for rows that already ran, so they can be retried
  row.runBtn.title = missing > 0 ? "Fill in the required values first" : (live && noId.length ? `Run ${row.chained[noId[0]]} first` : "");
  if (row.ran) return;
  const notes = Object.entries(row.chained).map(([p, op]) => el("div", { class: "status-note code" }, chainIds[p] ? `${p} = ${chainIds[p]} (from ${op})` : `${p} comes from ${op}`));
  const waiting = planned && planned.action === "skip" && !missing;
  row.status.replaceChildren(
    missing ? el("span", { class: "pill needs" }, `Needs ${missing} value${missing > 1 ? "s" : ""}`)
      : waiting ? el("span", { class: "pill neutral" }, "Waiting") : el("span", { class: "pill ready" }, "Ready"),
    ...(waiting ? [el("div", { class: "status-note" }, `Needs ${planned.waiting.join(", ")} first`)] : []),
    ...notes);
}

// A row's status depends on the rows before it, so refresh them together.
function refreshRows() {
  const plan = runPlan();
  migrateRows.forEach((r, i) => {
    r.runBtn.classList.toggle("danger", live);
    r.runBtn.textContent = live ? "Run live" : "Run";
    updateRowStatus(r, plan[i]);
  });
  $("migrate-btn").disabled = busy;
}

const rowLabel = (row) => `${row.index + 1}. ${row.operation_id}${row.source ? " for " + row.source : ""}`;

function renderMigrate(calls) {
  const out = $("migrate-out");
  migrateRows = [];
  $("migrate-note").replaceChildren();
  if (!calls.length) {
    out.replaceChildren(el("p", { class: "empty" }, "No directly migratable resources."));
    done.migrate = true;
    return;
  }
  const rows = calls.map((c, i) => {
    const fields = buildFields(c, `v${i}`);
    const values = fields.length
      ? el("div", { class: "values" }, ...fields.flatMap((f) => {
          if (f.help) f.input.setAttribute("aria-describedby", f.input.id + "-help");
          return [
            el("label", { class: "vlabel", for: f.input.id }, f.where === "path" ? `{${f.key}}` : f.key, ...(f.required ? [el("span", { class: "req", "aria-hidden": "true" }, " *")] : [])),
            el("div", { class: "vfield" }, f.input, ...(f.help ? [el("div", { class: "vhint", id: f.input.id + "-help" }, f.help)] : []))];
        }))
      : el("p", { class: "note" }, "No values to set");
    const status = el("td", { class: "status", "aria-live": "polite" });
    const runBtn = el("button", { type: "button", class: "btn secondary row-run", "aria-label": `Run call ${i + 1}: ${c.operation_id}` }, "Run");
    const source = c.source
      ? el("div", { class: "call-source" }, icon(resourceTypes[c.source], resourceKinds[c.source]), el("span", {}, "for ", el("span", { class: "id" }, c.source)))
      : "";
    const tr = el("tr", {}, el("td", { class: "seq" }, String(i + 1)),
      el("td", {}, el("div", { class: "op code" }, c.operation_id), el("div", { class: "call code" }, `${c.method} ${c.path}`), source),
      el("td", {}, values), status, el("td", { class: "run-cell" }, runBtn));
    const row = { tr, status, runBtn, index: i, method: c.method, operation_id: c.operation_id, source: c.source || "", chained: c.chained || {},
      pathTemplate: c.path, baseBody: c.body || {}, fields, ran: false, sent: false };
    fields.forEach((f) => {
      ["input", "change"].forEach((ev) => f.input.addEventListener(ev, () => { row.ran = false; row.sent = false; row.dirty = true; refreshRows(); }));
      if (f.input.tagName === "INPUT") f.input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runRow(row); } });
    });
    runBtn.addEventListener("click", () => runRow(row));
    migrateRows.push(row);
    return tr;
  });
  out.replaceChildren(table(["Order", "Call", "Values", "Status", "Run"], rows));
  done.migrate = false;
  refreshRows();
}

function showResult(row, r) {
  row.ran = true;
  row.sent = !!r.sent && r.status < 300;
  let pillEl, note = "";
  if (r.error) { pillEl = el("span", { class: "pill bad" }, "Error"); note = r.error; }
  else if (r.skipped) { pillEl = el("span", { class: "pill neutral" }, "Skipped"); note = r.reason; }
  else if (r.dry_run) { pillEl = el("span", { class: "pill neutral" }, "Dry run"); note = "Not sent"; }
  else {
    pillEl = el("span", { class: "pill " + (r.status < 400 ? "direct" : "bad") }, `Sent ${r.status}`);
    note = typeof r.response === "string" ? r.response : JSON.stringify(r.response).slice(0, 240);
  }
  row.status.replaceChildren(pillEl, el("div", { class: "status-note code" }, note));
}

// Errors that belong to one row are shown in that row, not in the page banner.
function rowError(row, message) {
  row.ran = true;
  row.status.replaceChildren(el("span", { class: "pill bad" }, "Error"), el("div", { class: "status-note" }, message));
}

function setChain(chain) {
  chainIds = chain || {};
  refreshRows();
}

// A request is in flight: run buttons are locked so nothing can be sent twice.
let busy = false;
function setBusy(on) {
  busy = on;
  refreshRows();
}

const withIds = (path) => path.replace(/\{([^}/]+)\}/g, (m, p) => chainIds[p] || m);

// Run one call. A live call asks for an explicit Send first.
async function runRow(row) {
  if (busy || row.runBtn.disabled) return;
  let call;
  try { call = collectCall(row); } catch (e) { rowError(row, e.message + "."); return; }
  if (live) {
    const ok = await askInline((p) => { const tr = el("tr", { class: "confirm-row" }, el("td", { colspan: "5" }, p)); row.tr.after(tr); return tr; }, {
      message: `Send ${rowLabel(row)} to Leaseweb now?`,
      details: [el("span", { class: "code" }, `${call.method} ${withIds(call.path)}`), "This is a live call and can create a billable resource."],
      confirmLabel: "Send live", danger: true, returnFocus: row.runBtn });
    if (!ok) return;
  }
  setError("");
  $("migrate-note").replaceChildren();
  setBusy(true);
  let res, data;
  try {
    res = await fetch("/api/migrate/run-one", { method: "POST", body: new URLSearchParams({ call: JSON.stringify(call) }) });
    data = await res.json();
  } catch (e) {
    setBusy(false);
    rowError(row, "Request failed. Check the server and retry.");
    return;
  }
  if (!res.ok) { setBusy(false); rowError(row, data.error || "Request failed"); return; }
  showResult(row, data.result);
  busy = false;
  setChain(data.chain);
  syncLive(data.live);
}

async function prepareMigrate() {
  const data = await call("/api/migrate/calls", null, $("migrate-out"), prepareMigrate, "GET");
  if (!data) return;
  await ensureOptions();
  live = data.live;
  renderMigrate(data.calls);
  refreshMode();
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Run every call that has not been sent yet, in order. A live run first lists exactly what will be
// sent and what will be skipped, and waits for an explicit Send.
async function migrate() {
  if (busy || !migrateRows.length) return;
  const btn = $("migrate-btn");
  const note = $("migrate-note");
  const plan = runPlan();
  const todo = plan.filter((p) => p.action !== "done");
  const send = todo.filter((p) => p.action === "send");
  const skip = todo.filter((p) => p.action === "skip");
  const sentBefore = plan.length - todo.length;
  note.replaceChildren();
  if (!todo.length) { note.replaceChildren(el("p", { class: "note" }, "Every call has already been sent. Change a value to send a call again.")); return; }
  const calls = [];
  for (const p of todo) {
    try { calls.push(collectCall(p.row)); } catch (e) { rowError(p.row, e.message + "."); return; }
  }
  if (live) {
    if (!send.length) { note.replaceChildren(el("p", { class: "note" }, "Nothing can be sent yet. Fill in the required values first.")); return; }
    const ok = await askInline((p) => { note.replaceChildren(p); return p; }, {
      message: `Send ${plural(send.length, "call")} to Leaseweb now? They can create billable resources.`,
      details: [
        ...send.map((p) => el("span", {}, el("b", {}, "Send "), rowLabel(p.row))),
        ...skip.map((p) => el("span", { class: "skip" }, el("b", {}, "Skip "), `${rowLabel(p.row)} (${p.why})`)),
        ...(sentBefore ? [el("span", { class: "skip" }, `${plural(sentBefore, "call")} already sent and left alone`)] : []),
      ],
      confirmLabel: `Send ${plural(send.length, "call")}`, danger: true, returnFocus: btn });
    if (!ok) return;
  }
  setError("");
  setBusy(true);
  btn.textContent = live ? `Sending ${plural(send.length, "call")}...` : "Running dry run...";
  let res, data;
  try {
    res = await fetch("/api/migrate", { method: "POST", body: new URLSearchParams({ calls: JSON.stringify(calls) }) });
    data = await res.json();
  } catch (e) { setBusy(false); refreshMode(); setError("Request failed. Check the server and retry.", migrate); return; }
  if (!res.ok) { setBusy(false); refreshMode(); setError(data.error || "Request failed", migrate); return; }
  data.results.forEach((r, i) => showResult(todo[i].row, r));
  busy = false;
  setChain(data.chain);
  refreshMode();
  syncLive(data.live);
  const ok = data.results.filter((r) => r.sent && r.status < 300).length;
  const failed = data.results.filter((r) => r.error || (r.sent && r.status >= 300)).length;
  const skipped = data.results.filter((r) => r.skipped).length;
  note.replaceChildren(el("p", { class: "run-summary" + (failed ? " bad" : "") }, data.live
    ? `Live run finished: ${plural(ok, "call")} sent` + (failed ? `, ${failed} failed` : "") + (skipped ? `, ${skipped} skipped` : "") + ". See each row for the response."
    : `Dry run finished: ${plural(data.results.length, "call")} checked, nothing sent.`));
  done.migrate = true;
  show("migrate");
}

// ---- AI provider: which assistant writes the assessments and plans
const AI_HELP = {
  "claude-cli": "Runs the `claude` command on this machine with your Claude Code login. No key needed.",
  "anthropic-api": "Calls the Anthropic API directly. The key is kept in server memory only, never saved or shown again. Leave the model empty for the default (claude-opus-5-5).",
  "opencode": "Runs `opencode run` in an empty scratch folder, so it cannot touch your project. Model format: provider/model, for example anthropic/claude-sonnet-5-5. Leave it empty for opencode's own default.",
};
const AI_MODEL_HINT = { "anthropic-api": "claude-opus-5-5", "opencode": "provider/model (optional)" };
let aiState = null;

function aiLabel(s) { return (s.providers.find((p) => p.id === s.provider) || {}).label || s.provider; }

function renderAi(s) {
  aiState = s;
  const sel = $("ai-provider");
  sel.replaceChildren(...s.providers.map((p) => el("option", { value: p.id }, `${p.label} (${p.detail})`)));
  sel.value = s.provider;
  $("ai-model").value = s.model;
  $("ai-btn").textContent = "AI: " + aiLabel(s);
  syncAiForm(s.provider);
  $("ai-key-remove").hidden = !s.api_key_set;
  $("ai-key").placeholder = s.api_key_set ? "Key is set. Paste a new one to replace it." : "Paste your Anthropic API key";
}

// Show only the fields the chosen provider uses.
function syncAiForm(provider) {
  $("ai-provider").value = provider;
  $("ai-model-row").hidden = provider === "claude-cli";
  $("ai-key-row").hidden = provider !== "anthropic-api";
  $("ai-model").placeholder = AI_MODEL_HINT[provider] || "";
  $("ai-help").textContent = AI_HELP[provider] || "";
  $("ai-result").textContent = "";
  $("ai-result").className = "";
}

async function loadAi() {
  try { renderAi(await (await fetch("/api/ai")).json()); } catch (e) { /* the header keeps its default label */ }
}

async function saveAi(e) {
  if (e) e.preventDefault();
  const form = new URLSearchParams({ provider: $("ai-provider").value, model: $("ai-model").value });
  const key = $("ai-key").value;
  $("ai-key").value = "";  // clear immediately: the key is never kept in the page
  if (key.trim()) form.set("api_key", key);
  let res, data;
  try { res = await fetch("/api/ai", { method: "POST", body: form }); data = await res.json(); }
  catch (err) { setAiResult("Could not save. Check the server.", false); return false; }
  if (!res.ok) { setAiResult(data.error || "Could not save.", false); return false; }
  renderAi(data);
  setAiResult("Saved.", true);
  return true;
}

function setAiResult(text, ok) {
  const r = $("ai-result");
  r.textContent = text;
  r.className = ok ? "ok" : "bad";
}

async function testAi() {
  if (!(await saveAi())) return;
  setAiResult("Testing...", true);
  $("ai-test").disabled = true;
  try {
    const res = await fetch("/api/ai/test", { method: "POST" });
    const data = await res.json();
    setAiResult(res.ok ? `Works: ${aiLabel(aiState)} answered.` : data.error || "Test failed.", res.ok);
  } catch (err) { setAiResult("Request failed. Check the server.", false); }
  $("ai-test").disabled = false;
}

async function removeAiKey() {
  try { renderAi(await (await fetch("/api/ai/key", { method: "DELETE" })).json()); setAiResult("Key removed.", true); }
  catch (err) { setAiResult("Could not remove the key.", false); }
}

async function setKey(e) {
  e.preventDefault();
  const input = $("api-key");
  const value = input.value;
  input.value = "";  // clear immediately: the key is never kept in the page
  if (!value.trim()) return;
  try {
    const res = await fetch("/api/key", { method: "POST", body: new URLSearchParams({ api_key: value }) });
    if (!res.ok) throw new Error();
  } catch (err) { setError("Could not save the API key.", null); return; }
  setError("");
  live = true;
  optionsCache = null;  // regions come live from Leaseweb once a key is set
  $("keybar").hidden = true;
  $("key-btn").setAttribute("aria-expanded", "false");
  refreshMode();
}

async function removeKey() {
  try { await fetch("/api/key", { method: "DELETE" }); } catch (err) { setError("Could not remove the API key.", null); return; }
  live = false;
  optionsCache = null;
  refreshMode();
}

async function discover() {
  const trigger = $("discover-form").querySelector("button[type=submit]");
  if (!(await confirmWipe("discover", $("discover-form"), "Discover", trigger))) return;
  const data = await call("/api/discover", { resource_group: $("rg").value }, $("discover-out"), discover);
  if (!data) return;
  invalidateAfter("discover");
  renderDiscover(data.resources);
  show("discover");
}

async function assess() {
  if (done.assess && !(await confirmWipe("assess", $("assess-btn").parentElement, "Assess", $("assess-btn")))) return;
  const data = await call("/api/assess", null, $("assess-out"), assess);
  if (!data) return;
  invalidateAfter("assess");
  renderAssess(data.assessments);
  show("assess");
}

const MAX_FOLDERS = 5;

function folderInputs() { return [...document.querySelectorAll(".folder-input")]; }

function refreshFolders() {
  const n = folderInputs().length;
  $("add-folder").disabled = n >= MAX_FOLDERS;
  $("folder-count").textContent = `${n} of ${MAX_FOLDERS}`;
  document.querySelectorAll(".folder-remove").forEach((b) => { b.hidden = n === 1; });
}

function addFolder(value = "") {
  if (folderInputs().length >= MAX_FOLDERS) return;
  const i = folderInputs().length;
  const input = el("input", { class: "folder-input", id: "src-" + i, placeholder: "/path/to/app", autocomplete: "off", "aria-label": "Source folder " + (i + 1) });
  input.value = value;
  const remove = el("button", { type: "button", class: "btn secondary folder-remove", "aria-label": "Remove folder " + (i + 1) }, "Remove");
  const row = el("div", { class: "folder-row" }, input, remove);
  remove.addEventListener("click", () => { row.remove(); refreshFolders(); });
  $("folder-list").append(row);
  refreshFolders();
}

// Poll the server while plans are generated in parallel and show a progress bar.
function startPlanProgress(out) {
  const label = el("div", { class: "progress-label" }, "Starting...");
  const fill = el("div", { class: "progress-fill" });
  const bar = el("div", { class: "progress-track", role: "progressbar", "aria-label": "Plan generation progress", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" }, fill);
  const list = el("div", { class: "progress-items" });
  out.replaceChildren(el("div", { class: "progress" }, label, bar, list));
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try {
      const p = await (await fetch("/api/plan/progress")).json();
      if (stopped) return;
      if (p.total) {
        const pct = Math.round((p.done / p.total) * 100);
        fill.style.width = pct + "%";
        bar.setAttribute("aria-valuenow", String(pct));
        const working = p.items.filter((i) => i.status === "running").map((i) => i.name);
        label.textContent = `${p.done} of ${p.total} plans done` + (working.length ? ` - working on ${working.slice(0, 3).join(", ")}${working.length > 3 ? ", ..." : ""}` : "");
        list.replaceChildren(...p.items.map((i) => el("span", { class: "chip status-" + i.status }, i.name)));
      }
    } catch (e) { /* keep polling; the main request reports real errors */ }
    if (!stopped) setTimeout(tick, 700);
  };
  tick();
  return () => { stopped = true; };
}

async function plan() {
  const form = new URLSearchParams();
  folderInputs().map((i) => i.value.trim()).filter(Boolean).forEach((v) => form.append("source_dirs", v));
  const submit = $("plan-form").querySelector("button[type=submit]");
  if (!(await confirmWipe("plan", $("plan-form"), "Generate the plan", submit))) return;
  submit.disabled = true;
  const pending = call("/api/plan", form, $("plan-out"), plan);
  const stop = startPlanProgress($("plan-out"));
  const data = await pending;
  stop();
  submit.disabled = false;
  if (!data) return;
  invalidateAfter("plan");
  renderPlan(data.plans, data.message);
  show("plan");
}

// Restore the last session from the server so a page refresh loses nothing.
async function restore() {
  let s;
  try { s = await (await fetch("/api/state")).json(); } catch (e) { return; }
  live = !!s.api_key_set;
  chainIds = s.chain || {};
  refreshMode();
  if (s.resource_group) $("rg").value = s.resource_group;
  (s.source_dirs || []).slice(0, MAX_FOLDERS).forEach((d, i) => { if (i === 0) folderInputs()[0].value = d; else addFolder(d); });
  let furthest = null;
  if (s.resources.length) { renderDiscover(s.resources); furthest = "discover"; }
  if (s.assessments.length) { renderAssess(s.assessments); furthest = "assess"; }
  if (s.plans.length || s.calls.length) { renderPlan(s.plans, "Nothing to plan: every resource migrates directly."); furthest = "plan"; }
  if (s.calls.length) { await ensureOptions(); renderMigrate(s.calls); done.migrate = true; furthest = "migrate"; }
  if (furthest) {
    $("restored").hidden = false;
    show(furthest);
  }
}

// Start over asks first, with the same inline Confirm / Cancel as every other destructive action.
async function resetAll() {
  const ok = await askInline((p) => { $("top-confirm").replaceChildren(p); return p; }, {
    message: "Erase all saved results and start over?",
    details: ["Discovered resources, the assessment, plans and migration values are deleted. The API key stays."],
    confirmLabel: "Erase and start over", danger: true, returnFocus: $("reset-btn") });
  if (!ok) return;
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (!res.ok) throw new Error();
  } catch (e) {
    setError("Reset failed. Check the server and retry.", resetAll);
    return;
  }
  setError("");
  Object.keys(done).forEach((k) => { done[k] = false; });
  Object.keys(resourceTypes).forEach((k) => delete resourceTypes[k]);
  ["assess", "plan", "migrate"].forEach((s) => { setLocked(s, true); $(s + "-out").replaceChildren(); });
  $("discover-out").replaceChildren(el("p", { class: "empty" }, "No resources loaded yet. Enter a resource group and discover it."));
  $("rg").value = $("rg").defaultValue;
  $("folder-list").replaceChildren();
  addFolder();
  migrateRows = [];
  chainIds = {};
  $("migrate-note").replaceChildren();
  $("restored").hidden = true;
  show("discover");
}

document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
  const stage = b.dataset.stage;
  show(stage);
  if (stage === "assess" && !done.assess) assess();
}));
$("discover-form").addEventListener("submit", (e) => { e.preventDefault(); discover(); });
$("add-folder").addEventListener("click", () => addFolder());
$("plan-form").addEventListener("submit", (e) => { e.preventDefault(); plan(); });
$("reset-btn").addEventListener("click", resetAll);
$("assess-btn").addEventListener("click", assess);
$("migrate-btn").addEventListener("click", migrate);
$("ai-btn").addEventListener("click", () => {
  const bar = $("aibar");
  bar.hidden = !bar.hidden;
  $("ai-btn").setAttribute("aria-expanded", String(!bar.hidden));
  if (!bar.hidden) $("ai-provider").focus();
});
$("ai-provider").addEventListener("change", () => syncAiForm($("ai-provider").value));
$("ai-form").addEventListener("submit", saveAi);
$("ai-test").addEventListener("click", testAi);
$("ai-key-remove").addEventListener("click", removeAiKey);
$("key-btn").addEventListener("click", () => {
  const bar = $("keybar");
  bar.hidden = !bar.hidden;
  $("key-btn").setAttribute("aria-expanded", String(!bar.hidden));
  if (!bar.hidden) $("api-key").focus();
});
$("key-form").addEventListener("submit", setKey);
$("key-remove").addEventListener("click", removeKey);
$("live-off").addEventListener("click", removeKey);
$("retry").addEventListener("click", () => lastAction && lastAction());
$("restored-dismiss").addEventListener("click", () => { $("restored").hidden = true; });
$("next").addEventListener("click", () => {
  const to = $("next").dataset.to;
  if (to === "assess" && !done.assess) { show("assess"); assess(); } else show(to);
});
// Use static/leaseweb-logo.svg (or .png) when present; otherwise keep the built-in mark.
(function loadLogo() {
  const img = $("lsw-logo");
  const candidates = ["/static/leaseweb-logo.svg", "/static/leaseweb-logo.png"];
  const tryNext = () => {
    const src = candidates.shift();
    if (!src) return;
    img.onload = () => { img.hidden = false; $("brand-mark").setAttribute("hidden", ""); };
    img.onerror = tryNext;
    img.src = src;
  };
  tryNext();
})();
addFolder();
loadAi();
restore();
