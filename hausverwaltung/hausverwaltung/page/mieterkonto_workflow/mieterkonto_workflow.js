// mieterkonto_workflow.js — Frappe-Page-Bootstrap für Mieterkonto (neu).
//
// Lädt die UI in das Frappe-Page-Skelett. URL-Param `?customer=XYZ` setzt den
// Mieter vor; Toolbar hat zusätzlich Mieter-Link + Von/Bis-Date-Felder + Presets.

frappe.pages["mieterkonto-workflow"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Mieterkonto (neu)"),
    single_column: true,
  });

  const todayStr = frappe.datetime.get_today();
  const yearStart = `${new Date().getFullYear()}-01-01`;

  // ─── Toolbar-Felder ────────────────────────────────────────────────────
  const customerField = page.add_field({
    label: __("Mieter"),
    fieldtype: "Link",
    fieldname: "customer",
    options: "Customer",
    change: () => reload(),
  });

  const fromField = page.add_field({
    label: __("Von"),
    fieldtype: "Date",
    fieldname: "from_date",
    default: yearStart,
    change: () => reload(),
  });

  const toField = page.add_field({
    label: __("Bis"),
    fieldtype: "Date",
    fieldname: "to_date",
    default: todayStr,
    change: () => reload(),
  });

  // Preset-Buttons unter "Zeitraum"-Gruppe
  page.add_inner_button(
    __("Dieses Jahr"),
    () => setRange(`${new Date().getFullYear()}-01-01`, todayStr),
    __("Zeitraum"),
  );
  page.add_inner_button(
    __("Vorjahr"),
    () => {
      const y = new Date().getFullYear() - 1;
      setRange(`${y}-01-01`, `${y}-12-31`);
    },
    __("Zeitraum"),
  );
  page.add_inner_button(
    __("Letzte 12 Monate"),
    () => {
      const d = new Date();
      d.setMonth(d.getMonth() - 12);
      const iso = d.toISOString().slice(0, 10);
      setRange(iso, frappe.datetime.get_today());
    },
    __("Zeitraum"),
  );

  page.set_primary_action(__("PDF erzeugen"), () => window.print());
  page.set_secondary_action(__("→ Offene Posten"), () =>
    frappe.set_route("op-workflow"),
  );

  // Setzt beide Date-Felder und triggert einen Reload (change-Event feuert pro
  // set_value automatisch — `_suppressReload` verhindert doppelten Call).
  let _suppressReload = false;
  function setRange(from, to) {
    _suppressReload = true;
    fromField.set_value(from);
    toField.set_value(to);
    _suppressReload = false;
    reload();
  }

  async function reload() {
    if (_suppressReload || !window.MK_ADAPTER) return;
    const customer = customerField.get_value();
    await window.MK_ADAPTER.load(customer, fromField.get_value(), toField.get_value());
    window.dispatchEvent(new CustomEvent("mk-data-refreshed"));
  }

  // React Mount-Point
  $(page.body).html(
    '<div id="mk-workflow-root" style="margin:-15px -15px 0 -15px;"></div>',
  );

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
      await loadScript("https://unpkg.com/react@18.3.1/umd/react.development.js", {
        integrity: "sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L",
      });
      await loadScript("https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js", {
        integrity: "sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm",
      });

      // Bridge-Layer (frappe.call)
      await loadScript(`${ASSET_BASE}/mk-data-adapter.js`);

      // Initial-Customer aus URL
      const initialCustomer = frappe.utils.get_query_params().customer;
      _suppressReload = true;
      if (initialCustomer) customerField.set_value(initialCustomer);
      _suppressReload = false;

      // Daten initial laden
      await window.MK_ADAPTER.load(
        initialCustomer,
        fromField.get_value(),
        toField.get_value(),
      );

      // ID-Shim — mk-app.jsx mounted auf #root, Page hat #mk-workflow-root
      const target = document.getElementById("mk-workflow-root");
      if (target) target.id = "root";

      // React-Components — esbuild-Bundle
      // Build: cd op_workflow_build && NODE_ENV=production npm run build
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
