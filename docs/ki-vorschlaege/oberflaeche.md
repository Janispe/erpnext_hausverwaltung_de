# KI-Vorschläge: Prüfer-Oberfläche „Pakete mit Graph“

Stand 17.11.2026. Ersetzt die Pilot-Seite `hausverwaltung/hv_proposals/page/hv_proposals/hv_proposals.js`.
Setzt die Backend-Änderungen aus [backend.md](backend.md) voraus.

Vorlage ist der Design-Canvas „KI-Vorschläge Inbox“, Variante B (Artboards B1 und B2). Das Markup liegt als
Referenz in [mockup/](mockup/), siehe [README.md](README.md). Alle Namen und Beträge dort sind fiktiv.

## Technik

- **Desk-Seite** `hv-proposals` (bleibt). Die Page-JS bleibt dünn wie bei `buchungs_inbox`. Die Logik kommt
  in ein UI-Modul `hausverwaltung/public/js/hv_proposals.js` mit `frappe.provide("hausverwaltung.hv_proposals")`.
- **Kein React, kein eigener Build.**
- **Styles:**
  - `hv-tokens.css` und `hv-components.css` sind über `app_include_css` schon global geladen. Für Buttons,
    Reiter, Pills und Felder `hv-btn`, `hv-btn-primary`, `hv-btn-danger`, `hv-tabs`/`hv-tab`, `hv-pill` und
    `hv-field` nutzen.
  - Seiteneigene Styles nur für Graph, Knoten, Kanten und Detail, mit Präfix `hv-prop-`.
  - Farben als CSS-Variablen mit Frappe-Variable und Fallback, damit Dark Mode funktioniert.
- **Frappe-Bausteine:**
  - `frappe.ui.make_app_page`
  - `frappe.call` mit `type: "POST"`
  - `frappe.ui.Dialog` für Ablehnungsgrund und Bestätigung der Sammelfreigabe
  - `frappe.show_alert` für Rückmeldungen
  - `frappe.utils.get_form_link` für „Dokument öffnen“
  - `frappe.datetime` für Zeiten, `frappe.user.full_name` für Namen
- **Routen:**
  - `/app/hv-proposals` zeigt die Paketliste.
  - `/app/hv-proposals/<package>` zeigt die Paketansicht.
  - `?vorschlag=<id>` wählt einen Knoten vor.
- **Optik:** Desk-Schrift und Desk-Farben über die hv-Tokens. Der Canvas zeigt die Knoten in der
  Process-Engine-Optik mit Manrope; hier die Form übernehmen, die Schrift nicht nachladen.

## Statusnamen und Symbole

| Backend | Anzeige | Symbol | Farbe (Richtung) |
|---|---|---|---|
| Pending | Prüfung offen | ▶ | Blau |
| Approved | Freigegeben | ◐ | Ocker |
| Succeeded | Ausgeführt | ✓ | Grün |
| Stale | Veraltet | ! | Rot |
| Rejected | Abgelehnt | / | Grau, Titel durchgestrichen |

Alle Texte auf Deutsch, keine Emojis. Farben dürfen sich nicht nur im Farbton unterscheiden; Symbol und
Text tragen die Bedeutung mit.

## Ansicht 1: Paketliste (Artboard B1)

- **Reiter** mit Anzahl: Offen · Wartet auf Ausführung · Abgeschlossen · Alle. Dazu ein Filter „Agent“.
- **Spalten:**
  - **Paket:** Titel; darunter eine Pill zur Art und der Bezug. Die Pill zeigt „Graph · n {lane_label}“,
    „ohne Abhängigkeiten“ oder „Einzelvorschlag“.
  - **Agent**
  - **Umfang:** „n Vorschläge“
  - **Stand:** Balken nach Status, darunter die Zahlen, z. B. „26 offen · 5 freigegeben · 3 ausgeführt“
  - **Nächster Schritt:** Primärbutton „n prüfen →“, sonst „n ausführen“, bei abgeschlossenen Paketen nur
    Text „Abgeschlossen“
  - **Eingang:** relativ, z. B. „vor 12 Min.“, „heute 09:02“, „15.11.“
