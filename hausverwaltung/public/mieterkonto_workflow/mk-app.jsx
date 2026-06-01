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

  const printPage = () => window.print();

  const exportCsv = () => {
    const csvRows = [
      ["Datum", "Art", "Belegart", "Belegnummer", "Beschreibung", "Miete", "BK", "HK", "G/N", "Summe", "Kontostand"],
      ...rows.map((r) => [
        r.datum || "",
        r.art || "",
        r.belegart || "",
        r.belegnummer || "",
        r.beschreibung || "",
        r.betrag_miete || 0,
        r.betrag_betriebskosten || 0,
        r.betrag_heizkosten || 0,
        r.betrag_guthaben_nachzahlungen || 0,
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

window.MK_RENDER = function renderMieterkontoWorkflow() {
  const rootEl = document.getElementById("root");
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
