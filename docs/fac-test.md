# FAC + Mistral: lokale Testintegration

FAC 2.5.1 (Commit `7ddc433772f4ade794d9f5ee30b7d9ea0af2a487`) ist optional.
Die bestehende Hausverwaltung funktioniert weiterhin ohne FAC.

## Vorhandene Umgebung auf Port 8090

FAC ist auch im vorhandenen Stack `hvp`, Site `frontend`, eingerichtet:
<http://localhost:8090/desk/hausverwaltung-assistant>.
Hier gelten die bisherigen Zugangsdaten und Mistral-Einstellungen. Im Chat
**FAC Original – nur Lesen (Test)** auswählen. Der Administrator hat FAC-Zugriff.

Dieser Modus (`fac_native`) verwendet ausschließlich 12 originale FAC-Core-Werkzeuge
für Suche, Dokumentabruf, Metadaten, Berichte und offene Freigaben. Er hat einen
separaten Systemprompt ohne die bisherigen Hausverwaltungs-Werkzeuganweisungen.
Mistral-Konfiguration, Chatoberfläche, Gesprächsschleife und Verlauf werden
weiterverwendet. Die Domänenregel Customer ↔ Mietvertrag (1:1) bleibt im Prompt.

Der bisherige Modus bleibt separat als **FAC + HV-Werkzeuge (Test)** (`fac`)
mit seinen 18 Hausverwaltungswerkzeugen verfügbar. Jeder Chat erhält nur den
Werkzeugkatalog seines gewählten Modus; ein Wechsel startet einen neuen Chat.

Das Backend-Image `hvp:16-helpdesk-suite-fac` und die Images
`hvp:8090-frontend-fac`, `hvp:8090-queue-short-fac`, `hvp:8090-queue-long-fac`
erweitern lokale Sicherungen der zuvor vorhandenen Container. Diese enthielten
bereits unterschiedliche Anpassungen, die im ursprünglichen Image
`hvp:16-helpdesk-suite` fehlten. Die Sicherungen heißen
`hvp:8090-<backend|frontend|queue-short|queue-long>-before-fac-20260916`.
Sie bleiben lokal und werden für einen erneuten Build benötigt.

Die Compose-Konfiguration in
`erp_next/production/frappe_docker/compose.custom.yaml` verwendet diese Images.
Ports, Daten-Volumes und bestehende Apps bleiben erhalten. Der Build übernimmt
nur die FAC-Integrationsdateien und ergänzt den jeweils bestehenden Hook.

Rebuild im Hausverwaltung-Repository:

```bash
bash scripts/build_fac_existing_image.sh
for role in frontend queue-short queue-long; do
  FAC_BASE_IMAGE="hvp:8090-${role}-before-fac-20260916" \
  FAC_IMAGE="hvp:8090-${role}-fac" bash scripts/build_fac_existing_image.sh
done
```

Die explizite CLI-Einrichtung erfolgt über
`hausverwaltung.hausverwaltung.services.fac_setup.install_on_existing_site`
mit `expected_site="frontend"`. Dabei wird nur der Conversation-DocType für
die zusätzliche Engine synchronisiert. Installations-E-Mails werden während
dieses Aufrufs unterdrückt. Vor der ersten Einrichtung wurde ein Datenbank-Backup
unter `frontend/private/backups/20260916_171012-frontend-database.sql.gz` erstellt.

Die nachfolgende Umgebung auf Port 18082 ist eine separate, leere Testsite.

## Start

Im Hausverwaltung-Repository:

```bash
docker compose -f compose.fac-test.yaml up -d --build
docker compose -f compose.fac-test.yaml logs -f setup
```

Voraussetzung ist das vorhandene lokale Image `hvp:16` mit Frappe/ERPNext und den
Hausverwaltungs-Abhängigkeiten. Alternativ `FAC_BASE_IMAGE` setzen. Die benachbarten
Repositories `mail_merge` und `process_engine` werden wie die Hausverwaltung
schreibgeschützt eingebunden. Die Testumgebung hat eigene Datenbank-, Site- und
Log-Volumes und verwendet keine bestehende Site.

