import React, { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Icon } from "../components/Icon.jsx";
import {
  embedded,
  loadDurchlauf,
  getProgress,
  startRun,
  markFailed,
  saveVariables,
  addRecipients as apiAddRecipients,
  removeRecipients as apiRemoveRecipients,
  availableRecipients,
  mergedPdf,
  isNewMode,
  getVorlageParam,
  listVorlagen,
  createDurchlauf,
  updateTitle,
  gotoDurchlauf,
  gotoNew,
} from "./api.js";

// Serienbrief Durchlauf — main app
// ============== Header ==============
const Header = ({ durchlauf, stats, onRun, onMergedPdf, onMarkFailed, onTitleCommit, onNew, running, progress, busy }) => {
  const statusLabel = { draft: "Entwurf", running: "Läuft…", completed: "Abgeschlossen", failed: "Fehlgeschlagen", sent: "Versendet" }[durchlauf.status] || durchlauf.status;
  const [titleDraft, setTitleDraft] = useState(durchlauf.title || "");
  useEffect(() => { setTitleDraft(durchlauf.title || ""); }, [durchlauf.title]);
  const commitTitle = () => {
    const t = (titleDraft || "").trim();
    if (t && t !== durchlauf.title && onTitleCommit) onTitleCommit(t);
  };
  return (
    <header className="dl-header">
      <div className="dl-header-row">
        <input
          className="dl-header-title"
          value={titleDraft}
          disabled={!durchlauf.can_write}
          onChange={e => setTitleDraft(e.target.value)}
          onBlur={commitTitle}
          onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
        />
        <span className="dl-id">{durchlauf.id}</span>
        <span className={`dl-status-pill ${durchlauf.status}`}>
          <span className="dl-status-dot"/> {statusLabel}{running && progress ? ` ${progress}` : ""}
        </span>
        <div className="dl-header-actions">
          <button className="btn ghost" onClick={onNew}><Icon name="plus" size={13}/> Neuer Durchlauf</button>
          <button className="btn" onClick={onRun} disabled={running || busy || !durchlauf.can_write}>
            <Icon name="refresh" size={13}/> {running ? "Läuft…" : "Lauf starten / neu rendern"}
          </button>
          {running && durchlauf.can_write && (
            <button
              className="btn"
              onClick={onMarkFailed}
              disabled={busy}
              title="Setzt den Status auf Fehlgeschlagen. Nur verwenden, wenn der Background-Job offensichtlich tot ist."
            >
              <Icon name="x" size={13}/> Als fehlgeschlagen markieren
            </button>
          )}
          <button className="btn" onClick={onMergedPdf} disabled={running || busy || stats.generated === 0}>
            <Icon name="download" size={13}/> Sammel-PDF
          </button>
          <button className="btn" disabled title="E-Mail-Versand kommt in Phase 2">
            <Icon name="send" size={13}/> E-Mails senden
          </button>
        </div>
      </div>
      <div className="dl-header-meta">
        <span className="dl-header-meta-item"><Icon name="tag" size={11}/> Vorlage: <strong>{durchlauf.vorlage.title}</strong></span>
        <span className="dl-header-meta-item"><Icon name="repeat" size={11}/> Iteration: <strong>{durchlauf.iteration_doctype}</strong></span>
        <span className="dl-header-meta-item"><Icon name="calendar" size={11}/> Datum: <strong>{new Date(durchlauf.date).toLocaleDateString("de-DE")}</strong></span>
        <span className="dl-header-meta-item"><Icon name="user" size={11}/> Erstellt von: <strong>{durchlauf.created_by.split("@")[0]}</strong></span>
      </div>
      <div className="dl-stats">
        <div className="dl-stat">
          <div className="dl-stat-label">Empfänger</div>
          <div className="dl-stat-value">{stats.total}</div>
          <div className="dl-stat-sub">in der Liste</div>
        </div>
        <div className="dl-stat ok">
          <div className="dl-stat-label">Gerendert</div>
          <div className="dl-stat-value">{stats.generated}</div>
          <div className="dl-stat-sub">{stats.totalPages} {stats.totalPages === 1 ? "Seite" : "Seiten"} · ⌀ {stats.avgMs} ms</div>
        </div>
        <div className="dl-stat warn">
          <div className="dl-stat-label">Übersprungen</div>
          <div className="dl-stat-value">{stats.skipped}</div>
          <div className="dl-stat-sub">{stats.skipped > 0 ? "z. B. Saldo = 0" : "—"}</div>
        </div>
        <div className="dl-stat error">
          <div className="dl-stat-label">Fehler</div>
          <div className="dl-stat-value">{stats.errors}</div>
          <div className="dl-stat-sub">{stats.errors > 0 ? "Pfade prüfen" : "—"}</div>
        </div>
        <div className="dl-stat info">
          <div className="dl-stat-label">Mit Warnungen</div>
          <div className="dl-stat-value">{stats.warnings}</div>
          <div className="dl-stat-sub">durchlauffähig</div>
        </div>
        <div className="dl-stat">
          <div className="dl-stat-label">Versand</div>
          <div className="dl-stat-value">{stats.withEmail}/{stats.total}</div>
          <div className="dl-stat-sub">{stats.noEmail} ohne E-Mail → Druck</div>
        </div>
      </div>
    </header>
  );
};

