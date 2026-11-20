const STAGES = ["discover", "assess", "plan", "migrate"];
const $ = (id) => document.getElementById(id);
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
  next.hidden = i === STAGES.length - 1 || !state[stage];
  next.textContent = "Continue to " + (STAGES[i + 1] || "");
  next.dataset.to = STAGES[i + 1] || "";
  $("export").hidden = !(stage === "plan" || stage === "migrate");
}

const state = {};

function unlock(stage) {
  const b = document.querySelector(`[data-stage="${stage}"]`);
  b.disabled = false;
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
  return t;
}

const pill = (route) => el("span", { class: "pill " + route }, route === "direct" ? "Direct" : "Rebuild");

async function discover() {
  const out = $("discover-out");
  const data = await call("/api/discover", { resource_group: $("rg").value }, out, discover);
  if (!data) return;
  state.discover = true;
  out.replaceChildren(table(["Resource", "Type", "Location"], data.resources.map((r) =>
    el("tr", {}, el("td", { class: "id" }, r.name), el("td", {}, r.type), el("td", {}, r.location)))));
  unlock("assess");
  show("discover");
}

async function assess() {
  const out = $("assess-out");
  const data = await call("/api/assess", null, out, assess);
  if (!data) return;
  state.assess = true;
  out.replaceChildren(table(["Resource", "Leaseweb target", "Route", "Why"], data.assessments.map((a) =>
    el("tr", {}, el("td", { class: "id" }, a.resource_name), el("td", {}, a.target), el("td", {}, pill(a.route)), el("td", {}, a.rationale)))));
  unlock("plan");
  show("assess");
}

function diffBlock(text) {
  const pre = el("pre");
  text.split("\n").forEach((line) => {
    const cls = line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    pre.append(el("span", cls ? { class: cls } : {}, line + "\n"));
  });
  return pre;
}

async function plan() {
  const out = $("plan-out");
  const data = await call("/api/plan", { source_dir: $("src").value }, out, plan);
  if (!data) return;
  state.plan = true;
  if (!data.plans.length) {
    out.replaceChildren(el("p", { class: "empty" }, data.message));
  } else {
    out.replaceChildren(...data.plans.map((p) => {
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
        const d = el("details", { class: "change", open: "" }, el("summary", {}, el("span", { class: "id" }, c.file), " - " + c.summary), diffBlock(c.diff));
        box.append(d);
      });
      p.warnings.forEach((w) => box.append(el("p", { class: "warning" }, w)));
      return box;
    }));
  }
  unlock("migrate");
  show("plan");
}

async function migrate() {
  const out = $("migrate-out");
  const data = await call("/api/migrate", null, out, migrate);
  if (!data) return;
  state.migrate = true;
  if (!data.calls.length) {
    out.replaceChildren(el("p", { class: "empty" }, "No directly migratable resources."));
  } else {
    out.replaceChildren(
      el("p", { class: "note" }, "Dry run: these calls were not sent."),
      table(["Method", "Path", "Operation", "Body"], data.calls.map((c) =>
        el("tr", {}, el("td", { class: "code" }, c.method), el("td", { class: "code" }, c.path),
          el("td", { class: "code" }, c.operation_id), el("td", { class: "code" }, JSON.stringify(c.body))))));
  }
  show("migrate");
}

document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
  const stage = b.dataset.stage;
  show(stage);
  if (stage === "assess" && !state.assess) assess();
}));
$("discover-form").addEventListener("submit", (e) => { e.preventDefault(); discover(); });
$("plan-form").addEventListener("submit", (e) => { e.preventDefault(); plan(); });
$("migrate-btn").addEventListener("click", migrate);
$("retry").addEventListener("click", () => lastAction && lastAction());
$("next").addEventListener("click", () => {
  const to = $("next").dataset.to;
  if (to === "assess") { show("assess"); assess(); } else show(to);
});
