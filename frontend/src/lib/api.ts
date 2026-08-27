/**
 * Marketplace contract: the API base is injected at build time, never hardcoded.
 * A failed fetch falls back to the last good payload and flips the source dot to
 * `local` — the board degrades, it never blanks.
 */
/**
 * Where the app is actually mounted, read from the URL in the address bar.
 * The marketplace serves each deployment at /p/{slug}/ and routes anything
 * outside that prefix to its own dashboard.
 */
function detectMountPrefix(): string {
  if (typeof window === "undefined") return "";
  const match = window.location.pathname.match(/^\/p\/[^/]+/);
  return match ? match[0] : "";
}

/**
 * Build-time injection is a hint, not the truth. The pipeline does not reliably
 * pass build args, and the slug baked at build time can differ from the one the
 * app is served under. The live path always wins; the injected value is the
 * fallback for a mount that is not under /p/.
 *
 * Trailing slashes are stripped: §6 injects `/p/{slug}` while §7's compose
 * example uses `/p/{slug}/`, and concatenating the slashed form onto "/api"
 * yields `/p/{slug}//api`, which the marketplace router does not resolve.
 */
const INJECTED_ROOT = (import.meta.env.VITE_API_URL || "").trim().replace(/\/+$/, "");
const API_ROOT = detectMountPrefix() || INJECTED_ROOT;
const API_BASE = `${API_ROOT}/api`;

/**
 * An absolute, same-origin URL for a full-page navigation — OAuth, where the
 * browser leaves the app and Google sends it back.
 *
 * This exists because `href="../api/google/authorize"` does NOT work: a
 * relative URL resolves against the current document, so under the marketplace
 * mount `/p/{slug}/` it becomes `/p/api/google/authorize` — a path that does
 * not exist. It only ever appeared correct because it happens to resolve to
 * `/api/...` at the root.
 *
 * `app_base` matters for the same reason: it is where the server sends the
 * browser after consent, and hardcoding "/" dumps a marketplace user out of
 * their app onto the host root.
 */
export function appUrl(path: string): string {
  const base = API_ROOT || "";
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/** The mount path the app is served under, with its trailing slash. */
export function appBase(): string {
  return `${API_ROOT || ""}/`;
}

/** A full-page OAuth navigation that comes back to THIS mount. */
export function oauthUrl(endpoint: "login" | "authorize"): string {
  return appUrl(`/api/google/${endpoint}?app_base=${encodeURIComponent(appBase())}`);
}

export function apiDiagnostics() {
  return {
    apiBase: API_BASE,
    detectedPrefix: detectMountPrefix(),
    injected: import.meta.env.VITE_API_URL ?? null,
    baseUrl: import.meta.env.BASE_URL,
  };
}

export type SourceState = "live" | "local";

type Listener = (state: SourceState) => void;
const listeners = new Set<Listener>();
let source: SourceState = "live";

export function getSource(): SourceState {
  return source;
}

export function onSourceChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function setSource(next: SourceState) {
  if (next === source) return;
  source = next;
  listeners.forEach((fn) => fn(next));
}

const CACHE_PREFIX = "signal-cs:cache:";

function readCache<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeCache(key: string, value: unknown) {
  try {
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(value));
  } catch {
    /* quota or private mode — the in-memory path still works */
  }
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** Reads fall back to cache. Writes never do — a silent no-op would lie. */
export async function apiGet<T>(path: string): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new ApiError(`GET ${path} failed`, res.status);
    assertJson(res, path);
    const data = (await res.json()) as T;
    writeCache(path, data);
    setSource("live");
    return data;
  } catch (err) {
    const cached = readCache<T>(path);
    setSource("local");
    if (cached) return cached;
    throw err instanceof ApiError ? err : new ApiError(`GET ${path} unreachable`, 0);
  }
}

/**
 * A misrouted /api request does not fail — it lands on the SPA fallback and
 * returns index.html with a 200. Catch that here so it reads as a routing
 * fault rather than a mystery JSON parse error.
 */
function assertJson(res: Response, path: string): void {
  const type = res.headers.get("content-type") || "";
  if (!type.includes("json")) {
    throw new ApiError(
      `${path} returned ${type || "no content-type"} instead of JSON — ` +
        `the /api proxy route is not reaching the backend (resolved base: ${API_BASE})`,
      res.status
    );
  }
}

async function write<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.ok && res.status !== 204) assertJson(res, path);
  if (!res.ok) {
    let detail = `${method} ${path} failed`;
    try {
      const payload = await res.json();
      if (payload?.detail) detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch { /* non-JSON error body */ }
    setSource("live");
    throw new ApiError(detail, res.status);
  }
  setSource("live");
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const apiPost = <T,>(path: string, body?: unknown) => write<T>("POST", path, body);
export const apiPatch = <T,>(path: string, body?: unknown) => write<T>("PATCH", path, body);
// DELETE carries a body here: destructive column actions require a target.
export const apiDelete = <T,>(path: string, body?: unknown) => write<T>("DELETE", path, body);

export function qs(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  return entries.length ? `?${entries.map(([k, v]) => `${k}=${encodeURIComponent(v!)}`).join("&")}` : "";
}
