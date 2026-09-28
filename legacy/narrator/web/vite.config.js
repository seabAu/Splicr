import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Builds to ../narrator/webui, which webapi.py serves as static files.
// One process serves both the API and the interface: no Node at runtime,
// nothing extra to install alongside the Python app.
export default defineConfig({
  plugins: [react()],
  // shadcn components are generated with "@/components/..." imports, so
  // the alias has to exist for them to resolve at all.
  resolve: {
    alias: { "@": path.resolve(new URL(".", import.meta.url).pathname, "src") },
  },
  build: { outDir: "../narrator/webui", emptyOutDir: true },
  server: {
    // Only used by `npm run dev`. The API stays on its own port and is
    // proxied, so the dev server and the shipped build hit identical URLs.
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
});
