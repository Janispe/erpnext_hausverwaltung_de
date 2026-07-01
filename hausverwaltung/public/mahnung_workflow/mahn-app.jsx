// mahn-app.jsx — Editor für das Mahnung-(Dunning-)Objekt.
// Links: Felder · Rechts: Live-A4-Brief. Layout über Tweaks umschaltbar.

const { useState: useStateApp, useMemo: useMemoApp, useEffect: useEffectApp, useRef: useRefApp } = React;
const {
  useTweaks: useMHTweaks,
  TweaksPanel: MHTweaksPanel,
  TweakSection: MHTweakSection,
  TweakRadio: MHTweakRadio,
  TweakToggle: MHTweakToggle,
} = window.MH_TWEAKS;

const MH_TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "layout": "Brief rechts",
  "papier": true,
  "density": "regular"
}/*EDITMODE-END*/;

const KANAELE = ["Brief", "E-Mail", "Brief + E-Mail"];

// Editierbarer Textblock mit eigener Platzhalter-Leiste + Cursor-Einfügen.
function EditableBlockMH({ label, value, onChange, hint, locked }) {
  const ref = useRefApp(null);
  const insert = (token) => {
    const el = ref.current;
    if (!el) { onChange((value || "") + " " + token); return; }
    const s = el.selectionStart ?? value.length;
    const e = el.selectionEnd ?? value.length;
    const next = value.slice(0, s) + token + value.slice(e);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      const pos = s + token.length;
      el.setSelectionRange(pos, pos);
    });
  };
  return (
    <FieldMH label={label} hint={hint} full>
      <textarea
        ref={ref}
        className="mh-textarea"
        value={value}
        rows={3}
        readOnly={locked}
        onChange={(e) => onChange(e.target.value)}
        onInput={(e) => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; }}
      />
      {!locked && <PlatzhalterBarMH onInsert={insert} />}
    </FieldMH>
  );
}

