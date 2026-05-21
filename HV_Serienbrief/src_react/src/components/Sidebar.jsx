import React, { useState, useMemo, useEffect, useRef } from "react";
import { Icon } from "./Icon.jsx";

// base64-PDF → Blob-URL (vermeidet riesige data:-URIs / CSP-Probleme)
function usePdfUrl(base64) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!base64) { setUrl(null); return; }
    try {
      const bin = atob(base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: "application/pdf" });
      const u = URL.createObjectURL(blob);
      setUrl(u);
      return () => URL.revokeObjectURL(u);
    } catch (e) {
      setUrl(null);
    }
  }, [base64]);
  return url;
}

// =========================
// Preview pane — echtes PDF
// =========================
const PreviewPane = ({ template, recipient, recipients, onChangeRecipient, onSearchRecipients,
                       previewPdf, previewLoading, previewError, previewMode, onRefresh, onMaximize }) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [q, setQ] = useState("");
  const pdfUrl = usePdfUrl(previewPdf);

  return (
    <div className="preview-pane">
      <div className="preview-control">
        <div className="recipient-picker" onClick={() => setPickerOpen(o => !o)}>
          <Icon name="user" size={13}/>
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2, flex: 1, minWidth: 0 }}>
            <span className="pp-label">Empfänger ({template.haupt_verteil_objekt || "—"})</span>
            <span className="pp-value" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {recipient?.label || "Beispielwerte"}
            </span>
          </div>
          <Icon name="chevron-down" size={12}/>
        </div>
        <button className="btn sm" title="Vorschau aktualisieren" onClick={onRefresh} disabled={previewLoading}>
          <Icon name="play" size={13}/>
        </button>
        <button className="btn sm icon" title="PDF groß ansehen" onClick={onMaximize}>
          <Icon name="play" size={13}/>
        </button>
      </div>

      {pickerOpen && (
        <div style={{ borderBottom: "1px solid var(--border)", background: "var(--surface)", padding: 8, maxHeight: 320, overflow: "auto" }}>
          <div className="ph-search-wrap" style={{ marginBottom: 6 }}>
            <span className="icon-left"><Icon name="search" size={13}/></span>
            <input
              className="ph-search-input"
              placeholder="Empfänger suchen…"
              value={q}
              onChange={e => { setQ(e.target.value); onSearchRecipients && onSearchRecipients(e.target.value); }}
            />
          </div>
          <div
            onClick={() => { onChangeRecipient(null); setPickerOpen(false); }}
            className="recipient-row"
            style={{ borderRadius: 4, cursor: "pointer", padding: "6px 10px", fontSize: 12.5,
                     background: !recipient?.id ? "var(--primary-50)" : "transparent" }}
          >
            <div style={{ fontWeight: 500 }}>Beispielwerte</div>
            <div style={{ fontSize: 10.5, color: "var(--text-faint)" }}>Vorschau mit Musterdaten</div>
          </div>
          {(recipients || []).map(r => (
            <div
              key={r.id}
              onClick={() => { onChangeRecipient(r); setPickerOpen(false); }}
              style={{ padding: "6px 10px", borderRadius: 4, cursor: "pointer", fontSize: 12.5,
                       background: r.id === recipient?.id ? "var(--primary-50)" : "transparent" }}
            >
              <div style={{ fontWeight: 500 }}>{r.label}</div>
              <div style={{ fontSize: 10.5, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{r.id}</div>
            </div>
          ))}
          {(recipients || []).length === 0 && (
            <div className="empty-hint" style={{ padding: 8 }}>Keine Empfänger gefunden.</div>
          )}
        </div>
      )}

      <div className="preview-doc" style={{ position: "relative" }}>
        {previewLoading && <div className="editor-loading">PDF wird gerendert …</div>}
        {!previewLoading && previewError && (
          <div className="editor-loading" style={{ color: "var(--danger)", padding: 16, textAlign: "center" }}>
            {previewError}
          </div>
        )}
        {!previewLoading && !previewError && pdfUrl && (
          <iframe title="PDF-Vorschau" src={pdfUrl} style={{ width: "100%", height: "100%", border: "none", minHeight: 420 }}/>
        )}
        {!previewLoading && !previewError && !pdfUrl && (
          <div className="editor-loading">Noch keine Vorschau · „▶" zum Rendern.</div>
        )}
      </div>
      <div className="preview-footer">
        <span>
          <span className="render-dot"/>{" "}
          {previewMode === "durchlauf" ? "Echter Empfänger" :
           previewMode === "split_preview" ? "Beispielwerte" : "PDF-Vorschau"}
          {" · gespeicherter Stand"}
        </span>
        {pdfUrl && (
          <a className="btn sm ghost" href={pdfUrl} download={`vorlage-${template.id || "preview"}.pdf`} title="PDF herunterladen">
            <Icon name="download" size={12}/> PDF
          </a>
        )}
      </div>
    </div>
  );
};

