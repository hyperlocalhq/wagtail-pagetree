import React from "react";
import ReactDOM from "react-dom";
import App from "./components/App.jsx";
import { readConfig } from "./urls.js";

// Auto-mount on DOM ready. The template renders #pagetree-root; if it's
// missing (e.g. bundle loaded on a different admin page) we no-op.

function mount() {
  const root = document.getElementById("pagetree-root");
  if (!root) return;
  let cfg;
  try {
    cfg = readConfig(root);
  } catch (e) {
    // Config error → leave the noscript fallback message; log for debugging.
    // eslint-disable-next-line no-console
    console.error(e);
    return;
  }
  // React 16.14: classic render API. No createRoot.
  ReactDOM.render(<App config={cfg} />, root);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount, { once: true });
} else {
  mount();
}
