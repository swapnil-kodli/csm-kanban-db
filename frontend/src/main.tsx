import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/inter/800.css";
import "./styles.css";
import App from "./App";

function mountPrefix(): string {
  const match = window.location.pathname.match(/^\/p\/[^/]+/);
  if (match) return match[0];
  // BASE_URL is "./" when the app is built with a relative base, which is not a
  // usable basename — React Router would match nothing and render null.
  const injected = import.meta.env.BASE_URL;
  return injected && injected.startsWith("/") ? injected : "/";
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* The marketplace serves the app under /p/{slug}/. Prefer the prefix the
        app is actually mounted at over the one baked in at build time — the
        build pipeline does not reliably receive the slug. */}
    <BrowserRouter basename={mountPrefix()}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
