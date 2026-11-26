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

## Mehrere Bons in einem Upload (Pilot #85)

Auf einer **isolierten synthetischen Site** nach `bench migrate` zusätzlich
`bench --site TESTSITE set-config --parse hv_receipt_batch 1` setzen. Beide
Pilot-Schalter müssen aktiv sein. Der Original-Upload bleibt bytegenau privat.
Ein Foto oder PDF ist ein eigener Auftrag, auch wenn mehrere Dateien
gleichzeitig ausgewählt werden. Je Datei sind 10 MB und fünf PDF-Seiten
möglich. Die Analyse unterstützt bis zu 20 Bons und bis zu zehn Ausschnitte je
Bon. Koordinaten liegen bei 0 bis 1000 je Bildachse, gemessen vom linken oberen
Rand der EXIF-korrigierten Fotoseite bzw. der gerenderten PDF-Seite.

### Paperclip-Mitarbeiter Barauslagen mit Codex

Für den vollständigen Codex-Ablauf zusätzlich
`bench --site TESTSITE set-config --parse hv_receipt_codex 1` setzen.
Alle drei Schalter sind standardmäßig aus. Die Rolle `Paperclip Bonanalyse`,
die signierte Routine und die Site-Konfiguration für den Webhook bleiben wie
unten beschrieben. Die Routine muss diesem einen Agenten zugewiesen sein.
Setze für ihn `runtimeConfig.heartbeat.enabled = false` für den periodischen
Timer und `runtimeConfig.heartbeat.maxConcurrentRuns = 1`. Die Routine weckt
ihn je Upload oder Revision.

Verwende einen absoluten Pfad zur Codex CLI **0.166.0**. Der CLI-Prozess
benötigt eine auf dem Testhost eingerichtete Codex-Anmeldung und ein
bildfähiges Modell wie `gpt-6.2-sol`. Der Worker benötigt Python mit
Pillow und pypdfium2. Erzwinge bei Testsite und Worker kompatible Versionen
von Pillow und pypdfium2, weil die Pixel des Zuschnitts überprüft werden.
Das App-Verzeichnis muss für die Worker-Laufzeit lesbar sein. Beispiel für
die Agent-Konfiguration (Pfade anpassen):

```json
{
  "name": "Barauslagen",
  "adapterType": "codex_local",
  "runner": "legacy",
  "adapterConfig": {
    "engine": "cli",
    "command": "/checkout/hausverwaltung/scripts/codex",
    "cwd": "/isolated/worker",
    "model": "gpt-6.2-sol",
    "instructionsFilePath": "/checkout/hausverwaltung/docs/paperclip-barauslagen-codex-agent.md",
    "timeoutSec": 2400,
    "env": {
      "HV_RECEIPT_CODEX_BINARY": "/opt/codex-0.166.0/bin/codex",
      "HV_RECEIPT_PILOT_URL": "http://isolierte-erpnext-site"
    }
  },
  "runtimeConfig": {
    "heartbeat": { "enabled": false, "maxConcurrentRuns": 1 }
  }
}
```

Der Startbefehl heißt `codex`, damit Paperclip den Hello-Test ausführt.
Das Skript braucht Python mit den genannten Bildbibliotheken im `PATH`
der Agentenlaufzeit. Die eigentliche Codex CLI steht unter dem absoluten
Pfad in `HV_RECEIPT_CODEX_BINARY`.

Hinterlege zusätzlich `HV_RECEIPT_PILOT_KEY` und `HV_RECEIPT_PILOT_SECRET`
im Paperclip Secret Store. Lege diese Zugangsdaten für einen eigenen
API-Benutzer mit ausschließlich der Rolle `Paperclip Bonanalyse` an.
Der Startbefehl konfiguriert den MCP-Server für den zugewiesenen Run und
startet genau eine Codex CLI. Paperclip behält Issue, Zuweisung, Verlauf und
Status. ERPNext bindet die bytegenaue Originaldatei, Vorschlagsschritte
und FAC-Leseoperationen an den von Paperclip validierten Run. Der Worker
rendert das Original und schneidet mit Pillow lokal zu. Abgeschlossene
Vorschläge, geprüfte Quellen und Rückfragen stehen in der Buchungs-Inbox.
Bei `blocked` den technischen Fehler beheben und in Paperclip dasselbe
Issue fortsetzen. ERPNext setzt beim ersten ausstehenden Bon fort.

