import React, { useState, useEffect } from "react";
import { Icon } from "./Icon.jsx";

// Vollbild-PDF-Vorschau. Zeigt das echte gerenderte PDF (base64) im Browser-
// PDF-Viewer (eigener Zoom/Seiten); Empfänger-Wechsel rendert neu.
export const PdfMaximized = ({ template, recipient, recipients, pdfBase64, loading, onChangeRecipient, onRefresh, onClose }) => {
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [url, setUrl] = useState(null);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Bei Öffnen rendern, falls noch kein PDF vorliegt.
  useEffect(() => {
    if (!pdfBase64 && !loading && onRefresh) onRefresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!pdfBase64) { setUrl(null); return; }
    try {
      const bin = atob(pdfBase64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const u = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
      setUrl(u);
      return () => URL.revokeObjectURL(u);
    } catch (e) { setUrl(null); }
  }, [pdfBase64]);

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
            <button className="btn sm" onClick={() => setRecipientPickerOpen(o => !o)} style={{ position: "relative" }}>
              <Icon name="user" size={12}/>
              <span style={{ marginLeft: 4 }}>{(recipient && recipient.label) || "Beispielwerte"}</span>
              <Icon name="chevron-down" size={11} style={{ marginLeft: 4 }}/>
            </button>
            <button className="btn sm" onClick={onRefresh} disabled={loading} title="Neu rendern">
              <Icon name="play" size={12}/>
            </button>
            {url && (
              <a className="btn sm" href={url} download={`vorlage-${template.id || "preview"}.pdf`}>
                <Icon name="download" size={12}/> PDF
              </a>
            )}
            <button className="btn ghost icon" onClick={onClose} title="Schließen (Esc)"><Icon name="x" size={14}/></button>
          </div>
        </header>

        {recipientPickerOpen && (
          <div className="pdf-max-recipient-pop">
            <div
              className={`recipient-row ${!recipient?.id ? "active" : ""}`}
              onClick={() => { onChangeRecipient(null); setRecipientPickerOpen(false); }}
              style={{ padding: "8px 14px" }}
            >
              <div style={{ flex: 1, fontWeight: 500, fontSize: 13 }}>Beispielwerte</div>
              {!recipient?.id && <Icon name="check" size={14}/>}
            </div>
            {(recipients || []).map(r => (
              <div
                key={r.id}
                className={`recipient-row ${r.id === recipient?.id ? "active" : ""}`}
                onClick={() => { onChangeRecipient(r); setRecipientPickerOpen(false); }}
                style={{ padding: "8px 14px" }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>{r.label}</div>
                  <div style={{ fontSize: 11, color: "var(--text-faint)", fontFamily: "var(--font-mono)" }}>{r.id}</div>
                </div>
                {r.id === recipient?.id && <Icon name="check" size={14}/>}
              </div>
            ))}
          </div>
        )}

        <div className="pdf-max-stage" style={{ display: "flex", alignItems: "stretch", justifyContent: "stretch" }}>
          {loading ? (
            <div className="editor-loading" style={{ flex: 1 }}>PDF wird gerendert …</div>
          ) : url ? (
            <iframe title="PDF-Vorschau (groß)" src={url} style={{ flex: 1, width: "100%", height: "100%", border: "none", background: "#fff" }}/>
          ) : (
            <div className="editor-loading" style={{ flex: 1 }}>Keine Vorschau verfügbar.</div>
          )}
        </div>

        <footer className="pdf-max-footer">
          <span><span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", marginRight: 6 }}/> Chrome-PDF · gespeicherter Stand</span>
          <span style={{ color: "var(--text-muted)" }}>Klicke außerhalb oder <span className="kbd">Esc</span> zum Schließen</span>
        </footer>
      </div>
    </div>
  );
};
