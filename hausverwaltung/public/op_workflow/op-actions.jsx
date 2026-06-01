// op-actions.jsx — Aktionen und Modals für den Offene-Posten-Report.
const { useState: useStateAct, useEffect: useEffectAct } = React;

function canCreateDunningFor(row) {
  const isSalesInvoice = String(row.belegart || "").replace(/ \(×\d+\)$/, "") === "Sales Invoice";
  if (row.status === "Written Off") return false;
  if (row.art !== "Forderungen" || !isSalesInvoice) return false;
  if (row.offen <= 0.01 || row.alter_tage <= 0) return false;
  return (row.mahnstufe || 0) < 4;
}

function isOverdueSalesInvoiceReceivable(row) {
  const isSalesInvoice = String(row.belegart || "").replace(/ \(×\d+\)$/, "") === "Sales Invoice";
  return (
    row.status !== "Written Off" &&
    row.art === "Forderungen" &&
    isSalesInvoice &&
    row.offen > 0.01 &&
    row.alter_tage > 0
  );
}

// Wählt die *primäre* Aktion pro Zeile basierend auf Status/Art/Mahnstufe.
function primaryActionFor(row) {
  // Bereits abgeschrieben → keine primäre Aktion
  if (row.status === "Written Off") return null;

  // Lieferanten-Rechnung
  if (row.art === "Rechnungen" && row.offen > 0) {
    return { key: "zahlung_anlegen", label: "Zahlung anlegen", kind: "primary" };
  }

  // Vorauszahlung (Payment Entry, unallocated)
  if (row.belegart === "Payment Entry") {
    return { key: "zuordnen", label: "Zuordnen", kind: "warn" };
  }

  // Mieter-Guthaben aus einer Credit Note / negativen Sales Invoice.
  if (row.art === "Forderungen" && row.belegart === "Sales Invoice" && row.offen < -0.01) {
    return { key: "guthaben_auszahlen", label: "Guthaben auszahlen", kind: "ghost" };
  }

  // Forderung, überfällig: erst ins Mahnwesen drillen. Dort sieht man Historie
  // und erstellt die nächste Mahnung explizit.
  if (isOverdueSalesInvoiceReceivable(row)) {
    const nextStufe = (row.mahnstufe || 0) + 1;
    if (nextStufe <= 4) {
      return {
        key: "mahnwesen",
        label: "Mahnwesen",
        kind: nextStufe >= 2 ? "late" : "primary",
      };
    }
    return { key: "inkasso", label: "An Inkasso", kind: "late" };
  }

  // Forderung noch nicht fällig → keine primäre Aktion
  return null;
}

