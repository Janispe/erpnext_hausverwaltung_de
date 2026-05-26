import React, { useState, useMemo, useEffect } from "react";
import { Icon } from "./Icon.jsx";
import { TEMPLATE_TREE } from "../data.js";
import { loadPref, savePref } from "../persist.js";

const SORT_OPTIONS = [
  { value: "kategorie", label: "Nach Ordner" },
  { value: "mod_desc", label: "Geändert ↓" },
  { value: "mod_asc", label: "Geändert ↑" },
  { value: "title_asc", label: "Titel A–Z" },
];

const collator = new Intl.Collator("de", { sensitivity: "base" });

// Templates ohne modified_iso ans Ende sortieren — sonst landen sie bei mod_desc oben.
const cmpModDesc = (a, b) => {
  const av = a.modified_iso || "";
  const bv = b.modified_iso || "";
  if (!av && !bv) return 0;
  if (!av) return 1;
  if (!bv) return -1;
  return bv.localeCompare(av);
};
const cmpModAsc = (a, b) => {
  const av = a.modified_iso || "";
  const bv = b.modified_iso || "";
  if (!av && !bv) return 0;
  if (!av) return 1;
  if (!bv) return -1;
  return av.localeCompare(bv);
};
const cmpTitleAsc = (a, b) => collator.compare(a.title || "", b.title || "");

const sortTemplates = (templates, mode) => {
  if (!templates || mode === "kategorie") return templates || [];
  const arr = templates.slice();
  if (mode === "mod_desc") arr.sort(cmpModDesc);
  else if (mode === "mod_asc") arr.sort(cmpModAsc);
  else if (mode === "title_asc") arr.sort(cmpTitleAsc);
  return arr;
};

export const Navigator = ({ tree: propTree, currentId, onSelect, collapsed, onToggleCollapse }) => {
  const tree = (propTree && propTree.length) ? propTree : TEMPLATE_TREE;
  const [query, setQuery] = useState("");
  // Offene/zugeklappte Kategorien aus localStorage wiederherstellen.
  const [openKeys, setOpenKeys] = useState(() => new Set(loadPref("navOpenKeys", [])));
  const [sort, setSort] = useState(() => {
    const stored = loadPref("navSort", "kategorie");
    return SORT_OPTIONS.some((o) => o.value === stored) ? stored : "kategorie";
  });

  // Offene Kategorien merken (uebersteht Neuladen/Sessions).
  useEffect(() => { savePref("navOpenKeys", [...openKeys]); }, [openKeys]);
  useEffect(() => { savePref("navSort", sort); }, [sort]);

  // Gruppe der aktuell ausgewählten Vorlage automatisch aufklappen (bzw. erste).
  useEffect(() => {
    const grp = tree.find(c => c.templates.some(t => t.id === currentId));
    setOpenKeys(prev => {
      const next = new Set(prev);
      if (grp) next.add(grp.key);
      else if (tree[0]) next.add(tree[0].key);
      return next;
    });
  }, [currentId, tree]);

  const toggle = (k) => {
    setOpenKeys(prev => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matchesQuery = (cat) => {
      if (!q) return cat.templates;
      return cat.templates.filter(
        (t) => t.title.toLowerCase().includes(q) || cat.label.toLowerCase().includes(q),
      );
    };
    return tree
      .map((cat) => ({ ...cat, templates: sortTemplates(matchesQuery(cat), sort) }))
      .filter((cat) => cat.templates.length > 0);
  }, [query, tree, sort]);

  const expandedKeys = query ? new Set(filtered.map(c => c.key)) : openKeys;

  if (collapsed) {
    return (
      <aside className="navigator navigator-collapsed">
        <button className="nav-collapse-btn" onClick={onToggleCollapse} title="Vorlagen einblenden">
          <Icon name="chevron-right" size={14}/>
        </button>
        <div className="nav-collapsed-label">Vorlagen</div>
      </aside>
    );
  }

  return (
    <aside className="navigator">
      <div className="nav-header">
        <div className="nav-header-row">
          <div className="label">Vorlagen</div>
          <button className="nav-collapse-btn small" onClick={onToggleCollapse} title="Einklappen">
            <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }}/>
          </button>
        </div>
        <div className="nav-search">
          <span className="icon-left"><Icon name="search" size={14}/></span>
          <input
            placeholder="Vorlage suchen…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {!query && <span className="kbd-hint kbd">⌘K</span>}
        </div>
        <div className="nav-sort">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            title="Sortierung der Vorlagen innerhalb der Ordner"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="nav-tree">
        {tree.some(c => c.pinned) && (
          <div className="nav-section">
            <div className="nav-section-title">Angeheftet</div>
          </div>
        )}
        {filtered.map(cat => {
          const isOpen = expandedKeys.has(cat.key);
          return (
            <div key={cat.key}>
              <div className={`nav-cat ${isOpen ? "open" : ""}`} onClick={() => toggle(cat.key)}>
                <span className="chev"><Icon name="chevron-right" size={12}/></span>
                <span className="nav-cat-icon">
                  <Icon name={isOpen ? "folder-open" : "folder"} size={13}/>
                </span>
                <span className="nav-cat-label">{cat.label}</span>
                {cat.pinned && <span className="pin"><Icon name="pin" size={11}/></span>}
                <span className="count">{cat.count}</span>
              </div>
              {isOpen && cat.templates.map(t => (
                <div
                  key={t.id}
                  className={`nav-template ${t.id === currentId ? "current" : ""}`}
                  onClick={() => onSelect && onSelect(t.id)}
                >
                  <span className="nav-template-icon">
                    <Icon name="file" size={12}/>
                  </span>
                  <div className="nav-template-body">
                    <div className="name" title={t.title}>{t.title}</div>
                    <div className="meta">{t.modified}</div>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="empty-hint">Keine Treffer für „{query}".</div>
        )}
      </div>
    </aside>
  );
};

