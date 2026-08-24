/**
 * Marketplace contract: the API base is injected at build time, never hardcoded.
 * A failed fetch falls back to the last good payload and flips the source dot to
 * `local` — the board degrades, it never blanks.
 */
const API_BASE = (import.meta.env.VITE_API_URL || "") + "/api";

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

async function write<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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