Für den Lieferantenvorschlag auf der isolierten Testsite zusätzlich
`hv_receipt_supplier_proposals=1` und `hv_proposals_enabled=1` setzen.
Dem separaten API-Benutzer zusätzlich `HV Proposal Agent` und über die
Rollenkonfiguration ausschließlich Leserechte auf `Supplier` geben.
Der Vorschlagsdienst akzeptiert für `Paperclip Bonanalyse` ausschließlich
serverseitig autorisierte Aufrufe aus dem verifizierten Auftragskontext.
`submit_receipt` übernimmt den Händlernamen aus der validierten Bonanalyse
und verwendet das FAC-Vorschlagswerkzeug. Eindeutige Stammdaten haben
Vorrang. Mehrdeutige Treffer erscheinen als Rückfrage.

Unter **Bon-Uploads** den Lieferantenvorschlag öffnen. Die Sachbearbeitung
prüft ihn in **Aktionsvorschläge**, gibt ihn frei und führt ihn aus.
Danach das ursprüngliche Paperclip-Issue fortsetzen. Der Mitarbeiter
übernimmt das erfolgreiche Ausführungsergebnis in den betroffenen Bon.
Bis zur Entscheidung blockiert der Auftrag ohne Timer. Nach einem
Ausführungsfehler zeigt die Inbox den Fehlerstatus. Nach Ablehnung und
Wiederaufnahme bleibt der betroffene Bon zur Klärung markiert. Die
Buchungsfreigabe erfolgt anschließend separat in **Buchungs-Inbox**.