// =========================
// Placeholder pane (echt)
// =========================
const PlaceholderPane = ({ groups, onInsert }) => {
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return groups;
    return groups.map(g => ({
      ...g,
      items: g.items.filter(it =>
        (it.label || "").toLowerCase().includes(query) ||
        (it.token || "").toLowerCase().includes(query) ||
        (it.hint || "").toLowerCase().includes(query)
      ),
    })).filter(g => g.items.length > 0);
  }, [q, groups]);

  const onDragStart = (e, token) => {
    e.dataTransfer.setData("application/json", JSON.stringify({ kind: "placeholder", token }));
    e.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div className="ph-pane">
      <div className="ph-search">
        <div className="ph-search-wrap">
          <span className="icon-left"><Icon name="search" size={13}/></span>
          <input className="ph-search-input" placeholder="Platzhalter suchen…" value={q} onChange={e => setQ(e.target.value)}/>
        </div>
        <div className="ph-hint">Felder des Objekts (objekt.*) + genutzte Platzhalter · Klicken zum Einfügen · Zahl = Häufigkeit</div>
      </div>

      {filtered.map(g => (
        <div className="ph-group" key={g.key}>
          <div className="ph-group-title">
            <Icon name={g.icon || "tag"} size={12}/>
            <span>{g.label}</span>
            <span className="ph-group-count">{g.items.length}</span>
          </div>
          {g.items.map((it, i) => (
            <div
              key={i}
              className="ph-item"
              draggable
              onDragStart={e => onDragStart(e, it.token)}
              onClick={() => onInsert(it.token)}
              title={`Klicken zum Einfügen: ${it.token}`}
            >
              <span style={{ color: "var(--text-faint)", paddingTop: 2 }}><Icon name="drag" size={12}/></span>
              <div className="ph-text">
                <div className="ph-label">{it.hint || it.label}</div>
                <span className="ph-token">{it.token}</span>
              </div>
              {it.count > 0 && <div className="ph-insert" title={`${it.count}× in Vorlagen verwendet`}>{it.count}</div>}
            </div>
          ))}
        </div>
      ))}

      {filtered.length === 0 && (
        <div className="empty-hint" style={{ marginTop: 24 }}>Keine Platzhalter für „{q}".</div>
      )}
    </div>
  );
};

// =========================
// Bausteine pane (echt)
// =========================
const BausteinePane = ({ items, onInsert }) => {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return items;
    return items.filter(b =>
      (b.title || "").toLowerCase().includes(query) ||
      (b.description || "").toLowerCase().includes(query)
    );
  }, [q, items]);

  const onDragStart = (e, name) => {
    e.dataTransfer.setData("application/json", JSON.stringify({ kind: "baustein", name }));
    e.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div className="bs-pane">
      <div className="ph-search" style={{ paddingBottom: 8 }}>
        <div className="ph-search-wrap">
          <span className="icon-left"><Icon name="search" size={13}/></span>
          <input className="ph-search-input" placeholder="Baustein suchen…" value={q} onChange={e => setQ(e.target.value)}/>
        </div>
        <div className="ph-hint"><strong>{items.length}</strong> Textbausteine · Klicken fügt {`{{ baustein("…") }}`} an den Cursor</div>
      </div>

      {filtered.map((b, i) => (
        <div key={i} className="bs-card" draggable onDragStart={e => onDragStart(e, b.name)}>
          <div className="bs-head">
            <Icon name="block" size={13} style={{ color: "var(--accent)" }}/>
            <div style={{ flex: 1 }}>
              <div className="bs-title">{b.title}</div>
              {b.description && <div className="bs-desc">{b.description}</div>}
            </div>
          </div>
          {b.preview && <div className="bs-preview">{b.preview}</div>}
          <div className="bs-actions">
            <button className="btn sm" onClick={() => onInsert(b.name)}>
              <Icon name="plus" size={12}/> An Cursor einfügen
            </button>
          </div>
        </div>
      ))}

      {filtered.length === 0 && (
        <div className="empty-hint" style={{ marginTop: 24 }}>Keine Bausteine für „{q}".</div>
      )}
    </div>
  );
};

