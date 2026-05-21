import React, { useState, useCallback } from "react";
import { Icon } from "./components/Icon.jsx";
import { Navigator } from "./components/Navigator.jsx";
import { Editor } from "./components/Editor.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { PdfMaximized } from "./components/PdfMaximized.jsx";
import { CURRENT_TEMPLATE, SAMPLE_RECIPIENTS, TEMPLATE_TREE } from "./data.js";

export const App = () => {
  const [template, setTemplate] = useState(() => CURRENT_TEMPLATE);
  const [recipient, setRecipient] = useState(() => SAMPLE_RECIPIENTS[0]);
  const [tab, setTab] = useState("preview");
  const [dirty, setDirty] = useState(false);
  const [title, setTitle] = useState(template.title);
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [pdfMaximized, setPdfMaximized] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(420);
  const [resizing, setResizing] = useState(false);

  // Resize handle for the right sidebar — drag left edge horizontally
  const onResizeStart = useCallback((e) => {
    e.preventDefault();
    setResizing(true);
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    const onMove = (ev) => {
      const delta = startX - ev.clientX;
      const next = Math.max(320, Math.min(900, startWidth + delta));
      setSidebarWidth(next);
    };
    const onUp = () => {
      setResizing(false);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [sidebarWidth]);

  // Insert a chip / snippet / baustein "at cursor" — for the prototype, append
  // to the last paragraph block (or append a new block).
  const insertItem = useCallback((item) => {
    setTemplate(prev => {
      const blocks = [...prev.blocks];
      if (item.kind === "chip") {
        const last = blocks[blocks.length - 1];
        if (last?.type === "p") {
          last.inlines = [...last.inlines, { type: "text", value: " " }, { type: "chip", token: item.token }];
        } else {
          blocks.push({ type: "p", inlines: [{ type: "chip", token: item.token }] });
        }
      } else if (item.kind === "baustein") {
        blocks.push({ type: "baustein", name: item.name });
      } else if (item.kind === "snippet") {
        // Insert a sample jinja-if block to visualize the snippet
        if (item.snippet.key.startsWith("if")) {
          blocks.push({
            type: "jinja-if",
            condition: item.snippet.key === "if-eq" ? 'FELD == "WERT"' : 'BEDINGUNG',
            thenBlocks: [{ type: "p", inlines: [{ type: "text", value: "Inhalt der Bedingung …" }] }],
          });
        } else {
          // fallback — append as text marker
          blocks.push({ type: "p", inlines: [{ type: "text", value: item.snippet.value }] });
        }
      }
      return { ...prev, blocks };
    });
    setDirty(true);
  }, []);

  const insertPlaceholder = useCallback((token) => insertItem({ kind: "chip", token }), [insertItem]);
  const insertBaustein = useCallback((name) => insertItem({ kind: "baustein", name }), [insertItem]);
  const removeBaustein = useCallback((name) => {
    setTemplate(prev => ({ ...prev, blocks: prev.blocks.filter(b => !(b.type === "baustein" && b.name === name)) }));
    setDirty(true);
  }, []);

  const onTemplateSelect = useCallback((id) => {
    // For the prototype we keep the current template — but show a hint
    // Could swap content per id; we'll just update title for visual feedback
    const allTemplates = TEMPLATE_TREE.flatMap(c => c.templates);
    const t = allTemplates.find(x => x.id === id);
    if (!t) return;
    if (id === "t-001") {
      setTemplate(CURRENT_TEMPLATE);
      setTitle(CURRENT_TEMPLATE.title);
    } else {
      // Build a stub template for visual feedback
      setTemplate({
        ...CURRENT_TEMPLATE,
        id,
        title: t.title,
        blocks: [
          { type: "h2", inlines: [{ type: "text", value: t.title }] },
          { type: "p", inlines: [{ type: "text", value: 'Diese Vorlage ist im Prototyp nicht hinterlegt. Wechsel zurück zu „1. Mahnung" für die volle Demo.' }] },
        ],
      });
      setTitle(t.title);
    }
    setDirty(false);
  }, []);

  const save = () => {
    setDirty(false);
    // little visual flash
  };

  return (
    <div className="app">
      <header className="topbar">
        <button className="btn ghost icon" title="Zurück zur Liste"><Icon name="back" size={16}/></button>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
          <span className="crumb">Serienbrief · {template.kategorie}</span>
        </div>
        <input
          className="title-input"
          value={title}
          onChange={e => { setTitle(e.target.value); setDirty(true); }}
        />
        <span className="status-pill">{template.haupt_verteil_objekt}</span>

        <div className="spacer"/>

        <div className="meta">
          {dirty ? (
            <span style={{ color: "var(--warn)" }}>● Ungespeicherte Änderungen</span>
          ) : (
            <span><span className="dot"/> Gespeichert · {template.modified}</span>
          )}
        </div>

        <button className="btn" onClick={save} disabled={!dirty}>
          <Icon name="save" size={14}/> Speichern
        </button>
        <button className="btn ghost"><Icon name="copy" size={14}/> Kopieren</button>
        <button className="btn primary">
          <Icon name="send" size={14}/> In Serienbrief laden
        </button>
        <button className="btn ghost icon"><Icon name="more"/></button>
      </header>

      <div
        className={`main ${resizing ? "resizing" : ""}`}
        style={{ gridTemplateColumns: `${navCollapsed ? "44px" : "260px"} 1fr ${sidebarWidth}px` }}
      >
        <Navigator currentId={template.id} onSelect={onTemplateSelect} collapsed={navCollapsed} onToggleCollapse={() => setNavCollapsed(c => !c)}/>
        <Editor
          template={template}
          recipient={recipient}
          onInsertItem={insertItem}
          onPickRecipient={() => setRecipientPickerOpen(true)}
          onMaximizePreview={() => setPdfMaximized(true)}
        />
        <Sidebar
          tab={tab}
          onTab={setTab}
          template={template}
          recipient={recipient}
          onChangeRecipient={setRecipient}
          onInsertPlaceholder={insertPlaceholder}
          onInsertBaustein={insertBaustein}
          onRemoveBaustein={removeBaustein}
          onMaximizePreview={() => setPdfMaximized(true)}
          onResizeStart={onResizeStart}
        />
      </div>

      {recipientPickerOpen && (
        <div className="modal-backdrop" onClick={() => setRecipientPickerOpen(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>Empfänger für Vorschau wählen</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Die Vorlage wird für den gewählten Empfänger gerendert — Platzhalter, Bausteine und Bedingungen werden ausgewertet.</div>
              </div>
              <button className="btn ghost icon" onClick={() => setRecipientPickerOpen(false)}><Icon name="x" size={14}/></button>
            </div>
            <div className="modal-body">
              {SAMPLE_RECIPIENTS.map(r => (
                <div
                  key={r.id}
                  className={`recipient-row ${r.id === recipient.id ? "active" : ""}`}
                  onClick={() => { setRecipient(r); setRecipientPickerOpen(false); }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 500, fontSize: 13 }}>{r.label}</div>
                    <div style={{ fontSize: 11, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{r.id} · Mahnstufe {r.values.mahnstufe} · Saldo {r.values.saldo}</div>
                  </div>
                  {r.id === recipient.id && <Icon name="check" size={14}/>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {pdfMaximized && (
        <PdfMaximized
          template={template}
          recipient={recipient}
          onChangeRecipient={setRecipient}
          onClose={() => setPdfMaximized(false)}
        />
      )}
    </div>
  );
};

