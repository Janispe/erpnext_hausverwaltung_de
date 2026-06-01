// mk-data-adapter.js — Bridge: Frappe ↔ Mieterkonto-React-Components.
//
// Ruft den echten Mieterkonto-Report + Stammdaten-Endpoint.

(function () {
  async function loadReal(customer, fromDate, toDate, options = {}) {
    if (!customer) {
      window.MIETERKONTO = emptyState();
      return window.MIETERKONTO;
    }

    const company = frappe.defaults.get_user_default("Company");
    const from = fromDate || defaultFromDate();
    const to = toDate || frappe.datetime.get_today();

    const [stammRes, reportRes] = await Promise.all([
      frappe.call({
        method: "hausverwaltung.hausverwaltung.page.mieterkonto_workflow.mieterkonto_workflow.get_mieter_stammdaten",
        args: { customer },
      }),
      frappe.call({
        method: "hausverwaltung.hausverwaltung.page.mieterkonto_workflow.mieterkonto_workflow.get_mieterkonto",
        args: {
          filters: {
            company,
            customer,
            from_date: from,
            to_date: to,
            show_kategorien: 1,
            gruppieren_pro_monat: options.gruppieren === false ? 0 : 1,
          },
        },
      }),
    ]);

    const mieter = stammRes.message;
    const { rows = [], summary = [] } = reportRes.message || {};

    const totalRow = rows.find((r) => r.is_total_row) || rows[rows.length - 1] || emptyTotalRow(to);
    const txRows = rows.filter((r) => !r.is_total_row);

    window.MIETERKONTO = {
      mieter,
      filters: {
        company,
        customer: `${customer} — ${mieter.name}`,
        from_date: from,
        to_date: to,
      },
      rows: txRows.map(adaptRow),
      totalRow: adaptRow(totalRow),
      summary: adaptSummary(summary),
    };
    return window.MIETERKONTO;
  }

  function adaptRow(raw) {
    if (!raw) return null;
    return {
      datum: raw.datum,
      art: raw.art,
      belegart: raw.belegart,
      belegnummer: raw.belegnummer,
      beschreibung: raw.beschreibung,
      betrag_miete: raw.betrag_miete || 0,
      betrag_betriebskosten: raw.betrag_betriebskosten || 0,
      betrag_heizkosten: raw.betrag_heizkosten || 0,
      betrag_guthaben_nachzahlungen: raw.betrag_guthaben_nachzahlungen || 0,
      betrag_summe: raw.betrag_summe || 0,
      kontostand: raw.kontostand || 0,
      faellig_am: raw.faellig_am || null,
      status: raw.status || null,
      offen: raw.offen || 0,
      is_opening_row: !!raw.is_opening_row,
      is_total_row: !!raw.is_total_row,
    };
  }

  function adaptSummary(rawSummary) {
    const summary = rawSummary && rawSummary.length ? rawSummary : defaultSummary();
    const normalized = summary.map((s) => ({
      label: s.label,
      value: Number(s.value) || 0,
      indicator: s.indicator || "neutral",
    }));
    for (const item of defaultSummary()) {
      if (!normalized.some((s) => s.label === item.label)) normalized.push(item);
    }
    return normalized;
  }

  function defaultFromDate() {
    return `${new Date().getFullYear()}-01-01`;
  }

  function emptyState() {
    return {
      mieter: {
        name: "Bitte Mieter auswählen",
        customer_id: "—",
        aufteilung_aktuell: {},
      },
      filters: {
        from_date: defaultFromDate(),
        to_date: frappe.datetime.get_today(),
      },
      rows: [],
      totalRow: emptyTotalRow(frappe.datetime.get_today()),
      summary: defaultSummary(),
    };
  }

  function emptyTotalRow(date) {
    return {
      datum: date,
      art: "",
      belegart: "",
      belegnummer: "",
      beschreibung: "",
      betrag_summe: 0,
      kontostand: 0,
      is_total_row: true,
    };
  }

  function defaultSummary() {
    return [
      { label: "Kontostand", value: 0, indicator: "neutral" },
      { label: "Bezahlt im Zeitraum", value: 0, indicator: "neutral" },
      { label: "Miete offen", value: 0, indicator: "neutral" },
      { label: "BK offen", value: 0, indicator: "neutral" },
      { label: "HK offen", value: 0, indicator: "neutral" },
      { label: "G/N offen", value: 0, indicator: "neutral" },
    ];
  }

  window.MK_ADAPTER = {
    async load(customer, fromDate, toDate, options) {
      return await loadReal(customer, fromDate, toDate, options);
    },
    async searchMieter(txt = "", status = "Läuft") {
      const res = await frappe.call({
        method: "hausverwaltung.hausverwaltung.page.mieterkonto_workflow.mieterkonto_workflow.search_mieter",
        args: { txt, status, limit: 30 },
      });
      return res.message || [];
    },
    emptyState,
  };
})();
