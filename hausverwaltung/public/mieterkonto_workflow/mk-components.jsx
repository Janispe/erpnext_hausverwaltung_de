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

function FilterBar({ filters, gruppieren, setGruppieren, showCats, setShowCats }) {
  return (
    <div className="mk-filterbar">
      <span className="mk-filter">
        <span className="mk-filter-label">Firma</span>
        <span className="mk-filter-value">{filters.company}</span>
      </span>
      <span className="mk-filter">
        <span className="mk-filter-label">Mieter</span>
        <span className="mk-filter-value">{filters.customer}</span>
      </span>
      <span className="mk-filter">
        <span className="mk-filter-label">Zeitraum</span>
        <span className="mk-filter-value">
          {fmtDate(filters.from_date)} — {fmtDate(filters.to_date)}
        </span>
      </span>
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
