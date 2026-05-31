// variant-a.jsx — Klassischer Kontoauszug.
// Soll/Haben/Saldo · Monatsblöcke · Kategorien als ausklappbare Sub-Zeile.

const { useState: useStateA } = React;

function CategoryRow({ row, isOpen }) {
  if (!isOpen) return null;
  return (
    <tr className="mk-row-cats">
      <td colSpan="7">
        <div className="mk-cats">
          {CATS.map((c) => {
            const v = row[`betrag_${c.key}`] || 0;
            return (
              <div className="mk-cat" key={c.key}>
                <span className="mk-cat-label">{c.label}</span>
                <span className={`mk-cat-val ${Math.abs(v) < 0.01 ? "is-zero" : ""}`}>
                  {Math.abs(v) < 0.01 ? "—" : fmtEUR(v, { signed: true })}
                </span>
              </div>
            );
          })}
        </div>
      </td>
    </tr>
  );
}

function CategoryBreakdown({ row, align = "inline" }) {
  const values = CATS
    .map((c) => ({ ...c, value: row[`betrag_${c.key}`] || 0 }))
    .filter((c) => Math.abs(c.value) >= 0.01);

  if (!values.length) return null;

  return (
    <span className={`mk-cat-breakdown mk-cat-breakdown-${align}`}>
      {values.map((c) => (
        <span className="mk-cat-chip" key={c.key}>
          <span className="mk-cat-chip-label">{c.label}</span>
          <span className="mk-cat-chip-val">{fmtEUR(c.value, { signed: true })}</span>
        </span>
      ))}
    </span>
  );
}

function VariantA({ rows, totalRow, density, defaultCatsOpen, highlightOpen, showInlineCats }) {
  const [openIdx, setOpenIdx] = useStateA(() => new Set());
  const isOpen = (i) => defaultCatsOpen || openIdx.has(i);
  const toggle = (i) => {
    setOpenIdx((prev) => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });
  };

  // Monats-Header zwischen verschiedenen Monaten einfügen
  const grouped = [];
  let lastMonth = null;
  rows.forEach((r, i) => {
    if (r.is_opening_row) {
      grouped.push({ type: "opening", row: r, key: `op-${i}` });
      return;
    }
    const month = r.datum.slice(0, 7);
    if (month !== lastMonth) {
      // monatlicher Endsaldo
      const lastInMonth = rows.filter(x => !x.is_opening_row && x.datum.slice(0, 7) === month).slice(-1)[0];
      grouped.push({
        type: "month", month, key: `m-${month}`,
        endSaldo: lastInMonth ? lastInMonth.kontostand : null,
      });
      lastMonth = month;
    }
    grouped.push({ type: "row", row: r, idx: i, key: `r-${i}` });
  });

  return (
    <div className="mk-table-wrap">
      <table className={`mk-table ${density === "compact" ? "is-compact" : density === "comfy" ? "is-comfy" : ""}`}>
        <thead>
          <tr>
            <th style={{ width: 96 }}>Datum</th>
            <th style={{ width: 110 }}>Art</th>
            <th style={{ width: 200 }}>Beleg</th>
            <th>Beschreibung</th>
            <th className="is-num" style={{ width: 110 }}>Soll</th>
            <th className="is-num" style={{ width: 110 }}>Haben</th>
            <th className="is-num" style={{ width: 130 }}>Saldo</th>
          </tr>
        </thead>
        <tbody>
          {grouped.map((g) => {
            if (g.type === "opening") {
              return (
                <tr key={g.key} className="mk-row-opening">
                  <td className="col-date">{fmtDate(g.row.datum)}</td>
                  <td><ArtPill art="Eröffnung" /></td>
                  <td className="col-beleg">—</td>
                  <td className="col-desc">Anfangsbestand</td>
                  <td className="is-num">—</td>
                  <td className="is-num">—</td>
                  <td className="is-num col-saldo">{fmtEUR(g.row.kontostand)}</td>
                </tr>
              );
            }
            if (g.type === "month") {
              return (
                <tr key={g.key} className="mk-month-row">
                  <td colSpan="7">
                    <div className="mk-month-bar">
                      <span>{monthLabel(g.month + "-01")}</span>
                      {g.endSaldo != null && (
                        <span className="mk-month-saldo">
                          Endsaldo Monat: <strong style={{ color: "var(--ink)" }}>{fmtEUR(g.endSaldo)}</strong>
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            }
            const r = g.row;
            const isForderung = r.art === "Forderung";
            const soll = isForderung ? r.betrag_summe : 0;
            const haben = !isForderung ? Math.abs(r.betrag_summe) : 0;
            const showOpen = highlightOpen && r.offen > 0;
            const opn = isOpen(g.idx);
            return (
              <React.Fragment key={g.key}>
                <tr className={showOpen ? "mk-row-open" : ""}>
                  <td className="col-date">{fmtDate(r.datum)}</td>
                  <td><ArtPill art={r.art} /></td>
                  <td className="col-beleg">{r.belegnummer}</td>
                  <td className="col-desc">
                    <div className="mk-desc-line">
                      <span className="mk-desc-main">
                        {r.beschreibung}
                        {showOpen && <OpenBadge amount={r.offen} />}
                      </span>
                      {showInlineCats && <CategoryBreakdown row={r} />}
                    </div>
                    {!defaultCatsOpen && (
                      <button
                        className={`mk-cats-toggle ${opn ? "is-open" : ""}`}
                        onClick={() => toggle(g.idx)}
                      >
                        <span className="mk-chevron">▶</span>
                        Aufteilung nach Miete/BK/HK/G+N
                      </button>
                    )}
                  </td>
                  <td className="is-num col-soll">{soll ? fmtEURsoll(soll) : ""}</td>
                  <td className="is-num col-haben">{haben ? fmtEURsoll(haben) : ""}</td>
                  <td className="is-num col-saldo">{fmtEUR(r.kontostand)}</td>
                </tr>
                <CategoryRow row={r} isOpen={opn} />
              </React.Fragment>
            );
          })}

          {/* Summenzeile */}
          <tr className="mk-row-total">
            <td className="col-date">{fmtDate(totalRow.datum)}</td>
            <td></td>
            <td className="col-beleg"></td>
            <td className="col-desc"><strong>Σ Zeitraum</strong></td>
            <td className="is-num">
              {fmtEURsoll(rows.filter(r => !r.is_opening_row && r.art === "Forderung")
                .reduce((a, r) => a + r.betrag_summe, 0))}
            </td>
            <td className="is-num">
              {fmtEURsoll(Math.abs(rows.filter(r => !r.is_opening_row && r.art !== "Forderung")
                .reduce((a, r) => a + r.betrag_summe, 0)))}
            </td>
            <td className="is-num col-saldo">{fmtEUR(totalRow.kontostand)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

window.VariantA = VariantA;
