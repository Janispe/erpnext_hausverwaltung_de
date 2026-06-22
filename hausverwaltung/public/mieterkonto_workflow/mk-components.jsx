// components.jsx — geteilte Atome für den Mieterkonto-Report.
const { useState, useMemo, useEffect, useRef } = React;

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

const isIsoDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s || ""));

const isoToDisplayDate = (s) => {
  if (!isIsoDate(s)) return "";
  const [y, m, d] = s.split("-");
  return `${d}.${m}.${y}`;
};

const pad2 = (n) => String(n).padStart(2, "0");

const validIsoDate = (y, m, d) => {
  const date = new Date(Date.UTC(y, m - 1, d));
  if (date.getUTCFullYear() !== y) return null;
  if (date.getUTCMonth() !== m - 1) return null;
  if (date.getUTCDate() !== d) return null;
  return `${y}-${pad2(m)}-${pad2(d)}`;
};

const parseDateInput = (raw) => {
  const value = String(raw || "").trim();
  if (!value) return "";

  const iso = value.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) return validIsoDate(Number(iso[1]), Number(iso[2]), Number(iso[3]));

  const de = value.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$/);
  if (de) {
    const year = Number(de[3].length === 2 ? `20${de[3]}` : de[3]);
    return validIsoDate(year, Number(de[2]), Number(de[1]));
  }

  const compact = value.match(/^(\d{2})(\d{2})(\d{4})$/);
  if (compact) return validIsoDate(Number(compact[3]), Number(compact[2]), Number(compact[1]));

  return null;
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
  { key: "vorauszahlungen", label: "VZ" },
  { key: "sonstiges", label: "Sonstig" },
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

function openVoucher(belegart, belegnummer) {
  if (!belegart || !belegnummer) return;
  frappe.set_route("Form", belegart, belegnummer);
}

function VoucherLink({ belegart, belegnummer, className = "" }) {
  if (!belegnummer) return null;
  if (!belegart) return <span className={className}>{belegnummer}</span>;
  return (
    <button
      type="button"
      className={`mk-voucher-link ${className}`.trim()}
      title={`${belegart} öffnen`}
      onClick={() => openVoucher(belegart, belegnummer)}
    >
      {belegnummer}
    </button>
  );
}

function VoucherLinks({ belegart, belegnummer, belegnummern, className = "" }) {
  const vouchers = Array.isArray(belegnummern) && belegnummern.length
    ? belegnummern
    : belegnummer
      ? [belegnummer]
      : [];
  if (!vouchers.length) return null;
  return (
    <span className={`mk-voucher-list ${className}`.trim()}>
      {vouchers.map((voucher) => (
        <VoucherLink
          key={voucher}
          belegart={belegart}
          belegnummer={voucher}
          className="mk-voucher-list-item"
        />
      ))}
    </span>
  );
}

function mieterOptionLabel(mieter) {
  if (!mieter) return "";
  return mieter.customer_name && mieter.customer_name !== mieter.name
    ? `${mieter.customer_name} (${mieter.name})`
    : mieter.name;
}

