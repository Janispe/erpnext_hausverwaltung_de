// mahnung_workflow.js — Frappe-Page-Bootstrap für den Mahnung-Editor.
//
// Lädt in Reihenfolge:
//   1. styles.css + Inter-Font
//   2. React + ReactDOM + (Dev:) Babel-Standalone
//   3. mahn-data-adapter.js  → window.MAHN_ADAPTER (Mock ↔ frappe.call)
//   4. data-mahnung.js (Mock) ODER echte Daten via Adapter → window.MAHNUNG
//   5. mahn-action-handlers.js → window.MAHN_ACTIONS (Versand/Buchung)
//   6. React-Components: tweaks-panel, mahn-components, mahn-letter, mahn-app
//
// Aufruf mit vorausgewähltem Mieter:
//   /app/mahnung-workflow?party=DEB-2024-00147
//
// Phase 1+2 laufen über Inline-Babel. Für Phase 3 die <script type="text/babel">
// durch ein gebautes Bundle ersetzen (siehe build/README.md).

frappe.pages["mahnung-workflow"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Mahnung erstellen (neu)"),
    single_column: true,
  });

  page.set_secondary_action(__("Offene Posten"), () => {
    frappe.set_route("op-workflow");
  });

  // React Mount-Point — der Adapter spiegelt die ID auf #root
  $(page.body).html('<div id="mahnung-workflow-root" style="margin:-15px -15px 0 -15px;"></div>');

  // CSS + Font
  const cssHref = "/assets/hausverwaltung/mahnung_workflow/styles.css";
  if (!document.querySelector(`link[href="${cssHref}"]`)) {
    $(`<link rel="stylesheet" href="${cssHref}">`).appendTo("head");
  }
  const fontHref = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap";
  if (!document.querySelector(`link[href="${fontHref}"]`)) {
    $(`<link rel="stylesheet" href="${fontHref}">`).appendTo("head");
  }

  const ASSET_BASE = "/assets/hausverwaltung/mahnung_workflow";

  const loadScript = (src, opts = {}) =>
    new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-mahn-src="${src}"]`);
      if (existing) return resolve();
      const s = document.createElement("script");
      s.src = src;
      s.dataset.mahnSrc = src;
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
      await loadScript("https://unpkg.com/react@18.3.1/umd/react.development.js", {
        integrity: "sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L",
      });
      await loadScript("https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js", {
        integrity: "sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm",
      });
      await loadScript("https://unpkg.com/@babel/standalone@7.29.0/babel.min.js", {
        integrity: "sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y",
      });

      // Bridge + Daten (Mock ODER frappe.call) → setzt window.MAHNUNG
      await loadScript(`${ASSET_BASE}/mahn-data-adapter.js`);
      await loadScript(`${ASSET_BASE}/mahn-action-handlers.js`);
      await window.MAHN_ADAPTER.loadInitial();

      // React-Components (Phase 3 → einzelnes Bundle)
      await loadScript(`${ASSET_BASE}/tweaks-panel.jsx`, { type: "text/babel" });
      await loadScript(`${ASSET_BASE}/mahn-components.jsx`, { type: "text/babel" });
      await loadScript(`${ASSET_BASE}/mahn-letter.jsx`, { type: "text/babel" });
      await loadScript(`${ASSET_BASE}/mahn-app.jsx`, { type: "text/babel" });
    } catch (err) {
      console.error("mahnung-workflow bootstrap failed", err);
      frappe.msgprint({
        title: __("Lade-Fehler"),
        message: __("Konnte UI nicht laden: ") + err.message,
        indicator: "red",
      });
    }
  })();
};
