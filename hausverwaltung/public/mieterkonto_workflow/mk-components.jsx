// components.jsx — geteilte Atome für den Mieterkonto-Report.
const { useState, useMemo } = React;

// ───────── Formatter ─────────

const fmtEUR = (n, opts = {}) => {
  if (n == null || isNaN(n)) return "";
  const sign = opts.signed && n > 0 ? "+" : "";
  return sign + new Intl.NumberFormat("de-DE", {
    style: "currency", currency: "EUR",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(n);
};

const fmtEURsoll = (n) => {
  if (!n || Math.abs(n) < 0.005) return "";
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(Math.abs(n));
};

const fmtDate = (s) => {
  if (!s) return "";
  const [y, m, d] = s.split("-");
  return `${d}.${m}.${y}`;
};

const fmtDateShort = (s) => {
  if (!s) return "";
  const [, m, d] = s.split("-");
  return `${d}.${m}.`;
};

const monthLabel = (s) => {
  const [y, m] = s.split("-");
  const names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember"];
  return `${names[parseInt(m, 10) - 1]} ${y}`;
};

const CATS = [
  { key: "miete", label: "Miete" },
  { key: "betriebskosten", label: "BK" },
  { key: "heizkosten", label: "HK" },
  { key: "guthaben_nachzahlungen", label: "G/N" },
];

// ───────── Pills ─────────

function ArtPill({ art }) {
  const map = {
    "Forderung": "mk-pill-forderung",
    "Zahlung": "mk-pill-zahlung",
    "Gutschrift": "mk-pill-gutschrift",
    "Abschreibung": "mk-pill-abschreibung",
    "Eröffnung": "mk-pill-eroeffnung",
  };
  return <span className={`mk-pill ${map[art] || ""}`}>{art}</span>;
}

function OpenBadge({ amount }) {
  if (!amount) return null;
  return (
    <span className="mk-pill mk-pill-open" style={{ marginLeft: 8 }}>
      offen · {fmtEURsoll(amount)} €
    </span>
  );
}

// ───────── Filterbar ─────────

function FilterBar({
  customer, onCustomerChange,
  fromDate, onFromChange,
  toDate, onToChange,
  setRange,
  customers, company,
  gruppieren, setGruppieren,
  showCats, setShowCats,
}) {
  const Y = new Date().getFullYear();
  const today = frappe.datetime.get_today();
  const yearStart = `${Y}-01-01`;
  const lastYearFrom = `${Y - 1}-01-01`;
  const lastYearTo = `${Y - 1}-12-31`;
  const last12From = (() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 12);
    return d.toISOString().slice(0, 10);
  })();

  const inputStyle = {
    font: "inherit",
    border: "1px solid var(--ink-3, #d6d3cb)",
    background: "#fff",
    borderRadius: 6,
    padding: "4px 8px",
    minWidth: 0,
  };
  const presetActive = (f, t) => fromDate === f && toDate === t;
  const presetBtn = (label, f, t) => (
    <button
      className={`mk-btn mk-btn-ghost ${presetActive(f, t) ? "is-active" : ""}`}
      onClick={() => setRange(f, t)}
    >
      {label}
    </button>
  );

  return (
    <div className="mk-filterbar">
      <span className="mk-filter">
        <span className="mk-filter-label">Mieter</span>
        <select
          style={{ ...inputStyle, minWidth: 220 }}
          value={customer}
          onChange={(e) => onCustomerChange(e.target.value)}
        >
          <option value="">— Mieter wählen —</option>
          {customers.map((c) => (
            <option key={c.name} value={c.name}>
              {c.customer_name && c.customer_name !== c.name
                ? `${c.customer_name} (${c.name})`
                : c.name}
            </option>
          ))}
        </select>
      </span>

      <span className="mk-filter">
        <span className="mk-filter-label">Von</span>
        <input
          type="date"
          style={inputStyle}
          value={fromDate || ""}
          onChange={(e) => onFromChange(e.target.value)}
        />
      </span>
      <span className="mk-filter">
        <span className="mk-filter-label">Bis</span>
        <input
          type="date"
          style={inputStyle}
          value={toDate || ""}
          onChange={(e) => onToChange(e.target.value)}
        />
      </span>

      <span style={{ display: "inline-flex", gap: 4 }}>
        {presetBtn("Dieses Jahr", yearStart, today)}
        {presetBtn("Vorjahr", lastYearFrom, lastYearTo)}
        {presetBtn("Letzte 12 Mo.", last12From, today)}
      </span>

      {company && <div className="mk-filter-sep" />}
      {company && (
        <span className="mk-filter">
          <span className="mk-filter-label">Firma</span>
          <span className="mk-filter-value">{company}</span>
        </span>
      )}

      <div className="mk-filter-sep" />
      <label className="mk-toggle">
        <input type="checkbox" checked={showCats}
          onChange={(e) => setShowCats(e.target.checked)} />
        Aufteilung nach Miete/BK/HK/G+N
      </label>
      <label className="mk-toggle">
        <input type="checkbox" checked={gruppieren}
          onChange={(e) => setGruppieren(e.target.checked)} />
        Mietabrechnung pro Monat zusammenfassen
      </label>
    </div>
  );
}

