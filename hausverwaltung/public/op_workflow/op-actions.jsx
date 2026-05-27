// op-actions.jsx — Aktionen und Modals für den Offene-Posten-Report.
const { useState: useStateAct, useEffect: useEffectAct } = React;

// Wählt die *primäre* Aktion pro Zeile basierend auf Status/Art/Mahnstufe.
function primaryActionFor(row) {
  // Bereits abgeschrieben → keine primäre Aktion
  if (row.status === "Written Off") return null;

  // Lieferanten-Rechnung
  if (row.art === "Rechnungen" && row.offen > 0) {
    return { key: "zahlung_anlegen", label: "Zahlung anlegen", kind: "primary" };
  }

  // Mieter-Guthaben (Mieter bekommt Geld)
  if (row.art === "Forderungen" && row.offen < -0.01) {
    return { key: "guthaben_auszahlen", label: "Guthaben auszahlen", kind: "ghost" };
  }

  // Vorauszahlung (Payment Entry, unallocated)
  if (row.belegart === "Payment Entry") {
    return { key: "zuordnen", label: "Zuordnen", kind: "warn" };
  }

  // Forderung, überfällig: Mahnstufe nach oben treiben
  if (row.alter_tage > 0) {
    const nextStufe = (row.mahnstufe || 0) + 1;
    if (nextStufe <= 3) {
      return {
        key: "mahnung",
        label: nextStufe === 1 ? "Mahnung erstellen" : `Mahnung M${nextStufe}`,
        kind: nextStufe >= 2 ? "late" : "primary",
      };
    } else {
      return { key: "inkasso", label: "An Inkasso", kind: "late" };
    }
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

function MahnungModal({ row, onClose }) {
  const nextStufe = (row.mahnstufe || 0) + 1;
  const [mahngebuehr, setMahngebuehr] = useStateAct(nextStufe === 1 ? 5.00 : nextStufe === 2 ? 10.00 : 20.00);
  const [zinsen, setZinsen] = useStateAct(true);
  const [zinssatz, setZinssatz] = useStateAct(9.12); // Basis + 9% gem. §288 BGB
  const [versand, setVersand] = useStateAct("Brief");
  const [neueFaelligkeit, setNeueFaelligkeit] = useStateAct(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });
  const [textStufe, setTextStufe] = useStateAct(`Zahlungserinnerung Stufe ${nextStufe}`);

  // Verzugszinsen-Berechnung (rein illustrativ)
  const zinsBetrag = zinsen ? (row.offen * (zinssatz / 100) * (row.alter_tage / 365)) : 0;

  const summe = row.offen + mahngebuehr + zinsBetrag;
  const partyName = window.OFFENE_POSTEN.partyName(row.party);
  const objekt = window.OFFENE_POSTEN.ccLabel[row.kostenstelle] || row.kostenstelle;

  return (
    <Modal
      title={`Mahnung erstellen · Stufe ${nextStufe}`}
      subtitle={`${partyName} · ${row.belegnummer} · ${fmtEUR_op(row.offen)} offen seit ${row.alter_tage} Tagen`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Erzeugt 1 Dunning-Doc · 1 Journal Entry (Mahngebühr) · 1 Datei (PDF)
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={onClose}>
              {`Mahnung versenden · ${fmtEUR_op(summe)}`}
            </button>
          </div>
        </>
      }
    >
      <div className="op-form-grid">
        <div className="op-field">
          <label>Mahnstufe</label>
          <div className="op-field-display">M{nextStufe} · {textStufe}</div>
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
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={zinsen} onChange={(e) => setZinsen(e.target.checked)} />
            <span>Verzugszinsen berechnen ({zinssatz}% p.a. · §288 BGB)</span>
          </label>
        </div>
      </div>

      <div className="op-preview">
        <div className="op-preview-label">Vorschau Forderung</div>
        <div className="op-preview-row">
          <span className="op-preview-key">Offene Hauptforderung</span>
          <span className="op-preview-val">{fmtEUR_op(row.offen)}</span>
        </div>
        <div className="op-preview-row">
          <span className="op-preview-key">+ Mahngebühr</span>
          <span className="op-preview-val">{fmtEUR_op(mahngebuehr)}</span>
        </div>
        {zinsen && (
          <div className="op-preview-row">
            <span className="op-preview-key">+ Verzugszinsen ({row.alter_tage} Tage)</span>
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
          Verwendungszweck: <strong>{row.belegnummer}</strong>
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
            <tr>
              <td>{row.belegnummer}</td>
              <td>{fmtDate_op(row.faellig_am)}</td>
              <td className="num">{fmtEUR_op(summe)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="op-checklist">
        <div className="op-checklist-item">Dunning-Doc gemäß ERPNext-Standard</div>
        <div className="op-checklist-item">Mahngebühr als Journal Entry auf 1400 (Forderungen Mieter)</div>
        <div className="op-checklist-item">PDF-Anhang automatisch erzeugt + im Mieter-Kontakt archiviert</div>
        {versand.includes("E-Mail") && <div className="op-checklist-item">E-Mail-Versand vorbereitet ({partyName})</div>}
      </div>
    </Modal>
  );
}

// ───────── Aktion: Zahlung anlegen (Lieferanten) ─────────

function ZahlungModal({ row, onClose }) {
  // Skonto-Logik: wenn Bemerkung "Skonto bis" enthält, biete an
  const skontoMatch = (row.bemerkungen || "").match(/Skonto bis (\d{2}\.\d{2}\.).*?(-?\d+(?:\.\d+)?)\s*%/i);
  const hasSkonto = !!skontoMatch;
  const skontoBis = skontoMatch ? skontoMatch[1] : null;
  const skontoSatz = skontoMatch ? parseFloat(skontoMatch[2]) : 0;
  const [nutzeSkonto, setNutzeSkonto] = useStateAct(hasSkonto);
  const [zahldatum, setZahldatum] = useStateAct("2026-05-27");
  const [zahlart, setZahlart] = useStateAct("SEPA-Überweisung");

  const abzug = nutzeSkonto ? row.offen * (Math.abs(skontoSatz) / 100) : 0;
  const auszahlung = row.offen - abzug;

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
            <button className="mk-btn" onClick={onClose}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={onClose}>
              {`Zahlung anlegen · ${fmtEUR_op(auszahlung)}`}
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

// ───────── Aktion: Vorauszahlung zuordnen ─────────

function ZuordnenModal({ row, onClose }) {
  // Mock: zeigt alle offenen Forderungen desselben Mieters
  const partyOpens = window.OFFENE_POSTEN.rows
    .filter(r => r.party === row.party && r.offen > 0.01)
    .sort((a, b) => a.faellig_am.localeCompare(b.faellig_am));
  const verfuegbar = Math.abs(row.offen);
  const [selected, setSelected] = useStateAct(() => new Set(partyOpens[0] ? [partyOpens[0].belegnummer] : []));
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
            <button className="mk-btn" onClick={onClose}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" onClick={onClose}>
              {`${sel.length} ${sel.length === 1 ? "Zuordnung buchen" : "Zuordnungen buchen"}`}
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

function SammelmahnungModal({ rows, onClose }) {
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
      nextStufe: Math.min(3, Math.max(...g.items.map((r) => (r.mahnstufe || 0) + 1))),
      gebuehr: g.items.length * 5.00, // Mock-Gebühr-Logik
    })).sort((a, b) => b.sum - a.sum);
  }, [rows]);

  const [versand, setVersand] = useStateAct("Brief");
  const [neueFaelligkeit, setNeueFaelligkeit] = useStateAct(() => {
    const d = new Date(); d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });
  const [excluded, setExcluded] = useStateAct(() => new Set());

  const aktiv = groups.filter((g) => !excluded.has(g.party));
  const totalSum = aktiv.reduce((a, g) => a + g.sum + g.gebuehr, 0);

  const toggle = (p) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });
  };

  return (
    <Modal
      title="Sammelmahnung erstellen"
      subtitle={`${rows.length} Posten · ${groups.length} ${groups.length === 1 ? "Mieter" : "Mieter"} · ein Dunning-Doc pro Mieter`}
      onClose={onClose}
      footer={
        <>
          <span className="op-modal-foot-info">
            Erzeugt {aktiv.length} Dunning-Doc{aktiv.length === 1 ? "" : "s"} · {aktiv.reduce((a, g) => a + g.items.length, 0)} Mahngebühr-JEs · {aktiv.length} PDF{aktiv.length === 1 ? "" : "s"}
          </span>
          <div className="op-modal-foot-actions">
            <button className="mk-btn" onClick={onClose}>Abbrechen</button>
            <button className="mk-btn mk-btn-primary" disabled={aktiv.length === 0} onClick={onClose}>
              {`${aktiv.length} ${aktiv.length === 1 ? "Mahnung" : "Mahnungen"} versenden · ${fmtEUR_op(totalSum)}`}
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
          <label>Neue Zahlungsfrist</label>
          <input type="date" value={neueFaelligkeit} onChange={(e) => setNeueFaelligkeit(e.target.value)} />
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
                <span style={{ color: g.nextStufe === 3 ? "var(--accent)" : "var(--ink)", fontWeight: 600, fontSize: 13 }}>
                  → M{g.nextStufe}
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
  primaryActionFor, ActionCell,
  Modal, MahnungModal, ZahlungModal, ZuordnenModal, SammelmahnungModal, Toast,
});
