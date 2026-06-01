// data-adapter.js — Datenschicht zwischen Frappe-Backend und den React-Components.
//
// Lädt offene Posten via op_workflow.get_open_items() per frappe.call.
// Die React-Components erwarten ein bestimmtes Row-Schema (siehe adaptRow unten).
// Falls dein echter Report andere Field-Namen liefert, passe NUR adaptRow() an.

(function () {
  const REQUEST_TIMEOUT_MS = 45000;

  function callWithTimeout(options, label) {
    let timer = null;
    const timeout = new Promise((_, reject) => {
      timer = window.setTimeout(
        () => reject(new Error(`${label || "Anfrage"} hat zu lange gedauert. Bitte erneut versuchen.`)),
        REQUEST_TIMEOUT_MS
      );
    });
    return Promise.race([frappe.call(options), timeout]).finally(() => window.clearTimeout(timer));
  }

  // ─── ROOT-Finder ───────────────────────────────────────────────────────
  // Bevorzugt den aktuellen Frappe-Page-Mount. #root bleibt nur als Fallback
  // für bereits geladene ältere Bundles im selben Desk-Tab.
  function ensureRootMount() {
    return document.getElementById("op-workflow-root") || document.getElementById("root");
  }

  async function fetchRows(filters) {
    const res = await callWithTimeout({
      method: "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_open_items",
      args: { filters: filters || {} },
    }, "Offene-Posten-Abfrage");
    return res.message;
  }

  async function fetchMahnkandidaten(filters) {
    const res = await callWithTimeout({
      method: "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_mahnkandidaten",
      args: { filters: filters || {} },
    }, "Mahnwesen-Abfrage");
    return res.message;
  }

  function chunkArray(items, size) {
    const chunks = [];
    for (let i = 0; i < items.length; i += size) {
      chunks.push(items.slice(i, i + size));
    }
    return chunks;
  }

  async function getListInBatches(doctype, names, fields, batchSize = 40) {
    const docs = [];
    for (const batch of chunkArray([...names], batchSize)) {
      const rows = await frappe.db.get_list(doctype, {
        filters: [["name", "in", batch]],
        fields,
        limit_page_length: batch.length,
      });
      docs.push(...rows);
    }
    return docs;
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

  function emptyState() {
    return {
      filters: defaultFilters(),
      rows: [],
      mahnkandidaten: [],
      parties: {},
      partyName: (id) => id,
      ccLabel: {},
      TODAY: frappe.datetime?.get_today?.() || new Date().toISOString().slice(0, 10),
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
      const docs = await getListInBatches(doctype, names, cfg.fields);
      for (const doc of docs) partyMap[doc.name] = cfg.label(doc);
    }

    const ccLabel = {};
    const ccs = [...new Set(rows.map((r) => r.kostenstelle).filter(Boolean))];
    if (ccs.length) {
      const ccDocs = await getListInBatches("Cost Center", ccs, ["name", "cost_center_name"]);
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
      member_voucher_nos: Array.isArray(raw.member_voucher_nos) ? raw.member_voucher_nos : [],
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
    } catch (err) {
      window.dispatchEvent(new CustomEvent("op-loading-error", { detail: err }));
      throw err;
    } finally {
      window.dispatchEvent(new CustomEvent("op-loading-end"));
    }
  }

  // ─── Public API ─────────────────────────────────────────────────────────
  window.OP_ADAPTER = {
    async loadInitial() {
      ensureRootMount();
      window.OFFENE_POSTEN = window.OFFENE_POSTEN || emptyState();
    },
    refresh,
    emptyState,
  };
})();
