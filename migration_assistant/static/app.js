// Names shown to the user; the ids in STAGES stay the same for state and the API.
const STAGE_LABELS = { discover: "Discover", assess: "Assess", plan: "Manual migration", migrate: "Automatic migration" };
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
const resourceByName = {};

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
    if (s === stage) {
      b.setAttribute("aria-current", "step");
      b.scrollIntoView({ inline: "center", block: "nearest" });  // the stepper scrolls sideways on a phone
    } else b.removeAttribute("aria-current");
    b.setAttribute("aria-label", `Step ${STAGES.indexOf(s) + 1}: ${STAGE_LABELS[s]}${done[s] ? ", done" : ""}`);
  });
  const i = STAGES.indexOf(stage);
  const next = $("next");
  next.hidden = i === STAGES.length - 1 || !done[stage];
  next.textContent = "Continue to " + (STAGE_LABELS[STAGES[i + 1]] || "").toLowerCase();
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

const STAGE_RESULTS = { assess: "the assessment", plan: "the manual migration plans", migrate: "the automatic migration values" };

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

// A table whose column headers sort it: ascending, descending, then back to the given order.
// entries: [{ rows: [tr, ...], values: [text per column] }]; extra rows (e.g. a detail row) move with their entry.
function sortableTable(columns, entries) {
  const tbody = el("tbody");
  let sort = { col: -1, dir: 1 };
  const ths = columns.map((name, col) => {
    const btn = el("button", { type: "button", class: "sort" }, name, el("span", { class: "arrow", "aria-hidden": "true" }));
    btn.addEventListener("click", () => {
      sort = sort.col !== col ? { col, dir: 1 } : sort.dir === 1 ? { col, dir: -1 } : { col: -1, dir: 1 };
      paint();
    });
    return el("th", { scope: "col" }, btn);
  });
  function paint() {
    const shown = sort.col < 0 ? entries
      : entries.slice().sort((a, b) => sort.dir * a.values[sort.col].localeCompare(b.values[sort.col], undefined, { numeric: true, sensitivity: "base" }));
    tbody.replaceChildren(...shown.flatMap((e) => e.rows));
    ths.forEach((th, col) => {
      th.setAttribute("aria-sort", sort.col === col ? (sort.dir === 1 ? "ascending" : "descending") : "none");
      th.querySelector(".arrow").textContent = sort.col === col ? (sort.dir === 1 ? "▲" : "▼") : "";
    });
  }
  paint();
  return el("div", { class: "scroll" }, el("table", {}, el("thead", {}, el("tr", {}, ...ths)), tbody));
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

// A changed file: name, summary, +/- counts and a button that opens the diff viewer.
function changeCard(c) {
  const st = DiffLib.diffStats(c.diff);
  const view = el("button", { type: "button", class: "btn secondary", "aria-label": `View the diff of ${c.file}` }, "View diff");
  view.addEventListener("click", () => openDiff(c, view));
  return el("div", { class: "change" },
    el("div", { class: "change-main" }, el("span", { class: "id change-file" }, c.file), el("span", { class: "change-sum" }, c.summary),
      el("span", { class: "change-stats" }, el("span", { class: "plus" }, "+" + st.added), " ", el("span", { class: "minus" }, "-" + st.removed))),
    view);
}

// ---- diff viewer: a modal with an inline and a side by side layout
const diffDialog = () => $("diff-dialog");
let diffCurrent = null;

function savedDiffView() {
  // Side by side unless the user picked inline before (a phone falls back to inline in setDiffView).
  try { return localStorage.getItem("diffView") === "inline" ? "inline" : "side"; } catch (e) { return "side"; }
}

const narrow = () => window.matchMedia("(max-width: 720px)").matches;

function diffCell(line, kind, cls) {
  return [el("td", { class: "ln " + (cls || "") }, line && line[kind] !== null && line[kind] !== undefined ? String(line[kind]) : ""),
    el("td", { class: "code-cell " + (cls || "") }, line ? line.text : "")];
}

function renderDiffBody(view) {
  const parsed = DiffLib.parseDiff(diffCurrent.diff);
  const box = $("diff-body");
  if (!parsed.hunks.length) { box.replaceChildren(el("p", { class: "empty" }, "This change has no diff to show.")); return; }
  const parts = [];
  if (parsed.meta.length) parts.push(el("div", { class: "diff-meta code" }, ...parsed.meta.map((m) => el("div", {}, m))));
  parsed.hunks.forEach((h) => {
    const rows = [];
    if (h.header) rows.push(el("tr", { class: "hunk" }, el("td", { colspan: view === "side" ? "4" : "3" }, h.header)));
    if (view === "side") {
      DiffLib.sideBySide(h).forEach((r) => rows.push(el("tr", {},
        ...diffCell(r.left, "oldNo", r.left ? (r.left.type === "del" ? "del" : "") : "empty"),
        ...diffCell(r.right, "newNo", r.right ? (r.right.type === "add" ? "add" : "") : "empty"))));
    } else {
      h.lines.forEach((l) => rows.push(el("tr", { class: l.type },
        el("td", { class: "ln" }, l.oldNo === null ? "" : String(l.oldNo)), el("td", { class: "ln" }, l.newNo === null ? "" : String(l.newNo)),
        el("td", { class: "code-cell" }, (l.type === "add" ? "+" : l.type === "del" ? "-" : " ") + l.text))));
    }
    // Explicit column widths: a fixed table layout would take them from the full-width "@@" row.
    const cols = view === "side" ? ["ln", "", "ln", ""] : ["ln", "ln", ""];
    parts.push(el("table", { class: "diff " + view }, el("colgroup", {}, ...cols.map((c) => el("col", c ? { class: "ln" } : {}))), el("tbody", {}, ...rows)));
  });
  box.replaceChildren(...parts);
}

function setDiffView(view, remember) {
  if (view === "side" && narrow()) view = "inline";  // two columns do not fit a phone
  $("diff-inline").setAttribute("aria-pressed", String(view === "inline"));
  $("diff-side").setAttribute("aria-pressed", String(view === "side"));
  $("diff-side").disabled = narrow();
  $("diff-side").title = narrow() ? "Needs a wider screen" : "";
  if (remember) { try { localStorage.setItem("diffView", view); } catch (e) { /* the choice just is not remembered */ } }
  renderDiffBody(view);
}

function openDiff(change, trigger) {
  diffCurrent = change;
  const st = DiffLib.diffStats(change.diff);
  $("diff-title").textContent = change.file;
  $("diff-summary").textContent = change.summary;
  $("diff-stats").replaceChildren(el("span", { class: "plus" }, "+" + st.added), " ", el("span", { class: "minus" }, "-" + st.removed));
  setDiffView(savedDiffView(), false);
  diffDialog().showModal();  // focus moves into the dialog and Esc closes it
  $("diff-body").scrollTop = 0;
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
  // Portal labels for known types; other types list every value with a readable label.
  const { rows, curated } = PortalLib.portalFields(r);
  if (!curated) flatten(r.properties || {}).filter(([k]) => !PortalLib.isCommonKey(k)).forEach(([k, v]) => rows.push([PortalLib.humanizeKey(k), PortalLib.fmt(v)]));
  const box = el("div", { class: "config" });
  if (!rows.length) { box.append(el("p", { class: "empty" }, "No configured values available for this resource.")); return box; }
  const dl = el("dl", { class: "kv" });
  rows.slice(0, MAX_CONFIG_ROWS).forEach(([k, v]) => dl.append(el("dt", {}, k), el("dd", {}, v)));
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
  const entries = PortalLib.resourceOrder(resources).map((r, i) => {
    resourceTypes[r.name] = r.type;
    resourceKinds[r.name] = (r.properties || {}).kind || "";
    resourceByName[r.name] = r;
    const panelId = "config-" + i;
    const toggle = el("button", { type: "button", class: "expander", "aria-expanded": "false", "aria-controls": panelId, "aria-label": `Show configured values of ${r.name}` }, el("span", { class: "chev", "aria-hidden": "true" }));
    const detail = el("tr", { class: "detail", id: panelId, hidden: "" }, el("td", { colspan: "3" }, configPanel(r)));
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      detail.hidden = !open;
    });
    const row = el("tr", { class: "item" }, el("td", {}, el("span", { class: "res" }, toggle, icon(r.type, resourceKinds[r.name]), el("span", { class: "id" }, r.name))),
      el("td", { title: r.type }, typeName(r.type), ...(headline(r) ? [el("div", { class: "headline" }, headline(r))] : [])), el("td", {}, PortalLib.locationName(r.location)));
    return { rows: [row, detail], values: [r.name, typeName(r.type), PortalLib.locationName(r.location)] };
  });
  $("discover-out").replaceChildren(el("p", { class: "count" }, `${resources.length} resources found. Expand a row to see its configured values. Click a column header to sort.`),
    sortableTable(["Resource", "Type", "Location"], entries));
  done.discover = true;
  setLocked("assess", false);
}

