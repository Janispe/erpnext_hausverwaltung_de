import React, { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Icon } from "./components/Icon.jsx";
import { Navigator } from "./components/Navigator.jsx";
import { Editor } from "./components/Editor.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { PdfMaximized } from "./components/PdfMaximized.jsx";
import { PfadMappingModal } from "./components/PfadMappingModal.jsx";
import { BausteinPopover } from "./components/BausteinPopover.jsx";
import { CURRENT_TEMPLATE, TEMPLATE_TREE } from "./data.js";
import {
  loadTree, loadTemplate, saveTemplate,
  loadPlaceholderTree, loadBausteine, loadRecipients, renderPreview,
  uploadImage, embedded,
} from "./api.js";
import { validateJinjaBalance } from "./tiptap/validateJinja.js";

// Sentinel-Empfänger „Beispielwerte" (kein echter Datensatz → Split-Preview).
const BEISPIEL = { id: null, label: "Beispielwerte" };

export const App = () => {
  const [template, setTemplate] = useState(() => CURRENT_TEMPLATE);
  const [recipient, setRecipient] = useState(BEISPIEL);
  const [tab, setTab] = useState("preview");
  const [dirty, setDirty] = useState(false);
  const [title, setTitle] = useState(template.title);
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [pdfMaximized, setPdfMaximized] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(420);
  const [resizing, setResizing] = useState(false);
  const [tree, setTree] = useState(() => TEMPLATE_TREE);
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [placeholders, setPlaceholders] = useState([]);
  const [bausteine, setBausteine] = useState([]);
  const [recipients, setRecipients] = useState([]);
  const [previewPdf, setPreviewPdf] = useState("");
  const [previewMode, setPreviewMode] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  // Token-Erhalt-Check beim Laden: null = sicher, sonst { lost, added } -> Speichern blockiert.
  const [editorSafety, setEditorSafety] = useState(null);
  // Pro-Baustein Input-Pfad-Overrides { "<Baustein>": { "<Variable>": "<Pfad>" } }
  const [bausteinPaths, setBausteinPaths] = useState({});
  const [mappingBaustein, setMappingBaustein] = useState(null);
  const [popoverBaustein, setPopoverBaustein] = useState(null); // { baustein, rect }
  const contentRef = useRef(null); // Zugriff auf den editierbaren HTML-Inhalt (getHtml)

  const changeRecipient = useCallback((r) => setRecipient(r || BEISPIEL), []);

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

  // Insert a chip / snippet / baustein "at cursor" — immer über den TipTap-Editor (contentRef).
  // Guard: keine Mutation bei fehlender Schreibberechtigung oder unsicherer (read-only) Vorlage.
  const insertItem = useCallback((item) => {
    if (!template.canWrite || editorSafety) return;
    const api = contentRef.current;
    if (!api || !api.insertToken) return;
    let raw = "";
    if (item.kind === "chip") raw = item.token;
    else if (item.kind === "baustein") raw = `{{ baustein("${item.name}") }}`;
    else if (item.kind === "snippet") raw = item.snippet.value;
    if (raw) {
      api.insertToken(raw);
      setDirty(true);
    }
  }, [template.canWrite, editorSafety]);

  const insertPlaceholder = useCallback((token) => insertItem({ kind: "chip", token }), [insertItem]);
  const insertBaustein = useCallback((name) => insertItem({ kind: "baustein", name }), [insertItem]);

  // Vorlage auswählen. Eingebettet → echtes HTML aus der DB nachladen.
  // Standalone (Prototyp) → Demo-/Stub-Inhalt wie gehabt.
  const onTemplateSelect = useCallback(async (id) => {
    if (embedded) {
      setLoadingTemplate(true);
      try {
        const t = await loadTemplate(id);
        setTemplate(t);
        setTitle(t.title);
        setBausteinPaths(t.bausteinPaths || {});
        setDirty(false);
      } catch (e) {
        setTemplate({
          id,
          title: "Fehler beim Laden",
          kategorie: "",
          haupt_verteil_objekt: "",
          canWrite: false,
          htmlContent: `<h2>Vorlage konnte nicht geladen werden</h2><p>${String((e && e.message) || e)}</p>`,
        });
        setTitle("Fehler beim Laden");
      } finally {
        setLoadingTemplate(false);
      }
      return;
    }

    // Prototyp-Modus: Stub für visuelles Feedback
    const allTemplates = TEMPLATE_TREE.flatMap(c => c.templates);
    const t = allTemplates.find(x => x.id === id);
    if (!t) return;
    if (id === "t-001") {
      setTemplate(CURRENT_TEMPLATE);
      setTitle(CURRENT_TEMPLATE.title);
    } else {
      setTemplate({
        ...CURRENT_TEMPLATE,
        id,
        title: t.title,
        htmlContent: `<h2>${t.title}</h2><p>Diese Vorlage ist im Prototyp nicht hinterlegt. Wechsel zurück zu „1. Mahnung" für die volle Demo.</p>`,
      });
      setTitle(t.title);
    }
    setDirty(false);
  }, []);

  // Beim Start: echten Vorlagen-Baum laden; eingebettet zusätzlich die erste
  // Vorlage automatisch öffnen, damit die Mitte nicht mit Mock-Inhalt startet.
  useEffect(() => {
    let cancelled = false;
    loadTree()
      .then(({ groups }) => {
        if (cancelled || !groups || !groups.length) return;
        setTree(groups);
        if (embedded) {
          const first = groups.flatMap(g => g.templates)[0];
          if (first) onTemplateSelect(first.id);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [onTemplateSelect]);

  const save = async () => {
    if (!template.canWrite || !dirty || saving) return;
    // Harte Sperre: Vorlage round-trippt nicht verlustfrei (Token-Erhalt-Check beim Laden).
    if (editorSafety) {
      alert(
        "Speichern blockiert: Diese Vorlage enthält Strukturen, die der Editor nicht verlustfrei " +
        "abbilden kann (z. B. ein nicht unterstützter Schleifen-/Tabellen-Aufbau).\n\n" +
        "Verlorene Tokens: " + Object.keys(editorSafety.lost || {}).join(", ") +
        "\n\nBitte diese Vorlage vorerst im klassischen Formular bearbeiten."
      );
      return;
    }
    const html = contentRef.current ? contentRef.current.getHtml() : (template.htmlContent || "");
    // Jinja-Balance-Warnung (nicht blockierend).
    const bal = validateJinjaBalance(html);
    if (!bal.ok) {
      const proceed = confirm(
        "Mögliche Jinja-Probleme:\n\n" + bal.errors.join("\n") + "\n\nTrotzdem speichern?"
      );
      if (!proceed) return;
    }
    setSaving(true);
    try {
      const res = await saveTemplate(template.id, html, bausteinPaths);
      setDirty(false);
      setTemplate(prev => ({ ...prev, modified: res.modified || prev.modified }));
    } catch (e) {
      alert("Speichern fehlgeschlagen: " + ((e && e.message) || e));
    } finally {
      setSaving(false);
    }
  };

  // Template-unabhängige Sidebar-Daten einmalig laden.
  useEffect(() => {
    loadBausteine().then(r => setBausteine(r.items || [])).catch(() => {});
    loadRecipients().then(r => setRecipients(r.items || [])).catch(() => {});
  }, []);

  // Platzhalter-Baum der aktuellen Vorlage laden (Objekt-Felder + Variablen + Referenzen).
  useEffect(() => {
    loadPlaceholderTree(template.id).then(r => setPlaceholders(r.groups || [])).catch(() => {});
  }, [template.id]);

  // Platzhalter-Baum zu flachen Pfaden (für den Pfad-Picker im Baustein-Mapping).
  const placeholderPaths = useMemo(() => {
    const out = [];
    const walk = (nodes) => {
      for (const n of nodes || []) {
        if (n.token) {
          const path = String(n.token).replace(/^\{\{\s*/, "").replace(/\s*\}\}$/, "").trim();
          if (path) out.push({ path, type: n.type || "", label: n.label || path });
        }
        if (n.children) walk(n.children);
      }
    };
    (placeholders || []).forEach((g) => walk(g.tree));
    return out;
  }, [placeholders]);

  // Baustein-Chip im Editor geklickt -> Detail-Popover (Inputs/Outputs) aufklappen.
  useEffect(() => {
    const onPop = (e) => {
      const name = e.detail && e.detail.name;
      if (!name) return;
      const bs = (bausteine || []).find((b) => b.name === name) ||
        { name, title: name, inputs: [], outputs: [], standardpfade: [] };
      setPopoverBaustein({ baustein: bs, rect: e.detail.rect });
    };
    window.addEventListener("hv-baustein-popover", onPop);
    return () => window.removeEventListener("hv-baustein-popover", onPop);
  }, [bausteine]);

  const searchRecipients = useCallback((q) => {
    loadRecipients(template.haupt_verteil_objekt, q)
      .then(r => setRecipients(r.items || [])).catch(() => {});
  }, [template.haupt_verteil_objekt]);

  // PDF-Vorschau (gespeicherter Stand). Mit Empfänger → echte Daten, sonst Beispiel.
  const refreshPreview = useCallback(async () => {
    if (!embedded || !template.id) return;
    setPreviewLoading(true);
    setPreviewError("");
    try {
      const res = await renderPreview({
        templateName: template.id,
        hauptVerteilObjekt: template.haupt_verteil_objekt,
        recipientId: recipient && recipient.id,
      });
      setPreviewPdf(res.pdf_base64 || "");
      setPreviewMode(res.mode || "");
    } catch (e) {
      setPreviewError((e && e.message) || String(e));
      setPreviewPdf("");
    } finally {
      setPreviewLoading(false);
    }
  }, [template.id, template.haupt_verteil_objekt, recipient]);

  // Automatisch rendern, wenn der Vorschau-Tab aktiv ist und sich Vorlage oder
  // Empfänger ändert (nur eingebettet).
  useEffect(() => {
    if (embedded && tab === "preview" && template.id) refreshPreview();
  }, [tab, template.id, recipient, refreshPreview]);

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

        <button className="btn" onClick={save} disabled={!dirty || !template.canWrite || saving} title={!template.canWrite ? "Keine Schreibberechtigung" : ""}>
          <Icon name="save" size={14}/> {saving ? "Speichert …" : "Speichern"}
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
        <Navigator tree={tree} currentId={template.id} onSelect={onTemplateSelect} collapsed={navCollapsed} onToggleCollapse={() => setNavCollapsed(c => !c)}/>
        <Editor
          template={template}
          recipient={recipient}
          loading={loadingTemplate}
          canWrite={!!template.canWrite}
          contentRef={contentRef}
          onDirty={() => setDirty(true)}
          onInsertItem={insertItem}
          onPickRecipient={() => setRecipientPickerOpen(true)}
          onMaximizePreview={() => setPdfMaximized(true)}
          onImageUpload={embedded ? (file) => uploadImage(file, template.id) : null}
          onSafety={setEditorSafety}
        />
        <Sidebar
          tab={tab}
          onTab={setTab}
          template={template}
          recipient={recipient}
          recipients={recipients}
          placeholders={placeholders}
          bausteine={bausteine}
          onChangeRecipient={changeRecipient}
          onSearchRecipients={searchRecipients}
          previewPdf={previewPdf}
          previewLoading={previewLoading}
          previewError={previewError}
          previewMode={previewMode}
          onRefreshPreview={refreshPreview}
          onInsertPlaceholder={insertPlaceholder}
          onInsertBaustein={insertBaustein}
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
              <div
                className={`recipient-row ${!recipient.id ? "active" : ""}`}
                onClick={() => { changeRecipient(null); setRecipientPickerOpen(false); }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>Beispielwerte</div>
                  <div style={{ fontSize: 11, color: "var(--text-faint)" }}>Vorschau mit Musterdaten (kein echter Empfänger)</div>
                </div>
                {!recipient.id && <Icon name="check" size={14}/>}
              </div>
              {recipients.map(r => (
                <div
                  key={r.id}
                  className={`recipient-row ${r.id === recipient.id ? "active" : ""}`}
                  onClick={() => { changeRecipient(r); setRecipientPickerOpen(false); }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 500, fontSize: 13 }}>{r.label}</div>
                    <div style={{ fontSize: 11, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{r.id}</div>
                  </div>
                  {r.id === recipient.id && <Icon name="check" size={14}/>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {popoverBaustein && (
        <BausteinPopover
          baustein={popoverBaustein.baustein}
          hauptVerteilObjekt={template.haupt_verteil_objekt}
          overrides={bausteinPaths[popoverBaustein.baustein.name] || {}}
          rect={popoverBaustein.rect}
          onClose={() => setPopoverBaustein(null)}
          onEditMapping={() => {
            setMappingBaustein(popoverBaustein.baustein);
            setPopoverBaustein(null);
          }}
        />
      )}

      {mappingBaustein && (
        <PfadMappingModal
          baustein={mappingBaustein}
          hauptVerteilObjekt={template.haupt_verteil_objekt}
          existingOverrides={bausteinPaths[mappingBaustein.name] || {}}
          placeholderPaths={placeholderPaths}
          onClose={() => setMappingBaustein(null)}
          onSave={(name, clean) => {
            setBausteinPaths((prev) => {
              const next = { ...prev };
              if (clean && Object.keys(clean).length) next[name] = clean;
              else delete next[name];
              return next;
            });
            setDirty(true);
          }}
        />
      )}

      {pdfMaximized && (
        <PdfMaximized
          template={template}
          recipient={recipient}
          recipients={recipients}
          pdfBase64={previewPdf}
          loading={previewLoading}
          onChangeRecipient={changeRecipient}
          onRefresh={refreshPreview}
          onClose={() => setPdfMaximized(false)}
        />
      )}
    </div>
  );
};