- URL: <http://fac.localhost:18082/desk/hausverwaltung-assistant>
- Benutzer: `Administrator`
- Lokales Testpasswort: `admin` (beim ersten Start über `FAC_TEST_ADMIN_PASSWORD` ändern).
- Port: `FAC_TEST_PORT`, Standard `18082`, nur an Loopback gebunden.
- Site: `fac.localhost`; neu und ohne bestehende Mieterdaten oder API-Schlüssel.

In **Hausverwaltung Einstellungen** die vorhandene Mistral-Konfiguration
(Aktivierung, API-URL, API-Schlüssel und Modell) eintragen. Im Assistenten einen
neuen Chat mit **FAC Original – nur Lesen (Test)** starten. Auf einer bestehenden Site würde
dieser Modus deren bereits gespeicherte Mistral-Einstellungen direkt verwenden.
Es ist kein FAC-Cloud-Konto erforderlich.

## Was getestet wird

Der lokale Chat verwendet den bestehenden `mistral_client` und FACs
`ToolRegistry`. FAC übernimmt Werkzeugfreigabe, Rollenprüfung, Ausführung und
Audit-Logging. Die Verbindung im selben Frappe-Prozess benötigt keinen
zusätzlichen HTTP-Aufruf oder zweiten Benutzerschlüssel. Modellanfragen und
benötigte Werkzeugergebnisse gehen wie bisher an den konfigurierten LLM-Anbieter.

Im Modus **FAC + HV-Werkzeuge (Test)** werden 18 vorhandene lesende Hausverwaltungswerkzeuge über den offiziellen
`assistant_tools`-Hook als FAC-Tools registriert. Die vollständige freigegebene
Liste bleibt auch bei Anschlussfragen verfügbar. Die Fachlogik einschließlich
Customer ↔ Mietvertrag (1:1) und der vorhandenen Dokument-/Feldrechte bleibt erhalten.
Die Testkonfiguration aktiviert die FAC-Plugins `custom_tools` und `core`.
Die 5 schreibenden Core-Werkzeuge sind explizit deaktiviert. Schreiben,
Serienbriefe und beliebige Python-/SQL-Ausführung sind nicht Teil dieses Piloten.

Der Pilot übernimmt weiterhin die bestehende Chat-Schleife und deren begrenzten
Verlauf. Er ist kein vollständiger Ersatz der Gesprächssteuerung. FACs originale Lesewerkzeuge sind im Modus `fac_native` aktiviert;
die FAC-3-Chat-Beta wird nicht verwendet.

FAC-Zugriff setzt zusätzlich `Assistant Core Settings.server_enabled` und
`User.assistant_enabled` voraus. Für den Testadministrator werden diese gesetzt.
Weitere Benutzer brauchen die passenden Frappe-Leserechte und die Rolle
`Agent Readonly API` oder `System Manager`.

## MCP und direkter Mistral-Connector

Der echte FAC-MCP-Endpunkt der vorhandenen Installation steht parallel bereit:

```text
http://localhost:8090/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp
```

Für die separate leere Testsite stattdessen `http://fac.localhost:18082` verwenden.

Der HTTP-MCP-Endpunkt stellt beide freigegebenen Lesekataloge gemeinsam bereit
(30 Werkzeuge). Die Trennung in 12 bzw. 18 Werkzeuge erfolgt für die beiden
Chatoptionen zusätzlich vor Modellaufruf und Werkzeugausführung.

FAC unterstützt OAuth bzw. API-Key/Secret-Authentifizierung. Ein externer
Mistral-Connector benötigt eine von Mistral erreichbare HTTPS-Adresse und eine
eigene Connector-Registrierung/Authentifizierung. Die lokale Loopback-Adresse
ist dafür nicht erreichbar. Für den eingebauten Testchat ist dieser Connector
nicht erforderlich.

Referenzen:
- <https://github.com/buildswithpaul/Frappe_Assistant_Core/releases/tag/v2.5.1>
- <https://docs.mistral.ai/studio/connectors>

