// mahn-components.jsx — Formatter + kleine Atome für den Mahnung-Editor.
// Eigene Namespaces (mh*), damit nichts mit dem Mieterkonto-/OP-Report kollidiert.

const { useState: useStateMH, useEffect: useEffectMH, useMemo: useMemoMH, useRef: useRefMH } = React;

// ───────── Formatter ─────────
const fmtEUR_mh = (n, opts = {}) => {
  if (n == null || isNaN(n)) return "—";
  const sign = opts.signed && n > 0 ? "+" : "";
  return sign + new Intl.NumberFormat("de-DE", {
    style: "currency", currency: "EUR",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(n);
};
const fmtNum_mh = (n) =>
  new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
const fmtDate_mh = (s) => {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  return `${d}.${m}.${y}`;
};
const fmtDateLong_mh = (s) => {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  const names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember"];
  return `${parseInt(d, 10)}. ${names[parseInt(m, 10) - 1]} ${y}`;
};
const addDays_mh = (iso, days) => {
  const d = new Date(iso);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const docHref_mh = (doctype, name) =>
  `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;

function handleDocLinkClick_mh(event, doctype, name) {
  event.stopPropagation();
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  frappe.set_route("Form", doctype, name);
}

function DocLinkMH({ doctype, name, className = "", children }) {
  if (!doctype || !name) return null;
  return (
    <a
      href={docHref_mh(doctype, name)}
      className={className}
      onClick={(event) => handleDocLinkClick_mh(event, doctype, name)}
    >
      {children || name}
    </a>
  );
}

function GeneratedDocLinkMH({ doc }) {
  const id = doc?.id || "";
  const desc = doc?.desc || "";
  if (!id) return null;
  if (id.startsWith("/") || /\.pdf(?:$|\?)/i.test(id)) {
    return <a className="mh-sent-doc-id" href={id} target="_blank" rel="noopener noreferrer">{id}</a>;
  }
  const doctype = desc.startsWith("Dunning") ? "Dunning"
    : desc.startsWith("Sales Invoice") ? "Sales Invoice"
    : desc.startsWith("Journal Entry") ? "Journal Entry"
    : desc.startsWith("E-Mail Queue") ? "Email Queue"
    : "";
  return doctype
    ? <DocLinkMH doctype={doctype} name={id} className="mh-sent-doc-id" />
    : <span className="mh-sent-doc-id">{id}</span>;
}

// Platzhalter im Brieftext live ersetzen
const fillPlaceholders_mh = (text, ctx) => {
  if (!text) return "";
  return text.replace(/\{(\w+)\}/g, (m, key) => (ctx[key] != null ? ctx[key] : m));
};

// ───────── Aging-Pill ─────────
function AgePillMH({ days }) {
  const cls = days <= 0 ? "is-future" : days <= 30 ? "is-due" : "is-late";
  const label = days <= 0 ? "fällig" : `${days} T`;
  return <span className={`op-age-pill ${cls}`}>{label}</span>;
}

// ───────── Mahnstufen-Badge ─────────
function StufeBadgeMH({ stufe, label }) {
  return (
    <span className="mh-stufe-badge">
      <span className="mh-stufe-dot" />
      {label || (stufe === 0 ? "Erinnerung" : `M${stufe}`)}
    </span>
  );
}

// ───────── Editor-Feld ─────────
function FieldMH({ label, hint, children, full }) {
  return (
    <div className={`mh-field ${full ? "is-full" : ""}`}>
      <label className="mh-field-label">{label}</label>
      {children}
      {hint && <span className="mh-field-hint">{hint}</span>}
    </div>
  );
}

// ───────── Sektionskopf ─────────
function SectionMH({ n, title, right }) {
  return (
    <div className="mh-section-head">
      <div className="mh-section-title">
        {n != null && <span className="mh-section-n">{n}</span>}
        {title}
      </div>
      {right}
    </div>
  );
}

// ───────── Platzhalter-Chips (in Textfeld einfügen) ─────────
const PLATZHALTER = [
  { token: "{mieter}", label: "Mieter" },
  { token: "{objekt}", label: "Objekt" },
  { token: "{betrag}", label: "Betrag" },
  { token: "{frist}", label: "Frist" },
  { token: "{stufe}", label: "Stufe" },
  { token: "{zweck}", label: "Verwendungszweck" },
];
function PlatzhalterBarMH({ onInsert }) {
  return (
    <div className="mh-ph-bar">
      <span className="mh-ph-bar-label">Platzhalter:</span>
      {PLATZHALTER.map((p) => (
        <button key={p.token} type="button" className="mh-ph-chip"
          title={`„${p.token}" einfügen`} onClick={() => onInsert(p.token)}>
          {p.label}
        </button>
      ))}
    </div>
  );
}

// ───────── Auto-resizing Textarea ─────────
function AutoTextareaMH({ value, onChange, minRows = 3, ...rest }) {
  const ref = useRefMH(null);
  useEffectMH(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }, [value]);
  return (
    <textarea ref={ref} className="mh-textarea" value={value}
      rows={minRows} onChange={(e) => onChange(e.target.value)} {...rest} />
  );
}

// ───────── Toast ─────────
function ToastMH({ message, onClose }) {
  useEffectMH(() => {
    const t = setTimeout(onClose, 2600);
    return () => clearTimeout(t);
  }, []);
  return <div className="mh-toast">{message}</div>;
}

