// Thin client for the Products API (same origin). Writes need X-API-Key.
const KEY = "products-api-key";

export const getKey = () => {
  try { return sessionStorage.getItem(KEY) || ""; } catch { return ""; }
};
export const setKey = (v) => {
  try { sessionStorage.setItem(KEY, v); } catch { /* ignore */ }
};

async function request(path, { method = "GET", json, raw, contentType, simulate, write } = {}) {
  const headers = {};
  if (write) headers["X-API-Key"] = getKey();
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (raw) { headers["Content-Type"] = contentType; body = raw; }
  const url = path + (simulate && simulate !== "none" ? `?simulate=${simulate}` : "");
  const res = await fetch(url, { method, headers, body });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const d = (await res.json()).detail;
      msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => `${e.loc?.slice(1).join(".")}: ${e.msg}`).join("; ") : msg;
    } catch { /* not json */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const toBody = (p) => ({
  name: p.name,
  category: p.category,
  price: Number(p.price),
  description: p.description || "",
  stock: Number(p.stock) || 0,
  ...(p.ttlSeconds ? { ttlSeconds: Number(p.ttlSeconds) } : {}),
});

export const api = {
  list: (category) => request(`/products?limit=200${category ? `&category=${encodeURIComponent(category)}` : ""}`),
  get: (id) => request(`/products/${id}`),
  create: (p, simulate) => request("/products", { method: "POST", json: toBody(p), simulate, write: true }),
  update: (id, p, simulate) => request(`/products/${id}`, { method: "PUT", json: toBody(p), simulate, write: true }),
  remove: (id, simulate) => request(`/products/${id}`, { method: "DELETE", simulate, write: true }),
  uploadImage: (id, file) =>
    request(`/products/${id}/image`, { method: "PUT", raw: file, contentType: file.type, write: true }),
  imageUrl: (id, v = 0) => `/products/${id}/image?v=${v}`,
};