function MahnApp() {
  const [t, setTweak] = useMHTweaks(MH_TWEAK_DEFAULTS);
  const M = window.MAHNUNG;

  if (!M?.mieter?.length) {
    return (
      <div className="mk-app mh-app is-regular">
        <div className="mk-topbar" data-screen-label="Topbar">
          <div className="mk-topbar-left">
            <h1>Mahnung erstellen</h1>
            <span className="mk-crumb">Hausverwaltung · Forderungsmanagement</span>
          </div>
        </div>
        <main className="mk-main mh-main">
          <div className="mh-card">
            <strong>Keine mahnfähigen Mieter gefunden.</strong>
            <p className="mh-empty-hint">Für die aktuelle Auswahl wurden keine offenen Forderungen gefunden.</p>
          </div>
        </main>
      </div>
    );
  }

  if (!M?.vorlagen?.length) {
    return (
      <div className="mk-app mh-app is-regular">
        <div className="mk-topbar" data-screen-label="Topbar">
          <div className="mk-topbar-left">
            <h1>Mahnung erstellen</h1>
            <span className="mk-crumb">Hausverwaltung · Forderungsmanagement</span>
          </div>
        </div>
        <main className="mk-main mh-main">
          <div className="mh-card">
            <strong>Keine Mahnstufen konfiguriert.</strong>
            <p className="mh-empty-hint">Bitte legen Sie zuerst mindestens einen Dunning Type an.</p>
          </div>
        </main>
      </div>
    );
  }

  // Mieter aus URL ?party= vorauswählen
  const initialId = useMemoApp(() => {
    const p = new URLSearchParams(location.search).get("party");
    return M.mieter.find((m) => m.id === p)?.id || M.mieter[0].id;
  }, []);
  const initialInvoices = useMemoApp(() => {
    const raw = new URLSearchParams(location.search).get("invoices") || "";
    return new Set(raw.split(",").map((v) => decodeURIComponent(v.trim())).filter(Boolean));
  }, []);

  const [mieterId, setMieterId] = useStateApp(initialId);
  const mieter = useMemoApp(() => M.mieter.find((m) => m.id === mieterId), [mieterId]);
  const selectedPostenFor = (m, useUrlSelection = false) => {
    const all = (m?.posten || []).map((p) => p.beleg);
    if (!useUrlSelection || m.id !== initialId || !initialInvoices.size) return new Set(all);

    const available = new Set(all);
    const fromUrl = [...initialInvoices].filter((name) => available.has(name));
    return new Set(fromUrl.length ? fromUrl : all);
  };

  const [vorlageKey, setVorlageKey] = useStateApp(() => mieter.empf_vorlage || M.naechsteVorlageKey(mieter.mahnstufe));

  // Eigene, benannte Vorlagen (frei anlegbar, persistent)
  const [customVorlagen, setCustomVorlagen] = useStateApp(() => {
    try { return JSON.parse(localStorage.getItem("mh_custom_vorlagen") || "[]"); } catch { return []; }
  });
  useEffectApp(() => {
    try { localStorage.setItem("mh_custom_vorlagen", JSON.stringify(customVorlagen)); } catch {}
  }, [customVorlagen]);

  // alle Vorlagen + Lookup (Standard zuerst, eigene danach)
  const alleVorlagen = useMemoApp(() => [...M.vorlagen, ...customVorlagen], [customVorlagen]);
  const vorlageMap = useMemoApp(() => Object.fromEntries(alleVorlagen.map((v) => [v.key, v])), [alleVorlagen]);
  const vorlage = vorlageMap[vorlageKey] || M.vorlagen[0];

  const [mahndatum, setMahndatum] = useStateApp(M.TODAY);
  const [kanal, setKanal] = useStateApp("Brief");
  const [selected, setSelected] = useStateApp(() => selectedPostenFor(mieter, true));
  const [gebuehr, setGebuehr] = useStateApp(vorlage.gebuehr);
  const [zinsenAktiv, setZinsenAktiv] = useStateApp(vorlage.zinsen);
  const [zinssatz, setZinssatz] = useStateApp(M.zinssatzFuer(mieter.verbrauchertyp));
  const [fristTage, setFristTage] = useStateApp(7);
  const [kontonummer, setKontonummer] = useStateApp(M.absender.iban);
  const [varValues, setVarValues] = useStateApp({});
  const [betreff, setBetreff] = useStateApp(vorlage.betreff);
  const [anrede, setAnrede] = useStateApp(mieter.anrede);
  const [einleitung, setEinleitung] = useStateApp(vorlage.einleitung);
  const [schluss, setSchluss] = useStateApp(vorlage.schluss);

  // Sortierung/Filter der Postenliste
  const [postenSort, setPostenSort] = useStateApp("faellig");
  const [postenDir, setPostenDir] = useStateApp("asc");
  const [postenSearch, setPostenSearch] = useStateApp("");
  const [nurUeberfaellig, setNurUeberfaellig] = useStateApp(false);

  const [toast, setToast] = useStateApp(null);
  const [sent, setSent] = useStateApp(null);
  const [pastDetail, setPastDetail] = useStateApp(null);
  const [viewEntry, setViewEntry] = useStateApp(null); // gebuchte Mahnung im Editor (gesperrt)

  // Vorlagen-Variablen initialisieren (frist_tage, mahngebuehr, kontonummer, generisch)
  const parseGeld = (s) => parseFloat(String(s).replace(/\./g, "").replace(",", ".")) || 0;
  const initVariablen = (v) => {
    const vars = v.variablen || [];
    const fr = vars.find((x) => x.name === "frist_tage");
    setFristTage(fr ? (parseInt(fr.default, 10) || 7) : 7);
    const kn = vars.find((x) => x.name === "kontonummer");
    setKontonummer(kn ? kn.default : M.absender.iban);
    const rest = {};
    vars.forEach((x) => {
      if (!["frist_tage", "mahngebuehr", "kontonummer"].includes(x.name)) rest[x.name] = x.default || "";
    });
    setVarValues(rest);
  };

  // generischer Zugriff auf einen Variablenwert (mit Bindung an bestehende States)
  const getVarVal = (name) =>
    name === "frist_tage" ? String(fristTage)
    : name === "mahngebuehr" ? String(gebuehr)
    : name === "kontonummer" ? kontonummer
    : (varValues[name] ?? "");
  const setVarVal = (name, raw) => {
    if (name === "frist_tage") setFristTage(parseInt(raw, 10) || 0);
    else if (name === "mahngebuehr") setGebuehr(parseGeld(raw));
    else if (name === "kontonummer") setKontonummer(raw);
    else setVarValues((m) => ({ ...m, [name]: raw }));
  };

  // reine Textvariablen der Vorlage (Frist + Gebühr sind Mahnungs-Felder, nicht hier)
  const textVariablen = (vorlage.variablen || []).filter(
    (x) => !["frist_tage", "mahngebuehr"].includes(x.name)
  );

  // Editor frisch aufsetzen (für aktuellen Mieter)
  const setupFresh = (m, options = {}) => {
    const empf = m.empf_vorlage || M.naechsteVorlageKey(m.mahnstufe);
    setVorlageKey(empf);
    setSelected(selectedPostenFor(m, !!options.useUrlSelection));
    setZinssatz(M.zinssatzFuer(m.verbrauchertyp));
    setAnrede(m.anrede);
    const v = M.vorlageByKey[empf];
    setBetreff(v.betreff); setEinleitung(v.einleitung); setSchluss(v.schluss);
    setGebuehr(v.gebuehr); setZinsenAktiv(v.zinsen);
    setMahndatum(M.TODAY); setKanal("Brief");
    initVariablen(v);
    setViewEntry(null);
  };

  // Mieterwechsel → alles neu aufsetzen
  useEffectApp(() => { setupFresh(mieter, { useUrlSelection: true }); }, [mieterId]);

  // Gebuchte Mahnung in der großen Seite öffnen → gesperrte Ansicht
  const openInEditor = (entry) => {
    applyVorlage(entry.vorlageKey);
    setMahndatum(entry.datum);
    const days = Math.max(1, Math.round((new Date(entry.frist) - new Date(entry.datum)) / 86400000));
    setFristTage(days);
    setKanal(entry.kanal);
    setGebuehr(entry.gebuehr);
    setZinsenAktiv(entry.zinsBetrag > 0);
    setSelected(new Set(entry.belege.map((b) => b.beleg)));
    setViewEntry(entry);
    setPastDetail(null);
    window.scrollTo(0, 0);
  };

  // Vorlagenwechsel → Textbausteine + Gebühr/Zinsen laden (Mieter bleibt)
  const applyVorlage = (key) => {
    setVorlageKey(key);
    const v = vorlageMap[key] || M.vorlageByKey[key];
    if (!v) return;
    setBetreff(v.betreff); setEinleitung(v.einleitung); setSchluss(v.schluss);
    setGebuehr(v.gebuehr); setZinsenAktiv(v.zinsen);
    initVariablen(v);
  };

  // aktuelle Eingaben als eigene, benannte Vorlage speichern
  const saveAsVorlage = () => {
    const name = (window.prompt("Name der neuen Vorlage:", "Eigene Vorlage " + (customVorlagen.length + 1)) || "").trim();
    if (!name) return;
    const key = "custom_" + Date.now();
    const neu = { key, label: name, custom: true, stufe_nr: null, ton: "frei",
      gebuehr, zinsen: zinsenAktiv, betreff, einleitung, schluss,
      variablen: vorlage.variablen || [] };
    setCustomVorlagen((arr) => [...arr, neu]);
    setVorlageKey(key);
    setToast(`Vorlage „${name}" gespeichert`);
  };

  const deleteVorlage = (key) => {
    setCustomVorlagen((arr) => arr.filter((v) => v.key !== key));
    if (vorlageKey === key) applyVorlage(M.naechsteVorlageKey(mieter.mahnstufe));
  };

  const togglePosten = (beleg) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(beleg) ? next.delete(beleg) : next.add(beleg);
      return next;
    });
  };

  // sortierte Vollliste — bestimmt auch die Reihenfolge im Brief
  const sortedPosten = useMemoApp(() => {
    const arr = [...mieter.posten];
    const cmp = (a, b) => {
      let r = 0;
      if (postenSort === "alter") r = b.overdue_days - a.overdue_days;
      else if (postenSort === "betrag") r = b.offen - a.offen;
      else if (postenSort === "beleg") r = a.beleg.localeCompare(b.beleg);
      else r = (a.faellig || "").localeCompare(b.faellig || "");
      if (r === 0) r = (a.faellig || "").localeCompare(b.faellig || "");
      return postenDir === "desc" ? -r : r;
    };
    return arr.sort(cmp);
  }, [mieter, postenSort, postenDir]);

  // gefilterte Anzeige (Auswahl bleibt davon unberührt)
  const displayPosten = useMemoApp(() => {
    let arr = sortedPosten;
    if (nurUeberfaellig) arr = arr.filter((p) => p.overdue_days > 0);
    if (postenSearch.trim()) {
      const q = postenSearch.toLowerCase();
      arr = arr.filter((p) => p.beleg.toLowerCase().includes(q) || (p.bez || "").toLowerCase().includes(q));
    }
    return arr;
  }, [sortedPosten, nurUeberfaellig, postenSearch]);

  const selectVisible = () => setSelected((prev) => {
    const n = new Set(prev); displayPosten.forEach((p) => n.add(p.beleg)); return n;
  });
  const clearVisible = () => setSelected((prev) => {
    const n = new Set(prev); displayPosten.forEach((p) => n.delete(p.beleg)); return n;
  });

  const locked = !!viewEntry;

  // Posten-Snapshot der gebuchten Mahnung (mit den gebuchten Beträgen)
  const lockedPosten = useMemoApp(() => {
    if (!viewEntry) return [];
    return viewEntry.belege.map((b) => {
      const src = mieter.posten.find((p) => p.beleg === b.beleg) || {};
      return {
        beleg: b.beleg, offen: b.betrag, betrag: b.betrag,
        art: src.art || "Sales Invoice", bez: src.bez || "Gemahnter Posten",
        faellig: src.faellig || viewEntry.datum, posting: src.posting || src.faellig || viewEntry.datum,
        overdue_days: src.overdue_days || 0, bezahlt: 0,
      };
    });
  }, [viewEntry, mieter]);

  const livePosten = useMemoApp(
    () => sortedPosten.filter((p) => selected.has(p.beleg)),
    [sortedPosten, selected]
  );
  const posten = locked ? lockedPosten : livePosten;

  const frist = locked ? viewEntry.frist : addDays_mh(mahndatum, fristTage);
  const verwendungszweck = `${mieter.id} · Mahnung ${fmtDate_mh(mahndatum)}`;

  // Beträge — im View-Modus die gebuchten Werte
  const hauptforderung = locked ? viewEntry.hauptforderung : posten.reduce((a, p) => a + p.offen, 0);
  const zinsBetrag = locked ? viewEntry.zinsBetrag
    : (zinsenAktiv ? Math.round(posten.reduce((a, p) => a + p.offen * (zinssatz / 100) * (p.overdue_days / 365), 0) * 100) / 100 : 0);
  const gebuehrEff = locked ? viewEntry.gebuehr : gebuehr;
  const summe = locked ? viewEntry.summe : Math.round((hauptforderung + zinsBetrag + gebuehrEff) * 100) / 100;

  const letterData = {
    mieter, vorlageLabel: vorlage.label,
    mahndatum, frist, kanal, anrede, betreff, einleitung, schluss,
    posten, hauptforderung, zinsBetrag,
    zinsenAktiv: locked ? viewEntry.zinsBetrag > 0 : zinsenAktiv,
    zinssatz, gebuehr: gebuehrEff, summe,
    kontonummer,
    verwendungszweck,
  };

  // ── Dunning-Draft anlegen ──
  const doSend = async (options = {}) => {
    if (posten.length === 0) { setToast("Bitte mindestens einen Posten auswählen."); return; }
    const finalize = options.finalize !== false;

    // Produktions-Bridge: existiert window.MAHN_ACTIONS (Frappe-Page), echte
    // Aktion auslösen; sonst lokaler Studio-Mock. (siehe mahn-action-handlers.js)
    if (window.MAHN_ACTIONS && window.MAHN_ACTIONS.createDunning) {
      try {
        const r = await window.MAHN_ACTIONS.createDunning({
          party: mieter.id, vorlageKey, tpl_id: vorlage.tpl_id,
          mahndatum, fristTage, kanal,
          belege: posten.map((p) => p.beleg),
          mahngebuehr: gebuehr, zinssatz, zinsenAktiv,
          kontonummer, variablen: varValues, summe, finalize,
        });
        const docs = r.docs || [{ id: r.dunning, desc: `Dunning-Doc · ${vorlage.label}`, amount: r.summe }];
        setSent({ vorlage: vorlage.label, mieter: mieter.name, kanal, docs, summe: r.summe ?? summe, draft: !!r.draft, email_queue: r.email_queue });
      } catch (e) {
        setToast("Fehler beim Erstellen: " + (e && e.message ? e.message : e));
      }
      return;
    }

    // Studio-Mock
    const docs = [
      { id: "DUN-2026-0091", desc: `Dunning-Doc · ${vorlage.label} · ${mieter.name}`, amount: summe },
    ];
    if (gebuehr > 0) docs.push({ id: "ACC-JV-2026-00118", desc: `Journal Entry · Mahngebühr auf ${M.absender.konto_erloese_mahn.split(" — ")[0]}`, amount: gebuehr });
    if (zinsenAktiv && zinsBetrag > 0) docs.push({ id: "ACC-JV-2026-00119", desc: "Journal Entry · Verzugszinsen", amount: zinsBetrag });
    docs.push({ id: "Mahnung.pdf", desc: `PDF-Anhang · ${kanal}`, amount: null });
    setSent({ vorlage: vorlage.label, mieter: mieter.name, kanal, docs, summe });
  };

  const cancelCurrentDunning = async () => {
    if (!viewEntry?.beleg) return;
    if (!window.MAHN_ACTIONS?.cancelDunning) {
      setToast("Storno ist in dieser Umgebung nicht angebunden.");
      return;
    }
    const confirmed = !frappe?.confirm || await new Promise((resolve) => {
      frappe.confirm(
        `Mahnung ${viewEntry.beleg} wirklich stornieren?`,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;
    try {
      const result = await window.MAHN_ACTIONS.cancelDunning(viewEntry.beleg);
      mieter.historie = (mieter.historie || []).filter((h) => h.beleg !== viewEntry.beleg);
      setViewEntry(null);
      setPastDetail(null);
      setupFresh(mieter);
      const feeHint = result?.fee_sales_invoice ? ` · Mahngebühr-Rechnung ${result.fee_sales_invoice} wurde mitstorniert` : "";
      setToast(`Mahnung ${viewEntry.beleg} storniert${feeHint}.`);
    } catch (e) {
      setToast("Fehler beim Stornieren: " + (e && e.message ? e.message : e));
    }
  };

  const openTemplateEditor = () => {
    const template = vorlage.serienbrief_vorlage;
    if (window.MAHN_ACTIONS?.openSerienbriefEditor) {
      const opened = window.MAHN_ACTIONS.openSerienbriefEditor(template);
      if (!opened) setToast("Für diese Mahnstufe ist keine Serienbrief-Vorlage hinterlegt.");
      return;
    }
    setToast("Serienbrief-Editor ist in dieser Umgebung nicht angebunden.");
  };

  const layoutClass =
    t.layout === "Brief links" ? "is-letter-left" :
    t.layout === "Gestapelt" ? "is-stacked" : "is-letter-right";

  return (
    <div className={`mk-app mh-app ${t.papier ? "is-papier" : ""} is-${t.density}`}>
      {/* Topbar */}
      <div className="mk-topbar" data-screen-label="Topbar">
        <div className="mk-topbar-left">
          <h1>Mahnung erstellen</h1>
          <span className="mk-crumb">Hausverwaltung · Forderungsmanagement</span>
        </div>
        <div className="mk-topbar-actions">
          <a className="mk-btn mk-btn-ghost" href="/app/op-workflow?view=mahnwesen">← Mahnwesen</a>
          <a className="mk-btn mk-btn-ghost" href="Mieterkonto Report.html">Mieterkonto</a>
          <button className="mk-btn mk-btn-ghost" onClick={() => window.print()}>Drucken</button>
          <button className="mk-btn" onClick={() => doSend({ finalize: false })} disabled={locked}>Als Draft speichern</button>
          <button className="mk-btn mk-btn-primary" onClick={() => doSend()} disabled={locked}>
            {kanal.includes("E-Mail") ? "Erstellen & E-Mail einreihen" : "Erstellen & PDF erzeugen"}
          </button>
        </div>
      </div>

      <main className="mk-main mh-main" data-screen-label={`Mahnung · ${mieter.name}`}>
        {/* Mieter-Kopf */}
        <div className="mh-tenant">
          <div className="mh-tenant-main">
            <div className="mh-tenant-kicker">Mahnempfänger</div>
            <div className="mh-tenant-row">
              <select className="mh-tenant-select" value={mieterId} disabled={locked} onChange={(e) => setMieterId(e.target.value)}>
                {M.mieter.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
              <StufeBadgeMH stufe={mieter.mahnstufe} label={`Erreichte Stufe: M${mieter.mahnstufe}`} />
              <span className="mh-tenant-typ">{mieter.verbrauchertyp === "gewerbe" ? "Gewerbe · §288 II BGB" : "Privat · §288 I BGB"}</span>
            </div>
            <div className="mh-tenant-meta">
              <div><span>Kundennr.</span>{mieter.id}</div>
              <div><span>Objekt</span>{mieter.objekt}</div>
              <div><span>Einheit</span>{mieter.einheit}</div>
              <div><span>E-Mail</span>{mieter.email}</div>
            </div>
          </div>
          <div className="mh-tenant-hist">
            <div className="mh-tenant-hist-label">Mahnhistorie</div>
            {mieter.historie.length === 0 && <div className="mh-hist-empty">Noch keine Mahnung</div>}
            {mieter.historie.map((h, i) => (
              <button type="button" className="mh-hist-item" key={i} onClick={() => setPastDetail(h)}
                title="Gebuchte Mahnung ansehen">
                <span className="mh-hist-date">{fmtDate_mh(h.datum)}</span>
                <span className="mh-hist-stufe">{h.stufe}</span>
                <span className="mh-hist-go">ansehen →</span>
                <span className="mh-hist-kanal">{h.beleg} · {h.kanal}</span>
              </button>
            ))}
          </div>
        </div>

        {locked && (
          <div className="mh-locked-banner">
            <div className="mh-locked-banner-text">
              <span className="mh-locked-badge">Gebucht</span>
              <span><strong>Mahnung {viewEntry.beleg}</strong> · {viewEntry.stufe} vom {fmtDate_mh(viewEntry.datum)} — schreibgeschützt. Gebühr, Zinsen, Posten und Text sind festgeschrieben.</span>
            </div>
            <div className="mh-locked-banner-actions">
              <button className="mk-btn" onClick={cancelCurrentDunning}>Stornieren</button>
              <button className="mk-btn" onClick={() => { setViewEntry(null); setToast("Entsperrt — jetzt als neue Mahnung bearbeitbar"); }}>Als neue Mahnung bearbeiten</button>
              <button className="mk-btn mk-btn-primary" onClick={() => { setupFresh(mieter); window.scrollTo(0, 0); }}>Schließen</button>
            </div>
          </div>
        )}

        {/* Split: Editor + Brief */}
        <div className={`mh-split ${layoutClass}`}>
          {/* ───────── Editor ───────── */}
          <div className="mh-editor">

            {/* 1 · Serienbrief-Vorlage & Versand */}
            <div className="mh-card">
              <SectionMH n="1" title="Serienbrief-Vorlage &amp; Versand"
                right={!locked && (
                  <div className="mh-vorlage-head-actions">
                    <button type="button" className="mh-add-btn"
                      onClick={openTemplateEditor}>Im Editor bearbeiten ↗</button>
                    <button type="button" className="mh-add-btn" onClick={saveAsVorlage}>＋ Als Vorlage sichern</button>
                  </div>
                )} />
              <FieldMH label={'Vorlage wählen · Bibliothek › Kategorie „Mahnungen"'} full
                hint={`Empfohlen nach erreichter Stufe M${mieter.mahnstufe}: „${M.vorlageByKey[mieter.empf_vorlage || M.naechsteVorlageKey(mieter.mahnstufe)].label}". Alle Vorlagen stammen aus dem Serienbrief-Modul.`}>
                <div className="mh-vorlage-pick">
                  <select className="mh-vorlage-select" value={vorlageKey} disabled={locked}
                    onChange={(e) => applyVorlage(e.target.value)}>
                    <optgroup label="Kategorie · Mahnungen">
                      {M.vorlagen.map((v) => (
                        <option key={v.key} value={v.key}>
                          {v.label}{(mieter.empf_vorlage || M.naechsteVorlageKey(mieter.mahnstufe)) === v.key ? "  ★ empfohlen" : ""}
                        </option>
                      ))}
                    </optgroup>
                    {customVorlagen.length > 0 && (
                      <optgroup label="Eigene Vorlagen">
                        {customVorlagen.map((v) => (
                          <option key={v.key} value={v.key}>{v.label}</option>
                        ))}
                      </optgroup>
                    )}
                  </select>
                  {!locked && vorlageKey !== (mieter.empf_vorlage || M.naechsteVorlageKey(mieter.mahnstufe)) && (
                    <button type="button" className="mh-mini-btn" title="Empfohlene Vorlage wählen"
                      onClick={() => applyVorlage(mieter.empf_vorlage || M.naechsteVorlageKey(mieter.mahnstufe))}>★ Empfehlung</button>
                  )}
                  {!locked && vorlage.custom && (
                    <button type="button" className="mh-mini-btn" title="Eigene Vorlage löschen"
                      onClick={() => deleteVorlage(vorlageKey)}>Löschen</button>
                  )}
                </div>
                <div className="mh-vorlage-meta">
                  <span className="mono">{vorlage.tpl_id || "eigene Vorlage"}</span>
                  <span>{vorlage.modified || "gespeichert"}</span>
                  <span>{vorlage.gebuehr > 0 ? `${fmtEUR_mh(vorlage.gebuehr)} Gebühr` : "keine Gebühr"}{vorlage.zinsen ? " · Verzugszinsen" : ""}</span>
                  {vorlage.custom && <span className="is-custom">eigene Vorlage</span>}
                </div>
              </FieldMH>
              <div className="mh-field-row">
                <FieldMH label="Mahndatum">
                  <input type="date" className="mh-input" value={mahndatum} disabled={locked} onChange={(e) => setMahndatum(e.target.value)} />
                </FieldMH>
                <FieldMH label="Zahlungsfrist" hint={`Fällig am ${fmtDate_mh(frist)}`}>
                  <div className="mh-input-suffix">
                    <input type="number" min="1" className="mh-input" value={fristTage} disabled={locked}
                      onChange={(e) => setFristTage(parseInt(e.target.value) || 0)} />
                    <span>Tage</span>
                  </div>
                </FieldMH>
                <FieldMH label="Versandweg">
                  {locked ? (
                    <div className="mh-locked-val">{kanal}</div>
                  ) : (
                    <div className="mh-seg">
                      {KANAELE.map((k) => (
                        <button key={k} type="button"
                          className={`mh-seg-btn ${kanal === k ? "is-active" : ""}`}
                          onClick={() => setKanal(k)}>{k}</button>
                      ))}
                    </div>
                  )}
                </FieldMH>
              </div>
            </div>

            {/* 2 · Überfällige Posten */}
            <div className="mh-card">
              <SectionMH n="2" title="Überfällige Posten"
                right={<span className="mh-card-aside">{locked ? `${posten.length} Posten · gebucht` : `${posten.length} / ${mieter.posten.length} gewählt`} · Σ {fmtEUR_mh(hauptforderung)}</span>} />
              {!locked && (
              <div className="mh-posten-toolbar">
                <div className="mh-posten-sort">
                  <select className="mh-mini-select" value={postenSort} onChange={(e) => setPostenSort(e.target.value)}>
                    <option value="faellig">Fälligkeit</option>
                    <option value="alter">Alter (Tage)</option>
                    <option value="betrag">Offener Betrag</option>
                    <option value="beleg">Belegnummer</option>
                  </select>
                  <button type="button" className="mh-mini-btn" title="Richtung umkehren"
                    onClick={() => setPostenDir((d) => d === "asc" ? "desc" : "asc")}>
                    {postenDir === "asc" ? "↑" : "↓"}
                  </button>
                </div>
                <input className="mh-mini-search" placeholder="Beleg oder Text suchen…"
                  value={postenSearch} onChange={(e) => setPostenSearch(e.target.value)} />
                <label className="mh-mini-check">
                  <input type="checkbox" checked={nurUeberfaellig} onChange={(e) => setNurUeberfaellig(e.target.checked)} />
                  nur überfällige
                </label>
                <span className="mh-posten-toolbar-spacer" />
                <button type="button" className="mh-mini-btn" onClick={selectVisible}>Alle</button>
                <button type="button" className="mh-mini-btn" onClick={clearVisible}>Keine</button>
              </div>
              )}
              <div className="mh-posten">
                {!locked && displayPosten.length === 0 && (
                  <p className="mh-empty-hint">Kein Posten passt zu Suche/Filter.</p>
                )}
                {(locked ? lockedPosten : displayPosten).map((p) => {
                  const on = locked || selected.has(p.beleg);
                  return (
                    <label key={p.beleg} className={`mh-posten-row ${on ? "is-on" : ""} ${locked ? "is-locked" : ""}`}>
                      <input type="checkbox" checked={on} disabled={locked} onChange={() => !locked && togglePosten(p.beleg)} />
                      <div className="mh-posten-main">
                        <div className="mh-posten-beleg">{p.beleg}<span className="mh-posten-art">{p.art}</span></div>
                        <div className="mh-posten-bez">{p.bez}</div>
                      </div>
                      <div className="mh-posten-due">
                        <AgePillMH days={p.overdue_days} />
                        <span className="mh-posten-faellig">fällig {fmtDate_mh(p.faellig)}</span>
                      </div>
                      <div className="mh-posten-amt">
                        {fmtEUR_mh(p.offen)}
                        {p.bezahlt > 0 && <span className="mh-posten-part">von {fmtEUR_mh(p.betrag)}</span>}
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>

            {/* 3 · Gebühr & Zinsen (Mahnung-Objekt — erzeugt Buchungen) */}
            <div className="mh-card">
              <SectionMH n="3" title="Gebühr &amp; Verzugszinsen"
                right={<span className="mh-card-aside">erzeugt Buchungen</span>} />
              <div className="mh-field-row">
                <FieldMH label="Mahngebühr (€)" hint={`bucht auf ${M.absender.konto_erloese_mahn.split(" — ")[0]}`}>
                  <input type="number" step="0.50" min="0" className="mh-input" value={gebuehr} disabled={locked}
                    onChange={(e) => setGebuehr(parseFloat(e.target.value) || 0)} />
                </FieldMH>
                <FieldMH label="Verzugszinssatz (% p. a.)" hint={`Basiszins ${fmtNum_mh(M.BASISZINS)} % + ${mieter.verbrauchertyp === "gewerbe" ? "9" : "5"} %-Punkte`}>
                  <input type="number" step="0.01" min="0" className="mh-input" value={zinssatz}
                    disabled={locked || !zinsenAktiv}
                    onChange={(e) => setZinssatz(parseFloat(e.target.value) || 0)} />
                </FieldMH>
                <FieldMH label="Verzugszinsen">
                  <label className="mh-check-inline">
                    <input type="checkbox" checked={zinsenAktiv} disabled={locked} onChange={(e) => setZinsenAktiv(e.target.checked)} />
                    berechnen ({fmtEUR_mh(zinsBetrag)})
                  </label>
                </FieldMH>
              </div>
            </div>

            {/* 4 · Vorlagen-Variablen (reine Textersetzung) */}
            <div className="mh-card">
              <SectionMH n="4" title="Vorlagen-Variablen"
                right={<span className="mh-card-aside">{textVariablen.length} aus der Vorlage</span>} />
              {textVariablen.length === 0 && (
                <p className="mh-empty-hint">Diese Vorlage hat keine zusätzlichen Textvariablen.</p>
              )}
              {textVariablen.length > 0 && (
                <div className="mh-var-grid">
                  {textVariablen.map((va) => (
                    <FieldMH key={va.name} label={va.name} hint={va.desc}>
                      {va.type === "Datum" ? (
                        <input type="date" className="mh-input" value={getVarVal(va.name)} disabled={locked}
                          onChange={(e) => setVarVal(va.name, e.target.value)} />
                      ) : va.type === "Zahl" ? (
                        <input type="number" step="1" min="0" className="mh-input" value={getVarVal(va.name)} disabled={locked}
                          onChange={(e) => setVarVal(va.name, e.target.value)} />
                      ) : (
                        <input type="text" className="mh-input" value={getVarVal(va.name)} disabled={locked}
                          onChange={(e) => setVarVal(va.name, e.target.value)} />
                      )}
                    </FieldMH>
                  ))}
                </div>
              )}
              <p className="mh-var-note">
                Frist und Mahngebühr stehen oben als Mahnungs-Felder, da sie Fälligkeit und Buchung beeinflussen. Betreff &amp; Brieftext werden im Serienbrief-Editor gepflegt.
              </p>
            </div>
          </div>

          {/* ───────── Brief-Spalte ───────── */}
          <div className="mh-letter-col">
            <LetterPreviewMH d={letterData} />
          </div>
        </div>
      </main>

      {/* Sticky Summen-/Aktionsleiste */}
      <div className={`mh-actionbar ${locked ? "is-locked" : ""}`}>
        <div className="mh-actionbar-breakdown">
          <span><em>Hauptforderung</em>{fmtEUR_mh(hauptforderung)}</span>
          {zinsBetrag > 0 && <span><em>+ Zinsen</em>{fmtEUR_mh(zinsBetrag)}</span>}
          {gebuehrEff > 0 && <span><em>+ Gebühr</em>{fmtEUR_mh(gebuehrEff)}</span>}
        </div>
        <div className="mh-actionbar-right">
          <div className="mh-actionbar-total">
            <span>{locked ? `Gebucht am ${fmtDate_mh(viewEntry.datum)}` : `Zahlbetrag bis ${fmtDate_mh(frist)}`}</span>
            <strong>{fmtEUR_mh(summe)}</strong>
          </div>
          {locked ? (
            <button className="mk-btn mh-actionbar-cta" onClick={() => { setupFresh(mieter); window.scrollTo(0, 0); }}>
              Ansicht schließen
            </button>
          ) : (
            <button className="mk-btn mk-btn-primary mh-actionbar-cta" onClick={() => doSend()}>
              {kanal.includes("E-Mail") ? `${vorlage.label} erstellen & E-Mail einreihen →` : `${vorlage.label} erstellen & PDF erzeugen →`}
            </button>
          )}
        </div>
      </div>

      <MHTweaksPanel title="Tweaks">
        <MHTweakSection label="Layout" />
        <MHTweakRadio label="Brief-Position" value={t.layout}
          options={["Brief rechts", "Brief links", "Gestapelt"]}
          onChange={(v) => setTweak("layout", v)} />
        <MHTweakRadio label="Dichte" value={t.density}
          options={["compact", "regular", "comfy"]}
          onChange={(v) => setTweak("density", v)} />
        <MHTweakSection label="Brief" />
        <MHTweakToggle label="Papier-Look (Schatten, A4-Blatt)" value={t.papier}
          onChange={(v) => setTweak("papier", v)} />
      </MHTweaksPanel>

      {toast && <ToastMH message={toast} onClose={() => setToast(null)} />}
      {sent && <SentOverlayMH data={sent} onClose={() => setSent(null)} />}
      {pastDetail && (
        <PastDunningOverlayMH
          entry={pastDetail}
          mieterName={mieter.name}
          onClose={() => setPastDetail(null)}
          onOpenFull={openInEditor}
          onReuse={(entry) => {
            applyVorlage(entry.vorlageKey);
            const valid = new Set(mieter.posten.map((p) => p.beleg));
            setSelected(new Set(entry.belege.map((b) => b.beleg).filter((b) => valid.has(b))));
            setPastDetail(null);
            setToast(`Vorlage „${M.vorlageByKey[entry.vorlageKey].label}" übernommen — Felder geladen`);
          }}
        />
      )}
    </div>
  );
}

window.MH_RENDER = function renderMahnungWorkflow() {
  const rootEl = document.getElementById("mahnung-workflow-root") || document.getElementById("root");
  if (!rootEl) return;
  if (window.__MH_REACT_ROOT) {
    try {
      window.__MH_REACT_ROOT.unmount();
    } catch (err) {
      // The previous mount point may already have been replaced by Frappe.
    }
  }
  window.__MH_REACT_ROOT = ReactDOM.createRoot(rootEl);
  window.__MH_REACT_ROOT.render(<MahnApp />);
};

window.MH_RENDER();
