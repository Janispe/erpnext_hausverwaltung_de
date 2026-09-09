# Versicherungsfall: Ansprüche und Zahlungen

Der Versicherungsfall steuert seine Anspruchsbuchungen. Der Customer gehört genau
zum ausgewählten Mietvertrag; der Versicherer bleibt als Supplier verknüpft und
bekommt keinen Mieter-Customer.

## Ansprüche gemeinsam buchen

1. Fall erfassen: Immobilie/Mietvertrag, Versicherer, Schadennummer und Nachweise.
   Anspruchsberechtigten gegenüber der Versicherung und Auszahlungsempfänger
   getrennt festhalten.
2. Für die Versicherung bewilligten Betrag, Regulierungszusage, Forderungssachkonto
   (Aktiva/Asset, kein Receivable) und Ertragskonto (Income) auswählen.
3. Für den Mieter anerkannten Erstattungsbetrag, Begründung/Belegnummer, Gegenkonto
   und Kategorie G/N oder Sonstig erfassen. Der Betrag ist unabhängig von der
   Versicherungsleistung. Auslagenersatz für eine Gebäudereparatur verwendet ein
   passendes Aufwandskonto, reine Weiterleitung ein passendes Verrechnungskonto.
4. Fall speichern und **Ansprüche buchen / Datum korrigieren** wählen. Die
   tatsächlichen Anspruchsdaten ausdrücklich auswählen; es wird nicht automatisch
   das heutige Erfassungsdatum als Buchungsdatum vorgeschlagen.
5. Aktion ausführen. Vorhandene Entwürfe werden verwendet; fehlende Ansprüche
   werden aus den Angaben des Falls erstellt. Alle erforderlichen Einreichungen
   erfolgen in einer Transaktion. Ein Fehler hinterlässt keine Teilbuchung.
   Bereits unverändert eingereichte Ansprüche werden nicht doppelt angelegt.

Bei einer bereits als Eingangsrechnung gebuchten Reparatur darf kein zweiter
Aufwand entstehen. Die Zahlung des Mieters gegen die Lieferantenverbindlichkeit
ist dann gesondert abzubilden und der zugehörige Erstattungsbeleg zu verknüpfen.

## Bereits erfasste Anspruchsdaten korrigieren

Dieselbe Aktion **Ansprüche buchen / Datum korrigieren** zeigt die vorhandenen
Daten. Neue Daten und einen Korrekturgrund angeben. Ein Entwurf wird aktualisiert.
Ein eingereichter, noch nicht ausgeglichener Anspruch wird storniert und aus dem
Fall neu erzeugt. Der neue Beleg erhält die Fallverknüpfung und `amended_from`;
Beide bleiben im Fall sichtbar. Stornierte Belege zählen nicht in die Fallsummen.
Ein Fehler bei der Neuerstellung rollt auch das Storno zurück.

Ist ein betroffener Anspruch bereits mit einem Zahlungs-/Ausgleichsbeleg
verknüpft, stoppt die Aktion vor der ersten Änderung und nennt den Beleg.
Dessen Zuordnung muss zuerst kontrolliert über **Beleg lösen** im Bankimport
aufgehoben werden. Bankumsätze und Zahlungsdaten werden durch die Datumskorrektur
nicht geändert. Bei tatsächlicher späterer Anspruchsentstehung darf kein Datum
lediglich zum Umgehen einer Validierung vorverlegt werden.

## Bankimport

- Versicherungseingang der eingereichten Versicherungsforderung zuordnen:
  **Bank an Forderungen gegen Versicherungen**, als Journal Entry mit direkter
  Referenz auf die Forderung. Teilzahlungen lassen den Rest offen; Überzahlungen
  werden abgewiesen. Ein Eingang wird genau einer Forderung zugeordnet.
- Bereits erfolgte Mieterauszahlung dem Erstattungsanspruch zuordnen:
  **Mieterdebitor an Bank**, als Payment Entry Pay mit direkter Referenz auf den
  Anspruch. Das ist eine Verbuchung des vorhandenen Ausgangs, keine Überweisung.

Ansprüche dürfen nach der aktuellen Verarbeitung nicht nach ihren zugehörigen
Zahlungen datiert sein. Eine entsprechende Fehlermeldung nennt beide Daten.
Die Zahlungsbelege werden automatisch dem Fall zugeordnet. Bank Transactions
sind zusätzliche Nachweise und erhöhen die Fallsummen nicht nochmals.
Abschluss ist erst möglich, wenn die anerkannten Ansprüche gebucht und
vollständig ausgeglichen sind. Ein Zahlungsstorno öffnet den Restbetrag wieder.

## Mieterkonto und EÜR

Der Mieteranspruch erscheint negativ, seine Auszahlung positiv in derselben
Kategorie, beispielsweise G/N −458,94 EUR und G/N +458,94 EUR. Unbekannte oder
uneindeutige Kategorien und Restbewegungen erscheinen unter Sonstig. Diese
Darstellung ändert kein Sachkonto; echte unzugeordnete Vorauszahlungen bleiben VZ.

Die EÜR zeigt Versicherungseingänge auf dem Ertragskonto der ursprünglichen
Forderung und Mieterauszahlungen auf dem Gegenkonto des ursprünglichen Anspruchs,
jeweils zum Zahlungsdatum und in Höhe der Zahlung. Die Anspruchsbuchungen ohne
Bankbewegung zählen nicht zusätzlich. Bei Glas-Auslagenersatz sind dies
Versicherungserstattung als Einnahme und Instandhaltung Glaser als Ausgabe.

## Prüfung

Die Skripte `verify_insurance_refund.py`, `verify_insurance_receivable.py` und
`verify_insurance_workflow.py` unter `scripts/` dürfen nur auf der explizit benannten
isolierten Testdatenbank laufen. Sie prüfen unter anderem Bankimport, EÜR,
Teilzahlungen, Storno, gemeinsame Buchung, Entwurfswiederverwendung, veraltete
Anfragen, verknüpfte Korrekturen und vollständiges Rollback bei Fehlern. Testbuchungen
werden zurückgerollt; echte Bankumsätze werden dabei nicht gebucht.