function ActionCell({ row, onAction }) {
  const [menuOpen, setMenuOpen] = useStateAct(false);
  const primary = primaryActionFor(row);

  useEffectAct(() => {
    if (!menuOpen) return;
    const onClick = () => setMenuOpen(false);
    window.addEventListener("click", onClick);
    return () => window.removeEventListener("click", onClick);
  }, [menuOpen]);

  return (
    <div className="op-row-actions" onClick={(e) => e.stopPropagation()}>
      {primary && (
        <button
          className={`op-action-btn is-${primary.kind}`}
          onClick={() => onAction(primary.key, row)}
        >
          {primary.label}
        </button>
      )}
      <div className="op-action-wrap">
        <button className="op-action-more" onClick={(e) => { e.stopPropagation(); setMenuOpen(o => !o); }}>
          ⋯
        </button>
        {menuOpen && (
          <div className="op-action-menu">
            <button className="op-action-menu-item" onClick={() => onAction("mieterkonto", row)}>
              → Mieterkonto öffnen
              <span className="op-action-menu-shortcut">↗</span>
            </button>
            <button className="op-action-menu-item" onClick={() => onAction("beleg", row)}>
              → Beleg öffnen
            </button>
            {canCreateDunningFor(row) && (
              <button className="op-action-menu-item" onClick={() => onAction("mahnung", row)}>
                Mahnung erstellen…
              </button>
            )}
            {row.art === "Forderungen" && (
              <button className="op-action-menu-item" onClick={() => onAction("kontakt", row)}>
                Mieter anrufen / mailen
              </button>
            )}
            <div className="op-action-menu-sep" />
            <button className="op-action-menu-item" onClick={() => onAction("notiz", row)}>
              Notiz hinzufügen
            </button>
            <button className="op-action-menu-item" onClick={() => onAction("stundung", row)}>
              Stundung vereinbaren
            </button>
            <button className="op-action-menu-item" onClick={() => onAction("klärung", row)}>
              Auf „in Klärung" setzen
            </button>
            <div className="op-action-menu-sep" />
            {row.can_write_off && (
              <button className="op-action-menu-item is-danger" onClick={() => onAction("abschreiben", row)}>
                Abschreiben…
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ───────── Modal-Shell ─────────

function Modal({ title, subtitle, onClose, footer, children }) {
  useEffectAct(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="op-modal-backdrop" onClick={onClose}>
      <div className="op-modal" onClick={(e) => e.stopPropagation()}>
        <div className="op-modal-head">
          <div>
            <h3>{title}</h3>
            {subtitle && <div className="op-modal-sub">{subtitle}</div>}
          </div>
          <button className="op-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="op-modal-body">{children}</div>
        {footer && <div className="op-modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

// ───────── Aktion: Mahnung erstellen ─────────

function MahnungModal({ row, rows, selectedInvoiceNames, onClose, onDone }) {
  const nextStufe = (row.mahnstufe || 0) + 1;
  const [mahngebuehr, setMahngebuehr] = useStateAct(nextStufe === 1 ? 0.00 : nextStufe === 2 ? 5.00 : nextStufe === 3 ? 10.00 : 15.00);
  const [zinsen, setZinsen] = useStateAct(true);
  const [zinssatz, setZinssatz] = useStateAct(9.12); // Basis + 9% gem. §288 BGB
  const [versand, setVersand] = useStateAct("Brief");
  const [zusatztext, setZusatztext] = useStateAct("");
  const [busy, setBusy] = useStateAct(false);
  const [neueFaelligkeit, setNeueFaelligkeit] = useStateAct(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });
  const suggestedDunningType = row.dunning_type || (nextStufe === 1 ? "Zahlungserinnerung - HP" : nextStufe === 2 ? "1. Mahnung - HP" : nextStufe === 3 ? "2. Mahnung - HP" : "Letzte Mahnung - HP");
  const [dunningTypes, setDunningTypes] = useStateAct([]);
  const [textStufe, setTextStufe] = useStateAct(suggestedDunningType);
  const [vorlagen, setVorlagen] = useStateAct([]);
  const [serienbriefVorlage, setSerienbriefVorlage] = useStateAct(row.serienbrief_vorlage || "");
  const mahnRows = rows?.length ? rows : [row];
  const [selectedInvoices, setSelectedInvoices] = useStateAct(() => new Set(
    selectedInvoiceNames?.length ? selectedInvoiceNames : [row.belegnummer]
  ));
  const [showInvoiceAdd, setShowInvoiceAdd] = useStateAct(false);
  const [invoiceSearch, setInvoiceSearch] = useStateAct("");
  const selectedRows = mahnRows.filter((item) => selectedInvoices.has(item.belegnummer));
  const selectedRow = selectedRows[0] || row;
  const selectedOpen = selectedRows.reduce((sum, item) => sum + (item.offen || 0), 0);
  const isBulk = selectedRows.length > 1;
  const addSearch = invoiceSearch.trim().toLowerCase();
  const addableRows = mahnRows
    .filter((item) => !selectedInvoices.has(item.belegnummer))
    .filter((item) =>
      !addSearch ||
      (item.belegnummer || "").toLowerCase().includes(addSearch) ||
      (item.bemerkungen || "").toLowerCase().includes(addSearch) ||
      (item.status || "").toLowerCase().includes(addSearch) ||
      (item.faellig_am || "").toLowerCase().includes(addSearch)
    )
    .slice(0, 20);

  useEffectAct(() => {
    let alive = true;
    Promise.all([
      window.OP_ACTIONS.listDunningTypes(),
      window.OP_ACTIONS.listSerienbriefVorlagen ? window.OP_ACTIONS.listSerienbriefVorlagen() : Promise.resolve([]),
    ])
      .then(([items, templates]) => {
        if (!alive) return;
        setDunningTypes(items);
        if (items.length && !items.includes(textStufe)) setTextStufe(items[0]);
        setVorlagen(templates || []);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Verzugszinsen-Berechnung (rein illustrativ)
  const zinsBetrag = zinsen ? selectedRows.reduce((sum, item) => sum + ((item.offen || 0) * (zinssatz / 100) * ((item.alter_tage || 0) / 365)), 0) : 0;

  const summe = selectedOpen + mahngebuehr + zinsBetrag;
  const partyName = window.OFFENE_POSTEN.partyName(row.party);
  const objekt = window.OFFENE_POSTEN.ccLabel[row.kostenstelle] || row.kostenstelle;
  const toggleInvoice = (invoiceName) => {
    setSelectedInvoices((prev) => {
      const next = new Set(prev);
      next.has(invoiceName) ? next.delete(invoiceName) : next.add(invoiceName);
      return next;
    });
  };
  const addInvoice = (invoiceName) => {
    setSelectedInvoices((prev) => {
      const next = new Set(prev);
      next.add(invoiceName);
      return next;
    });
  };
  const submit = async () => {
    if (!selectedRows.length) return;
    setBusy(true);
    try {
      const serienbriefWerte = zusatztext.trim()
        ? [{ variable: "zusatztext", wert: zusatztext.trim(), beschreibung: "Optionaler Text aus dem Mahn-Cockpit" }]
        : [];
      const result = isBulk
        ? await window.OP_ACTIONS.createBulkDunning({ [row.party]: selectedRows }, {
            dunningType: textStufe,
            neueFaelligkeit,
            mahngebuehr,
            zinsenAktiv: zinsen,
            serienbriefVorlage,
            serienbriefWerte,
          })
        : await window.OP_ACTIONS.createDunning(selectedRow, {
            dunningType: textStufe,
            neueFaelligkeit,
            mahngebuehr,
            zinsenAktiv: zinsen,
            serienbriefVorlage,
            serienbriefWerte,
          });
      onDone?.(result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`${nextStufe === 1 ? "Zahlungserinnerung" : nextStufe === 4 ? "Letzte Mahnung" : `${nextStufe - 1}. Mahnung`} erstellen`}
      subtitle={`${partyName} · ${row.belegnummer} · ${fmtEUR_op(row.offen)} offen seit ${row.alter_tage} Tagen`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Erzeugt {isBulk ? "1 Sammel-Dunning-Draft" : "1 Dunning-Draft"} · Mahngebühr-Rechnung beim Submit · 1 PDF
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose} disabled={busy}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={submit} disabled={busy || selectedRows.length === 0}>
              {busy ? "Draft wird angelegt …" : `${isBulk ? "Sammelmahnung" : "Mahnung"} als Draft anlegen · ${fmtEUR_op(summe)}`}
            </button>
          </div>
        </>
      }
    >
      <div className="op-form-grid">
        <div className="op-field">
          <label>Mahnstufe / Regel</label>
          {dunningTypes.length ? (
            <select value={textStufe} onChange={(e) => setTextStufe(e.target.value)}>
              {dunningTypes.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          ) : (
            <input value={textStufe} onChange={(e) => setTextStufe(e.target.value)} />
          )}
          {dunningTypes.includes(suggestedDunningType) && textStufe !== suggestedDunningType && (
            <button type="button" className="mk-btn mk-btn-ghost" style={{ marginTop: 6, padding: "4px 8px", fontSize: 11 }} onClick={() => setTextStufe(suggestedDunningType)}>
              Vorschlag wählen
            </button>
          )}
        </div>
        <div className="op-field">
          <label>Serienbrief-Vorlage</label>
          {vorlagen.length ? (
            <select value={serienbriefVorlage} onChange={(e) => setSerienbriefVorlage(e.target.value)}>
              <option value="">Default aus Mahnstufe</option>
              {vorlagen.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          ) : (
            <input value={serienbriefVorlage} placeholder="Default aus Mahnstufe" onChange={(e) => setSerienbriefVorlage(e.target.value)} />
          )}
        </div>
        <div className="op-field">
          <label>Versandart</label>
          <select value={versand} onChange={(e) => setVersand(e.target.value)}>
            <option>Brief</option>
            <option>E-Mail</option>
            <option>Brief + E-Mail</option>
            <option>Einschreiben</option>
          </select>
        </div>
        <div className="op-field">
          <label>Mahngebühr</label>
          <input type="number" step="0.50" value={mahngebuehr}
            onChange={(e) => setMahngebuehr(parseFloat(e.target.value) || 0)} />
        </div>
        <div className="op-field">
          <label>Neue Zahlungsfrist</label>
          <input type="date" value={neueFaelligkeit}
            onChange={(e) => setNeueFaelligkeit(e.target.value)} />
        </div>
        <div className="op-field is-full">
          <label>Optionaler Zusatztext</label>
          <textarea
            rows="3"
            value={zusatztext}
            placeholder="Wird als Variable {{ zusatztext }} an die Serienbrief-Vorlage übergeben."
            onChange={(e) => setZusatztext(e.target.value)}
          />
        </div>
        <div className="op-field is-full">
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={zinsen} onChange={(e) => setZinsen(e.target.checked)} />
            <span>Verzugszinsen berechnen ({zinssatz}% p.a. · §288 BGB)</span>
          </label>
        </div>
      </div>

      <div className="op-preview-label" style={{ marginTop: 14, marginBottom: 8 }}>Zu mahnende Rechnungen</div>
      <table className="op-mini-table" style={{ marginBottom: 14 }}>
        <tbody>
          {selectedRows.map((item) => (
            <tr key={item.belegnummer}>
              <td style={{ width: 28 }}>
                <input
                  type="checkbox"
                  checked
                  onChange={() => toggleInvoice(item.belegnummer)}
                />
              </td>
              <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openBeleg(item)}>{item.belegnummer}</button></td>
              <td>{fmtDate_op(item.faellig_am)}</td>
              <td className="is-num">{fmtEUR_op(item.offen)}</td>
              <td>{item.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {mahnRows.length > selectedRows.length && (
        <div style={{ marginBottom: 14 }}>
          <button
            type="button"
            className="mk-btn mk-btn-ghost"
            style={{ padding: "5px 10px", fontSize: 12 }}
            onClick={() => setShowInvoiceAdd((open) => !open)}
          >
            {showInvoiceAdd ? "Rechnungen ausblenden" : "Rechnung hinzufügen"}
          </button>
          {showInvoiceAdd && (
            <div style={{ marginTop: 8, border: "1px solid var(--line)", borderRadius: 4, background: "var(--bg-card)", padding: 10 }}>
              <input
                className="op-search"
                style={{ width: "100%", marginBottom: 8 }}
                placeholder="Rechnung suchen..."
                value={invoiceSearch}
                onChange={(e) => setInvoiceSearch(e.target.value)}
              />
              <table className="op-mini-table">
                <tbody>
                  {addableRows.length ? addableRows.map((item) => (
                    <tr key={item.belegnummer}>
                      <td><button type="button" className="op-link-btn" onClick={() => addInvoice(item.belegnummer)}>Hinzufügen</button></td>
                      <td><button className="op-link-btn" onClick={() => window.OP_ACTIONS.openBeleg(item)}>{item.belegnummer}</button></td>
                      <td>{fmtDate_op(item.faellig_am)}</td>
                      <td className="is-num">{fmtEUR_op(item.offen)}</td>
                      <td>{item.status}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan="5" style={{ color: "var(--ink-3)", padding: "10px" }}>Keine weiteren Rechnungen gefunden.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="op-preview">
        <div className="op-preview-label">Vorschau Forderung</div>
        <div className="op-preview-row">
          <span className="op-preview-key">Offene Hauptforderung</span>
          <span className="op-preview-val">{fmtEUR_op(selectedOpen)}</span>
        </div>
        <div className="op-preview-row">
          <span className="op-preview-key">+ Mahngebühr</span>
          <span className="op-preview-val">{fmtEUR_op(mahngebuehr)}</span>
        </div>
        {zinsen && (
          <div className="op-preview-row">
            <span className="op-preview-key">+ Verzugszinsen ({selectedRow.alter_tage} Tage)</span>
            <span className="op-preview-val">{fmtEUR_op(zinsBetrag)}</span>
          </div>
        )}
        <div className="op-preview-row is-total">
          <span className="op-preview-key">Σ Zahlungsaufforderung</span>
          <span className="op-preview-val">{fmtEUR_op(summe)}</span>
        </div>
      </div>

      <div className="op-doc-letter">
        <div className="op-doc-head">Hausverwaltung Müller GmbH · Hauptstr. 1 · 70173 Stuttgart</div>
        <h4>{textStufe}</h4>
        <p>{partyName}<br />Objekt {objekt}</p>
        <p>
          Sehr geehrte Damen und Herren,<br />
          wir bitten Sie höflich, den nachfolgend genannten Betrag bis spätestens
          <strong> {fmtDate_op(neueFaelligkeit)}</strong> auf unser Konto zu überweisen.
          Verwendungszweck: <strong>{selectedRows.map((item) => item.belegnummer).join(", ") || selectedRow.belegnummer}</strong>
        </p>
        <table>
          <thead>
            <tr>
              <th>Beleg</th>
              <th>Fällig am</th>
              <th className="num">Betrag</th>
            </tr>
          </thead>
          <tbody>
            {selectedRows.map((item) => (
              <tr key={item.belegnummer}>
                <td>{item.belegnummer}</td>
                <td>{fmtDate_op(item.faellig_am)}</td>
                <td className="num">{fmtEUR_op(item.offen)}</td>
              </tr>
            ))}
            <tr>
              <td>{isBulk ? "Summe inkl. Gebühren/Zinsen" : selectedRow.belegnummer}</td>
              <td>{fmtDate_op(neueFaelligkeit)}</td>
              <td className="num">{fmtEUR_op(summe)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="op-checklist">
        <div className="op-checklist-item">Dunning-Doc gemäß ERPNext-Standard</div>
        <div className="op-checklist-item">Mahngebühr als verlinkte Sales Invoice beim Submit</div>
        <div className="op-checklist-item">PDF-Anhang automatisch erzeugt + im Mieter-Kontakt archiviert</div>
        {versand.includes("E-Mail") && <div className="op-checklist-item">E-Mail-Versand vorbereitet ({partyName})</div>}
      </div>
    </Modal>
  );
}

// ───────── Aktion: Zahlung anlegen (Lieferanten) ─────────

function ZahlungModal({ row, onClose, onDone }) {
  // Skonto-Logik: wenn Bemerkung "Skonto bis" enthält, biete an
  const skontoMatch = (row.bemerkungen || "").match(/Skonto bis (\d{2}\.\d{2}\.).*?(-?\d+(?:\.\d+)?)\s*%/i);
  const hasSkonto = !!skontoMatch;
  const skontoBis = skontoMatch ? skontoMatch[1] : null;
  const skontoSatz = skontoMatch ? parseFloat(skontoMatch[2]) : 0;
  const [nutzeSkonto, setNutzeSkonto] = useStateAct(hasSkonto);
  const [zahldatum, setZahldatum] = useStateAct(() => frappe.datetime.get_today());
  const [zahlart, setZahlart] = useStateAct("SEPA-Überweisung");
  const [busy, setBusy] = useStateAct(false);

  const abzug = nutzeSkonto ? row.offen * (Math.abs(skontoSatz) / 100) : 0;
  const auszahlung = row.offen - abzug;
  const submit = async () => {
    setBusy(true);
    try {
      const result = await window.OP_ACTIONS.createPaymentEntry(row, {
        zahldatum,
        useSkonto: nutzeSkonto,
        skontoAmount: abzug,
        zahlart,
      });
      onDone?.(result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Zahlung an Lieferant anlegen"
      subtitle={`${window.OFFENE_POSTEN.partyName(row.party)} · ${row.belegnummer} · ${fmtEUR_op(row.offen)}`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Erzeugt 1 Payment Entry · ggf. 1 SEPA-XML
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose} disabled={busy}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={submit} disabled={busy}>
              {busy ? "Draft wird angelegt …" : `Zahlung als Draft anlegen · ${fmtEUR_op(auszahlung)}`}
            </button>
          </div>
        </>
      }
    >
      <div className="op-form-grid">
        <div className="op-field">
          <label>Zahldatum</label>
          <input type="date" value={zahldatum} onChange={(e) => setZahldatum(e.target.value)} />
        </div>
        <div className="op-field">
          <label>Zahlart</label>
          <select value={zahlart} onChange={(e) => setZahlart(e.target.value)}>
            <option>SEPA-Überweisung</option>
            <option>Lastschrift</option>
            <option>Manuelle Überweisung</option>
          </select>
        </div>
        {hasSkonto && (
          <div className="op-field is-full" style={{ background: "oklch(0.97 0.04 80)", padding: 12, border: "1px solid oklch(0.85 0.06 70)", borderRadius: 4 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "oklch(0.40 0.10 70)" }}>
              <input type="checkbox" checked={nutzeSkonto} onChange={(e) => setNutzeSkonto(e.target.checked)} />
              <strong>Skonto bis {skontoBis} nutzen ({Math.abs(skontoSatz)}%)</strong>
            </label>
            <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2 }}>
              Spart {fmtEUR_op(row.offen * (Math.abs(skontoSatz) / 100))} bei dieser Rechnung.
            </div>
          </div>
        )}
      </div>

      <div className="op-preview">
        <div className="op-preview-label">Buchungs-Vorschau</div>
        <div className="op-preview-row">
          <span className="op-preview-key">Rechnungsbetrag</span>
          <span className="op-preview-val">{fmtEUR_op(row.offen)}</span>
        </div>
        {nutzeSkonto && (
          <div className="op-preview-row">
            <span className="op-preview-key">− Skonto {Math.abs(skontoSatz)}%</span>
            <span className="op-preview-val">−{fmtEUR_op(abzug)}</span>
          </div>
        )}
        <div className="op-preview-row is-total">
          <span className="op-preview-key">Auszahlung</span>
          <span className="op-preview-val">{fmtEUR_op(auszahlung)}</span>
        </div>
      </div>

      <div className="op-checklist">
        <div className="op-checklist-item">Payment Entry zu {row.belegnummer}</div>
        {nutzeSkonto && <div className="op-checklist-item">Skonto-Buchung auf 3736 (Aufwandsminderung)</div>}
        {zahlart === "SEPA-Überweisung" && <div className="op-checklist-item">SEPA-XML zur nächsten Zahlungsdatei hinzugefügt</div>}
      </div>
    </Modal>
  );
}

// ───────── Aktion: Guthaben auszahlen (Mieter) ─────────

function GuthabenAuszahlenModal({ row, onClose, onDone }) {
  const [postingDate, setPostingDate] = useStateAct(() => frappe.datetime.get_today());
  const [modeOfPayment, setModeOfPayment] = useStateAct("Bank Draft");
  const [busy, setBusy] = useStateAct(false);
  const amount = Math.abs(row.offen || 0);
  const partyName = window.OFFENE_POSTEN.partyName(row.party);

  const submit = async () => {
    setBusy(true);
    try {
      const result = await window.OP_ACTIONS.createRefundPayment(row, {
        postingDate,
        modeOfPayment,
      });
      onDone?.(result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Guthaben auszahlen"
      subtitle={`${partyName} · ${row.belegnummer} · ${fmtEUR_op(amount)}`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Erzeugt einen Payment-Entry-Draft. Gebucht wird erst nach Submit im Desk.
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose} disabled={busy}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={submit} disabled={busy}>
              {busy ? "Draft wird angelegt …" : `Auszahlung als Draft anlegen · ${fmtEUR_op(amount)}`}
            </button>
          </div>
        </>
      }
    >
      <div className="op-form-grid">
        <div className="op-field">
          <label>Auszahlungsdatum</label>
          <input type="date" value={postingDate} onChange={(e) => setPostingDate(e.target.value)} />
        </div>
        <div className="op-field">
          <label>Zahlart</label>
          <select value={modeOfPayment} onChange={(e) => setModeOfPayment(e.target.value)}>
            <option>Bank Draft</option>
            <option>SEPA-Überweisung</option>
            <option>Manuelle Überweisung</option>
          </select>
        </div>
      </div>

      <div className="op-preview">
        <div className="op-preview-label">Auszahlungs-Vorschau</div>
        <div className="op-preview-row">
          <span className="op-preview-key">Guthaben aus Beleg</span>
          <span className="op-preview-val">{row.belegnummer}</span>
        </div>
        <div className="op-preview-row is-total">
          <span className="op-preview-key">Auszahlung an Mieter</span>
          <span className="op-preview-val">{fmtEUR_op(amount)}</span>
        </div>
      </div>

      <div className="op-checklist">
        <div className="op-checklist-item">Payment Entry Typ „Pay" gegen die Sales Invoice</div>
        <div className="op-checklist-item">Auszahlung wird mit dem negativen offenen Betrag verrechnet</div>
        <div className="op-checklist-item">Bank-/Kassenkonto kann im Draft vor Submit geprüft werden</div>
      </div>
    </Modal>
  );
}

// ───────── Aktion: Vorauszahlung zuordnen ─────────

function ZuordnenModal({ row, onClose, onDone }) {
  // Mock: zeigt alle offenen Forderungen desselben Mieters
  const partyOpens = window.OFFENE_POSTEN.rows
    .filter(r => r.party === row.party && r.offen > 0.01)
    .sort((a, b) => a.faellig_am.localeCompare(b.faellig_am));
  const verfuegbar = Math.abs(row.offen);
  const [selected, setSelected] = useStateAct(() => new Set(partyOpens[0] ? [partyOpens[0].belegnummer] : []));
  const [busy, setBusy] = useStateAct(false);
  const sel = partyOpens.filter(p => selected.has(p.belegnummer));
  const zugeordnet = sel.reduce((a, p) => a + Math.min(p.offen, verfuegbar - a), 0);
  const rest = verfuegbar - zugeordnet;
  const partyName = window.OFFENE_POSTEN.partyName(row.party);

  const toggle = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const submit = async () => {
    let remaining = verfuegbar;
    const allocations = [];
    for (const item of sel) {
      if (remaining <= 0) break;
      const amount = Math.min(item.offen, remaining);
      allocations.push({ invoice: item.belegnummer, amount });
      remaining -= amount;
    }
    setBusy(true);
    try {
      const result = await window.OP_ACTIONS.allocatePayment(row, allocations);
      onDone?.(result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Vorauszahlung zuordnen"
      subtitle={`${partyName} · Eingang ${fmtEUR_op(verfuegbar)} am ${fmtDate_op(row.buchungsdatum)}`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Rest {fmtEUR_op(rest)} bleibt als Vorauszahlung stehen.
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose} disabled={busy}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={submit} disabled={busy || sel.length === 0}>
              {busy ? "Draft wird angelegt …" : `${sel.length} ${sel.length === 1 ? "Zuordnung vorbereiten" : "Zuordnungen vorbereiten"}`}
            </button>
          </div>
        </>
      }
    >
      {partyOpens.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: "var(--ink-3)" }}>
          Keine offenen Forderungen bei {partyName}. Eingang als Anzahlung stehen lassen?
        </div>
      ) : (
        <>
          <p style={{ margin: "0 0 12px", fontSize: 12.5, color: "var(--ink-2)" }}>
            Wähle die Forderungen, die mit dieser Vorauszahlung verrechnet werden sollen.
            Ältester Posten ist vorausgewählt.
          </p>
          <table style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-soft)", color: "var(--ink-3)", textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.04em" }}>
                <th style={{ padding: "8px 10px", textAlign: "left" }}></th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>Beleg</th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>Fällig</th>
                <th style={{ padding: "8px 10px", textAlign: "right" }}>Offen</th>
              </tr>
            </thead>
            <tbody>
              {partyOpens.map((p) => (
                <tr key={p.belegnummer} style={{ borderBottom: "1px solid var(--line)" }}>
                  <td style={{ padding: "8px 10px" }}>
                    <input type="checkbox" checked={selected.has(p.belegnummer)}
                      onChange={() => toggle(p.belegnummer)} />
                  </td>
                  <td style={{ padding: "8px 10px", fontFamily: "ui-monospace, monospace", fontSize: 11.5 }}>
                    {p.belegnummer}
                  </td>
                  <td style={{ padding: "8px 10px" }}>{fmtDate_op(p.faellig_am)}</td>
                  <td style={{ padding: "8px 10px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {fmtEUR_op(p.offen)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="op-preview" style={{ marginTop: 14 }}>
            <div className="op-preview-row">
              <span className="op-preview-key">Verfügbar</span>
              <span className="op-preview-val">{fmtEUR_op(verfuegbar)}</span>
            </div>
            <div className="op-preview-row">
              <span className="op-preview-key">Zugeordnet ({sel.length} Beleg{sel.length === 1 ? "" : "e"})</span>
              <span className="op-preview-val">−{fmtEUR_op(zugeordnet)}</span>
            </div>
            <div className="op-preview-row is-total">
              <span className="op-preview-key">Rest als Vorauszahlung</span>
              <span className="op-preview-val">{fmtEUR_op(rest)}</span>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}

// ───────── Mini-Toast (nach Aktion) ─────────

function Toast({ message, onClose }) {
  useEffectAct(() => {
    const t = setTimeout(onClose, 2400);
    return () => clearTimeout(t);
  }, []);
  return (
    <div style={{
      position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
      background: "var(--ink)", color: "var(--bg)",
      padding: "10px 18px", borderRadius: 6, fontSize: 13,
      boxShadow: "0 8px 24px rgba(0,0,0,0.2)", zIndex: 200,
    }}>
      {message}
    </div>
  );
}

// ───────── Aktion: Sammelmahnung (Bulk, gruppiert pro Mieter) ─────────

function SammelmahnungModal({ rows, onClose, onDone }) {
  // Gruppiere pro Mieter
  const groups = React.useMemo(() => {
    const map = new Map();
    rows.forEach((r) => {
      if (!map.has(r.party)) map.set(r.party, { party: r.party, items: [], sum: 0 });
      const g = map.get(r.party);
      g.items.push(r);
      g.sum += r.offen;
    });
    return [...map.values()].map((g) => ({
      ...g,
      name: window.OFFENE_POSTEN.partyName(g.party),
      nextStufe: Math.min(4, Math.max(...g.items.map((r) => (r.mahnstufe || 0) + 1))),
      gebuehr: g.items.reduce((sum, r) => {
        const stufe = Math.min(4, (r.mahnstufe || 0) + 1);
        return sum + (stufe === 1 ? 0 : stufe === 2 ? 5 : stufe === 3 ? 10 : 15);
      }, 0),
    })).sort((a, b) => b.sum - a.sum);
  }, [rows]);

  const [versand, setVersand] = useStateAct("Brief");
  const [zusatztext, setZusatztext] = useStateAct("");
  const [dunningTypes, setDunningTypes] = useStateAct([]);
  const [dunningType, setDunningType] = useStateAct(rows.find((r) => r.dunning_type)?.dunning_type || "");
  const [vorlagen, setVorlagen] = useStateAct([]);
  const [serienbriefVorlage, setSerienbriefVorlage] = useStateAct(rows.find((r) => r.serienbrief_vorlage)?.serienbrief_vorlage || "");
  const [neueFaelligkeit, setNeueFaelligkeit] = useStateAct(() => {
    const d = new Date(); d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });
  const [excluded, setExcluded] = useStateAct(() => new Set());
  const [busy, setBusy] = useStateAct(false);

  const aktiv = groups.filter((g) => !excluded.has(g.party));
  const totalSum = aktiv.reduce((a, g) => a + g.sum + g.gebuehr, 0);

  useEffectAct(() => {
    let alive = true;
    Promise.all([
      window.OP_ACTIONS.listDunningTypes(),
      window.OP_ACTIONS.listSerienbriefVorlagen ? window.OP_ACTIONS.listSerienbriefVorlagen() : Promise.resolve([]),
    ])
      .then(([items, templates]) => {
        if (!alive) return;
        setDunningTypes(items);
        if (items.length && !dunningType) setDunningType(items[0]);
        setVorlagen(templates || []);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const toggle = (p) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });
  };
  const submit = async () => {
    const rowsByParty = {};
    const mahngebuehrPerParty = {};
    aktiv.forEach((group) => {
      rowsByParty[group.party] = group.items;
      mahngebuehrPerParty[group.party] = group.gebuehr;
    });
    setBusy(true);
    try {
      const serienbriefWerte = zusatztext.trim()
        ? [{ variable: "zusatztext", wert: zusatztext.trim(), beschreibung: "Optionaler Text aus dem Mahn-Cockpit" }]
        : [];
      const result = await window.OP_ACTIONS.createBulkDunning(rowsByParty, {
        neueFaelligkeit,
        dunningType,
        mahngebuehrPerParty,
        serienbriefVorlage,
        serienbriefWerte,
      });
      onDone?.(result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Sammelmahnung erstellen"
      subtitle={`${rows.length} Posten · ${groups.length} ${groups.length === 1 ? "Mieter" : "Mieter"} · ein Dunning-Doc pro Mieter`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Erzeugt {aktiv.length} Dunning-Doc{aktiv.length === 1 ? "" : "s"} · Mahngebühr-Rechnung beim Submit · {aktiv.length} PDF{aktiv.length === 1 ? "" : "s"}
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose} disabled={busy}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" disabled={busy || aktiv.length === 0} onClick={submit}>
              {busy ? "Drafts werden angelegt …" : `${aktiv.length} ${aktiv.length === 1 ? "Mahnung" : "Mahnungen"} als Draft anlegen · ${fmtEUR_op(totalSum)}`}
            </button>
          </div>
        </>
      }
    >
      <div className="op-form-grid">
        <div className="op-field">
          <label>Versandart (für alle)</label>
          <select value={versand} onChange={(e) => setVersand(e.target.value)}>
            <option>Brief</option>
            <option>E-Mail</option>
            <option>Brief + E-Mail</option>
            <option>Einschreiben</option>
          </select>
        </div>
        <div className="op-field">
          <label>Mahnstufe / Regel (für alle)</label>
          {dunningTypes.length ? (
            <select value={dunningType} onChange={(e) => setDunningType(e.target.value)}>
              {dunningTypes.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          ) : (
            <input value={dunningType} onChange={(e) => setDunningType(e.target.value)} placeholder="Automatisch" />
          )}
        </div>
        <div className="op-field">
          <label>Serienbrief-Vorlage</label>
          {vorlagen.length ? (
            <select value={serienbriefVorlage} onChange={(e) => setSerienbriefVorlage(e.target.value)}>
              <option value="">Default aus Mahnstufe</option>
              {vorlagen.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          ) : (
            <input value={serienbriefVorlage} onChange={(e) => setSerienbriefVorlage(e.target.value)} placeholder="Default aus Mahnstufe" />
          )}
        </div>
        <div className="op-field">
          <label>Neue Zahlungsfrist</label>
          <input type="date" value={neueFaelligkeit} onChange={(e) => setNeueFaelligkeit(e.target.value)} />
        </div>
        <div className="op-field is-full">
          <label>Optionaler Zusatztext</label>
          <textarea
            rows="3"
            value={zusatztext}
            placeholder="Wird als Variable {{ zusatztext }} an jede Serienbrief-Vorlage übergeben."
            onChange={(e) => setZusatztext(e.target.value)}
          />
        </div>
      </div>

      <div className="op-preview-label" style={{ marginBottom: 8 }}>Mahnungen pro Mieter</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {groups.map((g) => {
          const isOff = excluded.has(g.party);
          return (
            <div
              key={g.party}
              style={{
                display: "grid",
                gridTemplateColumns: "24px 1fr auto 100px",
                gap: 12,
                alignItems: "center",
                padding: "10px 12px",
                background: isOff ? "var(--bg-soft)" : "var(--bg-card)",
                border: "1px solid var(--line)",
                borderRadius: 4,
                opacity: isOff ? 0.55 : 1,
                transition: "opacity 0.1s",
              }}
            >
              <input type="checkbox" checked={!isOff} onChange={() => toggle(g.party)} />
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{g.name}</div>
                <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 2 }}>
                  {g.items.length} {g.items.length === 1 ? "Posten" : "Posten"} ·{" "}
                  Älteste seit {Math.max(...g.items.map(i => i.alter_tage))} Tagen
                </div>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--ink-3)", textAlign: "center" }}>
                Stufe<br />
                <span style={{ color: g.nextStufe >= 4 ? "var(--accent)" : "var(--ink)", fontWeight: 600, fontSize: 13 }}>
                  → {g.nextStufe === 1 ? "ZE" : g.nextStufe === 4 ? "Letzte" : `M${g.nextStufe - 1}`}
                </span>
              </div>
              <div style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{fmtEUR_op(g.sum + g.gebuehr)}</div>
                <div style={{ fontSize: 11, color: "var(--ink-3)" }}>
                  inkl. {fmtEUR_op(g.gebuehr)} Gebühr
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="op-preview" style={{ marginTop: 14 }}>
        <div className="op-preview-row is-total">
          <span className="op-preview-key">Σ Sammelmahnung ({aktiv.length} Schreiben)</span>
          <span className="op-preview-val">{fmtEUR_op(totalSum)}</span>
        </div>
      </div>
    </Modal>
  );
}

Object.assign(window, {
  canCreateDunningFor, isOverdueSalesInvoiceReceivable, primaryActionFor, ActionCell,
  Modal, MahnungModal, ZahlungModal, GuthabenAuszahlenModal, ZuordnenModal, SammelmahnungModal, Toast,
});
