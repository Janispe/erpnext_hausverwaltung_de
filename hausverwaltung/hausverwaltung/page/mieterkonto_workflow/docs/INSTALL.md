# INSTALL — Schritt für Schritt

Annahmen:
- Du hast eine laufende Bench unter `~/frappe-bench/`
- Die App `hausverwaltung` ist installiert (`bench list-apps` zeigt sie)
- Du hast eine Test-Site (`dev.local` o.ä.) — **nicht** Produktion verwenden

Falls etwas davon nicht stimmt, sag Bescheid bevor du weitermachst.

---

## Schritt 1 · Dateien kopieren (Phase 1)

```bash
cd ~/frappe-bench/apps/hausverwaltung

# Frappe Pages — beide Pages anlegen
mkdir -p hausverwaltung/hausverwaltung/page/op_workflow
mkdir -p hausverwaltung/hausverwaltung/page/mieterkonto_workflow
cp /path/to/production-patch/op_workflow/*           hausverwaltung/hausverwaltung/page/op_workflow/
cp /path/to/production-patch/mieterkonto_workflow/*  hausverwaltung/hausverwaltung/page/mieterkonto_workflow/

# Public Assets — beide Pages teilen sich denselben Asset-Ordner
mkdir -p hausverwaltung/public/op_workflow
mkdir -p hausverwaltung/public/mieterkonto_workflow
cp /path/to/production-patch/public/*  hausverwaltung/public/op_workflow/
cp /path/to/production-patch/public/*  hausverwaltung/public/mieterkonto_workflow/
```

## Schritt 2 · App bauen

```bash
cd ~/frappe-bench

bench --site dev.local migrate
bench build --app hausverwaltung
bench --site dev.local clear-cache
```

## Schritt 3 · Aufrufen

Frappe-Desk öffnen, dann:

```
https://dev.local:8000/app/op-workflow
https://dev.local:8000/app/mieterkonto-workflow
```

oder über das Suchfeld in der ERPNext-Topbar: `Offene Posten (neu)` /
`Mieterkonto (neu)`.

Du solltest jetzt unsere UI **mit Mock-Daten** sehen, eingebettet in deine
ERPNext-Sidebar / Topbar.

---

## Optional · Esbuild-Build für Produktion

Während Phase 1+2 läuft die UI über Babel-Inline (`<script type="text/babel">`),
das ist im Browser ok aber langsam.

Für Phase 3 (Produktion) schließt du auf Esbuild um:

```bash
cd /path/to/production-patch/build
npm install      # einmalig — installiert esbuild als devDep
npm run build    # baut op-workflow.bundle.js → public/op_workflow/

# Dann in hausverwaltung/public/op_workflow/index.html
# die <script type="text/babel">-Tags durch <script src="op-workflow.bundle.js">
# ersetzen (Anleitung siehe build/README.md)
```

---

## Schritt 4 · Echte Daten · Phase 2

In `hausverwaltung/public/op_workflow/data-adapter.js`:

```javascript
const USE_MOCK_DATA = false;   // ← war: true
```

Page neu laden. Falls Console Errors zu Field-Names: siehe `data-adapter.js`
Kommentare oben → `adaptRow()` an dein echtes Report-Schema anpassen.

---

## Schritt 5 · Aktionen scharf schalten · Phase 3

In `hausverwaltung/public/op_workflow/action-handlers.js`:

```javascript
const USE_MOCK_ACTIONS = {
  dunning:           true,   // ← auf false setzen wenn echte Mahnungen laufen
  bulkDunning:       true,
  paymentEntry:      true,
  paymentAllocation: true,
  writeOff:          true,
};
```

Pro Aktion: erst auf der **Test-Site** durchspielen, dann erst Produktion.

Die Server-Side-Endpoints in `op_workflow.py` haben für jeden Action-Typ
bereits eine `@frappe.whitelist()`-Funktion. Du kommentierst den Body
schrittweise ein.

---

## Rollback

Page deinstallieren:

```bash
bench --site dev.local execute frappe.delete_doc --kwargs '{"doctype":"Page","name":"op-workflow"}'
rm -rf hausverwaltung/hausverwaltung/page/op_workflow
rm -rf hausverwaltung/public/op_workflow
bench build --app hausverwaltung
```

Es wurden **keine** existierenden Daten/Reports verändert. Der bestehende Script
Report `noch_offene_rechnungen_und_forderungen` bleibt unangetastet.
