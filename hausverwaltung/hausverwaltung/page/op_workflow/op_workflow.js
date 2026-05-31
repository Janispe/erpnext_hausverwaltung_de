// op_workflow.js — Frappe-Page-Bootstrap.
//
// Hängt unsere React-UI in die Page ein. Lädt:
//   1. styles.css
//   2. data-adapter.js + action-handlers.js (Bridge zu frappe.call)
//   3. op-workflow.bundle.js (React + UI lokal gebundelt)
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

  // Page-Toolbar bewusst leer: Die React-UI rendert ihren eigenen Topbar
  // (Mieterkonto / Drucken / Export CSV / Sammelmahnung), eine zweite Leiste
  // im Frappe-Page-Header wäre ein optisches Duplikat.

  // ─── React Mount-Point + Loading-Spinner ────────────────────────────────
  $(page.body).html(`
    <div id="op-workflow-root" style="margin:-15px -15px 0 -15px;">
      <div style="display:flex;align-items:center;justify-content:center;height:60vh;color:#666;font-size:14px;">
        <span style="display:inline-block;width:18px;height:18px;border:2px solid #ccc;border-top-color:#666;border-radius:50%;animation:op-spin 0.8s linear infinite;margin-right:10px;"></span>
        Offene Posten werden geladen …
      </div>
    </div>
    <style>@keyframes op-spin{to{transform:rotate(360deg)}}</style>
  `);

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
      if (existing) {
        if (existing.dataset.loaded === "1") return resolve();
        existing.addEventListener("load", resolve, { once: true });
        existing.addEventListener("error", () => reject(new Error(`Failed to load: ${src}`)), { once: true });
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.dataset.opSrc = src;
      if (opts.type) s.type = opts.type;
      if (opts.integrity) {
        s.integrity = opts.integrity;
        s.crossOrigin = "anonymous";
      }
      s.onload = () => {
        s.dataset.loaded = "1";
        resolve();
      };
      s.onerror = () => reject(new Error(`Failed to load: ${src}`));
      document.head.appendChild(s);
    });

  (async () => {
    try {
      // Bridge-Layer (Mock ↔ frappe.call)
      await loadScript(`${ASSET_BASE}/data-adapter.js`);
      await loadScript(`${ASSET_BASE}/action-handlers.js`);

      // Daten initial laden — data-adapter.js setzt window.OFFENE_POSTEN
      await window.OP_ADAPTER.loadInitial();

      // React-Components — esbuild-Bundle (tweaks-panel + op-components + op-actions + op-app)
      // Build: cd op_workflow_build && NODE_ENV=production npm run build
      await loadScript(`${ASSET_BASE}/op-workflow.bundle.js`);
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
