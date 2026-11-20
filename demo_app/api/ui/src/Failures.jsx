import React, { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const SCENARIOS = {
  transient: {
    title: "Transient failure",
    blurb: "Worker fails, re-enqueues with a visibility timeout (10s, 20s…), then succeeds. Expect a 404 for ~30s, then the product appears.",
    product: { name: "Object Storage 1TB", category: "storage", price: 4.5 },
    btn: "primary",
  },
  poison: {
    title: "Poison command",
    blurb: "The runtime retries 3× then moves the message to the products-poison queue. The product never appears.",
    product: { name: "Broken product", category: "misc", price: 1 },
    btn: "danger",
  },
};
const GIVE_UP_S = 75;

export default function Failures({ notify, openKey, hasKey }) {
  return (
    <>
      <h1>Failure demo</h1>
      <p className="sub">
        Fire a write with <code>?simulate=</code> and watch for the result. The API has no status endpoint, so the UI
        polls <code>GET /products/{"{id}"}</code> (404 → 200).
      </p>
      <div className="grid2">
        {Object.entries(SCENARIOS).map(([k, s]) => (
          <Scenario key={k} kind={k} s={s} notify={notify} openKey={openKey} hasKey={hasKey} />
        ))}
      </div>
    </>
  );
}

function Scenario({ kind, s, notify, openKey, hasKey }) {
  const [run, setRun] = useState(null); // { id, state: queued | applied | gaveup }
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef();

  useEffect(() => () => clearInterval(timer.current), []);

  async function start() {
    if (!hasKey) return openKey();
    clearInterval(timer.current);
    try {
      const r = await api.create(s.product, kind);
      const startedAt = Date.now();
      setRun({ id: r.id, state: "queued" });
      setElapsed(0);
      timer.current = setInterval(async () => {
        const sec = Math.round((Date.now() - startedAt) / 1000);
        setElapsed(sec);
        try {
          await api.get(r.id);
          setRun({ id: r.id, state: "applied" });
          clearInterval(timer.current);
        } catch {
          if (sec >= GIVE_UP_S) {
            setRun({ id: r.id, state: "gaveup" });
            clearInterval(timer.current);
          }
        }
      }, 2000);
    } catch (e) {
      notify(e.status === 401 ? "Invalid or missing API key." : e.message);
    }
  }

  return (
    <div className="card pad">
      <h3 style={{ marginTop: 0 }}>{s.title}</h3>
      <p className="sub">{s.blurb}</p>
      <button className={`btn ${s.btn}`} onClick={start}>Send "{s.product.name}"</button>
      {run && (
        <ol style={{ margin: "16px 0 0", paddingLeft: 20, lineHeight: 2 }}>
          <li>✅ 202 Accepted, queued <span className="hint">(id {run.id.slice(0, 8)}…)</span></li>
          {run.state === "queued" && <li>⏳ Waiting… {elapsed}s <span className="hint">(GET → 404)</span></li>}
          {run.state === "applied" && (
            <li>✅ Visible in the catalog after ~{elapsed}s · <a href={`#/p/${run.id}`}>open</a></li>
          )}
          {run.state === "gaveup" && (
            <li><span className="pill err">Not applied after {GIVE_UP_S}s</span> likely moved to products-poison</li>
          )}
        </ol>
      )}
    </div>
  );
}
