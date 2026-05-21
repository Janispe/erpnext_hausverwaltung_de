import React, { useState, useRef, useEffect, useMemo } from "react";
import { Icon } from "./Icon.jsx";
import { PLACEHOLDER_GROUPS, SNIPPETS, TEXT_BAUSTEINE } from "../data.js";
import { decorateTemplateHtml } from "../htmlDecorate.js";

// Read-only-Anzeige echter Vorlagen: das HTML aus der DB, mit Chip-dekorierten
// Jinja-Tokens. Wird statt des Block-Modells gerendert, wenn htmlContent gesetzt ist.
const RenderedHtml = ({ html }) => {
  const decorated = useMemo(() => decorateTemplateHtml(html), [html]);
  return <div className="rendered-html" dangerouslySetInnerHTML={{ __html: decorated }} />;
};

// Find which placeholder-group a token belongs to (for chip color & tooltip)
const tokenGroup = (token) => {
  const inner = (token.match(/\{\{\s*([^}]+?)\s*\}\}/) || [])[1] || "";
  const prefix = inner.split(".")[0].trim();
  const map = {
    mieter: "mieter",
    verwalter: "verwalter",
    wohnung: "wohnung",
    immobilie: "wohnung",
    mietvertrag: "vertrag",
    saldo: "vertrag",
    saldo_betrag: "vertrag",
    kaltmiete: "vertrag",
    nebenkosten: "vertrag",
    warmmiete: "vertrag",
    mahnstufe: "vertrag",
    datum: "datum",
    datum_iso: "datum",
    stichtag: "datum",
    frist_tage: "datum",
    bankkonto: "bank",
  };
  return map[prefix] || "mieter";
};

const tokenKey = (token) => (token.match(/\{\{\s*([^}]+?)\s*\}\}/) || [])[1]?.trim() || "";

const findPlaceholderMeta = (token) => {
  const groups = PLACEHOLDER_GROUPS;
  for (const g of groups) {
    for (const item of g.items) {
      if (item.token === token) return { ...item, group: g };
    }
  }
  return null;
};

// =========================
// Chip with hover tooltip
// =========================
const Chip = ({ token, emphasis, recipient }) => {
  const [tt, setTt] = useState(null);
  const ref = useRef(null);
  const group = tokenGroup(token);
  const key = tokenKey(token);
  const value = recipient?.values?.[key];

  const onEnter = () => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    setTt({ x: r.left, y: r.bottom + 6 });
  };
  const onLeave = () => setTt(null);

  const meta = findPlaceholderMeta(token);
  return (
    <span
      ref={ref}
      className={`chip ${emphasis ? "emphasis" : ""}`}
      data-group={group}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      {token}
      {tt && (
        <span
          className="chip-tooltip"
          style={{ left: tt.x, top: tt.y }}
        >
          <span className="tt-token">{token}</span>
          <span className="tt-value">
            {value != null ? value : <em style={{color:"#bbb"}}>kein Wert für diesen Empfänger</em>}
          </span>
          {meta && <span className="tt-label">{meta.label}{meta.desc ? ` — ${meta.desc}` : ""}</span>}
        </span>
      )}
    </span>
  );
};

// =========================
// Render inline node
// =========================
const Inline = ({ node, recipient }) => {
  if (node.type === "text") return <span>{node.value}</span>;
  if (node.type === "chip") return <Chip token={node.token} emphasis={node.emphasis} recipient={recipient} />;
  return null;
};

