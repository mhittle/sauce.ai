import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy so the SPA can call the FastAPI backend at /api and /health.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