// Route filter on the Assess table: the chips toggle routes; nothing selected shows everything.
function needsCell(a) {
  if (a.route === "included") return el("td", { class: "sub" }, "With its owner");
  const deps = a.dependencies || [];
  const step = el("div", { class: "step-no" }, `Step ${(a.wave ?? 0) + 1}`);
  if (!deps.length) return el("td", {}, step, el("div", { class: "sub" }, "Nothing"));
  return el("td", {}, step, el("ul", { class: "deps" }, ...deps.map((d) =>
    el("li", { title: d.reason }, d.name, d.source === "ai" ? el("span", { class: "dep-ai", title: "Suggested by the AI: " + d.reason }, "AI") : ""))));
}

function renderAssess(assessments, message = "") {
  const picked = new Set();
  let query = "";
  const entries = assessments.map((a) => {
    const r = resourceByName[a.resource_name];
    const source = typeName(resourceTypes[a.resource_name] || "");
    const sub = r ? headline(r) : "";
    const deps = (a.dependencies || []).map((d) => d.name);
    const tr = el("tr", { "data-route": a.route }, el("td", {}, resCell(a.resource_name)),
      el("td", { title: resourceTypes[a.resource_name] || "" }, source, ...(sub ? [el("div", { class: "headline" }, sub)] : [])),
      el("td", {}, a.target), el("td", {}, pill(a.route)), needsCell(a), el("td", { class: "sub" }, a.rationale));
    tr.dataset.text = [a.resource_name, source, a.target, a.rationale, LABELS[a.route], ...deps].join(" ").toLowerCase();
    const needs = a.route === "included" ? "" : `Step ${(a.wave ?? 0) + 1} ${deps.join(" ")}`;
    return { rows: [tr], values: [a.resource_name, source, a.target, LABELS[a.route] || a.route, needs, a.rationale] };
  });
  const rows = entries.map((e) => e.rows[0]);
  const search = el("input", { type: "search", class: "filter-search", placeholder: "Search name, source, target or reason", "aria-label": "Search the assessment table", autocomplete: "off", spellcheck: "false" });
  const note = el("span", { class: "filter-note", role: "status", "aria-live": "polite" });
  const clear = el("button", { type: "button", class: "link", hidden: "" }, "Show all");
  const chips = [];
  const apply = () => {
    let shown = 0;
    rows.forEach((tr) => {
      const visible = (!picked.size || picked.has(tr.dataset.route)) && (!query || tr.dataset.text.includes(query));
      tr.hidden = !visible;
      if (visible) shown++;
    });
    chips.forEach(({ route, btn }) => btn.setAttribute("aria-pressed", String(picked.has(route))));
    const filtering = picked.size > 0 || query !== "";
    clear.hidden = !filtering;
    note.textContent = filtering ? (shown ? `Showing ${shown} of ${rows.length}` : "Nothing matches") : "";
  };
  const stat = (route) => {
    const n = assessments.filter((a) => a.route === route).length;
    const btn = el("button", { type: "button", class: "stat " + route, "aria-pressed": "false", "aria-label": `${LABELS[route]}: ${n}. Filter the table.` }, el("b", {}, String(n)), LABELS[route]);
    btn.disabled = n === 0;
    btn.addEventListener("click", () => { if (picked.has(route)) picked.delete(route); else picked.add(route); apply(); });
    chips.push({ route, btn });
    return btn;
  };
  search.addEventListener("input", () => { query = search.value.trim().toLowerCase(); apply(); });
  clear.addEventListener("click", () => { picked.clear(); query = ""; search.value = ""; apply(); });
  $("assess-out").replaceChildren(
    el("div", { class: "summary-bar" }, stat("direct"), stat("rebuild"), stat("included"), search, note, clear),
    el("p", { class: "legend" }, el("b", {}, "Direct"), " migrates as it is. ", el("b", {}, "Rebuild"), " has no Leaseweb equivalent and needs a plan. ",
      el("b", {}, "Included"), " is part of another resource (a VM's network interface, disk or public IP, or a private endpoint's network interface), so there is nothing to migrate separately. ",
      el("b", {}, "Needs first"), " lists the resources that must exist on Leaseweb before this one is created. Manual and Automatic migration follow this order."),
    ...(message ? [el("p", { class: "note", role: "status" }, message)] : []),
    sortableTable(["Resource", "Azure source", "Leaseweb target", "Route", "Needs first", "Why"], entries));
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
        el("summary", { class: "plan-head" }, icon(resourceTypes[p.resource_name], resourceKinds[p.resource_name]),
          el("div", { class: "plan-title" }, el("span", { class: "plan-type" }, typeName(resourceTypes[p.resource_name] || "")), el("h3", { class: "id" }, p.resource_name)), failedPlan(p) ? el("span", { class: "pill bad" }, "Failed") : el("span", { class: "pill rebuild" }, "Rebuild"), el("span", { class: "chev", "aria-hidden": "true" })));
      const detailsBtn = el("button", { type: "button", class: "btn secondary details-btn", "aria-label": `Open the details of ${p.resource_name}` }, "Details: steps and technical implementation");
      detailsBtn.addEventListener("click", () => openDetail(p.resource_name, detailsBtn));
      const box = el("div", { class: "plan-body" }, ...(failedPlan(p) ? [] : [el("div", { class: "details-row" }, detailsBtn)]), failedPlan(p) ? el("p", { class: "note" }, "This plan could not be generated. Click Generate plan to try again.") : el("p", { class: "summary" }, p.proposal));
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
      // Only files that really change get a diff. "No change needed" entries are grouped and have no diff button.
      const changed = p.code_changes.filter((c) => { const st = DiffLib.diffStats(c.diff); return st.added + st.removed > 0; });
      const unchanged = p.code_changes.filter((c) => !changed.includes(c));
      if (changed.length) side.append(el("h4", {}, "Code changes"));
      changed.forEach((c) => side.append(changeCard(c)));
      if (unchanged.length) {
        side.append(el("details", { class: "nochange" },
          el("summary", {}, `No change needed in ${unchanged.length} file${unchanged.length > 1 ? "s" : ""}`),
          el("ul", {}, ...unchanged.map((c) => el("li", {}, el("span", { class: "id" }, c.file), el("span", { class: "change-sum" }, c.summary))))));
      }
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
  $("migrate-title").textContent = live ? "Automatic migration (LIVE)" : "Automatic migration (dry run)";
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
let aiState = null;
const modelLists = {};  // provider -> {models, source, error}, filled on first use

