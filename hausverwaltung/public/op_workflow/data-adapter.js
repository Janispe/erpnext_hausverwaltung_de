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

  async function fetchMahnkandidaten(filters) {
    const res = await frappe.call({
      method: "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_mahnkandidaten",
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

  function defaultFilters() {
    return {
      company: frappe.defaults.get_user_default("Company"),
      mode: "Beides",
      show_aktion: 1,
      show_settled: 0,
      show_written_off: 0,
      ...defaultDateFilter(),
    };
  }

  async function hydrateLookups(rows) {
    const partyMap = {};
    const partiesByType = {};
    for (const r of rows) {
      if (r.party && r.party_name) partyMap[r.party] = r.party_name;
      if (r.party && r.party_type && !partyMap[r.party]) {
        if (!partiesByType[r.party_type]) partiesByType[r.party_type] = new Set();
        partiesByType[r.party_type].add(r.party);
      }
    }

    const partyConfig = {
      Customer: { fields: ["name", "customer_name"], label: (doc) => doc.customer_name || doc.name },
      Supplier: { fields: ["name", "supplier_name"], label: (doc) => doc.supplier_name || doc.name },
    };
    for (const [doctype, names] of Object.entries(partiesByType)) {
      const cfg = partyConfig[doctype];
      if (!cfg || !names.size) continue;
      const docs = await frappe.db.get_list(doctype, {
        filters: [["name", "in", [...names]]],
        fields: cfg.fields,
        limit_page_length: 500,
      });
      for (const doc of docs) partyMap[doc.name] = cfg.label(doc);
    }

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

    return { partyMap, ccLabel };
  }

  async function loadReal() {
    const filters = defaultFilters();
    const [{ rows, today }, mahnData] = await Promise.all([
      fetchRows(filters),
      fetchMahnkandidaten(filters),
    ]);
    const { partyMap, ccLabel } = await hydrateLookups(rows);

    window.OFFENE_POSTEN = {
      filters,
      rows: rows.map(adaptRow),
      mahnkandidaten: mahnData?.rows || [],
      parties: partyMap,
      partyName: (id) => partyMap[id] || id,
      ccLabel,
      TODAY: today || mahnData?.today,
    };
  }

  // ─── Row-Adapter: Backend-Format → React-Component-Format ───────────────
  //
  // ⚠ WENN DEIN REPORT-OUTPUT ABWEICHT: passe HIER die Mappings an,
  // nicht in den React-Components.
  function adaptRow(raw) {
    return {
      art: raw.art,
      party_type: raw.party_type,
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

  // Refresh — Caller gibt Report-Filter mit. Defaults bleiben erhalten, damit
  // Tab-Wechsel und Toggles immer gegen echte Backend-Daten laufen.
  async function refresh(filters) {
    const merged = {
      ...(window.OFFENE_POSTEN?.filters || defaultFilters()),
      ...(filters || {}),
    };
    window.dispatchEvent(new CustomEvent("op-loading-start"));
    try {
      const { rows, today } = await fetchRows(merged);
      const mahnData = await fetchMahnkandidaten(merged);
      const { partyMap, ccLabel } = await hydrateLookups(rows);
      window.OFFENE_POSTEN.filters = merged;
      window.OFFENE_POSTEN.rows = rows.map(adaptRow);
      window.OFFENE_POSTEN.mahnkandidaten = mahnData?.rows || [];
      window.OFFENE_POSTEN.parties = partyMap;
      window.OFFENE_POSTEN.partyName = (id) => partyMap[id] || id;
      window.OFFENE_POSTEN.ccLabel = ccLabel;
      if (today || mahnData?.today) window.OFFENE_POSTEN.TODAY = today || mahnData.today;
      window.dispatchEvent(new CustomEvent("op-data-refreshed"));
      window.dispatchEvent(new CustomEvent("op-mahn-data-refreshed"));
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
