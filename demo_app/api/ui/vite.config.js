import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, forward API calls to a locally running FastAPI (uvicorn app.main:app --port 8000).
const API = process.env.API_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/products": API, "/healthz": API } },
});
