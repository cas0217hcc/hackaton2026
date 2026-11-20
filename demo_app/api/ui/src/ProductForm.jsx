import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const EMPTY = { name: "", category: "", price: "", stock: "", description: "", ttlSeconds: "" };
const errStyle = { background: "var(--errbg)", color: "var(--err)" };
const authMsg = (x) => (x.status === 401 ? "Invalid or missing API key." : x.message);

// Create (no id) or edit (id) form.
export default function ProductForm({ id, addPending, notify, openKey, hasKey }) {
  const [f, setF] = useState(EMPTY);
  const [simulate, setSimulate] = useState("none");
  const [loading, setLoading] = useState(!!id);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [imgV, setImgV] = useState(0);
  const [imgOk, setImgOk] = useState(true);
  const fileRef = useRef();
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  useEffect(() => {
    if (!id) return;
    api.get(id)
      .then((d) =>
        setF({
          name: d.name,
          category: d.category,
          price: d.price,
          stock: d.stock ?? 0,
          description: d.description || "",
          ttlSeconds: d.ttl > 0 ? d.ttl : "",
        })
      )
      .catch((e) => setErr(e.status === 404 ? "Product not found (or not processed yet)." : e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const guard = () => {
    if (!hasKey) { openKey(); return false; }
    return true;
  };

  async function submit(e) {
    e.preventDefault();
    if (!guard()) return;
    setBusy(true);
    setErr("");
    try {
      const r = id ? await api.update(id, f, simulate) : await api.create(f, simulate);
      addPending({ id: r.id, action: id ? "update" : "create", name: f.name, expect: { ...f } });
      notify(id ? "Update accepted (202), applying…" : `Accepted (202). Product ${r.id.slice(0, 8)}… is being created…`);
      window.location.hash = "#/";
    } catch (x) {
      setErr(authMsg(x));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!guard() || !window.confirm(`Delete "${f.name}"?`)) return;
    try {
      await api.remove(id, simulate);
      addPending({ id, action: "delete", name: f.name });
      notify("Delete queued (202). The item is soft-deleted, then purged by TTL.");
      window.location.hash = "#/";
    } catch (x) {
      setErr(authMsg(x));
    }
  }

  async function upload(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file || !guard()) return;
    try {
      await api.uploadImage(id, file);
      setImgOk(true);
      setImgV((v) => v + 1);
      notify("Image uploaded.");
    } catch (x) {
      setErr(x.status === 413 ? "Image must be at most 5 MB." : authMsg(x));
    }
  }

  if (loading) return <p>Loading…</p>;

  const form = (
    <form className="card pad" onSubmit={submit}>
      {err && <div className="banner" style={errStyle}>{err}</div>}
      <div className="field">
        <label>Name *</label>
        <input required maxLength={200} value={f.name} onChange={set("name")} placeholder="VPS Small" />
      </div>
      <div className="grid2">
        <div className="field">
          <label>Category *</label>
          <input required pattern="[A-Za-z0-9_\-]+" maxLength={64} value={f.category} onChange={set("category")} placeholder="compute" />
          <div className="hint">
            Letters, digits, - and _. {id && "Changing it moves the product to another partition (one command)."}
          </div>
        </div>
        <div className="field">
          <label>Price (€) *</label>
          <input required type="number" min="0" step="0.01" value={f.price} onChange={set("price")} placeholder="9.99" />
        </div>
        <div className="field">
          <label>Stock</label>
          <input type="number" min="0" step="1" value={f.stock} onChange={set("stock")} placeholder="100" />
        </div>
        <div className="field">
          <label>TTL (seconds)</label>
          <input type="number" min="1" step="1" value={f.ttlSeconds} onChange={set("ttlSeconds")} placeholder="never expires" />
          <div className="hint">Optional. The product expires after this time.</div>
        </div>
      </div>
      <div className="field">
        <label>Description</label>
        <textarea rows="3" maxLength={2000} value={f.description} onChange={set("description")} />
      </div>
      <details className="dev field">
        <summary>Developer options</summary>
        <div style={{ marginTop: 8 }}>
          <label>Simulate failure</label>
          <select value={simulate} onChange={(e) => setSimulate(e.target.value)}>
            <option value="none">none</option>
            <option value="transient">transient (retry after 10s, 20s)</option>
            <option value="poison">poison (3 attempts → poison queue)</option>
          </select>
        </div>
      </details>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <a className="btn" href="#/">Cancel</a>
        <button className="btn primary" disabled={busy}>{id ? "Save changes" : "Create product"}</button>
      </div>
    </form>
  );

  if (!id) {
    return (
      <div style={{ maxWidth: 640, margin: "0 auto" }}>
        <h1>New product</h1>
        <p className="sub">The command is queued and applied by the worker.</p>
        {form}
      </div>
    );
  }

  return (
    <>
      <p className="sub"><a href="#/">← Catalog</a></p>
      <div className="bar">
        <div>
          <h1>{f.name || "Product"}</h1>
          <span className="sub" style={{ fontFamily: "monospace", fontSize: 13 }}>id {id}</span>
        </div>
        <span className="grow" />
        <button className="btn danger" onClick={remove}>Delete</button>
      </div>
      <div className="split">
        <div className="card pad">
          <div className="img-box" style={{ overflow: "hidden", padding: 0 }}>
            {imgOk ? (
              <img src={api.imageUrl(id, imgV)} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} onError={() => setImgOk(false)} />
            ) : (
              <>
                <div className="big">📦</div>
                No image yet
              </>
            )}
          </div>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={upload} />
          <div style={{ marginTop: 12 }}>
            <button className="btn" style={{ width: "100%" }} onClick={() => fileRef.current.click()}>Upload image…</button>
          </div>
          <p className="hint">Max 5 MB, stored in Blob storage.</p>
        </div>
        {form}
      </div>
    </>
  );
}
