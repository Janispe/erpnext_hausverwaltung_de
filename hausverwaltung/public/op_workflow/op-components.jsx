// op-components.jsx — Atome für Offene-Posten-Report.
const { useState: useStateOP, useMemo: useMemoOP } = React;

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
  StatusBadge, DirectionBadge, MahnstufeBadge, AgePill, AgingBar, AgingStrip,
});
