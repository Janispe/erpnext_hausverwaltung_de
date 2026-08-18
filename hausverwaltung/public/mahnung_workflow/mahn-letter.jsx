// mahn-letter.jsx — Vorschau der tatsächlich erzeugten Serienbrief-PDF.

function pdfBlobUrlMH(pdfBase64) {
  const binary = window.atob(pdfBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
}

function previewErrorMessageMH(error) {
  return error?.message
    || error?._server_messages
    || "Die PDF-Vorschau konnte nicht erzeugt werden.";
}

function LetterPreviewMH({ d }) {
  const [preview, setPreview] = React.useState({ url: "", loading: false, error: "" });
  const urlRef = React.useRef("");
  const requestRef = React.useRef(0);
  const frameRef = React.useRef(null);

  const payload = {
    belege: d.posten.map((posten) => posten.beleg),
    dunningType: d.dunningType,
    mahndatum: d.mahndatum,
    fristTage: d.fristTage,
    mahngebuehr: d.gebuehr,
    zinssatz: d.zinssatz,
    zinsenAktiv: d.zinsenAktiv,
    serienbriefVorlage: d.serienbriefVorlage,
    kontonummer: d.kontonummer,
    variablen: d.variablen,
    dunning: d.dunning,
  };
  const signature = JSON.stringify(payload);

  React.useEffect(() => {
    const actions = window.MAHN_ACTIONS;
    if (!actions?.previewDunning) {
      setPreview({ url: "", loading: false, error: "PDF-Vorschau ist in dieser Umgebung nicht verfügbar." });
      return undefined;
    }
    if (!d.dunning && (!d.serienbriefVorlage || payload.belege.length === 0)) {
      setPreview({
        url: "",
        loading: false,
        error: payload.belege.length === 0
          ? "Bitte mindestens einen Posten auswählen."
          : "Für diesen Mahnungstyp ist keine Serienbrief-Vorlage hinterlegt.",
      });
      return undefined;
    }

    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setPreview((current) => ({ ...current, loading: true, error: "" }));

    const timeout = window.setTimeout(async () => {
      try {
        const result = await actions.previewDunning(payload);
        if (requestRef.current !== requestId) return;
        if (!result?.pdf_base64) throw new Error("Der Server hat keine PDF-Vorschau geliefert.");
        const nextUrl = pdfBlobUrlMH(result.pdf_base64);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = nextUrl;
        setPreview({ url: nextUrl, loading: false, error: "" });
      } catch (error) {
        if (requestRef.current !== requestId) return;
        setPreview((current) => ({ ...current, loading: false, error: previewErrorMessageMH(error) }));
      }
    }, 900);

    return () => window.clearTimeout(timeout);
  }, [signature]);

  React.useEffect(() => {
    window.MAHN_PREVIEW_PRINT = () => {
      try {
        frameRef.current?.contentWindow?.focus();
        frameRef.current?.contentWindow?.print();
      } catch (_error) {
        if (urlRef.current) window.open(urlRef.current, "_blank", "noopener");
      }
    };
    return () => {
      requestRef.current += 1;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = "";
      if (window.MAHN_PREVIEW_PRINT) delete window.MAHN_PREVIEW_PRINT;
    };
  }, []);

  return (
    <div className="mh-pdf-preview" data-screen-label="Serienbrief-PDF-Vorschau">
      <div className="mh-pdf-preview-head">
        <div>
          <strong>Serienbrief-PDF</strong>
          <span>{d.serienbriefVorlage || d.vorlageLabel}</span>
        </div>
        {preview.loading && <span className="mh-pdf-preview-status">wird aktualisiert …</span>}
      </div>

      {preview.error && !preview.url && (
        <div className="mh-pdf-preview-error">{preview.error}</div>
      )}
      {preview.loading && !preview.url && (
        <div className="mh-pdf-preview-empty">PDF wird erzeugt …</div>
      )}
      {preview.url && (
        <div className="mh-pdf-preview-frame-wrap">
          <iframe
            ref={frameRef}
            className="mh-pdf-preview-frame"
            src={preview.url}
            title="Vorschau des Mahnungsschreibens"
          />
          {preview.loading && <div className="mh-pdf-preview-loading">PDF wird neu erzeugt …</div>}
        </div>
      )}
      {preview.error && preview.url && (
        <div className="mh-pdf-preview-error is-inline">{preview.error}</div>
      )}
    </div>
  );
}

Object.assign(window, { LetterPreviewMH });
