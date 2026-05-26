# HV Bankimport — React-UI

Eigenständige React-UI für den Bankauszug-Import-Workflow (Phasen 1–4), eingebaut
nach dem **gleichen Muster wie der Serienbrief-Editor** (`../../HV_Serienbrief/src_react`):

- **Vite-Single-App-Build** → kopiert nach
  `hausverwaltung/public/bankimport_v2/` und von Frappe unter
  `/assets/hausverwaltung/bankimport_v2/` ausgeliefert.
- **Per `<iframe>` eingebettet** in die Frappe-Page
  `hausverwaltung/page/bankimport_v2`. Grund: das Prototyp-CSS nutzt globale
  `body`/`100vh`-Selektoren, die im Desk-DOM andere Seiten beeinflussen würden.
- **Keine eigene `frappe.call`** im iframe. Aktionen gehen per **postMessage-RPC**
  (`src/bridge.js`) an die Host-Page (`bankimport_v2.js`), die sie gegen eine
  feste Allowlist (`RPC_ACTIONS`) auf echte Backend-Methoden mappt.

## Backend-Anbindung

Es wird **keine Buchungslogik dupliziert**. Fast alle Aktionen rufen direkt die
bestehende, erprobte API in
`hausverwaltung/doctype/bankauszug_import/bankauszug_import.py` auf
(`parse_csv`, `create_bank_transactions`, `apply_party_to_row_and_relink`,
`get_open_invoices_for_row`, `manually_reconcile_row`,
`create_standalone_payment_for_row`, `create_journal_entry_for_row`,
Abschlagsplan- und Kreditraten-Aktionen …).

Nur der dünne Adapter `hausverwaltung/page/bankimport_v2/bankimport_v2.py`
ergänzt das, was es noch nicht gab:

| Endpoint | Zweck |
|---|---|
| `get_overview(import_name)` | Doc + Zeilen → UI-Shape (rows/importMeta/phaseCounts) |
| `list_imports()` | Import-Auswahl, wenn die Page ohne `?import=` geöffnet wird |
| `search_parties(party_type, txt)` | Autocomplete für die Phase-1-Zuordnung |
| `search_accounts(txt)` | Konto-Autocomplete (Wrapper auf `buchen_cockpit.autocomplete_konten`) |

Die Phasen-Ableitung pro Zeile (party → bank_transaction → voucher) spiegelt
`bankauszug_import._recompute_doc_status`.

## Entwicklung

```bash
npm install
HV_BASE=/ npm run dev          # Standalone mit Mock-Daten (src/data.js)
#   http://localhost:5174/?import=DEMO  → volles UI mit Mock-Übersicht
```

Standalone (kein Frappe-Eltern-Fenster) erkennt `bridge.isEmbedded() === false`
und `src/api.js` fällt auf die Mock-Daten zurück.

## Deploy

```bash
npm run build:frappe          # baut + kopiert nach public/bankimport_v2/ (+ Cache-Bust)
# danach im Backend-Container:
#   bench --site frontend migrate      # registriert die Page (einmalig)
#   bench --site frontend clear-cache
```

Die gebauten Assets unter `hausverwaltung/public/bankimport_v2/` werden
**mit committed** (wie beim Serienbrief).

## Erreichbar

- Direkt: `/app/bankimport_v2` (Import-Picker) oder `/app/bankimport_v2?import=<name>`
- Button **„Bankimport-Ansicht (Beta)"** im `Bankauszug Import`-Formular.