- **Klick auf die Zeile oder den Button** öffnet die Paketansicht.
  - Pakete ohne Kanten öffnen direkt in der Listenansicht.
  - Einzelvorschläge zeigen nur das Detail.
- **Leerer Zustand:** „Keine Pakete in diesem Status.“

## Ansicht 2: Paketansicht (Artboard B2)

### Kopf

- Label „Paket · Graph mit n Zeilen“, darunter der Titel.
- Eine Zeile mit Agent, Anlass, Eingang und „n Vorschläge in m {lane_label}“.
- Statusbalken mit Legende.
- Umschalter **Graph | Liste**.
- **Offene freigeben …** (sekundär):
  - öffnet einen Dialog mit der Anzahl und dem Hinweis „Jede Freigabe wird einzeln für ihre Revision und
    ihren Hash protokolliert. Veraltete und abgelehnte Vorschläge bleiben unverändert. Ausgeführt wird erst
    mit ‚Freigegebene ausführen‘.“
  - sendet genau die angezeigten Bindungen an `review_many`.
  - Nur für Prüfer sichtbar.
- **Freigegebene ausführen (n)** (primär, bei 0 deaktiviert):
  - sendet die angezeigten freigegebenen Bindungen an `execute_ready`.
  - Rückmeldung: „n in Reihenfolge ausgeführt · m warten auf Vorgänger“.
  - Bei einem Fehler: Meldung zeigen und den betroffenen Knoten auswählen.

### Graph

- **Layout aus `package_graph`:**
  - Spalten nach `column`, Zeilen nach `lane.key`.
  - Knoten ohne `lane` (z. B. die Wurzel) stehen links und vertikal mittig.
  - Über jeder Zeile steht `lane.label`.
  - Die Wurzel verbindet sich über eine senkrechte Sammelleitung mit dem ersten Knoten jeder Zeile.
- **Ohne `lane`-Werte** (allgemeiner Graph): Spalten nach `column`, Knoten untereinander; Kanten dürfen als
  SVG-Overlay gezeichnet werden.
- **Knoten (200 × 84 px):**
  - links eine 4-px-Statusleiste
  - Kopf: Symbol-Kachel, Kurztitel (`title`, gekürzt mit „…“), darunter die ID in Monospace
  - Fuß: `summary` in Monospace und das Statuslabel
  - ausgewählt: Akzentrahmen; „Veraltet“: gestrichelter Rand; „Abgelehnt“: Titel durchgestrichen
  - echte `<button>` mit `aria-label` „ID Titel, Status“
- **Kanten:** durchgezogen, wenn der Vorgänger ausgeführt ist (`satisfied`), sonst gestrichelt. Die Legende
  oben erklärt beides.
- **Große Pakete:** Ab 6 Zeilen werden die übrigen eingeklappt: „n weitere {lane_label} · Zahlen nach
  Status“. Ein Klick klappt sie auf.
- Der Graph-Bereich scrollt waagerecht, wenn er nicht passt.

### Liste

Tabelle mit Zeile | Schritt (Titel + ID) | Änderung | Status. Ein Klick wählt den Vorschlag aus.

### Detail (rechte Spalte, 360–460 px; unter 1100 px Breite unter dem Graph)

1. **Kopf:**
   - Objektart als Label und Status-Pill
   - Kurztitel
   - Bezeichnung des Zieldokuments (`target.label`) mit Link
   - ID · Revision · Hash (gekürzt) · Position, z. B. „Zeile MV-0182 · Schritt 2 von 3“
2. **Statushinweis:**
   - Freigegeben: „von … am …, gilt nur für Revision n“
   - Veraltet: Ursache aus `stale_cause`, als Satz formuliert
   - Ausgeführt: Zeitpunkt, Ergebnis und „Dokument öffnen →“
   - Abgelehnt: von, am, Begründung
