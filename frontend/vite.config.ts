import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The marketplace build pipeline runs a plain `docker build` and does not pass
 * the compose `build.args`, so BASE_PATH cannot be assumed to arrive as a build
 * argument. Resolve it from every source that might carry it, in order:
 *
 *   1. process.env  — a real `--build-arg` / shell export
 *   2. frontend/.env — loadEnv with an empty prefix, because Vite does NOT put
 *                      .env files onto process.env (this is why an earlier
 *                      build shipped root-absolute /assets/... and blanked)
 *   3. "./"          — relative, so assets resolve under whatever path the app
 *                      is actually mounted at, whatever the slug turns out to
 *                      be. Safe here because the app has no deep client-side
 *                      routes; it only ever varies the query string.
 *
 * An empty string counts as "not set" — Docker's `ENV X=$X` on an empty ARG
 * defines the variable as "", which would otherwise win over .env.
 */
export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, process.cwd(), "");
  const basePath =
    (process.env.BASE_PATH || "").trim() || (fileEnv.BASE_PATH || "").trim() || "./";

  return {
    base: basePath,
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        // Local `npm run dev` only; in the container nginx does this.
        "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
  };
});