// ============== Config column ==============
const ConfigColumn = ({ durchlauf, onUpdateVar }) => {
  return (
    <aside className="dl-config">
      <div className="dl-section">
        <div className="dl-section-title">Vorlage</div>
        <div className="dl-template-card">
          <div className="dl-template-card-head">
            <div className="dl-template-icon"><Icon name="tag" size={14}/></div>
            <div className="dl-template-info">
              <div className="dl-template-title">{durchlauf.vorlage.title}</div>
              <div className="dl-template-sub">Kategorie: {durchlauf.vorlage.kategorie}</div>
            </div>
          </div>
          <div className="dl-template-actions">
            <button className="btn sm"><Icon name="edit" size={11}/> Öffnen</button>
            <button className="btn sm ghost">Wechseln…</button>
          </div>
        </div>
      </div>

      <div className="dl-section">
        <div className="dl-section-title">Konfiguration</div>
        <div className="dl-config-field">
          <label className="dl-config-label">Iterations-Doctype</label>
          <select className="dl-config-select" defaultValue={durchlauf.iteration_doctype}>
            <option>Mietvertrag</option>
            <option>BK Mieter</option>
            <option>Eigentümer</option>
          </select>
        </div>
        <div className="dl-config-field">
          <label className="dl-config-label">Datum</label>
          <input className="dl-config-input" type="date" defaultValue={durchlauf.date}/>
        </div>
        <div className="dl-config-field">
          <label className="dl-config-label">Kategorie</label>
          <input className="dl-config-input" defaultValue={durchlauf.vorlage.kategorie}/>
        </div>
      </div>

      <div className="dl-section">
        <div className="dl-section-title">
          Vorlagen-Variablen
          <button title="Variable hinzufügen"><Icon name="plus" size={11}/></button>
        </div>
        <div className="dl-vars">
          {durchlauf.variables.map((v, i) => (
            <div key={i} className="dl-var">
              <div className="dl-var-head">
                <span className="dl-var-name">{v.name}</span>
                <span className="dl-var-type">{v.type}</span>
                {v.default && <span className="dl-var-default">⌥ {v.default}</span>}
              </div>
              {v.desc && <div className="dl-var-desc">{v.desc}</div>}
              <input
                className="dl-var-input"
                defaultValue={v.value}
                onChange={e => onUpdateVar(v.name, e.target.value)}
              />
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
};

// ============== Recipients ==============
const FILTER_DEFS = [
  { key: "all", label: "Alle" },
  { key: "ok", label: "Bereit", icon: "check", className: "ok" },
  { key: "warning", label: "Warnungen", icon: "branch", className: "warn" },
  { key: "error", label: "Fehler", icon: "x", className: "error" },
  { key: "skipped", label: "Übersprungen", className: "muted" },
  { key: "no_email", label: "Ohne E-Mail" },
];

const RecipientRow = ({ r, selected, onSelect, onToggleSelect, isCurrent, onDownload, hasOverrides, overrideCount }) => {
  const statusMap = {
    pending:   { label: "Pending", cls: "pending" },
    generated: { label: r.warning ? "OK ⚠" : "OK", cls: r.warning ? "warning" : "generated" },
    skipped:   { label: "Übersprungen", cls: "skipped" },
    error:     { label: "Fehler", cls: "error" },
    sent:      { label: "Gesendet", cls: "sent" },
  };
  const s = statusMap[r.status];
  const saldoNum = parseFloat(r.saldo.replace(/[.,]/g, m => m === "," ? "." : "").replace("–", "-").replace("€", ""));
  const saldoCls = isNaN(saldoNum) ? "" : saldoNum < 0 ? "negative" : saldoNum === 0 ? "zero" : "";

  return (
    <div className={`dl-row ${isCurrent ? "selected" : ""}`} onClick={() => onSelect(r)}>
      <div className="dl-cell dl-cell-check" onClick={e => { e.stopPropagation(); onToggleSelect(r.id); }}>
        <input type="checkbox" checked={selected} onChange={() => {}}/>
      </div>
      <div className="dl-cell dl-cell-status">
        <span className={`dl-row-status ${s.cls}`}>{s.label}</span>
      </div>
      <div className="dl-cell">
        <div className="dl-row-name">
          {r.customer}
          {hasOverrides && (
            <span className="dl-row-override-badge" title={`${overrideCount} Variable(n) überschrieben`}>
              ↻ {overrideCount}
            </span>
          )}
        </div>
        <div className="dl-row-address">{r.address}</div>
        {r.warning && (
          <div className="dl-row-warning"><Icon name="branch" size={11}/> {r.warning}</div>
        )}
        {r.error_msg && (
          <div className="dl-row-error"><Icon name="x" size={11}/> {r.error_msg}</div>
        )}
        {r.skip_reason && r.status === "skipped" && (
          <div className="dl-row-warning" style={{ background: "var(--bg-subtle)", color: "var(--text-muted)" }}>
            <Icon name="x" size={11}/> Grund: {r.skip_reason}
          </div>
        )}
      </div>
      <div className={`dl-cell dl-cell-saldo ${saldoCls}`}>{r.saldo}</div>
      <div className="dl-cell dl-cell-pages">{r.pages > 0 ? `${r.pages} S.` : <span style={{ color: "var(--text-faint)" }}>—</span>}</div>
      <div className={`dl-cell dl-cell-email ${r.has_email ? "" : "no-email"}`} title={r.email || "Keine E-Mail — wird gedruckt"}>
        <Icon name={r.has_email ? "send" : "x"} size={11}/>
        {r.has_email ? r.email.split("@")[0] : "—"}
      </div>
      <div className="dl-cell dl-cell-time">
        {r.generated_at ? new Date(r.generated_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
      </div>
      <div className="dl-cell dl-cell-actions" onClick={e => e.stopPropagation()}>
        <button className="dl-row-action" title="Aktionen" onClick={() => onDownload(r)}><Icon name="more" size={11}/></button>
      </div>
    </div>
  );
};

const RecipientsList = ({ recipients, filter, onFilter, filterCounts, query, onQuery, selectedIds, onToggleSelect, currentId, onSelect, onAddRecipient, onBulkAction, overrideCounts, canWrite, busy }) => {
  return (
    <main className="dl-recipients">
      <div className="dl-recipients-head">
        <div className="dl-recipients-title">Empfänger</div>
        <div className="dl-recipients-filters">
          {FILTER_DEFS.map(f => (
            <button
              key={f.key}
              className={`dl-filter-pill ${filter === f.key ? "active" : ""}`}
              onClick={() => onFilter(f.key)}
            >
              {f.icon && <Icon name={f.icon} size={10}/>}
              {f.label}
              <span className="dl-filter-count">{filterCounts[f.key]}</span>
            </button>
          ))}
        </div>
        <div className="dl-recipients-search">
          <span className="dl-recipients-search-icon"><Icon name="search" size={12}/></span>
          <input placeholder="Empfänger suchen…" value={query} onChange={e => onQuery(e.target.value)}/>
        </div>
        <button className="btn sm" onClick={onAddRecipient} disabled={!canWrite || busy}><Icon name="plus" size={11}/> Hinzufügen</button>
      </div>

      {selectedIds.size > 0 && (
        <div className="dl-bulk-bar">
          <div className="dl-bulk-info">
            <span className="dl-bulk-count">{selectedIds.size}</span>
            <span>{selectedIds.size === 1 ? "Empfänger" : "Empfänger"} ausgewählt</span>
          </div>
          <div className="dl-bulk-actions">
            <button className="btn sm" onClick={() => onBulkAction("rerender")}><Icon name="refresh" size={11}/> Neu rendern</button>
            <button className="btn sm" onClick={() => onBulkAction("download")}><Icon name="download" size={11}/> PDFs</button>
            <button className="btn sm" onClick={() => onBulkAction("send")}><Icon name="send" size={11}/> Senden</button>
            <button className="btn sm" style={{ color: "var(--danger)" }} onClick={() => onBulkAction("remove")}><Icon name="x" size={11}/> Entfernen</button>
          </div>
        </div>
      )}

      <div className="dl-list">
        <div className="dl-list-header">
          <div className="dl-cell"/>
          <div className="dl-cell">Status</div>
          <div className="dl-cell">Empfänger</div>
          <div className="dl-cell" style={{ textAlign: "right", paddingRight: 16 }}>Saldo</div>
          <div className="dl-cell" style={{ textAlign: "center" }}>Seiten</div>
          <div className="dl-cell">Versand</div>
          <div className="dl-cell" style={{ textAlign: "right" }}>Gerendert</div>
          <div className="dl-cell"/>
        </div>
        {recipients.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            Keine Empfänger für diesen Filter.
          </div>
        ) : recipients.map(r => (
          <RecipientRow
            key={r.id}
            r={r}
            selected={selectedIds.has(r.id)}
            onSelect={onSelect}
            onToggleSelect={onToggleSelect}
            isCurrent={r.id === currentId}
            onDownload={() => {}}
            hasOverrides={overrideCounts && !!overrideCounts[r.id]}
            overrideCount={overrideCounts?.[r.id] ? Object.keys(overrideCounts[r.id]).length : 0}
          />
        ))}
      </div>
    </main>
  );
};

const AddRecipientDialog = ({ open, doctype, selected, busy, onClose, onConfirm }) => {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [checked, setChecked] = useState(() => new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setChecked(new Set());
    setError("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    const timer = setTimeout(() => {
      availableRecipients(query)
        .then((res) => {
          if (!alive) return;
          setItems(res.items || []);
          setError("");
        })
        .catch((e) => {
          if (!alive) return;
          setItems([]);
          setError(e?.message || "Objekte konnten nicht geladen werden.");
        })
        .finally(() => { if (alive) setLoading(false); });
    }, 180);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [open, query]);

  const toggle = (id) => {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const add = () => {
    const ids = Array.from(checked);
    if (!ids.length) return;
    onConfirm(ids);
  };

  if (!open) return null;

  return (
    <div className="dl-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="dl-modal" role="dialog" aria-modal="true" aria-labelledby="dl-add-recipient-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="dl-modal-head">
          <div>
            <div className="dl-modal-title" id="dl-add-recipient-title">Iterationsobjekte hinzufügen</div>
            <div className="dl-modal-sub">{doctype || "Iterations-Doctype"} · bereits gewählte Objekte werden ausgeblendet</div>
          </div>
          <button className="dl-modal-icon-btn" onClick={onClose} disabled={busy} title="Schließen"><Icon name="x" size={14}/></button>
        </div>

        <div className="dl-modal-search">
          <span className="dl-modal-search-icon"><Icon name="search" size={13}/></span>
          <input autoFocus value={query} placeholder="Name oder Titel suchen…" onChange={(e) => setQuery(e.target.value)}/>
        </div>

        <div className="dl-modal-list">
          {loading ? (
            <div className="dl-modal-empty">Lade Objekte …</div>
          ) : error ? (
            <div className="dl-modal-error">{error}</div>
          ) : items.length === 0 ? (
            <div className="dl-modal-empty">Keine weiteren Objekte gefunden.</div>
          ) : items.map((item) => {
            const id = item.id || item.name;
            const label = item.label || item.customer || id;
            return (
              <label className="dl-modal-row" key={id}>
                <input type="checkbox" checked={checked.has(id)} onChange={() => toggle(id)}/>
                <span className="dl-modal-row-main">
                  <span className="dl-modal-row-title">{label}</span>
                  <span className="dl-modal-row-sub">{id}{item.address ? ` · ${item.address}` : ""}</span>
                </span>
              </label>
            );
          })}
        </div>

        <div className="dl-modal-actions">
          <div className="dl-modal-count">{checked.size ? `${checked.size} ausgewählt` : `${selected} im Durchlauf`}</div>
          <button className="btn" onClick={onClose} disabled={busy}>Abbrechen</button>
          <button className="btn primary" onClick={add} disabled={busy || checked.size === 0}>
            <Icon name="plus" size={13}/> {busy ? "Füge hinzu…" : "Hinzufügen"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ============== Detail (right) ==============
const DetailPane = ({ r, durchlauf, overrides, onSetOverride, onClearOverrides, overrideCounts, onDownloadPdf, onRun, running }) => {
  const [tab, setTab] = useState("preview");

  if (!r) {
    return (
      <aside className="dl-detail">
        <div className="dl-detail-empty">
          <Icon name="play" size={32}/>
          <div className="dl-detail-empty-title">Empfänger-Details</div>
          <div className="dl-detail-empty-sub">Klicke links auf einen Empfänger, um PDF, Variablen und Render-Log zu sehen.</div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="dl-detail">
      <div className="dl-detail-head">
        <div className="dl-detail-head-row">
          <div>
            <div className="dl-detail-name">{r.customer}</div>
            <div className="dl-detail-address">{r.address} · {r.id}</div>
          </div>
          <span className={`dl-row-status ${r.status === "generated" && r.warning ? "warning" : r.status}`}>
            {r.status === "generated" ? (r.warning ? "OK ⚠" : "OK") : r.status === "skipped" ? "Übersprungen" : r.status === "error" ? "Fehler" : r.status}
          </span>
        </div>
      </div>

      <div className="dl-detail-tabs">
        <button className={`dl-detail-tab ${tab === "preview" ? "active" : ""}`} onClick={() => setTab("preview")}><Icon name="play" size={11}/> PDF-Vorschau</button>
        <button className={`dl-detail-tab ${tab === "vars" ? "active" : ""}`} onClick={() => setTab("vars")}>
          <Icon name="tag" size={11}/> Werte
          {Object.keys(overrides).length > 0 && <span className="dl-tab-badge">{Object.keys(overrides).length}</span>}
        </button>
        <button className={`dl-detail-tab ${tab === "log" ? "active" : ""}`} onClick={() => setTab("log")}><Icon name="code" size={11}/> Render-Log</button>
      </div>

      <div className="dl-detail-body">
        {tab === "preview" && (
          <div className="dl-pdf-stage">
            {r.status === "skipped" ? (
              <div style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
                <Icon name="x" size={28} style={{ color: "var(--text-faint)" }}/>
                <div style={{ marginTop: 8, fontWeight: 500 }}>Übersprungen</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>{r.skip_reason}</div>
              </div>
            ) : r.status === "error" ? (
              <div style={{ padding: 32, textAlign: "center" }}>
                <Icon name="x" size={28} style={{ color: "var(--danger)" }}/>
                <div style={{ marginTop: 8, fontWeight: 500, color: "var(--danger)" }}>Render-Fehler</div>
                <div style={{ fontSize: 12, marginTop: 4, color: "var(--text-muted)", maxWidth: 320, marginLeft: "auto", marginRight: "auto" }}>{r.error_msg}</div>
              </div>
            ) : embedded ? (
              r.pdf_url ? (
                <iframe className="dl-pdf-frame" src={r.pdf_url} title="PDF-Vorschau" style={{ width: "100%", height: "100%", minHeight: 520, border: "none", background: "#fff" }}/>
              ) : (
                <div style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
                  <Icon name="play" size={28} style={{ color: "var(--text-faint)" }}/>
                  <div style={{ marginTop: 8, fontWeight: 500 }}>{r.status === "pending" ? "Noch nicht gerendert" : "Kein PDF verfügbar"}</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>{r.status === "pending" ? "Starte den Lauf, um das PDF zu erzeugen." : ""}</div>
                </div>
              )
            ) : (
              <div className="dl-pdf-paper">
                <div className="dl-pdf-right">München, 25. Mai 2026</div>
                <br/>
                <div>{r.customer}</div>
                <div style={{ fontSize: 11, color: "#666" }}>{r.address}</div>
                <br/><br/>
                <div className="dl-pdf-h2">Zahlungserinnerung — {r.address.split("·")[0].trim()}</div>
                <p>Sehr geehrte/r {r.customer.split(",")[0]},</p>
                <br/>
                <p>auf dem Mietkonto Ihrer Wohnung in der {r.address.split("·")[0].trim()} besteht aktuell ein offener Saldo in Höhe von <strong>{r.saldo}</strong>.</p>
                <br/>
                <p>Wir bitten Sie höflich, den fälligen Betrag bis spätestens <strong>{new Date(durchlauf.variables.find(v => v.name === "stichtag")?.value || "2026-06-08").toLocaleDateString("de-DE")}</strong> (Frist: {durchlauf.variables.find(v => v.name === "frist_tage")?.value} Tage) auf unser Konto zu überweisen.</p>
                {r.mahnstufe === 2 && (
                  <>
                    <br/>
                    <p>Da es sich um die zweite Mahnung handelt, erheben wir eine Mahngebühr in Höhe von {durchlauf.variables.find(v => v.name === "mahngebuehr")?.value} €.</p>
                  </>
                )}
                <br/>
                <p>Sollten Sie den Betrag bereits überwiesen haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.</p>
                <br/>
                <p>Mit freundlichen Grüßen<br/>Peters Hausverwaltung GmbH</p>
              </div>
            )}
          </div>
        )}

        {tab === "vars" && (
          <div className="dl-vars-list">
            <div className="dl-vars-section">
              <div className="dl-vars-section-head">
                <span className="dl-vars-section-title">Vorlagen-Variablen <span className="dl-vars-section-sub">(pro Empfänger überschreibbar)</span></span>
                {Object.keys(overrides).length > 0 && (
                  <button className="dl-vars-reset" onClick={onClearOverrides}>
                    <Icon name="refresh" size={11}/> Auf Durchlauf-Default zurück
                  </button>
                )}
              </div>
              <div className="dl-vars">
                {durchlauf.variables.map((v, i) => {
                  const overridden = overrides[v.name] !== undefined;
                  const effective = overridden ? overrides[v.name] : v.value;
                  return (
                    <div key={i} className={`dl-var dl-var-editable ${overridden ? "dl-var-overridden" : ""}`}>
                      <div className="dl-var-head">
                        <span className="dl-var-name">{v.name}</span>
                        <span className="dl-var-type">{v.type}</span>
                        {overridden ? (
                          <span className="dl-var-badge">↻ Override</span>
                        ) : (
                          <span className="dl-var-default">⌥ {v.value}</span>
                        )}
                      </div>
                      {v.desc && <div className="dl-var-desc">{v.desc}</div>}
                      <div className="dl-var-input-row">
                        <input
                          className="dl-var-input"
                          type={v.type === "Datum" ? "date" : "text"}
                          value={effective}
                          onChange={e => onSetOverride(v.name, e.target.value)}
                        />
                        {overridden && (
                          <button
                            className="dl-var-input-reset"
                            onClick={() => onSetOverride(v.name, v.value)}
                            title={`Zurück auf Durchlauf-Default „${v.value}"`}
                          >
                            <Icon name="x" size={11}/>
                          </button>
                        )}
                      </div>
                      {overridden && (
                        <div className="dl-var-override-hint">
                          <Icon name="branch" size={10}/>
                          Durchlauf-Default: <code>{v.value}</code>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="dl-vars-section">
              <div className="dl-vars-section-head">
                <span className="dl-vars-section-title">Aufgelöste Kontextwerte <span className="dl-vars-section-sub">(read-only, aus Datenbank)</span></span>
              </div>
              <div className="dl-vars">
                <div className="dl-var">
                  <div className="dl-var-head"><span className="dl-var-name">{`{{ mieter.nachname }}`}</span><span className="dl-var-type">String</span></div>
                  <div className="dl-var-readonly">{r.customer.split(",")[0]}</div>
                </div>
                <div className="dl-var">
                  <div className="dl-var-head"><span className="dl-var-name">{`{{ saldo }}`}</span><span className="dl-var-type">Currency</span></div>
                  <div className="dl-var-readonly">{r.saldo}</div>
                </div>
                <div className="dl-var">
                  <div className="dl-var-head"><span className="dl-var-name">{`{{ mahnstufe }}`}</span><span className="dl-var-type">Int</span></div>
                  <div className="dl-var-readonly">{r.mahnstufe}</div>
                </div>
                <div className="dl-var">
                  <div className="dl-var-head"><span className="dl-var-name">{`{{ bankkonto.iban }}`}</span><span className="dl-var-type">Data</span></div>
                  <div className={`dl-var-readonly ${r.missing_vars?.includes("bankkonto.iban") ? "dl-var-missing" : ""}`}>
                    {r.missing_vars?.includes("bankkonto.iban") ? "— leer —" : "DE89 3704 0044 0532 0130 00"}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "log" && (
          <div className="dl-log-list">
            <div className="dl-log-line"><span className="dl-log-time">09:16:21.412</span><span className="dl-log-level dl-log-level-info">INFO</span><span>Render started for {r.id}</span></div>
            <div className="dl-log-line"><span className="dl-log-time">09:16:21.418</span><span className="dl-log-level dl-log-level-info">INFO</span><span>Resolving baustein paths for haupt_verteil_objekt=Mietvertrag</span></div>
            <div className="dl-log-line"><span className="dl-log-time">09:16:21.422</span><span className="dl-log-level dl-log-level-ok">OK</span><span>Anrede formal → mieter=objekt.customer</span></div>
            <div className="dl-log-line"><span className="dl-log-time">09:16:21.425</span><span className="dl-log-level dl-log-level-ok">OK</span><span>Saldo-Berechnung → mietvertrag=objekt</span></div>
            <div className="dl-log-line"><span className="dl-log-time">09:16:21.427</span><span className="dl-log-level dl-log-level-ok">OK</span><span>Output: saldo={r.saldo}, mahnstufe={r.mahnstufe}</span></div>
            {r.mahnstufe === 2 && <div className="dl-log-line"><span className="dl-log-time">09:16:21.430</span><span className="dl-log-level dl-log-level-info">INFO</span><span>Jinja-if mahnstufe == "2" evaluated TRUE</span></div>}
            {r.missing_vars?.length > 0 && r.missing_vars.map((v, i) => (
              <div key={i} className="dl-log-line"><span className="dl-log-time">09:16:21.435</span><span className="dl-log-level dl-log-level-warn">WARN</span><span>Optional placeholder `{v}` is empty — rendered as ''</span></div>
            ))}
            {r.error_msg ? (
              <div className="dl-log-line"><span className="dl-log-time">09:16:21.510</span><span className="dl-log-level dl-log-level-err">ERR</span><span>{r.error_msg}</span></div>
            ) : (
              <>
                <div className="dl-log-line"><span className="dl-log-time">09:16:22.{String(r.render_ms).padStart(3,"0")}</span><span className="dl-log-level dl-log-level-info">INFO</span><span>HTML rendered, passing to Chrome PDF engine</span></div>
                <div className="dl-log-line"><span className="dl-log-time">09:16:23.{String(r.render_ms+100).slice(-3)}</span><span className="dl-log-level dl-log-level-ok">OK</span><span>PDF generated, {r.pages} page{r.pages!==1?"s":""}, {r.render_ms} ms</span></div>
                <div className="dl-log-line"><span className="dl-log-time">09:16:23.{String(r.render_ms+110).slice(-3)}</span><span className="dl-log-level dl-log-level-ok">OK</span><span>Stored at /private/files/SBDL-2026-00042/{r.id}.pdf</span></div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="dl-detail-footer">
        <button className="btn sm" onClick={onRun} disabled={running}><Icon name="refresh" size={12}/> Neu rendern</button>
        <button className="btn sm" onClick={() => onDownloadPdf && onDownloadPdf(r)} disabled={!r.pdf_url}><Icon name="download" size={12}/> PDF</button>
        <button className="btn sm" disabled title="E-Mail-Versand kommt in Phase 2"><Icon name="send" size={12}/> Senden</button>
      </div>
    </aside>
  );
};

// ============== Durchlauf-Viewer (bestehender Durchlauf) ==============
const DurchlaufApp = () => {
  const [durchlaufMeta, setDurchlaufMeta] = useState({ id: "", title: "", status: "draft", vorlage: { title: "", kategorie: "" }, iteration_doctype: "", date: "", created_by: "", can_write: true });
  const [recipients, setRecipients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [currentId, setCurrentId] = useState(null);
  const [vars, setVars] = useState([]);
  // Per-recipient variable overrides: { [recipientId]: { [varName]: value } }
  const [perRecipientOverrides, setPerRecipientOverrides] = useState({});
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [busy, setBusy] = useState(false);
  const [addDialogOpen, setAddDialogOpen] = useState(false);

  const durchlauf = { ...durchlaufMeta, variables: vars };

  // --- Laden ---------------------------------------------------------------
  const applyData = useCallback((d) => {
    setDurchlaufMeta(d.durchlauf);
    setRecipients(d.recipients || []);
    setVars(d.durchlauf.variables || []);
    setPerRecipientOverrides(d.overrides || {});
    setRunning((d.durchlauf.status || "") === "running");
    setCurrentId((prev) => {
      const list = d.recipients || [];
      if (prev && list.some((r) => r.id === prev)) return prev;
      return list.length ? list[0].id : null;
    });
  }, []);

  const refresh = useCallback(async () => {
    const d = await loadDurchlauf();
    applyData(d);
    return d;
  }, [applyData]);

  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setLoadError(null))
      .catch((e) => setLoadError(e?.message || String(e)))
      .finally(() => setLoading(false));
  }, [refresh]);

  // --- Variablen speichern (debounced) ------------------------------------
  const saveTimer = useRef(null);
  const scheduleSave = useCallback((nextVars, nextOverrides) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveVariables(
        (nextVars || []).map((v) => ({ name: v.name, value: v.value })),
        nextOverrides || {},
      ).catch(() => {});
    }, 600);
  }, []);

  const onUpdateVar = (name, value) => {
    setVars((prev) => {
      const next = prev.map((v) => (v.name === name ? { ...v, value } : v));
      scheduleSave(next, perRecipientOverrides);
      return next;
    });
  };

  const setRecipientOverride = (recipientId, varName, value) => {
    setPerRecipientOverrides(prev => {
      const next = { ...prev };
      const cur = { ...(next[recipientId] || {}) };
      const defaultVal = vars.find(v => v.name === varName)?.value;
      if (value === "" || value === defaultVal) {
        delete cur[varName];
      } else {
        cur[varName] = value;
      }
      if (Object.keys(cur).length === 0) delete next[recipientId];
      else next[recipientId] = cur;
      scheduleSave(vars, next);
      return next;
    });
  };

  const clearRecipientOverrides = (recipientId) => {
    setPerRecipientOverrides(prev => {
      const next = { ...prev };
      delete next[recipientId];
      scheduleSave(vars, next);
      return next;
    });
  };

  // --- Lauf starten + Fortschritt pollen ----------------------------------
  const pollTimer = useRef(null);
  const stopPolling = () => { if (pollTimer.current) { clearTimeout(pollTimer.current); pollTimer.current = null; } };
  const poll = useCallback(() => {
    stopPolling();
    pollTimer.current = setTimeout(async () => {
      try {
        const p = await getProgress();
        setProgress(p.progress || "");
        if (p.status === "running") {
          poll();
        } else {
          setRunning(false);
          setProgress("");
          await refresh();
        }
      } catch {
        setRunning(false);
        stopPolling();
      }
    }, 1500);
  }, [refresh]);

  // Falls beim Öffnen bereits ein Job läuft → Polling aufnehmen.
  useEffect(() => {
    if (running) poll();
    return stopPolling;
  }, [running, poll]);

  const onRun = useCallback(async () => {
    if (running) return;
    setBusy(true);
    try {
      await startRun();
      setRunning(true);
      setProgress("");
      poll();
    } catch (e) {
      window.alert(e?.message || "Lauf konnte nicht gestartet werden.");
    } finally {
      setBusy(false);
    }
  }, [running, poll]);

  const onMergedPdf = useCallback(async () => {
    setBusy(true);
    try {
      const res = await mergedPdf();
      if (res && res.file_url) window.open(res.file_url, "_blank");
    } catch (e) {
      window.alert(e?.message || "Sammel-PDF fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }, []);

  // Manueller Reset: bricht das Polling, setzt running=false und refresht den Doc,
  // damit Status/Counts vom Backend kommen. Backend prüft status === "Läuft" +
  // docstatus === 0 selbst, daher hier nur User-Confirmation.
  const onMarkFailed = useCallback(async () => {
    if (!running) return;
    const ok = window.confirm(
      "Lauf als FEHLGESCHLAGEN markieren?\n\nNur verwenden, wenn der Background-Job offensichtlich tot ist (z.B. Worker-Crash). Bereits erzeugte Dokumente bleiben erhalten."
    );
    if (!ok) return;
    setBusy(true);
    try {
      await markFailed();
      stopPolling();
      setRunning(false);
      setProgress("");
      await refresh();
    } catch (e) {
      window.alert(e?.message || "Reset fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }, [running, refresh]);

  const onDownloadPdf = useCallback((r) => {
    if (r && r.pdf_url) window.open(r.pdf_url, "_blank");
  }, []);

  const onTitleCommit = useCallback((t) => {
    setDurchlaufMeta((m) => ({ ...m, title: t }));
    updateTitle(t).catch(() => {});
  }, []);

  const onNew = useCallback(() => { gotoNew(); }, []);

  const onAddRecipient = useCallback(() => {
    if (!durchlaufMeta.can_write || busy) return;
    setAddDialogOpen(true);
  }, [durchlaufMeta.can_write, busy]);

  const onConfirmAddRecipients = useCallback(async (ids) => {
    if (!ids.length) return;
    setBusy(true);
    try {
      await apiAddRecipients(ids);
      setAddDialogOpen(false);
      await refresh();
    } catch (e) {
      window.alert(e?.message || "Hinzufügen fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const onBulkAction = useCallback(async (action) => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (action === "remove") {
      if (!window.confirm(`${ids.length} Empfänger entfernen?`)) return;
      setBusy(true);
      try {
        await apiRemoveRecipients(ids);
        setSelectedIds(new Set());
        await refresh();
      } catch (e) {
        window.alert(e?.message || "Entfernen fehlgeschlagen.");
      } finally {
        setBusy(false);
      }
    } else if (action === "rerender") {
      onRun();
    } else if (action === "download") {
      onMergedPdf();
    } else if (action === "send") {
      window.alert("E-Mail-Versand kommt in Phase 2.");
    }
  }, [selectedIds, onRun, onMergedPdf, refresh]);

  const filterCounts = useMemo(() => ({
    all: recipients.length,
    ok: recipients.filter(r => r.status === "generated" && !r.warning).length,
    warning: recipients.filter(r => r.warning).length,
    error: recipients.filter(r => r.status === "error").length,
    skipped: recipients.filter(r => r.status === "skipped").length,
    no_email: recipients.filter(r => !r.has_email).length,
  }), [recipients]);

  const filtered = useMemo(() => {
    let rows = recipients;
    if (filter === "ok") rows = rows.filter(r => r.status === "generated" && !r.warning);
    else if (filter === "warning") rows = rows.filter(r => r.warning);
    else if (filter === "error") rows = rows.filter(r => r.status === "error");
    else if (filter === "skipped") rows = rows.filter(r => r.status === "skipped");
    else if (filter === "no_email") rows = rows.filter(r => !r.has_email);
    const q = query.trim().toLowerCase();
    if (q) rows = rows.filter(r => r.customer.toLowerCase().includes(q) || r.address.toLowerCase().includes(q) || r.id.toLowerCase().includes(q));
    return rows;
  }, [recipients, filter, query]);

  const stats = useMemo(() => {
    const generated = recipients.filter(r => r.status === "generated");
    return {
      total: recipients.length,
      generated: generated.length,
      skipped: recipients.filter(r => r.status === "skipped").length,
      errors: recipients.filter(r => r.status === "error").length,
      warnings: recipients.filter(r => r.warning).length,
      withEmail: recipients.filter(r => r.has_email).length,
      noEmail: recipients.filter(r => !r.has_email).length,
      totalPages: generated.reduce((n, r) => n + r.pages, 0),
      avgMs: generated.length ? Math.round(generated.reduce((n, r) => n + r.render_ms, 0) / generated.length) : 0,
    };
  }, [recipients]);

  const toggleSelect = useCallback((id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const currentRecipient = recipients.find(r => r.id === currentId);

  if (loadError) {
    return <div className="durchlauf-app" style={{ padding: 24, color: "var(--danger)" }}>Fehler beim Laden: {loadError}</div>;
  }
  if (loading) {
    return <div className="durchlauf-app" style={{ padding: 24, color: "var(--text-muted)" }}>Lade Durchlauf …</div>;
  }

  return (
    <div className="durchlauf-app">
      <AddRecipientDialog
        open={addDialogOpen}
        doctype={durchlauf.iteration_doctype}
        selected={recipients.length}
        busy={busy}
        onClose={() => { if (!busy) setAddDialogOpen(false); }}
        onConfirm={onConfirmAddRecipients}
      />
      <Header
        durchlauf={durchlauf}
        stats={stats}
        onRun={onRun}
        onMergedPdf={onMergedPdf}
        onMarkFailed={onMarkFailed}
        onTitleCommit={onTitleCommit}
        onNew={onNew}
        running={running}
        progress={progress}
        busy={busy}
      />
      <div className="dl-main">
        <ConfigColumn durchlauf={durchlauf} onUpdateVar={onUpdateVar}/>
        <RecipientsList
          recipients={filtered}
          filter={filter}
          onFilter={setFilter}
          filterCounts={filterCounts}
          query={query}
          onQuery={setQuery}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          currentId={currentId}
          onSelect={(r) => setCurrentId(r.id)}
          onAddRecipient={onAddRecipient}
          onBulkAction={onBulkAction}
          overrideCounts={perRecipientOverrides}
          canWrite={durchlauf.can_write}
          busy={busy}
        />
        <DetailPane
          r={currentRecipient}
          durchlauf={durchlauf}
          overrides={perRecipientOverrides[currentId] || {}}
          onSetOverride={(name, val) => setRecipientOverride(currentId, name, val)}
          onClearOverrides={() => clearRecipientOverrides(currentId)}
          overrideCounts={perRecipientOverrides}
          onDownloadPdf={onDownloadPdf}
          onRun={onRun}
          running={running}
        />
      </div>
    </div>
  );
};

// ============== Neuer Durchlauf (Vollbild-Page ohne docname) ==============
const NewDurchlauf = ({ preselect }) => {
  const [vorlagen, setVorlagen] = useState([]);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(preselect || "");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const selRowRef = React.useRef(null);

  useEffect(() => {
    let alive = true;
    // pinnedId = preselect: das Backend stellt die vorausgewaehlte Vorlage
    // immer ans Anfang der Liste, sonst wirkt der Picker leer-ausgewaehlt
    // (sel-State ist gesetzt, die Vorlage aber nicht in den ersten 50).
    listVorlagen(q, preselect)
      .then((r) => { if (alive) { setVorlagen(r.items || []); setErr(null); } })
      .catch((e) => {
        // RPC-Fehler nicht schlucken — sonst sieht der User nur "Keine Vorlagen
        // gefunden" und kann nicht unterscheiden zwischen leerer Liste und Fehler.
        if (alive) setErr(e?.message || "Vorlagen konnten nicht geladen werden.");
        // eslint-disable-next-line no-console
        console.error("[durchlauf] listVorlagen failed:", e);
      });
    return () => { alive = false; };
  }, [q, preselect]);

  // Beim ersten Render mit gesetzter Vorauswahl ins Viewport scrollen,
  // damit der User die Markierung sofort sieht.
  useEffect(() => {
    if (sel && selRowRef.current) {
      try { selRowRef.current.scrollIntoView({ block: "nearest" }); } catch (_) {}
    }
  }, [vorlagen.length, sel]);

  const create = async () => {
    if (!sel) { setErr("Bitte eine Vorlage wählen."); return; }
    setErr(null);
    setBusy(true);
    try {
      const res = await createDurchlauf(title, sel);
      await gotoDurchlauf(res.docname); // Page-Route → iframe lädt mit docname neu
    } catch (e) {
      setErr(e?.message || "Anlegen fehlgeschlagen.");
      setBusy(false);
    }
  };

  return (
    <div className="durchlauf-app dl-new">
      <div className="dl-new-card">
        <div className="dl-new-title">Neuer Serienbrief-Durchlauf</div>
        <div className="dl-new-sub">Vorlage wählen — Kategorie und Iterations-Objekt werden übernommen.</div>

        <label className="dl-new-label">Titel (optional)</label>
        <input className="dl-new-input" value={title} placeholder="z. B. Mahnlauf Mai 2026" onChange={(e) => setTitle(e.target.value)}/>

        <label className="dl-new-label">Vorlage</label>
        <input className="dl-new-input" value={q} placeholder="Vorlage suchen…" onChange={(e) => setQ(e.target.value)}/>
        <div className="dl-new-list">
          {vorlagen.length === 0 ? (
            <div className="dl-new-empty">Keine Vorlagen gefunden.</div>
          ) : vorlagen.map((v) => (
            <div
              key={v.id}
              ref={v.id === sel ? selRowRef : undefined}
              className={`dl-new-row ${v.id === sel ? "active" : ""}`}
              onClick={() => setSel(v.id)}
            >
              <div>
                <div className="dl-new-row-title">{v.title}</div>
                <div className="dl-new-row-sub">{v.kategorie || "—"}{v.haupt_verteil_objekt ? ` · ${v.haupt_verteil_objekt}` : ""}</div>
              </div>
              {v.id === sel && <Icon name="check" size={14}/>}
            </div>
          ))}
        </div>

        {err && <div className="dl-new-error">{err}</div>}

        <div className="dl-new-actions">
          <button className="btn primary" onClick={create} disabled={busy || !sel}>
            <Icon name="plus" size={13}/> {busy ? "Wird angelegt…" : "Durchlauf anlegen"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ============== App (Wrapper: Neu-Modus vs. Viewer) ==============
export const App = () => {
  // Eingebettet ohne docname → „Neuer Durchlauf"; sonst der Viewer. Standalone (Mock)
  // zeigt direkt den Viewer.
  if (isNewMode()) return <NewDurchlauf preselect={getVorlageParam()}/>;
  return <DurchlaufApp/>;
};
