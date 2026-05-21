import React, { useState, useMemo, useEffect } from "react";
import { Icon } from "./Icon.jsx";
import { SAMPLE_RECIPIENTS, PLACEHOLDER_GROUPS, TEXT_BAUSTEINE, TEMPLATE_VARIABLES } from "../data.js";

// =========================
// Preview pane (renders template with values substituted)
// =========================
const PreviewInline = ({ node, recipient }) => {
  if (node.type === "text") return <span>{node.value}</span>;
  if (node.type === "chip") {
    const key = (node.token.match(/\{\{\s*([^}]+?)\s*\}\}/) || [])[1]?.trim();
    const v = recipient?.values?.[key];
    return <span className="live-value">{v != null ? v : node.token}</span>;
  }
  return null;
};
const PreviewBlock = ({ block, recipient }) => {
  if (block.type === "p") {
    const cls = block.align === "right" ? "right" : "";
    return (
      <p className={cls}>
        {block.inlines.length === 0 || (block.inlines.length === 1 && !block.inlines[0].value)
          ? <br/>
          : block.inlines.map((n, i) => <PreviewInline key={i} node={n} recipient={recipient}/>)}
      </p>
    );
  }
  if (block.type === "h2") {
    return <h2>{block.inlines.map((n, i) => <PreviewInline key={i} node={n} recipient={recipient}/>)}</h2>;
  }
  if (block.type === "baustein") {
    const bs = TEXT_BAUSTEINE.find(b => b.name === block.name);
    const previewText = bs?.preview || "";
    // Substitute placeholders in baustein preview
    const substituted = previewText.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, k) => {
      const v = recipient?.values?.[k.trim()];
      return v != null ? v : `{{ ${k.trim()} }}`;
    });
    return <div style={{ whiteSpace: "pre-wrap", margin: "6px 0" }}>{substituted}</div>;
  }
  if (block.type === "jinja-if") {
    // Evaluate (simple) — for sample data, check mahnstufe
    const cond = block.condition;
    let show = false;
    const m = cond.match(/^(\w+)\s*==\s*"([^"]+)"$/);
    if (m) {
      const k = m[1];
      const v = recipient?.values?.[k];
      show = String(v) === m[2];
    }
    if (!show) return null;
    return <>{block.thenBlocks.map((b, i) => <PreviewBlock key={i} block={b} recipient={recipient}/>)}</>;
  }
  return null;
};

const PreviewPane = ({ template, recipient, onChangeRecipient, onMaximize }) => {
  const [pickerOpen, setPickerOpen] = useState(false);

  return (
    <div className="preview-pane">
      <div className="preview-control">
        <div className="recipient-picker" onClick={() => setPickerOpen(o => !o)}>
          <Icon name="user" size={13}/>
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2, flex: 1, minWidth: 0 }}>
            <span className="pp-label">Empfänger ({template.haupt_verteil_objekt})</span>
            <span className="pp-value" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {recipient.label}
            </span>
          </div>
          <Icon name="chevron-down" size={12}/>
        </div>
        <button className="btn sm icon" title="PDF groß ansehen" onClick={onMaximize}>
          <Icon name="play" size={13}/>
        </button>
      </div>

      {pickerOpen && (
        <div style={{ borderBottom: "1px solid var(--border)", background: "var(--surface)", padding: 8 }}>
          {SAMPLE_RECIPIENTS.map(r => (
            <div
              key={r.id}
              onClick={() => { onChangeRecipient(r); setPickerOpen(false); }}
              style={{
                padding: "6px 10px",
                borderRadius: 4,
                cursor: "pointer",
                fontSize: 12.5,
                background: r.id === recipient.id ? "var(--primary-50)" : "transparent",
                color: r.id === recipient.id ? "var(--primary-hover)" : "var(--text)",
                marginBottom: 2,
              }}
              onMouseEnter={(e) => { if (r.id !== recipient.id) e.currentTarget.style.background = "var(--surface-hover)"; }}
              onMouseLeave={(e) => { if (r.id !== recipient.id) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ fontWeight: 500 }}>{r.label}</div>
              <div style={{ fontSize: 10.5, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{r.id}</div>
            </div>
          ))}
        </div>
      )}

      <div className="preview-doc">
        <div className="preview-paper">
          {template.blocks.map((b, i) => <PreviewBlock key={i} block={b} recipient={recipient}/>)}
        </div>
      </div>
      <div className="preview-footer">
        <span><span className="render-dot"/> PDF gerendert · 1,4 s</span>
        <button className="btn sm ghost" title="PDF herunterladen"><Icon name="download" size={12}/> PDF</button>
      </div>
    </div>
  );
};