// =========================
// Render a block in the editor "paper"
// =========================
const Block = ({ block, recipient }) => {
  if (block.type === "p") {
    const cls = block.align === "right" ? "right" : "";
    return (
      <p className={cls}>
        {block.inlines.length === 0 || (block.inlines.length === 1 && !block.inlines[0].value)
          ? <br/>
          : block.inlines.map((n, i) => <Inline key={i} node={n} recipient={recipient}/>)}
      </p>
    );
  }
  if (block.type === "h2") {
    return (
      <h2>
        {block.inlines.map((n, i) => <Inline key={i} node={n} recipient={recipient}/>)}
      </h2>
    );
  }
  if (block.type === "baustein") {
    const bs = TEXT_BAUSTEINE.find(b => b.name === block.name);
    const fullPreview = bs?.preview || "(Baustein-Inhalt)";
    // Compact: collapse multiple newlines to single, truncate to ~140 chars
    const compact = fullPreview.replace(/\n+/g, " · ").trim();
    const truncated = compact.length > 140 ? compact.slice(0, 140) + "…" : compact;
    return (
      <div className="baustein-block">
        <div className="baustein-head">
          <Icon name="block" size={12}/>
          <span>BAUSTEIN</span>
          {bs?.pageBreakBefore && <span className="baustein-hint">↵ Seitenumbruch davor</span>}
        </div>
        <div className="baustein-name-row">{block.name}</div>
        <div className="baustein-preview baustein-preview-compact">{truncated}</div>
      </div>
    );
  }
  if (block.type === "jinja-if") {
    return (
      <div className="jinja-block">
        <div className="jinja-head">
          <Icon name="branch" size={12}/>
          <span>{`{% if ${block.condition} %}`}</span>
        </div>
        <div className="jinja-body">
          {block.thenBlocks.map((b, i) => <Block key={i} block={b} recipient={recipient}/>)}
        </div>
        <div className="jinja-foot">{`{% endif %}`}</div>
      </div>
    );
  }
  return null;
};

