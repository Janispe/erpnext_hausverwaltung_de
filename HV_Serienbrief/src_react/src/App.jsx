import React, { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Icon } from "./components/Icon.jsx";
import { Navigator } from "./components/Navigator.jsx";
import { Editor } from "./components/Editor.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { PdfMaximized } from "./components/PdfMaximized.jsx";
import { PfadMappingModal } from "./components/PfadMappingModal.jsx";
import { BausteinPopover } from "./components/BausteinPopover.jsx";
import { JinjaTokenPopover } from "./components/JinjaTokenPopover.jsx";
import { CURRENT_TEMPLATE, TEMPLATE_TREE } from "./data.js";
import {
  loadTree, loadTemplate, saveTemplate, copyTemplate, deleteTemplate, openDurchlauf,
  openClassicForm, openBrowser,
  loadPlaceholderTree, loadBausteine, loadRecipients, renderPreview,
  renderBausteinPreviews,
  loadEditorPrintFormatCss,
  loadEditorFooterHtml,
  uploadImage, embedded,
} from "./api.js";
import { validateJinjaBalance } from "./tiptap/validateJinja.js";
import { loadPref, savePref } from "./persist.js";

// Sentinel-Empfänger „Beispielwerte" (kein echter Datensatz → Split-Preview).
const BEISPIEL = { id: null, label: "Beispielwerte" };

// Leerer Start-Zustand für die eingebettete Variante: KEINE id, damit beim Mount keine
// Backend-Calls (Vorschau etc.) für die Mock-Vorlage „t-001" feuern. Die echte erste
// Vorlage wird gleich darauf via loadTree -> onTemplateSelect geladen.
const EMPTY_TEMPLATE = {
  id: null, title: "", kategorie: "", haupt_verteil_objekt: "",
  content_type: "", htmlContent: "", bausteinPaths: {}, variables: [], canWrite: false,
};