// =========================
// Placeholder pane
// =========================
const PlaceholderPane = ({ recipient, onInsert }) => {
  const [q, setQ] = useState("");
  const groups = PLACEHOLDER_GROUPS;

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return groups;
    return groups.map(g => ({
      ...g,
      items: g.items.filter(it =>
        it.label.toLowerCase().includes(query) ||
        it.token.toLowerCase().includes(query) ||
        (it.desc || "").toLowerCase().includes(query)
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
          <input
            className="ph-search-input"
            placeholder="Platzhalter suchen…"
            value={q}
            onChange={e => setQ(e.target.value)}
          />
        </div>
        <div className="ph-hint">
          Klicken um einzufügen · Ziehen für Drop-Position · Werte für <strong>{recipient.label.split("—")[0].trim()}</strong>
        </div>
      </div>

      {filtered.map(g => {
        const tokKey = (t) => (t.match(/\{\{\s*([^}]+?)\s*\}\}/) || [])[1]?.trim() || "";
        return (
          <div className="ph-group" key={g.key}>
            <div className="ph-group-title">
              <Icon name={g.icon} size={12}/>
              <span>{g.label}</span>
              <span className="ph-group-count">{g.items.length}</span>
            </div>
            {g.items.map((it, i) => {
              const value = recipient?.values?.[tokKey(it.token)];
              return (
                <div
                  key={i}
                  className="ph-item"
                  draggable
                  onDragStart={e => onDragStart(e, it.token)}
                  onClick={() => onInsert(it.token)}
                  title={`Klicken zum Einfügen: ${it.token}`}
                >
                  <span style={{ color: "var(--text-faint)", paddingTop: 2 }}>
                    <Icon name="drag" size={12}/>
                  </span>
                  <div className="ph-text">
                    <div className="ph-label">{it.label}</div>
                    <span className="ph-token">{it.token}</span>
                    {value != null && <div className="ph-value">→ {String(value)}</div>}
                  </div>
                  <div className="ph-insert">+</div>
                </div>
              );
            })}
          </div>
        );
      })}

      {filtered.length === 0 && (
        <div className="empty-hint" style={{ marginTop: 24 }}>
          Keine Platzhalter für „{q}".
        </div>
      )}
    </div>
  );
};

// =========================
// Bausteine pane
// =========================
const BausteinePane = ({ template, onInsert, onRemoveBaustein }) => {
  const all = TEXT_BAUSTEINE;
  const usedNames = new Set((template.blocks || []).filter(b => b.type === "baustein").map(b => b.name));

  const onDragStart = (e, name) => {
    e.dataTransfer.setData("application/json", JSON.stringify({ kind: "baustein", name }));
    e.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div className="bs-pane">
      <div style={{ marginBottom: 12, fontSize: 12, color: "var(--text-muted)" }}>
        <strong style={{ color: "var(--text)" }}>{usedNames.size}</strong> Bausteine in dieser Vorlage verwendet · Verwaltet im Reiter <em>Serienbrief Textbaustein</em>.
      </div>

      {all.map((b, i) => {
        const used = usedNames.has(b.name);
        return (
          <div
            key={i}
            className="bs-card"
            draggable
            onDragStart={e => onDragStart(e, b.name)}
          >
            <div className="bs-head">
              <Icon name="block" size={13} style={{ color: "var(--accent)" }}/>
              <div style={{ flex: 1 }}>
                <div className="bs-title">{b.name}</div>
                <div className="bs-desc">{b.desc}</div>
              </div>
              {used && <span className="status-pill">in Vorlage</span>}
            </div>
            <div className="bs-preview">{b.preview}</div>
            <div className="bs-actions">
              {used ? (
                <button className="btn sm" onClick={() => onRemoveBaustein(b.name)}>
                  <Icon name="x" size={12}/> Entfernen
                </button>
              ) : (
                <button className="btn sm" onClick={() => onInsert(b.name)}>
                  <Icon name="plus" size={12}/> An Cursor einfügen
                </button>
              )}
              <button className="btn sm ghost"><Icon name="copy" size={12}/> Token kopieren</button>
            </div>
          </div>
        );
      })}

      <button className="btn sm" style={{ width: "100%", marginTop: 4 }}>
        <Icon name="plus" size={12}/> Neuen Baustein anlegen
      </button>
    </div>
  );
};

// =========================
// Variables pane
// =========================
const VariablesPane = () => {
  const vars = TEMPLATE_VARIABLES;
  return (
    <div className="var-pane">
      <div style={{ marginBottom: 10, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
        Vorlagen-Variablen sind feste Werte, die beim Erzeugen eines Serienbriefs überschreibbar sind — z. B. „Zahlungsfrist 14 Tage" oder „Mahngebühr 5 €". Im Editor als <code style={{fontFamily:"var(--font-mono)", fontSize:11, background:"var(--bg-subtle)", padding:"1px 4px", borderRadius:3}}>{`{{ frist_tage }}`}</code> einfügen.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 100px", gap: 4, padding: "6px 10px", fontSize: 11, color: "var(--text-faint)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
        <div>Name / Beschreibung</div>
        <div>Typ</div>
        <div>Standard</div>
      </div>

      {vars.map((v, i) => (
        <div key={i} className="var-row">
          <div className="var-name-wrap">
            <div className="var-name">{v.name}</div>
            <div className="var-desc">{v.desc}</div>
          </div>
          <div className="var-type">{v.type}</div>
          <input className="var-default" defaultValue={v.default}/>
        </div>
      ))}
      <button className="btn sm" style={{ width: "100%", marginTop: 8 }}>
        <Icon name="plus" size={12}/> Variable hinzufügen
      </button>
    </div>
  );
};

// =========================
// Sidebar shell
// =========================
export const Sidebar = ({ tab, onTab, template, recipient, onChangeRecipient, onInsertPlaceholder, onInsertBaustein, onRemoveBaustein, onMaximizePreview, onResizeStart }) => {
  const ph = PLACEHOLDER_GROUPS.reduce((n, g) => n + g.items.length, 0);
  const bsUsed = (template.blocks || []).filter(b => b.type === "baustein").length;
  const varCount = TEMPLATE_VARIABLES.length;

  return (
    <aside className="sidebar">
      <div className="sidebar-resize-handle" onMouseDown={onResizeStart} title="Ziehen zum Verbreitern"/>
      <div className="sb-tabs">
        <button className={`sb-tab ${tab === "preview" ? "active" : ""}`} onClick={() => onTab("preview")}>
          Vorschau
        </button>
        <button className={`sb-tab ${tab === "placeholders" ? "active" : ""}`} onClick={() => onTab("placeholders")}>
          Platzhalter <span className="sb-tab-badge">{ph}</span>
        </button>
        <button className={`sb-tab ${tab === "bausteine" ? "active" : ""}`} onClick={() => onTab("bausteine")}>
          Bausteine <span className="sb-tab-badge">{bsUsed}</span>
        </button>
        <button className={`sb-tab ${tab === "variables" ? "active" : ""}`} onClick={() => onTab("variables")}>
          Variablen <span className="sb-tab-badge">{varCount}</span>
        </button>
      </div>
      <div className="sb-body">
        {tab === "preview" && <PreviewPane template={template} recipient={recipient} onChangeRecipient={onChangeRecipient} onMaximize={onMaximizePreview}/>}
        {tab === "placeholders" && <PlaceholderPane recipient={recipient} onInsert={onInsertPlaceholder}/>}
        {tab === "bausteine" && <BausteinePane template={template} onInsert={onInsertBaustein} onRemoveBaustein={onRemoveBaustein}/>}
        {tab === "variables" && <VariablesPane/>}
      </div>
    </aside>
  );
};

