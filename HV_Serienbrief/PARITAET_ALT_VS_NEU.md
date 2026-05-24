# Serienbrief-Editor — Feature-Abgleich: altes Formular vs. neuer React-Editor

Stand: 2026-05-21. Quelle alt: `doctype/serienbrief_vorlage/serienbrief_vorlage.js`
(2551 Z.), `serienbrief_vorlage_list.js` (237 Z.) + whitelisted Methoden in
`serienbrief_vorlage.py`. Quelle neu: `HV_Serienbrief/src_react/` + Page
`page/serienbrief_editor/`.

Legende: ✓ vorhanden · ◑ teilweise · ✗ fehlt

## A — Editor / Inhalt

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| A1 | Rich-Text-Editor | ◑ | alt: **Quill** (Frappe Text Editor), vergrößert. neu: `contenteditable`. Format-Fidelity ggü. Formular nicht garantiert. |
| A2 | Inline-Platzhalter als **Badges** (nicht editierbar) | ✓ | neu: Chips via `data-token` + `contenteditable=false`, Round-trip beim Speichern. |
| A3 | Platzhalter an Cursor einfügen | ✓ | `insertToken`. |
| A4 | **content_type umschalten** (Rich Text ↔ HTML+Jinja) | ✗ | neu zeigt nur `content`. `html_content`/`jinja_content` werden gespeichert, aber nicht editierbar/umschaltbar. |
| A5 | Editor-Zugriffsmodus nach Rolle (restricted Hausverwalter → content_type read-only, Tabelle versteckt) | ◑ | neu: nur `can_write` (write-Permission) → read-only. Keine Rollen-Feindifferenzierung. |
| A6 | Formatierungs-Toolbar (Fett/Kursiv/Listen/Ausrichtung/Link) | ✓ | via execCommand. |

## B — Platzhalter-Picker

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| B1 | Rekursiver Feld-**Baum** (Allgemein, Vorlagen-Variablen, Iterationsobjekt Tiefe 2, Referenz) | ✓ | **gerade erreicht** (`get_editor_placeholder_tree`). |
| B2 | Suche im Baum (filtert + expandiert) | ✓ | |
| B3 | Klick/Drag zum Einfügen | ✓ | |
| B4 | Snippets / Basis-Platzhalter-Buttons | ◑ | „Allgemein"-Gruppe (datum/datum_iso) da; alte Snippet-Schnellbuttons im Panel nicht 1:1. |

## C — Bausteine (Textbausteine)

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| C1 | Bausteine-Liste + Einfügen | ✓ | Sidebar-Tab. |
| C2 | **Inline `{{ baustein() }}` ↔ Tabelle `textbausteine` sync** | ✗ | alt: hält Child-Tabelle & Inhalt konsistent (Listen- vs Inline-Modus). neu: kein Sync. |
| C3 | **Position pro Baustein** (Vor/Nach Standardtext) + `content_position` | ✗ | |
| C4 | Tabellen-Sichtbarkeit nach Rolle | ✗ | |
| C5 | **Block-Anforderungen** (required fields pro Baustein, Spalte „anforderungen") | ✗ | via `get_template_requirements`. |
| C6 | **Mapping-Wizard** (Pfad-Zuordnung `pfad_zuordnung` + Variablen-Werte `variablen_werte` pro Baustein) | ✗ | mappt benötigte Referenz-Felder/Variablen. |

## D — Variablen

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| D1 | Variablen anzeigen | ✓ | Sidebar-Tab (read-only). |
| D2 | **Variablen anlegen/bearbeiten** (Dialog: Name/Typ/Label) | ✗ | |
| D3 | Variablen-Typen (template-value vs reference) | ✗ | |

## E — Vorschau

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| E1 | PDF-Vorschau (Split-Preview Beispielwerte + echter Empfänger) | ✓ | |
| E2 | Empfänger-Selektor | ✓ | echte Mietverträge, Suche. |
| E3 | Iterations-Doctype-Mismatch-Handling beim Empfänger | ◑ | neu lädt Empfänger nach haupt_verteil_objekt, aber kein expliziter Reset/Mismatch-Hinweis. |
| E4 | Live-Update beim Tippen (debounced) | ◑ | neu: Vorschau zeigt **gespeicherten** Stand; kein Live-Render der ungespeicherten Edits. |

## F — Aktionen

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| F1 | **„In Serienbrief laden"** (Durchlauf starten, `open_new_durchlauf_dialog`) | ✗ | Button im neuen UI vorhanden, **nicht verdrahtet**. |
| F2 | **„Vorlage kopieren"** (`copy_serienbrief_vorlage`) | ✗ | Button vorhanden, **nicht verdrahtet**. |
| F3 | Speichern | ✓ | |
| F4 | Titel / Kategorie / haupt_verteil_objekt bearbeiten | ◑ | Titel editierbar; Kategorie/haupt_verteil_objekt nicht im neuen UI änderbar. |

## G — Listenansicht (`serienbrief_vorlage_list.js`)

| # | Feature (alt) | neu | Anmerkung |
|---|---|---|---|
| G1 | Volltextsuche über alle Vorlagen (`search_serienbrief_vorlagen`) | ✗ | neu: nur Titel-Filter im Navigator-Baum. |
| G2 | Ordner/Kategorie-Verwaltung + Ordneransicht | ◑ | Navigator zeigt Kategorien; kein Anlegen/Verschieben. |

## H — Backend-Methoden (bereits vorhanden, wiederverwendbar)

`render_template_preview_pdf` ✓ genutzt · `copy_serienbrief_vorlage` (für F2) ·
`search_serienbrief_vorlagen` (für G1) · `get_template_requirements` (für C5/C6) ·
`render_template_preview_html`.

---

## Vorgeschlagene Reihenfolge (Aufwand/Wert)

1. **F1 + F2 — Aktionen verdrahten** (klein, hoher Wert; Backend existiert).
2. **D2/D3 — Variablen bearbeiten** (klein-mittel).
3. **C2/C3 — Baustein-Tabellen-Sync + Positionen** (mittel; Kernlogik der Vorlage).
4. **C5/C6 — Anforderungen + Mapping-Wizard** (mittel-groß; Backend existiert).
5. **A4 — content_type-Umschaltung + HTML/Jinja-Editing** (mittel).
6. **G1 — Volltextsuche** (klein; Backend existiert).
7. **E4 — Live-Vorschau ungespeicherter Edits** (mittel; Risiko Render unsaved).
8. **A1 — Quill statt contenteditable** (groß, riskant; nur wenn Format-Parität nötig).