// What the header shows: the provider and the model it will use right now.
function aiModelText(s) {
  if (s.effective_model) return s.effective_model;
  return s.provider === "opencode" ? "opencode's default model" : "default model";
}

function aiLabel(s) { return (s.providers.find((p) => p.id === s.provider) || {}).label || s.provider; }

function renderAi(s) {
  aiState = s;
  const sel = $("ai-provider");
  sel.replaceChildren(...s.providers.map((p) => el("option", { value: p.id }, `${p.label} (${p.detail})`)));
  sel.value = s.provider;
  $("ai-btn").textContent = `AI: ${aiLabel(s)} · ${aiModelText(s)}`;
  $("ai-btn").title = "Change the AI provider and model";
  syncAiForm(s.provider);
  $("ai-key-remove").hidden = !s.api_key_set;
  $("ai-key").placeholder = s.api_key_set ? "Key is set. Paste a new one to replace it." : "Paste your Anthropic API key";
}

// Show only the fields the chosen provider uses.
function syncAiForm(provider) {
  $("ai-provider").value = provider;
  $("ai-key-row").hidden = provider !== "anthropic-api";
  loadModels(provider);
  $("ai-help").textContent = AI_HELP[provider] || "";
  $("ai-result").textContent = "";
  $("ai-result").className = "";
}