// =========================
// Slash menu
// =========================
const SlashMenu = ({ open, x, y, query, onClose, onPick }) => {
  if (!open) return null;
  const groups = PLACEHOLDER_GROUPS;
  const snippets = SNIPPETS;
  const bausteine = TEXT_BAUSTEINE;

  const q = (query || "").toLowerCase().trim();
  const matchesPh = groups.flatMap(g =>
    g.items
      .filter(it => !q || it.label.toLowerCase().includes(q) || it.token.toLowerCase().includes(q))
      .map(it => ({ kind: "placeholder", group: g, item: it }))
  );
  const matchesSn = snippets.filter(s => !q || s.label.toLowerCase().includes(q)).map(s => ({ kind: "snippet", item: s }));
  const matchesBs = bausteine.filter(b => !q || b.name.toLowerCase().includes(q)).map(b => ({ kind: "baustein", item: b }));

  const [active, setActive] = useState(0);
  const all = [...matchesPh.slice(0, 8), ...matchesSn, ...matchesBs];

  useEffect(() => { setActive(0); }, [query]);

  useEffect(() => {
    const onKey = (e) => {
      if (!open) return;
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, all.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
      if (e.key === "Enter") {
        e.preventDefault();
        const sel = all[active];
        if (sel) onPick(sel);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, all, active, onClose, onPick]);

  return (
    <div className="slash-menu" style={{ left: x, top: y }}>
      <div className="slash-header">Einfügen{query ? ` · "${query}"` : ""}</div>
      <div className="slash-list">
        {matchesPh.length > 0 && <div className="slash-section-label">Platzhalter</div>}
        {matchesPh.slice(0, 8).map((m, i) => (
          <div key={`p-${i}`} className={`slash-item ${i === active ? "active" : ""}`} onMouseEnter={() => setActive(i)} onClick={() => onPick(m)}>
            <span className="slash-icon"><Icon name={m.group.icon} size={13}/></span>
            <span className="slash-text">
              <div className="slash-label">{m.item.label}</div>
              <div className="slash-desc">{m.item.token}</div>
            </span>
          </div>
        ))}
        {matchesSn.length > 0 && <div className="slash-section-label">Snippets</div>}
        {matchesSn.map((m, i) => {
          const idx = matchesPh.slice(0, 8).length + i;
          return (
            <div key={`s-${i}`} className={`slash-item ${idx === active ? "active" : ""}`} onMouseEnter={() => setActive(idx)} onClick={() => onPick(m)}>
              <span className="slash-icon"><Icon name="branch" size={13}/></span>
              <span className="slash-text">
                <div className="slash-label">{m.item.label}</div>
                <div className="slash-desc">{m.item.desc}</div>
              </span>
            </div>
          );
        })}
        {matchesBs.length > 0 && <div className="slash-section-label">Bausteine</div>}
        {matchesBs.map((m, i) => {
          const idx = matchesPh.slice(0, 8).length + matchesSn.length + i;
          return (
            <div key={`b-${i}`} className={`slash-item ${idx === active ? "active" : ""}`} onMouseEnter={() => setActive(idx)} onClick={() => onPick(m)}>
              <span className="slash-icon"><Icon name="block" size={13}/></span>
              <span className="slash-text">
                <div className="slash-label">{m.item.name}</div>
                <div className="slash-desc">{m.item.desc}</div>
              </span>
            </div>
          );
        })}
        {all.length === 0 && (
          <div className="empty-hint">Keine Treffer für „{query}".</div>
        )}
      </div>
    </div>
  );
};

// =========================
// Editor Toolbar
// =========================
const EditorToolbar = ({ onInsert }) => {
  return (
    <div className="editor-toolbar">
      <div className="tool-group">
        <select className="block-style-select" defaultValue="Fließtext">
          <option>Fließtext</option>
          <option>Überschrift 1</option>
          <option>Überschrift 2</option>
        </select>
      </div>
      <div className="tool-group">
        <button className="tool-btn" title="Fett"><Icon name="bold"/></button>
        <button className="tool-btn" title="Kursiv"><Icon name="italic"/></button>
        <button className="tool-btn" title="Unterstrichen"><Icon name="underline"/></button>
      </div>
      <div className="tool-group">
        <button className="tool-btn active" title="Links"><Icon name="align-left"/></button>
        <button className="tool-btn" title="Zentriert"><Icon name="align-center"/></button>
        <button className="tool-btn" title="Rechts"><Icon name="align-right"/></button>
      </div>
      <div className="tool-group">
        <button className="tool-btn" title="Liste"><Icon name="list"/></button>
        <button className="tool-btn" title="Nummerierte Liste"><Icon name="list-ordered"/></button>
        <button className="tool-btn" title="Link"><Icon name="link"/></button>
      </div>
      <div style={{ flex: 1 }}/>
      <div className="tool-group" style={{ borderRight: "none" }}>
        <button className="tool-btn tool-btn-wide primary-tool" onClick={onInsert} title="Einfügen / Slash-Commander">
          <Icon name="tag" size={14}/>
          <span>Einfügen</span>
          <span className="kbd" style={{ marginLeft: 4 }}>/</span>
        </button>
      </div>
    </div>
  );
};

// =========================
// Sanity Status Row — shown above the editor, summarizes the preview situation
// =========================
const SanityStatusRow = ({ recipient, onPickRecipient, onMaximizePreview }) => {
  const v = recipient?.values || {};
  const mahnstufe2 = v.mahnstufe === "2";

  return (
    <div className="sanity-row">
      <button className="sanity-recipient" onClick={onPickRecipient} title="Empfänger wechseln">
        <Icon name="user" size={13}/>
        <span className="sanity-recipient-label">Vorschau-Empfänger</span>
        <span className="sanity-recipient-value">{recipient.label.split("—")[0].trim()}</span>
        <Icon name="chevron-down" size={11}/>
      </button>

      <div className="sanity-stats">
        <span className="sanity-badge ok">
          <Icon name="check" size={11}/> 28/28 Platzhalter aufgelöst
        </span>
        {mahnstufe2 ? (
          <span className="sanity-badge warn">
            <Icon name="branch" size={11}/> Mahnstufe-2-Klausel aktiv
          </span>
        ) : (
          <span className="sanity-badge muted">
            <Icon name="branch" size={11}/> Mahnstufe-2-Klausel inaktiv
          </span>
        )}
        <span className="sanity-badge muted">
          <Icon name="block" size={11}/> 2 Bausteine eingebettet
        </span>
      </div>

      <button className="sanity-action" onClick={onMaximizePreview} title="PDF-Vorschau vergrößern">
        <Icon name="play" size={12}/>
        <span>PDF groß ansehen</span>
      </button>
    </div>
  );
};

// =========================
// Editor (Paper)
// =========================
export const Editor = ({ template, recipient, loading, onInsertItem, onPickRecipient, onMaximizePreview }) => {
  const hasHtml = typeof template.htmlContent === "string" && template.htmlContent.length > 0;
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashPos, setSlashPos] = useState({ x: 0, y: 0 });
  const [slashQuery, setSlashQuery] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const editorRef = useRef(null);

  const openSlash = (anchorRect) => {
    const r = anchorRect || editorRef.current?.getBoundingClientRect();
    setSlashPos({ x: (r?.left || 100) + 60, y: (r?.top || 100) + 40 });
    setSlashQuery("");
    setSlashOpen(true);
  };

  const closeSlash = () => setSlashOpen(false);

  const onPick = (selection) => {
    if (selection.kind === "placeholder") {
      onInsertItem({ kind: "chip", token: selection.item.token });
    } else if (selection.kind === "snippet") {
      onInsertItem({ kind: "snippet", snippet: selection.item });
    } else if (selection.kind === "baustein") {
      onInsertItem({ kind: "baustein", name: selection.item.name });
    }
    closeSlash();
  };

  // Drop handling
  const onDragOver = (e) => {
    e.preventDefault();
    setDragOver(true);
  };
  const onDragLeave = () => setDragOver(false);
  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    try {
      const data = JSON.parse(e.dataTransfer.getData("application/json"));
      if (data.kind === "placeholder") onInsertItem({ kind: "chip", token: data.token });
      else if (data.kind === "baustein") onInsertItem({ kind: "baustein", name: data.name });
    } catch (err) {}
  };

  // Keybind: "/" opens slash menu
  useEffect(() => {
    const onKey = (e) => {
      if (slashOpen) return;
      if (e.key === "/" && (e.target?.tagName !== "INPUT") && (e.target?.tagName !== "TEXTAREA")) {
        e.preventDefault();
        openSlash();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [slashOpen]);

  return (
    <main className="center">
      <SanityStatusRow recipient={recipient} onPickRecipient={onPickRecipient} onMaximizePreview={onMaximizePreview}/>
      <EditorToolbar onInsert={() => openSlash()}/>

      <div className="editor-scroll" ref={editorRef}>
        <div
          className={`paper editor-mode ${dragOver ? "drag-over" : ""}`}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          {loading ? (
            <div className="editor-loading">Vorlage wird geladen …</div>
          ) : hasHtml ? (
            <RenderedHtml html={template.htmlContent}/>
          ) : (
            (template.blocks || []).map((b, i) => (
              <Block key={i} block={b} recipient={recipient}/>
            ))
          )}
          {!loading && !hasHtml && (
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px dashed var(--border)", color: "var(--text-faint)", fontSize: 12, textAlign: "center" }}>
              Tippe <span className="kbd">/</span> für Platzhalter, Snippets oder Bausteine — oder ziehe aus der rechten Seitenleiste.
            </div>
          )}
          {!loading && hasHtml && (
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px dashed var(--border)", color: "var(--text-faint)", fontSize: 12, textAlign: "center" }}>
              Echte Vorlage · read-only Vorschau · Bearbeiten &amp; Speichern folgt im nächsten Schritt.
            </div>
          )}
        </div>
      </div>

      <SlashMenu
        open={slashOpen}
        x={slashPos.x}
        y={slashPos.y}
        query={slashQuery}
        onClose={closeSlash}
        onPick={onPick}
      />
    </main>
  );
};