3. **Änderung:** Tabelle Feld | Bisher | Neu aus `changes`. Text-Änderungen mit `segments` als gestrichen/neu.
4. **Begründung des Agenten:** `rationale` kursiv; darunter `sources`, mit Link, wenn `doctype`/`name` da sind.
5. **Im Graph:**
   - Vorgänger und Nachfolger, jeweils anklickbar und mit Status
   - wenn Ausführen blockiert ist: „Ausführen erst, wenn alle Vorgänger ausgeführt sind. Freigeben geht
     schon jetzt.“
6. **Beim Ausführen:** `effects` als Liste.
7. **Aktionen** (Tabelle unten).
8. **Verlauf:** `audit` als Zeitleiste mit Titel, Akteur (Anzeigename), Zeit und Notiz.

Optional ein eingeklappter Bereich „Technische Details“ mit vollem Hash und `limits`. Kein rohes JSON in der
Hauptansicht.

### Aktionen je Status

| Status | Hauptaktion | Weitere | Hinweis |
|---|---|---|---|
| Prüfung offen | „Revision n freigeben“ | „Ablehnen …“: Dialog, Grund ist Pflicht | „Ablehnen macht alle Nachfolger veraltet.“ |
| Freigegeben | „Ausführen“, deaktiviert bei offenen Vorgängern; dann Grund nennen und Sprung zum Vorgänger anbieten | — | „Speichert über die normale Frappe-Validierung.“ |
| Veraltet | „Neue Revision anfordern“ (`request_revision`) | — | Ursache steht oben |
| Ausgeführt | — | „Dokument öffnen →“ | — |
| Abgelehnt | — | — | Begründung steht oben |

- Freigeben, Ablehnen und Sammelfreigabe gibt es nur für `HV Proposal Reviewer` ohne `HV Proposal Agent`.
  Alle anderen sehen statt der Buttons den Hinweis „Nur Prüfer können freigeben.“
- Ausführen erfordert eine vorhandene menschliche Freigabe. Wer ausführen darf, regelt das Backend.

### Tastatur

- J/K: nächster/vorheriger Knoten in Graph-Reihenfolge
- A: freigeben, R: ablehnen, E: ausführen
- Nur wenn der Fokus in der Seite liegt und nicht in einem Eingabefeld. Kein globaler Handler, der Desk-
  Kürzel stört.

### Fehler

- Rechtefehler vom Server („Proposal operation unavailable“) als „Vorgang nicht verfügbar“ zeigen.
- HTTP 409 (`ConcurrentRevisionRetry`): „Die Daten haben sich gleichzeitig geändert. Bitte erneut
  versuchen.“ Danach die Ansicht neu laden.
- Elemente aus `review_many` oder `execute_ready` mit `ok: false` werden mit ihrem Grund aufgelistet.

## Entfällt gegenüber dem Pilot

- Das Eingabeformular für Agenten (Ziel, Bezeichnung, Paket). Agenten reichen über die API ein.
- Die Vorgängerauswahl als JSON und die rohen JSON-Details.
- Die gleichrangige Button-Leiste unabhängig vom Status.

## Abnahme

- Playwright (`tests/proposals_playwright_e2e.py`) mit getrennten Logins für Prüfer und Agent, wie bisher:
  1. Paketliste → Paket öffnen → Knoten wählen
  2. freigeben → in Reihenfolge ausführen
  3. ablehnen mit Grund → Nachfolger werden „Veraltet“
  4. Sammelfreigabe
  5. Liste umschalten
- Screenshots beider Ansichten in hell und dunkel im PR.
- Bei 1440 px Breite und eingeklapptem Desk-Seitenmenü passt der Graph des synthetischen Pakets (Wurzel +
  3 Zeilen × 3 Schritte) ohne waagerechtes Scrollen. Bei offenem Seitenmenü darf er waagerecht scrollen;
  Knoten (200 px) und Detail (360 px) werden dafür nicht verkleinert. Unter 1100 px steht das Detail unter
  dem Graph.
