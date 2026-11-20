import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, getKey, setKey } from "./api.js";
import Catalog from "./Catalog.jsx";
import ProductForm from "./ProductForm.jsx";
import Failures from "./Failures.jsx";

const POLL_MS = 3000;
const TIMEOUT_MS = 90000;

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#/, "");
}

// A queued write is "done" once GET /products/{id} reflects it.
async function isDone(p) {
  try {
    const d = await api.get(p.id);
    if (p.action === "delete") return false;
    if (p.action === "create") return true;
    const e = p.expect;
    return (
      d.name === e.name && d.category === e.category && Number(d.price) === Number(e.price) &&
      (d.stock || 0) === (Number(e.stock) || 0) && (d.description || "") === (e.description || "")
    );
  } catch (err) {
    return p.action === "delete" && err.status === 404;
  }
}

export default function App() {
  const route = useHash();
  const [products, setProducts] = useState(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState([]);
  const [pending, setPending] = useState([]);
  const [toast, setToast] = useState("");
  const [keyDlg, setKeyDlg] = useState(false);
  const [hasKey, setHasKey] = useState(!!getKey());
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  const notify = useCallback((m) => {
    setToast(m);
    setTimeout(() => setToast(""), 4000);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const list = await api.list(category);
      setProducts(list);
      setError("");
      setCategories((c) => [...new Set([...c, ...list.map((p) => p.category)])].sort());
    } catch (e) {
      setError(e.message);
    }
  }, [category]);

  useEffect(() => { refresh(); }, [refresh]);

  const addPending = useCallback(
    (p) => setPending((cur) => [...cur.filter((x) => x.id !== p.id), { ...p, at: Date.now() }]),
    []
  );
  const dismiss = (id) => setPending((cur) => cur.filter((x) => x.id !== id));

  const active = pending.some((p) => !p.timedOut);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(async () => {
      const cur = pendingRef.current.filter((p) => !p.timedOut);
      const results = await Promise.all(cur.map(async (p) => [p, await isDone(p)]));
      const done = new Set(results.filter(([, d]) => d).map(([p]) => `${p.id}:${p.at}`));
      setPending((all) =>
        all
          .filter((p) => !done.has(`${p.id}:${p.at}`))
          .map((p) => (!p.timedOut && Date.now() - p.at > TIMEOUT_MS ? { ...p, timedOut: true } : p))
      );
      refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [active, refresh]);

  const ctx = { addPending, notify, openKey: () => setKeyDlg(true), hasKey };
  const detail = route.match(/^\/p\/(.+)$/);
  const page = route.startsWith("/new") ? "new" : route.startsWith("/failures") ? "failures" : "catalog";

  return (
    <>
      <header className="top">
        <span className="logo">📦 Products</span>
        <nav>
          <a className={page === "catalog" ? "on" : ""} href="#/">Catalog</a>
          <a className={page === "new" ? "on" : ""} href="#/new">New product</a>
          <a className={page === "failures" ? "on" : ""} href="#/failures">Failure demo</a>
        </nav>
        <div className="key">
          <span className="dot" style={{ background: hasKey ? "var(--ok)" : "var(--err)" }} />
          {hasKey ? "API key set" : "No API key"}{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); setKeyDlg(true); }}>{hasKey ? "change" : "set"}</a>
        </div>
      </header>
      <main>
        {detail ? (
          <ProductForm key={detail[1]} id={decodeURIComponent(detail[1])} {...ctx} />
        ) : page === "new" ? (
          <ProductForm {...ctx} />
        ) : page === "failures" ? (
          <Failures {...ctx} />
        ) : (
          <Catalog {...{ products, error, category, setCategory, categories, pending, dismiss, refresh }} />
        )}
      </main>
      {toast && <div className="toast show">{toast}</div>}
      {keyDlg && (
        <KeyDialog
          onClose={() => setKeyDlg(false)}
          onSave={(v) => { setKey(v); setHasKey(!!v); setKeyDlg(false); }}
        />
      )}
    </>
  );
}

function KeyDialog({ onClose, onSave }) {
  const [v, setV] = useState(getKey());
  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", display: "grid", placeItems: "center", padding: 16 }}
      onClick={onClose}
    >
      <form
        className="card pad"
        style={{ width: 420, maxWidth: "100%" }}
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); onSave(v.trim()); }}
      >
        <h2 style={{ marginTop: 0 }}>API key</h2>
        <p className="sub">Required for create / update / delete. Kept in this browser tab only (sessionStorage).</p>
        <div className="field">
          <label>X-API-Key</label>
          <input type="password" autoFocus value={v} onChange={(e) => setV(e.target.value)} placeholder="paste key from Key Vault" />
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary">Save</button>
        </div>
      </form>
    </div>
  );
}
