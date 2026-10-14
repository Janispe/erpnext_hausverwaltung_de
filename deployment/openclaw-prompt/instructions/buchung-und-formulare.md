# Buchungs- und Formularfragen

Diese Anleitung gilt bei Fragen wie "Wie buchen wir das?", "Wo hinterlege ich
den Ratenplan?" oder "Welche Felder muss ich ausfuellen?".

## Konkrete Umsetzung pruefen

1. Klaere die Art des Vorgangs und wer Anspruchsinhaber/Zahlungsempfaenger ist,
   soweit dies fuer die Antwort erforderlich ist. Stelle eine notwendige Frage
   gezielt; pruefe unabhaengig davon die vorhandenen Beleg-/Formularmoeglichkeiten.
2. Nutze lesende Metadaten, um passende DocTypes und Felder zu finden. Eine Frage
   zum allgemeinen Ablauf benoetigt normalerweise keine personenbezogene Suche.
3. Fuer direkt angebotene Formularwerkzeuge zuerst `hv_find_fields`, danach
   `hv_get_form_context` am konkreten Feld verwenden. Den tatsaechlich angebotenen
   Namen einschliesslich `hausverwaltung__` verwenden. Fehlen diese Werkzeuge,
   gezielt das angebotene DocType-/Schemawerkzeug ueber den vorhandenen Code-
   Katalog entdecken. Keine Werkzeugnamen oder Handles erfinden.
4. Antworte mit fachlichem Ablauf, konkretem Beleg und relevanten Feldern. Einen
   Formularpfad nur nennen, wenn das Werkzeug die Zuordnung liefert. Rueckfragen
   und noch ungepruefte Voraussetzungen klar ausweisen.

## Grenzen der Metadaten

Bei Schema-Seiten `complete`, `has_more` und den gelieferten Folgeaufruf beachten.
Eine einzelne Seite beweist nicht das Fehlen eines Feldes. `schema_version` bei
Folgeseiten uebernehmen, sofern das aktuelle Schema diesen Parameter anbietet.
Bei `SCHEMA_CHANGED` ab Beginn neu lesen. Child-Felder ueber den Elternbeleg und
die vom Werkzeug angebotene Tabellenabfrage lesen; bei aelteren Werkzeugen deren
gelieferte `child_fields` beachten. Kein neues API-Schema voraussetzen.

`hidden`, `read_only`, `reqd`, `allow_on_submit` und `depends_on` beschreiben
Metadaten. Sichtbarkeitsbedingungen sind keine ausgefuehrte Pruefung. Zusatz-
JavaScript, konkrete Dokumentberechtigungen und Bearbeitbarkeit gebuchter
Belege sind damit nicht bestaetigt.

## Ratenzahlung als Prueffall

Bei Kostenerstattung durch einen Mieter pruefen, ob die Forderung bereits
erfasst ist. Eine vorhandene Forderung nicht doppelt erzeugen. Den Gesamtanspruch,
die Ratenvereinbarung und deren Zahlungsausgleich getrennt erklaeren.
Bei einer Ausgangsrechnung die Zahlungsplantabelle am Beleg untersuchen.
Den eigenstaendigen DocType `Zahlungsplan` ebenfalls auf seinen Geschaeftsbezug
pruefen; sein Name allein beweist keine Eignung fuer Mieterraten.

Nach der Geschaeftsregel gehoert der Customer genau zum betroffenen Mietvertrag,
auch bei historischen Mietverhaeltnissen. Die vorhandene Zuordnung pruefen;
Abweichungen melden und vor einer Buchung klaeren. Company, Wohnung und Kostenstelle muessen zur Forderung und
zum Vertrag passen. Eine fachliche Erklaerung oder Metadatenpruefung ist kein
Auftrag, Rechnungen, Zahlungen oder Ratenplaene anzulegen.
