import React, { useState, useMemo, useEffect } from "react";
import { Icon } from "./Icon.jsx";
import { RenderedBlock, resolveBlocks } from "./InlinePreview.jsx";
import { TEXT_BAUSTEINE, SAMPLE_RECIPIENTS } from "../data.js";

export const PdfMaximized = ({ template, recipient, onChangeRecipient, onClose }) => {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Use the InlinePreview structure logic to know about pages — for the prototype we'll
  // just compute resolved blocks and split into pages similar to inline-preview.
  // For a real Frappe integration the PDF backend renders the truth; here we approximate.
  const bausteinMap = useMemo(() => {
    const m = new Map();
    TEXT_BAUSTEINE.forEach(bs => m.set(bs.name, bs));
    return m;
  }, []);

  // Use the helpers exported from inline-preview if available
    const resolved = useMemo(() => resolveBlocks ? resolveBlocks(template.blocks, recipient, bausteinMap) : [], [template, recipient, bausteinMap]);

  // For a quick demo, pages are split by page-break-hint markers
  const pages = useMemo(() => {
    const ps = [];
    let cur = [];
    resolved.forEach(b => {
      if (b.type === "page-break-hint" && b.before && cur.length > 0) {
        ps.push(cur);
        cur = [];
        return;
      }
      cur.push(b);
    });
    if (cur.length) ps.push(cur);
    return ps.length ? ps : [[]];
  }, [resolved]);

  const pageCount = pages.length;
  const safePage = Math.min(Math.max(page, 1), pageCount);

  return (
    <div className="pdf-max-backdrop" onClick={onClose}>
      <div className="pdf-max-wrap" onClick={e => e.stopPropagation()}>
        <header className="pdf-max-header">
          <div className="pdf-max-title">
            <Icon name="play" size={13}/>
            <span style={{ fontWeight: 600 }}>PDF-Vorschau</span>
            <span style={{ color: "var(--text-muted)", marginLeft: 6 }}>· {template.title}</span>
          </div>

          <div className="pdf-max-controls">
            <button
              className="btn sm"
              onClick={() => setRecipientPickerOpen(o => !o)}
              style={{ position: "relative" }}
            >
              <Icon name="user" size={12}/>
              <span style={{ marginLeft: 4 }}>{recipient.label.split("—")[0].trim()}</span>
              <Icon name="chevron-down" size={11} style={{ marginLeft: 4 }}/>
            </button>

            <div className="pdf-max-page-nav">
              <button className="btn sm ghost icon" onClick={() => setPage(p => Math.max(p - 1, 1))} disabled={safePage <= 1}>
                <Icon name="chevron-right" size={13} style={{ transform: "rotate(180deg)" }}/>
              </button>
              <span className="pdf-max-page-info">Seite <strong>{safePage}</strong> / {pageCount}</span>
              <button className="btn sm ghost icon" onClick={() => setPage(p => Math.min(p + 1, pageCount))} disabled={safePage >= pageCount}>
                <Icon name="chevron-right" size={13}/>
              </button>
            </div>

            <div className="pdf-max-zoom">
              <button className="btn sm ghost icon" onClick={() => setZoom(z => Math.max(z - 10, 50))}>−</button>
              <span className="pdf-max-zoom-val">{zoom}%</span>
              <button className="btn sm ghost icon" onClick={() => setZoom(z => Math.min(z + 10, 200))}>+</button>
            </div>

            <button className="btn sm"><Icon name="download" size={12}/> PDF</button>
            <button className="btn ghost icon" onClick={onClose} title="Schließen (Esc)"><Icon name="x" size={14}/></button>
          </div>
        </header>

        {recipientPickerOpen && (
          <div className="pdf-max-recipient-pop">
            {SAMPLE_RECIPIENTS.map(r => (
              <div
                key={r.id}
                className={`recipient-row ${r.id === recipient.id ? "active" : ""}`}
                onClick={() => { onChangeRecipient(r); setRecipientPickerOpen(false); setPage(1); }}
                style={{ padding: "8px 14px" }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>{r.label}</div>
                  <div style={{ fontSize: 11, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{r.id} · Mahnstufe {r.values.mahnstufe}</div>
                </div>
                {r.id === recipient.id && <Icon name="check" size={14}/>}
              </div>
            ))}
          </div>
        )}

        <div className="pdf-max-stage">
          <div
            className="a4-page pdf-max-page"
            style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
          >
            <div className="a4-margin-guide top" />
            <div className="a4-margin-guide bottom" />
            <div className="a4-margin-guide left" />
            <div className="a4-margin-guide right" />
            <div className="a4-content">
              {(pages[safePage - 1] || []).map((b, i) => (
                <RenderedBlock key={i} block={b} recipient={recipient}/>
              ))}
            </div>
            <div className="a4-page-footer">
              <span>Seite {safePage} von {pageCount}</span>
              <span style={{ float: "right" }}>{recipient.label.split("—")[0].trim()} · {template.title}</span>
            </div>
          </div>
        </div>

        <footer className="pdf-max-footer">
          <span><span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", marginRight: 6 }}/> Chrome-PDF gerendert · 1,4 s</span>
          <span style={{ color: "var(--text-muted)" }}>Klicke außerhalb oder <span className="kbd">Esc</span> zum Schließen</span>
        </footer>
      </div>
    </div>
  );
};

