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
// Placeholder pane — rekursiver Baum (Parität zum alten Formular-Picker)
// =========================
const nodeMatches = (n, q) =>
  (n.label || "").toLowerCase().includes(q) || (n.token || "").toLowerCase().includes(q);

function filterNodes(nodes, q) {
  if (!q) return nodes || [];
  const out = [];
  for (const n of nodes || []) {
    const kids = filterNodes(n.children, q);
    if (nodeMatches(n, q) || kids.length) out.push({ ...n, children: kids });
  }
  return out;
}

export function countTokens(nodes) {
  let c = 0;
  for (const n of nodes || []) {
    if (n.token) c++;
    c += countTokens(n.children);
  }
  return c;
}

const TreeNode = ({ node, depth, onInsert, expandAll, tokenTransform }) => {
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(1); // 1-basiert; welches Child-Element
  const hasChildren = (node.children || []).length > 0;
  const isOpen = expandAll || open;
  const isTable = node.type === "Tabelle";
  const xform = tokenTransform || ((t) => t);

  // Für Kinder einer Tabelle: [0] -> [idx-1] (gewähltes Element).
  const childTransform = isTable ? (t) => xform(t).replace("[0]", `[${idx - 1}]`) : xform;
  const effToken = node.token ? xform(node.token) : "";

  // "Schleife über alle": Loop-Gerüst aus den Kindern ableiten.
  const insertLoop = () => {
    const childTok = (node.children || []).map((c) => c.token).find(Boolean) || "";
    const m = /\{\{\$\s*(.+?)\[0\]\./.exec(childTok);
    if (!m) return;
    const listPath = m[1]; // z.B. objekt.mieter
    const firstField =
      (node.children || [])
        .map((c) => (/\[0\]\.(\w+)/.exec(c.token || "") || [])[1])
        .find((f) => f && f !== "name") || "name";
    onInsert(`{% for eintrag in ${listPath} %}\n{{ eintrag.${firstField} }}\n{% endfor %}`);
  };

  return (
    <div className="ph-tree-node">
      <div className="ph-tree-row" style={{ paddingLeft: 6 + depth * 14 }}>
        {hasChildren ? (
          <span className="ph-tree-chev" onClick={() => setOpen(o => !o)}>
            <Icon name="chevron-right" size={11} style={{ transform: isOpen ? "rotate(90deg)" : "none" }}/>
          </span>
        ) : (
          <span className="ph-tree-chev spacer"/>
        )}
        <span
          className="ph-tree-label"
          draggable={!!effToken}
          onDragStart={effToken ? (e) => {
            e.dataTransfer.setData("application/json", JSON.stringify({ kind: "placeholder", token: effToken }));
            e.dataTransfer.effectAllowed = "copy";
          } : undefined}
          onClick={() => (effToken ? onInsert(effToken) : hasChildren && setOpen(o => !o))}
          title={effToken ? `Einfügen: ${effToken}` : node.label}
        >
          {node.label}
          {node.type && <span className="ph-tree-token ph-tree-type">{node.type}</span>}
        </span>
        {isTable && (
          <span className="ph-table-tools" onClick={(e) => e.stopPropagation()}>
            <input
              className="ph-idx-input"
              type="number"
              min={1}
              value={idx}
              title="Welches Element (1 = erstes)"
              onChange={(e) => setIdx(Math.max(1, parseInt(e.target.value, 10) || 1))}
            />
            <button className="ph-loop-btn" onClick={insertLoop} title="Schleife über alle Zeilen einfügen">
              ↻ alle
            </button>
          </span>
        )}
        {effToken && (
          <button className="ph-tree-insert" onClick={() => onInsert(effToken)} title="Einfügen">+</button>
        )}
      </div>
      {hasChildren && isOpen && (node.children || []).map((c, i) => (
        <TreeNode key={i} node={c} depth={depth + 1} onInsert={onInsert} expandAll={expandAll} tokenTransform={childTransform}/>
      ))}
    </div>
  );
};

const PlaceholderPane = ({ groups, onInsert }) => {
  const [q, setQ] = useState("");
  const query = q.trim().toLowerCase();
  const filtered = useMemo(
    () => (groups || []).map(g => ({ ...g, tree: filterNodes(g.tree, query) })).filter(g => (g.tree || []).length),
    [groups, query]
  );

  return (
    <div className="ph-pane">
      <div className="ph-search">
        <div className="ph-search-wrap">
          <span className="icon-left"><Icon name="search" size={13}/></span>
          <input className="ph-search-input" placeholder="Platzhalter suchen…" value={q} onChange={e => setQ(e.target.value)}/>
        </div>
        <div className="ph-hint">Felder des Objekts (rekursiv) + Variablen · Klicken oder Ziehen zum Einfügen</div>
      </div>

      {filtered.map(g => (
        <div className="ph-group" key={g.key}>
          <div className="ph-group-title">
            <Icon name={g.icon || "tag"} size={12}/>
            <span>{g.label}</span>
            <span className="ph-group-count">{countTokens(g.tree)}</span>
          </div>
          {(g.tree || []).map((n, i) => (
            <TreeNode key={i} node={n} depth={0} onInsert={onInsert} expandAll={!!query}/>
          ))}
        </div>
      ))}

      {filtered.length === 0 && (
        <div className="empty-hint" style={{ marginTop: 24 }}>Keine Platzhalter{query ? ` für „${q}"` : ""}.</div>
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
// Variables pane (editierbar: anlegen/löschen, Typ + Wert/Pfad)
// =========================
const VAR_TYPES = ["Text", "String", "Zahl", "Bool", "Datum", "Doctype", "Doctype Liste"];
const isDoctypeType = (t) => t === "Doctype" || t === "Doctype Liste";

const VariablesPane = ({ variables, onChange, onInsert, placeholderPaths }) => {
  const vars = variables || [];
  const update = (i, patch) =>
    onChange && onChange(vars.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));
  const remove = (i) => onChange && onChange(vars.filter((_, idx) => idx !== i));
  const add = () =>
    onChange &&
    onChange([
      ...vars,
      { variable: "", type: "Text", label: "", reference_doctype: "", value: "", path: "" },
    ]);

  return (
    <div className="var-pane">
      <div style={{ marginBottom: 10, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
        Vorlagen-Variablen: anlegen, Typ + Wert (Text) bzw. Pfad (Doctype) setzen. Im Brief via{" "}
        <code>{"{{ name }}"}</code> nutzbar. Speichern oben rechts.
      </div>
      <datalist id="hv-var-path-suggestions">
        {(placeholderPaths || []).map((p, i) => (
          <option key={i} value={p.path}>{p.type ? `${p.path} · ${p.type}` : p.path}</option>
        ))}
      </datalist>

      {vars.map((v, i) => {
        const dt = isDoctypeType(v.type);
        return (
          <div key={i} className="var-edit-row">
            <div className="var-edit-head">
              <input
                className="var-edit-name"
                placeholder="variablen_name"
                value={v.variable || ""}
                onChange={(e) => update(i, { variable: e.target.value })}
                spellCheck={false}
              />
              <select
                className="var-edit-type"
                value={v.type || "Text"}
                onChange={(e) => update(i, { type: e.target.value })}
              >
                {VAR_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <button className="var-edit-del" title="Variable löschen" onClick={() => remove(i)}>
                <Icon name="x" size={12} />
              </button>
            </div>

            {dt ? (
              <>
                <input
                  className="var-edit-sub"
                  placeholder="Referenz-Doctype (z. B. Immobilie)"
                  value={v.reference_doctype || ""}
                  onChange={(e) => update(i, { reference_doctype: e.target.value })}
                  spellCheck={false}
                />
                <input
                  className="var-edit-sub var-edit-path"
                  list="hv-var-path-suggestions"
                  placeholder="Pfad, z. B. objekt.wohnung.immobilie"
                  value={v.path || ""}
                  onChange={(e) => update(i, { path: e.target.value })}
                  spellCheck={false}
                />
              </>
            ) : (
              <input
                className="var-edit-sub"
                placeholder="Wert"
                value={v.value || ""}
                onChange={(e) => update(i, { value: e.target.value })}
              />
            )}

            <div className="var-edit-actions">
              <button
                className="var-insert-btn"
                disabled={!v.variable}
                onClick={() => onInsert && onInsert(`{{ ${v.variable} }}`)}
                title="In den Brief einfügen"
              >
                <Icon name="tag" size={11} /> einfügen
              </button>
            </div>
          </div>
        );
      })}

      {vars.length === 0 && <div className="empty-hint">Noch keine Variablen.</div>}
      <button className="var-add-btn" onClick={add}>
        <Icon name="plus" size={12} /> Variable hinzufügen
      </button>
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
  variables, placeholderPaths, onVariablesChange,
}) => {
  const phCount = (placeholders || []).reduce((n, g) => n + countTokens(g.tree), 0);
  const bsCount = (bausteine || []).length;
  const varCount = (variables || []).length;

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
        {tab === "variables" && (
          <VariablesPane
            variables={variables}
            onChange={onVariablesChange}
            onInsert={onInsertPlaceholder}
            placeholderPaths={placeholderPaths}
          />
        )}
      </div>
    </aside>
  );
};
