# HV Serienbrief Editor — React Build

Vite-basierter React-Build des Serienbrief-Editor-Prototyps.

## Setup

```bash
cd src_react
npm install
```

## Development

```bash
npm run dev
```

Öffnet [http://localhost:5173](http://localhost:5173) mit Hot Module Reload.

## Production Build

```bash
npm run build
```

Output landet in `src_react/dist/`:

```
dist/
├── index.html                              # für standalone hosting
├── assets/
│   ├── serienbrief-editor.js               # bundled, minified JS (~250 KB gzipped)
│   └── serienbrief-editor.css              # bundled CSS
```

## Frappe Integration

1. **Build laufen lassen:**
   ```bash
   cd src_react && npm install && npm run build
   ```

2. **Dist-Files nach Frappe kopieren:**
   ```bash
   mkdir -p ../hausverwaltung/hausverwaltung/public/serienbrief_editor
   cp -r dist/assets/* ../hausverwaltung/hausverwaltung/public/serienbrief_editor/
   ```

3. **In `hausverwaltung/hooks.py` registrieren:**
   ```python
   app_include_js = [
       "/assets/hausverwaltung/serienbrief_editor/serienbrief-editor.js"
   ]
   app_include_css = [
       "/assets/hausverwaltung/serienbrief_editor/serienbrief-editor.css"
   ]
   ```

   Oder als dedicated Frappe Page (empfohlen — lädt nur auf der Editor-Seite):
   - Lege eine Page `serienbrief_editor` an
   - In `serienbrief_editor.js` mounte `<div id="root">` und require die Bundle-Files via `frappe.require()`

4. **Mock-Daten ersetzen:** Die Daten in `src/data.js` (`SAMPLE_RECIPIENTS`, `PLACEHOLDER_GROUPS`, `TEMPLATE_TREE`) durch echte `frappe.call(...)`-Aufrufe ersetzen.

5. **Editor-Engine:** Statt der statischen Block-Rendering React-Logik die existierende Quill-Instanz aus `serienbrief_vorlage.js` einbinden. Die Sidebar / Slash-Commander / Drag-and-Drop ruft Quill-API auf (`quill.insertEmbed`, `insertText`).

6. **Cache leeren nach Hooks-Änderung:**
   ```bash
   docker exec hausverwaltung_peters-backend-1 bench --site frontend clear-cache
   ```

## Struktur

```
src_react/src/
├── main.jsx                    # ReactDOM mount
├── App.jsx                     # Top-level shell
├── data.js                     # Mock-Daten (Recipients, Placeholders, Templates)
├── styles.css                  # All styles
└── components/
    ├── Icon.jsx                # Inline SVG icon set
    ├── Navigator.jsx           # Left template tree
    ├── Editor.jsx              # Center editor + toolbar + slash menu
    ├── Sidebar.jsx             # Right tabs (Preview/Placeholders/Bausteine/Variablen)
    ├── InlinePreview.jsx       # A4 paginated rendering helpers
    └── PdfMaximized.jsx        # Maximize overlay
```
