# KI-Buchungsvorschläge: Übergabe

Stand 18.11.2026. Design für KI-Vorschläge im Buchungssystem. Ein Agent schlägt für die Zeilen eines
Kontoauszugs Zuordnungen und Buchungen vor. Die Vorschläge erscheinen **direkt im Bankimport an der Zeile**
und **zusätzlich auf der Vorschläge-Seite** (`/app/hv-proposals`) als Paket.

Grundlage ist der Vorschlags-Kern aus PR #44–#46 (`hausverwaltung/proposals/`, Seite `hv-proposals`), der in
`main` liegt. Die Umsetzung erfolgt in Orchestrator.inc.

| Datei | Inhalt |
|---|---|
| [oberflaeche.md](oberflaeche.md) | Bankimport (Tabelle, Seitenpanel, Sammeldialog) und Ergänzungen der Vorschläge-Seite |
| [schnittstelle.md](schnittstelle.md) | Datenform, die die Oberfläche erwartet, und Skizze fürs spätere Backend |
| [issues.md](issues.md) | Aufträge für Orchestrator.inc, mit Abnahme |
| [mockup/](mockup/) | Referenz-Markup aus dem Design-Canvas |

## Entscheidungen (Janis, 18.11.2026)

1. **Übernehmen im Bankimport ist ein Klick.** „Übernehmen & buchen“ gibt den Vorschlag frei und führt ihn
   sofort aus. Freigabe und Ausführung stehen trotzdem als zwei Ereignisse im Prüfprotokoll, gebunden an
   Revision und Hash.
2. **Orte:** Die bestehende Bankimport-Seite (`/app/bankimport_v2`) wird verändert. Die Vorschläge-Seite zeigt
   dieselben Vorschläge zusätzlich als Paket. Buchungs-Inbox und Buchen-Cockpit bleiben unverändert.
3. **Design-System:** „Hausverwaltung Design System“. Im Bankimport gelten dessen Bankimport-Klassen und
   Tokens, auf der Vorschläge-Seite `hv-tokens.css` und `hv-components.css`.
4. **Reihenfolge:** zuerst die Oberfläche mit Mock-Daten, das Backend später.

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

1. **Auftrag 1 – Oberfläche im Bankimport** mit Mock-Daten in `HV_Bankimport/src_react`. Ohne Backend bleibt
   alles KI-Bezogene unsichtbar, die Seite verhält sich wie heute.
2. **Auftrag 2 – Backend und Vorschläge-Seite:** Buchungsaktionen im Kern, Lese- und Übernahme-Endpunkte,
   Ergänzungen in `hv_proposals.js`. Erst nach Janis' Freigabe von Auftrag 1.
3. **Später:** der Agent, der die Vorschläge erzeugt. Nicht Teil dieser Unterlagen.

Merge durch Janis. Tests in einem isolierten Stack, nicht auf der Dev-Site 8090.

## Vorgaben für Auftrag 1 nach dem Review

- Frappe reicht `row` aus dem Zeilenlink ans Bankimport-iframe weiter.
- Der Betrag bleibt bei schmaler Ansicht in der Tabellenzeile sichtbar.
- Die Sammelauswahl startet leer. „Hohe Sicherheit“ markiert die passenden Zeilen auf Klick.

## Offene Entscheidungen

1. **Auslöser:** Agent automatisch nach dem CSV-Import starten oder per Knopf „Vorschläge anfordern“? Das
   Design zeigt beides (Banner-Zustände), Auftrag 1 baut nur die Anzeige.
2. **„Anpassen“ und dann selbst buchen:** Vorschlag als „Abgelehnt“ mit automatischem Grund
   „Angepasst gebucht: <Beleg>“ schließen (Vorschlag des Designs) oder eigener Status im Kern?
3. **Regeln:** Soll der Agent bei wiederkehrenden Mustern (z. B. Kontoführungsgebühr) zusätzlich eine
   Bankimport-Regel vorschlagen?
4. **Sicherheit:** Zeigen wir die Prozentzahl oder nur die Stufe hoch/mittel/niedrig? Die Zahl stammt vom
   Agenten und ist keine kalibrierte Wahrscheinlichkeit.

## Zum Mockup-Format

Die Dateien in `mockup/` stammen aus dem Design-Canvas und laufen nicht direkt im Browser:

- `{{ … }}` sind Platzhalter, `<sc-for>` und `<sc-if>` Schleifen und Bedingungen, `<dc-import>` bindet eine
  andere Datei als Komponente ein (`Matchpanel.dc.html`).
- Die Zustandslogik steht im `<script type="text/x-dc">` am Ende.
- `ds/hausverwaltung/…` verweist auf die Stylesheets des Design-Systems. Im Repo entsprechen ihnen
  `HV_Bankimport/src_react/src/styles/*.css` (Bankimport) und `hausverwaltung/public/css/hv-tokens.css`,
  `hv-components.css` (Vorschläge-Seite).

Die Exporte zeigen Aufbau, Texte und Zustände mit fiktiven Namen, Beträgen, Konten und Kennungen. Für die
Umsetzung gelten die Vorgaben nach dem Review und die [Oberflächenspezifikation](oberflaeche.md).

| Artboard | Datei |
|---|---|
| A1 Bankimport mit KI-Vorschlägen (klickbar) | `Main.dc.html` |
| A2 Sammeldialog (klickbar) | `Sammeluebernahme.dc.html` |
| B1 Seitenpanel, alle acht Zustände | `Zustaende.dc.html` |
| B2 Seitenpanel als Komponente | `Matchpanel.dc.html` |
| C1 Vorschläge-Seite, Paketliste | `Vorschlaege-Pakete.dc.html` |
| C2 Vorschläge-Seite, Paket Kontoauszug | `Vorschlaege-Paket.dc.html` |