## Prüfungen und Betrieb

```bash
docker compose -f compose.fac-test.yaml exec -T backend \
  bench --site fac.localhost run-tests --module hausverwaltung.hausverwaltung.services.test_fac_assistant
docker compose -f compose.fac-test.yaml exec -T backend \
  ./env/bin/python apps/hausverwaltung/docker/fac-test/smoke.py
docker compose -f compose.fac-test.yaml stop
```

Der HTTP-Smoke-Test prüft den MCP-Handshake, den Werkzeugkatalog, ein echtes
Mietvertrag-Schema und die Ablehnung nicht authentifizierter Anfragen. Er legt
bei Bedarf API-Zugangsdaten für den lokalen Testadministrator an, gibt sie aber
nicht aus. Die automatisierten Tests benötigen keinen Mistral-Schlüssel.

`up -d` startet erneut, `stop` erhält die Testdaten. Es läuft kein Scheduler;
Mailversand ist deaktiviert. Der Bootstrap legt vor der Mail-Merge-Installation
einen temporären Druckformat-Platzhalter an, um deren bestehenden Zyklus zwischen
Singleton-Default und erst nach Migration erstelltem Druckformat aufzulösen.
`mail_merge` ersetzt diesen bei der Migration durch das reguläre Format.

### Verifikation der vorhandenen Site auf 8090

Am 16.09.2026 erfolgreich geprüft: Loginseite HTTP 200, MCP-Handshake und
Werkzeugkatalog mit 18 Lesewerkzeugen über das bestehende Administrator-API-Login,
MCP-Schemaabruf für Mietvertrag, nicht authentifizierter Zugriff HTTP 401 sowie
eine vollständige FAC-Anfrage mit dem bereits konfigurierten
`mistral-small-latest`. Dabei wurden nur Schemaangaben ans Modell geschickt.
Die Antwort ordnete `kunde` dem DocType `Customer` und `wohnung` dem DocType
`Wohnung` zu. Der Bestand blieb bei 364 Mietverträgen und 141 Wohnungen.
Der Hintergrundworker kann den FAC-Werkzeugkatalog laden.

Der anschließend ergänzte Modus `fac_native` wurde ebenfalls auf Port 8090 über
`start_assistant_run` und den Hintergrundworker mit einer echten Mistral-Anfrage
geprüft. Das Modell erhielt ausschließlich die 12 originalen FAC-Lesewerkzeuge
und rief `get_doctype_info` auf. Die Herkunft aller 12 Implementierungen aus
`frappe_assistant_core.plugins.core.tools` wurde geprüft. Die neue Auswahl wird
über den authentifizierten Seitenendpunkt ausgeliefert. Alle 10 FAC-Integrationstests
und der MCP-Smoke-Test mit 30 Werkzeugen auf der isolierten Site waren erfolgreich.

### DocType-Erkennung und leere Modellantworten

Der native Prompt erklärt die generische FAC-Entdeckung über
`list_documents(doctype="DocType")`, gefolgt von `get_doctype_info`.
`search_doctype` sucht dagegen Datensätze innerhalb eines bekannten DocTypes.
Am Werkzeuglimit erzwingt die Chat-Schleife für FAC eine Textantwort mit
`tool_choice="none"`. Eine weiterhin leere Antwort wird als unvollständige
Auskunft gemeldet, niemals als fehlender Mieterbestand. FAC-Dokumentdaten
werden für die Trefferanzeige generisch auf Dokumentlinks abgebildet.

Verifiziert mit 12 Regressionstests, lokalem FAC-Abruf aller 16 Immobilien und
der unveränderten Frage „welche immobilien gibt es hier ?“ an Mistral mit
ausschließlich synthetischen Werkzeugantworten. Das Modell fand den DocType,
las dessen Schema und listete beide erfundenen Objekte in 3 fehlerfreien
Werkzeugaufrufen auf. Der synthetische Testchat wurde gekennzeichnet und archiviert.