Für einen synthetischen Inferenzlauf `CODEX_ROLLOUT_TRACE_ROOT` vorübergehend
auf ein privates Verzeichnis setzen. Vergleiche die Zell-ID der
`tool_call_started`-Ereignisse mit `code_cell_started` und
`code_cell_ended`. Prüfe alle Inferenzanfragen auf Rohdatenmarker und
fremde Quellen sowie jede geprüfte Kurzliste auf die erwarteten Konten und
passenden Kostenstellen. Der Trace kann Originalbilder und MCP-Rohdaten
enthalten. Die Modellanfragen enthalten nur Zellenausgaben und den übrigen
Gesprächskontext. Die MCP-Schnittstelle attestiert den Zellaufruf nicht,
und Modellcode kann Daten über seine Ausgabe offenlegen. Der Nachweis
gilt für die geprüften synthetischen Läufe. Paperclip erhält vom
Startbefehl nur technische Laufereignisse, keine Modell- oder
Werkzeug-Rohausgaben. Lösche den privaten Trace nach der Auswertung.
[Paperclip Codex-Adapter](https://docs.paperclip.ing/reference/adapters/codex/)

### Produktionsvorbereitung und Abnahme

1. Lege zunächst eine isolierte ERPNext-Site und eine eigene Paperclip-Company
   an. Diese Kombination ist für die Vorbereitung festgelegt:
   Frappe **16.16.0**, ERPNext **16.14.0**, Paperclip **2026.1117.0** mit
   Node **24.22.3** und der Codex CLI **0.166.0**. Konfiguriere in Paperclip
   explizit `codex_local`, `runner: legacy` und `engine: cli`. Prüfe den
   Adapter in Paperclip und aktiviere den Mitarbeiter erst auf der
   isolierten Site. Gleiche
   die Renderer zwischen ERPNext und Worker ab (Pillow **13.0.0** und
   pypdfium2 **5.15.2** für diese Kombination). Das neuere Release mit
   Frappe **16.55.2** und ERPNext **16.53.0** verwendet pypdfium2
   **5.14.0**. Nutze ein eigenes Worker-
   Verzeichnis, eine dedizierte Codex-Anmeldung und ein privates Paperclip.
2. Richte einen dedizierten ERPNext-Systembenutzer mit der Rolle
   `Paperclip Bonanalyse` ein. Er braucht keine zusätzlichen DocType-,
   File-, Buchhaltungs-, Freigabe- oder generischen FAC-Rollen.
   `HV_RECEIPT_PILOT_KEY` und `HV_RECEIPT_PILOT_SECRET` sind die
   ERPNext-API-Zugänge im Paperclip Secret Store.
   `HV_RECEIPT_PILOT_URL` ist die ERPNext-Basisadresse des Workers.
   `HV_RECEIPT_CODEX_BINARY` verweist auf die geprüfte CLI.
   Paperclip verwaltet das serverseitige Signaturgeheimnis für Run-JWTs
   und injiziert `PAPERCLIP_API_KEY`, `PAPERCLIP_API_URL` und
   `PAPERCLIP_AGENT_ID` in den gestarteten Run. Verwende dafür keine
   dauerhaften Board-Zugangsdaten. Lege das separate Signaturgeheimnis
   des Routine-Webhooks in der geschützten Frappe-Site-Konfiguration
   unter `hv_receipt_webhook_secret` ab.
3. Richte die Sachbearbeitung mit `Accounts User` oder `Accounts Manager`
   und dem regulären Zugriff auf ihre Uploads, Vorschläge, Lieferanten,
   Kostenstellen und Konten ein. Uploads benötigen Anlegen-Rechte auf
   `File` und `Buchungs Vorschlag` sowie Leserecht auf `HV Bon Upload`.
   Freigabe und Buchung benötigen die für die Buchungs-Inbox vorgesehenen
   Rechte auf Vorschlag, Eingangsrechnung und Journal. Originale und
   Ausschnitte sind private Frappe-Dateien. Die Original-URL erbt das
   Leserecht vom Upload, die Ausschnitt-URL vom Vorschlag. Das gilt auch
   für alte Dateieinträge und Abrufe mit `fid`, unabhängig vom Dateieigentümer.
4. App migrieren und die Routine, Agenten-UUID und Site-Adressen gemäß
   Abschnitt unten setzen. Prüfe in beide Richtungen die Erreichbarkeit
   ohne Zugangsdaten auszugeben. Auf der isolierten Site
   `hv_receipt_pilot`, `hv_receipt_batch` und `hv_receipt_codex`
   mit `bench --site TESTSITE set-config --parse KEY 1` setzen.
   Anschließend Web-, Scheduler- und Queue-Konfiguration neu laden.
   Auf Produktion alle drei Schalter ausgeschaltet und die Routine
   deaktiviert lassen.
5. Lade auf der Testsite ein synthetisches Foto mit drei Bons und ein PDF
   mit einem fortlaufenden Bon hoch, jeweils mit Notiz. Prüfe unterschiedliche
   Issue-IDs, höchstens einen aktiven Run, exakte Endbeträge, den Sollinhalt
   der privaten Zuschnitte und sichtbare Vorschläge samt Gesprächslink.
   Lege für den Kontierungsvergleich passende und fremde synthetische
   Vergleichsbuchungen an. Werte den privaten nativen Trace wie oben aus.
   Revidiere einen Bon und vergleiche die übrigen Vorschläge und die
   gespeicherten früheren Fassungen. Erzwinge einen Analysefehler nach
   Öffnen eines Schritts, prüfe `blocked` samt Blockiergrund und setze
   dasselbe Issue fort. Teste als Analysebenutzer nach dem Lauf den
   Direktdownload beider Dateitypen, auch mit alter File-ID. Prüfe
   separat als berechtigte Sachbearbeitung den erfolgreichen Download.
   Überprüfe, dass die Vorschläge keinem automatisch angelegten
   `Purchase Invoice` oder `Journal Entry` zugeordnet sind.
6. Zum Abschalten zuerst den Routine-Trigger deaktivieren, aktive
   Paperclip-Läufe auslaufen lassen oder abbrechen und die drei ERPNext-
   Schalter auf `0` setzen. Leere die Warteschlange erst nach fachlicher
   Entscheidung über offene Aufträge. Ziehe bei dauerhafter Abschaltung
   den API-Zugang des Analysebenutzers zurück und entferne die
   Worker-Secrets und das Webhook-Geheimnis. Bestehende Vorschläge,
   Originale, Ausschnitte und Revisionen bleiben erhalten. Allein
   `hv_receipt_codex` auf `0` zu setzen gibt den früheren
   Prozesspfad wieder frei, solange beide anderen Schalter an sind.
   Schalte deshalb den Stapel-Pilot zusätzlich aus, wenn die Verarbeitung
   vollständig ruhen soll.

### Gemeinsame Routine und früherer Prozesspilot

Für die Webhook-Einrichtung gelten unten Punkt 3 und 4. Punkt 2 beschreibt
die historische Vision-/Claude-Variante für Sites mit deaktiviertem
`hv_receipt_codex`.


1. In der Testsite einen separaten API-Benutzer mit der Rolle
   `Paperclip Bonanalyse` einrichten. Die Rolle erhält keine DocType-, File-,
   Lese-, Buchhaltungs- oder FAC-Rechte. Die bestehende Einzelbon-Rolle
   `Paperclip Barauslagen` ist für den älteren Agenten bestimmt.
2. In der **bestehenden isolierten Paperclip-Company** einen festen
   Mitarbeiter **Barauslagen** aus dem getesteten Checkout als Prozessagenten
   konfigurieren. In seinen Laufzeiteinstellungen
   `runtimeConfig.heartbeat.maxConcurrentRuns = 1` setzen. Der Mitarbeiter
   bearbeitet die getrennten Stapel-Aufträge seriell. Paperclip muss lokale,
   kurzlebige Run-JWTs injizieren. In die geschützte Agentenkonfiguration
   `HV_RECEIPT_PILOT_URL`, `HV_RECEIPT_PILOT_KEY` und
   `HV_RECEIPT_PILOT_SECRET` eintragen. Für die neue Betriebsart
   `HV_RECEIPT_MODE=batch` setzen. Zusätzlich in der Prozesslaufzeit
   `HV_RECEIPT_VISION_URL` (OpenAI-kompatible Basisadresse einschließlich
   `/v1`), `HV_RECEIPT_VISION_MODEL` und bei einem authentifizierten
   Modellendpunkt `HV_RECEIPT_VISION_KEY` setzen. Für den getrennten PTC-Aufruf
   an Claude Messages `HV_PTC_CLAUDE_KEY` und `HV_PTC_CLAUDE_MODEL` mit
   PTC-fähiger Modell-ID setzen. Optional ersetzt `HV_PTC_CLAUDE_URL` die
   Standard-Basisadresse `https://api.anthropic.com`. Der gewählte Python-Interpreter
   benötigt Pillow (zum Beispiel in einer eigenen virtuellen Umgebung mit
   `python -m pip install Pillow`). Beispiel für den Prozess:

   ```json
   {
     "command": "/usr/bin/python3",
     "args": ["/checkout/hausverwaltung/scripts/paperclip_receipts.py"],
     "cwd": "/checkout/hausverwaltung",
     "timeoutSec": 2400
   }
   ```

3. Eine aktive Routine für diesen Agenten mit `concurrencyPolicy: "always_enqueue"`
   und einem signierten `app_webhook`-Trigger anlegen. Die Routine braucht
   keine Vorlage für Falldaten und keinen Heartbeat-Timer. Die angesprochene
   Version muss bei erfolgreicher Webhook-Zustellung eine Run-Antwort mit
   `status: "issue_created"` und `linkedIssueId` liefern. In der geschützten
   Frappe-Site-Konfiguration eintragen:

   | Einstellung | Wert |
   | --- | --- |
   | `hv_receipt_paperclip_url` | Paperclip-Basisadresse, aus dem ERPNext-Backend erreichbar |
   | `hv_receipt_paperclip_agent` | UUID des Mitarbeiters Barauslagen |
   | `hv_receipt_paperclip_web_url` | Browser-Basisadresse für die Buchhaltung, ohne Zugangsdaten |
   | `hv_receipt_paperclip_company_prefix` | Issue-Präfix der isolierten Company, z. B. `HVT` |
   | `hv_receipt_webhook_url` | Vollständige URL des öffentlichen Routine-Triggers |
   | `hv_receipt_webhook_secret` | HMAC-Schlüssel aus Paperclip |

   Die Webhook-Payload enthält Upload- und Auftrags-ID. ERPNext verifiziert
   den Run-JWT gegen Paperclip und liest den Issue-Bezug des verifizierten
   Runs, bevor es den zugehörigen Auftrag bearbeitet. Pro Upload und Revision
   entsteht ein eigener Ausführungskontext. Ein Modellaufruf erhält Seiten
   oder Ausschnitte als PNG-Bildteile und die Notiz als Textdaten. Der
   Paperclip-Prozess ruft das Modell direkt auf und erzeugt die Ausschnitte
   mit Pillow in seiner eigenen Laufzeit. Er sendet die PNG-Dateien
   gemeinsam mit dem Vorschlag. ERPNext prüft PNG-Typ, Größe, Seitenbezug,
   Koordinaten und Pixel gegen das private Original. Die konfigurierte
   Vision-Modell-ID muss multimodale JSON-Antworten unterstützen.
   [Paperclip-Routine](https://docs.paperclip.ing/reference/api/routines/)
   [Paperclip-Prozessadapter](https://docs.paperclip.ing/reference/adapters/process/)
4. ERPNext-Scheduler aktivieren und Web- und Worker-Prozesse nach der
   Konfigurationsänderung neu laden. Bei einem Zustellfehler wiederholt die
   Outbox den Versand mit derselben Ereignis-ID und Signatur. Ist ein
   Paperclip-Auftrag bereits zugeordnet und der Lauf unterbrochen, das
   zugehörige Issue in Paperclip fortsetzen. ERPNext setzt anhand der
   gespeicherten Bons fort. Die Anzeige markiert ausbleibenden Fortschritt
   nach fünf Minuten als unterbrochen.

### Bedienung und Abnahme

- **Barauslagen-Stapel** in der Buchungs-Inbox öffnen, Foto oder PDF auswählen,
  optional Notiz und vorhandene Barauslagen-Angaben erfassen. Unter
  **Bon-Uploads** erscheinen Empfang, Zustellung, Zahl der bearbeiteten Bons
  und Abschlussstatus. Die Bildvorschau am Bon zeigt seinen privaten
  Ausschnitt bzw. ein PDF aller zugehörigen Ausschnitte. Der Original-Link
  verweist auf den gesamten Upload.
- Bei Unschärfe, Anschnitt, Überlappung oder unklarer Gruppierung erscheint
  eine Rückfrage. **Überarbeiten lassen** sendet eine Rückfrage für den
  ausgewählten Bon. Bisherige und neue Fassung bleiben mit Ausschnitt,
  Seitenkoordinaten und erkanntem Betrag prüfbar. Bei vermuteter Aufteilung
  oder Zusammenlegung erscheint eine Klärfrage. Die Revision kann nur den
  ausgewählten Bon ersetzen. Eine neue Fassung erfordert eine neue
  menschliche Buchungsfreigabe.
- Ausschließlich synthetisches Material verwenden. Ein Foto mit drei gut
  unterscheidbaren Beträgen und ein dreiseitiges PDF mit einem Bon über
  zwei Seiten sowie einem zweiten Bon auf Seite drei einreichen. Als
  Bildnachweis erfundene Händler und Beträge ausschließlich im Bild
  platzieren und die erkannten Werte sowie Seitenzuordnung protokollieren.
  Je einen unlesbaren oder überlappenden Bon hinzufügen und den Klärfall
  prüfen. Die Buchungs-Inbox muss bis zum vollständigen Abschluss
  Einzelvorschläge und Fortschritt zeigen.
- Den Webhook bei einem Upload vorübergehend unerreichbar machen und
  anschließend mit unverändertem Trigger fortsetzen. Eine akzeptierte
  Zustellung mit derselben Ereignis-ID erneut senden. Bei zwei überlappenden
  Uploads zwei verschiedene Issue-UUIDs prüfen. Einen Lauf nach dem ersten
  Vorschlag unterbrechen und im selben Issue fortsetzen. Ein Versuch mit
  einem Run-JWT eines fremden Issues darf keine Daten des Uploads erhalten.
- Einen einzelnen Bon überarbeiten. Danach die alte Freigabefassung, die
  übrigen Bons und beide privaten Ausschnitte prüfen. Einen Lauf der älteren
  Revision nach der neueren Rückfrage fortsetzen und die Ablehnung der
  veralteten Analyse prüfen. Erst **Freigeben und buchen** darf die
  Eingangsrechnung und das Ausgleichsjournal anlegen.

Die deterministischen ERPNext-Regressionstests stehen in
`hausverwaltung.hausverwaltung.services.test_receipt_batch`. Sie verwenden
synthetische Bilddateien und kontrollierte Antworten für Fehler und
Wiederholungen. Der Nachweis der tatsächlichen Modellerkennung erfolgt im
isolierten Pilot mit der oben beschriebenen Bildprobe.


### Kontierungsvergleich und PTC prüfen

`scripts/programmatic_tools.py` ist eine eigenständige Bibliothek. Sie nimmt
einen Prompt, einen freigegebenen Werkzeugkatalog im MCP-Schemaformat, einen
authentifizierten Dispatcher und einen Modelladapter entgegen. Sie kennt
keine ERPNext- oder Paperclip-IDs. Der Claude-Adapter registriert die Tools
als Client-Tools mit `allowed_callers` und nutzt den dokumentierten
Code-Execution-Container. Der Dispatcher lehnt direkte Aufrufe ab. Er
liefert die Zwischenlisten als Code-Tool-Ergebnisse an genau diesen
Container. Der Modellcode darf als einzige Ausgabe die vom jeweiligen
Prüfwerkzeug bestätigte Kurzliste ausgeben.
[Claude Programmatic Tool Calling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling)

Für Barauslagen stellt `receipt_evidence.py` einen an den aktuellen Bon
gebundenen `tools/list`- und `tools/call`-Dispatcher bereit. Er verwendet
die FAC-Routing-Metadaten für Code und prüft jeden Aufruf mit der
ERPNext-Rolle und dem Paperclip-Run. Claude registriert die erhaltenen
Schemas einzeln. Der eingebaute Claude-MCP-Connector ist für diesen
PTC-Ablauf ungeeignet.

Der Code sucht den aus dem Bon gelesenen Händler. Bei einem eindeutigen
Stammdatentreffer kann er frühere gebuchte Rechnungspositionen desselben
Lieferanten in der ermittelten ERPNext-Company vergleichen. Er ermittelt
zulässige Sachkonten und priorisiert passende Positionen desselben Objekts,
wenn es über die Kostenstelle eindeutig zugeordnet ist. Die Inbox zeigt
höchstens drei belegte Kontenvorschläge mit Quellen. Fehlt eine eindeutige
Zuordnung oder ein Beleg, steht die Frage am Bon. Die Sachbearbeitung
entscheidet über die Kontierung in ERPNext.

1. Ausschließlich auf der synthetischen Pilotkonfiguration vorübergehend
   `HV_RECEIPT_PTC_SYNTHETIC_TRACE=1` setzen. Das Protokoll zeigt dann
   den tatsächlich vom Modell erzeugten Python-Code, seine Prüfsumme,
   die Folge der Code-Tool-Aufrufe, ihre Antwortgrößen und die bestätigte
   Schlussausgabegröße. Es zeigt keine Werkzeug-Zwischenlisten.
2. Gebuchte synthetische Vergleichspositionen desselben Lieferanten in
   der Test-Company und mindestens einen Gegenbeleg eines anderen
   Lieferanten anlegen. Mindestens eine passende Position muss auf
   dasselbe Objekt kontiert sein. Ein zweiter Fall verwendet einen
   Händler ohne eindeutige Zuordnung. In beiden Läufen auf den
   bedingten Abruf und die Quellen der Kurzliste achten.
3. Ohne Paperclip dieselbe Ausführungsschicht gegen den unabhängigen
   Messdaten-Katalog prüfen. Hierfür in einer geschützten Shell
   `HV_PTC_CLAUDE_KEY` und `HV_PTC_CLAUDE_MODEL` bereitstellen und
   `python3 -m unittest discover -s scripts -p test_programmatic_tools.py -v`
   ausführen. Der Live-Test dokumentiert den vom Anbieter gelieferten
   Code und seine Tool-Aufrufe. Die übrigen Tests prüfen den Vertrag
   mit kontrollierten Provider-Antworten.

### Vorbereiteter Bonschritt aus dem früheren Codex-Pilot

Der zweite PTC-Pilot verwendet die native JavaScript-Runtime der Codex CLI.
Die CLI spricht Standard-MCP über stdio. `ptc_mcp_stdio.py` stellt den
Transport bereit. `receipt_ptc_mcp.py` bindet ihn an denselben ERPNext-Katalog
und Auftragsdispatcher wie der Claude-Pilot. Der Start über den
Paperclip-CLI-Legacy-Adapter benötigt keine Änderung in Paperclip selbst.
Der Pilot prüft den Kontierungsvergleich eines vorbereiteten Bonschritts.
Bildinventar, Ausschnitt und Einreichung gehören weiterhin zum regulären
Barauslagen-Prozess.

#### Unabhängiger Test auf dem Start-Host

Geprüft auf Linux x86_64 mit Python 3.12.3, lokaler Codex CLI **0.166.0**,
bestehender ChatGPT-Anmeldung und Modell **gpt-6.2-sol**. Der Worker-Befehl
`codex` zeigte zunächst auf 0.164.0. Die 0.166.0 wurde für den Test separat
aus dem offiziellen Paket `@openai/codex@0.166.0` unter `/tmp` installiert.
Verwende im Adapter den absoluten Pfad des tatsächlich geprüften Binaries.
Der MCP-Prozess läuft auf demselben Host und benötigt hier nur Python.

```bash
/path/to/codex --version
/path/to/codex login status
python3 scripts/verify_codex_ptc.py --codex /path/to/codex --model gpt-6.2-sol
```

Der Test startet in einem leeren Verzeichnis mit `--ignore-user-config`,
`--ignore-rules`, `--ephemeral`, `--sandbox read-only` und `-a never`.
Er aktiviert `--enable code_mode --enable code_mode_only --enable
code_mode_only_strict_3p_tools` und gibt nur dem synthetischen MCP-Server
seine drei Werkzeuge frei. Die Schalter sind in 0.166.0 als in Entwicklung
gekennzeichnet. Ohne die gezielte MCP-Freigabe wurde der Tool-Aufruf trotz
aktivem Code Mode mit „MCP tool call requires approval, but approval
policy is never“ abgebrochen.

Der lokale Rollout-Trace muss eine vom Modell geschriebene JavaScript-Zelle
mit drei verschachtelten Aufrufen des synthetischen Messdaten-Katalogs nachweisen. Der Test vergleicht
Zell-ID und Werkzeugaufrufe, prüft zwei Rohdatenmarker in der Runtime und
ihre Abwesenheit in den Modellanfragen. Die einzige fachliche Ausgabe an
das Modell muss das bestätigte aggregierte Ergebnis sein. Der Test legt
die interne Spur temporär ab und gibt nur den synthetischen Kurzbeleg
aus. Die übliche CLI-JSONL-Ausgabe enthält selbst die vollständigen
MCP-Ereignisse. Verwende sie ausschließlich mit synthetischen Daten und
veröffentliche keine Rohtraces.
[Codex MCP](https://developers.openai.com/codex/mcp)
[Codex Rollout Trace 0.166.0](https://raw.githubusercontent.com/openai/codex/rust-v0.166.0/codex-rs/rollout-trace/README.md)

#### ERPNext-Pilot über den zugewiesenen Paperclip-Run

1. Auf einer Rootless-Wegwerf-Site mit migrierter App, `hv_disposable_test_site=1`,
   `hv_receipt_pilot=1` und `hv_receipt_batch=1` arbeiten. Der Adapter-Host
   braucht Zugriff auf die HTTP-API der Wegwerf-Site. Die CI-Site in diesem
   Workspace war am Host unter `http://127.0.0.1:8285` erreichbar und hieß
   im ERPNext-Container `frontend`. Der ERPNext-Backend-Container muss die
   Paperclip-API über seine eigene Netzroute erreichen. Loopback im Container
   ist der Container selbst. Die im Backend wirksame
   `hv_receipt_paperclip_url` und die Agenten-UUID
   `hv_receipt_paperclip_agent` auf die isolierte Company abstimmen.
2. Die Demo-Daten der Testsite verwenden und über den bestehenden ERPNext-Weg
   synthetische Eingangsrechnungen buchen. Mindestens ein Beleg soll denselben
   Lieferanten und dieselbe Kostenstelle haben. Ein anderer soll einer
   anderen Kostenstelle oder einem anderen Lieferanten zugeordnet sein.
   Dann einen privaten synthetischen Upload mit passender Kostenstelle und
   Notiz einreichen. Auf die bestätigte Paperclip-Issue-Zuordnung warten.
   Den Pilotlauf erst nach der folgenden Vorbereitung starten oder dasselbe
   Issue erneut starten:

   ```bash
   bench --site frontend execute hausverwaltung.cypress_fixtures.prepare_e2e_receipt_ptc \
     --args '["SYNTHETISCHE-UPLOAD-UUID"]'
   ```

   Den Platzhalter durch die Upload-UUID ersetzen. Das Fixture setzt
   ausschließlich auf einer Wegwerf-Site einen noch unbearbeiteten,
   bereits verknüpften Upload auf Bonschritt 1. Die tatsächliche Routine
   liefert die Issue-Zuordnung weiterhin selbst.
3. Dem CLI-Legacy-Adapter die drei getesteten Code-Mode-Schalter und
   `-a never` mitgeben. Die in Schritt 1 genannte Pilot-Site wird über
   `HV_RECEIPT_PILOT_URL` gebunden. Für den MCP-Prozess
   `HV_RECEIPT_PTC_STEP=1` und `HV_RECEIPT_PTC_MERCHANT` mit dem exakten
   Namen des synthetischen Lieferanten setzen. `HV_RECEIPT_PILOT_KEY` und
   `HV_RECEIPT_PILOT_SECRET` kommen aus der geschützten Agentenkonfiguration
   eines API-Benutzers in der Rolle `Paperclip Bonanalyse`.
   `PAPERCLIP_API_KEY` muss der kurzlebige Run-JWT des tatsächlich
   laufenden zugewiesenen Issues sein. Ein Board-Schlüssel oder der
   eigene Terminal-Login kann diesen Run-Bezug nicht herstellen.
4. Nur diesen MCP-Server im isolierten Lauf registrieren. Die
   TOML-Einstellungen entsprechen einzelnen `-c key=value`-Overrides
   bei `--ignore-user-config`. Verwende absolute Pfade auf dem Adapter-Host.

   ```toml
   [mcp_servers.receipt_ptc]
   command = "/usr/bin/python3"
   args = ["/checkout/hausverwaltung/scripts/receipt_ptc_mcp.py"]
   required = true
   enabled_tools = ["lookup_supplier", "list_booked_receipts", "list_allowed_accounts", "verify_shortlist"]
   default_tools_approval_mode = "approve"
   env_vars = [
     "HV_RECEIPT_PILOT_URL", "HV_RECEIPT_PILOT_KEY", "HV_RECEIPT_PILOT_SECRET",
     "HV_RECEIPT_PTC_STEP", "HV_RECEIPT_PTC_MERCHANT", "PAPERCLIP_API_KEY"
   ]
   ```

5. Den Agenten anweisen, eine native JavaScript-Zelle zu schreiben.
   Darin soll er den Lieferanten ermitteln, bei einem Treffer die
   Vergleichsbelege abrufen, zulässige Konten schneiden und
   `verify_shortlist` mit höchstens drei belegten Konten aufrufen. Nur
   dessen geprüftes Ergebnis mit `text(...)` ausgeben. Für die Abnahme
   `CODEX_ROLLOUT_TRACE_ROOT` in ein privates temporäres Verzeichnis auf
   dem Adapter-Host setzen und die Zellspur gegen alle Inferenzanfragen
   prüfen. Für den Fall eines unbekannten synthetischen Lieferanten einen zweiten
   Upload mit eigenem Paperclip-Issue verwenden. Dabei soll der historische Abruf ausbleiben.
6. Im ERPNext-Auftrag die gespeicherte Kurzliste und ihre passenden
   Belegreferenzen prüfen. Ein fremder oder beendeter Paperclip-Run
   muss bei der Initialisierung des Fachkatalogs scheitern. Der
   CLI-Pilot stellt keine Buchungswerkzeuge bereit und reicht keinen
   vollständigen Bon ein. Die stdio-Schnittstelle enthält keine
   Attestation, ob ein MCP-Aufruf aus Code Mode stammt. Für diesen Pilot
   belegt das die native Spur nach dem Lauf. Die CLI kann bei einer
   abweichenden Modellantwort Werkzeugdaten ausgeben. Daher nur
   synthetische Daten verwenden.