export const App = () => {
  // Standalone (npm run dev) startet mit der Demo-Vorlage; eingebettet leer.
  const [template, setTemplate] = useState(() => (embedded ? EMPTY_TEMPLATE : CURRENT_TEMPLATE));
  const [recipient, setRecipient] = useState(BEISPIEL);
  const [tab, setTab] = useState(() => loadPref("tab", "preview"));
  const [dirty, setDirty] = useState(false);
  const [title, setTitle] = useState(template.title);
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [pdfMaximized, setPdfMaximized] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(() => loadPref("navCollapsed", false));
  const [sidebarWidth, setSidebarWidth] = useState(() => loadPref("sidebarWidth", 420));
  const [resizing, setResizing] = useState(false);
  const [tree, setTree] = useState(() => TEMPLATE_TREE);
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copying, setCopying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [placeholders, setPlaceholders] = useState([]);
  const [bausteine, setBausteine] = useState([]);
  const [recipients, setRecipients] = useState([]);
  const [previewPdf, setPreviewPdf] = useState("");
  const [previewMode, setPreviewMode] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [bausteinLayoutMode, setBausteinLayoutMode] = useState(() => loadPref("bausteinLayoutMode", false));
  const [bausteinPreviewHtml, setBausteinPreviewHtml] = useState({});
  const [editorPrintCss, setEditorPrintCss] = useState("");
  // Gerendertes Page-Footer-HTML (mit Mock-Bankverbindung + Pfad-Zeile) für die
  // Per-Seite-Anzeige im Layoutmodus. Leer wenn der Modus aus ist.
  const [editorFooterHtml, setEditorFooterHtml] = useState("");
  // Token-Erhalt-Check beim Laden: null = sicher, sonst { lost, added } -> Speichern blockiert.
  const [editorSafety, setEditorSafety] = useState(null);
  // Pro-Baustein Input-Pfad-Overrides { "<Baustein>": { "<Variable>": "<Pfad>" } }
  const [bausteinPaths, setBausteinPaths] = useState({});
  // Pro-Baustein Werte für Text-/Bool-Variablen { "<Baustein>": { "<Variable>": <Wert> } }
  const [bausteinValues, setBausteinValues] = useState({});
  const [mappingBaustein, setMappingBaustein] = useState(null);
  const [popoverBaustein, setPopoverBaustein] = useState(null); // { baustein, rect }
  // Jinja-Token-Editor-Popover (loest window.prompt ab). { token, rect, save, kind }
  const [jinjaPopover, setJinjaPopover] = useState(null);
  // Vorlagen-Variablen (Definition + Wert/Pfad), im Editor bearbeitbar.
  const [variables, setVariables] = useState([]);
  // Transiente Vorschau-Werte für Eingabe-Variablen { key: wert } — NICHT gespeichert,
  // nur für die Live-Vorschau (siehe PreviewPane „Vorschau-Werte").
  const [previewVars, setPreviewVars] = useState({});
  const contentRef = useRef(null); // Zugriff auf den editierbaren HTML-Inhalt (getHtml)

  // UI-Präferenzen merken (Sidebar-Breite/Trennlinie, Vorlagen auf/zu, aktiver Tab).
  useEffect(() => savePref("tab", tab), [tab]);
  useEffect(() => savePref("navCollapsed", navCollapsed), [navCollapsed]);
  useEffect(() => savePref("sidebarWidth", sidebarWidth), [sidebarWidth]);
  useEffect(() => savePref("bausteinLayoutMode", bausteinLayoutMode), [bausteinLayoutMode]);

  useEffect(() => {
    if (!embedded) return;
    let alive = true;
    loadEditorPrintFormatCss()
      .then((res) => {
        if (alive) setEditorPrintCss(res.css || "");
      })
      .catch(() => {
        if (alive) setEditorPrintCss("");
      });
    return () => { alive = false; };
  }, []);

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
  // Guard: keine Mutation bei fehlender Schreibberechtigung, unsicherer (read-only) Vorlage
  // oder waehrend ein Template-Wechsel laeuft (Token wuerde sonst im alten Editor-Stand landen).
  const insertItem = useCallback((item) => {
    if (!template.canWrite || editorSafety || loadingTemplate) return;
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
  }, [template.canWrite, editorSafety, loadingTemplate]);

  const insertPlaceholder = useCallback((token) => insertItem({ kind: "chip", token }), [insertItem]);
  const insertBaustein = useCallback((name) => insertItem({ kind: "baustein", name }), [insertItem]);

  // Bearbeitbar nur mit Schreibrecht, solange die Vorlage verlustfrei round-trippt
  // und kein Template-Wechsel laeuft (sonst tippt der User im alten Editor, der gleich
  // durch die neue Vorlage ersetzt wird).
  const editable = !!template.canWrite && !editorSafety && !loadingTemplate;

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
        setBausteinValues(t.bausteinValues || {});
        setVariables(t.variables || []);
        setPreviewVars({});
        setDirty(false);
        // Zuletzt geöffnete Vorlage merken, damit sie beim Neuladen wieder erscheint.
        try { savePref("lastTemplateId", t.id || id); } catch (_) {}
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
          const all = groups.flatMap(g => g.templates);
          // Deep-Link aus dem Vorlagen-Browser: ?template=<name> bevorzugen,
          // sonst die erste Vorlage öffnen.
          let target = null;
          try {
            const wanted = new URLSearchParams(window.location.search).get("template");
            if (wanted) target = all.find(t => t.id === wanted) || null;
          } catch (_) {}
          // Sonst zuletzt geöffnete Vorlage aus localStorage; wenn die nicht mehr
          // existiert (gelöscht/umbenannt), fällt es auf die erste der Liste zurück.
          if (!target) {
            const last = loadPref("lastTemplateId", null);
            if (last) target = all.find(t => t.id === last) || null;
          }
          const pick = target || all[0];
          if (pick) onTemplateSelect(pick.id);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [onTemplateSelect]);

  // Gibt true bei Erfolg zurück (für Aufrufer wie Kopieren/„In Serienbrief laden",
  // die vor ihrer Aktion erst speichern wollen).
  const save = async () => {
    if (!template.canWrite || !dirty || saving) return false;
    // Harte Sperre: Vorlage round-trippt nicht verlustfrei (Token-Erhalt-Check beim Laden).
    if (editorSafety) {
      alert(
        "Speichern blockiert: Diese Vorlage enthält Strukturen, die der Editor nicht verlustfrei " +
        "abbilden kann (z. B. ein nicht unterstützter Schleifen-/Tabellen-Aufbau).\n\n" +
        "Verlorene Tokens: " + Object.keys(editorSafety.lost || {}).join(", ") +
        "\n\nBitte diese Vorlage vorerst im klassischen Formular bearbeiten."
      );
      return false;
    }
    const html = contentRef.current ? contentRef.current.getHtml() : (template.htmlContent || "");
    // Jinja-Balance-Warnung (nicht blockierend).
    const bal = validateJinjaBalance(html);
    if (!bal.ok) {
      const proceed = confirm(
        "Mögliche Jinja-Probleme:\n\n" + bal.errors.join("\n") + "\n\nTrotzdem speichern?"
      );
      if (!proceed) return false;
    }
    setSaving(true);
    try {
      const res = await saveTemplate(template.id, html, bausteinPaths, bausteinValues, variables, title);
      setDirty(false);
      // autoname = format:{title}: bei Titeländerung benennt das Backend um -> neue id.
      const renamed = res.id && res.id !== template.id;
      setTemplate(prev => ({
        ...prev,
        id: res.id || prev.id,
        title: res.title || prev.title,
        modified: res.modified || prev.modified,
      }));
      if (res.title) setTitle(res.title);
      // lastTemplateId mitziehen, sonst landet ein Reload nach Umbenennung nicht in
      // dieser Vorlage, sondern (weil die alte ID nicht mehr existiert) auf der ersten.
      try { savePref("lastTemplateId", res.id || template.id); } catch (_) {}
      if (renamed) {
        try { const { groups } = await loadTree(); if (groups && groups.length) setTree(groups); } catch (_) {}
      }
      // Return-Shape enthält die (ggf. umbenannte) neue ID + Titel, damit Caller
      // wie handleOpenClassic/handleLoadDurchlauf nach `await save` die richtige ID
      // benutzen koennen statt das stale `template.id` aus ihrer Closure.
      return { ok: true, id: res.id || template.id, title: res.title || title };
    } catch (e) {
      alert("Speichern fehlgeschlagen: " + ((e && e.message) || e));
      return false;
    } finally {
      setSaving(false);
    }
  };

  // Strg+S / Cmd+S -> Speichern (statt Browser-Speichern-Dialog). saveRef hält die
  // aktuelle save-Closure, damit der Listener nur einmal registriert wird.
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        e.stopPropagation();
        saveRef.current && saveRef.current();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  // „Kopieren" -> Vorlage duplizieren und die Kopie öffnen. Die Kopie basiert auf
  // dem gespeicherten Stand, daher offene Änderungen vorher speichern.
  const handleCopy = useCallback(async () => {
    if (!template.id || copying || saving) return;
    if (dirty && template.canWrite) {
      const ok = await saveRef.current();
      if (!ok) return;
    }
    setCopying(true);
    try {
      const res = await copyTemplate(template.id, `${title} (Kopie)`);
      // Navigator-Baum aktualisieren, damit die Kopie erscheint, dann öffnen.
      try { const { groups } = await loadTree(); if (groups && groups.length) setTree(groups); } catch (_) {}
      if (res && res.name) onTemplateSelect(res.name);
    } catch (e) {
      alert("Kopieren fehlgeschlagen: " + ((e && e.message) || e));
    } finally {
      setCopying(false);
    }
  }, [template.id, template.canWrite, title, dirty, copying, saving, onTemplateSelect]);

  // „Löschen" -> Vorlage nach Bestätigung entfernen, Baum neu laden und die erste
  // verbleibende Vorlage öffnen (sonst leeren Zustand). Serverseitig schlägt das
  // Löschen fehl, wenn die Vorlage noch in einem Durchlauf referenziert wird.
  const handleDelete = useCallback(async () => {
    if (!template.id || deleting || copying || saving) return;
    if (!window.confirm(`Vorlage „${title}" wirklich löschen? Das kann nicht rückgängig gemacht werden.`)) return;
    setDeleting(true);
    try {
      await deleteTemplate(template.id);
      let nextId = null;
      try {
        const { groups } = await loadTree();
        if (groups && groups.length) {
          setTree(groups);
          const first = groups.flatMap(g => g.templates)[0];
          nextId = first ? first.id : null;
        } else {
          setTree([]);
        }
      } catch (_) {}
      if (nextId) {
        onTemplateSelect(nextId);
      } else {
        setTemplate(EMPTY_TEMPLATE);
        setTitle("");
        setDirty(false);
      }
    } catch (e) {
      alert("Löschen fehlgeschlagen: " + ((e && e.message) || e));
    } finally {
      setDeleting(false);
    }
  }, [template.id, title, deleting, copying, saving, onTemplateSelect]);

  // „Klassisch" -> Escape-Hatch zur Standard-Frappe-Form. Nötig für den
  // geführten Mapping-Wizard und Spezialfälle (Mehrfach-Baustein-Mapping über
  // das Alt-Datenmodell textbausteine[].pfad_zuordnung). Vor dem Verlassen
  // anbieten zu speichern, damit ungespeicherte Edits nicht verloren gehen.
  // Wichtig: Bei Titeländerung benennt das Backend um (autoname = format:{title}),
  // die neue ID kommt aus dem save-Return; das stale `template.id` aus der
  // useCallback-Closure ist dann veraltet und würde auf einen 404 führen.
  const handleOpenClassic = useCallback(async () => {
    if (!template.id) return;
    let vorlageId = template.id;
    if (dirty && template.canWrite) {
      const res = await saveRef.current();
      if (!res) return;
      vorlageId = res.id || vorlageId;
    }
    try {
      await openClassicForm({ vorlage: vorlageId });
    } catch (e) {
      alert("Klassische Form öffnen fehlgeschlagen: " + ((e && e.message) || e));
    }
  }, [template.id, template.canWrite, dirty]);

  // „In Serienbrief laden" -> neues Durchlauf-Formular im Desk öffnen, Vorlage
  // vorausgewählt. Der Durchlauf rendert aus dem gespeicherten Stand -> erst speichern.
  // Bei Titeländerung benennt das Backend um — die neue ID + Titel kommen aus dem
  // save-Return (sonst landet das Durchlauf-Formular auf einer alten, nicht mehr
  // existierenden Vorlage).
  const handleLoadDurchlauf = useCallback(async () => {
    if (!template.id || saving) return;
    let vorlageId = template.id;
    let vorlageTitle = title;
    if (dirty && template.canWrite) {
      const res = await saveRef.current();
      if (!res) return;
      vorlageId = res.id || vorlageId;
      vorlageTitle = res.title || vorlageTitle;
    }
    try {
      await openDurchlauf({
        vorlage: vorlageId,
        title: vorlageTitle,
        iterationDoctype: template.haupt_verteil_objekt,
      });
      // Das Desk navigiert jetzt zum neuen Durchlauf — das iframe wird ersetzt.
    } catch (e) {
      alert("In Serienbrief laden fehlgeschlagen: " + ((e && e.message) || e));
    }
  }, [template.id, template.canWrite, template.haupt_verteil_objekt, title, dirty, saving]);

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
          // Sowohl {{ x }} (Variablen) als auch {{$ x $}} (Objekt-Platzhalter) ->
          // reiner Pfad „x". Das $ MUSS mit weg, sonst landet „$ objekt.wohnung $"
          // im Pfad-Picker und _resolve_value_path() kann es nicht auflösen.
          const path = String(n.token)
            .replace(/^\{\{\s*\$?\s*/, "")
            .replace(/\s*\$?\s*\}\}$/, "")
            .trim();
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

  // Jinja-Token (z.B. {% if ... %}, {% endif %}) im Editor geklickt → Inline-
  // Popover statt window.prompt. NodeView (extensions.js) dispatcht den Save-
  // Callback mit, damit die State-Mutation im NodeView-Kontext bleibt.
  useEffect(() => {
    const onPop = (e) => {
      console.debug("[hv-jinja-popover] App received event", e.detail);
      if (!e.detail) return;
      setJinjaPopover({
        token: e.detail.token || "",
        rect: e.detail.rect || null,
        kind: e.detail.kind || "",
        save: typeof e.detail.save === "function" ? e.detail.save : () => {},
      });
    };
    window.addEventListener("hv-jinja-token-popover", onPop);
    console.debug("[hv-jinja-popover] App listener mounted");
    return () => {
      window.removeEventListener("hv-jinja-token-popover", onPop);
      console.debug("[hv-jinja-popover] App listener removed");
    };
  }, []);

  const searchRecipients = useCallback((q) => {
    loadRecipients(template.haupt_verteil_objekt, q)
      .then(r => setRecipients(r.items || [])).catch(() => {});
  }, [template.haupt_verteil_objekt]);

  // PDF-Live-Vorschau: rendert den aktuellen (ungespeicherten) Editor-Stand.
  // Queue-Guard: nie zwei Chrome-Renders parallel (OOM-Schutz) — läuft schon einer,
  // wird er gemerkt und nach Abschluss einmal nachgezogen. Signatur-Check: kein Render,
  // wenn sich nichts geändert hat.
  const previewBusy = useRef(false);
  const previewPending = useRef(false);
  const previewSig = useRef(null);
  const previewTimer = useRef(null);
  const bausteinPreviewBusy = useRef(false);
  const bausteinPreviewPending = useRef(false);
  const bausteinPreviewSig = useRef(null);
  const bausteinPreviewTimer = useRef(null);

  const refreshPreview = useCallback(async ({ force = false } = {}) => {
    if (!embedded || !template.id) return;
    const html = contentRef.current ? contentRef.current.getHtml() : (template.htmlContent || "");
    const sig = JSON.stringify([html, recipient && recipient.id, variables, bausteinPaths, bausteinValues, previewVars]);
    if (!force && sig === previewSig.current) return;        // nichts geändert
    if (previewBusy.current) { previewPending.current = true; return; } // läuft -> queue
    previewBusy.current = true;
    previewPending.current = false;
    previewSig.current = sig;
    setPreviewLoading(true);
    setPreviewError("");
    try {
      const res = await renderPreview({
        templateName: template.id,
        hauptVerteilObjekt: template.haupt_verteil_objekt,
        recipientId: recipient && recipient.id,
        html,
        variables,
        bausteinPaths,
        bausteinValues,
        previewValues: previewVars,
      });
      setPreviewPdf(res.pdf_base64 || "");
      setPreviewMode(res.mode || "");
    } catch (e) {
      setPreviewError((e && e.message) || String(e));
      setPreviewPdf("");
      previewSig.current = null; // bei Fehler erneuten Versuch erlauben
    } finally {
      previewBusy.current = false;
      setPreviewLoading(false);
      if (previewPending.current) { previewPending.current = false; refreshPreview({ force: true }); }
    }
  }, [template.id, template.haupt_verteil_objekt, recipient, variables, bausteinPaths, bausteinValues, previewVars]);

  const refreshBausteinPreview = useCallback(async ({ force = false } = {}) => {
    if (!embedded || !template.id || !bausteinLayoutMode) return;
    const html = contentRef.current ? contentRef.current.getHtml() : (template.htmlContent || "");
    const sig = JSON.stringify([html, recipient && recipient.id, variables, bausteinPaths, bausteinValues, previewVars]);
    if (!force && sig === bausteinPreviewSig.current) return;
    if (bausteinPreviewBusy.current) {
      bausteinPreviewPending.current = true;
      return;
    }
    bausteinPreviewBusy.current = true;
    bausteinPreviewPending.current = false;
    bausteinPreviewSig.current = sig;
    try {
      const res = await renderBausteinPreviews({
        templateName: template.id,
        hauptVerteilObjekt: template.haupt_verteil_objekt,
        recipientId: recipient && recipient.id,
        html,
        variables,
        bausteinPaths,
        bausteinValues,
        previewValues: previewVars,
      });
      setBausteinPreviewHtml(res.items || {});
    } catch (e) {
      setBausteinPreviewHtml({});
      bausteinPreviewSig.current = null;
    } finally {
      bausteinPreviewBusy.current = false;
      if (bausteinPreviewPending.current) {
        bausteinPreviewPending.current = false;
        refreshBausteinPreview({ force: true });
      }
    }
  }, [template.id, template.htmlContent, template.haupt_verteil_objekt, recipient, variables, bausteinPaths, bausteinValues, previewVars, bausteinLayoutMode]);

  const scheduleBausteinPreview = useCallback(() => {
    if (!embedded || !bausteinLayoutMode) return;
    if (bausteinPreviewTimer.current) clearTimeout(bausteinPreviewTimer.current);
    bausteinPreviewTimer.current = setTimeout(() => refreshBausteinPreview(), 900);
  }, [bausteinLayoutMode, refreshBausteinPreview]);

  // Debounce: nach der letzten Eingabe ~4s warten, dann (live) rendern. Nur wenn der
  // Vorschau-Tab sichtbar ist.
  const schedulePreview = useCallback(() => {
    if (!embedded || tab !== "preview") return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => refreshPreview(), 4000);
  }, [tab, refreshPreview]);

  useEffect(() => {
    if (bausteinLayoutMode) refreshBausteinPreview({ force: true });
    else setBausteinPreviewHtml({});
  }, [bausteinLayoutMode, template.id, refreshBausteinPreview]);

  // Footer-HTML nachladen, sobald Layoutmodus an ist oder die Vorlage wechselt.
  // Footer-Inhalt hängt nur an der Vorlage (Mock-Bank + Pfad-Zeile aus Kategorie),
  // nicht am Empfänger oder am Edit-Stand — daher kein Debounce, ein-Fetch reicht.
  useEffect(() => {
    if (!embedded || !bausteinLayoutMode || !template.id) {
      setEditorFooterHtml("");
      return;
    }
    let alive = true;
    loadEditorFooterHtml(template.id)
      .then((res) => { if (alive) setEditorFooterHtml((res && res.html) || ""); })
      .catch(() => { if (alive) setEditorFooterHtml(""); });
    return () => { alive = false; };
  }, [bausteinLayoutMode, template.id]);

  // Sofort rendern bei Tab-/Vorlagen-/Empfängerwechsel (Signatur-Check dedupt).
  useEffect(() => {
    if (embedded && tab === "preview" && template.id) refreshPreview();
  }, [tab, template.id, recipient, refreshPreview]);

  // Variablen-/Baustein-Pfad-/Vorschau-Wert-Änderungen (nicht über den Editor)
  // -> debounced nachrendern. Cleanup-Return killt den 4s-Timer beim
  // Vorlagen-/Empfänger-Wechsel oder Unmount, damit ein altes setTimeout
  // nicht mehr auf die inzwischen ausgetauschte Vorlage refreshPreview() ruft.
  useEffect(() => {
    schedulePreview();
    return () => {
      if (previewTimer.current) {
        clearTimeout(previewTimer.current);
        previewTimer.current = null;
      }
    };
  }, [variables, bausteinPaths, bausteinValues, previewVars, schedulePreview]);

  useEffect(() => {
    scheduleBausteinPreview();
    return () => {
      if (bausteinPreviewTimer.current) {
        clearTimeout(bausteinPreviewTimer.current);
        bausteinPreviewTimer.current = null;
      }
    };
  }, [variables, bausteinPaths, bausteinValues, previewVars, scheduleBausteinPreview]);

  return (
    <div className="app">
      {editorPrintCss && <style id="hv-editor-print-format-css">{editorPrintCss}</style>}
      <header className="topbar">
        <button
          className="btn ghost icon"
          title="Zurück zur Liste"
          onClick={async () => {
            // Ungespeicherte Edits anbieten zu speichern, damit der User
            // sie beim Wechsel zum Browser nicht verliert.
            if (dirty && template.canWrite) {
              const proceed = confirm("Ungespeicherte Änderungen. Vor dem Verlassen speichern?");
              if (proceed) {
                const res = await saveRef.current();
                if (!res) return;
              }
            }
            try { await openBrowser(); } catch (e) { alert("Zurück zur Liste fehlgeschlagen: " + ((e && e.message) || e)); }
          }}
        >
          <Icon name="back" size={16}/>
        </button>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
          <span className="crumb">Serienbrief · {template.kategorie}</span>
        </div>
        <input
          className="title-input"
          value={title}
          title={title}
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

        <button className="btn" onClick={save} disabled={!dirty || !template.canWrite || saving || deleting} title={!template.canWrite ? "Keine Schreibberechtigung" : ""}>
          <Icon name="save" size={14}/> {saving ? "Speichert …" : "Speichern"}
        </button>
        <button className="btn ghost" onClick={handleCopy} disabled={!template.id || copying || saving || deleting} title="Diese Vorlage duplizieren">
          <Icon name="copy" size={14}/> {copying ? "Kopiert …" : "Kopieren"}
        </button>
        <button className="btn ghost tb-danger" onClick={handleDelete} disabled={!template.id || !template.canWrite || copying || saving || deleting} title={!template.canWrite ? "Keine Berechtigung" : "Diese Vorlage löschen"}>
          <Icon name="trash" size={14}/> {deleting ? "Löscht …" : "Löschen"}
        </button>
        <button className="btn ghost" onClick={handleOpenClassic} disabled={!template.id || copying || saving || deleting} title="In klassischer Form öffnen (Mapping-Wizard, Spezialfälle)">
          <Icon name="file" size={14}/> Klassisch
        </button>
        <button className="btn primary" onClick={handleLoadDurchlauf} disabled={!template.id || saving || deleting} title="Neuen Serienbrief-Durchlauf mit dieser Vorlage starten">
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
          onDirty={() => { setDirty(true); schedulePreview(); scheduleBausteinPreview(); }}
          onInsertItem={insertItem}
          onPickRecipient={() => setRecipientPickerOpen(true)}
          onMaximizePreview={() => setPdfMaximized(true)}
          onImageUpload={embedded ? (file) => uploadImage(file, template.id) : null}
          onSafety={setEditorSafety}
          bausteinLayoutMode={bausteinLayoutMode}
          onToggleBausteinLayout={() => setBausteinLayoutMode((v) => !v)}
          bausteinPreviews={bausteinPreviewHtml}
          footerHtml={editorFooterHtml}
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
          variablesForPreview={variables}
          previewVars={previewVars}
          onPreviewVarChange={(key, value) =>
            setPreviewVars((prev) => {
              const next = { ...prev };
              if (value === "" || value == null) delete next[key];
              else next[key] = value;
              return next;
            })
          }
          onInsertPlaceholder={insertPlaceholder}
          onInsertBaustein={insertBaustein}
          onMaximizePreview={() => setPdfMaximized(true)}
          onResizeStart={onResizeStart}
          variables={variables}
          placeholderPaths={placeholderPaths}
          editable={editable}
          onVariablesChange={(v) => { if (!editable) return; setVariables(v); setDirty(true); scheduleBausteinPreview(); }}
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
          values={bausteinValues[popoverBaustein.baustein.name] || {}}
          rect={popoverBaustein.rect}
          onClose={() => setPopoverBaustein(null)}
          onEditMapping={() => {
            setMappingBaustein(popoverBaustein.baustein);
            setPopoverBaustein(null);
          }}
          onValuesChange={(clean) => {
            if (!editable) return;
            const name = popoverBaustein.baustein.name;
            setBausteinValues((prev) => {
              const next = { ...prev };
              if (clean && Object.keys(clean).length) next[name] = clean;
              else delete next[name];
              return next;
            });
            setDirty(true);
          }}
        />
      )}

      {jinjaPopover && (
        <JinjaTokenPopover
          token={jinjaPopover.token}
          rect={jinjaPopover.rect}
          kind={jinjaPopover.kind}
          onSave={(newToken) => jinjaPopover.save(newToken)}
          onClose={() => setJinjaPopover(null)}
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
