import React, { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Icon } from "../components/Icon.jsx";
import { loadPref, savePref } from "../persist.js";
import {
  loadBrowserData,
  setFavorite as apiSetFavorite,
  moveTemplates,
  copyTemplate,
  deleteTemplate,
  createFolder as apiCreateFolder,
  openDurchlauf,
  openEditor as apiOpenEditor,
  loadRecipients,
  renderPreview,
  embedded,
} from "./api.js";

// Serienbrief Browser — main app
// ============== Utilities ==============

const formatDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMin / 60);
  const diffD = Math.floor(diffH / 24);
  if (diffMin < 1) return "gerade eben";
  if (diffMin < 60) return `vor ${diffMin} Min.`;
  if (diffH < 24) return `vor ${diffH} Std.`;
  if (diffD < 7) return `vor ${diffD} ${diffD === 1 ? "Tag" : "Tagen"}`;
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "short", year: "numeric" });
};

const formatDateAbs = (iso) => {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

// ============== Tree Sidebar ==============

const SmartFolderItem = ({ icon, label, count, active, onClick, color }) => (
  <div className={`smart-folder ${active ? "active" : ""}`} onClick={onClick}>
    <span className="smart-folder-icon" style={color ? { color } : undefined}><Icon name={icon} size={14}/></span>
    <span className="smart-folder-label">{label}</span>
    {count != null && <span className="smart-folder-count">{count}</span>}
  </div>
);

const FolderTree = ({ folders, selected, onSelect, openKeys, onToggle, counts, dragOver, onDragOverFolder, onDropFolder }) => {
  const children = (parentId) => folders.filter(f => f.parent === parentId);

  const renderFolder = (f, depth) => {
    const kids = children(f.id);
    const isOpen = openKeys.has(f.id);
    const isActive = selected === f.id;
    const isDragOver = dragOver === f.id;
    const tmpCount = counts[f.id] != null ? counts[f.id] : f.count;
    return (
      <div key={f.id}>
        <div
          className={`folder-row ${isActive ? "active" : ""} ${isDragOver ? "drag-over" : ""}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => onSelect(f.id)}
          onDragOver={e => { e.preventDefault(); onDragOverFolder(f.id); }}
          onDragLeave={() => onDragOverFolder(null)}
          onDrop={e => { e.preventDefault(); onDropFolder(f.id, e); onDragOverFolder(null); }}
        >
          {kids.length > 0 ? (
            <span className="folder-chev" onClick={e => { e.stopPropagation(); onToggle(f.id); }}>
              <Icon name="chevron-right" size={11} style={{ transform: isOpen ? "rotate(90deg)" : "none" }}/>
            </span>
          ) : <span className="folder-chev spacer"/>}
          <span className="folder-icon" style={f.color ? { color: f.color } : undefined}>
            <Icon name={isOpen && kids.length > 0 ? "folder-open" : "folder"} size={14}/>
          </span>
          <span className="folder-title" title={f.title}>{f.title}</span>
          <span className="folder-count">{tmpCount}</span>
        </div>
        {isOpen && kids.map(c => renderFolder(c, depth + 1))}
      </div>
    );
  };

  return (
    <div className="folder-tree">
      {children(null).map(f => renderFolder(f, 0))}
    </div>
  );
};

const Sidebar = ({
  folders, selectedFolder, smartFolder, onSelectFolder, onSelectSmart,
  openKeys, onToggle, counts, smartCounts,
  dragOver, onDragOverFolder, onDropFolder, onCreateFolder,
}) => {
  return (
    <aside className="bw-sidebar">
      <div className="bw-sidebar-section">
        <div className="bw-sidebar-section-title">Schnellzugriff</div>
        <SmartFolderItem icon="star" label="Favoriten" count={smartCounts.favorites} active={smartFolder === "favorites"} onClick={() => onSelectSmart("favorites")} color="#b4691c"/>
        <SmartFolderItem icon="clock" label="Zuletzt bearbeitet" count={smartCounts.recent} active={smartFolder === "recent"} onClick={() => onSelectSmart("recent")} color="#1859a0"/>
        <SmartFolderItem icon="check" label="Zuletzt verwendet" count={smartCounts.used} active={smartFolder === "used"} onClick={() => onSelectSmart("used")} color="#2e6f5e"/>
        <SmartFolderItem icon="branch" label="Pfade fehlen" count={smartCounts.broken} active={smartFolder === "broken"} onClick={() => onSelectSmart("broken")} color="#b54545"/>
      </div>

      <div className="bw-sidebar-section bw-sidebar-section-tree">
        <div className="bw-sidebar-section-title">
          <span>Ordner</span>
          <button className="bw-sidebar-add" title="Neuer Ordner" onClick={onCreateFolder}><Icon name="plus" size={11}/></button>
        </div>
        <div
          className={`folder-row folder-row-root ${selectedFolder === "" && !smartFolder ? "active" : ""}`}
          onClick={() => onSelectFolder("")}
          onDragOver={e => { e.preventDefault(); onDragOverFolder(""); }}
          onDragLeave={() => onDragOverFolder(null)}
          onDrop={e => { e.preventDefault(); onDropFolder("", e); onDragOverFolder(null); }}
        >
          <span className="folder-chev spacer"/>
          <span className="folder-icon"><Icon name="home" size={14}/></span>
          <span className="folder-title">Alle Vorlagen</span>
          <span className="folder-count">{counts.__all || 0}</span>
        </div>
        <FolderTree
          folders={folders}
          selected={selectedFolder}
          onSelect={onSelectFolder}
          openKeys={openKeys}
          onToggle={onToggle}
          counts={counts}
          dragOver={dragOver}
          onDragOverFolder={onDragOverFolder}
          onDropFolder={onDropFolder}
        />
      </div>
    </aside>
  );
};

// ============== Topbar ==============

const Breadcrumb = ({ folders, folderId, smartFolder, onSelect }) => {
  if (smartFolder) {
    const labels = {
      favorites: { icon: "star", label: "Favoriten", color: "#b4691c" },
      recent: { icon: "clock", label: "Zuletzt bearbeitet", color: "#1859a0" },
      used: { icon: "check", label: "Zuletzt verwendet", color: "#2e6f5e" },
      broken: { icon: "branch", label: "Pfade fehlen", color: "#b54545" },
    };
    const x = labels[smartFolder];
    return (
      <div className="bw-breadcrumb">
        <span className="bw-crumb" onClick={() => onSelect("")}>Vorlagen</span>
        <span className="bw-crumb-sep">/</span>
        <span className="bw-crumb-current" style={{ color: x?.color }}>
          <Icon name={x?.icon || "tag"} size={11}/> {x?.label}
        </span>
      </div>
    );
  }
  // Build chain to root
  const chain = [];
  let cur = folders.find(f => f.id === folderId);
  while (cur) {
    chain.unshift(cur);
    cur = cur.parent ? folders.find(f => f.id === cur.parent) : null;
  }
  return (
    <div className="bw-breadcrumb">
      <span className="bw-crumb" onClick={() => onSelect("")}>Vorlagen</span>
      {chain.map((seg, i) => (
        <React.Fragment key={seg.id}>
          <span className="bw-crumb-sep">/</span>
          {i === chain.length - 1
            ? <span className="bw-crumb-current">{seg.title}</span>
            : <span className="bw-crumb" onClick={() => onSelect(seg.id)}>{seg.title}</span>}
        </React.Fragment>
      ))}
    </div>
  );
};

const Topbar = ({
  folders, folderId, smartFolder, onSelectFolder,
  query, onQuery, fulltextMode, onToggleFulltextMode,
  sort, onSort, view, onView,
  showPreview, onTogglePreview,
}) => {
  return (
    <header className="bw-topbar">
      <Breadcrumb folders={folders} folderId={folderId} smartFolder={smartFolder} onSelect={onSelectFolder}/>
      <div className="bw-topbar-actions">
        <div className="bw-search">
          <span className="bw-search-icon"><Icon name="search" size={13}/></span>
          <input
            className="bw-search-input"
            placeholder={fulltextMode ? "Volltext im Inhalt suchen…" : "Vorlage suchen…"}
            value={query}
            onChange={e => onQuery(e.target.value)}
          />
          <button
            className={`bw-search-mode ${fulltextMode ? "active" : ""}`}
            onClick={onToggleFulltextMode}
            title={fulltextMode ? "Volltext-Suche aktiv — klicken zum Deaktivieren" : "Volltext-Suche aktivieren — durchsucht Inhalt der Vorlagen"}
          >
            {fulltextMode ? "VOLLTEXT" : "Aa"}
          </button>
        </div>
        <div className="bw-sort">
          <select value={sort} onChange={e => onSort(e.target.value)} title="Sortierung">
            <option value="modified_desc">Zuletzt geändert ↓</option>
            <option value="modified_asc">Zuletzt geändert ↑</option>
            <option value="title_asc">Titel A–Z</option>
            <option value="title_desc">Titel Z–A</option>
            <option value="used_desc">Zuletzt verwendet</option>
          </select>
        </div>
        <div className="bw-view-toggle">
          <button className={view === "list" ? "active" : ""} onClick={() => onView("list")} title="Liste"><Icon name="list" size={12}/></button>
          <button className={view === "grid" ? "active" : ""} onClick={() => onView("grid")} title="Raster"><Icon name="grid" size={12}/></button>
        </div>
        <button className={`bw-preview-toggle ${showPreview ? "active" : ""}`} onClick={onTogglePreview} title="Vorschau ein-/ausklappen">
          <Icon name="play" size={12}/>
          <span>Vorschau</span>
        </button>
        <button className="btn primary"><Icon name="plus" size={12}/> Neue Vorlage</button>
      </div>
    </header>
  );
};

// ============== List ==============

const TemplateRow = ({ tpl, folder, selected, selectedIds, onSelect, onToggleSelect, onPreview, onAction, onDragStart, viewMode, query, fulltextMode, ftMatch }) => {
  const highlight = (text) => {
    if (!query || !text) return text;
    return <HighlightedText text={text} query={query}/>;
  };

  const status = [];
  if (tpl.favorite) status.push({ key: "fav", icon: "star", color: "#b4691c", title: "Favorit" });
  if (tpl.missing_paths > 0) status.push({ key: "missing", icon: "branch", color: "#b54545", title: `${tpl.missing_paths} Pfad${tpl.missing_paths > 1 ? "e" : ""} fehlt` });

  if (viewMode === "grid") {
    return (
      <div
        className={`tpl-card ${selected ? "selected" : ""}`}
        draggable
        onDragStart={e => onDragStart(e, tpl.id)}
        onClick={() => onPreview(tpl)}
        onDoubleClick={() => onAction("open", tpl)}
      >
        <div className="tpl-card-head">
          <div className="tpl-card-folder-pill" style={{ background: folder?.color ? `${folder.color}1a` : "var(--bg-subtle)", color: folder?.color || "var(--text-muted)" }}>
            <Icon name="folder" size={10}/> {folder?.title || "—"}
          </div>
          <div className="tpl-card-status">
            {status.map(s => <span key={s.key} className="tpl-status" style={{ color: s.color }} title={s.title}><Icon name={s.icon} size={11}/></span>)}
          </div>
        </div>
        <div className="tpl-card-title">{highlight(tpl.title)}</div>
        <div className="tpl-card-desc">{highlight(tpl.description)}</div>
        <div className="tpl-card-meta">
          <span title={formatDateAbs(tpl.modified)}>{formatDate(tpl.modified)}</span>
          <span className="tpl-card-meta-dot">·</span>
          <span>{tpl.bausteine.length} Bausteine</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`tpl-row ${selected ? "selected" : ""} ${fulltextMode && ftMatch ? "tpl-row-fulltext" : ""}`}
      draggable
      onDragStart={e => onDragStart(e, tpl.id)}
      onClick={() => onPreview(tpl)}
      onDoubleClick={() => onAction("open", tpl)}
    >
      <div className="tpl-cell tpl-cell-check" onClick={e => { e.stopPropagation(); onToggleSelect(tpl.id); }}>
        <input type="checkbox" checked={selectedIds?.has(tpl.id) || false} onChange={() => {}}/>
      </div>
      <div className="tpl-cell tpl-cell-title">
        <span className="tpl-row-status">
          {tpl.favorite && <Icon name="star" size={12} style={{ color: "#b4691c" }}/>}
        </span>
        <div className="tpl-row-titlecol">
          <div className="tpl-row-title">
            {highlight(tpl.title)}
            {fulltextMode && ftMatch && (
              <span className="tpl-ft-count" title={`${ftMatch.matchCount} Treffer im Inhalt`}>
                {ftMatch.matchCount}
              </span>
            )}
          </div>
          {fulltextMode && ftMatch && ftMatch.snippets.length > 0 ? (
            <div className="tpl-row-snippets">
              {ftMatch.snippets.map((s, i) => (
                <div key={i} className="tpl-row-snippet">
                  <span className="tpl-row-snippet-icon"><Icon name="search" size={9}/></span>
                  <HighlightedText text={s.text} query={query}/>
                </div>
              ))}
            </div>
          ) : (
            <div className="tpl-row-desc">{highlight(tpl.description)}</div>
          )}
        </div>
      </div>
      <div className="tpl-cell tpl-cell-folder">
        <span className="tpl-folder-pill" style={{ background: folder?.color ? `${folder.color}1a` : "var(--bg-subtle)", color: folder?.color || "var(--text-muted)" }}>
          {folder?.title || "—"}
        </span>
      </div>
      <div className="tpl-cell tpl-cell-modified" title={`${formatDateAbs(tpl.modified)} · ${tpl.modified_by}`}>
        <div>{formatDate(tpl.modified)}</div>
        <div className="tpl-cell-sub">{tpl.modified_by.split("@")[0]}</div>
      </div>
      <div className="tpl-cell tpl-cell-used" title={tpl.last_used ? formatDateAbs(tpl.last_used) : "Noch nicht verwendet"}>
        {tpl.last_used ? formatDate(tpl.last_used) : <span style={{ color: "var(--text-faint)" }}>—</span>}
      </div>
      <div className="tpl-cell tpl-cell-actions" onClick={e => e.stopPropagation()}>
        <button className="tpl-action primary" onClick={() => onAction("durchlauf", tpl)} title="Serienbrief-Durchlauf starten">
          <Icon name="send" size={11}/> Durchlauf
        </button>
        <button className="tpl-action" onClick={() => onAction("open", tpl)} title="Im Editor öffnen">
          <Icon name="edit" size={11}/>
        </button>
        <button className="tpl-action" onClick={() => onAction("menu", tpl)} title="Weitere Aktionen">
          <Icon name="more" size={11}/>
        </button>
      </div>
    </div>
  );
};

const ListHeader = ({ sort, onSortClick, allSelected, someSelected, onSelectAll, viewMode }) => {
  if (viewMode === "grid") return null;
  const arrow = (key) => {
    if (sort === `${key}_asc`) return " ↑";
    if (sort === `${key}_desc`) return " ↓";
    return "";
  };
  return (
    <div className="tpl-header-row">
      <div className="tpl-cell tpl-cell-check">
        <input
          type="checkbox"
          checked={allSelected}
          ref={el => el && (el.indeterminate = !allSelected && someSelected)}
          onChange={() => onSelectAll(!allSelected)}
        />
      </div>
      <div className="tpl-cell tpl-cell-title tpl-th" onClick={() => onSortClick("title")}>Titel{arrow("title")}</div>
      <div className="tpl-cell tpl-cell-folder tpl-th">Ordner</div>
      <div className="tpl-cell tpl-cell-modified tpl-th" onClick={() => onSortClick("modified")}>Geändert{arrow("modified")}</div>
      <div className="tpl-cell tpl-cell-used tpl-th" onClick={() => onSortClick("used")}>Verwendet{arrow("used")}</div>
      <div className="tpl-cell tpl-cell-actions"></div>
    </div>
  );
};

const BulkBar = ({ count, onClear, onMove, onCopy, onDelete, onDurchlauf }) => {
  if (count === 0) return null;
  return (
    <div className="bw-bulk-bar">
      <div className="bw-bulk-info">
        <span className="bw-bulk-count">{count}</span>
        <span>{count === 1 ? "Vorlage" : "Vorlagen"} ausgewählt</span>
        <button className="bw-bulk-clear" onClick={onClear}><Icon name="x" size={11}/></button>
      </div>
      <div className="bw-bulk-actions">
        <button className="btn sm" onClick={onDurchlauf}><Icon name="send" size={12}/> Durchlauf</button>
        <button className="btn sm" onClick={onMove}><Icon name="folder" size={12}/> Verschieben</button>
        <button className="btn sm" onClick={onCopy}><Icon name="copy" size={12}/> Kopieren</button>
        <button className="btn sm" style={{ color: "var(--danger)" }} onClick={onDelete}><Icon name="x" size={12}/> Löschen</button>
      </div>
    </div>
  );
};

const TemplateList = ({
  templates, folders, selectedIds, onToggleSelect, onSelectAll, allSelected, someSelected,
  previewId, onPreview, onAction, onDragStart, sort, onSortClick, view, query, emptyHint,
  fulltextMode, ftMatches,
}) => {
  return (
    <div className={`tpl-list ${view === "grid" ? "tpl-list-grid" : "tpl-list-rows"}`}>
      <ListHeader sort={sort} onSortClick={onSortClick} allSelected={allSelected} someSelected={someSelected} onSelectAll={onSelectAll} viewMode={view}/>
      {templates.length === 0 ? (
        <div className="tpl-empty">
          <Icon name="search" size={28}/>
          <div>{emptyHint}</div>
        </div>
      ) : view === "grid" ? (
        <div className="tpl-grid">
          {templates.map(t => (
            <TemplateRow
              key={t.id}
              tpl={t}
              folder={folders.find(f => f.id === t.folder)}
              selected={previewId === t.id}
              onSelect={onToggleSelect}
              onToggleSelect={onToggleSelect}
              onPreview={onPreview}
              onAction={onAction}
              onDragStart={onDragStart}
              viewMode="grid"
              query={query}
              fulltextMode={fulltextMode}
              ftMatch={ftMatches[t.id]}
            />
          ))}
        </div>
      ) : (
        templates.map(t => (
          <TemplateRow
            key={t.id}
            tpl={t}
            folder={folders.find(f => f.id === t.folder)}
            selected={selectedIds.has(t.id) || previewId === t.id}
            selectedIds={selectedIds}
            onSelect={onToggleSelect}
            onToggleSelect={onToggleSelect}
            onPreview={onPreview}
            onAction={onAction}
            onDragStart={onDragStart}
            viewMode="list"
            query={query}
            fulltextMode={fulltextMode}
            ftMatch={ftMatches[t.id]}
          />
        ))
      )}
    </div>
  );
};

// ============== Preview ==============

const RECIPIENTS = [
  { id: null, label: "Beispielwerte", sub: "Musterdaten (Split-Preview)" },
  { id: "MV-2024-0142", label: "Müller, Andreas", sub: "Tristanstr. 4, WE 03 · Mietvertrag" },
  { id: "MV-2023-0098", label: "Schäfer, Marlene", sub: "Tristanstr. 4, WE 07 · Mietvertrag" },
  { id: "MV-2021-0034", label: "Bauer, Reinhold", sub: "Leopoldstr. 88, WE 12 · Mietvertrag · Mahnstufe 2" },
];

const PreviewPane = ({ tpl, folder, onClose, onOpen, onDurchlauf }) => {
  const [recipients, setRecipients] = useState(RECIPIENTS);
  const [recipient, setRecipient] = useState(RECIPIENTS[0]);
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [pdfBase64, setPdfBase64] = useState("");
  const [pdfUrl, setPdfUrl] = useState(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState(null);

  const tplId = tpl?.id;
  const tplDoctype = tpl?.haupt_verteil_objekt;

  // Beim Wechsel der Vorlage zurück auf "Beispielwerte".
  useEffect(() => { setRecipient(RECIPIENTS[0]); }, [tplId]);

  // Echte Empfänger laden (nur eingebettet), abhängig vom Verteil-Objekt.
  useEffect(() => {
    if (!embedded || !tplId) { setRecipients(RECIPIENTS); return; }
    let alive = true;
    loadRecipients(tplDoctype)
      .then((res) => {
        if (!alive) return;
        const real = (res.items || []).map((r) => ({ id: r.id, label: r.label, sub: res.doctype || tplDoctype }));
        setRecipients([RECIPIENTS[0], ...real]);
      })
      .catch(() => { if (alive) setRecipients([RECIPIENTS[0]]); });
    return () => { alive = false; };
  }, [tplId, tplDoctype]);

  // Echtes PDF rendern (nur eingebettet), wenn Vorlage/Empfänger wechselt.
  useEffect(() => {
    if (!embedded || !tplId) { setPdfBase64(""); return; }
    let alive = true;
    setRendering(true);
    setRenderError(null);
    renderPreview({ templateName: tplId, hauptVerteilObjekt: tplDoctype, recipientId: recipient?.id })
      .then((res) => { if (alive) setPdfBase64(res.pdf_base64 || ""); })
      .catch((e) => { if (alive) { setRenderError(e?.message || "Vorschau fehlgeschlagen."); setPdfBase64(""); } })
      .finally(() => { if (alive) setRendering(false); });
    return () => { alive = false; };
  }, [tplId, tplDoctype, recipient?.id]);

  // base64 → Blob-URL (zuverlässiger als data: im iframe), mit Cleanup.
  useEffect(() => {
    if (!pdfBase64) { setPdfUrl(null); return; }
    try {
      const bin = atob(pdfBase64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const u = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
      setPdfUrl(u);
      return () => URL.revokeObjectURL(u);
    } catch (e) { setPdfUrl(null); }
  }, [pdfBase64]);

  if (!tpl) {
    return (
      <aside className="bw-preview">
        <div className="bw-preview-empty">
          <Icon name="play" size={32}/>
          <div className="bw-preview-empty-title">Vorschau</div>
          <div className="bw-preview-empty-sub">Klicke links auf eine Vorlage, um sie hier zu rendern.</div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="bw-preview">
      <div className="bw-preview-head">
        <div className="bw-preview-titlecol">
          <div className="bw-preview-title">{tpl.title}</div>
          <div className="bw-preview-sub">
            <span className="tpl-folder-pill" style={{ background: folder?.color ? `${folder.color}1a` : "var(--bg-subtle)", color: folder?.color || "var(--text-muted)" }}>
              {folder?.title || "—"}
            </span>
            <span>·</span>
            <span>{tpl.haupt_verteil_objekt}</span>
            {tpl.favorite && <Icon name="star" size={11} style={{ color: "#b4691c" }}/>}
          </div>
        </div>
        <button className="btn ghost icon" onClick={onClose} title="Vorschau schließen"><Icon name="x" size={13}/></button>
      </div>

      <div className="bw-preview-recipient">
        <button className="bw-preview-recipient-btn" onClick={() => setRecipientPickerOpen(o => !o)}>
          <Icon name="user" size={12}/>
          <span className="bw-preview-recipient-label">Empfänger</span>
          <span className="bw-preview-recipient-value">{recipient.label}</span>
          <Icon name="chevron-down" size={11}/>
        </button>
      </div>

      {recipientPickerOpen && (
        <div className="bw-preview-recipient-dropdown">
          {recipients.map(r => (
            <div
              key={r.id || "_b"}
              className={`bw-preview-recipient-row ${r.id === recipient.id ? "active" : ""}`}
              onClick={() => { setRecipient(r); setRecipientPickerOpen(false); }}
            >
              <div>
                <div className="bw-preview-recipient-row-label">{r.label}</div>
                <div className="bw-preview-recipient-row-sub">{r.sub}</div>
              </div>
              {r.id === recipient.id && <Icon name="check" size={12}/>}
            </div>
          ))}
        </div>
      )}

      <div className="bw-preview-pdf">
        {embedded ? (
          rendering ? (
            <div className="bw-preview-pdf-state">PDF wird gerendert …</div>
          ) : renderError ? (
            <div className="bw-preview-pdf-state" style={{ color: "var(--danger)" }}>{renderError}</div>
          ) : pdfUrl ? (
            <iframe className="bw-preview-pdf-frame" src={pdfUrl} title="PDF-Vorschau" style={{ width: "100%", height: "100%", border: "none" }}/>
          ) : (
            <div className="bw-preview-pdf-state">Keine Vorschau verfügbar.</div>
          )
        ) : (
          // Standalone (npm run dev): Mock-„Papier" ohne Backend.
          <div className="bw-preview-pdf-paper">
            <div className="bw-preview-pdf-right">München, 21. Mai 2026</div>
            <br/>
            <div>{recipient.label === "Beispielwerte" ? "Mustermieter" : recipient.label}</div>
            <div style={{ fontSize: 11, color: "#666" }}>Musterstr. 1 · 12345 Musterstadt</div>
            <br/><br/>
            <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 13 }}>{tpl.title}</div>
            <br/>
            <div style={{ fontStyle: "italic", color: "#666", fontSize: 11 }}>
              (Vorschau-Inhalt — in Frappe wird hier das echte PDF gerendert via render_template_preview_pdf.)
            </div>
            <br/>
            <div>{tpl.description}</div>
            <br/>
            {tpl.bausteine.map((b, i) => (
              <div key={i} style={{ marginBottom: 6, padding: "4px 6px", background: "var(--accent-50)", borderLeft: "2px solid var(--accent)", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--accent)" }}>
                [Baustein: {b}]
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bw-preview-stats">
        <div className="bw-preview-stat">
          <div className="bw-preview-stat-label">Bausteine</div>
          <div className="bw-preview-stat-value">{tpl.bausteine.length}</div>
        </div>
        <div className="bw-preview-stat">
          <div className="bw-preview-stat-label">Variablen</div>
          <div className="bw-preview-stat-value">{tpl.variables}</div>
        </div>
        <div className="bw-preview-stat">
          <div className="bw-preview-stat-label">Fehlende Pfade</div>
          <div className="bw-preview-stat-value" style={{ color: tpl.missing_paths > 0 ? "var(--danger)" : "var(--accent)" }}>
            {tpl.missing_paths}
          </div>
        </div>
        <div className="bw-preview-stat">
          <div className="bw-preview-stat-label">Verwendet seit</div>
          <div className="bw-preview-stat-value" style={{ fontSize: 12 }}>{tpl.last_used ? formatDate(tpl.last_used) : "nie"}</div>
        </div>
      </div>

      <div className="bw-preview-actions">
        <button className="btn primary" onClick={() => onDurchlauf(tpl)}><Icon name="send" size={13}/> Durchlauf starten</button>
        <button className="btn" onClick={() => onOpen(tpl)}><Icon name="edit" size={13}/> Im Editor öffnen</button>
      </div>
    </aside>
  );
};

// ============== Context Menu ==============

const ContextMenu = ({ x, y, items, onClose }) => {
  useEffect(() => {
    const onDown = (e) => {
      if (e.target.closest && e.target.closest(".bw-context-menu")) return;
      onClose();
    };
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
  }, [onClose]);
  return (
    <div className="bw-context-menu" style={{ left: x, top: y }}>
      {items.map((it, i) => it.sep ? (
        <div key={`s${i}`} className="bw-context-sep"/>
      ) : (
        <button key={i} className={`bw-context-item ${it.danger ? "danger" : ""}`} onClick={() => { it.onClick(); onClose(); }}>
          {it.icon && <Icon name={it.icon} size={12}/>}
          <span>{it.label}</span>
          {it.kbd && <span className="bw-context-kbd">{it.kbd}</span>}
        </button>
      ))}
    </div>
  );
};

// ============== Fulltext search helper ==============

// Build snippets around the search query. Returns array of { snippet, matchCount }.
const extractSnippets = (text, query, maxSnippets = 2, snippetLen = 100) => {
  if (!text || !query) return { snippets: [], matchCount: 0 };
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const positions = [];
  let i = 0;
  while (true) {
    const idx = lower.indexOf(q, i);
    if (idx < 0) break;
    positions.push(idx);
    i = idx + q.length;
  }
  if (!positions.length) return { snippets: [], matchCount: 0 };

  // Pick a few well-separated positions
  const picked = [];
  for (const pos of positions) {
    if (picked.length >= maxSnippets) break;
    if (picked.length === 0 || pos - picked[picked.length - 1] > snippetLen) {
      picked.push(pos);
    }
  }

  const snippets = picked.map((pos) => {
    const start = Math.max(0, pos - 40);
    const end = Math.min(text.length, pos + q.length + 60);
    const prefix = start > 0 ? "…" : "";
    const suffix = end < text.length ? "…" : "";
    return { text: prefix + text.slice(start, end) + suffix, matchOffset: pos - start + prefix.length };
  });
  return { snippets, matchCount: positions.length };
};

const HighlightedText = ({ text, query }) => {
  if (!query) return <>{text}</>;
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const parts = [];
  let i = 0;
  while (i < text.length) {
    const idx = lower.indexOf(q, i);
    if (idx < 0) {
      parts.push(text.slice(i));
      break;
    }
    if (idx > i) parts.push(text.slice(i, idx));
    parts.push(<mark key={idx}>{text.slice(idx, idx + q.length)}</mark>);
    i = idx + q.length;
  }
  return <>{parts.map((p, j) => typeof p === "string" ? <React.Fragment key={j}>{p}</React.Fragment> : p)}</>;
};

// ============== Move / Copy Modals ==============

const FolderTreePicker = ({ folders, selected, onSelect }) => {
  const [openKeys, setOpenKeys] = useState(() => new Set(folders.filter(f => !f.parent).map(f => f.id)));
  const children = (parentId) => folders.filter(f => f.parent === parentId);

  const toggle = (id) => {
    setOpenKeys(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const renderFolder = (f, depth) => {
    const kids = children(f.id);
    const isOpen = openKeys.has(f.id);
    const isActive = selected === f.id;
    return (
      <div key={f.id}>
        <div
          className={`folder-row ${isActive ? "active" : ""}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => onSelect(f.id)}
        >
          {kids.length > 0 ? (
            <span className="folder-chev" onClick={e => { e.stopPropagation(); toggle(f.id); }}>
              <Icon name="chevron-right" size={11} style={{ transform: isOpen ? "rotate(90deg)" : "none" }}/>
            </span>
          ) : <span className="folder-chev spacer"/>}
          <span className="folder-icon" style={f.color ? { color: f.color } : undefined}>
            <Icon name={isOpen && kids.length > 0 ? "folder-open" : "folder"} size={14}/>
          </span>
          <span className="folder-title">{f.title}</span>
        </div>
        {isOpen && kids.map(c => renderFolder(c, depth + 1))}
      </div>
    );
  };

  return (
    <div className="mc-folder-picker">
      <div
        className={`folder-row folder-row-root ${selected === "" ? "active" : ""}`}
        onClick={() => onSelect("")}
      >
        <span className="folder-chev spacer"/>
        <span className="folder-icon"><Icon name="home" size={14}/></span>
        <span className="folder-title">Alle Vorlagen (Root)</span>
      </div>
      {children(null).map(f => renderFolder(f, 0))}
    </div>
  );
};

const MoveCopyModal = ({ mode, items, folders, currentFolderId, onClose, onConfirm }) => {
  const [targetFolder, setTargetFolder] = useState(currentFolderId || "");
  const [newTitle, setNewTitle] = useState(
    items.length === 1 && mode === "copy" ? `${items[0].title} (Kopie)` : ""
  );

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onConfirm({ targetFolder, newTitle });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onConfirm, targetFolder, newTitle]);

  const isCopy = mode === "copy";
  const bulk = items.length > 1;
  const title = isCopy
    ? bulk ? `${items.length} Vorlagen kopieren` : `„${items[0].title}" kopieren`
    : bulk ? `${items.length} Vorlagen verschieben` : `„${items[0].title}" verschieben`;

  const targetTitle = targetFolder === ""
    ? "Alle Vorlagen (Root)"
    : folders.find(f => f.id === targetFolder)?.title || "—";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal mc-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name={isCopy ? "copy" : "folder"} size={14}/>
              {title}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
              {isCopy
                ? "Wähle den Zielordner. Die Original-Vorlage bleibt unverändert."
                : "Wähle den Zielordner. Die Vorlage wird dorthin verschoben."}
            </div>
          </div>
          <button className="btn ghost icon" onClick={onClose}><Icon name="x" size={14}/></button>
        </div>

        <div className="modal-body mc-body">
          {isCopy && !bulk && (
            <div className="mc-field">
              <label className="mc-label">Neuer Titel</label>
              <input
                className="mc-input"
                value={newTitle}
                onChange={e => setNewTitle(e.target.value)}
                autoFocus
              />
            </div>
          )}

          {bulk && (
            <div className="mc-bulk-summary">
              <div className="mc-label">Betroffene Vorlagen</div>
              <div className="mc-bulk-list">
                {items.slice(0, 5).map(t => (
                  <div key={t.id} className="mc-bulk-item">
                    <Icon name="tag" size={11}/>
                    <span>{t.title}</span>
                  </div>
                ))}
                {items.length > 5 && (
                  <div className="mc-bulk-more">… und {items.length - 5} weitere</div>
                )}
              </div>
            </div>
          )}

          <div className="mc-field">
            <label className="mc-label">Zielordner</label>
            <div className="mc-target-current">
              <Icon name={targetFolder ? "folder" : "home"} size={12}/>
              <span>{targetTitle}</span>
            </div>
            <FolderTreePicker
              folders={folders}
              selected={targetFolder}
              onSelect={setTargetFolder}
            />
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn ghost" onClick={onClose}>Abbrechen</button>
          <button
            className="btn primary"
            onClick={() => onConfirm({ targetFolder, newTitle })}
            disabled={isCopy && !bulk && !newTitle.trim()}
          >
            <Icon name={isCopy ? "copy" : "folder"} size={13}/>
            {isCopy ? "Kopieren" : "Verschieben"}
            <span className="kbd" style={{ marginLeft: 6, opacity: 0.7 }}>⌘↵</span>
          </button>
        </div>
      </div>
    </div>
  );
};

