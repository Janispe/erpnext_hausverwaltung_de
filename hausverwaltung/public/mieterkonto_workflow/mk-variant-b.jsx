// variant-b.jsx — Timeline-Stil. Chronologische Karten + Saldo-Sparkline.

function SaldoSparkline({ rows }) {
  // Build path from rows (including opening). Width 100%, height fixed.
  const points = rows.map((r, i) => ({ i, v: r.kontostand || 0 }));
  if (points.length < 2) return null;
  const W = 600, H = 80, padY = 8;
  const maxV = Math.max(...points.map(p => p.v), 0);
  const minV = Math.min(...points.map(p => p.v), 0);
  const range = (maxV - minV) || 1;
  const x = (i) => (i / (points.length - 1)) * W;
  const y = (v) => padY + (1 - (v - minV) / range) * (H - 2 * padY);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = path + ` L${W},${y(minV).toFixed(1)} L0,${y(minV).toFixed(1)} Z`;
  const zeroY = y(0);
  const finalV = points[points.length - 1].v;
  const finalDue = finalV > 0.01;

  return (
    <div className="mk-saldo-chart">
      <div className="mk-saldo-chart-head">
        <h3>Saldoverlauf</h3>
        <span className="mk-current">
          Aktueller Saldo: <strong>{fmtEUR(finalV)}</strong>
          <span style={{ color: "var(--ink-3)", marginLeft: 8 }}>
            {finalDue ? "(Rückstand)" : finalV < -0.01 ? "(Guthaben)" : "(ausgeglichen)"}
          </span>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}>
        {/* Nulllinie */}
        <line x1="0" x2={W} y1={zeroY} y2={zeroY}
          stroke="var(--line-strong)" strokeWidth="1" strokeDasharray="3 3" />
        {/* Fläche */}
        <path d={area} fill="var(--accent-soft)" opacity={finalDue ? 1 : 0.4} />
        {/* Linie */}
        <path d={path} fill="none" stroke="var(--ink)" strokeWidth="1.5"
          vectorEffect="non-scaling-stroke" />
        {/* Punkte für Forderungen */}
        {points.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.v)} r="2.5" fill="var(--bg-card)"
            stroke="var(--ink)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
    </div>
  );
}

function VariantB({ rows, totalRow }) {
  // group by month
  const byMonth = {};
  const order = [];
  rows.forEach((r) => {
    if (r.is_opening_row) return;
    const m = r.datum.slice(0, 7);
    if (!byMonth[m]) { byMonth[m] = []; order.push(m); }
    byMonth[m].push(r);
  });

  return (
    <div>
      <SaldoSparkline rows={rows} />
      <div className="mk-timeline">
        {order.map((m) => {
          const items = byMonth[m];
          const endSaldo = items[items.length - 1].kontostand;
          return (
            <div key={m}>
              <div className="mk-tl-month">
                <span className="mk-tl-month-label">{monthLabel(m + "-01")}</span>
                <span className="mk-tl-month-saldo">
                  Endsaldo: <strong>{fmtEUR(endSaldo)}</strong>
                </span>
              </div>
              {items.map((r, idx) => {
                const isOpen = r.offen > 0;
                const cls = isOpen ? "is-open"
                  : r.art === "Forderung" ? "is-forderung"
                  : r.art === "Zahlung" ? "is-zahlung"
                  : r.art === "Gutschrift" ? "is-gutschrift" : "";
                const amount = r.betrag_summe;
                const isOut = amount < 0;
                return (
                  <div key={idx} className={`mk-tl-item ${cls}`}>
                    <div className="mk-tl-item-date">{fmtDateShort(r.datum)}</div>
                    <div className="mk-tl-item-desc">
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <ArtPill art={r.art} />
                        <span>{r.beschreibung}</span>
                        {isOpen && <OpenBadge amount={r.offen} />}
                      </div>
                      <VoucherLinks
                        belegart={r.belegart}
                        belegnummer={r.belegnummer}
                        belegnummern={r.belegnummern}
                        className="mk-tl-beleg"
                      />
                    </div>
                    <div className={`mk-tl-item-amount ${isOut ? "is-out" : ""}`}>
                      {fmtEUR(amount, { signed: true })}
                    </div>
                    <div className="mk-tl-item-saldo">
                      Saldo<strong>{fmtEUR(r.kontostand)}</strong>
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

window.VariantB = VariantB;