// ───────── Bestätigungs-Overlay nach „Versenden" ─────────
function SentOverlayMH({ data, onClose }) {
  return (
    <div className="mh-sent-backdrop" onClick={onClose}>
      <div className="mh-sent-card" onClick={(e) => e.stopPropagation()}>
        <div className="mh-sent-check">✓</div>
        <h3>{data.draft ? "Mahnung-Draft erstellt" : data.email_queue ? "Mahnung erstellt & E-Mail eingereiht" : "Mahnung erstellt"}</h3>
        <p className="mh-sent-sub">
          {data.vorlage} an {data.mieter} · {data.kanal}
        </p>
        <div className="mh-sent-ledger">
          <div className="mh-sent-ledger-label">Erzeugte Dokumente</div>
          {data.docs.map((d, i) => (
            <div className="mh-sent-doc" key={i}>
              <GeneratedDocLinkMH doc={d} />
              <span className="mh-sent-doc-desc">{d.desc}</span>
              {d.amount != null && <span className="mh-sent-doc-amt">{fmtEUR_mh(d.amount)}</span>}
            </div>
          ))}
        </div>
        <div className="mh-sent-total">
          <span>Gesamtforderung dieser Mahnung</span>
          <strong>{fmtEUR_mh(data.summe)}</strong>
        </div>
        <div className="mh-sent-actions">
          <button className="mk-btn" onClick={onClose}>Schließen</button>
          <a className="mk-btn mk-btn-ghost" href="/app/op-workflow?view=mahnwesen">Zum Mahnwesen</a>
          <button className="mk-btn mk-btn-primary" onClick={onClose}>Nächste Mahnung</button>
        </div>
      </div>
    </div>
  );
}

// ───────── Detail einer bereits gebuchten Mahnung (read-only) ─────────
function PastDunningOverlayMH({ entry, mieterName, onClose, onReuse, onOpenFull }) {
  if (!entry) return null;
  return (
    <div className="mh-past-backdrop" onClick={onClose}>
      <div className="mh-past-card" onClick={(e) => e.stopPropagation()}>
        <div className="mh-past-head">
          <div>
            <div className="mh-past-kicker">Gebuchte Mahnung · {mieterName}</div>
            <h3>{entry.stufe} · {fmtDate_mh(entry.datum)}</h3>
            <div className="mh-past-sub">
              <DocLinkMH doctype="Dunning" name={entry.beleg} className="mh-past-id" />
              <span className="mh-past-status">● {entry.status}</span>
              <span>Versand: {entry.kanal}</span>
              <span>Frist war: {fmtDate_mh(entry.frist)}</span>
            </div>
          </div>
          <button className="op-modal-close" onClick={onClose}>×</button>
        </div>

        <div className="mh-past-body">
          <div className="mh-past-section-label">Gemahnte Posten</div>
          <table className="mh-past-table">
            <thead>
              <tr><th>Beleg</th><th className="num">Betrag</th></tr>
            </thead>
            <tbody>
              {entry.belege.map((b) => (
                <tr key={b.beleg}>
                  <td className="mono"><DocLinkMH doctype="Sales Invoice" name={b.beleg} /></td>
                  <td className="num">{fmtEUR_mh(b.betrag)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="op-preview" style={{ marginTop: 14 }}>
            <div className="op-preview-row">
              <span className="op-preview-key">Hauptforderung</span>
              <span className="op-preview-val">{fmtEUR_mh(entry.hauptforderung)}</span>
            </div>
            {entry.zinsBetrag > 0 && (
              <div className="op-preview-row">
                <span className="op-preview-key">+ Verzugszinsen</span>
                <span className="op-preview-val">{fmtEUR_mh(entry.zinsBetrag)}</span>
              </div>
            )}
            {entry.gebuehr > 0 && (
              <div className="op-preview-row">
                <span className="op-preview-key">+ Mahngebühr</span>
                <span className="op-preview-val">{fmtEUR_mh(entry.gebuehr)}</span>
              </div>
            )}
            <div className="op-preview-row is-total">
              <span className="op-preview-key">Gemahnter Betrag</span>
              <span className="op-preview-val">{fmtEUR_mh(entry.summe)}</span>
            </div>
          </div>

          <div className="mh-past-section-label" style={{ marginTop: 16 }}>Erzeugte Buchungen &amp; Dokumente</div>
          <div className="mh-sent-ledger" style={{ marginBottom: 0 }}>
            {entry.docs.map((d, i) => (
              <div className="mh-sent-doc" key={i}>
                <GeneratedDocLinkMH doc={d} />
                <span className="mh-sent-doc-desc">{d.desc}</span>
                {d.amount != null && <span className="mh-sent-doc-amt">{fmtEUR_mh(d.amount)}</span>}
              </div>
            ))}
          </div>
        </div>

        <div className="mh-past-foot">
          <span className="mh-past-foot-note">Bereits gebucht — schreibgeschützt.</span>
          <div className="mh-past-foot-actions">
            <button className="mk-btn" onClick={() => onReuse && onReuse(entry)}>Als Vorlage übernehmen</button>
            <button className="mk-btn" onClick={() => onOpenFull && onOpenFull(entry)}>Im Editor öffnen →</button>
            <button className="mk-btn mk-btn-primary" onClick={onClose}>Schließen</button>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  fmtEUR_mh, fmtNum_mh, fmtDate_mh, fmtDateLong_mh, addDays_mh, fillPlaceholders_mh,
  AgePillMH, StufeBadgeMH, FieldMH, SectionMH, PlatzhalterBarMH, AutoTextareaMH,
  ToastMH, SentOverlayMH, PastDunningOverlayMH, PLATZHALTER,
  docHref_mh, DocLinkMH, GeneratedDocLinkMH,
});
