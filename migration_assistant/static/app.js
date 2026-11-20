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

function show(stage) {
  STAGES.forEach((s) => {
    $("stage-" + s).hidden = s !== stage;
    document.querySelector(`[data-stage="${s}"]`).classList.toggle("on", s === stage);
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
    res = await fetch(path, { method: "POST", body: form ? new URLSearchParams(form) : undefined });
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
  $("discover-out").replaceChildren(table(["Resource", "Type", "Location"], resources.map((r) =>
    el("tr", {}, el("td", { class: "id" }, r.name), el("td", { title: r.type }, typeName(r.type)), el("td", {}, r.location)))));
  done.discover = true;
  setLocked("assess", false);
}

function renderAssess(assessments) {
  $("assess-out").replaceChildren(table(["Resource", "Leaseweb target", "Route", "Why"], assessments.map((a) =>
    el("tr", {}, el("td", { class: "id" }, a.resource_name), el("td", {}, a.target), el("td", {}, pill(a.route)), el("td", {}, a.rationale)))));
  done.assess = true;
  setLocked("plan", false);
}

function renderPlan(plans, message) {
  const out = $("plan-out");
  if (!plans.length) {
    out.replaceChildren(el("p", { class: "empty" }, message));
  } else {
    out.replaceChildren(...plans.map((p) => {
      const box = el("div", { class: "plan" },
        el("div", { class: "plan-head" }, el("h3", { class: "id" }, p.resource_name), el("span", { class: "pill rebuild" }, "Rebuild")),
        el("p", { class: "summary" }, p.proposal));
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
      return box;
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
      el("p", { class: "note" }, "Dry run: these calls were not sent."),
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

async function plan() {
  const data = await call("/api/plan", { source_dir: $("src").value }, $("plan-out"), plan);
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
  if (s.source_dir) $("src").value = s.source_dir;
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
$("plan-form").addEventListener("submit", (e) => { e.preventDefault(); plan(); });
$("assess-btn").addEventListener("click", assess);
$("migrate-btn").addEventListener("click", migrate);
$("retry").addEventListener("click", () => lastAction && lastAction());
$("next").addEventListener("click", () => {
  const to = $("next").dataset.to;
  if (to === "assess" && !done.assess) { show("assess"); assess(); } else show(to);
});
restore();
