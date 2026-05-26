import React, { useState, useMemo, useEffect } from "react";
import { Icon } from "./Icon.jsx";
import { TEMPLATE_TREE } from "../data.js";
import { loadPref, savePref } from "../persist.js";

export const Navigator = ({ tree: propTree, currentId, onSelect, collapsed, onToggleCollapse }) => {
  const tree = (propTree && propTree.length) ? propTree : TEMPLATE_TREE;
  const [query, setQuery] = useState("");
  // Offene/zugeklappte Kategorien aus localStorage wiederherstellen.
  const [openKeys, setOpenKeys] = useState(() => new Set(loadPref("navOpenKeys", [])));

  // Offene Kategorien merken (uebersteht Neuladen/Sessions).
  useEffect(() => { savePref("navOpenKeys", [...openKeys]); }, [openKeys]);

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
    if (!q) return tree;
    return tree.map(cat => ({
      ...cat,
      templates: cat.templates.filter(t => t.title.toLowerCase().includes(q) || cat.label.toLowerCase().includes(q)),
    })).filter(cat => cat.templates.length > 0);
  }, [query, tree]);

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
                <span>{cat.label}</span>
                {cat.pinned && <span className="pin"><Icon name="pin" size={11}/></span>}
                <span className="count">{cat.count}</span>
              </div>
              {isOpen && cat.templates.map(t => (
                <div
                  key={t.id}
                  className={`nav-template ${t.id === currentId ? "current" : ""}`}
                  onClick={() => onSelect && onSelect(t.id)}
                >
                  <div className="name" title={t.title}>{t.title}</div>
                  <div className="meta">{t.modified}</div>
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

