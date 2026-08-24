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

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Marketplace serves the app under /p/{slug}/ — the basename is injected. */}
    <BrowserRouter basename={import.meta.env.BASE_URL || "/"}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
