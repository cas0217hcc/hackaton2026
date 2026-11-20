import React, { useState } from "react";

const eur = (n) => `€ ${Number(n).toFixed(2)}`;
const errStyle = { background: "var(--errbg)", color: "var(--err)" };

export default function Catalog({ products, error, category, setCategory, categories, pending, dismiss, refresh }) {
  const [q, setQ] = useState("");
  const byId = Object.fromEntries(pending.map((p) => [p.id, p]));
  const queued = pending.filter((p) => !p.timedOut).length;
  const timedOut = pending.filter((p) => p.timedOut);
  const shown = (products || []).filter((p) => p.name.toLowerCase().includes(q.toLowerCase()));
  const ghosts = pending.filter(
    (p) => p.action === "create" && !p.timedOut && !(products || []).some((x) => x.id === p.id)
  );

  return (
    <>
      <h1>Catalog</h1>
      <p className="sub">Reads come straight from Cosmos DB. Writes go through a queue, so changes appear after a few seconds.</p>

      {error && <div className="banner" style={errStyle}>Could not load products: {error}</div>}
      {queued > 0 && (
        <div className="banner warn">
          ⏳ {queued} change{queued > 1 ? "s" : ""} queued, waiting for the worker…{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); refresh(); }}>Refresh</a>{" "}
          <span style={{ opacity: 0.7 }}>(auto-refresh every 3s)</span>
        </div>
      )}
      {timedOut.map((p) => (
        <div key={p.id} className="banner" style={errStyle}>
          "{p.name}" ({p.action}) was not applied within 90s — the command may be in the poison queue.{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); dismiss(p.id); }}>Dismiss</a>
        </div>
      ))}

      <div className="bar">
        <div style={{ width: 220 }}>
          <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <input style={{ maxWidth: 320 }} placeholder="Filter by name" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="grow" />
        <a className="btn primary" href="#/new">+ New product</a>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr><th>Product</th><th>Category</th><th className="num">Price</th><th className="num">Stock</th><th>Status</th><th /></tr>
          </thead>
          <tbody>
            {products === null && <tr><td colSpan="6">Loading…</td></tr>}
            {ghosts.map((g) => (
              <tr key={g.id}>
                <td><span className="thumb">⏳</span>{g.name}</td>
                <td>{g.expect.category}</td>
                <td className="num">{eur(g.expect.price)}</td>
                <td className="num">{g.expect.stock || 0}</td>
                <td><span className="pill warn">Queued…</span></td>
                <td />
              </tr>
            ))}
            {shown.map((p) => {
              const pe = byId[p.id];
              return (
                <tr key={p.id}>
                  <td><Thumb id={p.id} /><a href={`#/p/${p.id}`}>{p.name}</a></td>
                  <td>{p.category}</td>
                  <td className="num">{eur(p.price)}</td>
                  <td className="num">{p.stock ?? "—"}</td>
                  <td>
                    {pe && !pe.timedOut ? (
                      <span className="pill warn">{pe.action === "delete" ? "Deleting…" : "Applying…"}</span>
                    ) : p.ttl > 0 ? (
                      <span className="pill">TTL {p.ttl}s</span>
                    ) : (
                      <span className="pill ok">Live</span>
                    )}
                  </td>
                  <td><a className="btn sm" href={`#/p/${p.id}`}>Edit</a></td>
                </tr>
              );
            })}
            {products && !shown.length && !ghosts.length && (
              <tr><td colSpan="6" style={{ color: "var(--muted)" }}>No products.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="hint" style={{ marginTop: 12 }}>
        {shown.length} product{shown.length === 1 ? "" : "s"}{category && " · single-partition query"}
      </p>
    </>
  );
}

function Thumb({ id }) {
  const [ok, setOk] = useState(true);
  return ok ? (
    <img className="thumb" style={{ objectFit: "cover" }} src={`/products/${id}/image`} alt="" loading="lazy" onError={() => setOk(false)} />
  ) : (
    <span className="thumb">📦</span>
  );
}