// ───────── Mieter-Kopf ─────────

function MieterHeader({ mieter, filters }) {
  return (
    <header className="mk-header">
      <div>
        <div className="mk-header-id">Mieterkonto · {mieter.customer_id}</div>
        <h2>{mieter.name}</h2>
        <div style={{ color: "var(--ink-2)", fontSize: 14 }}>
          {mieter.objekt} · {mieter.einheit}
        </div>
        <div className="mk-header-meta">
          <dl>
            <dt>Vertrag seit</dt>
            <dd>{fmtDate(mieter.vertrag_seit)}</dd>
          </dl>
          <dl>
            <dt>Sollmiete aktuell</dt>
            <dd className="num">{fmtEUR(mieter.sollmiete_aktuell)}</dd>
          </dl>
          <dl>
            <dt>Aufteilung</dt>
            <dd className="num" style={{ fontSize: 12, color: "var(--ink-2)" }}>
              {fmtEURsoll(mieter.aufteilung_aktuell.miete)} M ·{" "}
              {fmtEURsoll(mieter.aufteilung_aktuell.betriebskosten)} BK ·{" "}
              {fmtEURsoll(mieter.aufteilung_aktuell.heizkosten)} HK
            </dd>
          </dl>
          <dl>
            <dt>Verwendungszweck</dt>
            <dd style={{ fontFamily: "ui-monospace, monospace", fontSize: 12 }}>
              {mieter.iban_verwendung}
            </dd>
          </dl>
          <dl>
            <dt>Firma</dt>
            <dd>{mieter.firma}</dd>
          </dl>
        </div>
      </div>
      <div className="mk-period-badge">
        Berichtszeitraum
        <span className="mk-period-range">
          {fmtDate(filters.from_date)}<br />— {fmtDate(filters.to_date)}
        </span>
      </div>
    </header>
  );
}

// ───────── Summary-Cards (für Variante A) ─────────

function SummaryCards({ summary }) {
  const [kontostand, bezahlt, ...offen] = summary;
  const isDue = kontostand.value > 0.01;
  return (
    <div className="mk-summary">
      <div className={`mk-summary-card is-primary ${isDue ? "is-due" : ""}`}>
        <div className="mk-summary-label">Kontostand</div>
        <div className="mk-summary-value num">{fmtEUR(kontostand.value)}</div>
        <div className="mk-summary-sub">
          {isDue ? "Mieter im Rückstand" : kontostand.value < -0.01 ? "Guthaben Mieter" : "ausgeglichen"}
        </div>
      </div>
      <div className="mk-summary-card">
        <div className="mk-summary-label">Bezahlt im Zeitraum</div>
        <div className="mk-summary-value num">{fmtEUR(bezahlt.value)}</div>
      </div>
      {offen.map((s) => (
        <div key={s.label}
          className={`mk-summary-card ${Math.abs(s.value) < 0.01 ? "is-zero" : ""}`}>
          <div className="mk-summary-label">{s.label}</div>
          <div className="mk-summary-value num">{fmtEUR(s.value)}</div>
        </div>
      ))}
    </div>
  );
}

Object.assign(window, {
  fmtEUR, fmtEURsoll, fmtDate, fmtDateShort, monthLabel, CATS,
  ArtPill, OpenBadge, FilterBar, MieterHeader, SummaryCards,
});