// Fill the model dropdown for a provider. The saved model is selected; one that is not in the list is kept as an extra entry.
async function loadModels(provider) {
  const sel = $("ai-model");
  const wanted = aiState && aiState.provider === provider ? aiState.model : "";
  if (!modelLists[provider]) {
    sel.replaceChildren(el("option", { value: "" }, "Loading models..."));
    sel.disabled = true;
    try {
      const res = await fetch("/api/ai/models?provider=" + encodeURIComponent(provider));
      modelLists[provider] = res.ok ? await res.json() : { models: [{ id: "", label: "Default", group: "" }], source: "fallback", error: "Could not load the model list." };
    } catch (e) {
      modelLists[provider] = { models: [{ id: "", label: "Default", group: "" }], source: "fallback", error: "Could not load the model list." };
    }
  }
  if ($("ai-provider").value !== provider) return;  // the user moved on while it loaded
  const list = modelLists[provider];
  const models = list.models.some((m) => m.id === wanted) ? list.models : [...list.models, { id: wanted, label: wanted + " (saved)", group: "" }];
  const groups = {};
  const options = [];
  models.forEach((m) => {
    const opt = el("option", { value: m.id }, m.label);
    if (!m.group || m.group === "default") { options.push(opt); return; }
    if (!groups[m.group]) { groups[m.group] = el("optgroup", { label: m.group }); options.push(groups[m.group]); }
    groups[m.group].append(opt);
  });
  sel.replaceChildren(...options);
  sel.value = wanted;
  sel.disabled = false;
  $("ai-model-note").textContent = list.error ? list.error
    : list.source === "fallback" ? "Built-in list. Paste a key and save to load the live list from Anthropic." : "";
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
  delete modelLists["anthropic-api"];  // a new key can unlock the live model list
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

// ---- resource group picker: a dropdown of the groups the az login can see (a text box if az cannot list them)
const defaultGroup = () => $("rg").dataset.default;
const currentGroup = () => ($("rg-typed").hidden ? $("rg").value : $("rg-typed").value).trim();

function setGroup(name) {
  const sel = $("rg");
  if (![...sel.options].some((o) => o.value === name)) sel.append(el("option", { value: name }, name));
  sel.value = name;
  $("rg-typed").value = name;
}

let groupsLoaded = null;
async function loadGroups(keep) {
  const wanted = keep || currentGroup() || defaultGroup();
  const sel = $("rg");
  $("rg-refresh").disabled = true;
  try {
    const res = await fetch("/api/resource-groups");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Could not list resource groups (the server answered ${res.status}; restart it if it is an older version).`);
    sel.replaceChildren(...data.groups.map((g) => el("option", { value: g.name }, g.location ? `${g.name} (${g.location})` : g.name)));
    sel.hidden = false;
    $("rg-typed").hidden = true;
    setGroup(data.groups.some((g) => g.name === wanted) ? wanted : data.groups.some((g) => g.name === data.default) ? data.default : wanted);
  } catch (e) {
    // az could not list them: keep the default selectable and let the user type any name instead
    sel.hidden = true;
    $("rg-typed").hidden = false;
    $("rg-typed").value = wanted;
    setError(`${e.message} You can type the resource group name instead.`, null);
  }
  $("rg-refresh").disabled = false;
}

async function discover() {
  const trigger = $("discover-form").querySelector("button[type=submit]");
  if (!(await confirmWipe("discover", $("discover-form"), "Discover", trigger))) return;
  const group = currentGroup();
  if (!group) { setError("Enter or pick a resource group first.", null); return; }
  const data = await call("/api/discover", { resource_group: group }, $("discover-out"), discover);
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
  renderAssess(data.assessments, data.message);
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

// The server runs on this machine, so it opens the OS folder picker (Explorer, Finder, ...) and returns the path.
async function browseFolder(input, btn) {
  btn.disabled = true;
  try {
    const form = new FormData();
    form.append("initial", input.value.trim());
    const res = await fetch("/api/pick-folder", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not open the folder picker.");
    setError("");
    if (data.path) input.value = data.path;
  } catch (e) {
    setError(e.message);
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

function addFolder(value = "") {
  if (folderInputs().length >= MAX_FOLDERS) return;
  const i = folderInputs().length;
  const input = el("input", { class: "folder-input", id: "src-" + i, placeholder: "/path/to/app", autocomplete: "off", "aria-label": "Source folder " + (i + 1) });
  input.value = value;
  const remove = el("button", { type: "button", class: "btn secondary folder-remove", "aria-label": "Remove folder " + (i + 1) }, "Remove");
  const browse = el("button", { type: "button", class: "btn secondary", "aria-label": "Browse for folder " + (i + 1) }, "Browse…");
  browse.addEventListener("click", () => browseFolder(input, browse));
  const row = el("div", { class: "folder-row" }, input, browse, remove);
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

// ---- detail modal: each migration step beside the Leaseweb call that implements it
// Where a path parameter comes from, when it is not the response of an earlier call.
const PARAM_SOURCE = { objectStorageId: "objectStorageId is an Object Storage product that already exists in your Leaseweb account" };

function opCard(o) {
  const required = o.body_fields.filter((f) => f.required);
  const fieldRows = o.body_fields.map((f) => el("tr", {},
    el("td", { class: "code" }, f.name, ...(f.required ? [el("span", { class: "req", "aria-hidden": "true" }, " *")] : [])),
    el("td", { class: "sub" }, f.type + (f.enum.length ? `: ${f.enum.slice(0, 6).join(", ")}${f.enum.length > 6 ? ", ..." : ""}` : "")),
    el("td", { class: "sub" }, f.description)));
  return el("div", { class: "op-card" },
    el("div", { class: "op-line" }, el("span", { class: "method m-" + o.method.toLowerCase() }, o.method), el("code", { class: "op-path" }, o.path)),
    el("div", { class: "op-id" }, el("b", {}, o.id), o.summary ? " - " + o.summary : ""),
    ...(o.description ? [el("p", { class: "op-desc" }, o.description)] : []),
    ...(o.path_params.length ? [el("p", { class: "op-params" }, "Path: ", ...o.path_params.map((p) => el("code", {}, `{${p}}`)), ` (${o.path_params.map((p) => PARAM_SOURCE[p] || "from the response of the call that creates it").filter((v, i, a) => a.indexOf(v) === i).join("; ")})`)] : []),
    o.body_fields.length
      ? el("details", { class: "op-fields" }, el("summary", {}, `Request body: ${required.length} required, ${o.body_fields.length - required.length} optional`),
          el("div", { class: "scroll" }, el("table", {}, el("tbody", {}, ...fieldRows))))
      : el("p", { class: "op-params" }, "No request body."));
}

async function openDetail(name, trigger) {
  setError("");
  trigger.disabled = true;
  let res, d;
  try { res = await fetch("/api/plan/detail?resource=" + encodeURIComponent(name)); d = await res.json(); }
  catch (e) { trigger.disabled = false; setError("Request failed. Check the server and retry.", null); return; }
  trigger.disabled = false;
  if (!res.ok) { setError(d.error || `Could not load the details (the server answered ${res.status}; restart it if it is an older version).`, null); return; }
  const r = d.resource;
  $("detail-type").textContent = typeName(r.type);
  $("detail-title").textContent = r.name;
  $("detail-summary").textContent = d.proposal;
  const config = flatten(r.properties || {});
  const azure = el("details", { class: "azure-config" },
    el("summary", {}, `Azure today: ${typeName(r.type)} in ${r.location || "unknown location"} (${config.length} configured values)`),
    config.length ? el("dl", { class: "kv" }, ...config.slice(0, MAX_CONFIG_ROWS).flatMap(([k, v]) => [el("dt", { class: "code" }, k), el("dd", {}, v)])) : el("p", { class: "empty" }, "No configured values available."));
  const rows = d.steps.map((st, i) => el("tr", {},
    el("td", { class: "step-text" }, el("span", { class: "step-no" }, String(i + 1)), el("span", {}, st.text)),
    el("td", {}, ...(st.operations.length ? st.operations.map(opCard) : [el("p", { class: "op-none" }, "No Leaseweb API call. This is done on the instance or in your code.")]))));
  const parts = [azure];
  parts.push(rows.length
    ? el("div", { class: "scroll" }, el("table", { class: "steps-table", id: "detail-steps" }, el("thead", {}, el("tr", {}, el("th", {}, "Migration step"), el("th", {}, "Technical implementation on Leaseweb"))), el("tbody", {}, ...rows)))
    : el("p", { class: "empty" }, "This plan has no migration steps."));
  if (d.unassigned.length) parts.push(el("h3", { class: "detail-h" }, "Other Leaseweb calls in this plan"), el("div", { class: "op-grid" }, ...d.unassigned.map(opCard)));
  if (d.code_changes.length) {
    const changed = d.code_changes.filter((c) => { const st = DiffLib.diffStats(c.diff); return st.added + st.removed > 0; });
    if (changed.length) parts.push(el("h3", { class: "detail-h" }, "Code changes"), ...changed.map(changeCard));
  }
  $("detail-body").replaceChildren(...parts);
  $("detail-dialog").showModal();
  $("detail-body").scrollTop = 0;
}

// Restore the last session from the server so a page refresh loses nothing.
async function restore() {
  let s;
  try { s = await (await fetch("/api/state")).json(); } catch (e) { return; }
  live = !!s.api_key_set;
  chainIds = s.chain || {};
  refreshMode();
  await groupsLoaded;  // the dropdown must hold the options before a saved group can be selected
  if (s.resource_group) setGroup(s.resource_group);
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
  $("discover-out").replaceChildren(el("p", { class: "empty" }, "No resources loaded yet. Pick a resource group and discover it."));
  setGroup(defaultGroup());
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
$("diff-inline").addEventListener("click", () => setDiffView("inline", true));
$("diff-side").addEventListener("click", () => setDiffView("side", true));
$("diff-close").addEventListener("click", () => diffDialog().close());
$("detail-close").addEventListener("click", () => $("detail-dialog").close());
$("detail-dialog").addEventListener("click", (e) => { if (e.target === $("detail-dialog")) $("detail-dialog").close(); });
diffDialog().addEventListener("click", (e) => { if (e.target === diffDialog()) diffDialog().close(); });  // click on the backdrop
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
$("rg-refresh").addEventListener("click", () => loadGroups());
groupsLoaded = loadGroups();
restore();
