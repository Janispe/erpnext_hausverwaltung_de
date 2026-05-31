// mieterkonto_workflow.js — Frappe-Page-Bootstrap für Mieterkonto (neu).
//
// Picker (Mieter, Von, Bis, Presets) wird in der React-FilterBar gerendert
// (siehe mk-components.jsx). Hier nur Asset-Loading + Initialdaten.

frappe.pages["mieterkonto-workflow"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Mieterkonto (neu)"),
    single_column: true,
  });

  page.set_primary_action(__("PDF erzeugen"), () => window.print());
  page.set_secondary_action(__("→ Offene Posten"), () =>
    frappe.set_route("op-workflow"),
  );

  // React Mount-Point + Loading-Spinner
  $(page.body).html(`
    <div id="mk-workflow-root" style="margin:-15px -15px 0 -15px;">
      <div style="display:flex;align-items:center;justify-content:center;height:60vh;color:#666;font-size:14px;">
        <span style="display:inline-block;width:18px;height:18px;border:2px solid #ccc;border-top-color:#666;border-radius:50%;animation:mk-spin 0.8s linear infinite;margin-right:10px;"></span>
        Mieterkonto wird geladen …
      </div>
    </div>
    <style>@keyframes mk-spin{to{transform:rotate(360deg)}}</style>
  `);

  // ─── Assets laden ──────────────────────────────────────────────────────
  const ASSET_BASE = "/assets/hausverwaltung/mieterkonto_workflow";

  const cssHref = `${ASSET_BASE}/styles.css`;
  if (!document.querySelector(`link[href="${cssHref}"]`)) {
    $(`<link rel="stylesheet" href="${cssHref}">`).appendTo("head");
  }

  const loadScript = (src, opts = {}) =>
    new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-mk-src="${src}"]`);
      if (existing) return resolve();
      const s = document.createElement("script");
      s.src = src;
      s.dataset.mkSrc = src;
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
      await loadScript("https://unpkg.com/react@18.3.1/umd/react.production.min.js");
      await loadScript("https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js");

      // Bridge-Layer (frappe.call)
      await loadScript(`${ASSET_BASE}/mk-data-adapter.js`);

      // Erste Treffer für die suchbare Mieter-Auswahl vorladen.
      window.MK_CUSTOMERS = await window.MK_ADAPTER.searchMieter("", "Läuft");

      // Initiale Filter
      const initialCustomer = frappe.utils.get_query_params().customer || "";
      const initialFrom = `${new Date().getFullYear()}-01-01`;
      const initialTo = frappe.datetime.get_today();
      window.MK_INITIAL = { customer: initialCustomer, from_date: initialFrom, to_date: initialTo };

      // Daten initial laden — Adapter setzt window.MIETERKONTO
      await window.MK_ADAPTER.load(initialCustomer, initialFrom, initialTo);

      // ID-Shim — mk-app.jsx mounted auf #root, Page hat #mk-workflow-root
      const target = document.getElementById("mk-workflow-root");
      if (target) target.id = "root";

      // React-Components — esbuild-Bundle
      await loadScript(`${ASSET_BASE}/mk-workflow.bundle.js`);
    } catch (err) {
      console.error("mieterkonto-workflow bootstrap failed", err);
      frappe.msgprint({
        title: __("Lade-Fehler"),
        message: __("Konnte UI nicht laden: ") + err.message,
        indicator: "red",
      });
    }
  })();
};
