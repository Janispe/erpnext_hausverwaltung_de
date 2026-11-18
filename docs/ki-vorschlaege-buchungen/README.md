# KI-Buchungsvorschläge: Übergabe

Stand 18.11.2026, überarbeitet nach dem Review von Auftrag 1. Design für KI-Vorschläge im Buchungssystem.
Ein Agent schlägt für die Zeilen eines Kontoauszugs Zuordnungen und Buchungen vor. Die Vorschläge erscheinen
**direkt im Bankimport an der Zeile** und **zusätzlich auf der Vorschläge-Seite** (`/app/hv-proposals`) als
Paket. Später kommen **Regelvorschläge** aus wiederkehrenden Mustern dazu, ohne KI.

Grundlage ist der Vorschlags-Kern aus PR #44–#46 (`hausverwaltung/proposals/`, Seite `hv-proposals`), der in
`main` liegt. Die Umsetzung erfolgt in Orchestrator.inc.

| Datei | Inhalt |
|---|---|
| [oberflaeche.md](oberflaeche.md) | Teil A Bankimport, Teil B Vorschläge-Seite, Teil C Regelvorschläge im Regel-Fenster |
| [schnittstelle.md](schnittstelle.md) | Datenform, die die Oberfläche erwartet, und Skizze fürs spätere Backend |
| [issues.md](issues.md) | Aufträge für Orchestrator.inc, mit Abnahme |
| [mockup/](mockup/) | Referenz-Markup aus dem Design-Canvas |
| [screenshots/](screenshots/) | Stand von Auftrag 1 (PR #51), vor der Überarbeitung |

## Entscheidungen (Janis, 18.11.2026)

1. **Übernehmen im Bankimport ist ein Klick.** „Übernehmen & buchen“ gibt den Vorschlag frei und führt ihn
   sofort aus. Freigabe und Ausführung stehen trotzdem als zwei Ereignisse im Prüfprotokoll, gebunden an
   Revision und Hash.
2. **Orte:** Die bestehende Bankimport-Seite (`/app/bankimport_v2`) wird verändert. Die Vorschläge-Seite zeigt
   dieselben Vorschläge zusätzlich als Paket. Buchungs-Inbox und Buchen-Cockpit bleiben unverändert.
3. **Design-System:** „Hausverwaltung Design System“. Im Bankimport gelten dessen Bankimport-Klassen und
   Tokens, auf der Vorschläge-Seite `hv-tokens.css` und `hv-components.css`.
4. **Reihenfolge:** zuerst die Oberfläche mit Mock-Daten, das Backend später.

### Nach dem Review von Auftrag 1

5. **Kompakte Vorschlagskarte.** Art, Schritte mit Ziel und Betrag, Sicherheit und Aktionen sind immer
   sichtbar. Buchungsvorschau, Begründung und Belege klappt „Details“ auf. Bei mittlerer und niedriger
   Sicherheit sind die Details von Anfang an offen, weil ein Klick echt bucht.
6. **Sicherheit nur als Stufe** hoch, mittel, niedrig. Keine Prozentzahl, auch wenn der Agent eine liefert.
7. **Auslöser:** Der Agent startet automatisch nach dem CSV-Import. Je Zeile gibt es „Erneut anfordern“ bei
   „Kein Vorschlag“ und „Neue Revision anfordern“ bei „Veraltet“.
8. **Anpassen und abweichend buchen:** Das Backend schließt den Vorschlag als „Abgelehnt“ mit der Kategorie
   „Angepasst gebucht“ und dem Grund „Angepasst gebucht: <Beleg>“. Kein neuer Status im Kern.
9. **Schmale Ansicht:** Unter 1100 px scrollt ein Zeilenwechsel das Panel ins Bild, und Enter bucht nur bei
   sichtbarer Karte. Unter 760 px zeigt die Zeile eine KI-Marke mit Sicherheitsbalken.
10. **Regelvorschläge** kommen aus einer Mustersuche ohne KI und erscheinen nur im Regel-Fenster des
    Bankimports, nicht auf der Vorschläge-Seite. Schwellen, Laufzeit und Mietvertragsbindung legt der
    Backend-Plan von Auftrag 3 fest.

## Grundsätze

- **Eine Datenhaltung.** Jeder Buchungsvorschlag ist ein `HV Action Proposal` im bestehenden Kern. Der
  Bankimport liest dieselben Datensätze wie die Vorschläge-Seite. Es gibt keine zweite Tabelle und kein Feld
  an der Importzeile, das einen Vorschlag kopiert.
- **Keine neue Buchungslogik.** Ausführen ruft dieselben Funktionen in
  `hausverwaltung/hausverwaltung/doctype/bankauszug_import/bankauszug_import.py` auf, die heute die Knöpfe im
  Bankimport nutzen.
- **Der Agent bucht nie selbst.** Er reicht nur ein. Freigeben darf nur ein Mensch mit
  `HV Proposal Reviewer` ohne `HV Proposal Agent`, wie im Kern.
- **Lieber kein Vorschlag als ein geratener.** Bei Mehrdeutigkeit enthält sich der Agent und sagt warum
  (Zustand „Kein Vorschlag“).
- **Domäneninvariante aus `AGENTS.md`:** Ein Customer gehört genau einem Mietvertrag. Ein Parteivorschlag
  nennt den exakten Mietvertrag. Gibt es mehrere passende Mietverträge, enthält sich der Agent.

## Ablauf

1. **Auftrag 1 – Oberfläche im Bankimport** mit Mock-Daten in `HV_Bankimport/src_react`. Erledigt mit PR #51.
   Ohne Backend bleibt alles KI-Bezogene unsichtbar, die Seite verhält sich wie heute.
2. **Auftrag 1b – Überarbeitung nach dem Review** (Entscheidungen 5–9), weiterhin nur Oberfläche mit
   Mock-Daten.
3. **Auftrag 2 – Backend und Vorschläge-Seite:** Buchungsaktionen im Kern, Lese- und Übernahme-Endpunkte,
   Ergänzungen in `hv_proposals.js`. Erst nach Janis' Freigabe von Auftrag 1b.
4. **Auftrag 3 – Regelvorschläge** im Regel-Fenster (Teil C). Ohne KI, nach Auftrag 2.
5. **Später:** der Agent, der die Vorschläge erzeugt, mit dem automatischen Start nach dem Import. Nicht Teil
   dieser Unterlagen.

Merge durch Janis. Tests in einem isolierten Stack, nicht auf der Dev-Site 8090.

## Vorgaben für Auftrag 1 aus dem Design-Review

- Frappe reicht `row` aus dem Zeilenlink ans Bankimport-iframe weiter.
- Der Betrag bleibt bei schmaler Ansicht in der Tabellenzeile sichtbar.
- Die Sammelauswahl startet leer. „Hohe Sicherheit“ markiert die passenden Zeilen auf Klick.

## Zum Mockup-Format

Die Dateien in `mockup/` stammen aus dem Design-Canvas und laufen nicht direkt im Browser:

- `{{ … }}` sind Platzhalter, `<sc-for>` und `<sc-if>` Schleifen und Bedingungen, `<dc-import>` bindet eine
  andere Datei als Komponente ein (`Matchpanel.dc.html`).
- Die Zustandslogik steht im `<script type="text/x-dc">` am Ende.
- `ds/hausverwaltung/…` verweist auf die Stylesheets des Design-Systems. Im Repo entsprechen ihnen
  `HV_Bankimport/src_react/src/styles/*.css` (Bankimport) und `hausverwaltung/public/css/hv-tokens.css`,
  `hv-components.css` (Vorschläge-Seite).

Die Exporte zeigen Aufbau, Texte und Zustände mit fiktiven Namen, Beträgen, Konten und Kennungen. Für die
Umsetzung gelten die Vorgaben aus dem Design-Review, die Entscheidungen 5 bis 10 und die [Oberflächenspezifikation](oberflaeche.md).

D1 und D2 binden `Main.dc.html` ein. Die Breite des Artboards löst dort die Media-Queries aus.

| Artboard | Datei |
|---|---|
| A1 Bankimport mit KI-Vorschlägen (klickbar, Tweak `banner` für die Banner-Zustände) | `Main.dc.html` |
| A2 Sammeldialog (klickbar) | `Sammeluebernahme.dc.html` |
| B1 Seitenpanel, alle zwölf Zustände | `Zustaende.dc.html` |
| B2 Seitenpanel als Komponente (Props `row-id`, `mode`, `details`) | `Matchpanel.dc.html` |
| C1 Vorschläge-Seite, Paketliste | `Vorschlaege-Pakete.dc.html` |
| C2 Vorschläge-Seite, Paket Kontoauszug | `Vorschlaege-Paket.dc.html` |
| D1 Bankimport bei 1024 px, Panel unter der Tabelle | `Schmal-1024.dc.html` |
| D2 Bankimport bei 390 px | `Schmal-390.dc.html` |
| E1 Regel-Fenster mit Regelvorschlägen (Skizze, klickbar) | `Regelvorschlaege.dc.html` |
