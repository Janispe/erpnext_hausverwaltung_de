// variant-c.jsx — Dashboard-Stil: KPI-Kacheln prominent, Tabelle kompakter.

function VariantC({ rows, totalRow, summary, density, sortByWertstellung }) {
  const rowDate = (row) => sortByWertstellung ? (row.wertstellungsdatum || row.datum || "") : (row.datum || "");
  const kontostand = getSummaryItem(summary, "Kontostand").value;
  const bezahlt = getSummaryItem(summary, "Bezahlt im Zeitraum").value;
  const offen = getOpenSummaryItems(summary);
  const totalOffen = offen.reduce((a, s) => a + s.value, 0);
  const offenPosten = rows.filter(r => r.offen > 0).length;
  const isDue = kontostand > 0.01;

  // Forderungen total für Bar-Anteile
  const maxCat = Math.max(...offen.map(o => Math.abs(o.value)), 1);

  return (
    <div>
      <div className="mk-dash-kpis">
        <div className={`mk-kpi-big ${isDue ? "is-due" : kontostand < -0.01 ? "is-credit" : ""}`}>
          <div className="mk-kpi-big-label">Kontostand</div>
          <div>
            <div className="mk-kpi-big-value">{fmtEUR(kontostand)}</div>
            <div className="mk-kpi-big-sub">
              {isDue
                ? `${offenPosten} offene${offenPosten === 1 ? "r Posten" : " Posten"}`
                : kontostand < -0.01 ? "Guthaben des Mieters" : "vollständig ausgeglichen"}
            </div>
          </div>
        </div>
        <div className="mk-kpi-stack">
          <div className="mk-kpi-small">
            <div className="mk-kpi-small-label">Bezahlt im Zeitraum</div>
            <div className="mk-kpi-small-value">{fmtEUR(bezahlt)}</div>
          </div>
          <div className="mk-kpi-small">
            <div className="mk-kpi-small-label">Offene Forderungen</div>
            <div className="mk-kpi-small-value">{fmtEUR(totalOffen)}</div>
          </div>
        </div>
        <div className="mk-kpi-stack">
          <div className="mk-kpi-small">
            <div className="mk-kpi-small-label">Forderungen Zeitraum</div>
            <div className="mk-kpi-small-value">
              {fmtEUR(rows.filter(r => !r.is_opening_row && r.art === "Forderung")
                .reduce((a, r) => a + r.betrag_summe, 0))}
            </div>
          </div>
          <div className="mk-kpi-small">
            <div className="mk-kpi-small-label">Älteste offene Forderung</div>
            <div className="mk-kpi-small-value" style={{ fontSize: 16 }}>
              {(() => {
                const o = rows.filter(r => r.offen > 0).sort((a, b) => rowDate(a).localeCompare(rowDate(b)))[0];
                return o ? fmtDate(rowDate(o)) : "—";
              })()}
            </div>
          </div>
        </div>
      </div>

      {/* Kategorien-Aufteilung als kompakter Block */}
      <div className="mk-kpi-cat-grid">
        {offen.map((s) => {
          const v = s.value;
          const w = Math.min(100, (Math.abs(v) / maxCat) * 100);
          const isOpen = v > 0.01;
          return (
            <div className={`mk-kpi-cat ${isOpen ? "is-open" : ""}`} key={s.label}>
              <div className="mk-kpi-cat-label">{s.label}</div>
              <div className={`mk-kpi-cat-val ${Math.abs(v) < 0.01 ? "is-zero" : ""}`}>
                {Math.abs(v) < 0.01 ? "ausgeglichen" : fmtEUR(v)}
              </div>
              <div className="mk-kpi-cat-bar"><span style={{ width: `${w}%` }} /></div>
            </div>
          );
        })}
      </div>

      <h3 className="mk-section-title" style={{ marginTop: 28 }}>Buchungen</h3>

      <VariantA
        rows={rows}
        totalRow={totalRow}
        density="compact"
        defaultCatsOpen={false}
        highlightOpen={true}
        sortByWertstellung={sortByWertstellung}
      />
    </div>
  );
}

window.VariantC = VariantC;