// =========================
// Variables pane (echt, read-only)
// =========================
const VariablesPane = ({ variables, onInsert }) => {
  const vars = variables || [];
  return (
    <div className="var-pane">
      <div style={{ marginBottom: 10, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
        Vorlagen-Variablen dieser Vorlage. Im Editor als Platzhalter einfügbar; Bearbeiten der Definition erfolgt (noch) im Formular.
      </div>
      {vars.length === 0 && (
        <div className="empty-hint">Keine Variablen in dieser Vorlage.</div>
      )}
      {vars.map((v, i) => (
        <div key={i} className="var-row" onClick={() => onInsert && onInsert(`{{ ${v.variable} }}`)} title={`Einfügen: {{ ${v.variable} }}`} style={{ cursor: "pointer" }}>
          <div className="var-name-wrap">
            <div className="var-name">{v.variable}</div>
            {(v.label || v.beschreibung) && <div className="var-desc">{v.label || v.beschreibung}</div>}
          </div>
          <div className="var-type">{v.type || "—"}</div>
        </div>
      ))}
    </div>
  );
};

// =========================
// Sidebar shell
// =========================
export const Sidebar = ({
  tab, onTab, template, recipient, recipients,
  placeholders, bausteine,
  onChangeRecipient, onSearchRecipients,
  previewPdf, previewLoading, previewError, previewMode, onRefreshPreview,
  onInsertPlaceholder, onInsertBaustein, onMaximizePreview, onResizeStart,
}) => {
  const phCount = (placeholders || []).reduce((n, g) => n + g.items.length, 0);
  const bsCount = (bausteine || []).length;
  const varCount = (template.variables || []).length;

  return (
    <aside className="sidebar">
      <div className="sidebar-resize-handle" onMouseDown={onResizeStart} title="Ziehen zum Verbreitern"/>
      <div className="sb-tabs">
        <button className={`sb-tab ${tab === "preview" ? "active" : ""}`} onClick={() => onTab("preview")}>Vorschau</button>
        <button className={`sb-tab ${tab === "placeholders" ? "active" : ""}`} onClick={() => onTab("placeholders")}>
          Platzhalter <span className="sb-tab-badge">{phCount}</span>
        </button>
        <button className={`sb-tab ${tab === "bausteine" ? "active" : ""}`} onClick={() => onTab("bausteine")}>
          Bausteine <span className="sb-tab-badge">{bsCount}</span>
        </button>
        <button className={`sb-tab ${tab === "variables" ? "active" : ""}`} onClick={() => onTab("variables")}>
          Variablen <span className="sb-tab-badge">{varCount}</span>
        </button>
      </div>
      <div className="sb-body">
        {tab === "preview" && (
          <PreviewPane
            template={template} recipient={recipient} recipients={recipients}
            onChangeRecipient={onChangeRecipient} onSearchRecipients={onSearchRecipients}
            previewPdf={previewPdf} previewLoading={previewLoading} previewError={previewError}
            previewMode={previewMode} onRefresh={onRefreshPreview} onMaximize={onMaximizePreview}
          />
        )}
        {tab === "placeholders" && <PlaceholderPane groups={placeholders || []} onInsert={onInsertPlaceholder}/>}
        {tab === "bausteine" && <BausteinePane items={bausteine || []} onInsert={onInsertBaustein}/>}
        {tab === "variables" && <VariablesPane variables={template.variables} onInsert={onInsertPlaceholder}/>}
      </div>
    </aside>
  );
};
