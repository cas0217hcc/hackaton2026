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
const resourceTypes = {};

function icon(type) {
  const name = TYPE_ICONS[(type || "").toLowerCase()] || "cube";
  const span = el("span", { class: "ico" });
  span.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
  return span;
}

const resCell = (name) => el("span", { class: "res" }, icon(resourceTypes[name]), el("span", { class: "id" }, name));

function show(stage) {
  STAGES.forEach((s) => {
    $("stage-" + s).hidden = s !== stage;
    const b = document.querySelector(`[data-stage="${s}"]`);
    b.classList.toggle("on", s === stage);
    b.classList.toggle("done", !!done[s]);
  });
  const i = STAGES.indexOf(stage);
  const next = $("next");
  next.hidden = i === STAGES.length - 1 || !done[stage];
  next.textContent = "Continue to " + STAGES[i + 1];
  next.dataset.to = STAGES[i + 1] || "";
  $("export").hidden = !(stage === "plan" || stage === "migrate");
}

function setLocked(stage, locked) {
  document.querySelector(`[data-stage="${stage}"]`).disabled = locked;
}

// Everything after `stage` is stale once `stage` is re-run.
function invalidateAfter(stage) {
  STAGES.slice(STAGES.indexOf(stage) + 1).forEach((s) => {
    done[s] = false;
    $(s + "-out").replaceChildren();
    setLocked(s, true);
  });
}

function setError(msg, retry) {
  $("error").hidden = !msg;
  $("error-text").textContent = msg || "";
  lastAction = retry || null;
}

async function call(path, form, outEl, action) {
  setError("");
  outEl.replaceChildren(el("div", { class: "skeleton" }), el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
  let res, data;
  try {
    res = await fetch(path, { method: "POST", body: form ? (form instanceof URLSearchParams ? form : new URLSearchParams(form)) : undefined });
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

function renderDiscover(resources) {
  $("discover-out").replaceChildren(el("p", { class: "count" }, `${resources.length} resources found.`), table(["Resource", "Type", "Location"], resources.map((r) => {
    resourceTypes[r.name] = r.type;
    return el("tr", {}, el("td", {}, resCell(r.name)), el("td", { title: r.type }, typeName(r.type)), el("td", {}, r.location));
  })));
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
    table(["Resource", "Leaseweb target", "Route", "Why"], assessments.map((a) =>
      el("tr", {}, el("td", {}, resCell(a.resource_name)), el("td", {}, a.target), el("td", {}, pill(a.route)), el("td", { class: "sub" }, a.rationale)))));
  done.assess = true;
  setLocked("plan", false);
}

function renderPlan(plans, message) {
  const out = $("plan-out");
  if (!plans.length) {
    out.replaceChildren(el("p", { class: "empty" }, message));
  } else {
    out.replaceChildren(...plans.map((p) => {
      const card = el("div", { class: "plan" },
        el("div", { class: "plan-head" }, icon(resourceTypes[p.resource_name]), el("h3", { class: "id" }, p.resource_name), el("span", { class: "pill rebuild" }, "Rebuild")));
      const box = el("div", { class: "plan-body" }, el("p", { class: "summary" }, p.proposal));
      card.append(box);
      if (p.steps.length) {
        box.append(el("h4", {}, "Migration steps"), el("ol", { class: "steps-list" }, ...p.steps.map((t) => el("li", {}, t))));
      }
      if (p.lw_operations.length) {
        box.append(el("h4", {}, "Leaseweb operations"), el("div", { class: "chips" }, ...p.lw_operations.map((o) => el("span", { class: "chip" }, o))));
      }
      p.code_changes.forEach((c) => {
        box.append(el("details", { class: "change", open: "" }, el("summary", {}, el("span", { class: "id" }, c.file), " - " + c.summary), diffBlock(c.diff)));
      });
      p.warnings.forEach((w) => box.append(el("p", { class: "warning" }, w)));
      return card;
    }));
  }
  done.plan = true;
  setLocked("migrate", false);
}

function renderMigrate(calls) {
  const out = $("migrate-out");
  if (!calls.length) {
    out.replaceChildren(el("p", { class: "empty" }, "No directly migratable resources."));
  } else {
    out.replaceChildren(
      table(["Method", "Path", "Operation", "Request body"], calls.map((c) => {
        const hasBody = Object.keys(c.body).length > 0;
        return el("tr", {}, el("td", { class: "code" }, c.method), el("td", { class: "code" }, c.path),
          el("td", { class: "code" }, c.operation_id),
          el("td", { class: hasBody ? "body" : "body none" }, hasBody ? JSON.stringify(c.body, null, 1) : "No request body"));
      })));
  }
  done.migrate = true;
}

async function discover() {
  const data = await call("/api/discover", { resource_group: $("rg").value }, $("discover-out"), discover);
  if (!data) return;
  invalidateAfter("discover");
  renderDiscover(data.resources);
  show("discover");
}

async function assess() {
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

async function plan() {
  const form = new URLSearchParams();
  folderInputs().map((i) => i.value.trim()).filter(Boolean).forEach((v) => form.append("source_dirs", v));
  const data = await call("/api/plan", form, $("plan-out"), plan);
  if (!data) return;
  invalidateAfter("plan");
  renderPlan(data.plans, data.message);
  show("plan");
}

async function migrate() {
  const data = await call("/api/migrate", null, $("migrate-out"), migrate);
  if (!data) return;
  renderMigrate(data.calls);
  show("migrate");
}

// Restore the last session from the server so a page refresh loses nothing.
async function restore() {
  let s;
  try { s = await (await fetch("/api/state")).json(); } catch (e) { return; }
  if (s.resource_group) $("rg").value = s.resource_group;
  (s.source_dirs || []).slice(0, MAX_FOLDERS).forEach((d, i) => { if (i === 0) folderInputs()[0].value = d; else addFolder(d); });
  let furthest = null;
  if (s.resources.length) { renderDiscover(s.resources); furthest = "discover"; }
  if (s.assessments.length) { renderAssess(s.assessments); furthest = "assess"; }
  if (s.plans.length || s.calls.length) { renderPlan(s.plans, "Nothing to plan: every resource migrates directly."); furthest = "plan"; }
  if (s.calls.length) { renderMigrate(s.calls); furthest = "migrate"; }
  if (furthest) {
    $("restored").hidden = false;
    show(furthest);
  }
}

document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
  const stage = b.dataset.stage;
  show(stage);
  if (stage === "assess" && !done.assess) assess();
}));
$("discover-form").addEventListener("submit", (e) => { e.preventDefault(); discover(); });
$("add-folder").addEventListener("click", () => addFolder());
$("plan-form").addEventListener("submit", (e) => { e.preventDefault(); plan(); });
$("assess-btn").addEventListener("click", assess);
$("migrate-btn").addEventListener("click", migrate);
$("retry").addEventListener("click", () => lastAction && lastAction());
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
restore();
