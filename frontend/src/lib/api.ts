/**
 * Marketplace contract: the API base is injected at build time, never hardcoded.
 * A failed fetch falls back to the last good payload and flips the source dot to
 * `local` — the board degrades, it never blanks.
 */
// INSTRUCTIONS.md §6 injects `/p/{slug}` while §7's compose example uses
// `/p/{slug}/`, so the injected value may or may not carry a trailing slash.
// Concatenating the slashed form produces `/p/{slug}//api`, which the
// marketplace router does not resolve — it falls through to the SPA and
// returns index.html with a 200. Normalise instead of trusting the input.
const API_ROOT = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const API_BASE = `${API_ROOT}/api`;

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
export const apiDelete = <T,>(path: string) => write<T>("DELETE", path);

export function qs(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  return entries.length ? `?${entries.map(([k, v]) => `${k}=${encodeURIComponent(v!)}`).join("&")}` : "";
}
