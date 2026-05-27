// app.jsx — Main shell + variant switcher + Tweaks.

const { useState, useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "variant": "A",
  "density": "regular",
  "showCats": false,
  "gruppieren": true,
  "highlightOpen": true,
  "defaultCatsOpen": false,
  "printMode": false
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const { mieter, filters, rows, totalRow, summary } = window.MIETERKONTO;

  const [variant, setVariantLocal] = useState(t.variant);
  const [showCats, setShowCats] = useState(t.showCats);
  const [gruppieren, setGruppieren] = useState(t.gruppieren);

  useEffect(() => { setVariantLocal(t.variant); }, [t.variant]);
  useEffect(() => { setShowCats(t.showCats); }, [t.showCats]);
  useEffect(() => { setGruppieren(t.gruppieren); }, [t.gruppieren]);

  const setVariant = (v) => {
    setVariantLocal(v);
    setTweak("variant", v);
  };

  // Filter-Toggle synct mit Tweak
  const setShowCatsBoth = (v) => { setShowCats(v); setTweak("showCats", v); };
  const setGruppierenBoth = (v) => { setGruppieren(v); setTweak("gruppieren", v); };

  return (
    <div className={`mk-app ${t.printMode ? "is-print-mode" : ""}`}>
      <div className="mk-topbar" data-screen-label="Topbar">
        <div className="mk-topbar-left">
          <h1>Mieterkonto</h1>
          <span className="mk-crumb">Hausverwaltung · Berichte</span>
          <div className="mk-tabs" style={{ marginLeft: 16 }}>
            {[
              { v: "A", l: "Kontoauszug" },
              { v: "B", l: "Verlauf" },
              { v: "C", l: "Dashboard" },
            ].map(({ v, l }) => (
              <button key={v}
                className={`mk-tab ${variant === v ? "is-active" : ""}`}
                onClick={() => setVariant(v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="mk-topbar-actions">
          <button className="mk-btn mk-btn-ghost" onClick={() => window.print()}>Drucken</button>
          <button className="mk-btn mk-btn-ghost">Export CSV</button>
          <button className="mk-btn mk-btn-primary">PDF</button>
        </div>
      </div>

      <main className="mk-main" data-screen-label={`Variante ${variant}`}>
        <MieterHeader mieter={mieter} filters={filters} />

        {variant !== "C" && <SummaryCards summary={summary} />}

        <FilterBar
          filters={filters}
          gruppieren={gruppieren}
          setGruppieren={setGruppierenBoth}
          showCats={showCats}
          setShowCats={setShowCatsBoth}
        />

        {variant === "A" && (
          <VariantA
            rows={rows}
            totalRow={totalRow}
            density={t.density}
            defaultCatsOpen={showCats || t.defaultCatsOpen}
            highlightOpen={t.highlightOpen}
          />
        )}
        {variant === "B" && <VariantB rows={rows} totalRow={totalRow} />}
        {variant === "C" && (
          <VariantC
            rows={rows}
            totalRow={totalRow}
            summary={summary}
            density={t.density}
          />
        )}
      </main>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Layout" />
        <TweakRadio label="Variante" value={t.variant}
          options={["A", "B", "C"]}
          onChange={(v) => setTweak("variant", v)} />
        <p style={{ margin: "0 0 4px", fontSize: 10.5, color: "rgba(41,38,27,.55)", lineHeight: 1.4 }}>
          A · klassischer Kontoauszug ·  B · Verlauf  ·  C · Dashboard
        </p>
        <TweakRadio label="Dichte" value={t.density}
          options={["compact", "regular", "comfy"]}
          onChange={(v) => setTweak("density", v)} />

        <TweakSection label="Inhalt" />
        <TweakToggle label="Kategorien immer offen" value={t.defaultCatsOpen}
          onChange={(v) => setTweak("defaultCatsOpen", v)} />
        <TweakToggle label="Offene Posten hervorheben" value={t.highlightOpen}
          onChange={(v) => setTweak("highlightOpen", v)} />

        <TweakSection label="Vorschau" />
        <TweakToggle label="Print-Modus (A4 quer)" value={t.printMode}
          onChange={(v) => setTweak("printMode", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