function MieterPicker({
  customer,
  customers,
  status,
  searchText,
  searching,
  onStatusChange,
  onSearchChange,
  onCustomerChange,
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const selected = customers.find((c) => c.name === customer);

  useEffect(() => {
    const onPointerDown = (event) => {
      if (!rootRef.current || rootRef.current.contains(event.target)) return;
      setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const choose = (mieter) => {
    onSearchChange(mieter ? mieterOptionLabel(mieter) : "");
    onCustomerChange(mieter?.name || "");
    setOpen(false);
  };

  return (
    <span className="mk-filter mk-mieter-filter" ref={rootRef}>
      <span className="mk-filter-label">Mieter</span>
      <select
        className="mk-field mk-status-select"
        value={status}
        onChange={(e) => onStatusChange(e.target.value)}
      >
        <option value="Läuft">Aktive</option>
        <option value="Alle">Alle</option>
        <option value="Zukunft">Zukünftige</option>
        <option value="Vergangenheit">Vergangene</option>
      </select>
      <div className="mk-combobox">
        <input
          className="mk-field mk-mieter-search"
          type="search"
          value={searchText}
          placeholder={selected ? mieterOptionLabel(selected) : "Mieter suchen"}
          onFocus={(e) => {
            e.target.select();
            setOpen(true);
          }}
          onChange={(e) => {
            onSearchChange(e.target.value);
            setOpen(true);
          }}
        />
        {customer && (
          <button
            type="button"
            className="mk-combobox-clear"
            aria-label="Mieterauswahl löschen"
            onClick={() => {
              onSearchChange("");
              choose(null);
            }}
          >
            ×
          </button>
        )}
        {open && (
          <div className="mk-combobox-menu">
            {searching && <div className="mk-combobox-empty">Suche läuft …</div>}
            {!searching && customers.length === 0 && (
              <div className="mk-combobox-empty">Keine Mieter gefunden</div>
            )}
            {!searching && customers.map((mieter) => (
              <button
                type="button"
                key={`${mieter.name}-${mieter.mietvertrag || ""}`}
                className={`mk-combobox-option ${customer === mieter.name ? "is-selected" : ""}`}
                onClick={() => choose(mieter)}
              >
                <span className="mk-combobox-title">{mieterOptionLabel(mieter)}</span>
                <span className="mk-combobox-meta">
                  {[mieter.status, mieter.wohnung, mieter.immobilie].filter(Boolean).join(" · ")}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </span>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M4.5 1.5v3M11.5 1.5v3M2.5 6h11" />
      <rect x="2.5" y="3.5" width="11" height="10" rx="1.5" />
    </svg>
  );
}

function DateField({ label, value, onChange }) {
  const [draft, setDraft] = useState(isoToDisplayDate(value));
  const [invalid, setInvalid] = useState(false);
  const nativeRef = useRef(null);

  useEffect(() => {
    setDraft(isoToDisplayDate(value));
    setInvalid(false);
  }, [value]);

  const commit = () => {
    const parsed = parseDateInput(draft);
    if (parsed === "") {
      onChange("");
      setInvalid(false);
      return;
    }
    if (!parsed) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setDraft(isoToDisplayDate(parsed));
    if (parsed !== value) onChange(parsed);
  };

  const openPicker = () => {
    const nativeInput = nativeRef.current;
    if (!nativeInput) return;
    if (typeof nativeInput.showPicker === "function") {
      nativeInput.showPicker();
      return;
    }
    nativeInput.focus();
    nativeInput.click();
  };

  return (
    <span className={`mk-filter mk-date-filter ${invalid ? "is-invalid" : ""}`}>
      <span className="mk-filter-label">{label}</span>
      <span className="mk-date-field">
        <input
          className="mk-field mk-date-text"
          type="text"
          inputMode="numeric"
          placeholder="TT.MM.JJJJ"
          value={draft}
          aria-invalid={invalid ? "true" : "false"}
          onChange={(e) => {
            setDraft(e.target.value);
            if (invalid) setInvalid(false);
          }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
              e.currentTarget.blur();
            } else if (e.key === "Escape") {
              setDraft(isoToDisplayDate(value));
              setInvalid(false);
              e.currentTarget.blur();
            }
          }}
        />
        <button
          type="button"
          className="mk-date-picker-button"
          aria-label={`${label}: Kalender öffnen`}
          title="Kalender öffnen"
          onClick={openPicker}
        >
          <CalendarIcon />
        </button>
        <input
          ref={nativeRef}
          className="mk-native-date"
          aria-hidden="true"
          tabIndex={-1}
          type="date"
          value={isIsoDate(value) ? value : ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </span>
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
  mieterStatus, onMieterStatusChange,
  mieterSearch, onMieterSearchChange,
  mieterSearching,
  gruppieren, setGruppieren,
  showCats, setShowCats,
  openScope, setOpenScope,
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
      <MieterPicker
        customer={customer}
        customers={customers}
        status={mieterStatus}
        searchText={mieterSearch}
        searching={mieterSearching}
        onStatusChange={onMieterStatusChange}
        onSearchChange={onMieterSearchChange}
        onCustomerChange={onCustomerChange}
      />

      <DateField label="Von" value={fromDate} onChange={onFromChange} />
      <DateField label="Bis" value={toDate} onChange={onToChange} />

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
      <span className="mk-filter">
        <span className="mk-filter-label">Offene Beträge</span>
        <select
          className="mk-field"
          value={openScope}
          onChange={(e) => setOpenScope(e.target.value)}
        >
          <option value="Zeitraum">Zeitraum</option>
          <option value="Gesamt">Gesamt</option>
        </select>
      </span>
      <label className="mk-toggle">
        <input type="checkbox" checked={showCats}
          onChange={(e) => setShowCats(e.target.checked)} />
        Aufteilung nach Miete/BK/HK/G+N/VZ/Sonstig
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
            <dt>Bankkonto</dt>
            <dd style={{ fontFamily: "ui-monospace, monospace", fontSize: 12 }}>
              {mieter.iban_verwendung || "—"}
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
  const kontostand = getSummaryItem(summary, "Kontostand");
  const bezahlt = getSummaryItem(summary, "Bezahlt im Zeitraum");
  const writtenOff = getSummaryItem(summary, "Abgeschrieben im Zeitraum", null);
  const offen = getOpenSummaryItems(summary);
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
      {writtenOff && (
        <div className="mk-summary-card">
          <div className="mk-summary-label">{writtenOff.label}</div>
          <div className="mk-summary-value num">{fmtEUR(writtenOff.value)}</div>
        </div>
      )}
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

function getSummaryItem(summary, label, fallback = { label, value: 0 }) {
  return (summary || []).find((s) => s.label === label) || fallback;
}

function getOpenSummaryItems(summary) {
  const preferred = ["Miete offen", "BK offen", "HK offen", "G/N offen", "VZ offen", "Sonstig offen"];
  return preferred.map((label) => getOpenSummaryItem(summary, label)).filter(Boolean);
}

function getOpenSummaryItem(summary, label) {
  const items = summary || [];
  return (
    items.find((s) => s.label && s.label.startsWith(`${label} (`))
    || items.find((s) => s.label === label)
    || { label, value: 0 }
  );
}

Object.assign(window, {
  fmtEUR, fmtEURsoll, fmtDate, fmtDateShort, monthLabel, CATS,
  ArtPill, OpenBadge, VoucherLink, VoucherLinks, openVoucher, DateField, FilterBar, MieterHeader, SummaryCards,
  getSummaryItem, getOpenSummaryItems,
});
