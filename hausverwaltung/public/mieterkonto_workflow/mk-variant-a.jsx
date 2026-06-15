// variant-a.jsx — Klassischer Kontoauszug.
// Standard: Soll/Haben/Saldo. Kategorie-Modus: Miete/BK/HK/G+N/Saldo.

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

function categoryAmount(row, category) {
  return row[`betrag_${category.key}`] || 0;
}

function formatSignedAmount(value) {
  return Math.abs(value) < 0.01 ? "" : fmtEUR(value, { signed: true });
}

function monthEndRow(rows, month) {
  return rows
    .filter((r) => !r.is_opening_row && r.datum && r.datum.slice(0, 7) === month)
    .reduce((best, row) => {
      if (!best) return row;
      return row.datum > best.datum ? row : best;
    }, null);
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
      const lastInMonth = monthEndRow(rows, month);
      grouped.push({
        type: "month", month, key: `m-${month}`,
        endSaldo: lastInMonth ? lastInMonth.kontostand : null,
      });
      lastMonth = month;
    }
    grouped.push({ type: "row", row: r, idx: i, key: `r-${i}` });
  });

  const splitCategories = !!showInlineCats;
  const tableClasses = [
    "mk-table",
    density === "compact" ? "is-compact" : density === "comfy" ? "is-comfy" : "",
    splitCategories ? "is-cat-split" : "",
  ].filter(Boolean).join(" ");
  const totalForCategory = (category) => rows
    .filter((r) => !r.is_opening_row)
    .reduce((a, r) => a + categoryAmount(r, category), 0);
  const colspan = splitCategories ? 9 : 7;

  return (
    <div className="mk-table-wrap">
      <table className={tableClasses}>
        <thead>
          <tr>
            <th style={{ width: 92 }}>Datum</th>
            <th style={{ width: 104 }}>Art</th>
            <th style={{ width: 190 }}>Beleg</th>
            <th>Beschreibung</th>
            {splitCategories ? (
              <>
                {CATS.map((c) => (
                  <th key={c.key} className="is-num col-cat-amount">{c.label}</th>
                ))}
              </>
            ) : (
              <>
                <th className="is-num" style={{ width: 110 }}>Soll</th>
                <th className="is-num" style={{ width: 110 }}>Haben</th>
              </>
            )}
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
                  {splitCategories ? (
                    CATS.map((c) => <td key={c.key} className="is-num col-cat-amount">—</td>)
                  ) : (
                    <>
                      <td className="is-num">—</td>
                      <td className="is-num">—</td>
                    </>
                  )}
                  <td className="is-num col-saldo">{fmtEUR(g.row.kontostand)}</td>
                </tr>
              );
            }
            if (g.type === "month") {
              return (
                <tr key={g.key} className="mk-month-row">
                  <td colSpan={colspan}>
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
                  <td className="col-beleg">
                    <VoucherLinks
                      belegart={r.belegart}
                      belegnummer={r.belegnummer}
                      belegnummern={r.belegnummern}
                    />
                  </td>
                  <td className="col-desc">
                    <div className="mk-desc-line">
                      <span className="mk-desc-main">
                        {r.beschreibung}
                        {showOpen && <OpenBadge amount={r.offen} />}
                      </span>
                      {!splitCategories && showInlineCats && <CategoryBreakdown row={r} />}
                    </div>
                    {!splitCategories && !defaultCatsOpen && (
                      <button
                        className={`mk-cats-toggle ${opn ? "is-open" : ""}`}
                        onClick={() => toggle(g.idx)}
                      >
                        <span className="mk-chevron">▶</span>
                        Aufteilung nach Miete/BK/HK/G+N
                      </button>
                    )}
                  </td>
                  {splitCategories ? (
                    CATS.map((c) => (
                      <td key={c.key} className="is-num col-cat-amount">
                        {formatSignedAmount(categoryAmount(r, c))}
                      </td>
                    ))
                  ) : (
                    <>
                      <td className="is-num col-soll">{soll ? fmtEURsoll(soll) : ""}</td>
                      <td className="is-num col-haben">{haben ? fmtEURsoll(haben) : ""}</td>
                    </>
                  )}
                  <td className="is-num col-saldo">{fmtEUR(r.kontostand)}</td>
                </tr>
                {!splitCategories && <CategoryRow row={r} isOpen={opn} />}
              </React.Fragment>
            );
          })}

          {/* Summenzeile */}
          <tr className="mk-row-total">
            <td className="col-date">{fmtDate(totalRow.datum)}</td>
            <td></td>
            <td className="col-beleg"></td>
            <td className="col-desc"><strong>Σ Zeitraum</strong></td>
            {splitCategories ? (
              CATS.map((c) => (
                <td key={c.key} className="is-num col-cat-amount">
                  {formatSignedAmount(totalForCategory(c))}
                </td>
              ))
            ) : (
              <>
                <td className="is-num">
                  {fmtEURsoll(rows.filter(r => !r.is_opening_row && r.art === "Forderung")
                    .reduce((a, r) => a + r.betrag_summe, 0))}
                </td>
                <td className="is-num">
                  {fmtEURsoll(Math.abs(rows.filter(r => !r.is_opening_row && r.art !== "Forderung")
                    .reduce((a, r) => a + r.betrag_summe, 0)))}
                </td>
              </>
            )}
            <td className="is-num col-saldo">{fmtEUR(totalRow.kontostand)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

window.VariantA = VariantA;
