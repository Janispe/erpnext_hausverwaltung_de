// mahnung_workflow.js — Frappe-Page-Bootstrap für den Mahnung-Editor.
//
// Lädt lokale Assets:
//   1. styles.css
//   2. mahn-data-adapter.js + mahn-action-handlers.js
//   3. mahn-workflow.bundle.js (React + UI lokal gebundelt)

let mahnung_workflow_page_body = null;

frappe.pages["mahnung-workflow"].on_page_show = function () {
  if (mahnung_workflow_page_body) {
    render_mahnung_workflow(mahnung_workflow_page_body);
  }
};

frappe.pages["mahnung-workflow"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Mahnung erstellen (neu)"),
    single_column: true,
  });

  page.set_secondary_action(__("Offene Posten"), () => {
    frappe.set_route("op-workflow");
  });

  mahnung_workflow_page_body = page.body;
  render_mahnung_workflow(page.body);
};

function render_mahnung_workflow(page_body) {
  if (window.__MH_REACT_ROOT) {
    try {
      window.__MH_REACT_ROOT.unmount();
    } catch (err) {
      // Frappe may already have replaced the previous mount point.
    }
    window.__MH_REACT_ROOT = null;
  }

  $(page_body).html(`
    <div id="mahnung-workflow-root" style="margin:-15px -15px 0 -15px;">
      <div style="display:flex;align-items:center;justify-content:center;height:60vh;color:#666;font-size:14px;">
        <span style="display:inline-block;width:18px;height:18px;border:2px solid #ccc;border-top-color:#666;border-radius:50%;animation:mh-spin 0.8s linear infinite;margin-right:10px;"></span>
        Mahnung wird geladen ...
      </div>
    </div>
    <style>@keyframes mh-spin{to{transform:rotate(360deg)}}</style>
  `);

  const ASSET_BASE = "/assets/hausverwaltung/mahnung_workflow";
  const ASSET_VERSION = "20260625-finalized";
  const versioned = (src) => `${src}?v=${ASSET_VERSION}`;

  const cssHref = versioned(`${ASSET_BASE}/styles.css`);
  if (!document.querySelector(`link[href="${cssHref}"]`)) {
    $(`<link rel="stylesheet" href="${cssHref}">`).appendTo("head");
  }

  const fontHref = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap";
  if (!document.querySelector(`link[href="${fontHref}"]`)) {
    $(`<link rel="stylesheet" href="${fontHref}">`).appendTo("head");
  }

  const loadScript = (src) =>
    new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-mahn-src="${src}"]`);
      if (existing) {
        if (existing.dataset.loaded === "1") return resolve();
        existing.addEventListener("load", resolve, { once: true });
        existing.addEventListener("error", () => reject(new Error(`Failed to load: ${src}`)), { once: true });
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.dataset.mahnSrc = src;
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
    const root = document.getElementById("mahnung-workflow-root") || document.getElementById("root");
    if (root) {
      root.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;min-height:60vh;padding:32px;color:#8a1f11;">
          <div style="max-width:720px;border:1px solid #f0b8ad;background:#fff4f1;border-radius:8px;padding:16px 18px;">
            <div style="font-weight:600;margin-bottom:6px;">Mahnung konnte nicht geladen werden.</div>
            <div style="font-size:13px;color:#6f2b21;">${escapeHtml(message)}</div>
            <button class="btn btn-default btn-sm" style="margin-top:12px;" onclick="frappe.pages['mahnung-workflow'].on_page_show()">Erneut laden</button>
          </div>
        </div>
      `;
    }
  };

  (async () => {
    try {
      await loadScript(versioned(`${ASSET_BASE}/mahn-data-adapter.js`));
      await loadScript(versioned(`${ASSET_BASE}/mahn-action-handlers.js`));
      await window.MAHN_ADAPTER.loadInitial();

      await loadScript(versioned(`${ASSET_BASE}/mahn-workflow.bundle.js`));
      if (window.MH_RENDER) window.MH_RENDER();
    } catch (err) {
      console.error("mahnung-workflow bootstrap failed", err);
      showBootstrapError(err);
      frappe.msgprint({
        title: __("Lade-Fehler"),
        message: __("Konnte UI nicht laden: ") + err.message,
        indicator: "red",
      });
    }
  })();
}
