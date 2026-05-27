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

  async function loadReal() {
    const { rows, today } = await fetchRows({
      company: frappe.defaults.get_user_default("Company"),
      mode: "Forderungen",
      show_aktion: 1,
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

  async function refresh(filters) {
    const { rows } = await fetchRows(filters);
    window.OFFENE_POSTEN.rows = rows.map(adaptRow);
    window.dispatchEvent(new CustomEvent("op-data-refreshed"));
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
