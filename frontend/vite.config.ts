import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Marketplace injects BASE_PATH (/p/{slug}/) at build time. Never hardcode a slug.
export default defineConfig({
  base: process.env.BASE_PATH || "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Local `npm run dev` only; in the container nginx does this.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
