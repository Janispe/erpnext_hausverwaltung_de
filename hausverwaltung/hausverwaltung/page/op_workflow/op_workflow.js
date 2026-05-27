// op_workflow.js — Frappe-Page-Bootstrap.
//
// Hängt unsere React-UI in die Page ein. Lädt:
//   1. styles.css
//   2. React + ReactDOM + (Dev:) Babel-Standalone
//   3. Unsere Components in Reihenfolge
//   4. data-adapter.js + action-handlers.js (Bridge zu frappe.call)
//
// In Phase 1+2 läuft alles über Inline-Babel (Dev-Modus).
// In Phase 3 ersetzt du die <script type="text/babel">-Blöcke durch
// <script src="op-workflow.bundle.js"> (siehe build/README.md).

frappe.pages["op-workflow"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Offene Posten (neu)"),
    single_column: true,
  });

  // ─── Page-Toolbar ───────────────────────────────────────────────────────
  page.set_primary_action(__("Sammelmahnung"), () => {
    window.dispatchEvent(new CustomEvent("op-trigger-bulk-dunning"));
  });
  page.set_secondary_action(__("Export CSV"), () => {
    window.dispatchEvent(new CustomEvent("op-trigger-export"));
  });

  // ─── React Mount-Point ──────────────────────────────────────────────────
  $(page.body).html('<div id="op-workflow-root" style="margin:-15px -15px 0 -15px;"></div>');

  // ─── CSS + Fonts laden ──────────────────────────────────────────────────
  const cssHref = "/assets/hausverwaltung/op_workflow/styles.css";
  if (!document.querySelector(`link[href="${cssHref}"]`)) {
    $(`<link rel="stylesheet" href="${cssHref}">`).appendTo("head");
  }
  // Inter Font — falls schon via ERPNext geladen, kein Doppellade-Problem
  const fontHref = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap";
  if (!document.querySelector(`link[href="${fontHref}"]`)) {
    $(`<link rel="stylesheet" href="${fontHref}">`).appendTo("head");
  }

  // ─── Scripts in Reihenfolge laden ───────────────────────────────────────
  const ASSET_BASE = "/assets/hausverwaltung/op_workflow";

  const loadScript = (src, opts = {}) =>
    new Promise((resolve, reject) => {
      // Idempotent: nicht doppelt laden
      const existing = document.querySelector(`script[data-op-src="${src}"]`);
      if (existing) return resolve();
      const s = document.createElement("script");
      s.src = src;
      s.dataset.opSrc = src;
      if (opts.type) s.type = opts.type;
      if (opts.integrity) {
        s.integrity = opts.integrity;
        s.crossOrigin = "anonymous";
      }
      s.onload = resolve;
      s.onerror = () => reject(new Error(`Failed to load: ${src}`));
      document.head.appendChild(s);
    });

  (async () => {
    try {
      // React + ReactDOM (Bundle nutzt window.React/window.ReactDOM als Globals)
      await loadScript("https://unpkg.com/react@18.3.1/umd/react.development.js", {
        integrity: "sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L",
      });
      await loadScript("https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js", {
        integrity: "sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm",
      });

      // Bridge-Layer (Mock ↔ frappe.call)
      await loadScript(`${ASSET_BASE}/data-adapter.js`);
      await loadScript(`${ASSET_BASE}/action-handlers.js`);

      // Daten initial laden — data-adapter.js setzt window.OFFENE_POSTEN
      await window.OP_ADAPTER.loadInitial();

      // React-Components — esbuild-Bundle (tweaks-panel + op-components + op-actions + op-app)
      // Build: cd op_workflow_build && NODE_ENV=production npm run build
      await loadScript(`${ASSET_BASE}/op-workflow.bundle.js`);

      // op-app.jsx mounted automatisch auf #root — wir haben aber #op-workflow-root
      // → kleiner Shim: alias setzen bevor das Script lädt (in data-adapter.js)
    } catch (err) {
      console.error("op-workflow bootstrap failed", err);
      frappe.msgprint({
        title: __("Lade-Fehler"),
        message: __("Konnte UI nicht laden: ") + err.message,
        indicator: "red",
      });
    }
  })();
};
