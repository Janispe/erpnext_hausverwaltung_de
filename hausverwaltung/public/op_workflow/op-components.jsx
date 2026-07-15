// op-components.jsx — Atome für Offene-Posten-Report.
const { useState: useStateOP, useMemo: useMemoOP, useEffect: useEffectOP, useRef: useRefOP } = React;

// ───────── Formatter (gleiche Konvention) ─────────

const fmtEUR_op = (n) => {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("de-DE", {
    style: "currency", currency: "EUR",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(n);
};
const fmtDate_op = (s) => {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  return `${d}.${m}.${y}`;
};

const docHref_op = (doctype, name) => {
  if (!doctype || !name) return "#";
  return `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
};

const dunningPdfHref_op = (name) => {
  const params = new URLSearchParams({
    doctype: "Dunning",
    name,
    format: "HV Dunning Letter",
    no_letterhead: "0",
  });
  return `/api/method/frappe.utils.print_format.download_pdf?${params.toString()}`;
};

function handleDocLinkClick_op(event, onOpen) {
  event.stopPropagation();
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  if (!onOpen) return;
  event.preventDefault();
  onOpen();
}

function DocLink_op({ doctype, name, className = "op-link-btn", title, onOpen, children, style }) {
  if (!doctype || !name) return null;
  return (
    <a
      href={docHref_op(doctype, name)}
      className={className}
      title={title || `${doctype} ${name} öffnen`}
      style={style}
      onClick={(event) => handleDocLinkClick_op(event, onOpen || (() => frappe.set_route("Form", doctype, name)))}
    >
      {children || name}
    </a>
  );
}

function DunningPdfLink_op({ name, className = "op-link-btn", children = "PDF" }) {
  if (!name) return null;
  return <a href={dunningPdfHref_op(name)} className={className} target="_blank" rel="noopener noreferrer">{children}</a>;
}

const isIsoDate_op = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s || ""));

const isoToDisplayDate_op = (s) => {
  if (!isIsoDate_op(s)) return "";
  const [y, m, d] = s.split("-");
  return `${d}.${m}.${y}`;
};

const pad2_op = (n) => String(n).padStart(2, "0");

const validIsoDate_op = (y, m, d) => {
  const date = new Date(Date.UTC(y, m - 1, d));
  if (date.getUTCFullYear() !== y) return null;
  if (date.getUTCMonth() !== m - 1) return null;
  if (date.getUTCDate() !== d) return null;
  return `${y}-${pad2_op(m)}-${pad2_op(d)}`;
};

const parseDateInput_op = (raw) => {
  const value = String(raw || "").trim();
  if (!value) return "";

  const iso = value.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) return validIsoDate_op(Number(iso[1]), Number(iso[2]), Number(iso[3]));

  const de = value.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$/);
  if (de) {
    const year = Number(de[3].length === 2 ? `20${de[3]}` : de[3]);
    return validIsoDate_op(year, Number(de[2]), Number(de[1]));
  }

  const compact = value.match(/^(\d{2})(\d{2})(\d{4})$/);
  if (compact) return validIsoDate_op(Number(compact[3]), Number(compact[2]), Number(compact[1]));

  return null;
};

function CalendarIcon_op() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M4.5 1.5v3M11.5 1.5v3M2.5 6h11" />
      <rect x="2.5" y="3.5" width="11" height="10" rx="1.5" />
    </svg>
  );
}

function DateField_op({ value, onChange, ariaLabel }) {
  const [draft, setDraft] = useStateOP(isoToDisplayDate_op(value));
  const [invalid, setInvalid] = useStateOP(false);
  const nativeRef = useRefOP(null);

  useEffectOP(() => {
    setDraft(isoToDisplayDate_op(value));
    setInvalid(false);
  }, [value]);

  const commit = () => {
    const parsed = parseDateInput_op(draft);
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
    setDraft(isoToDisplayDate_op(parsed));
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
    <span className={`op-date-field ${invalid ? "is-invalid" : ""}`}>
      <input
        className="op-date-text"
        type="text"
        inputMode="numeric"
        placeholder="TT.MM.JJJJ"
        value={draft}
        aria-label={ariaLabel}
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
            setDraft(isoToDisplayDate_op(value));
            setInvalid(false);
            e.currentTarget.blur();
          }
        }}
      />
      <button
        type="button"
        className="op-date-picker-button"
        aria-label={`${ariaLabel}: Kalender öffnen`}
        title="Kalender öffnen"
        onClick={openPicker}
      >
        <CalendarIcon_op />
      </button>
      <input
        ref={nativeRef}
        className="op-native-date"
        aria-hidden="true"
        tabIndex={-1}
        type="date"
        value={isIsoDate_op(value) ? value : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </span>
  );
}

// Aging-Buckets gemäß ERPNext range "30, 60, 90, 120"
const AGING_BUCKETS = [
  { key: "b0", label: "nicht fällig", min: -Infinity, max: 0, sub: "0 Tage" },
  { key: "b1", label: "1–30",  min: 1,  max: 30,  sub: "Tage" },
  { key: "b2", label: "31–60", min: 31, max: 60,  sub: "Tage" },
  { key: "b3", label: "61–90", min: 61, max: 90,  sub: "Tage" },
  { key: "b4", label: "> 90",   min: 91, max: Infinity, sub: "Tage" },
];
const bucketOf = (age) => AGING_BUCKETS.find(b => age >= b.min && age <= b.max);

// ───────── Status-Badge ─────────

function StatusBadge({ status }) {
  const map = {
    "Paid":             ["op-status-paid",       "Bezahlt"],
    "Partly Paid":      ["op-status-partly",     "Teilweise bezahlt"],
    "Unpaid":           ["op-status-unpaid",     "Offen"],
    "Overdue":          ["op-status-overdue",    "Überfällig"],
    "Written Off":      ["op-status-writtenoff", "Abgeschrieben"],
    "Partly Paid and Written Off": ["op-status-writtenoff", "Teilweise abgeschr."],
  };
  const [cls, label] = map[status] || ["op-status-unpaid", status || "—"];
  return <span className={`op-status ${cls}`}>{label}</span>;
}

// ───────── Richtung-Badge ─────────

function DirectionBadge({ direction }) {
  const map = {
    "Geld bekommen":              ["is-in",  "Geld bekommen"],
    "Geld bezahlen / erstatten":  ["is-out", "Geld bezahlen"],
    "Abschlag":                   ["is-bal", "Abschlag"],
    "Ausgeglichen":               ["is-bal", "Ausgeglichen"],
  };
  const [cls, label] = map[direction] || ["is-bal", direction];
  return <span className={`op-dir ${cls}`}>{label}</span>;
}

// ───────── Mahnstufen-Anzeige ─────────

function MahnstufeBadge({ stufe }) {
  if (!stufe) return null;
  const dots = Array.from({ length: stufe }, (_, i) => <span key={i} className="op-mahn-dot" />);
  return (
    <span className="op-mahn" title={`Mahnstufe ${stufe}`}>
      {dots}<span style={{ marginLeft: 2 }}>M{stufe}</span>
    </span>
  );
}

// ───────── Aging-Pill ─────────

function AgePill({ age, faellig_am }) {
  if (age == null) return null;
  if (age <= 0) {
    // noch nicht fällig
    return <span className="op-age-pill is-future">fällig {fmtDate_op(faellig_am)}</span>;
  }
  const cls = age > 30 ? "is-late" : "is-due";
  return <span className={`op-age-pill ${cls}`}>{age} Tage</span>;
}

// ───────── Aging-Heatmap-Bar ─────────

function AgingBar({ buckets, totalSum, mini = false }) {
  // buckets: {b0: amount, b1: amount, ...}
  const parts = AGING_BUCKETS.map(b => ({ ...b, val: buckets[b.key] || 0 }));
  const total = totalSum ?? parts.reduce((a, p) => a + p.val, 0);
  if (Math.abs(total) < 0.01) {
    return (
      <div className="op-aging-bars">
        <div className="op-aging-seg is-empty">keine</div>
      </div>
    );
  }
  return (
    <div className="op-aging-bars">
      {parts.map((p, i) => {
        if (Math.abs(p.val) < 0.01) return null;
        const pct = (p.val / total) * 100;
        return (
          <div
            key={p.key}
            className={`op-aging-seg op-aging-seg-${i}`}
            style={{ flex: `${pct} 1 0` }}
            title={`${p.label}: ${fmtEUR_op(p.val)}`}
          >
            {!mini && pct > 8 && fmtEUR_op(p.val).replace("€", "").trim()}
          </div>
        );
      })}
    </div>
  );
}

// ───────── Aging-Strip mit Legende ─────────

function AgingStrip({ buckets }) {
  return (
    <div>
      <AgingBar buckets={buckets} />
      <div className="op-aging-legend">
        {AGING_BUCKETS.map((b) => {
          const v = buckets[b.key] || 0;
          return (
            <span key={b.key}>
              <div style={{ color: "var(--ink-2)", fontWeight: 500 }}>{b.label}</div>
              <div className="num">{Math.abs(v) < 0.01 ? "—" : fmtEUR_op(v)}</div>
            </span>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, {
	fmtEUR_op, fmtDate_op, AGING_BUCKETS, bucketOf,
	StatusBadge, DirectionBadge, MahnstufeBadge, AgePill, AgingBar, AgingStrip, DateField_op,
	docHref_op, dunningPdfHref_op, DocLink_op, DunningPdfLink_op,
});
