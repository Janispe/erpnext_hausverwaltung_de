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
  const [MAHN_ROWS, setMahnRows] = React.useState(window.OFFENE_POSTEN.mahnkandidaten || []);
  const [isLoading, setIsLoading] = React.useState(false);

  React.useEffect(() => {
    const onRefresh = () => {
      setAllRows([...window.OFFENE_POSTEN.rows]);
      setMahnRows([...(window.OFFENE_POSTEN.mahnkandidaten || [])]);
      setSelected(new Set());
    };
    const onMahnRefresh = () => setMahnRows([...(window.OFFENE_POSTEN.mahnkandidaten || [])]);
    const onLoadStart = () => setIsLoading(true);
    const onLoadEnd = () => setIsLoading(false);
    window.addEventListener("op-data-refreshed", onRefresh);
    window.addEventListener("op-mahn-data-refreshed", onMahnRefresh);
    window.addEventListener("op-loading-start", onLoadStart);
    window.addEventListener("op-loading-end", onLoadEnd);
    return () => {
      window.removeEventListener("op-data-refreshed", onRefresh);
      window.removeEventListener("op-mahn-data-refreshed", onMahnRefresh);
      window.removeEventListener("op-loading-start", onLoadStart);
      window.removeEventListener("op-loading-end", onLoadEnd);
    };
  }, []);

  // Filter-State
  const [view, setView] = useStateA0(() => {
    const params = new URLSearchParams(window.location.search || "");
    return params.get("view") === "mahnwesen" || frappe.route_options?.view === "mahnwesen" ? "mahnwesen" : "op";
  });
  const [mode, setMode] = useStateA0("Forderungen");
  const [sortierung, setSortierung] = useStateA0("Fällig am");
  const [sortDir, setSortDir] = useStateA0("asc"); // asc | desc
  const [showSettled, setShowSettled] = useStateA0(false);
  const [showWrittenOff, setShowWrittenOff] = useStateA0(false);
  const [search, setSearch] = useStateA0("");
  const [activeChip, setActiveChip] = useStateA0(null);
  const [directionFilter, setDirectionFilter] = useStateA0("alle");
  const [partyFilter, setPartyFilter] = useStateA0("");
  const [selected, setSelected] = useStateA0(() => new Set());
  const [immoFilter, setImmoFilter] = useStateA0(() => new Set()); // leer = alle
  // Default: aktueller Monat (1. bis letzter Tag)
  const _initNow = new Date();
  const _initPad = (n) => String(n).padStart(2, "0");
  const _initMonthStart = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-01`;
  const _initMonthEnd = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-${_initPad(new Date(_initNow.getFullYear(), _initNow.getMonth() + 1, 0).getDate())}`;
  const [datumVon, setDatumVon] = useStateA0(_initMonthStart);
  const [datumBis, setDatumBis] = useStateA0(_initMonthEnd);

  // Backend-Refresh bei Report-Filtern (debounced 300ms). First render skip:
  // Bootstrap hat bereits mit den Initial-Filtern geladen.
  const _didInitRef = React.useRef(false);
  React.useEffect(() => {
    if (!_didInitRef.current) { _didInitRef.current = true; return; }
    const timer = setTimeout(() => {
      window.OP_ADAPTER.refresh({
        mode: "Beides",
        von_faelligkeit: datumVon,
        bis_faelligkeit: datumBis,
        show_settled: showSettled ? 1 : 0,
        show_written_off: showWrittenOff ? 1 : 0,
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [datumVon, datumBis, showSettled, showWrittenOff]);

  // Modal-State
  const [modal, setModal] = useStateA0(null); // { type, row }
  const [toast, setToast] = useStateA0(null);
  const [expandedMahnRows, setExpandedMahnRows] = useStateA0(() => new Set());

  const mahnCandidateByInvoice = useMemoA0(() => {
    const map = new Map();
    (MAHN_ROWS || []).forEach((candidate) => {
      (candidate.invoices || []).forEach((invoice) => {
        if (invoice.sales_invoice) map.set(invoice.sales_invoice, candidate);
      });
    });
    return map;
  }, [MAHN_ROWS]);

  const toggleMahnwesenForRow = (row) => {
    setExpandedMahnRows((prev) => {
      const next = new Set(prev);
      next.has(row.belegnummer) ? next.delete(row.belegnummer) : next.add(row.belegnummer);
      return next;
    });
    setSelected(new Set());
  };

  const handleAction = async (key, row) => {
    try {
      if (key === "mahnwesen") toggleMahnwesenForRow(row);
      else if (key === "mahnung" || key === "sammelmahnung") setModal({ type: "mahnung", row });
      else if (key === "zahlung_anlegen") setModal({ type: "zahlung", row });
      else if (key === "zuordnen") setModal({ type: "zuordnen", row });
      else if (key === "guthaben_auszahlen") setModal({ type: "guthaben", row });
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
  }, [ALL_ROWS]);

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

  const availableParties = useMemoA0(() => {
    const map = new Map();
    modeRows.forEach((r) => {
      if (!r.party) return;
      if (!map.has(r.party)) {
        map.set(r.party, {
          id: r.party,
          label: partyName(r.party) || r.party,
          count: 0,
        });
      }
      map.get(r.party).count += 1;
    });
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [modeRows, partyName]);

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
    if (partyFilter) rows = rows.filter((r) => r.party === partyFilter);
    if (directionFilter !== "alle") rows = rows.filter((r) => r.zahlungsrichtung === directionFilter);
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
      else if (sortierung === "Richtung") r = (a.zahlungsrichtung || "").localeCompare(b.zahlungsrichtung || "");
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
  }, [modeRows, immoFilter, partyFilter, directionFilter, datumVon, datumBis, showSettled, showWrittenOff, activeChip, search, sortierung, sortDir]);

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
  React.useEffect(() => {
    const visibleIds = new Set(filteredRows.map((r) => r.belegnummer));
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => visibleIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [filteredRows]);
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

  const exportCsv = () => {
    const cols = [
      ["faellig_am", "Fällig am"],
      ["alter_tage", "Alter Tage"],
      ["party", mode === "Rechnungen" ? "Lieferant" : "Mieter"],
      ["kostenstelle", "Immobilie/Kostenstelle"],
      ["belegart", "Belegart"],
      ["belegnummer", "Belegnummer"],
      ["bemerkungen", "Bemerkungen"],
      ["status", "Status"],
      ["rechnungsbetrag", "Rechnungsbetrag"],
      ["bezahlt", "Bezahlt"],
      ["offen", "Offen"],
      ["zahlungsrichtung", "Zahlungsrichtung"],
    ];
    const esc = (value) => {
      const text = value == null ? "" : String(value);
      return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    const csv = [
      cols.map(([, label]) => esc(label)).join(";"),
      ...filteredRows.map((row) => cols.map(([key]) => esc(row[key])).join(";")),
    ].join("\n");
    const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `offene-posten-${mode.toLowerCase()}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const openBulkDunning = (rows) => {
    const candidates = rows.filter((r) =>
      r.art === "Forderungen" &&
      r.belegart === "Sales Invoice" &&
      r.offen > 0.01 &&
      r.alter_tage > 0 &&
      r.status !== "Written Off"
    );
    if (!candidates.length) {
      setToast("Keine mahnfähigen Forderungen in der Auswahl.");
      return;
    }
    setSelected(new Set(candidates.map((r) => r.belegnummer)));
    setModal({ type: "sammelmahnung", rows: candidates });
  };

  const openCandidateDunning = (candidate) => {
    const rows = (candidate.invoices || []).map((invoice) => ({
      art: "Forderungen",
      party_type: "Customer",
      party: candidate.customer,
      buchungsdatum: invoice.posting_date,
      faellig_am: invoice.due_date,
      belegart: "Sales Invoice",
      belegnummer: invoice.sales_invoice,
      rechnungsbetrag: invoice.grand_total,
      bezahlt: Math.max((invoice.grand_total || 0) - (invoice.outstanding_amount || 0), 0),
      offen: invoice.outstanding_amount,
      party_account: null,
      kostenstelle: invoice.cost_center,
      bemerkungen: invoice.remarks || invoice.mietabrechnung_id || "",
      status: invoice.status,
      zahlungsrichtung: "Geld bekommen",
      alter_tage: candidate.oldest_age_days || 0,
      can_write_off: true,
      mahnstufe: Math.max((candidate.next_level || 1) - 1, 0),
      dunning_type: candidate.next_dunning_type || "",
      serienbrief_vorlage: candidate.serienbrief_vorlage || "",
    }));
    if (!rows.length) {
      setToast("Keine offenen Rechnungen für diese Mahnung.");
      return;
    }
    setModal({
      type: rows.length === 1 ? "mahnung" : "sammelmahnung",
      row: rows[0],
      rows,
    });
  };

  const openCandidatesBulkDunning = (candidates) => {
    const rows = candidates.flatMap((candidate) => (candidate.invoices || []).map((invoice) => ({
      art: "Forderungen",
      party_type: "Customer",
      party: candidate.customer,
      buchungsdatum: invoice.posting_date,
      faellig_am: invoice.due_date,
      belegart: "Sales Invoice",
      belegnummer: invoice.sales_invoice,
      rechnungsbetrag: invoice.grand_total,
      bezahlt: Math.max((invoice.grand_total || 0) - (invoice.outstanding_amount || 0), 0),
      offen: invoice.outstanding_amount,
      party_account: null,
      kostenstelle: invoice.cost_center,
      bemerkungen: invoice.remarks || invoice.mietabrechnung_id || "",
      status: invoice.status,
      zahlungsrichtung: "Geld bekommen",
      alter_tage: candidate.oldest_age_days || 0,
      can_write_off: true,
      mahnstufe: Math.max((candidate.next_level || 1) - 1, 0),
      dunning_type: candidate.next_dunning_type || "",
      serienbrief_vorlage: candidate.serienbrief_vorlage || "",
    })));
    if (!rows.length) {
      setToast("Keine offenen Rechnungen für eine Sammelmahnung.");
      return;
    }
    setModal({ type: "sammelmahnung", rows });
  };

  const writeOffSelected = async () => {
    const candidates = selectedRows.filter((r) => r.can_write_off);
    if (!candidates.length) {
      setToast("Keine abschreibbaren Sales-Invoice-Forderungen ausgewählt.");
      return;
    }
    for (const row of candidates) {
      await window.OP_ACTIONS.writeOff(row, {
        remarks: `Abschreibung aus OP-Workflow vorbereitet: ${row.belegnummer}`,
      });
    }
    setSelected(new Set());
    setToast(`${candidates.length} Abschreibungs-Draft${candidates.length === 1 ? "" : "s"} erstellt.`);
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
          <button className="mk-btn mk-btn-ghost" onClick={exportCsv}>Export CSV</button>
          <button className="mk-btn mk-btn-primary" onClick={() => openBulkDunning(mahnStats.rows)}>Sammelmahnung</button>
        </div>
      </div>

      <main className="mk-main" data-screen-label={`Mode ${mode}`}>
        <div className="op-view-tabs">
          <button className={`op-view-tab ${view === "op" ? "is-active" : ""}`} onClick={() => setView("op")}>
            Offene Posten
          </button>
          <button className={`op-view-tab ${view === "mahnwesen" ? "is-active" : ""}`} onClick={() => setView("mahnwesen")}>
            Mahnwesen <span className="op-count">{MAHN_ROWS.length}</span>
          </button>
        </div>

        {/* Mode-Switch */}
        {view === "op" && <div className="op-mode-bar">
          <div className="op-mode-tabs">
            {["Forderungen", "Rechnungen", "Beides"].map((m) => (
              <button key={m}
                className={`op-mode-tab ${mode === m ? "is-active" : ""}`}
                onClick={() => { setMode(m); setSelected(new Set()); setActiveChip(null); setPartyFilter(""); }}>
                <span>{MODE_LABEL[m]}</span>
                <span className="op-count">{countsByMode[m]}</span>
              </button>
            ))}
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-3)", textAlign: "right" }}>
            <div>{MODE_SUB[mode]}</div>
            <div style={{ marginTop: 2 }}>Stichtag: {fmtDate_op(window.OFFENE_POSTEN.TODAY)}</div>
          </div>
        </div>}

        {view === "mahnwesen" ? (
          <MahnwesenView
            rows={MAHN_ROWS}
            search={search}
            setSearch={setSearch}
            onCreateDunning={openCandidateDunning}
            onCreateBulkDunning={openCandidatesBulkDunning}
          />
        ) : (
          <>

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
            <span className="op-chip-separator" />
            <button className={`op-chip ${directionFilter === "alle" ? "is-active" : ""}`} onClick={() => setDirectionFilter("alle")}>
              Alle Richtungen
            </button>
            <button className={`op-chip ${directionFilter === "Geld bekommen" ? "is-active" : ""}`} onClick={() => setDirectionFilter("Geld bekommen")}>
              Geld bekommen
            </button>
            <button className={`op-chip ${directionFilter === "Geld bezahlen / erstatten" ? "is-active" : ""}`} onClick={() => setDirectionFilter("Geld bezahlen / erstatten")}>
              Geld zahlen
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
            <select
              className="op-party-select"
              value={partyFilter}
              onChange={(e) => { setPartyFilter(e.target.value); setSelected(new Set()); }}
              title={mode === "Rechnungen" ? "Lieferant auswählen" : mode === "Beides" ? "Mieter oder Lieferant auswählen" : "Mieter auswählen"}
            >
              <option value="">{mode === "Rechnungen" ? "Alle Lieferanten" : mode === "Beides" ? "Alle Parteien" : "Alle Mieter"}</option>
              {availableParties.map((party) => (
                <option key={party.id} value={party.id}>
                  {party.label} ({party.count})
                </option>
              ))}
            </select>
            <input className="op-search" placeholder="Beleg oder Bemerkung suchen…"
              value={search} onChange={(e) => setSearch(e.target.value)} />
            <select className="op-sort-select" value={sortierung} onChange={(e) => { setSortierung(e.target.value); setSortDir("asc"); }}>
              <option>Fällig am</option>
              <option>Buchungsdatum</option>
              <option>Älteste zuerst</option>
              <option>Offener Betrag absteigend</option>
              <option>Mieter</option>
              <option>Immobilie</option>
              <option>Status</option>
              <option>Richtung</option>
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
              <button className="op-bulk-btn" onClick={() => openBulkDunning(selectedRows)}>Mahnung erstellen</button>
              <button className="op-bulk-btn is-primary" onClick={writeOffSelected}>Ausgewählte abschreiben</button>
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
          <GroupedView
            groups={grouped}
            selected={selected}
            toggleSel={toggleSel}
            selectableIds={selectableIds}
            mode={mode}
            gruppierung={t.gruppierung}
            showObjekt={t.showObjekt}
            onAction={handleAction}
            mahnCandidateByInvoice={mahnCandidateByInvoice}
            expandedMahnRows={expandedMahnRows}
            onCreateDunning={openCandidateDunning}
          />
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
            mahnCandidateByInvoice={mahnCandidateByInvoice}
            expandedMahnRows={expandedMahnRows}
            onCreateDunning={openCandidateDunning}
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
          </>
        )}
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
      {modal?.type === "guthaben" && <GuthabenAuszahlenModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Auszahlungs-Draft erstellt: ${result.payment_entry}`); }} />}
      {modal?.type === "zuordnen" && <ZuordnenModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Payment Reconciliation Draft erstellt: ${result.payment_reconciliation}`); }} />}
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

function MahnwesenView({ rows, search, setSearch, onCreateDunning, onCreateBulkDunning }) {
  const [openSet, setOpenSet] = useStateA0(() => new Set());
  const filtered = useMemoA0(() => {
    const q = (search || "").trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) =>
      (row.customer_name || "").toLowerCase().includes(q) ||
      (row.customer || "").toLowerCase().includes(q) ||
      (row.mietvertrag || "").toLowerCase().includes(q) ||
      (row.wohnung || "").toLowerCase().includes(q) ||
      (row.serienbrief_vorlage || "").toLowerCase().includes(q) ||
      (row.invoices || []).some((invoice) =>
        (invoice.sales_invoice || "").toLowerCase().includes(q) ||
        (invoice.remarks || "").toLowerCase().includes(q) ||
        (invoice.mietabrechnung_id || "").toLowerCase().includes(q)
      ) ||
      (row.mahnungen || []).some((mahnung) =>
        (mahnung.name || "").toLowerCase().includes(q) ||
        (mahnung.dunning_type || "").toLowerCase().includes(q)
      )
    );
  }, [rows, search]);
  const total = filtered.reduce((sum, row) => sum + (row.offen || 0), 0);
  const toggle = (key) => {
    setOpenSet((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  return (
    <div className="op-mahn-cockpit">
      <div className="op-mahn-head">
        <div>
          <h2>Mahnwesen</h2>
          <div className="op-mahn-head-sub">
            {filtered.length} Kandidaten · {fmtEUR_op(total)} offen · Stichtag {fmtDate_op(window.OFFENE_POSTEN.TODAY)}
          </div>
        </div>
        <input
          className="op-search"
          placeholder="Mieter, Beleg, Wohnung, Vertrag oder Vorlage suchen..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="mk-btn mk-btn-primary" onClick={() => onCreateBulkDunning(filtered)} disabled={!filtered.length}>
          Sammelmahnung erstellen
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="op-empty">
          <strong>Keine Mahnkandidaten.</strong>
          Es gibt aktuell keine überfälligen offenen Sales Invoices in dieser Auswahl.
        </div>
      ) : (
        <div className="op-mahn-table-wrap">
          <table className="op-table op-mahn-table">
            <thead>
              <tr>
                <th style={{ width: 34 }}></th>
                <th>Mieter</th>
                <th>Wohnung</th>
                <th>Mietvertrag</th>
                <th className="is-num">Offen</th>
                <th>Älteste Fälligkeit</th>
                <th>Letzte Mahnung</th>
                <th>Nächste Stufe</th>
                <th>Serienbrief-Vorlage</th>
                <th style={{ width: 170 }}>Aktionen</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const open = openSet.has(row.key);
                const last = (row.mahnungen || [])[0];
                const drafts = (row.mahnungen || []).filter((mahnung) => mahnung.docstatus === 0);
                const draft = drafts[0];
                return (
                  <React.Fragment key={row.key}>
                    <tr className={row.draft_warning ? "is-mahn-draft" : ""}>
                      <td>
                        <button className="op-row-toggle" onClick={() => toggle(row.key)}>{open ? "▾" : "▸"}</button>
                      </td>
                      <td className="col-party">
                        {row.customer_name || row.customer}
                        <span className="op-party-id">{row.customer}</span>
                      </td>
                      <td>{row.wohnung || "—"}</td>
                      <td>{row.mietvertrag || "—"}</td>
                      <td className="is-num col-offen">{fmtEUR_op(row.offen)}</td>
                      <td>
                        {fmtDate_op(row.oldest_due_date)}
                        <span className="op-party-id">{row.oldest_age_days || 0} Tage</span>
                      </td>
                      <td>
                        {last ? (
                          <>
                            <span>
                              {last.dunning_type || last.name}
                              {last.docstatus === 0 && <span className="op-draft-badge">Draft</span>}
                              {drafts.length > 1 && <span className="op-draft-badge is-multiple">{drafts.length} Drafts</span>}
                            </span>
                            <span className="op-party-id">{fmtDate_op(last.posting_date)} · {last.status}</span>
                          </>
                        ) : "—"}
                      </td>
                      <td><MahnstufeBadge stufe={row.next_level} /></td>
                      <td>{row.serienbrief_vorlage || <span className="op-muted">Default fehlt</span>}</td>
                      <td className="op-mahn-actions">
                        {drafts.length > 1 ? (
                          <button className="op-action-btn is-draft" onClick={() => toggle(row.key)}>
                            Drafts prüfen
                          </button>
                        ) : draft ? (
                          <button className="op-action-btn is-draft" onClick={() => window.OP_ACTIONS.openDunning(draft.name)}>
                            Draft öffnen
                          </button>
                        ) : (
                          <button className="op-action-btn is-primary" onClick={() => onCreateDunning(row)}>Mahnung erstellen</button>
                        )}
                      </td>
                    </tr>
                    {open && (
                      <tr className="op-mahn-detail-row">
                        <td></td>
                        <td colSpan="9">
                          <div className="op-mahn-detail">
                            <div>
                              <div className="op-preview-label">Offene Rechnungen</div>
                              <table className="op-mini-table">
                                <tbody>
                                  {(row.invoices || []).map((invoice) => (
                                    <tr key={invoice.sales_invoice}>
                                      <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: invoice.sales_invoice })}>{invoice.sales_invoice}</button></td>
                                      <td>{fmtDate_op(invoice.due_date)}</td>
                                      <td className="is-num">{fmtEUR_op(invoice.outstanding_amount)}</td>
                                      <td>{invoice.status}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            <div>
                              <div className="op-preview-label">
                                Mahnhistorie
                                {drafts.length > 1 && (
                                  <span className="op-draft-note">Mehrere offene Drafts. Bitte einen finalisieren oder alte Drafts löschen.</span>
                                )}
                              </div>
                              {(row.mahnungen || []).length ? (
                                <table className="op-mini-table">
                                  <tbody>
                                    {row.mahnungen.map((mahnung) => (
                                      <tr key={mahnung.name}>
                                        <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openDunning(mahnung.name)}>{mahnung.name}</button></td>
                                        <td>
                                          {mahnung.docstatus === 0 ? <span className="op-draft-badge">Draft</span> : mahnung.status}
                                        </td>
                                        <td>{mahnung.dunning_type || "—"}</td>
                                        <td>{mahnung.serienbrief_vorlage || "—"}</td>
                                        <td>
                                          {mahnung.fee_sales_invoice ? (
                                            <button className="op-link-btn" onClick={() => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: mahnung.fee_sales_invoice })}>
                                              Gebühr
                                            </button>
                                          ) : "—"}
                                        </td>
                                        <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openDunningPdf(mahnung.name)}>PDF</button></td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              ) : (
                                <div className="op-muted">Noch keine Mahnung zu diesen offenen Rechnungen.</div>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function MahnInlineDetail({ candidate, row, onCreateDunning }) {
  if (!candidate) {
    return (
      <div className="op-mahn-inline">
        <div className="op-muted">Für {row.belegnummer} wurde kein Mahnwesen-Datensatz gefunden.</div>
      </div>
    );
  }

  const mahnungen = candidate.mahnungen || [];
  const drafts = mahnungen.filter((mahnung) => mahnung.docstatus === 0);
  const draft = drafts[0];

  return (
    <div className="op-mahn-inline">
      <div className="op-mahn-inline-head">
        <div>
          <strong>{candidate.customer_name || candidate.customer}</strong>
          <span>{candidate.wohnung || "—"} · {candidate.mietvertrag || "—"} · {fmtEUR_op(candidate.offen)} offen</span>
        </div>
        {drafts.length > 1 ? (
          <button className="op-action-btn is-draft" onClick={() => window.OP_ACTIONS.openDunning(draft.name)}>
            Ersten Draft öffnen
          </button>
        ) : draft ? (
          <button className="op-action-btn is-draft" onClick={() => window.OP_ACTIONS.openDunning(draft.name)}>
            Draft öffnen
          </button>
        ) : (
          <button className="op-action-btn is-primary" onClick={() => onCreateDunning(candidate)}>
            Mahnung erstellen
          </button>
        )}
      </div>
      {drafts.length > 1 && (
        <div className="op-draft-note">Mehrere offene Drafts. Bitte einen finalisieren oder alte Drafts löschen.</div>
      )}
      <div className="op-mahn-detail">
        <div>
          <div className="op-preview-label">Offene Rechnungen</div>
          <table className="op-mini-table">
            <tbody>
              {(candidate.invoices || []).map((invoice) => (
                <tr key={invoice.sales_invoice}>
                  <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: invoice.sales_invoice })}>{invoice.sales_invoice}</button></td>
                  <td>{fmtDate_op(invoice.due_date)}</td>
                  <td className="is-num">{fmtEUR_op(invoice.outstanding_amount)}</td>
                  <td>{invoice.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <div className="op-preview-label">Mahnhistorie</div>
          {mahnungen.length ? (
            <table className="op-mini-table">
              <tbody>
                {mahnungen.map((mahnung) => (
                  <tr key={mahnung.name}>
                    <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openDunning(mahnung.name)}>{mahnung.name}</button></td>
                    <td>{mahnung.docstatus === 0 ? <span className="op-draft-badge">Draft</span> : mahnung.status}</td>
                    <td>{mahnung.dunning_type || "—"}</td>
                    <td>{mahnung.serienbrief_vorlage || "—"}</td>
                    <td>
                      {mahnung.fee_sales_invoice ? (
                        <button className="op-link-btn" onClick={() => window.OP_ACTIONS.openBeleg({ belegart: "Sales Invoice", belegnummer: mahnung.fee_sales_invoice })}>
                          Gebühr
                        </button>
                      ) : "—"}
                    </td>
                    <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openDunningPdf(mahnung.name)}>PDF</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="op-muted">Noch keine Mahnung zu diesen offenen Rechnungen.</div>
          )}
        </div>
      </div>
    </div>
  );
}

// ───────── Flache Tabelle ─────────

function FlatTable({
  rows,
  selected,
  toggleSel,
  selectableIds,
  toggleSelAll,
  mode,
  showAktion,
  showObjekt,
  sortierung,
  sortDir,
  onSort,
  onAction,
  mahnreifIds,
  mahnCandidateByInvoice,
  expandedMahnRows,
  onCreateDunning,
}) {
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
            <SortableTh col="Richtung" label="Richtung" style={{ width: 130 }} />
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
            const mahnOpen = expandedMahnRows?.has(r.belegnummer);
            const mahnCandidate = mahnCandidateByInvoice?.get(r.belegnummer);
            const detailColspan = 11 + (showObjekt ? 1 : 0) + (showAktion ? 1 : 0);
            return (
              <React.Fragment key={r.belegnummer + r.party}>
                <tr className={`${sel ? "is-selected" : ""} ${writtenOff ? "is-written-off" : ""} ${mahnreif ? "is-mahnreif" : ""} ${mahnOpen ? "is-mahn-open" : ""}`}>
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
                    <button
                      type="button"
                      className="op-link-btn op-beleg-link"
                      onClick={() => window.OP_ACTIONS.openBeleg(r)}
                      title={`${r.belegart} ${r.belegnummer} öffnen`}
                    >
                      {r.belegnummer}
                    </button>
                    <span className="op-beleg-art">{r.belegart}</span>
                  </td>
                  <td className="col-bemerk">
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span>{r.bemerkungen}</span>
                      {r.mahnstufe ? <MahnstufeBadge stufe={r.mahnstufe} /> : null}
                    </div>
                  </td>
                  <td><StatusBadge status={r.status} /></td>
                  <td><DirectionBadge direction={r.zahlungsrichtung} /></td>
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
                {mahnOpen && (
                  <tr className="op-mahn-inline-row">
                    <td colSpan={detailColspan}>
                      <MahnInlineDetail candidate={mahnCandidate} row={r} onCreateDunning={onCreateDunning} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ───────── Gruppierte Ansicht ─────────

function GroupedView({
  groups,
  selected,
  toggleSel,
  selectableIds,
  mode,
  gruppierung,
  showObjekt,
  onAction,
  mahnCandidateByInvoice,
  expandedMahnRows,
  onCreateDunning,
}) {
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
                      const mahnOpen = expandedMahnRows?.has(r.belegnummer);
                      const mahnCandidate = mahnCandidateByInvoice?.get(r.belegnummer);
                      const detailColspan = 8 + (gruppierung !== "objekt" && showObjekt ? 1 : 0) + (gruppierung === "objekt" ? 1 : 0);
                      return (
                        <React.Fragment key={r.belegnummer}>
                          <tr className={`${sel ? "is-selected" : ""} ${writtenOff ? "is-written-off" : ""} ${mahnOpen ? "is-mahn-open" : ""}`}>
                            <td className="col-check" style={{ width: 32 }}>
                              <input type="checkbox" checked={sel}
                                disabled={!r.can_write_off}
                                onChange={() => toggleSel(r.belegnummer)} />
                            </td>
                            <td className="col-date" style={{ width: 100 }}>{fmtDate_op(r.faellig_am)}</td>
                            <td style={{ width: 80 }}><AgePill age={r.alter_tage} faellig_am={r.faellig_am} /></td>
                            <td className="col-beleg" style={{ width: 170 }}>
                              <button
                                type="button"
                                className="op-link-btn op-beleg-link"
                                onClick={() => window.OP_ACTIONS.openBeleg(r)}
                                title={`${r.belegart} ${r.belegnummer} öffnen`}
                              >
                                {r.belegnummer}
                              </button>
                              <span className="op-beleg-art">{r.belegart}</span>
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
                          {mahnOpen && (
                            <tr className="op-mahn-inline-row">
                              <td colSpan={detailColspan}>
                                <MahnInlineDetail candidate={mahnCandidate} row={r} onCreateDunning={onCreateDunning} />
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
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
