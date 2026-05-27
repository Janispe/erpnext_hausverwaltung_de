# Phasen-Plan

Detaillierte Reihenfolge, was wann tun, mit Verifikations-Checks pro Schritt.

---

## Phase 1 · Demo (~30 Min)

### Schritt 1a · Installation
Siehe `INSTALL.md` Schritt 1–3.

**Verifikation:**
- Frappe-Desk öffnen
- Suchfeld → "Offene Posten (neu)"
- Page lädt, Tabelle zeigt Mock-Daten (Sandra Hofmann, Familie Albrecht, …)
- Mahn-Banner oben mit "6 Posten mahnreif"
- Tweaks-Panel rechts unten erreichbar

### Schritt 1b · Team-Walkthrough
- Zeig den OP-Workflow mit Mode-Switch (Forderungen/Rechnungen/Beides)
- Zeig die Aging-Heatmap im Stats-Strip
- Zeig "Sammelmahnung erstellen" — Bulk-Dialog
- **Sammle Feedback bevor du Phase 2 startest**

---

## Phase 2 · Echte Daten (~1 Tag)

### Schritt 2a · Reports-Schema verifizieren

```bash
bench --site dev.local execute hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.noch_offene_rechnungen_und_forderungen.execute --kwargs '{"filters":{"company":"Deine Firma GmbH","mode":"Forderungen"}}'
```

Schau dir die Felder im Output an. Aktuell erwartet `data-adapter.js`:
```
art, party, buchungsdatum, faellig_am, belegart, belegnummer,
rechnungsbetrag, bezahlt, offen, party_account, kostenstelle,
bemerkungen, status, zahlungsrichtung, alter_tage, can_write_off
```

Wenn ein Feld fehlt oder anders heißt → `adaptRow()` in `data-adapter.js` anpassen.

### Schritt 2b · `mahnstufe` ermitteln

Im Mockup hat jede Zeile ein `mahnstufe`-Feld. In deinem echten Report gibt es das
*noch nicht*. Zwei Wege:

**Option A · Server-Script (empfohlen):**
Custom-Field `mahnstufe` auf Sales Invoice (Int). Ein DocEvent auf "Dunning"
(after_insert) zählt das Feld auf der referenzierten Invoice hoch.

**Option B · Live-Berechnung im Report:**
In `noch_offene_rechnungen_und_forderungen.py`, in `_map_row()`:
```python
dunning_count = frappe.db.count("Dunning", filters={
    "sales_invoice": row.get("belegnummer"),
    "docstatus": 1,
})
row["mahnstufe"] = dunning_count
```
Langsamer, aber kein Schema-Change nötig.

**Wenn keine Mahnungen genutzt werden**: `data-adapter.js` einfach `mahnstufe = 0`
zurückgeben lassen. Der Mahn-Banner zeigt dann jede überfällige Forderung als M1-fällig.

### Schritt 2c · Flag flippen + Test

```javascript
// data-adapter.js
const USE_MOCK_DATA = false;
```

Page neu laden. Wenn Console errors: `adaptRow()` debuggen.

### Schritt 2d · Verifikation
- Echte Mieter erscheinen
- Echte Saldi
- Aging-Buckets stimmen mit deinem Wissen überein
- Aktionen sind noch Toast (das ist gewollt — Phase 3 macht das scharf)

---

## Phase 3 · Aktionen scharf schalten

### Schritt 3a · Dunning Types konfigurieren

In ERPNext:

1. Desk → "Dunning Type" anlegen
2. Drei Types: "Zahlungserinnerung Stufe 1", "Mahnung Stufe 2", "Letzte Mahnung Stufe 3"
3. Pro Type setzen:
   - **Mahngebühr** (5 / 10 / 20 €)
   - **Verzugszinsen** (9.12% p.a.)
   - **Letterhead** (falls vorhanden)
   - **Auto-mail** (optional)

### Schritt 3b · Einzelmahnung scharf schalten

```javascript
// action-handlers.js
const USE_MOCK_ACTIONS = {
  ...,
  dunning: false,   // ← scharf
};
```

Dann in `op_workflow.py`, in `create_dunning()`:
- Den auskommentierten Body entkommentieren
- Test auf Test-Site: 1 Mahnung erstellen, in Desk prüfen ob Dunning-Doc + JE entstanden
- Dann erst Produktion

### Schritt 3c · Restliche Aktionen analog
Pro Aktion: Flag flippen → Body in `op_workflow.py` entkommentieren → testen.

Reihenfolge nach Risiko:
1. `dunning` (ein Doc, leicht zurückzunehmen)
2. `bulkDunning` (mehrere Docs)
3. `paymentAllocation` (Bestehende Belege werden verknüpft, keine neuen Buchungen)
4. `paymentEntry` (echtes Geld bewegt — Skonto-Logik genau testen)
5. `writeOff` (immutable — am Schluss)

### Schritt 3d · Custom-Field für Stundungen

"Stundung vereinbaren" aus dem Overflow-Menü gibt es in ERPNext-Standard nicht.
Empfehlung:
- Custom-Field `stundung_bis` (Date) auf Sales Invoice
- Custom-Field `stundung_grund` (Small Text)
- In `op_workflow.py` → `set_stundung()` Funktion
- In der Aging-Logik werden Posten mit `stundung_bis > today` aus dem Mahn-Banner ausgeschlossen
