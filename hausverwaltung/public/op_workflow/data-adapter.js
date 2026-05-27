// data-adapter.js — Datenschicht zwischen Frappe-Backend und den React-Components.
//
// Lädt offene Posten via op_workflow.get_open_items() per frappe.call.
// Die React-Components erwarten ein bestimmtes Row-Schema (siehe adaptRow unten).
// Falls dein echter Report andere Field-Namen liefert, passe NUR adaptRow() an.

(function () {
  // ─── ROOT-ID-Shim ──────────────────────────────────────────────────────
  // op-app.jsx mounted auf #root — Frappe-Page hat #op-workflow-root.
  // Wir spiegeln das Element als #root, damit der bestehende Code unverändert läuft.
  function ensureRootMount() {
    const target = document.getElementById("op-workflow-root");
    if (target && !document.getElementById("root")) {
      target.id = "root";
    }
  }

  async function fetchRows(filters) {
    const res = await frappe.call({
      method: "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_open_items",
      args: { filters: filters || {} },
    });
    return res.message;
  }

  function defaultDateFilter() {
    const d = new Date();
    const Y = d.getFullYear();
    const M = d.getMonth();
    const pad = (n) => String(n).padStart(2, "0");
    return {
      von_faelligkeit: `${Y}-${pad(M + 1)}-01`,
      bis_faelligkeit: `${Y}-${pad(M + 1)}-${pad(new Date(Y, M + 1, 0).getDate())}`,
    };
  }

  async function loadReal() {
    const { rows, today } = await fetchRows({
      company: frappe.defaults.get_user_default("Company"),
      mode: "Forderungen",
      show_aktion: 1,
      ...defaultDateFilter(),
    });

    // Parties extrahieren für partyName-Lookup
    const partyMap = {};
    for (const r of rows) {
      if (r.party && r.party_name) partyMap[r.party] = r.party_name;
    }

    // CC-Labels — pro Kostenstelle deren `cost_center_name` holen.
    const ccLabel = {};
    const ccs = [...new Set(rows.map((r) => r.kostenstelle).filter(Boolean))];
    if (ccs.length) {
      const ccDocs = await frappe.db.get_list("Cost Center", {
        filters: [["name", "in", ccs]],
        fields: ["name", "cost_center_name"],
        limit_page_length: 200,
      });
      for (const cc of ccDocs) ccLabel[cc.name] = cc.cost_center_name || cc.name;
    }

    window.OFFENE_POSTEN = {
      filters: {},
      rows: rows.map(adaptRow),
      parties: partyMap,
      partyName: (id) => partyMap[id] || id,
      ccLabel,
      TODAY: today,
    };
  }

  // ─── Row-Adapter: Backend-Format → React-Component-Format ───────────────
  //
  // ⚠ WENN DEIN REPORT-OUTPUT ABWEICHT: passe HIER die Mappings an,
  // nicht in den React-Components.
  function adaptRow(raw) {
    return {
      art: raw.art,
      party: raw.party,
      buchungsdatum: raw.buchungsdatum,
      faellig_am: raw.faellig_am,
      belegart: raw.belegart,
      belegnummer: raw.belegnummer,
      rechnungsbetrag: raw.rechnungsbetrag,
      bezahlt: raw.bezahlt,
      offen: raw.offen,
      party_account: raw.party_account,
      kostenstelle: raw.kostenstelle,
      bemerkungen: raw.bemerkungen,
      status: raw.status,
      zahlungsrichtung: raw.zahlungsrichtung,
      alter_tage: raw.alter_tage ?? 0,
      can_write_off: !!raw.can_write_off,
      mahnstufe: raw.mahnstufe ?? 0,
    };
  }

  // Refresh — Caller gibt {von_faelligkeit, bis_faelligkeit, ...} mit.
  // Andere Filter (company/mode/show_aktion) werden ergänzt.
  async function refresh(filters) {
    const merged = {
      company: frappe.defaults.get_user_default("Company"),
      mode: "Forderungen",
      show_aktion: 1,
      ...(filters || {}),
    };
    window.dispatchEvent(new CustomEvent("op-loading-start"));
    try {
      const { rows } = await fetchRows(merged);
      window.OFFENE_POSTEN.rows = rows.map(adaptRow);
      window.dispatchEvent(new CustomEvent("op-data-refreshed"));
    } finally {
      window.dispatchEvent(new CustomEvent("op-loading-end"));
    }
  }

  // ─── Public API ─────────────────────────────────────────────────────────
  window.OP_ADAPTER = {
    async loadInitial() {
      ensureRootMount();
      await loadReal();
    },
    refresh,
  };
})();
