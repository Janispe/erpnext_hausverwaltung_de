// app.jsx — Main shell + variant switcher + Tweaks.

const { useState, useEffect, useRef } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "variant": "A",
  "density": "regular",
  "showCats": false,
  "gruppieren": true,
  "highlightOpen": true,
  "defaultCatsOpen": false,
  "printMode": false
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Daten-State (wird bei Filter-Änderung neu gesetzt)
  const initialData = window.MIETERKONTO || window.MK_ADAPTER?.emptyState?.() || {
    mieter: { name: "Bitte Mieter auswählen", customer_id: "-", aufteilung_aktuell: {} },
    filters: {},
    rows: [],
    totalRow: {},
    summary: [{ label: "Kontostand", value: 0 }, { label: "Bezahlt im Zeitraum", value: 0 }],
  };
  const [data, setData] = useState(initialData);
  const [loadingData, setLoadingData] = useState(false);
  const [loadError, setLoadError] = useState("");
  const loadSeq = useRef(0);
  const { mieter, filters, rows, totalRow, summary } = data;

  // Filter-State
  const _init = window.MK_INITIAL || {};
  const [customer, setCustomer] = useState(_init.customer || "");
  const [fromDate, setFromDate] = useState(_init.from_date || `${new Date().getFullYear()}-01-01`);
  const [toDate, setToDate] = useState(_init.to_date || frappe.datetime.get_today());
  const [mieterStatus, setMieterStatus] = useState("Läuft");
  const [mieterSearch, setMieterSearch] = useState("");
  const [customers, setCustomers] = useState(window.MK_CUSTOMERS || []);
  const [mieterSearching, setMieterSearching] = useState(false);

  async function applyFilters(c, f, t, gruppierenOverride) {
    const seq = ++loadSeq.current;
    setLoadingData(!!c);
    setLoadError("");
    try {
      const nextData = await window.MK_ADAPTER.load(c, f, t, {
        gruppieren: gruppierenOverride ?? gruppieren,
      });
      if (seq === loadSeq.current) {
        setData(nextData || window.MIETERKONTO);
      }
    } catch (err) {
      console.error("mieterkonto load failed", err);
      if (seq === loadSeq.current) {
        setLoadError(err?.message || "Mieterkonto konnte nicht geladen werden.");
      }
    } finally {
      if (seq === loadSeq.current) {
        setLoadingData(false);
      }
    }
  }

  const onCustomerChange = (c) => { setCustomer(c); applyFilters(c, fromDate, toDate); };
  const onFromChange = (f) => { setFromDate(f); applyFilters(customer, f, toDate); };
  const onToChange = (t) => { setToDate(t); applyFilters(customer, fromDate, t); };
  const setRange = (f, tt) => { setFromDate(f); setToDate(tt); applyFilters(customer, f, tt); };

  async function searchMieter(txt, status) {
    setMieterSearching(true);
    try {
      const result = await window.MK_ADAPTER.searchMieter(txt, status);
      setCustomers(result);
    } catch (err) {
      console.error("mieterkonto mieter search failed", err);
      setCustomers([]);
    } finally {
      setMieterSearching(false);
    }
  }

  useEffect(() => {
    const handle = window.setTimeout(() => {
      searchMieter(mieterSearch, mieterStatus);
    }, 220);
    return () => window.clearTimeout(handle);
  }, [mieterSearch, mieterStatus]);

  const onMieterStatusChange = (status) => {
    setMieterStatus(status);
    setMieterSearch("");
    if (customer) {
      setCustomer("");
      applyFilters("", fromDate, toDate);
    }
  };

  const [variant, setVariantLocal] = useState(t.variant);
  const [showCats, setShowCats] = useState(t.showCats);
  const [gruppieren, setGruppieren] = useState(t.gruppieren);

  useEffect(() => {
    if (customer) {
      applyFilters(customer, fromDate, toDate);
    }
  }, []);

  useEffect(() => { setVariantLocal(t.variant); }, [t.variant]);
  useEffect(() => { setShowCats(t.showCats); }, [t.showCats]);
  useEffect(() => { setGruppieren(t.gruppieren); }, [t.gruppieren]);

  const setVariant = (v) => {
    setVariantLocal(v);
    setTweak("variant", v);
  };

  // Filter-Toggle synct mit Tweak
  const setShowCatsBoth = (v) => { setShowCats(v); setTweak("showCats", v); };
  const setGruppierenBoth = (v) => {
    setGruppieren(v);
    setTweak("gruppieren", v);
    applyFilters(customer, fromDate, toDate, v);
  };

  const openLegacyReport = () => {
    if (!customer) {
      frappe.msgprint(__("Bitte zuerst einen Mieter auswählen."));
      return;
    }
    const company = frappe.defaults.get_user_default("Company");
    if (!company) {
      frappe.msgprint(__("Bitte zuerst eine Standard-Firma setzen."));
      return;
    }
    frappe.set_route("query-report", "Mieterkonto", {
      company,
      customer,
      from_date: fromDate,
      to_date: toDate,
      show_kategorien: showCats ? 1 : 0,
      gruppieren_pro_monat: gruppieren ? 1 : 0,
    });
  };

  const printPage = () => openMieterkontoPrintWindow(data, { showCats });

  const exportCsv = () => {
    const csvRows = [
      ["Datum", "Art", "Belegart", "Belegnummern", "Beschreibung", "Miete", "BK", "HK", "G/N", "VZ", "Sonstig", "Gesamt", "Kontostand"],
      ...rows.map((r) => [
        r.datum || "",
        r.art || "",
        r.belegart || "",
        (r.belegnummern && r.belegnummern.length ? r.belegnummern : [r.belegnummer].filter(Boolean)).join(", "),
        r.beschreibung || "",
        r.betrag_miete || 0,
        r.betrag_betriebskosten || 0,
        r.betrag_heizkosten || 0,
        r.betrag_guthaben_nachzahlungen || 0,
        r.betrag_vorauszahlungen || 0,
        r.betrag_sonstiges || 0,
        r.betrag_summe || 0,
        r.kontostand || 0,
      ]),
    ];
    const csv = csvRows.map((row) => row.map(csvCell).join(";")).join("\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const safeCustomer = (customer || "mieterkonto").replace(/[^a-z0-9_-]+/gi, "_");
    link.href = url;
    link.download = `${safeCustomer}_${fromDate}_${toDate}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={`mk-app ${t.printMode ? "is-print-mode" : ""}`}>
      <div className="mk-topbar" data-screen-label="Topbar">
        <div className="mk-topbar-left">
          <h1>Mieterkonto</h1>
          <span className="mk-crumb">Hausverwaltung · Berichte</span>
          <div className="mk-tabs" style={{ marginLeft: 16 }}>
            {[
              { v: "A", l: "Kontoauszug" },
              { v: "B", l: "Verlauf" },
              { v: "C", l: "Dashboard" },
            ].map(({ v, l }) => (
              <button key={v}
                className={`mk-tab ${variant === v ? "is-active" : ""}`}
                onClick={() => setVariant(v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="mk-topbar-actions">
          <button className="mk-btn mk-btn-ghost" onClick={openLegacyReport}>Alte Ansicht</button>
          <button className="mk-btn mk-btn-ghost" onClick={printPage}>Drucken</button>
          <button className="mk-btn mk-btn-ghost" onClick={exportCsv}>Export CSV</button>
          <button className="mk-btn mk-btn-primary" onClick={printPage}>PDF</button>
        </div>
      </div>

      <main className="mk-main" data-screen-label={`Variante ${variant}`}>
        <MieterHeader mieter={mieter} filters={filters} />

        {(loadingData || loadError) && (
          <div className={`mk-load-state ${loadError ? "is-error" : ""}`}>
            {loadError || "Mieterkonto-Daten werden geladen ..."}
          </div>
        )}

        {variant !== "C" && <SummaryCards summary={summary} />}

        <FilterBar
          customer={customer}
          onCustomerChange={onCustomerChange}
          fromDate={fromDate}
          onFromChange={onFromChange}
          toDate={toDate}
          onToChange={onToChange}
          setRange={setRange}
          customers={customers}
          company={filters?.company}
          mieterStatus={mieterStatus}
          onMieterStatusChange={onMieterStatusChange}
          mieterSearch={mieterSearch}
          onMieterSearchChange={setMieterSearch}
          mieterSearching={mieterSearching}
          gruppieren={gruppieren}
          setGruppieren={setGruppierenBoth}
          showCats={showCats}
          setShowCats={setShowCatsBoth}
        />

        {variant === "A" && (
          <VariantA
            rows={rows}
            totalRow={totalRow}
            density={t.density}
            defaultCatsOpen={t.defaultCatsOpen}
            highlightOpen={t.highlightOpen}
            showInlineCats={showCats}
          />
        )}
        {variant === "B" && <VariantB rows={rows} totalRow={totalRow} />}
        {variant === "C" && (
          <VariantC
            rows={rows}
            totalRow={totalRow}
            summary={summary}
            density={t.density}
          />
        )}
      </main>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Layout" />
        <TweakRadio label="Variante" value={t.variant}
          options={["A", "B", "C"]}
          onChange={(v) => setTweak("variant", v)} />
        <p style={{ margin: "0 0 4px", fontSize: 10.5, color: "rgba(41,38,27,.55)", lineHeight: 1.4 }}>
          A · klassischer Kontoauszug ·  B · Verlauf  ·  C · Dashboard
        </p>
        <TweakRadio label="Dichte" value={t.density}
          options={["compact", "regular", "comfy"]}
          onChange={(v) => setTweak("density", v)} />

        <TweakSection label="Inhalt" />
        <TweakToggle label="Kategorien immer offen" value={t.defaultCatsOpen}
          onChange={(v) => setTweak("defaultCatsOpen", v)} />
        <TweakToggle label="Offene Posten hervorheben" value={t.highlightOpen}
          onChange={(v) => setTweak("highlightOpen", v)} />

        <TweakSection label="Vorschau" />
        <TweakToggle label="Print-Modus (A4 quer)" value={t.printMode}
          onChange={(v) => setTweak("printMode", v)} />
      </TweaksPanel>
    </div>
  );
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[;"\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function openMieterkontoPrintWindow(data, options = {}) {
  const doc = buildMieterkontoPrintHtml(data, options);
  const win = window.open("", "_blank", "width=1200,height=800");
  if (!win) {
    frappe.msgprint(__("Druckfenster konnte nicht geöffnet werden. Bitte Pop-ups für diese Seite erlauben."));
    return;
  }
  win.document.open();
  win.document.write(doc);
  win.document.close();
  win.focus();
  let didPrint = false;
  const printOnce = () => {
    if (didPrint) return;
    didPrint = true;
    win.focus();
    win.print();
  };
  win.addEventListener("load", () => win.setTimeout(printOnce, 250), { once: true });
  win.setTimeout(printOnce, 700);
}

function buildMieterkontoPrintHtml(data, options = {}) {
  const { mieter = {}, filters = {}, rows = [], totalRow = {}, summary = [] } = data || {};
  const showCats = !!options.showCats;
  const txRows = rows || [];
  const kontostand = getSummaryItem(summary, "Kontostand");
  const bezahlt = getSummaryItem(summary, "Bezahlt im Zeitraum");
  const openItems = getOpenSummaryItems(summary);
  const title = `Mieterkonto ${mieter.name || ""}`.trim();
  const visibleCols = showCats ? CATS.length + 6 : 8;

  const grouped = [];
  let lastMonth = null;
  const monthEndRow = (month) => txRows
    .filter((r) => !r.is_opening_row && (r.datum || "").slice(0, 7) === month)
    .reduce((best, row) => {
      if (!best) return row;
      return (row.datum || "") > (best.datum || "") ? row : best;
    }, null);

  txRows.forEach((row, index) => {
    if (row.is_opening_row) {
      grouped.push({ type: "opening", row, key: `op-${index}` });
      return;
    }
    const month = (row.datum || "").slice(0, 7);
    if (month && month !== lastMonth) {
      const lastInMonth = monthEndRow(month);
      grouped.push({
        type: "month",
        month,
        endSaldo: lastInMonth ? lastInMonth.kontostand : null,
        key: `m-${month}`,
      });
      lastMonth = month;
    }
    grouped.push({ type: "row", row, key: `r-${index}` });
  });

  const totalForCategory = (category) => txRows
    .filter((r) => !r.is_opening_row)
    .reduce((a, r) => a + Number(r[`betrag_${category.key}`] || 0), 0);
  const totalSoll = txRows
    .filter((r) => !r.is_opening_row && r.art === "Forderung")
    .reduce((a, r) => a + Number(r.betrag_summe || 0), 0);
  const totalHaben = Math.abs(txRows
    .filter((r) => !r.is_opening_row && r.art !== "Forderung")
    .reduce((a, r) => a + Number(r.betrag_summe || 0), 0));

  const tableRows = grouped.map((entry) => {
    if (entry.type === "opening") {
      return `
        <tr class="opening">
          <td>${esc(fmtDate(entry.row.datum))}</td>
          <td>Eröffnung</td>
          <td>—</td>
          <td>Anfangsbestand</td>
          ${showCats ? CATS.map(() => "<td class=\"num muted\">—</td>").join("") : "<td class=\"num muted\">—</td><td class=\"num muted\">—</td>"}
          <td class="num muted">—</td>
          <td class="num saldo">${esc(fmtEUR(entry.row.kontostand))}</td>
        </tr>`;
    }
    if (entry.type === "month") {
      return `
        <tr class="month">
          <td colspan="${visibleCols}">
            <span>${esc(monthLabel(entry.month + "-01"))}</span>
            ${entry.endSaldo != null ? `<strong>Endsaldo Monat: ${esc(fmtEUR(entry.endSaldo))}</strong>` : ""}
          </td>
        </tr>`;
    }
    const row = entry.row;
    const isForderung = row.art === "Forderung";
    const vouchers = Array.isArray(row.belegnummern) && row.belegnummern.length
      ? row.belegnummern
      : row.belegnummer
        ? [row.belegnummer]
        : [];
    return `
      <tr>
        <td>${esc(fmtDate(row.datum))}</td>
        <td>${esc(row.art || "")}</td>
        <td class="voucher">${vouchers.map(esc).join("<br>")}</td>
        <td>
          ${esc(row.beschreibung || "")}
          ${row.offen > 0 ? `<span class="open">offen ${esc(fmtEURsoll(row.offen))} EUR</span>` : ""}
        </td>
        ${showCats ? CATS.map((cat) => {
          const value = Number(row[`betrag_${cat.key}`] || 0);
          return `<td class="num">${Math.abs(value) < 0.01 ? "" : esc(fmtEUR(value, { signed: true }))}</td>`;
        }).join("") : `
          <td class="num">${isForderung && row.betrag_summe ? esc(fmtEURsoll(row.betrag_summe)) : ""}</td>
          <td class="num">${!isForderung && row.betrag_summe ? esc(fmtEURsoll(Math.abs(row.betrag_summe))) : ""}</td>
        `}
        <td class="num">${Math.abs(Number(row.betrag_summe || 0)) < 0.01 ? "" : esc(fmtEUR(Number(row.betrag_summe || 0), { signed: true }))}</td>
        <td class="num saldo">${esc(fmtEUR(row.kontostand))}</td>
      </tr>`;
  }).join("");

  const totalSumme = txRows
    .filter((r) => !r.is_opening_row)
    .reduce((a, r) => a + Number(r.betrag_summe || 0), 0);
  const totalCells = showCats
    ? CATS.map((cat) => {
        const value = totalForCategory(cat);
        return `<td class="num">${Math.abs(value) < 0.01 ? "" : esc(fmtEUR(value, { signed: true }))}</td>`;
      }).join("")
    : `<td class="num">${esc(fmtEURsoll(totalSoll))}</td><td class="num">${esc(fmtEURsoll(totalHaben))}</td>`;
  const totalSummeCell = `<td class="num">${Math.abs(totalSumme) < 0.01 ? "" : esc(fmtEUR(totalSumme, { signed: true }))}</td>`;

  return `<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>${esc(title)}</title>
  <style>
    @page { size: A4 landscape; margin: 9mm 8mm 11mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #111;
      background: #fff;
      font-family: Inter, Arial, Helvetica, sans-serif;
      font-size: 10px;
      line-height: 1.25;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12mm;
      padding-bottom: 4mm;
      margin-bottom: 4mm;
      border-bottom: 1px solid #777;
    }
    .eyebrow {
      font-size: 8px;
      color: #555;
      letter-spacing: .08em;
      text-transform: uppercase;
      margin-bottom: 1.5mm;
    }
    h1 {
      margin: 0 0 1mm;
      font-size: 16px;
      line-height: 1.1;
    }
    .sub { color: #444; font-size: 9px; }
    .period { text-align: right; color: #555; font-size: 8px; }
    .period strong { display: block; color: #111; font-size: 10px; margin-top: 1mm; }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 3mm 7mm;
      margin-top: 3mm;
    }
    .meta div { min-width: 26mm; }
    .label {
      display: block;
      color: #666;
      font-size: 7.5px;
      letter-spacing: .04em;
      text-transform: uppercase;
      margin-bottom: .6mm;
    }
    .value { font-weight: 600; }
    .summary {
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      border: 1px solid #bbb;
      margin-bottom: 4mm;
    }
    .summary .box {
      padding: 2.4mm 3mm;
      border-right: 1px solid #bbb;
      min-height: 14mm;
    }
    .summary .box:last-child { border-right: 0; }
    .summary .amount {
      display: block;
      font-size: 12px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      margin-top: 1mm;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 8.5px;
    }
    thead { display: table-header-group; }
    th {
      background: #f2f2f2;
      color: #444;
      text-align: left;
      font-size: 7.5px;
      letter-spacing: .03em;
      text-transform: uppercase;
      padding: 1.8mm 1.6mm;
      border-bottom: 1px solid #777;
    }
    td {
      vertical-align: top;
      padding: 1.9mm 1.6mm;
      border-bottom: 1px solid #ddd;
      overflow-wrap: anywhere;
    }
    tr { break-inside: avoid; page-break-inside: avoid; }
    th:nth-child(1), td:nth-child(1) { width: 18mm; }
    th:nth-child(2), td:nth-child(2) { width: 21mm; }
    th:nth-child(3), td:nth-child(3) { width: 32mm; }
    th:last-child, td:last-child { width: 24mm; }
    ${showCats ? "th:nth-child(n+5):not(:last-child),td:nth-child(n+5):not(:last-child){width:17mm;}" : "th:nth-child(5),td:nth-child(5),th:nth-child(6),td:nth-child(6),th:nth-child(7),td:nth-child(7){width:21mm;}"}
    .num {
      text-align: right;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    .voucher {
      font-family: "SF Mono", Menlo, Consolas, monospace;
      font-size: 7.2px;
      color: #444;
    }
    .saldo { font-weight: 700; }
    .muted { color: #777; }
    .open {
      display: inline-block;
      margin-top: .8mm;
      padding: .5mm 1.4mm;
      border: 1px solid #777;
      border-radius: 3px;
      font-size: 7px;
      color: #111;
    }
    .month td {
      background: #f7f7f7;
      color: #555;
      padding: 1.4mm 1.6mm;
      font-size: 7.5px;
      border-top: 1px solid #bbb;
      border-bottom: 1px solid #bbb;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .month td {
      display: table-cell;
    }
    .month strong {
      float: right;
      color: #111;
      text-transform: none;
      letter-spacing: 0;
      font-size: 8px;
    }
    .opening td,
    .total td {
      background: #f8f8f8;
      font-weight: 600;
    }
    .total td {
      border-top: 1.5px solid #111;
    }
    @media screen {
      body { padding: 16px; background: #e9e9e9; }
      .page {
        max-width: 297mm;
        min-height: 210mm;
        margin: 0 auto;
        background: #fff;
        padding: 9mm 8mm 11mm;
        box-shadow: 0 8px 30px rgba(0,0,0,.15);
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <header>
      <div>
        <div class="eyebrow">Mieterkonto · ${esc(mieter.customer_id || "")}</div>
        <h1>${esc(mieter.name || "Mieterkonto")}</h1>
        <div class="sub">${esc([mieter.objekt, mieter.einheit].filter(Boolean).join(" · "))}</div>
        <div class="meta">
          <div><span class="label">Vertrag seit</span><span class="value">${esc(fmtDate(mieter.vertrag_seit)) || "—"}</span></div>
          <div><span class="label">Sollmiete aktuell</span><span class="value">${esc(fmtEUR(mieter.sollmiete_aktuell)) || "—"}</span></div>
          <div><span class="label">Firma</span><span class="value">${esc(mieter.firma || filters.company || "—")}</span></div>
          <div><span class="label">Bankkonto</span><span class="value">${esc(mieter.iban_verwendung || "—")}</span></div>
        </div>
      </div>
      <div class="period">
        Berichtszeitraum
        <strong>${esc(fmtDate(filters.from_date))} - ${esc(fmtDate(filters.to_date))}</strong>
      </div>
    </header>

    <section class="summary">
      <div class="box"><span class="label">Kontostand</span><span class="amount">${esc(fmtEUR(kontostand.value || 0))}</span></div>
      <div class="box"><span class="label">Bezahlt im Zeitraum</span><span class="amount">${esc(fmtEUR(bezahlt.value || 0))}</span></div>
      ${openItems.map((item) => `
        <div class="box"><span class="label">${esc(item.label)}</span><span class="amount">${esc(fmtEUR(item.value || 0))}</span></div>
      `).join("")}
    </section>

    <table>
      <thead>
        <tr>
          <th>Datum</th>
          <th>Art</th>
          <th>Beleg</th>
          <th>Beschreibung</th>
          ${showCats ? CATS.map((cat) => `<th class="num">${esc(cat.label)}</th>`).join("") : "<th class=\"num\">Soll</th><th class=\"num\">Haben</th>"}
          <th class="num">Gesamt</th>
          <th class="num">Saldo</th>
        </tr>
      </thead>
      <tbody>
        ${tableRows}
        <tr class="total">
          <td>${esc(fmtDate(totalRow.datum))}</td>
          <td></td>
          <td></td>
          <td>Σ Zeitraum</td>
          ${totalCells}
          ${totalSummeCell}
          <td class="num saldo">${esc(fmtEUR(totalRow.kontostand || 0))}</td>
        </tr>
      </tbody>
    </table>
  </div>
</body>
</html>`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

window.MK_RENDER = function renderMieterkontoWorkflow() {
  const rootEl = document.getElementById("mk-workflow-root") || document.getElementById("root");
  if (!rootEl) return;
  if (window.__MK_REACT_ROOT) {
    try {
      window.__MK_REACT_ROOT.unmount();
    } catch (err) {
      // The previous mount point may already have been replaced by Frappe.
    }
  }
  window.__MK_REACT_ROOT = ReactDOM.createRoot(rootEl);
  window.__MK_REACT_ROOT.render(<App />);
};

window.MK_RENDER();
