# HV Serienbrief — React Builds (Editor · Browser · Durchlauf)

Vite-Monorepo mit drei React-Apps, die sich Icons + Base-Styles teilen:

| App | Entry | Bundle |
|---|---|---|
| **Editor** (TipTap) | `index.html` → `src/main.jsx` | `serienbrief-editor.{js,css}` |
| **Vorlagen-Browser** | `browser.html` → `src/browser/main.jsx` | `serienbrief-browser.{js,css}` |
| **Serienbrief Durchlauf** | `durchlauf.html` → `src/durchlauf/main.jsx` | `serienbrief-durchlauf.{js,css}` |

## Geteilte Files

- `src/components/Icon.jsx` — Inline-SVG-Icon-Set, von allen drei genutzt
- `src/shared/base.css` — Design-Tokens (CSS-Variablen), `body`, `.btn`, `.kbd`, Modal-Styles
  - Wird von Browser + Durchlauf per `@import "../shared/base.css"` eingebunden
  - Der Editor (`src/styles.css`) bringt seine Base-Styles inline mit; falls du sie irgendwann harmonisieren willst, könnte `src/styles.css` ebenfalls `@import "./shared/base.css"` benutzen und die Duplikate dort rausnehmen

## Setup

```bash
npm install
```

## Development

```bash
npm run dev               # öffnet alle Entries (Vite listet sie)
npm run dev:editor        # nur Editor
npm run dev:browser       # nur Browser
npm run dev:durchlauf     # nur Durchlauf
```

## Production-Build

```bash
npm run build             # baut alle 3 Apps in dist/
```

Output:
```
dist/
├── index.html                              # Editor entry HTML
├── browser.html                            # Browser entry HTML
├── durchlauf.html                          # Durchlauf entry HTML
└── assets/
    ├── serienbrief-editor.js               # Editor bundle
    ├── serienbrief-editor.css
    ├── serienbrief-browser.js              # Browser bundle
    ├── serienbrief-browser.css
    ├── serienbrief-durchlauf.js            # Durchlauf bundle
    ├── serienbrief-durchlauf.css
    └── chunk-*.js                          # shared chunks (React, etc.)
```

Optional einzeln bauen mit korrektem Frappe-Asset-Prefix:
```bash
npm run build:editor       # base=/assets/hausverwaltung/serienbrief_editor/
npm run build:browser      # base=/assets/hausverwaltung/serienbrief_browser/
npm run build:durchlauf    # base=/assets/hausverwaltung/serienbrief_durchlauf/
```

## Frappe-Integration

Für jede App eine eigene Frappe-Page anlegen, analog zu `serienbrief_editor.js`:

```
hausverwaltung/hausverwaltung/page/
├── serienbrief_editor/          # existiert
├── serienbrief_browser/         # NEU
└── serienbrief_durchlauf/       # NEU
```

Jede Page-`.js` lädt den Build per `<iframe src="/assets/hausverwaltung/<asset_name>/<entry>.html">`.
Die RPC-Bridge (postMessage-Allowlist) kann von `serienbrief_editor.js` 1:1 abgekupfert werden,
nur die `RPC_ACTIONS`-Liste muss pro Page passend angepasst werden.

Falls du je einen Build separat deployen willst:

1. Bauen mit dem passenden Asset-Prefix:
   ```bash
   HV_APP=browser npm run build
   ```
2. Nur die App-eigenen Files kopieren:
   ```bash
   mkdir -p ../hausverwaltung/hausverwaltung/public/serienbrief_browser
   cp dist/browser.html ../hausverwaltung/hausverwaltung/public/serienbrief_browser/index.html
   cp -r dist/assets ../hausverwaltung/hausverwaltung/public/serienbrief_browser/
   ```

Oder das mitgelieferte `scripts/copy-to-frappe.mjs` erweitern, damit es alle drei Apps automatisch deployt.

## Mock-Daten ersetzen

Browser + Durchlauf benutzen aktuell Mock-Daten:

- `src/browser/data.js` — `BROWSER_FOLDERS`, `BROWSER_TEMPLATES`
- `src/durchlauf/data.js` — `DURCHLAUF`, `RECIPIENTS`

Im Frappe-Build werden diese durch `frappe.call`-Aufrufe ersetzt (postMessage-RPC analog zum Editor — siehe `src/api.js` + `src/bridge.js`).
