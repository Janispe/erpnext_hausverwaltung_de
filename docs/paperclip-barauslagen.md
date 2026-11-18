# Dev-Pilot für Barauslagen

In der Buchungs-Inbox bündelt **Barauslagen-Stapel** bis zu 50 JPEG-, PNG- oder
PDF-Dateien. Eine Datei entspricht einem Bon und bleibt als privater Originalbeleg
am Vorschlag. Ein PDF kann bis zu fünf Seiten enthalten. Die Dateiobergrenze
liegt bei 10 MB. Der bisherige **Sammel-Upload** bleibt der Weg für normale
Eingangsrechnungen.

## Isolierte Testsite einrichten

1. App migrieren und nur auf der Dev-/Testsite `bench --site <dev-site> set-config --parse hv_receipt_pilot 1`
   ausführen. Der Pilot ist standardmäßig deaktiviert.
2. Unter **Hausverwaltung Einstellungen** die vorhandene Mistral-kompatible
   Schnittstelle mit einem bildfähigen Modell konfigurieren. Der Pilot sendet
   Bonfotos direkt und PDF-Seiten als gerenderte PNGs an dieses Modell.
3. In ERPNext die Rolle `Paperclip Barauslagen` und einen eigenen API-Benutzer
   mit dieser Rolle anlegen. Keine Buchhaltungs-, System-Manager-, Dokument-,
   Datei- oder Freigaberechte hinzufügen. Der Agent erhält ausschließlich die
   beiden Pilotoperationen für die Warteschlange und die Vorbereitung eines
   Vorschlags einschließlich seines Originals.
4. Für die Freigabe einen persönlichen Desk-Benutzer mit `Accounts User` oder
   `Accounts Manager` und Schreibrecht am Buchungsvorschlag verwenden. Er braucht
   außerdem die ERPNext-Rechte zum Lesen des Lieferanten sowie zum Anlegen und
   Einreichen von `Purchase Invoice` und `Journal Entry`. Auf einer frischen
   Dev-Site mit angepassten Rollenrechten diese Berechtigungen ausdrücklich für
   den Testbenutzer einrichten.
5. In der isolierten Paperclip-Company einen Agenten mit `adapterType: "process"`
   anlegen. Paperclip muss den Checkout auf seinem Host lesen können. Die drei
   Umgebungsvariablen `HV_RECEIPT_PILOT_URL`, `HV_RECEIPT_PILOT_KEY` und
   `HV_RECEIPT_PILOT_SECRET` aus geschützter Laufzeitkonfiguration bereitstellen.
   Benutzerschlüssel und Secret gehören in den Secret Store des Agenten.
   Beispiel für die Prozesskonfiguration ohne Zugangsdaten:

   ```json
   {
     "command": "/usr/bin/python3",
     "args": ["/checkout/hausverwaltung/scripts/paperclip_receipts.py"],
     "cwd": "/checkout/hausverwaltung",
     "timeoutSec": 4800
   }
   ```

   Der Prozess verarbeitet je Ausführung bis zu 50 wartende Pilotvorschläge.
   Den Agenten manuell starten oder für die Dev-Company einen Rhythmus für
   Heartbeats einstellen. [Paperclip-Prozessadapter](https://docs.paperclip.ing/reference/adapters/process/)

## Stapel prüfen

- Beim Hochladen die Kostenstelle des eindeutig zugeordneten Gebäudes und die Zahlungsquelle für alle
  gleichartigen Bons einmal erfassen. Bei Objektkasse das zugehörige
  Kassenkonto auswählen. Für privat vorgestreckte Bons die auslegende Person
  und das bestätigte Verrechnungskonto eintragen. Fehlende Angaben können
  beim Upload leer bleiben.
- Nach der Vorbereitung Original, Händler, Datum, Brutto-Endbetrag,
  Einzelpositionen und Kostenartenvorschläge in der Inbox prüfen.
  **Barauslagen-Angaben ändern** korrigiert die Stapelvorgaben für den
  jeweiligen Bon. Eine leere oder ungeeignete Kontozuordnung bleibt eine
  offene Frage. Der Modellaufruf erhält keine Gegenkonten zur Auswahl.
- **Bon prüfen** öffnet den Eingangsrechnungsdialog in der Inbox. Die Buchhaltung
  prüft Lieferant, Datum und Kostenarten und bestätigt Währung und Brutto-Endbetrag
  am Original. **Freigeben und buchen** speichert diese Fassung samt Freigabe in der
  Vorschlagsengine und bucht anschließend Eingangsrechnung und Ausgleichsjournal.
  Die Freigabe erfordert eine angemeldete Buchhaltungssitzung mit Buchungsrechten.
- Änderungen am Bon oder an seinen Buchungsdaten erfordern eine erneute Prüfung
  und Freigabe. **Buchungsdaten korrigieren** zieht eine offene Freigabe zurück.
  Scheitert die Buchung, kann die Buchhaltung dieselbe Fassung mit **Buchung
  fortsetzen** erneut ausführen. Rechnung, Journal und Buchungsergebnis werden
  gemeinsam gespeichert. Ein erneuter Aufruf liefert die bereits gebuchten Belege.
- Bei Abweichungen durch Steuern oder Rundung bricht die Buchung ab. Fremdwährungsbelege
  und spätere Erstattungen werden separat erfasst.
- Die Freigabe bindet auch die von ERPNext ermittelte Netto- und Steueraufteilung.
  Ändert sich die Aufteilung bei gleichbleibendem Brutto, ist eine neue Freigabe nötig.
- Stornierte Rechnungen oder Ausgleichsjournale kennzeichnet die Inbox am Bon.
  Original und bisherige Buchung bleiben für die Nachprüfung verknüpft.
- Bytegleiche Uploads zeigen auf denselben Vorschlag samt ursprünglichen
  Angaben. Bei einem Analysefehler den vorhandenen Vorschlag reaktivieren.
  Er steht dann wieder für den nächsten Agentenlauf bereit.
