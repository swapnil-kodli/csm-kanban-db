# Runbook: white screen on a path-based deployment

For an agent debugging a SPA that builds fine, deploys "successfully", and renders
a blank page when served under a path prefix like `https://host/p/{slug}/`.

Derived from a real deployment that failed this way three times in a row, each
time for a different reason. Every cause below was reproduced, not guessed.

---

## 0. The one rule

**A white screen is almost never a JavaScript error.** It is almost always the
browser refusing to execute a script that came back as HTML.

When a request for `/assets/index-abc.js` misses, a SPA server does not answer
`404`. It answers **`200 text/html`** with `index.html`, because that is what an
SPA fallback is *for*. The browser then refuses the module for its MIME type and
stops — often with nothing in the console at all.

So: **do not start by reading application code.** Start by asking what the
browser actually asked for and what actually came back.

---

## 1. Triage in one command

```bash
curl -s https://HOST/p/SLUG/ | grep -o '\(src\|href\)="[^"]*"'
```

| Output | Meaning | Go to |
|---|---|---|
| `src="/assets/…"` | Root-absolute. The host routes this outside your app. | [§2](#2-root-absolute-asset-paths) |
| `src="./assets/…"` | Correct and slug-independent. Problem is elsewhere. | [§3](#3-doubled-slash-in-the-api-base), [§4](#4-lost-trailing-slash) |
| `src="/p/OTHER-slug/assets/…"` | A slug was pinned at build time and it is the wrong one. | [§2](#2-root-absolute-asset-paths) |
| Page is not your HTML at all | Routing never reached your container. | Check the platform's route/slug registration. |

Then confirm what the asset request returns:

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' https://HOST/p/SLUG/assets/index-abc.js
```

`200 text/html` is the smoking gun. `200 application/javascript` means assets are
fine and the fault is elsewhere.

### Byte-count trick

If you can see the deploy log but not the page, the served size of `/` identifies
the build. Each asset URL losing a `/p/{slug}` prefix costs exactly
`len("/p/{slug}")` bytes, twice (JS + CSS). A 24-byte shortfall against a known-good
build is two references losing a 12-character prefix. That is enough to identify
the cause without ever loading the page.

---

## 2. Root-absolute asset paths

**Symptom:** `index.html` contains `src="/assets/…"`. The platform routes anything
outside `/p/{slug}/` to *its own* app, so your bundle never loads.

There are two independent reasons the base path fails to arrive. Check both.

### 2a. Vite does not put `.env` onto `process.env`

```ts
// BROKEN — process.env.BASE_PATH is undefined even when frontend/.env sets it
export default defineConfig({ base: process.env.BASE_PATH || "/" });
```

`.env` files are read by Vite's own loader, not injected into `process.env`. A
config reading `process.env` silently sees nothing and falls back.

### 2b. A `/` default in the Dockerfile beats every fallback

```dockerfile
ARG BASE_PATH=/        # ← truthy, so it wins over .env and over any fallback
ENV BASE_PATH=$BASE_PATH
```

Worse than no value at all. And note **many deploy pipelines run a plain
`docker build` and never pass compose `build.args`** — so the ARG *default* is
what actually ships. Verify with the pipeline's real command:

```bash
docker build -t app ./frontend            # NO --build-arg, like the pipeline
docker run --rm app cat /usr/share/nginx/html/index.html | grep -o 'src="[^"]*"'
```

### Fix — resolve from every source, treat empty as unset

```ts
// vite.config.ts
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, process.cwd(), ""); // "" prefix = load ALL vars
  const basePath =
    (process.env.BASE_PATH || "").trim() ||   // real --build-arg / shell export
    (fileEnv.BASE_PATH || "").trim() ||       // .env, which Vite alone can see
    "./";                                     // relative: works under any prefix
  return { base: basePath, /* … */ };
});
```

```dockerfile
ARG BASE_PATH=          # empty, never "/"
ARG VITE_API_URL=
ENV BASE_PATH=$BASE_PATH
ENV VITE_API_URL=$VITE_API_URL
```

`.trim()` and the empty defaults matter together: `ENV X=$X` on an empty `ARG`
defines the variable as `""`, and an empty string must not count as "set".

### Why relative (`./`) is the safest default

It resolves against whatever prefix actually serves the page, so it is correct
for *any* slug and survives a rename with no rebuild.

**Precondition:** the app must have no deep client-side routes — only `/` plus a
query string — because relative URLs resolve against the current path. If you
have routes like `/board/123`, a relative base breaks on refresh there. Either
pin the real slug at build time, or serve deep routes from a path that keeps the
same depth.

---

## 3. Doubled slash in the API base

**Symptom:** requests to `/p/{slug}//api/…`. Assets load; the page renders a shell
with no data, or an error state.

