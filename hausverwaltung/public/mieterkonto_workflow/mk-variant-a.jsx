// variant-a.jsx — Klassischer Kontoauszug.
// Standard: Soll/Haben/Gesamt/Saldo. Kategorie-Modus: Miete/BK/HK/G+N/VZ/Sonstig/Gesamt/Saldo.

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

function VariantA({ rows, totalRow, density, highlightOpen, showInlineCats }) {
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
  const totalAmount = (row) => Number(row?.betrag_summe || 0);
  const totalForPeriod = () => rows
    .filter((r) => !r.is_opening_row)
    .reduce((a, r) => a + totalAmount(r), 0);
  const colspan = splitCategories ? CATS.length + 6 : 8;

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
            <th className="is-num col-total" style={{ width: 110 }}>Gesamt</th>
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
                  <td className="is-num col-total">—</td>
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
                    </div>
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
                  <td className="is-num col-total">{formatSignedAmount(totalAmount(r))}</td>
                  <td className="is-num col-saldo">{fmtEUR(r.kontostand)}</td>
                </tr>
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
            <td className="is-num col-total">{formatSignedAmount(totalForPeriod())}</td>
            <td className="is-num col-saldo">{fmtEUR(totalRow.kontostand)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

window.VariantA = VariantA;
