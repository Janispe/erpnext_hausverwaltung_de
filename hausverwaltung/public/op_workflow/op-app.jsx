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
  const initialData = window.OFFENE_POSTEN || window.OP_ADAPTER?.emptyState?.() || {
    filters: {},
    rows: [],
    mahnkandidaten: [],
    partyName: (id) => id,
    ccLabel: {},
    TODAY: frappe.datetime?.get_today?.() || new Date().toISOString().slice(0, 10),
  };
  window.OFFENE_POSTEN = initialData;
  const partyName = (id) => window.OFFENE_POSTEN.partyName(id);

  // Rows als State — werden bei Backend-Refresh aktualisiert
  const [ALL_ROWS, setAllRows] = React.useState(initialData.rows || []);
  const [MAHN_ROWS, setMahnRows] = React.useState(initialData.mahnkandidaten || []);
  const [isLoading, setIsLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");

  React.useEffect(() => {
    const onRefresh = () => {
      setAllRows([...window.OFFENE_POSTEN.rows]);
      setMahnRows([...(window.OFFENE_POSTEN.mahnkandidaten || [])]);
      setSelected(new Set());
      setLoadError("");
    };
    const onMahnRefresh = () => setMahnRows([...(window.OFFENE_POSTEN.mahnkandidaten || [])]);
    const onLoadStart = () => {
      setIsLoading(true);
      setLoadError("");
    };
    const onLoadEnd = () => setIsLoading(false);
    const onLoadError = (event) => {
      console.error("op data load failed", event.detail);
      setLoadError(event.detail?.message || "Offene Posten konnten nicht geladen werden.");
    };
    window.addEventListener("op-data-refreshed", onRefresh);
    window.addEventListener("op-mahn-data-refreshed", onMahnRefresh);
    window.addEventListener("op-loading-start", onLoadStart);
    window.addEventListener("op-loading-end", onLoadEnd);
    window.addEventListener("op-loading-error", onLoadError);
    return () => {
      window.removeEventListener("op-data-refreshed", onRefresh);
      window.removeEventListener("op-mahn-data-refreshed", onMahnRefresh);
      window.removeEventListener("op-loading-start", onLoadStart);
      window.removeEventListener("op-loading-end", onLoadEnd);
      window.removeEventListener("op-loading-error", onLoadError);
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
  const [showAbschlagszahlungen, setShowAbschlagszahlungen] = useStateA0(false);
  const [search, setSearch] = useStateA0("");
  const [activeChip, setActiveChip] = useStateA0(null);
  const [directionFilter, setDirectionFilter] = useStateA0("alle");
  const [partyFilter, setPartyFilter] = useStateA0("");
  const [partySearch, setPartySearch] = useStateA0("");
  const [selected, setSelected] = useStateA0(() => new Set());
  const [immoFilter, setImmoFilter] = useStateA0(() => new Set()); // leer = alle
  // Default: aktueller Monat (1. bis letzter Tag)
  const _initNow = new Date();
  const _initPad = (n) => String(n).padStart(2, "0");
  const _initMonthStart = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-01`;
  const _initMonthEnd = `${_initNow.getFullYear()}-${_initPad(_initNow.getMonth() + 1)}-${_initPad(new Date(_initNow.getFullYear(), _initNow.getMonth() + 1, 0).getDate())}`;
  const [datumVon, setDatumVon] = useStateA0(_initMonthStart);
  const [datumBis, setDatumBis] = useStateA0(_initMonthEnd);

  const routeViewFromUrl = () => {
    const params = new URLSearchParams(window.location.search || "");
    return params.get("view") === "mahnwesen" ? "mahnwesen" : "op";
  };
  const viewRef = React.useRef(view);
  React.useEffect(() => {
    viewRef.current = view;
  }, [view]);
  const setWorkflowView = (nextView) => {
    viewRef.current = nextView;
    setView(nextView);
    const url = new URL(window.location.href);
    if (nextView === "mahnwesen") url.searchParams.set("view", "mahnwesen");
    else url.searchParams.delete("view");
    window.history.pushState(
      { ...(window.history.state || {}), opWorkflowView: nextView },
      "",
      `${url.pathname}${url.search}${url.hash}`
    );
  };
  React.useEffect(() => {
    const syncViewFromUrl = () => {
      const nextView = routeViewFromUrl();
      if (viewRef.current !== nextView) {
        viewRef.current = nextView;
        setView(nextView);
      }
    };
    const syncViewFromEvent = (event) => {
      const nextView = event.detail?.view === "mahnwesen" ? "mahnwesen" : "op";
      if (viewRef.current !== nextView) {
        viewRef.current = nextView;
        setView(nextView);
      }
    };
    const interval = window.setInterval(syncViewFromUrl, 500);
    window.addEventListener("popstate", syncViewFromUrl);
    window.addEventListener("hashchange", syncViewFromUrl);
    window.addEventListener("op-workflow-view-change", syncViewFromEvent);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("popstate", syncViewFromUrl);
      window.removeEventListener("hashchange", syncViewFromUrl);
      window.removeEventListener("op-workflow-view-change", syncViewFromEvent);
    };
  }, []);

  // Backend-Refresh bei Report-Filtern (debounced 300ms). Läuft auch initial,
  // weil der Bootstrap nur die UI rendert und keine Reportdaten blockierend lädt.
  React.useEffect(() => {
    const timer = setTimeout(() => {
      window.OP_ADAPTER.refresh({
        mode: "Beides",
        von_faelligkeit: datumVon,
        bis_faelligkeit: datumBis,
        show_settled: showSettled ? 1 : 0,
        show_written_off: showWrittenOff ? 1 : 0,
        hide_abschlagszahlungen: showAbschlagszahlungen ? 0 : 1,
      }).catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [datumVon, datumBis, showSettled, showWrittenOff, showAbschlagszahlungen]);

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

  const openCandidateDunning = (candidate, selectedInvoiceNames = null) => {
    const selectedNames = selectedInvoiceNames ? new Set(selectedInvoiceNames) : null;
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
      setToast("Keine ausgewählten Rechnungen für diese Mahnung.");
      return;
    }
    const initialRows = selectedNames
      ? rows.filter((item) => selectedNames.has(item.belegnummer))
      : [rows[0]];
    setModal({
      type: "mahnung",
      row: initialRows[0] || rows[0],
      rows,
      selectedInvoiceNames: initialRows.map((item) => item.belegnummer),
    });
  };

  const openCandidatesBulkDunning = (candidates, selectedInvoicesByCandidate = null) => {
    const rows = candidates.flatMap((candidate) => {
      const selectedNames = selectedInvoicesByCandidate?.get?.(candidate.key);
      const invoices = (candidate.invoices || []).filter((invoice) =>
        !selectedNames || selectedNames.has(invoice.sales_invoice)
      );
      return invoices.map((invoice) => ({
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
    });
    if (!rows.length) {
      setToast("Keine ausgewählten Rechnungen für eine Sammelmahnung.");
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
          <button className="mk-btn mk-btn-primary" onClick={() => setWorkflowView("mahnwesen")}>Sammelmahnung</button>
        </div>
      </div>

      <main className="mk-main" data-screen-label={`Mode ${mode}`}>
        <div className="op-view-tabs">
          <button className={`op-view-tab ${view === "op" ? "is-active" : ""}`} onClick={() => setWorkflowView("op")}>
            Offene Posten
          </button>
          <button className={`op-view-tab ${view === "mahnwesen" ? "is-active" : ""}`} onClick={() => setWorkflowView("mahnwesen")}>
            Mahnwesen <span className="op-count">{MAHN_ROWS.length}</span>
          </button>
        </div>

        {(isLoading || loadError) && (
          <div className={`op-load-state ${loadError ? "is-error" : ""}`}>
            {loadError || "Offene-Posten-Daten werden geladen ..."}
          </div>
        )}

        {/* Mode-Switch */}
        {view === "op" && <div className="op-mode-bar">
          <div className="op-mode-tabs">
            {["Forderungen", "Rechnungen", "Beides"].map((m) => (
              <button key={m}
                className={`op-mode-tab ${mode === m ? "is-active" : ""}`}
                onClick={() => { setMode(m); setSelected(new Set()); setActiveChip(null); setPartyFilter(""); setPartySearch(""); }}>
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
              onClick={() => setWorkflowView("mahnwesen")}>
              Zum Mahnwesen →
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
            <label className="mk-toggle">
              <input type="checkbox" checked={showAbschlagszahlungen} onChange={(e) => setShowAbschlagszahlungen(e.target.checked)} />
              Abschläge anzeigen
            </label>
          </div>
          <div className="op-toolbar-right">
            <PartyPicker
              value={partyFilter}
              searchText={partySearch}
              parties={availableParties}
              mode={mode}
              onSearchChange={setPartySearch}
              onChange={(partyId) => { setPartyFilter(partyId); setSelected(new Set()); }}
            />
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
      {modal?.type === "mahnung" && <MahnungModal row={modal.row} rows={modal.rows} selectedInvoiceNames={modal.selectedInvoiceNames} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(result.created ? `${(result.created || []).length} Mahnung-Drafts erstellt` : `Mahnung-Draft erstellt: ${result.dunning}`); }} />}
      {modal?.type === "sammelmahnung" && <SammelmahnungModal rows={modal.rows} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`${(result.created || []).length} Mahnung-Drafts erstellt`); }} />}
      {modal?.type === "zahlung" && <ZahlungModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Payment Entry Draft erstellt: ${result.payment_entry}`); }} />}
      {modal?.type === "guthaben" && <GuthabenAuszahlenModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Auszahlungs-Draft erstellt: ${result.payment_entry}`); }} />}
      {modal?.type === "zuordnen" && <ZuordnenModal row={modal.row} onClose={() => setModal(null)} onDone={(result) => { setModal(null); setToast(`Payment Reconciliation Draft erstellt: ${result.payment_reconciliation}`); }} />}
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

function partyPickerLabel(party) {
  if (!party) return "";
  return party.label && party.label !== party.id ? `${party.label} (${party.id})` : party.id;
}

function PartyCellLabel({ party }) {
  const label = window.OFFENE_POSTEN.partyName(party) || party;
  const showId = party && label !== party;
  return (
    <>
      {label}
      {showId && <span className="op-party-id">{party}</span>}
    </>
  );
}

function PartyPicker({ value, searchText, parties, mode, onSearchChange, onChange }) {
  const [open, setOpen] = useStateA0(false);
  const rootRef = React.useRef(null);
  const selected = parties.find((party) => party.id === value);
  const roleLabel = mode === "Rechnungen" ? "Lieferant" : mode === "Beides" ? "Partei" : "Mieter";
  const q = (searchText || "").trim().toLowerCase();
  const visibleParties = useMemoA0(() => {
    if (!q) return parties.slice(0, 80);
    return parties.filter((party) =>
      (party.label || "").toLowerCase().includes(q) ||
      (party.id || "").toLowerCase().includes(q)
    ).slice(0, 80);
  }, [parties, q]);

  useEffectA0(() => {
    const onPointerDown = (event) => {
      if (!rootRef.current || rootRef.current.contains(event.target)) return;
      setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const choose = (party) => {
    onSearchChange(party ? partyPickerLabel(party) : "");
    onChange(party?.id || "");
    setOpen(false);
  };

  return (
    <div className="op-party-picker" ref={rootRef}>
      <input
        className="op-party-search"
        type="search"
        value={searchText}
        placeholder={selected ? partyPickerLabel(selected) : `${roleLabel} suchen`}
        onFocus={(e) => {
          e.target.select();
          setOpen(true);
        }}
        onChange={(e) => {
          onSearchChange(e.target.value);
          setOpen(true);
        }}
      />
      {value && (
        <button
          type="button"
          className="op-party-clear"
          aria-label={`${roleLabel}auswahl löschen`}
          onClick={() => choose(null)}
        >
          ×
        </button>
      )}
      {open && (
        <div className="op-party-menu">
          {visibleParties.length === 0 ? (
            <div className="op-party-empty">Keine Treffer</div>
          ) : visibleParties.map((party) => (
            <button
              type="button"
              key={party.id}
              className={`op-party-option ${value === party.id ? "is-selected" : ""}`}
              onClick={() => choose(party)}
            >
              <span className="op-party-option-title">{partyPickerLabel(party)}</span>
              <span className="op-party-option-meta">{party.count} {party.count === 1 ? "Posten" : "Posten"}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function latestInvoiceName(invoices) {
  const sorted = [...(invoices || [])].sort((a, b) => {
    const dateCmp = (b.due_date || "").localeCompare(a.due_date || "");
    if (dateCmp !== 0) return dateCmp;
    return (b.sales_invoice || "").localeCompare(a.sales_invoice || "");
  });
  return sorted[0]?.sales_invoice || "";
}

function MahnwesenView({ rows, search, setSearch, onCreateDunning, onCreateBulkDunning }) {
  const [openSet, setOpenSet] = useStateA0(() => new Set());
  const [invoiceFilter, setInvoiceFilter] = useStateA0("current");
  const [selectedInvoices, setSelectedInvoices] = useStateA0(() => new Map());
  useEffectA0(() => {
    setSelectedInvoices((prev) => {
      const next = new Map();
      rows.forEach((row) => {
        const valid = new Set((row.invoices || []).map((invoice) => invoice.sales_invoice));
        const existing = prev.get(row.key);
        const keep = existing ? new Set([...existing].filter((name) => valid.has(name))) : new Set();
        next.set(row.key, keep);
      });
      return next;
    });
  }, [rows]);

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
  const visibleInvoicesFor = (row) => {
    const invoices = row.invoices || [];
    if (invoiceFilter !== "current") return invoices;
    const latest = latestInvoiceName(invoices);
    return invoices.filter((invoice) => invoice.sales_invoice === latest);
  };
  const effectiveSelectedInvoices = useMemoA0(() => {
    const next = new Map();
    filtered.forEach((row) => {
      const visibleNames = new Set(visibleInvoicesFor(row).map((invoice) => invoice.sales_invoice));
      const selected = new Set(
        [...(selectedInvoices.get(row.key) || new Set())].filter((name) => visibleNames.has(name))
      );
      if (selected.size) next.set(row.key, selected);
    });
    return next;
  }, [filtered, selectedInvoices, invoiceFilter]);
  const selectedRows = filtered.filter((row) => (effectiveSelectedInvoices.get(row.key)?.size || 0) > 0);
  const selectedTotal = filtered.reduce((sum, row) => {
    const selected = effectiveSelectedInvoices.get(row.key) || new Set();
    return sum + (row.invoices || []).reduce((inner, invoice) => (
      selected.has(invoice.sales_invoice) ? inner + (invoice.outstanding_amount || 0) : inner
    ), 0);
  }, 0);
  const total = filtered.reduce((sum, row) => sum + (row.offen || 0), 0);
  const toggleInvoice = (candidateKey, invoiceName) => {
    setSelectedInvoices((prev) => {
      const next = new Map(prev);
      const current = new Set(next.get(candidateKey) || []);
      current.has(invoiceName) ? current.delete(invoiceName) : current.add(invoiceName);
      next.set(candidateKey, current);
      return next;
    });
  };
  const selectVisibleInvoices = (row, checked) => {
    const names = visibleInvoicesFor(row).map((invoice) => invoice.sales_invoice).filter(Boolean);
    setSelectedInvoices((prev) => {
      const next = new Map(prev);
      const current = new Set(next.get(row.key) || []);
      names.forEach((name) => checked ? current.add(name) : current.delete(name));
      next.set(row.key, current);
      return next;
    });
  };
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
            {filtered.length} Kandidaten · {fmtEUR_op(total)} offen · ausgewählt {fmtEUR_op(selectedTotal)}
          </div>
          <div className="op-mahn-scope-note">
            Zeigt alle mahnreifen offenen Rechnungen, unabhängig vom Fälligkeitsfilter der Offene-Posten-Ansicht.
            {!selectedRows.length && " Rechnungen in den aufgeklappten Zeilen auswählen."}
          </div>
        </div>
        <div className="op-chips" style={{ flex: "0 0 auto" }}>
          <button className={`op-chip ${invoiceFilter === "current" ? "is-active" : ""}`} onClick={() => setInvoiceFilter("current")}>
            Aktuelle Rechnung
          </button>
          <button className={`op-chip ${invoiceFilter === "all" ? "is-active" : ""}`} onClick={() => setInvoiceFilter("all")}>
            Alle Rechnungen
          </button>
        </div>
        <input
          className="op-search"
          placeholder="Mieter, Beleg, Wohnung, Vertrag oder Vorlage suchen..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button
          className="mk-btn mk-btn-primary"
          onClick={() => onCreateBulkDunning(selectedRows, effectiveSelectedInvoices)}
          disabled={!selectedRows.length}
        >
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
                const selected = effectiveSelectedInvoices.get(row.key) || new Set();
                const visibleInvoices = visibleInvoicesFor(row);
                const visibleSelected = visibleInvoices.filter((invoice) => selected.has(invoice.sales_invoice));
                const visibleSum = visibleInvoices.reduce((sum, invoice) => sum + (invoice.outstanding_amount || 0), 0);
                const visibleDueDates = visibleInvoices.map((invoice) => invoice.due_date).filter(Boolean).sort();
                const visibleDueDate = visibleDueDates[0] || row.oldest_due_date;
                const visibleAge = visibleDueDate
                  ? Math.max(0, Math.floor((new Date(window.OFFENE_POSTEN.TODAY) - new Date(visibleDueDate)) / 86400000))
                  : row.oldest_age_days || 0;
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
                      <td className="is-num col-offen">
                        {fmtEUR_op(invoiceFilter === "current" ? visibleSum : row.offen)}
                        {invoiceFilter === "current" && Math.abs((row.offen || 0) - visibleSum) > 0.01 && (
                          <span className="op-party-id">gesamt {fmtEUR_op(row.offen)}</span>
                        )}
                      </td>
                      <td>
                        {fmtDate_op(invoiceFilter === "current" ? visibleDueDate : row.oldest_due_date)}
                        <span className="op-party-id">{invoiceFilter === "current" ? visibleAge : row.oldest_age_days || 0} Tage</span>
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
                          <button
                            className="op-action-btn is-primary"
                            disabled={!selected.size}
                            onClick={() => onCreateDunning(row, [...selected])}
                          >
                            Mahnung erstellen
                          </button>
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
                                <thead>
                                  <tr>
                                    <th>
                                      <input
                                        type="checkbox"
                                        checked={visibleInvoices.length > 0 && visibleSelected.length === visibleInvoices.length}
                                        ref={(el) => el && (el.indeterminate = visibleSelected.length > 0 && visibleSelected.length < visibleInvoices.length)}
                                        onChange={(e) => selectVisibleInvoices(row, e.target.checked)}
                                      />
                                    </th>
                                    <th>Beleg</th>
                                    <th>Fällig</th>
                                    <th className="is-num">Offen</th>
                                    <th>Status</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {visibleInvoices.map((invoice) => (
                                    <tr key={invoice.sales_invoice}>
                                      <td>
                                        <input
                                          type="checkbox"
                                          checked={selected.has(invoice.sales_invoice)}
                                          onChange={() => toggleInvoice(row.key, invoice.sales_invoice)}
                                        />
                                      </td>
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
  const currentInvoices = (candidate.invoices || []).filter((invoice) => invoice.sales_invoice === row.belegnummer);
  const visibleInvoices = currentInvoices.length ? currentInvoices : [{
    sales_invoice: row.belegnummer,
    due_date: row.faellig_am,
    outstanding_amount: row.offen,
    status: row.status,
  }];

  return (
    <div className="op-mahn-inline">
      <div className="op-mahn-inline-head">
        <div>
          <strong>{candidate.customer_name || candidate.customer}</strong>
          <span>{candidate.wohnung || "—"} · {candidate.mietvertrag || "—"} · {fmtEUR_op(row.offen)} offen</span>
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
          <button className="op-action-btn is-primary" onClick={() => onCreateDunning(candidate, [row.belegnummer])}>
            Mahnung erstellen
          </button>
        )}
      </div>
      {drafts.length > 1 && (
        <div className="op-draft-note">Mehrere offene Drafts. Bitte einen finalisieren oder alte Drafts löschen.</div>
      )}
      <div className="op-mahn-detail">
        <div>
          <div className="op-preview-label">Aktuelle Rechnung</div>
          <table className="op-mini-table">
            <tbody>
              {visibleInvoices.map((invoice) => (
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

function BelegLink({ row }) {
  const memberCount = row.member_voucher_nos?.length || 0;
  const hasMembers = memberCount > 1;
  const title = hasMembers
    ? `${memberCount} ${row.belegart.replace(/ \(×\d+\)$/, "")} auswählen`
    : `${row.belegart} ${row.belegnummer} öffnen`;
  return (
    <>
      <button
        type="button"
        className="op-link-btn op-beleg-link"
        onClick={() => window.OP_ACTIONS.openBeleg(row)}
        title={title}
      >
        {row.belegnummer}
        {hasMembers ? <span className="op-beleg-count">+{memberCount - 1}</span> : null}
      </button>
      <span className="op-beleg-art">{row.belegart}</span>
    </>
  );
}

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
        <colgroup>
          <col className="op-col-check" />
          <col className="op-col-date" />
          <col className="op-col-age" />
          <col className="op-col-party" />
          {showObjekt && <col className="op-col-object" />}
          <col className="op-col-beleg" />
          <col className="op-col-bemerk" />
          <col className="op-col-status" />
          <col className="op-col-direction" />
          <col className="op-col-amount" />
          <col className="op-col-paid" />
          <col className="op-col-open" />
          {showAktion && <col className="op-col-action" />}
        </colgroup>
        <thead>
          <tr>
            <th className="is-check">
              <input type="checkbox" checked={allChecked}
                ref={(el) => el && (el.indeterminate = someChecked)}
                onChange={toggleSelAll}
                disabled={selectableIds.size === 0} />
            </th>
            <SortableTh col="Fällig am" label="Fällig am" />
            <SortableTh col="Alter" label="Alter" />
            <SortableTh col="Mieter" label={mode === "Rechnungen" ? "Lieferant" : "Mieter"} />
            {showObjekt && <SortableTh col="Immobilie" label="Immobilie" />}
            <th>Beleg</th>
            <th className="col-bemerk-head">Bemerkung</th>
            <SortableTh col="Status" label="Status" />
            <SortableTh col="Richtung" label="Richtung" />
            <th className="is-num">Rechnungsbetrag</th>
            <th className="is-num">Bezahlt</th>
            <SortableTh col="Offener Betrag absteigend" label="Offen" className="is-num" />
            {showAktion && <th>Aktion</th>}
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
                    <PartyCellLabel party={r.party} />
                  </td>
                  {showObjekt && (
                    <td style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
                      {window.OFFENE_POSTEN.ccLabel[r.kostenstelle] || r.kostenstelle || "—"}
                    </td>
                  )}
                  <td className="col-beleg">
                    <BelegLink row={r} />
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
                  <colgroup>
                    <col className="op-col-check" />
                    <col className="op-col-date" />
                    <col className="op-col-age" />
                    <col className="op-col-beleg" />
                    {gruppierung !== "objekt" && showObjekt && <col className="op-col-object" />}
                    {gruppierung === "objekt" && <col className="op-col-party" />}
                    <col className="op-col-bemerk" />
                    <col className="op-col-status" />
                    <col className="op-col-open" />
                    <col className="op-col-action" />
                  </colgroup>
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
                            <td className="col-check">
                              <input type="checkbox" checked={sel}
                                disabled={!r.can_write_off}
                                onChange={() => toggleSel(r.belegnummer)} />
                            </td>
                            <td className="col-date">{fmtDate_op(r.faellig_am)}</td>
                            <td><AgePill age={r.alter_tage} faellig_am={r.faellig_am} /></td>
                            <td className="col-beleg">
                              <BelegLink row={r} />
                            </td>
                            {gruppierung !== "objekt" && showObjekt && (
                              <td style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
                                {window.OFFENE_POSTEN.ccLabel[r.kostenstelle] || "—"}
                              </td>
                            )}
                            {gruppierung === "objekt" && (
                              <td className="col-party" style={{ fontSize: 12.5 }}>
                                <PartyCellLabel party={r.party} />
                              </td>
                            )}
                            <td className="col-bemerk">
                              <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                                <span>{r.bemerkungen}</span>
                                {r.mahnstufe ? <MahnstufeBadge stufe={r.mahnstufe} /> : null}
                              </div>
                            </td>
                            <td><StatusBadge status={r.status} /></td>
                            <td className={`is-num col-offen ${isNeg ? "is-negative" : ""}`}>
                              {fmtEUR_op(r.offen)}
                            </td>
                            <td style={{ position: "relative", textAlign: "right" }}>
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

window.OP_RENDER = function renderOpWorkflow() {
  const rootEl = document.getElementById("op-workflow-root") || document.getElementById("root");
  if (!rootEl) return;
  if (window.__OP_REACT_ROOT) {
    try {
      window.__OP_REACT_ROOT.unmount();
    } catch (err) {
      // The previous mount point may already have been replaced by Frappe.
    }
  }
  window.__OP_REACT_ROOT = ReactDOM.createRoot(rootEl);
  window.__OP_REACT_ROOT.render(<OpApp />);
};

window.OP_RENDER();