```ts
const API_BASE = (import.meta.env.VITE_API_URL || "") + "/api";
// VITE_API_URL="/p/slug/"  →  "/p/slug//api"
```

**This hides locally.** nginx has `merge_slashes on` by default and silently
repairs `//` before matching. A test suite in front of local nginx passes 100%
against a build that cannot work behind a router that does not collapse slashes.

Specs are frequently inconsistent about the trailing slash (one section injects
`/p/{slug}`, another example shows `/p/{slug}/`). Normalise; do not trust input.

### Fix

```ts
// Prefer where the app is ACTUALLY mounted; the injected value is only a hint.
function detectMountPrefix(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/^\/p\/[^/]+/);
  return m ? m[0] : "";
}
const INJECTED = (import.meta.env.VITE_API_URL || "").trim().replace(/\/+$/, "");
const API_BASE = `${detectMountPrefix() || INJECTED}/api`;
```

Reading the live URL also immunises you against a build-time slug that turns out
to be wrong.

### Reproduce it before believing you fixed it

```bash
# simulate a router that does NOT collapse slashes
sed 's/server {/server {\n    merge_slashes off;/' nginx.conf > /etc/nginx/conf.d/test.conf
```

---

## 4. Lost trailing slash

**Symptom:** the app works, then goes blank **after a client-side navigation and a
refresh**. Only reproducible if you reload *after* interacting.

React Router collapses `basename` + `"/"`. With `basename="/p/slug"`, a
`navigate({ search })` produces `/p/slug?x=1` — **no trailing slash**. On that URL
a relative `./assets/index.js` resolves one level up to `/p/assets/index.js`,
which the SPA fallback answers `200 text/html`.

This is the specific hazard that relative asset paths introduce. Close it at both
layers.

```nginx
# nginx: redirect the bare form, preserving the query string
location ~ ^/p/([^/]+)$ {
    return 301 /p/$1/$is_args$args;
}
```

```ts
// app: normalise the address bar so a copied link never relies on the redirect
useEffect(() => {
  const { pathname, search, hash } = window.location;
  if (/^\/p\/[^/]+$/.test(pathname)) {
    window.history.replaceState(null, "", `${pathname}/${search}${hash}`);
  }
});
```

Do **not** attempt this through `navigate({ pathname })` — the router collapses it
either way, and you end up with a comment describing a fix that never runs.

---

## 5. Make the page diagnose itself

The highest-value change in this whole exercise. A blank page reports nothing,
and each round trip to ask the user for a screenshot costs a deploy cycle.

Add an **inline** script to `index.html` — inline so it runs even when the bundle
never loads:

```html
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
<script>
  (function () {
    function apiBase() {
      var m = location.pathname.match(/^\/p\/[^/]+/);
      return (m ? m[0] : "") + "/api";
    }
    function report() {
      var root = document.getElementById("root");
      if (root && root.childNodes.length > 0) return;   // app mounted; stay silent
      var urls = [].map.call(
        document.querySelectorAll("script[src], link[rel=stylesheet]"),
        function (el) { return el.src || el.href; }
      ).filter(Boolean);
      Promise.all(urls.concat([location.origin + apiBase() + "/health"]).map(function (u) {
        return fetch(u).then(
          function (r) { return u + " → " + r.status + " " + (r.headers.get("content-type") || "?"); },
          function (e) { return u + " → network error: " + e.message; }
        );
      })).then(function (rows) {
        document.body.innerHTML =
          "<pre style='font:13px ui-monospace,monospace;padding:32px;white-space:pre-wrap'>" +
          "App did not start\n\n" + rows.join("\n") +
          "\n\npage url     " + location.href +
          "\nmount prefix " + (location.pathname.match(/^\/p\/[^/]+/) || ["(root)"])[0] +
          "\napi base     " + apiBase() + "</pre>";
      });
    }
    window.addEventListener("load", function () { setTimeout(report, 6000); });
  })();
</script>
```

**The content-type column is the point.** A `404` and a `200 text/html` look
identical from the outside — a blank page — but they mean different things, and
without that column you cannot tell them apart.

If even this panel never appears, the inline script itself was blocked: suspect a
Content-Security-Policy on the platform side.

---

