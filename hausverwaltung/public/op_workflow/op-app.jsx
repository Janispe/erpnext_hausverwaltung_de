// op-app.jsx — Hauptseite "Noch offene Rechnungen und Forderungen".

const { useState: useStateA0, useMemo: useMemoA0, useEffect: useEffectA0 } = React;

const OP_TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "layout": "flat",
  "showAktion": true,
  "density": "regular",
  "gruppierung": "keine",
  "showObjekt": true
}/*EDITMODE-END*/;

const MODE_LABEL = {
  "Forderungen": "Forderungen",
  "Rechnungen":  "Rechnungen",
  "Beides":      "Beides",
};
const MODE_SUB = {
  "Forderungen": "Mieter schulden uns",
  "Rechnungen":  "Wir schulden Lieferanten",
  "Beides":      "Bilanzielle Gesamtsicht",
};

function OpApp() {
  const [t, setTweak] = useTweaks(OP_TWEAK_DEFAULTS);
  const { partyName } = window.OFFENE_POSTEN;

  // Rows als State — werden bei Backend-Refresh aktualisiert
  const [ALL_ROWS, setAllRows] = React.useState(window.OFFENE_POSTEN.rows);
  const [isLoading, setIsLoading] = React.useState(false);

  React.useEffect(() => {
    const onRefresh = () => setAllRows([...window.OFFENE_POSTEN.rows]);
    const onLoadStart = () => setIsLoading(true);
    const onLoadEnd = () => setIsLoading(false);
    window.addEventListener("op-data-refreshed", onRefresh);
    window.addEventListener("op-loading-start", onLoadStart);
    window.addEventListener("op-loading-end", onLoadEnd);
    return () => {
      window.removeEventListener("op-data-refreshed", onRefresh);
      window.removeEventListener("op-loading-start", onLoadStart);
      window.removeEventListener("op-loading-end", onLoadEnd);
    };
  }, []);

  // Filter-State
  const [mode, setMode] = useStateA0("Forderungen");
  const [sortierung, setSortierung] = useStateA0("Fällig am");
  const [sortDir, setSortDir] = useStateA0("asc"); // asc | desc
  const [showSettled, setShowSettled] = useStateA0(false);
  const [showWrittenOff, setShowWrittenOff] = useStateA0(true);
  const [search, setSearch] = useStateA0("");
  const [activeChip, setActiveChip] = useStateA0(null);
  const [selected, setSelected] = useStateA0(() => new Set());
  const [immoFilter, setImmoFilter] = useStateA0(() => new Set()); // leer = alle
  // Default: aktueller Monat (1. bis letzter Tag)
  const _initNow = new Date();
  const _initPad = (n) => String(n).padStart(2, "0");
  const _initMonthStart = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-01`;
  const _initMonthEnd = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-${_initPad(new Date(_initNow.getFullYear(), _initNow.getMonth() + 1, 0).getDate())}`;
  const [datumVon, setDatumVon] = useStateA0(_initMonthStart);
  const [datumBis, setDatumBis] = useStateA0(_initMonthEnd);

  // Backend-Refresh bei Datums-Änderung (debounced 300ms). First render skip:
  // Bootstrap hat bereits mit aktuellem Monat geladen.
  const _didInitRef = React.useRef(false);
  React.useEffect(() => {
    if (!_didInitRef.current) { _didInitRef.current = true; return; }
    const timer = setTimeout(() => {
      window.OP_ADAPTER.refresh({
        von_faelligkeit: datumVon,
        bis_faelligkeit: datumBis,
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [datumVon, datumBis]);

  // Modal-State
  const [modal, setModal] = useStateA0(null); // { type, row }
  const [toast, setToast] = useStateA0(null);

  const handleAction = async (key, row) => {
    try {
      if (key === "mahnung" || key === "sammelmahnung") setModal({ type: "mahnung", row });
      else if (key === "zahlung_anlegen") setModal({ type: "zahlung", row });
      else if (key === "zuordnen") setModal({ type: "zuordnen", row });
      else if (key === "mieterkonto") {
        window.OP_ACTIONS.openMieterkonto(row);
      }
      else if (key === "abschreiben") {
        const result = await window.OP_ACTIONS.writeOff(row, {
          remarks: `Abschreibung aus OP-Workflow vorbereitet: ${row.belegnummer}`,
        });
        setToast(`Journal Entry Draft erstellt: ${result.journal_entry}`);
      }
      else if (key === "beleg") window.OP_ACTIONS.openBeleg(row);
      else if (key === "kontakt") setToast(`Kontakt: ${window.OFFENE_POSTEN.partyName(row.party)}`);
      else if (key === "notiz") setToast("Notiz-Dialog (mock)");
      else if (key === "stundung") {
        await window.OP_ACTIONS.setStundungComment(row, { grund: "Stundung im OP-Workflow markiert" });
        setToast(`Stundung dokumentiert: ${row.belegnummer}`);
      }
      else if (key === "kl\u00e4rung") setToast(`Status: in Klärung → ${row.belegnummer}`);
      else if (key === "guthaben_auszahlen") setToast(`Auszahlung an ${window.OFFENE_POSTEN.partyName(row.party)} vorbereitet`);
      else if (key === "inkasso") setToast(`Inkasso-Vorgang eröffnet: ${row.belegnummer}`);
      else setToast(`Aktion: ${key}`);
    } catch (err) {
      console.error("op action failed", err);
    }
  };

  // Counts pro Mode (für Tab-Badges)
  const countsByMode = useMemoA0(() => {
    const cnt = { "Forderungen": 0, "Rechnungen": 0, "Beides": 0 };
    ALL_ROWS.forEach((r) => {
      if (Math.abs(r.offen) < 0.01) return;
      cnt[r.art] = (cnt[r.art] || 0) + 1;
      cnt["Beides"] += 1;
    });
    return cnt;
  }, []);

  // Mode-gefilterte Rows
  const modeRows = useMemoA0(() => {
    return ALL_ROWS.filter((r) => mode === "Beides" || r.art === mode);
  }, [mode, ALL_ROWS]);

  // Mahn-Statistik für Banner
  const mahnStats = useMemoA0(() => {
    const reif = modeRows.filter(r => {
      if (r.status === "Written Off") return false;
      if (r.art !== "Forderungen") return false;
      if (r.belegart === "Payment Entry") return false;
      if (r.offen <= 0) return false;
      return r.alter_tage > 0 && (r.mahnstufe || 0) < 4;
    });
    const sum = reif.reduce((a, r) => a + r.offen, 0);
    const partySet = new Set(reif.map(r => r.party));
    const byStufe = { m0: 0, m1: 0, m2: 0, m3: 0 };
    reif.forEach(r => { byStufe[`m${r.mahnstufe || 0}`] = (byStufe[`m${r.mahnstufe || 0}`] || 0) + 1; });
    const mahnreifIds = new Set(reif.map(r => r.belegnummer));
    return { count: reif.length, sum, parties: partySet.size, byStufe, rows: reif, mahnreifIds };
  }, [modeRows]);

  // Verfügbare Immobilien für aktuellen Mode
  const availableImmos = useMemoA0(() => {
    const map = new Map();
    modeRows.forEach((r) => {
      const cc = r.kostenstelle;
      if (!cc) return;
      if (!map.has(cc)) map.set(cc, { cc, label: window.OFFENE_POSTEN.ccLabel[cc] || cc, count: 0 });
      map.get(cc).count += 1;
    });
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [modeRows]);

  // Quick-Filter-Chip-Counts (auf modeRows berechnet)
  const chipCounts = useMemoA0(() => ({
    overdue: modeRows.filter(r => r.alter_tage > 0 && r.status !== "Written Off" && Math.abs(r.offen) > 0.01).length,
    mahnung: modeRows.filter(r => r.mahnstufe && r.mahnstufe > 0).length,
    gt1000:  modeRows.filter(r => Math.abs(r.offen) >= 1000).length,
    guthaben: modeRows.filter(r => r.offen < -0.01).length,
  }), [modeRows]);

  // Voll-Filter angewendet
  const filteredRows = useMemoA0(() => {
    let rows = modeRows;
    if (immoFilter.size > 0) rows = rows.filter((r) => immoFilter.has(r.kostenstelle));
    if (datumVon) rows = rows.filter((r) => (r.faellig_am || "") >= datumVon);
    if (datumBis) rows = rows.filter((r) => (r.faellig_am || "") <= datumBis);
    if (!showSettled) rows = rows.filter((r) => Math.abs(r.offen) > 0.01);
    if (!showWrittenOff) rows = rows.filter((r) => r.status !== "Written Off");
    if (activeChip === "overdue") rows = rows.filter(r => r.alter_tage > 0 && r.status !== "Written Off");
    if (activeChip === "mahnung") rows = rows.filter(r => r.mahnstufe && r.mahnstufe > 0);
    if (activeChip === "gt1000") rows = rows.filter(r => Math.abs(r.offen) >= 1000);
    if (activeChip === "guthaben") rows = rows.filter(r => r.offen < -0.01);
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(r =>
        (partyName(r.party) || "").toLowerCase().includes(q) ||
        (r.belegnummer || "").toLowerCase().includes(q) ||
        (r.party || "").toLowerCase().includes(q) ||
        (r.bemerkungen || "").toLowerCase().includes(q));
    }

    // Sortierung
    const cmp = (a, b) => {
      let r = 0;
      if (sortierung === "Offener Betrag absteigend") r = Math.abs(b.offen) - Math.abs(a.offen);
      else if (sortierung === "Offener Betrag") r = a.offen - b.offen;
      else if (sortierung === "Buchungsdatum") r = (a.buchungsdatum || "").localeCompare(b.buchungsdatum || "");
      else if (sortierung === "Mieter") r = (window.OFFENE_POSTEN.partyName(a.party) || "").localeCompare(window.OFFENE_POSTEN.partyName(b.party) || "");
      else if (sortierung === "Status") r = (a.status || "").localeCompare(b.status || "");
      else if (sortierung === "Richtung: Geld bekommen zuerst")
        r = (a.zahlungsrichtung === "Geld bekommen" ? -1 : 1) - (b.zahlungsrichtung === "Geld bekommen" ? -1 : 1);
      else if (sortierung === "Richtung: Geld bezahlen zuerst")
        r = (a.zahlungsrichtung === "Geld bezahlen / erstatten" ? -1 : 1) - (b.zahlungsrichtung === "Geld bezahlen / erstatten" ? -1 : 1);
      else if (sortierung === "Immobilie") {
        const ka = window.OFFENE_POSTEN.ccLabel[a.kostenstelle] || a.kostenstelle || "";
        const kb = window.OFFENE_POSTEN.ccLabel[b.kostenstelle] || b.kostenstelle || "";
        r = ka.localeCompare(kb);
      }
      else if (sortierung === "Älteste zuerst" || sortierung === "Alter") r = (b.alter_tage || 0) - (a.alter_tage || 0);
      else /* Fällig am */ r = (a.faellig_am || "").localeCompare(b.faellig_am || "");

      // Tiebreaker für deterministische Reihenfolge
      if (r === 0) r = (a.faellig_am || "").localeCompare(b.faellig_am || "");
      if (r === 0) r = (a.belegnummer || "").localeCompare(b.belegnummer || "");
      return sortDir === "desc" ? -r : r;
    };
    const sorted = [...rows].sort(cmp);
    return sorted;
  }, [modeRows, immoFilter, datumVon, datumBis, showSettled, showWrittenOff, activeChip, search, sortierung, sortDir]);

  // Aggregate für Stats + Aging
  const stats = useMemoA0(() => {
    const positiveOpen = filteredRows.filter(r => r.offen > 0 && r.status !== "Written Off");
    const summe = positiveOpen.reduce((a, r) => a + r.offen, 0);
    const ueberfaellig = positiveOpen.filter(r => r.alter_tage > 0).reduce((a, r) => a + r.offen, 0);
    const guthabenSum = filteredRows.filter(r => r.offen < -0.01).reduce((a, r) => a + Math.abs(r.offen), 0);

    const parties = new Set(positiveOpen.map(r => r.party));
    const oldest = positiveOpen.reduce((max, r) => Math.max(max, r.alter_tage || 0), 0);

    // Aging-Buckets
    const buckets = { b0: 0, b1: 0, b2: 0, b3: 0, b4: 0 };
    positiveOpen.forEach((r) => {
      const b = bucketOf(r.alter_tage);
      if (b) buckets[b.key] += r.offen;
    });
    return { summe, ueberfaellig, guthabenSum, parties: parties.size, oldest, buckets };
  }, [filteredRows]);

  // Selection: Bulk-Aktionen
  const selectableIds = useMemoA0(() => new Set(filteredRows.filter(r => r.can_write_off).map(r => r.belegnummer)), [filteredRows]);
  const selectedRows = useMemoA0(() => filteredRows.filter(r => selected.has(r.belegnummer)), [filteredRows, selected]);
  const selectedSum = selectedRows.reduce((a, r) => a + r.offen, 0);
  const toggleSel = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const toggleSelAll = () => {
    if (selected.size === selectableIds.size) setSelected(new Set());
    else setSelected(new Set(selectableIds));
  };

  // Generische Gruppierung: nach Mieter oder Immobilie
  const grouped = useMemoA0(() => {
    if (t.gruppierung === "keine") return null;
    const keyFn = t.gruppierung === "objekt"
      ? (r) => r.kostenstelle || "—"
      : (r) => r.party;
    const labelFn = t.gruppierung === "objekt"
      ? (k) => window.OFFENE_POSTEN.ccLabel[k] || k
      : (k) => partyName(k);
    const map = new Map();
    filteredRows.forEach((r) => {
      const k = keyFn(r);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(r);
    });
    return [...map.entries()].map(([key, rows]) => {
      const sum = rows.reduce((a, r) => a + r.offen, 0);
      const overdue = rows.reduce((a, r) => a + (r.alter_tage > 0 ? r.offen : 0), 0);
      const buckets = { b0: 0, b1: 0, b2: 0, b3: 0, b4: 0 };
      rows.forEach(r => {
        if (r.offen > 0) {
          const b = bucketOf(r.alter_tage);
          if (b) buckets[b.key] += r.offen;
        }
      });
      const maxAge = rows.reduce((m, r) => Math.max(m, r.alter_tage || 0), 0);
      const maxMahn = rows.reduce((m, r) => Math.max(m, r.mahnstufe || 0), 0);
      const partySet = new Set(rows.map(r => r.party));
      return {
        key,
        label: labelFn(key),
        subLabel: t.gruppierung === "objekt"
          ? `${partySet.size} ${partySet.size === 1 ? "Mieter" : "Mieter"} · ${rows.length} ${rows.length === 1 ? "Posten" : "Posten"}`
          : `${key} · ${rows.length} ${rows.length === 1 ? "Posten" : "Posten"}`,
        rows, sum, overdue, buckets, maxAge, maxMahn,
      };
    }).sort((a, b) => b.sum - a.sum);
  }, [filteredRows, t.gruppierung]);

  return (
    <div className="mk-app">
      <div className="mk-topbar" data-screen-label="Topbar">
        <div className="mk-topbar-left">
          <h1>
            Noch offene Rechnungen und Forderungen
            {isLoading && (
              <span style={{ display: "inline-block", marginLeft: 10, width: 14, height: 14, border: "2px solid #ccc", borderTopColor: "#666", borderRadius: "50%", animation: "op-spin 0.8s linear infinite", verticalAlign: "middle" }} />
            )}
          </h1>
          <span className="mk-crumb">Hausverwaltung · Berichte</span>
        </div>
        <div className="mk-topbar-actions">
          <a className="mk-btn mk-btn-ghost" href="/app/mieterkonto-workflow">← Mieterkonto</a>
          <button className="mk-btn mk-btn-ghost" onClick={() => window.print()}>Drucken</button>
          <button className="mk-btn mk-btn-ghost">Export CSV</button>
          <button className="mk-btn mk-btn-primary">Sammelmahnung</button>
        </div>
      </div>

      <main className="mk-main" data-screen-label={`Mode ${mode}`}>
        {/* Mode-Switch */}
        <div className="op-mode-bar">
          <div className="op-mode-tabs">
            {["Forderungen", "Rechnungen", "Beides"].map((m) => (
              <button key={m}
                className={`op-mode-tab ${mode === m ? "is-active" : ""}`}
                onClick={() => { setMode(m); setSelected(new Set()); setActiveChip(null); }}>
                <span>{MODE_LABEL[m]}</span>
                <span className="op-count">{countsByMode[m]}</span>
              </button>
            ))}
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "right" }}>
            <div>{MODE_SUB[mode]}</div>
            <div style={{ marginTop: 2 }}>Stichtag: {fmtDate_op(window.OFFENE_POSTEN.TODAY)}</div>
          </div>
        </div>

        {/* Mahn-Banner (kompakt, eine Zeile) */}
        {mahnStats.count > 0 && mode !== "Rechnungen" && (
          <div className="op-mahn-banner">
            <span className="op-mahn-badge">{mahnStats.count}</span>
            <span className="op-mahn-banner-headline">
              {mahnStats.count} Posten <strong>mahnreif</strong>
            </span>
            <span className="op-mahn-banner-meta">
              bei <strong>{mahnStats.parties}</strong> {mahnStats.parties === 1 ? "Mieter" : "Mietern"} · Σ <strong>{fmtEUR_op(mahnStats.sum)}</strong>
            </span>
            <span className="op-mahn-stufes">
              {mahnStats.byStufe.m0 > 0 && <span>→ ZE <strong>{mahnStats.byStufe.m0}</strong></span>}
              {mahnStats.byStufe.m1 > 0 && <span>→ M1 <strong>{mahnStats.byStufe.m1}</strong></span>}
              {mahnStats.byStufe.m2 > 0 && <span>→ M2 <strong>{mahnStats.byStufe.m2}</strong></span>}
              {mahnStats.byStufe.m3 > 0 && <span>→ Letzte <strong>{mahnStats.byStufe.m3}</strong></span>}
            </span>
            <span className="op-mahn-banner-spacer" />
            <button className="op-mahn-banner-secondary"
              onClick={() => setActiveChip(activeChip === "overdue" ? null : "overdue")}>
              {activeChip === "overdue" ? "Filter zurücksetzen" : "Nur diese zeigen"}
            </button>
            <button className="op-mahn-banner-cta"
              onClick={() => { setSelected(new Set(mahnStats.rows.map(r => r.belegnummer))); setModal({ type: "sammelmahnung", rows: mahnStats.rows }); }}>
              Sammelmahnung erstellen →
            </button>
          </div>
        )}

        {/* Stats + Aging */}
        <div className="op-stats">
          <div className={`op-stat is-primary`}>
            <div className="op-stat-label">Offen gesamt</div>
            <div className="op-stat-value">{fmtEUR_op(stats.summe)}</div>
            <div className="op-stat-sub">
              {filteredRows.filter(r => r.offen > 0 && r.status !== "Written Off").length} Posten ·{" "}
              {stats.parties} {mode === "Rechnungen" ? "Lieferanten" : "Mieter"}
            </div>
          </div>
          <div className="op-stat">
            <div className="op-stat-label">davon überfällig</div>
            <div className="op-stat-value" style={{ color: "var(--accent)" }}>{fmtEUR_op(stats.ueberfaellig)}</div>
            <div className="op-stat-sub">
              {((stats.ueberfaellig / Math.max(stats.summe, 1)) * 100).toFixed(0)} % des Offen-Saldos
            </div>
          </div>
          <div className="op-stat">
            <div className="op-stat-label">Älteste Forderung</div>
            <div className="op-stat-value">{stats.oldest}<span style={{ fontSize: 14, color: "var(--ink-3)", marginLeft: 4 }}>Tage</span></div>
          </div>
          <div className="op-stat">
            <div className="op-stat-label">Guthaben (auszuzahlen)</div>
            <div className="op-stat-value">{stats.guthabenSum > 0 ? fmtEUR_op(stats.guthabenSum) : "—"}</div>
          </div>
          <div className="op-aging-strip">
            <div className="op-stat-label">Aging nach Fälligkeit</div>
            <AgingStrip buckets={stats.buckets} />
          </div>
        </div>

        {/* Filter-Zeile: Immobilie + Datum */}
        <FilterRow
          availableImmos={availableImmos}
          immoFilter={immoFilter}
          setImmoFilter={setImmoFilter}
          datumVon={datumVon}
          datumBis={datumBis}
          setDatumVon={setDatumVon}
          setDatumBis={setDatumBis}
        />

        {/* Toolbar */}
        <div className="op-toolbar">
          <div className="op-chips">
            <button className={`op-chip ${activeChip === null ? "is-active" : ""}`} onClick={() => setActiveChip(null)}>
              Alle <span className="op-chip-count">{filteredRows.length}</span>
            </button>
            <button className={`op-chip ${activeChip === "overdue" ? "is-active" : ""}`} onClick={() => setActiveChip(activeChip === "overdue" ? null : "overdue")}>
              Überfällig <span className="op-chip-count">{chipCounts.overdue}</span>
            </button>
            <button className={`op-chip ${activeChip === "mahnung" ? "is-active" : ""}`} onClick={() => setActiveChip(activeChip === "mahnung" ? null : "mahnung")}>
              Im Mahnlauf <span className="op-chip-count">{chipCounts.mahnung}</span>
            </button>
            <button className={`op-chip ${activeChip === "gt1000" ? "is-active" : ""}`} onClick={() => setActiveChip(activeChip === "gt1000" ? null : "gt1000")}>
              ≥ 1.000 € <span className="op-chip-count">{chipCounts.gt1000}</span>
            </button>
            <button className={`op-chip ${activeChip === "guthaben" ? "is-active" : ""}`} onClick={() => setActiveChip(activeChip === "guthaben" ? null : "guthaben")}>
              Guthaben <span className="op-chip-count">{chipCounts.guthaben}</span>
            </button>
            <label className="mk-toggle" style={{ marginLeft: 10 }}>
              <input type="checkbox" checked={showWrittenOff} onChange={(e) => setShowWrittenOff(e.target.checked)} />
              Abgeschriebene
            </label>
            <label className="mk-toggle">
              <input type="checkbox" checked={showSettled} onChange={(e) => setShowSettled(e.target.checked)} />
              Auch ausgeglichene
            </label>
          </div>
          <div className="op-toolbar-right">
            <input className="op-search" placeholder="Mieter, Beleg oder Bemerkung suchen…"
              value={search} onChange={(e) => setSearch(e.target.value)} />
            <select className="op-sort-select" value={sortierung} onChange={(e) => { setSortierung(e.target.value); setSortDir("asc"); }}>
              <option>Fällig am</option>
              <option>Buchungsdatum</option>
              <option>Älteste zuerst</option>
              <option>Offener Betrag absteigend</option>
              <option>Mieter</option>
              <option>Immobilie</option>
              <option>Status</option>
              <option>Richtung: Geld bekommen zuerst</option>
              <option>Richtung: Geld bezahlen zuerst</option>
            </select>
            <button className="mk-btn mk-btn-ghost" title="Richtung umkehren"
              onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")}
              style={{ padding: "5px 10px", fontSize: 12 }}>
              {sortDir === "asc" ? "↑ aufst." : "↓ abst."}
            </button>
          </div>
        </div>

        {/* Bulk-Bar (nur wenn ausgewählt) */}
        {selected.size > 0 && (
          <div className="op-bulkbar">
            <div className="op-bulkbar-left">
              <span className="op-bulkbar-count">{selected.size} ausgewählt</span>
              <span className="op-bulkbar-sep" />
              <span className="op-bulkbar-sum">Σ offen: <strong>{fmtEUR_op(selectedSum)}</strong></span>
            </div>
            <div className="op-bulkbar-actions">
              <button className="op-bulk-btn" onClick={() => setSelected(new Set())}>Auswahl aufheben</button>
              <button className="op-bulk-btn">Mahnung erstellen</button>
              <button className="op-bulk-btn is-primary">Ausgewählte abschreiben</button>
            </div>
          </div>
        )}

        {/* Body — gruppiert oder flach */}
        {filteredRows.length === 0 ? (
          <div className="op-empty">
            <strong>Keine offenen Posten in dieser Auswahl.</strong>
            Filter ändern oder „Auch ausgeglichene anzeigen" aktivieren.
          </div>
        ) : t.gruppierung !== "keine" ? (
          <GroupedView groups={grouped} selected={selected} toggleSel={toggleSel} selectableIds={selectableIds} mode={mode} gruppierung={t.gruppierung} showObjekt={t.showObjekt} onAction={handleAction} />
        ) : (
          <FlatTable
            rows={filteredRows}
            selected={selected}
            toggleSel={toggleSel}
            selectableIds={selectableIds}
            toggleSelAll={toggleSelAll}
            mode={mode}
            showAktion={t.showAktion}
            showObjekt={t.showObjekt}
            sortierung={sortierung}
            sortDir={sortDir}
            onSort={(col) => {
              if (sortierung === col) setSortDir(sortDir === "asc" ? "desc" : "asc");
              else { setSortierung(col); setSortDir("asc"); }
            }}
            onAction={handleAction}
            mahnreifIds={mahnStats.mahnreifIds}
          />
        )}

        {/* Footer-Total */}
        <div className="op-footer-total">
          <div className="op-footer-total-label">
            Σ {filteredRows.length} Posten in Auswahl
          </div>
          <div className="op-footer-total-value">
            {fmtEUR_op(filteredRows.reduce((a, r) => a + r.offen, 0))}
          </div>
        </div>
      </main>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Gruppierung" />
        <TweakRadio label="Gruppiert nach" value={t.gruppierung}
          options={["keine", "mieter", "objekt"]}
          onChange={(v) => setTweak("gruppierung", v)} />
        <p style={{ margin: "0 0 4px", fontSize: 10.5, color: "rgba(41,38,27,.55)", lineHeight: 1.4 }}>
          Mieter · pro Partei · Objekt · pro Immobilie
        </p>
        <TweakSection label="Layout" />
        <TweakRadio label="Dichte" value={t.density}
          options={["compact", "regular", "comfy"]}
          onChange={(v) => setTweak("density", v)} />
        <TweakSection label="Spalten" />
        <TweakToggle label="Immobilie anzeigen" value={t.showObjekt}
          onChange={(v) => setTweak("showObjekt", v)} />
        <TweakToggle label="Aktion-Spalte (Abschreiben)" value={t.showAktion}
          onChange={(v) => setTweak("showAktion", v)} />
      </TweaksPanel>

      {/* Modals */}
      {modal?.type === "mahnung" && <MahnungModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Mahnung-Draft erstellt: ${result.dunning}`); }} />}
      {modal?.type === "sammelmahnung" && <SammelmahnungModal rows={modal.rows} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`${(result.created || []).length} Mahnung-Drafts erstellt`); }} />}
      {modal?.type === "zahlung" && <ZahlungModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Payment Entry Draft erstellt: ${result.payment_entry}`); }} />}
      {modal?.type === "zuordnen" && <ZuordnenModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Payment Reconciliation Draft erstellt: ${result.payment_reconciliation}`); }} />}
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

// ───────── Flache Tabelle ─────────

function FlatTable({ rows, selected, toggleSel, selectableIds, toggleSelAll, mode, showAktion, showObjekt, sortierung, sortDir, onSort, onAction, mahnreifIds }) {
  const allChecked = selectableIds.size > 0 && selected.size === selectableIds.size;
  const someChecked = selected.size > 0 && !allChecked;
  const SortableTh = ({ col, label, style, className = "" }) => {
    const active = sortierung === col;
    const ind = active ? (sortDir === "asc" ? "▲" : "▼") : "◇";
    return (
      <th
        style={style}
        className={`is-sortable ${active ? "is-sorted" : ""} ${className}`}
        onClick={() => onSort(col)}
        title={`Nach ${label} sortieren`}
      >
        {label}<span className="op-sort-ind">{ind}</span>
      </th>
    );
  };
  return (
    <div className="op-table-wrap">
      <table className="op-table">
        <thead>
          <tr>
            <th className="is-check">
              <input type="checkbox" checked={allChecked}
                ref={(el) => el && (el.indeterminate = someChecked)}
                onChange={toggleSelAll}
                disabled={selectableIds.size === 0} />
            </th>
            <SortableTh col="Fällig am" label="Fällig am" style={{ width: 100 }} />
            <SortableTh col="Alter" label="Alter" style={{ width: 80 }} />
            <SortableTh col="Mieter" label={mode === "Rechnungen" ? "Lieferant" : "Mieter"} style={{ minWidth: 200 }} />
            {showObjekt && <SortableTh col="Immobilie" label="Immobilie" style={{ width: 140 }} />}
            <th style={{ width: 170 }}>Beleg</th>
            <th>Bemerkung</th>
            <SortableTh col="Status" label="Status" style={{ width: 120 }} />
            <th className="is-num" style={{ width: 120 }}>Rechnungsbetrag</th>
            <th className="is-num" style={{ width: 100 }}>Bezahlt</th>
            <SortableTh col="Offener Betrag absteigend" label="Offen" style={{ width: 130 }} className="is-num" />
            {showAktion && <th style={{ width: 200 }}>Aktion</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sel = selected.has(r.belegnummer);
            const isNeg = r.offen < -0.01;
            const writtenOff = r.status === "Written Off";
            const mahnreif = mahnreifIds && mahnreifIds.has(r.belegnummer);
            return (
              <tr key={r.belegnummer + r.party} className={`${sel ? "is-selected" : ""} ${writtenOff ? "is-written-off" : ""} ${mahnreif ? "is-mahnreif" : ""}`}>
                <td className="col-check">
                  <input type="checkbox" checked={sel}
                    disabled={!r.can_write_off}
                    onChange={() => toggleSel(r.belegnummer)} />
                </td>
                <td className="col-date">{fmtDate_op(r.faellig_am)}</td>
                <td><AgePill age={r.alter_tage} faellig_am={r.faellig_am} /></td>
                <td className="col-party">
                  {window.OFFENE_POSTEN.partyName(r.party)}
                  <span className="op-party-id">{r.party}</span>
                </td>
                {showObjekt && (
                  <td style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
                    {window.OFFENE_POSTEN.ccLabel[r.kostenstelle] || r.kostenstelle || "—"}
                  </td>
                )}
                <td className="col-beleg">
                  {r.belegnummer}
                  <span className="op-beleg-art">{r.belegart}</span>
                </td>
                <td className="col-bemerk">
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span>{r.bemerkungen}</span>
                    {r.mahnstufe ? <MahnstufeBadge stufe={r.mahnstufe} /> : null}
                  </div>
                </td>
                <td><StatusBadge status={r.status} /></td>
                <td className="is-num">{fmtEUR_op(r.rechnungsbetrag)}</td>
                <td className="is-num" style={{ color: "var(--ink-3)" }}>
                  {r.bezahlt > 0.01 ? fmtEUR_op(r.bezahlt) : "—"}
                </td>
                <td className={`is-num col-offen ${isNeg ? "is-negative" : ""}`}>
                  {fmtEUR_op(r.offen)}
                </td>
                {showAktion && (
                  <td style={{ position: "relative", textAlign: "right" }}>
                    <ActionCell row={r} onAction={onAction} />
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ───────── Gruppierte Ansicht ─────────

function GroupedView({ groups, selected, toggleSel, selectableIds, mode, gruppierung, showObjekt, onAction }) {
  const [openSet, setOpenSet] = useStateA0(() => new Set(groups.map(g => g.key)));
  const toggle = (p) => {
    setOpenSet(prev => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });
  };
  return (
    <div>
      {groups.map((g) => {
        const open = openSet.has(g.key);
        return (
          <div key={g.key} className={`op-group ${open ? "is-open" : ""}`}>
            <div className="op-group-head" onClick={() => toggle(g.key)}>
              <span className="op-group-chevron">▶</span>
              <div className="op-group-party">
                <span className="op-group-party-name">
                  {gruppierung === "objekt" && <span style={{ color: "var(--ink-3)", fontWeight: 400, marginRight: 6 }}>🏠</span>}
                  {g.label}
                </span>
                <span className="op-group-party-id">{g.subLabel}</span>
              </div>
              <div className="op-group-aging">
                <AgingBar buckets={g.buckets} mini={true} />
              </div>
              <div className="op-group-stat">
                Ältester
                <strong>{g.maxAge} d</strong>
              </div>
              <div className="op-group-stat">
                Mahnstufe
                <strong>{g.maxMahn || "—"}</strong>
              </div>
              <div className={`op-group-stat ${g.overdue > 0.01 ? "is-overdue" : ""}`}>
                Σ Offen
                <strong>{fmtEUR_op(g.sum)}</strong>
              </div>
            </div>
            {open && (
              <div className="op-group-body">
                <table className="op-table">
                  <tbody>
                    {g.rows.map((r) => {
                      const sel = selected.has(r.belegnummer);
                      const isNeg = r.offen < -0.01;
                      const writtenOff = r.status === "Written Off";
                      return (
                        <tr key={r.belegnummer} className={`${sel ? "is-selected" : ""} ${writtenOff ? "is-written-off" : ""}`}>
                          <td className="col-check" style={{ width: 32 }}>
                            <input type="checkbox" checked={sel}
                              disabled={!r.can_write_off}
                              onChange={() => toggleSel(r.belegnummer)} />
                          </td>
                          <td className="col-date" style={{ width: 100 }}>{fmtDate_op(r.faellig_am)}</td>
                          <td style={{ width: 80 }}><AgePill age={r.alter_tage} faellig_am={r.faellig_am} /></td>
                          <td className="col-beleg" style={{ width: 170 }}>
                            {r.belegnummer}<span className="op-beleg-art">{r.belegart}</span>
                          </td>
                          {gruppierung !== "objekt" && showObjekt && (
                            <td style={{ width: 130, fontSize: 12.5, color: "var(--ink-2)" }}>
                              {window.OFFENE_POSTEN.ccLabel[r.kostenstelle] || "—"}
                            </td>
                          )}
                          {gruppierung === "objekt" && (
                            <td className="col-party" style={{ width: 200, fontSize: 12.5 }}>
                              {window.OFFENE_POSTEN.partyName(r.party)}
                              <span className="op-party-id">{r.party}</span>
                            </td>
                          )}
                          <td className="col-bemerk">
                            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                              <span>{r.bemerkungen}</span>
                              {r.mahnstufe ? <MahnstufeBadge stufe={r.mahnstufe} /> : null}
                            </div>
                          </td>
                          <td style={{ width: 120 }}><StatusBadge status={r.status} /></td>
                          <td className={`is-num col-offen ${isNeg ? "is-negative" : ""}`} style={{ width: 130 }}>
                            {fmtEUR_op(r.offen)}
                          </td>
                          <td style={{ position: "relative", textAlign: "right", width: 200 }}>
                            <ActionCell row={r} onAction={onAction} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ───────── Filter-Zeile: Immobilie + Datum ─────────

function FilterRow({ availableImmos, immoFilter, setImmoFilter, datumVon, datumBis, setDatumVon, setDatumBis }) {
  const toggleImmo = (cc) => {
    setImmoFilter((prev) => {
      const next = new Set(prev);
      next.has(cc) ? next.delete(cc) : next.add(cc);
      return next;
    });
  };
  const clearAll = () => {
    setImmoFilter(new Set());
    setDatumVon("");
    setDatumBis("");
  };
  const hasFilter = immoFilter.size > 0 || datumVon || datumBis;

  // Datum-Presets — alles dynamisch zur Render-Zeit berechnet
  const _now = new Date();
  const _Y = _now.getFullYear();
  const _M = _now.getMonth(); // 0-indexed
  const _pad = (n) => String(n).padStart(2, "0");
  const _ymd = (y, m, d) => `${y}-${_pad(m + 1)}-${_pad(d)}`;

  const curMonthStart = _ymd(_Y, _M, 1);
  const curMonthEnd = _ymd(_Y, _M, new Date(_Y, _M + 1, 0).getDate());

  const _prev = new Date(_Y, _M - 1, 1);
  const prevMonthStart = _ymd(_prev.getFullYear(), _prev.getMonth(), 1);
  const prevMonthEnd = _ymd(
    _prev.getFullYear(),
    _prev.getMonth(),
    new Date(_prev.getFullYear(), _prev.getMonth() + 1, 0).getDate(),
  );

  const todayStr = _ymd(_Y, _M, _now.getDate());
  const _d30 = new Date(_now); _d30.setDate(_d30.getDate() - 30);
  const minus30Str = _ymd(_d30.getFullYear(), _d30.getMonth(), _d30.getDate());

  const presets = [
    { label: "Aktueller Monat", von: curMonthStart, bis: curMonthEnd },
    { label: "Letzter Monat", von: prevMonthStart, bis: prevMonthEnd },
    { label: "Heute", von: todayStr, bis: todayStr },
    { label: "> 30 Tage", von: "", bis: minus30Str },
    { label: `${_Y}`, von: `${_Y}-01-01`, bis: `${_Y}-12-31` },
    { label: `${_Y - 1}`, von: `${_Y - 1}-01-01`, bis: `${_Y - 1}-12-31` },
  ];
  const presetMatch = presets.find((p) => p.von === datumVon && p.bis === datumBis);

  return (
    <div className="op-filter-row">
      <div className="op-filter-group">
        <span className="op-filter-group-label">Immobilie</span>
        <button
          className={`op-immo-chip ${immoFilter.size === 0 ? "is-active" : ""}`}
          onClick={() => setImmoFilter(new Set())}
        >
          Alle
        </button>
        {availableImmos.map((i) => (
          <button
            key={i.cc}
            className={`op-immo-chip ${immoFilter.has(i.cc) ? "is-active" : ""}`}
            onClick={() => toggleImmo(i.cc)}
          >
            {i.label}
            <span className="op-immo-chip-count">{i.count}</span>
          </button>
        ))}
      </div>

      <div className="op-filter-sep" />

      <div className="op-filter-group">
        <span className="op-filter-group-label">Fälligkeit</span>
        <input
          type="date"
          className="op-date-input"
          value={datumVon}
          onChange={(e) => setDatumVon(e.target.value)}
          placeholder="von"
        />
        <span style={{ color: "var(--ink-3)" }}>—</span>
        <input
          type="date"
          className="op-date-input"
          value={datumBis}
          onChange={(e) => setDatumBis(e.target.value)}
          placeholder="bis"
        />
        <span style={{ display: "inline-flex", gap: 2, marginLeft: 4 }}>
          {presets.map((p) => (
            <button
              key={p.label}
              className={`op-date-preset ${presetMatch?.label === p.label ? "is-active" : ""}`}
              onClick={() => { setDatumVon(p.von); setDatumBis(p.bis); }}
            >
              {p.label}
            </button>
          ))}
        </span>
      </div>

      {hasFilter && (
        <button className="op-filter-clear" onClick={clearAll}>
          Filter zurücksetzen ×
        </button>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<OpApp />);
