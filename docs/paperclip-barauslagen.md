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
4. In der isolierten Paperclip-Company einen Agenten mit `adapterType: "process"`
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

- Beim Hochladen die Objekt-Kostenstelle und Zahlungsquelle für alle
  gleichartigen Bons einmal erfassen. Bei Objektkasse das zugehörige
  Kassenkonto auswählen. Für privat vorgestreckte Bons die auslegende Person
  und das bestätigte Verrechnungskonto eintragen. Fehlende Angaben können
  beim Upload leer bleiben.
- Nach der Vorbereitung Original, Händler, Datum, Brutto-Endbetrag,
  Einzelpositionen und Kostenartenvorschläge in der Inbox prüfen.
  **Barauslagen-Angaben ändern** korrigiert die Stapelvorgaben für den
  jeweiligen Bon. Eine leere oder ungeeignete Kontozuordnung bleibt eine
  offene Frage. Der Modellaufruf erhält keine Gegenkonten zur Auswahl.
- **Prüfen und buchen** öffnet den vorhandenen Eingangsrechnungsdialog.
  Der Mensch prüft Lieferant, Datum und Kostenarten und bestätigt die Währung
  EUR sowie den Brutto-Endbetrag am Original. Bei einer Abweichung durch
  Steuern oder Rundung bricht der Dialog die Buchung ab. Fremdwährungsbelege
  werden separat erfasst. Der Dialog gleicht auf das bestätigte Konto aus.
  Eine spätere Erstattung wird separat bearbeitet.
- Bytegleiche Uploads zeigen auf denselben Vorschlag samt ursprünglichen
  Angaben. Bei einem Analysefehler den vorhandenen Vorschlag reaktivieren.
  Er steht dann wieder für den nächsten Agentenlauf bereit.