## 6. Guards that stop it recurring

### Build-time assertion

Fail the image build rather than discovering it after deploy:

```dockerfile
RUN npm run build
RUN if grep -qE '(src|href)="/assets/' dist/index.html; then \
      echo "FATAL: index.html references root-absolute /assets/ — this blanks under a path prefix." >&2; \
      grep -oE '(src|href)="[^"]*"' dist/index.html >&2; \
      exit 1; \
    fi
```

### Fail loudly when an API call returns HTML

```ts
function assertJson(res: Response, path: string) {
  const type = res.headers.get("content-type") || "";
  if (!type.includes("json")) {
    throw new Error(
      `${path} returned ${type || "no content-type"} instead of JSON — ` +
      `the /api proxy is not reaching the backend (resolved base: ${API_BASE})`
    );
  }
}
// call on every 2xx response except 204
```

### Make a misrouted `/api` path impossible to mistake for success

```nginx
# Any /api path that reaches the SPA fallback would answer 200 text/html.
location ~ ^(?:/p/[^/]+)?/api(?:/|$) {
    default_type application/json;
    return 502 '{"detail":"API route did not reach the backend"}';
}
```

Order matters: mark the real proxy location `^~` so this regex cannot shadow it.

### Browser-level regression tests

```js
const apiReqs = [];
page.on("request", r => { if (r.url().includes("/api/")) apiReqs.push(r.url()); });
page.on("response", async r => { /* record status + content-type */ });

// assert: no request URL contains "//api"
// assert: every 2xx /api response is application/json, never text/html
```

Run the whole suite at **several mount points** — `/`, `/p/slug-a/`,
`/p/slug-b/` — and once with `merge_slashes off`. A suite that only ever runs at
one prefix behind a forgiving proxy will pass on a build that cannot deploy.

---

## 7. Two adjacent failures worth knowing

**nginx refuses to start if the backend name does not resolve.** `proxy_pass
http://backend:8000` is resolved at *config load*, so nginx exits with
`host not found in upstream` and the container crash-loops — no page at all,
rather than a blank one. Wait for the name before starting:

```sh
i=0; while [ "$i" -lt 30 ]; do getent hosts backend >/dev/null 2>&1 && break; i=$((i+1)); sleep 1; done
exec nginx -g 'daemon off;'
```

(A runtime `resolver` with a variable `proxy_pass` also defers resolution, but it
makes every request depend on Docker's embedded DNS at `127.0.0.11`. Only take
that trade if you know the runtime provides it.)

**`npm ci` can fail and still exit 0.** It has been observed printing
`Exit handler never called!`, exiting 0, and leaving `node_modules` incomplete —
so the build dies later with a misleading `tsc: not found`, or ships a partial
bundle. Verify the toolchain immediately after install:

```dockerfile
RUN npm ci && npx --no-install tsc --version && npx --no-install vite --version
```

---

## 8. Checklist

- [ ] Built `index.html` references `./assets/…` or `/p/{correct-slug}/assets/…`, never `/assets/…`
- [ ] Verified by building with the pipeline's **real** command (usually no `--build-arg`)
- [ ] Base path resolved from `process.env` → `.env` via `loadEnv` → relative fallback; empty treated as unset
- [ ] Dockerfile ARGs default to empty, not `/`
- [ ] API base strips trailing slashes; no request can contain `//api`
- [ ] API base derived from `window.location`, with the injected value only a fallback
- [ ] `/p/{slug}` redirects to `/p/{slug}/`, query string preserved
- [ ] App normalises its own address bar to keep the trailing slash
- [ ] A misrouted `/api` path returns an error, never `200 text/html`
- [ ] Build fails on root-absolute assets
- [ ] Inline boot check ships in `index.html`
- [ ] Suite runs at multiple mount points and once with `merge_slashes off`

---

## 9. Process notes

Three lessons that cost more than the bugs did:

1. **Local nginx is more forgiving than the platform router.** `merge_slashes on`
   masked a broken build through 26 passing checks. Test against the unforgiving
   configuration deliberately.

2. **Test the command the pipeline runs.** Compose passing `BASE_PATH=""` as an
   explicit build-arg *overrode the very ARG default that was breaking
   production*. The test exercised a path the pipeline never takes.

3. **Do not report a root cause you have not reproduced.** Each of §2, §3 and §4
   is a genuine bug, and each was announced as "the" fix before the next deploy
   proved otherwise. The fix that ended it was making the page report its own
   state, which turned guessing into one screenshot.
