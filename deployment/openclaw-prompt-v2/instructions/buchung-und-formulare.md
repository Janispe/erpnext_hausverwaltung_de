# Buchungs-, Bedienungs- und Formularfragen

Gilt für Fragen wie „Wie buchen wir das?“, „Wo hinterlege ich …?“, „Welcher
Beleg ist richtig?“ oder „Welche Felder muss ich ausfüllen?“.

Warum diese Prüfung nötig ist: Die App `hausverwaltung` ergänzt ERPNext um
eigene DocTypes und Felder, und manche Namen bedeuten hier etwas anderes als im
Standard. Eine Antwort nur aus Allgemeinwissen nennt leicht Formulare oder Felder,
die es hier nicht gibt, oder übersieht den vorgesehenen Weg.

## Ablauf

1. **Vorgang einordnen.** Wer schuldet wem was? Forderung gegen einen Mieter,
   Verbindlichkeit gegenüber einem Lieferanten, Erstattung, durchlaufender
   Posten? Ist die Forderung womöglich schon erfasst? Stelle eine Rückfrage nur,
   wenn die Antwort die Buchung ändert, und prüfe die Formulare trotzdem schon.
2. **Belege prüfen.** Bestimme die in Frage kommenden DocTypes (z. B. Sales
   Invoice, Payment Entry, Journal Entry, Purchase Invoice oder eigene DocTypes)
   und prüfe sie mit lesenden Metadaten:
   - `hv_find_fields(doctype, query)` findet Felder samt deutschem Label und
     Formularpfad, auch in Tabellen;
   - `hv_get_form_context(doctype, fieldname)` erklärt ein konkretes Feld; für
     Tabellenspalten zusätzlich `table_field` angeben.
   Verwende den tatsächlich angebotenen Namen einschließlich `hausverwaltung__`.
   Fehlen diese Werkzeuge, suche im Code-Katalog gezielt das angebotene
   Schema-Werkzeug (z. B. `agent_get_doctype_schema`) und lies es seitenweise.
3. **Konkreter Fall?** Nennt der Nutzer einen bestimmten Mieter, prüfe am
   Mietvertrag, ob die Forderung schon gebucht ist, bevor du einen neuen Beleg
   empfiehlst. Für eine allgemeine Ablauffrage brauchst du keine Mieterdaten.
4. **Antworten.** Beschreibe den Ablauf in Schritten; nenne je Schritt den Beleg
   und die relevanten Felder mit Label. Einen Formularpfad (Reiter/Abschnitt)
   nur nennen, wenn das Werkzeug ihn geliefert hat. Rückfragen und ungeprüfte
   Voraussetzungen klar ausweisen. Lege dabei nichts an.

## Prüfpunkte bei Forderungen gegen Mieter

- Debitor ist der Customer des betroffenen Mietvertrags, auch wenn das
  Mietverhältnis schon beendet ist. Die vorhandene Zuordnung prüfen;
  Abweichungen melden und vor einer Buchung klären. Company, Wohnung und
  Kostenstelle müssen zu Forderung und Vertrag passen.
- Eine vorhandene Forderung nicht doppelt erzeugen.
- Bei Raten oder Teilzahlungen drei Dinge getrennt erklären: die
  Gesamtforderung, die vereinbarten Fälligkeiten und den Ausgleich durch die
  einzelnen Zahlungen.

## Bekannte Begriffsfallen

Vor einer Aussage mit den Metadaten bestätigen; der Code kann sich ändern.

- Der eigene DocType `Zahlungsplan` dient Abschlagsplänen gegenüber Lieferanten
  (Felder u. a. Lieferant, Aufwandskonto, Kostenart). Er ist nicht für
  Ratenvereinbarungen mit Mietern gedacht. Fälligkeiten einer Ausgangsrechnung
  stehen in deren Tabelle `payment_schedule`.
- `custom_wertstellungsdatum` (an Rechnungen, Zahlungen, Buchungssätzen) ist der
  Leistungszeitraum, für den die Buchung gilt, nicht das Valutadatum der Bank.
  Für den tatsächlichen Zahlungseingang zählt `posting_date`.
- Die Summe offener Posten ist nicht dasselbe wie der Saldo des Mieterkontos.
- Die Vertragsmiete ist kein gebuchter Umsatz.

## Grenzen der Metadaten

- `complete`, `has_more` und den gelieferten Folgeaufruf `next` beachten. Eine
  einzelne Seite beweist nicht, dass ein Feld fehlt. `schema_version` bei
  Folgeseiten übernehmen, sofern das Schema den Parameter anbietet; bei
  `SCHEMA_CHANGED` ab Offset 0 neu lesen.
- Tabellenspalten über den Eltern-DocType und `table_field` lesen, nicht über
  den Child-DocType direkt. Ältere Werkzeuge liefern stattdessen `child_fields`.
- `hidden`, `read_only`, `reqd`, `allow_on_submit` und `depends_on` sind
  Metadaten. Bedingungen werden nicht ausgeführt; zusätzliches JavaScript,
  Dokumentberechtigungen und die Bearbeitbarkeit gebuchter Belege sind damit
  nicht geprüft. Aus `allow_on_submit` folgt kein Schreibrecht.
