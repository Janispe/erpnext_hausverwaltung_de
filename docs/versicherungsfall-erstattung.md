# Versicherungsfall: Auslagen an den Mieter erstatten

Der Customer gehört genau zum ausgewählten Mietvertrag. Ein Erstattungsanspruch
ist ein eigenständiges Guthaben auf diesem Debitor, keine Korrektur einer
Mietrechnung. Hierfür wird ein Journal Entry verwendet; dessen Auszahlung ist
ein Payment Entry vom Typ **Pay**, zugeordnet zum Journal Entry.

## Ablauf

1. Versicherungsfall anlegen: Immobilie/Mietvertrag, Versicherer, Schadennummer,
   Anspruchsberechtigten gegenüber der Versicherung und Auszahlungsempfänger
   getrennt erfassen. Rechnung und Regulierung als Nachweise beifügen.
2. Anerkannten Erstattungsbetrag, Grund, Gegenkonto und Mieterkonto-Kategorie
   **G/N** oder **Sonstig** festlegen.
   - Gebäudereparatur vom Mieter vorgestreckt: passendes Instandhaltungs-
     Aufwandskonto (optional eigenes Unterkonto für Auslagenerstattungen).
   - Ausschließlich fremde Versicherungsleistung weitergeleitet: ein sachlich
     passendes Verrechnungskonto. Keine pauschale Umdeutung in Reparaturaufwand.
3. **Mieteranspruch vorbereiten** wählen, Buchungsdatum festlegen und den
   erzeugten Journal-Entwurf prüfen/einreichen. Dieser bucht Gegenkonto im Soll,
   Mieterdebitor im Haben. Die Aktion erzeugt keinen Bankumsatz.
4. Im Bankimport die bereits erfolgte Mieterauszahlung wählen. Unter den
   offenen Guthaben erscheint der Journal Entry als **Erstattungsguthaben**.
   Betrag zuordnen und buchen. Es entsteht ein eingereichter Payment Entry
   **Mieterdebitor an Bank**, dessen Bank Transaction abgeglichen wird.
   Dies ist eine Verbuchung der vorhandenen Auszahlung, keine neue Überweisung.
5. Versicherungseingang separat sachgerecht buchen (bei gebuchter Versicherungsforderung
   wie unten beschrieben dagegen ausgleichen) und dessen Journal Entry
   als **Versicherungseingang** mit dem Fall verknüpfen. Bank Transactions können
   zusätzlich als Nachweis verknüpft werden; sie erhöhen die Fallsummen nicht
   ein zweites Mal.
6. Fall abschließen, wenn die anerkannten Ansprüche gebucht und ausgeglichen
   sind. Entwürfe und Stornos zählen nicht als erhaltene/ausgezahlte Beträge.
   Bei Storno eines verknüpften Zahlungsbelegs wird der Fall wieder geöffnet.

Eine bereits als Eingangsrechnung erfasste Reparatur darf nicht erneut als
Aufwand gebucht werden. In diesem Fall ist die Zahlung des Mieters gegen die
bestehende Lieferantenverbindlichkeit gesondert abzubilden und der zugehörige
Erstattungs-Journal-Entry im Fall zu verknüpfen.

## Mieterkonto

Der Anspruch erscheint als negatives Guthaben, die Auszahlung positiv in
derselben Kategorie. Beispiel: G/N −458,94 EUR und G/N +458,94 EUR, offen 0 EUR.
Die Versicherung selbst bucht nicht auf den Mieterdebitor.

Bekannte Rechnungsartikel werden wie bisher kategorisiert. Unbekannte Artikel,
uneindeutige Gegenkonten und bisher nicht dargestellte Restbewegungen eines
Debitorenbelegs erscheinen unter **Sonstig**. Diese Darstellung verändert keine
Sachkontenbuchung. Echte unzugeordnete Payment-Entry-Vorauszahlungen bleiben VZ;
Zahlungen gegen Journal-Guthaben übernehmen die Anspruchskategorie.

## Validierung

`scripts/verify_insurance_refund.py` prüft den vollständigen Ablauf ausschließlich
auf der ausdrücklich benannten isolierten Testdatenbank. Er prüft Entwurf,
Einreichung, Teil-/Vollauszahlung, ungültige und veraltete Zuordnungen,
Bankimport-Abgleich, Report-Spalten und Storno. Die Testbuchungen werden
zurückgerollt; die eigentlichen Bankumsätze auf 8090 bleiben ungebucht.

## Versicherungsforderung vor Geldeingang

Für eine zugesagte, bezifferte Leistung Schadennummer, Bewilligungsnachweis und
bewilligten Betrag erfassen. **Forderungen gegen Versicherungen** ist ein eigenes
Aktiv-Sachkonto; **Versicherungserstattungen** ist das Ertragskonto. Der Versicherer
bleibt als Supplier mit dem Fall verknüpft und erhält keinen Mieter-Customer.

**Versicherungsforderung vorbereiten** erzeugt einen prüfbaren Journal-Entwurf:
Forderungen gegen Versicherungen an Versicherungserstattungen. Nach Einreichung
erscheint der Beleg beim Eingang des Versicherers im Bankimport unter den offenen
Versicherungsforderungen. Die Zuordnung erzeugt einen Bank-Journal-Entry:
Bank an Forderungen gegen Versicherungen, mit direkter Referenz auf die Forderung.
Teilzahlungen lassen den Rest offen; eine Überzahlung wird abgewiesen. Ein
Bankeingang wird in diesem Ablauf genau einer Versicherungsforderung zugeordnet.

Gebuchte Eingänge und Forderungen bleiben am Fall verknüpft. Vor dem Storno einer
bezahlten Forderung müssen die zugeordneten Eingänge storniert werden. Ein Storno
öffnet den entsprechenden Betrag wieder. Für den Erstattungsanspruch gegenüber
dem Mieter besteht weiterhin der separate Ablauf oben.

Die EÜR ordnet den Zahlungseingang dem ursprünglichen Ertragskonto zu und die
Auszahlung des Mieteranspruchs dem ursprünglichen Aufwandskonto, jeweils zum
Zahlungsdatum und nur in Höhe der Zahlung. Die Anspruchsbuchungen ohne Bankbewegung
zählen nicht. Das gilt auch bei Teilzahlungen über verschiedene Berichtszeiträume;
Forderungs- und Debitorenkonto erzeugen keine zusätzliche Einnahme/Ausgabe.

`scripts/verify_insurance_receivable.py` prüft diesen Ablauf auf der isolierten
Testdatenbank einschließlich beider EÜR-Ansichten, Teilzahlungen und Storno.
