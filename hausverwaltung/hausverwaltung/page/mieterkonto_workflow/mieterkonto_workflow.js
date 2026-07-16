// mieterkonto_workflow.js — Frappe-Page-Bootstrap für Mieterkonto (neu).
//
// Picker (Mieter, Von, Bis, Presets) wird in der React-FilterBar gerendert
// (siehe mk-components.jsx). Hier nur Asset-Loading + Initialdaten.

let mieterkonto_workflow_page_body = null;

frappe.pages["mieterkonto-workflow"].on_page_show = function () {
  if (mieterkonto_workflow_page_body) {
    render_mieterkonto_workflow(mieterkonto_workflow_page_body);
  }
};

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

  mieterkonto_workflow_page_body = page.body;
  render_mieterkonto_workflow(page.body);
};

function render_mieterkonto_workflow(page_body) {
  if (window.__MK_REACT_ROOT) {
    try {
      window.__MK_REACT_ROOT.unmount();
    } catch (err) {
      // Frappe may already have replaced the previous mount point.
    }
    window.__MK_REACT_ROOT = null;
  }

  // React Mount-Point + Loading-Spinner
  $(page_body).html(`
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
  const ASSET_VERSION = "20260716-split-totals";
  const versioned = (src) => `${src}?v=${ASSET_VERSION}`;

  const cssHref = versioned(`${ASSET_BASE}/styles.css`);
  if (!document.querySelector(`link[href="${cssHref}"]`)) {
    $(`<link rel="stylesheet" href="${cssHref}">`).appendTo("head");
  }

  const loadScript = (src, opts = {}) =>
    new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-mk-src="${src}"]`);
      if (existing) {
        if (existing.dataset.loaded === "1") return resolve();
          existing.addEventListener("load", resolve, { once: true });
          existing.addEventListener("error", () => reject(new Error(`Failed to load: ${src}`)), { once: true });
          return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.dataset.mkSrc = src;
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

  const showBootstrapError = (err) => {
    const message = err?.message || String(err || __("Unbekannter Fehler"));
    const escapeHtml = (value) =>
      String(value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch]));
    const root = document.getElementById("mk-workflow-root");
    if (root) {
      root.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;min-height:60vh;padding:32px;color:#8a1f11;">
          <div style="max-width:720px;border:1px solid #f0b8ad;background:#fff4f1;border-radius:8px;padding:16px 18px;">
            <div style="font-weight:600;margin-bottom:6px;">Mieterkonto konnte nicht geladen werden.</div>
            <div style="font-size:13px;color:#6f2b21;">${escapeHtml(message)}</div>
            <button class="btn btn-default btn-sm" style="margin-top:12px;" onclick="frappe.pages['mieterkonto-workflow'].on_page_show()">Erneut laden</button>
          </div>
        </div>
      `;
    }
  };

  (async () => {
    try {
      // Bridge-Layer (frappe.call)
      await loadScript(versioned(`${ASSET_BASE}/mk-data-adapter.js`));

      // Initiale Filter
      const initialCustomer = new URLSearchParams(window.location.search).get("customer") || "";
      const initialFrom = `${new Date().getFullYear()}-01-01`;
      const initialTo = frappe.datetime.get_today();
      window.MK_INITIAL = { customer: initialCustomer, from_date: initialFrom, to_date: initialTo };
      window.MIETERKONTO = window.MK_ADAPTER.emptyState();

      // React-Components — esbuild-Bundle. Das Bundle rendert beim Ausführen;
      // bei erneuter Desk-Navigation rendert MK_RENDER auf den neuen Mount-Point.
      await loadScript(versioned(`${ASSET_BASE}/mk-workflow.bundle.js`));
      if (window.MK_RENDER) window.MK_RENDER();
    } catch (err) {
      console.error("mieterkonto-workflow bootstrap failed", err);
      showBootstrapError(err);
      frappe.msgprint({
        title: __("Lade-Fehler"),
        message: __("Konnte UI nicht laden: ") + err.message,
        indicator: "red",
      });
    }
  })();
}
