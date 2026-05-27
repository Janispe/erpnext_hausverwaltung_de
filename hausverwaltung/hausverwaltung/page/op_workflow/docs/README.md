# Production Patch — Offene Posten Workflow

Komplettes Paket, um die designte UI als **Frappe Page** in deine existierende
`erpnext_hausverwaltung_de`-App einzubauen.

Drei Phasen — jede für sich lauffähig, du gehst in deinem Tempo weiter.

---

## Phase 1 · Demo-Seite mit Mock-Daten · ~30 Minuten · null Risiko

Ziel: Die UI läuft als eigene Seite **innerhalb deines ERPNext** mit der bestehenden
Navigation, aber mit Mock-Daten (wie hier im Studio). Du kannst sie deinem Team
zeigen, bekommst Feedback, gehst aber an keine echten Buchungen ran.

**Was du tust:**
1. Dateien aus `production-patch/` in deinen App-Source kopieren
2. `bench build` + `bench migrate`
3. Browser öffnen: `https://<dein-erpnext>/app/op-workflow`

**Details siehe** `INSTALL.md` Schritt 1.

---

## Phase 2 · Echte Daten · ~1 Tag

Ziel: Die Mock-Daten in `data-adapter.js` ersetzt durch echte Calls zur bestehenden
`noch_offene_rechnungen_und_forderungen.execute()`-Funktion. Du sieht echte Mieter,
echte Posten, echte Salden. Aktion-Buttons bleiben Toast (noch nicht scharf).

**Was du tust:**
1. In `data-adapter.js` Flag `USE_MOCK_DATA = false` setzen
2. Falls deine Field-Namen im Report abweichen → Mapping in `adaptRow()` anpassen
3. Page neu laden

Die Skeleton-Logik dafür ist **schon drin** — du musst nur den Flag flippen und
ggf. Feldnamen angleichen.

---

## Phase 3 · Aktionen scharf schalten · 2–5 Tage

Ziel: Die Action-Buttons (Mahnung erstellen, Zahlung anlegen, Vorauszahlung zuordnen,
Abschreiben) erzeugen jetzt echte ERPNext-Dokumente.

**Was du tust:**
Jede Aktion einzeln in `action-handlers.js` von `MOCK` auf den echten Frappe-Call
umstellen. Du kannst Aktion für Aktion live schalten, der Rest bleibt im Toast-Modus.

Die Endpoints sind in `op_workflow.py` schon als `@frappe.whitelist()`-Funktionen
ausgeschrieben — du musst nur die Logik darin einkommentieren.

**Konkret pro Aktion:**

| Aktion | Endpoint (Frappe-Methode) | Status im Patch |
|---|---|---|
| Mahnung erstellen | `op_workflow.api.create_dunning` | Skeleton vorhanden, Body kommentiert |
| Sammelmahnung | `op_workflow.api.create_bulk_dunning` | Skeleton vorhanden |
| Zahlung anlegen (mit Skonto) | `op_workflow.api.create_payment_entry` | Skeleton vorhanden |
| Vorauszahlung zuordnen | `op_workflow.api.allocate_payment` | Skeleton vorhanden |
| Abschreiben | `op_workflow.api.write_off_invoice` | Skeleton vorhanden |
| → Mieterkonto öffnen | (clientseitig: `frappe.set_route`) | Funktioniert sofort |
| → Beleg öffnen | (clientseitig: `frappe.set_route`) | Funktioniert sofort |

---

## Datei-Struktur des Patches

```
production-patch/
├── README.md                       ← bist du hier
├── INSTALL.md                      ← Concrete bench-Befehle
├── PHASES.md                       ← Was wann tun, Reihenfolge
│
├── op_workflow/                    ← Frappe Page (Backend-Side)
│   ├── __init__.py
│   ├── op_workflow.json            ← Page-Metadaten
│   ├── op_workflow.py              ← Whitelist-API
│   └── op_workflow.js              ← Page-Bootstrap (Frappe-Hook)
│
├── public/                         ← Frontend-Bundle-Quellen
│   ├── data-adapter.js             ← Mock ↔ Real toggle
│   ├── action-handlers.js          ← Mock ↔ Real toggle pro Aktion
│   └── (siehe build/install_react.sh)
│
└── build/
    ├── package.json                ← devDeps: esbuild
    ├── esbuild.config.mjs          ← Bundle-Setup
    └── install_react.sh            ← Kopiert die React-Files in public/
```

Die eigentlichen React-Komponenten (`op-app.jsx`, `op-actions.jsx`, …) liegen
**direkt in `production-patch/public/`** — du nimmst den ganzen Ordner und es ist alles drin.

Wenn du sie später hier im Studio weiterentwickelst und in den Patch
zurückspielen willst: `build/install_react.sh` macht das in einem Schritt.

---

## Was du *nicht* dafür brauchst

- **Keine neue DocType-Definition.** Die Page liest aus existierenden Sales Invoices,
  Payment Entries, Journal Entries. Es wird *nichts* an deinem Datenmodell geändert.
- **Keine Migration.** `bench migrate` wegen der Frappe-Page-Definition reicht.
- **Kein neuer Service.** Läuft im selben Frappe-Worker wie der Rest.
- **Keine Frontend-Frameworks installieren.** React kommt als CDN-Script, esbuild
  ist optional und nur für Produktion empfohlen.

---

## Was du *vor* der Live-Schaltung brauchst

1. **Dunning Types** in ERPNext konfigurieren (Stufe 1, 2, 3 mit Gebühren und
   Verzugszinsen). Siehe `PHASES.md` § Phase 3a.
2. **Custom Field** `mahnstufe` auf Sales Invoice (Int, 0–3). Wird beim Erstellen
   einer Dunning automatisch hochgezählt — kleiner Server-Script-Trigger.
3. **Test-Site** für Phase 3 — *nie* gleich auf Produktion.

---

## Support

Wenn dein Field-Mapping vom Mockup abweicht (z. B. heißt bei dir `mieter` statt
`party`), liefer ich dir mit dem Output von

```bash
bench --site dev.local execute hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.noch_offene_rechnungen_und_forderungen.execute --kwargs '{"filters":{"company":"Hausverwaltung Müller GmbH","mode":"Forderungen"}}'
```

das passende `adaptRow()` zurück.