// ============== App ==============

export const App = () => {
  const [folders, setFolders] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  // Verschiebbare Sidebar — Breite in localStorage merken. Min/Max-Werte
  // verhindern, dass der User die Spalte unter die Lesbarkeitsschwelle
  // schrumpft oder die Vorlagen-Liste komplett verdrängt.
  const [sidebarWidth, setSidebarWidth] = useState(() => loadPref("browserSidebarWidth", 240));
  const [resizingSidebar, setResizingSidebar] = useState(false);
  useEffect(() => savePref("browserSidebarWidth", sidebarWidth), [sidebarWidth]);
  const onSidebarResizeStart = useCallback((e) => {
    e.preventDefault();
    setResizingSidebar(true);
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    const onMove = (ev) => {
      const next = Math.max(180, Math.min(480, startWidth + (ev.clientX - startX)));
      setSidebarWidth(next);
    };
    const onUp = () => {
      setResizingSidebar(false);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [sidebarWidth]);

  // Daten laden (eingebettet → Backend, standalone → Mock aus data.js).
  const reload = useCallback(() => {
    setLoading(true);
    loadBrowserData()
      .then((d) => {
        setFolders(d.folders || []);
        setTemplates(d.templates || []);
        setLoadError(null);
      })
      .catch((e) => setLoadError(e?.message || String(e)))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const [selectedFolder, setSelectedFolder] = useState(""); // "" = all
  const [smartFolder, setSmartFolder] = useState(null);  // "favorites" | "recent" | "used" | "broken" | null
  const [openKeys, setOpenKeys] = useState(() => new Set(["mahnungen", "mietvertrag"]));
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [previewId, setPreviewId] = useState(null);
  const [showPreview, setShowPreview] = useState(true);
  const [query, setQuery] = useState("");
  const [fulltextMode, setFulltextMode] = useState(false);
  const [sort, setSort] = useState("modified_desc");
  const [view, setView] = useState("list");
  const [dragOverFolder, setDragOverFolder] = useState(null);
  const [contextMenu, setContextMenu] = useState(null);
  const [counts, setCounts] = useState({});
  const [moveCopyModal, setMoveCopyModal] = useState(null); // { mode: 'move'|'copy', items: [...] }

  // --- Aktionen (Backend + optimistisches State-Update) -------------------
  // Verschieben in einen Ordner. Wurzel ("") ist kein gültiges Ziel, da die
  // Kategorie auf der Vorlage Pflicht ist → no-op.
  const moveTemplatesTo = useCallback((ids, folderId) => {
    if (!folderId) return;
    setTemplates((prev) => prev.map((t) => (ids.includes(t.id) ? { ...t, folder: folderId } : t)));
    setSelectedIds(new Set());
    moveTemplates(ids, folderId).catch(() => reload());
  }, [reload]);

  const toggleFavorite = useCallback((tpl) => {
    const next = !tpl.favorite;
    setTemplates((prev) => prev.map((t) => (t.id === tpl.id ? { ...t, favorite: next } : t)));
    apiSetFavorite(tpl.id, next).catch(() => reload());
  }, [reload]);

  const startDurchlauf = useCallback((tpl) => {
    openDurchlauf({ vorlage: tpl.id, title: tpl.title, iterationDoctype: tpl.haupt_verteil_objekt });
  }, []);

  const openInEditor = useCallback((tpl) => { apiOpenEditor(tpl.id); }, []);

  const removeTemplate = useCallback((tpl) => {
    if (!window.confirm(`Vorlage „${tpl.title}" wirklich löschen?`)) return;
    setTemplates((prev) => prev.filter((t) => t.id !== tpl.id));
    setPreviewId((p) => (p === tpl.id ? null : p));
    deleteTemplate(tpl.id).catch((e) => {
      window.alert(e?.message || "Löschen fehlgeschlagen.");
      reload();
    });
  }, [reload]);

  const handleCreateFolder = useCallback(() => {
    const title = window.prompt("Name des neuen Ordners:");
    if (!title || !title.trim()) return;
    apiCreateFolder(title.trim(), selectedFolder || null)
      .then(() => reload())
      .catch((e) => window.alert(e?.message || "Ordner konnte nicht angelegt werden."));
  }, [reload, selectedFolder]);

  // Build descendants lookup
  const descendants = useMemo(() => {
    const map = {};
    folders.forEach(f => { map[f.id] = [f.id]; });
    folders.forEach(f => {
      let cur = f;
      while (cur && cur.parent) {
        map[cur.parent].push(f.id);
        cur = folders.find(x => x.id === cur.parent);
      }
    });
    return map;
  }, [folders]);

  // Compute folder counts (incl. children) and smart counts
  useEffect(() => {
    const c = { __all: templates.length };
    folders.forEach(f => {
      const ids = new Set(descendants[f.id] || [f.id]);
      c[f.id] = templates.filter(t => ids.has(t.folder)).length;
    });
    setCounts(c);
  }, [templates, folders, descendants]);

  const smartCounts = useMemo(() => ({
    favorites: templates.filter(t => t.favorite).length,
    recent: templates.filter(t => {
      const d = new Date(t.modified);
      return (Date.now() - d.getTime()) < 7 * 24 * 60 * 60 * 1000;
    }).length,
    used: templates.filter(t => t.last_used).length,
    broken: templates.filter(t => t.missing_paths > 0).length,
  }), [templates]);

  // Filter + sort
  const visibleTemplates = useMemo(() => {
    let rows = templates;
    if (smartFolder === "favorites") rows = rows.filter(t => t.favorite);
    else if (smartFolder === "recent") {
      rows = rows.filter(t => (Date.now() - new Date(t.modified).getTime()) < 7 * 24 * 60 * 60 * 1000);
    }
    else if (smartFolder === "used") rows = rows.filter(t => t.last_used);
    else if (smartFolder === "broken") rows = rows.filter(t => t.missing_paths > 0);
    else if (selectedFolder) {
      const ids = new Set(descendants[selectedFolder] || [selectedFolder]);
      rows = rows.filter(t => ids.has(t.folder));
    }

    const q = query.trim().toLowerCase();
    if (q) {
      rows = rows.filter(t => {
        const inTitle = t.title.toLowerCase().includes(q);
        const inDesc = (t.description || "").toLowerCase().includes(q);
        const inBausteine = t.bausteine.join(" ").toLowerCase().includes(q);
        const inContent = fulltextMode && (t.content || "").toLowerCase().includes(q);
        return inTitle || inDesc || inBausteine || inContent;
      });
    }

    const sorted = [...rows];
    switch (sort) {
      case "title_asc": sorted.sort((a, b) => a.title.localeCompare(b.title, "de")); break;
      case "title_desc": sorted.sort((a, b) => b.title.localeCompare(a.title, "de")); break;
      case "modified_asc": sorted.sort((a, b) => new Date(a.modified) - new Date(b.modified)); break;
      case "used_desc": sorted.sort((a, b) => {
        if (!a.last_used && !b.last_used) return 0;
        if (!a.last_used) return 1;
        if (!b.last_used) return -1;
        return new Date(b.last_used) - new Date(a.last_used);
      }); break;
      case "modified_desc":
      default: sorted.sort((a, b) => new Date(b.modified) - new Date(a.modified));
    }
    return sorted;
  }, [templates, selectedFolder, smartFolder, descendants, query, fulltextMode, sort]);

  // Fulltext-match map: template.id -> { snippets, matchCount }
  const ftMatches = useMemo(() => {
    if (!fulltextMode || !query.trim()) return {};
    const map = {};
    for (const t of visibleTemplates) {
      const m = extractSnippets(t.content || "", query.trim(), 2, 100);
      if (m.matchCount > 0) map[t.id] = m;
    }
    return map;
  }, [visibleTemplates, fulltextMode, query]);

  const ftTotalHits = useMemo(
    () => Object.values(ftMatches).reduce((n, m) => n + m.matchCount, 0),
    [ftMatches]
  );

  const previewTpl = useMemo(() => templates.find(t => t.id === previewId), [templates, previewId]);

  const toggleOpen = (id) => {
    setOpenKeys(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectFolder = (id) => {
    setSelectedFolder(id);
    setSmartFolder(null);
  };
  const selectSmart = (key) => {
    setSmartFolder(key);
    setSelectedFolder("");
  };

  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll = (yes) => {
    if (yes) setSelectedIds(new Set(visibleTemplates.map(t => t.id)));
    else setSelectedIds(new Set());
  };

  const allSelected = selectedIds.size > 0 && selectedIds.size === visibleTemplates.length;
  const someSelected = selectedIds.size > 0 && selectedIds.size < visibleTemplates.length;

  const onSortClick = (key) => {
    setSort(prev => {
      if (prev === `${key}_desc`) return `${key}_asc`;
      if (prev === `${key}_asc`) return `${key}_desc`;
      return `${key}_desc`;
    });
  };

  const onDragStart = (e, tplId) => {
    if (!selectedIds.has(tplId)) {
      e.dataTransfer.setData("application/json", JSON.stringify({ ids: [tplId] }));
    } else {
      e.dataTransfer.setData("application/json", JSON.stringify({ ids: Array.from(selectedIds) }));
    }
    e.dataTransfer.effectAllowed = "move";
  };

  const onDropFolder = (folderId, e) => {
    try {
      const data = JSON.parse(e.dataTransfer.getData("application/json"));
      moveTemplatesTo(data.ids || [], folderId);
    } catch (err) {}
  };

  const onAction = (action, tpl) => {
    if (action === "menu") {
      // Open context menu near the action button
      const r = window.event?.target?.getBoundingClientRect() || { left: 200, bottom: 200 };
      setContextMenu({
        x: r.right - 200,
        y: r.bottom + 4,
        tpl,
      });
    } else if (action === "move") {
      setMoveCopyModal({ mode: "move", items: [tpl] });
    } else if (action === "copy") {
      setMoveCopyModal({ mode: "copy", items: [tpl] });
    } else if (action === "favorite") {
      toggleFavorite(tpl);
    } else if (action === "durchlauf") {
      startDurchlauf(tpl);
    } else if (action === "open") {
      openInEditor(tpl);
    } else if (action === "delete") {
      removeTemplate(tpl);
    } else {
      // "rename" o. Ä. noch nicht verdrahtet.
      console.log(`Action ${action} on ${tpl.id}`);
    }
  };

  const openBulkMove = () => {
    const items = visibleTemplates.filter(t => selectedIds.has(t.id));
    if (!items.length) return;
    setMoveCopyModal({ mode: "move", items });
  };
  const openBulkCopy = () => {
    const items = visibleTemplates.filter(t => selectedIds.has(t.id));
    if (!items.length) return;
    setMoveCopyModal({ mode: "copy", items });
  };

  const handleMoveCopyConfirm = ({ targetFolder, newTitle }) => {
    const { mode, items } = moveCopyModal;
    if (mode === "move") {
      moveTemplatesTo(items.map(i => i.id), targetFolder);
    } else if (mode === "copy") {
      // Kopien nacheinander anlegen, dann neu laden (Backend vergibt Namen).
      Promise.all(items.map(i => copyTemplate(i.id, newTitle || `${i.title} (Kopie)`)))
        .then(() => reload())
        .catch((e) => { window.alert(e?.message || "Kopieren fehlgeschlagen."); reload(); });
    }
    setMoveCopyModal(null);
  };

  const onPreview = (tpl) => {
    setPreviewId(tpl.id);
  };

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "Escape") {
        setSelectedIds(new Set());
        setPreviewId(null);
      }
      if (e.key === "/" || ((e.metaKey || e.ctrlKey) && e.key === "k")) {
        e.preventDefault();
        document.querySelector(".bw-search-input")?.focus();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "i") {
        e.preventDefault();
        setShowPreview(s => !s);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const emptyHint = loadError
    ? `Fehler beim Laden: ${loadError}`
    : loading
      ? "Lade Vorlagen …"
      : query
        ? `Keine Vorlagen für „${query}".`
        : smartFolder === "favorites"
          ? "Keine Favoriten — klick auf den Stern bei einer Vorlage."
          : smartFolder === "broken"
            ? "Alle Vorlagen haben ihre Pfade. 🎉"
            : "Keine Vorlagen in diesem Ordner.";

  return (
    <div
      className={`browser-app ${resizingSidebar ? "resizing-sidebar" : ""}`}
      style={{ gridTemplateColumns: `${sidebarWidth}px 6px 1fr auto` }}
    >
      <Sidebar
        folders={folders}
        selectedFolder={selectedFolder}
        smartFolder={smartFolder}
        onSelectFolder={selectFolder}
        onSelectSmart={selectSmart}
        openKeys={openKeys}
        onToggle={toggleOpen}
        counts={counts}
        smartCounts={smartCounts}
        dragOver={dragOverFolder}
        onDragOverFolder={setDragOverFolder}
        onDropFolder={onDropFolder}
        onCreateFolder={handleCreateFolder}
      />
      <div className="bw-resize-handle" onMouseDown={onSidebarResizeStart} title="Ziehen, um die Seitenleiste zu verbreitern" />

      <main className={`bw-main ${showPreview && previewTpl ? "with-preview" : ""}`}>
        <Topbar
          folders={folders}
          folderId={selectedFolder}
          smartFolder={smartFolder}
          onSelectFolder={selectFolder}
          query={query}
          onQuery={setQuery}
          fulltextMode={fulltextMode}
          onToggleFulltextMode={() => setFulltextMode(m => !m)}
          sort={sort}
          onSort={setSort}
          view={view}
          onView={setView}
          showPreview={showPreview}
          onTogglePreview={() => setShowPreview(s => !s)}
        />

        <BulkBar
          count={selectedIds.size}
          onClear={() => setSelectedIds(new Set())}
          onMove={openBulkMove}
          onCopy={openBulkCopy}
          onDelete={() => console.log("Bulk-Löschen")}
          onDurchlauf={() => {
            const first = visibleTemplates.find(t => selectedIds.has(t.id));
            if (first) startDurchlauf(first);
          }}
        />

        {fulltextMode && query.trim() && (
          <div className="bw-ft-banner">
            <Icon name="search" size={12}/>
            <span>
              <strong>{ftTotalHits}</strong> Treffer in <strong>{Object.keys(ftMatches).length}</strong> Vorlage{Object.keys(ftMatches).length !== 1 ? "n" : ""}
              {visibleTemplates.length > Object.keys(ftMatches).length && (
                <span style={{ color: "var(--text-faint)" }}> · {visibleTemplates.length - Object.keys(ftMatches).length} weitere Titel-/Beschreibungs-Treffer</span>
              )}
            </span>
            <button className="bw-ft-clear" onClick={() => setQuery("")}>Suche zurücksetzen</button>
          </div>
        )}

        <TemplateList
          templates={visibleTemplates}
          folders={folders}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onSelectAll={selectAll}
          allSelected={allSelected}
          someSelected={someSelected}
          previewId={previewId}
          onPreview={onPreview}
          onAction={onAction}
          onDragStart={onDragStart}
          sort={sort}
          onSortClick={onSortClick}
          view={view}
          query={query}
          emptyHint={emptyHint}
          fulltextMode={fulltextMode}
          ftMatches={ftMatches}
        />
      </main>

      {showPreview && previewTpl && (
        <PreviewPane
          tpl={previewTpl}
          folder={folders.find(f => f.id === previewTpl.folder)}
          onClose={() => setShowPreview(false)}
          onOpen={(tpl) => openInEditor(tpl)}
          onDurchlauf={(tpl) => startDurchlauf(tpl)}
        />
      )}

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            { icon: "edit", label: "Im Editor öffnen", onClick: () => onAction("open", contextMenu.tpl), kbd: "↵" },
            { icon: "send", label: "Durchlauf starten", onClick: () => onAction("durchlauf", contextMenu.tpl) },
            { sep: true },
            { icon: "star", label: contextMenu.tpl.favorite ? "Favorit entfernen" : "Als Favorit markieren", onClick: () => onAction("favorite", contextMenu.tpl) },
            { icon: "folder", label: "Verschieben…", onClick: () => onAction("move", contextMenu.tpl) },
            { icon: "copy", label: "Kopieren…", onClick: () => onAction("copy", contextMenu.tpl) },
            { icon: "edit", label: "Umbenennen…", onClick: () => onAction("rename", contextMenu.tpl) },
            { sep: true },
            { icon: "x", label: "Löschen", danger: true, onClick: () => onAction("delete", contextMenu.tpl) },
          ]}
        />
      )}

      {moveCopyModal && (
        <MoveCopyModal
          mode={moveCopyModal.mode}
          items={moveCopyModal.items}
          folders={folders}
          currentFolderId={selectedFolder}
          onClose={() => setMoveCopyModal(null)}
          onConfirm={handleMoveCopyConfirm}
        />
      )}
    </div>
  );
};

