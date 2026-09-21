# LibreChat und Open WebUI: Docker-Testinstanzen

Die beiden separaten Clients verwenden dieselbe Mistral-API und den vorhandenen
FAC-MCP-Endpunkt der ERPNext-Instanz auf Port 8090. Jeder Client speichert seine
Chats in einem eigenen Docker-Volume. Die vorhandene ERPNext-Oberfläche bleibt
bestehen; es wurde kein eigener Chat- oder MCP-Proxy implementiert.

| Client | Adresse | Image |
| --- | --- | --- |
| LibreChat | http://100.89.21.12:8091 | `ghcr.io/danny-avila/librechat:v0.8.7` |
| Open WebUI | http://100.89.21.12:8092 | `ghcr.io/open-webui/open-webui:v0.11.3` |

In beiden Clients ist **FAC Original · Mistral** mit `mistral-small-latest`
vorkonfiguriert. Die Testzugänge stehen in
`docker/ai-clients/credentials.local.json` (nicht versioniert, Dateimodus 0600).
Öffentliche Registrierung ist deaktiviert.

Zusätzlich steht in beiden Modellauswahlen **FAC · GLM 5.3 (via Mistral)** bereit.
Dieses Profil verwendet `zai-glm-5-3` über denselben Mistral-Endpunkt und denselben
API-Schlüssel sowie dieselben zwölf FAC-Werkzeuge und denselben Systemhinweis.
Das Ausgabelimit beträgt für dieses Reasoning-Modell 4096 Tokens. Es wurde kein
separater Z.ai-Zugang angelegt. Die Verfügbarkeit einschließlich Function Calling
wurde über die Modellliste des vorhandenen Mistral-Zugangs geprüft.
Open WebUI stellte Mistrals strukturierte `thinking`-Blöcke zunächst als Rohtext
dar. Deshalb ist ausschließlich diesem GLM-Profil der lokale Stream-Formatfilter
`mistral_structured_content` zugeordnet (Quelltext:
`docker/ai-clients/mistral_content_filter.py`). Er überträgt Text und Denkspur in
die von Open WebUI erwarteten Felder; Werkzeugaufrufe bleiben unverändert.
Das Modell verwendet weiter seine Standard-Reasoning-Einstellung. GLM 5.3
akzeptierte im Test nur `low`, `high` und `max`, nicht `none`.
LibreChat benötigte diesen Formatfilter nicht.

## Werkzeuge und Modell

Der LibreChat-Agent aktiviert genau die zwölf originalen lesenden FAC-Werkzeuge.
In Open WebUI ist dieselbe Liste als Werkzeugfilter der MCP-Verbindung hinterlegt
und im vorkonfigurierten Modell aktiviert. Die zusätzlichen Hausverwaltungswerkzeuge
des Servers sind nicht Bestandteil dieser beiden Chat-Voreinstellungen.

FAC veröffentlicht am gemeinsamen Endpunkt weiterhin insgesamt 30 Werkzeuge.
LibreChat kann diese im Agent-Editor anzeigen; für den Vergleich den vorbereiteten
Agenten verwenden. Die Beschränkung in den Clients ist keine Einschränkung des
zugrunde liegenden ERPNext-API-Tokens: Es handelt sich um den vorhandenen
Administrator-Zugang. Die API-Schlüssel liegen lokal in der ignorierten `.env`
und werden an die jeweiligen Backends übergeben.

Ein kurzer identischer Hinweis fordert Metadatenabfragen, begrenzte Listen und
ehrliche Fehlermeldungen. Es gibt keine Übernahme der eigenen Agentenschleife oder
der spezialisierten Hausverwaltungswerkzeuge. Ein Clientwechsel behebt keine
fehlenden FAC-Feldrechte oder ungeeigneten ERP-Abfragen.

## Betrieb

Vom Wurzelverzeichnis dieser App aus:

```bash
docker compose --env-file docker/ai-clients/.env -f docker/ai-clients/compose.yaml up -d
docker compose --env-file docker/ai-clients/.env -f docker/ai-clients/compose.yaml ps
docker compose --env-file docker/ai-clients/.env -f docker/ai-clients/compose.yaml stop
```

Docker-Projekt: `hv-ai-clients`. Das externe Netzwerk `hvp_default` muss existieren.
MongoDB wird nur intern für LibreChat bereitgestellt; Open WebUI verwendet seine
eigene persistente Datenbank. `down` erhält die Daten-Volumes; `down -v` löscht sie.

LibreChat liest `docker/ai-clients/librechat.yaml` beim Start. Der dort referenzierte
Agent wird in MongoDB gespeichert. Open WebUI speichert Integrationen und
Modell-Voreinstellungen in seiner Datenbank; Umgebungsvariablen überschreiben
bereits gespeicherte Einstellungen nicht automatisch. Nach Änderungen an Schlüsseln
daher auch die gespeicherte Verbindung im Adminbereich von Open WebUI aktualisieren.

Die Clients sind HTTP-Testinstanzen mit Login auf den angegebenen Ports. Es wurde
kein öffentlicher Reverse-Proxy oder TLS-Endpunkt angelegt.

## Geprüft am 16.09.2026

Beide Logins und die vorausgewählte FAC-Konfiguration wurden im Browser geprüft.
In jedem Client wurde über Mistral genau einmal `get_doctype_info` für den
Standard-DocType `ToDo` ausgeführt. Beide Werkzeugaufrufe waren erfolgreich und
die abschließenden Antworten nannten vorhandene Felder. Für diese Tests wurden
keine Mieter-, Vertrags- oder Immobiliendatensätze abgefragt.

Auch GLM 5.3 wurde in beiden Browseroberflächen mit derselben ToDo-Schemaabfrage
erfolgreich getestet. Open WebUI zeigte nach Aktivierung des Formatfilters eine
korrekte Antwort ohne rohe `thinking`-Objekte. Synthetische Prüfungen des Filters
bestätigten, dass Werkzeugaufrufe, normale Text-Deltas, andere Inhaltstypen und
Usage-Ereignisse erhalten bleiben.

## Dateien, Berechnungen und Excel in Open WebUI

In Open WebUI steht zusätzlich **GLM · Dateien & Auswertungen + FAC** bereit.
Das Profil verwendet GLM 5.3 über Mistral, die bisherigen zwölf FAC-Lesewerkzeuge
und den automatisch ausgewählten Arbeitsbereich **Dateien & Auswertungen**.

Der zusätzliche Docker-Dienst `open-terminal` verwendet das offizielle Image
`ghcr.io/open-webui/open-terminal:0.13.0`. Python, pandas, openpyxl, pypdf,
python-docx, matplotlib, LibreOffice und PDF-Werkzeuge sind enthalten. Die
Anbindung erfolgt über Open WebUIs native Open-Terminal-Integration und deren
HTTP-API. LibreChat wurde für diese Erweiterung nicht verändert.

Bedienung:

1. Open WebUI neu laden und einen neuen Chat öffnen.
2. **GLM · Dateien & Auswertungen + FAC** auswählen.
3. Über **+ / Upload Files** eine PDF-, Word-, Excel- oder CSV-Datei hochladen.
4. Die gewünschte Auswertung oder Ausgabedatei anfordern.

Uploads werden für diese Terminalverbindung direkt im Arbeitsbereich abgelegt
(`chat_uploads: filesystem`). Das Modell erhält den Dateipfad und kann die Datei
gezielt lesen. Die Dateiseitenleiste erlaubt Uploads und Downloads; erzeugte
Dateien kann das Modell über `display_file` anzeigen. Der Arbeitsbereich ist
zwischen den Chats dieses Testzugangs gemeinsam und bleibt bei Neustarts erhalten.

Technische Grenzen:

- Eigenes Volume `hv-ai-clients_analysis-workspace`, im Container `/home/user`.
- Nur internes Docker-Netzwerk `hv-ai-clients_workspace`; keine veröffentlichten
  Ports und kein ausgehender Internetzugang aus dem Terminal.
- Keine Host-Verzeichnisse, ERP-Dateien oder Docker-Socket eingebunden.
- Keine Mistral- oder ERP-API-Schlüssel im Terminal; eigener API-Schlüssel in `.env`.
- Nicht privilegierter Benutzer, schreibgeschütztes Container-Dateisystem mit
  beschreibbarem Arbeitsbereich und `/tmp`; 2 CPUs, 2 GiB RAM, 256 Prozesse.
- Kein OCR-Dienst eingerichtet. Bildbasierte Scans sind deshalb nicht wie PDFs
  mit vorhandener Textebene auslesbar.

Die Verbindung und die Profilkonfiguration liegen zusätzlich in Open WebUIs
Datenbank. Wie bei den anderen Integrationen müssen sie beim Wiederaufbau mit
einem leeren Daten-Volume erneut angelegt werden.

Verifiziert: PDF und DOCX mit erfundenen Inhalten erstellt und über das native
`read_file` erfolgreich ausgelesen. Im Browser eine CSV hochgeladen, durch GLM
eine Excel-Auswertung erzeugen lassen und über die Dateiseitenleiste heruntergeladen.
Die heruntergeladene XLSX wurde unabhängig geöffnet: drei Positionen mit 120,50,
79,50 und 50,00 EUR, korrekte Summe 250,00 EUR. Dabei wurden keine ERP-Daten gelesen.

## Mail-Archiv (Stalwart, nur lesend)

Der Dienst `mail-mcp` (Image `ghcr.io/wh1isper/mcp-email-server:1.9.1`) gibt beiden
Clients lesenden Zugriff auf das Stalwart-Konto `archiv@archiv.test` auf dem Laptop
(`janis-hp-pavilion-x360-convertible-14-dh1xxx.tailadb960.ts.net:993`, IMAP über das
Tailnet). Er läuft nur mit Compose-Profil `mail`, veröffentlicht keinen Port und ist
ausschließlich als `http://mail-mcp:9557/mcp` im Netzwerk `clients` erreichbar. Der
Endpunkt hat keine eigene Authentifizierung.

```bash
docker compose --env-file docker/ai-clients/.env -f docker/ai-clients/compose.yaml --profile mail up -d mail-mcp
```

Zugangsdaten stehen als `MAIL_MCP_*` in der ignorierten `.env`. `MCP_EMAIL_SERVER_USER_NAME`
darf nicht leer gesetzt werden, sonst meldet sich der Server mit leerem Benutzernamen an.

Nur-Lesen ist mehrschichtig umgesetzt, aber noch nicht serverseitig in Stalwart:

- kein SMTP-Host und leere Empfängerliste, dadurch `can_send=false`;
- Anhänge deaktiviert;
- in beiden Clients nur `list_available_accounts`, `list_mailboxes`, `list_email_tags`,
  `list_emails_metadata` und `get_emails_content` freigegeben;
- das Konto `archiv@archiv.test` selbst hat volle Rechte. Für den Dauerbetrieb ein eigenes
  Stalwart-Konto nur mit Leserecht verwenden.

Profile: LibreChat **Mail Archiv · GLM 5.3** (Agent in `mail-agent-id.txt`), Open WebUI
**Mail Archiv · GLM 5.3** (`mail-archiv-glm-5-3` mit Formatfilter `mistral_structured_content`,
Verbindung `server:mcp:mail`). Modell `zai-glm-5-3` über Mistral, max. 4096 Ausgabetokens.
Die Agentenanweisung verlangt bei `get_emails_content` denselben `mailbox`-Wert wie bei der
Suche: IMAP-UIDs gelten nur innerhalb eines Ordners, ohne `mailbox` sucht der Server in
`INBOX`. Mit Mistral Small ging das im ersten Browsertest schief.

Das globale LibreChat-Agentenlimit steht auf `recursionLimit: 25` / `maxRecursionLimit: 50`
(vorher 8/12, zu knapp für mehrstufige Mailsuchen). Die beiden FAC-Agenten haben weiterhin
ein eigenes gespeichertes Limit von 8. Die
Open-WebUI-Verbindung ist auch in `OWUI_TOOL_SERVER_CONNECTIONS` hinterlegt.

Der Stalwart-Container auf dem Laptop hing zeitweise an keinem Docker-Netz und
veröffentlichte deshalb keine Ports; behoben mit `docker network connect bridge stalwart`.

Geprüft am 16.09.2026: 704 Ordner und Metadaten des Posteingangs über MCP gelesen;
LibreChat lädt beide MCP-Server; Open WebUI bietet Mistral die Mail-Werkzeuge an und das
Modell erzeugt einen passenden `list_mailboxes`-Aufruf. Ein vollständiger Chat im Browser
steht noch aus.

## Kombiniertes Profil „Hausverwaltung · GLM 5.3“

Ein Agent bzw. Modell mit allen lesenden Werkzeugen: 12 FAC-Standardwerkzeuge,
18 Hausverwaltungswerkzeuge aus `agent_tools/fac_contract.py` und 5 Mail-Werkzeuge
(35 insgesamt). LibreChat-Agent in `hv-agent-id.txt`; Open WebUI `hausverwaltung-glm-5-3`
mit den Verbindungen `server:mcp:fac-hv` (dieselbe FAC-URL mit erweitertem
Werkzeugfilter) und `server:mcp:mail`.

Die 18 Hausverwaltungswerkzeuge wurden vor der Freigabe geprüft: Der Aufrufgraph enthält
nur `SELECT`-Abfragen, Frappe-Leseaufrufe und einen Script-Report, keine Schreib-, Commit-
oder Enqueue-Aufrufe. Der Code in `hvp-backend-1` war identisch mit dem Repo-Stand
(Hash-Vergleich von `assistant.py`, `read_api.py`, `fac_tools.py`, `fac_contract.py`).

## LibreChat Code Interpreter (selbst gehostet, Test)

LibreChats Code Interpreter v1.1.0 (`LibreChat-AI/code-interpreter`, Apache-2.0) läuft als
eigenes Compose-Projekt `hv-code-interpreter`. Quelltext in `docker/ai-clients/code-interpreter/src`
(ignoriert), Härtung in `docker/ai-clients/code-interpreter/compose.hv.yaml`, Geheimnisse in
`code-interpreter/.env` (ignoriert, 0600).

```bash
cd docker/ai-clients
docker compose -p hv-code-interpreter --env-file code-interpreter/.env \
  -f code-interpreter/src/docker-compose.yaml -f code-interpreter/compose.hv.yaml up -d
```

Es gibt keine fertigen Images; der erste Build kompiliert u. a. Python 3.14 (Sandbox-Image ca. 5 GB).

Abweichungen vom Upstream-Compose: keine veröffentlichten Ports, keine festen Containernamen,
nur `api` im LibreChat-Netz (Alias `codeapi`), `LOCAL_MODE=false` mit LibreChat-JWT (EdDSA),
Remote-Bridge aus, eigene Secrets und Manifest-Schlüssel, maximal 2 Sandboxen mit 1 GiB RAM.
Die libkrun-MicroVM kann Dockers DNS (127.0.0.11) nicht nutzen; ohne feste Adresse schlug der
Datei-Upload aus der Sandbox mit `ConnectionRefused` fehl. Der Egress-Gateway hat daher im Subnetz
`10.203.0.0/24` die feste IP `10.203.0.10`.

LibreChat: `LIBRECHAT_CODE_BASEURL=http://codeapi:3112/v1`, `CODEAPI_*`-JWT-Variablen in
`compose.yaml`, privater Schlüssel in `.env`, Agent-Fähigkeit `execute_code` in `librechat.yaml`.
Nur der Agent **Hausverwaltung · GLM 5.3** hat `execute_code`.

Geprüft am 17.09.2026: Anfragen ohne bzw. mit falschem Token → 401; Python 3.14 erzeugt
XLSX/DOCX/PDF (Inhalte zurückgelesen), alle drei über `/download` abrufbar; ein anderer Benutzer
erhält 403; Internet und ERPNext aus der Sandbox nicht erreichbar. Nicht enthalten: Tesseract
(OCR) und LibreOffice. Ein Test im Browser-Chat steht noch aus.

## Sichtbare Profile (Stand 17.09.2026)

Beide Clients bieten nur noch **Hausverwaltung · GLM 5.3** an. LibreChat: `modelSpecs` mit
`enforce: true` und `prioritize: true`, die übrigen Agenten bleiben in MongoDB (IDs als Kommentar in
`librechat.yaml`). Open WebUI: alle anderen Modelle per `meta.hidden` ausgeblendet (nicht deaktiviert,
weil das Profil auf `zai-glm-5-3` aufbaut), Arena-Modell aus, Standardmodell und Standardparameter
(`max_tokens` 8192) über die Admin-API gesetzt. Open WebUI hält diese Werte in seiner Datenbank;
`DEFAULT_MODELS`/`DEFAULT_MODEL_PARAMS` in `compose.yaml` wirken nur bei leerem Daten-Volume.
In Open WebUI bleibt die Fähigkeit „Code Interpreter“ (Pyodide/Jupyter) aus; Dateien und
Berechnungen laufen dort über das Terminal „Dateien & Auswertungen“ (`open-terminal`).

## Große Datenmengen per Code (Stand 17.09.2026)

Direkte Werkzeugantworten landen im Modellkontext und sind deshalb gekappt; Massendaten verarbeitet das
Modell per Skript (LibreChat `run_tools_with_bash`, Programmatic Tool Calling), sodass nur die
Skriptausgabe ins Modell geht.

- `agent_tools/fac_output.py`: FAC-Antworten der Hausverwaltungswerkzeuge ohne UI-Felder (`matches`,
  `candidate_limit`), `hv_query_view` mit `aggregate` ohne Beispielzeilen, Gesamtgröße höchstens 12 000
  Zeichen. Beim Kürzen: `output_truncated`, Hinweis auf `hv_export_view`, `next_offset` zeigt auf die erste
  nicht gelieferte Zeile.
- `hv_query_view` hat einen optionalen `offset` (auch im internen Assistenten verfügbar, Schema dort unverändert).
- Neues FAC-Werkzeug `hv_export_view` (nicht in `FAC_TOOL_NAMES`, also nicht in den eingebauten FAC-Engines):
  bis 1000 Zeilen pro Seite, bis 20 000 Kandidaten, gleiche Rechteprüfung, Antwort nur `rows` + Paging.
- LibreChat-Agent **Hausverwaltung · GLM 5.3**: `hv_export_view` mit `allowed_callers: ["code_execution"]`,
  12 weitere Werkzeuge direkt und per Code; die 12 FAC-Standardwerkzeuge entfernt (25 Werkzeuge,
  vorher 40). `librechat.yaml`: Fähigkeit `programmatic_tools`. `maxContextTokens` 128 000 bei den GLM-Agenten
  (LibreChat kennt `zai-glm-5-3` nicht und nahm sonst 32 000 an).
- Open WebUI (kein Programmatic Tool Calling): Verbindung `fac-hv` nur noch mit den 18 Hausverwaltungswerkzeugen.

Gemessen gegen den FAC-Endpunkt: Zählen von `tenant_contracts` 583 statt 56 398 Zeichen; direkte Abfrage
mit `limit: 100` auf 25 Zeilen / 11 249 Zeichen gekappt; Export aller 364 Verträge in 3 Seiten. Tests:
`agent_tools/test_fac_output.py` (13) und `services/test_fac_assistant.py` (12) im Dev-Stack grün.
Deployment in den Dev-Stack `hvp` per `docker cp` (App nicht gemountet) nach backend und queue-Workern.

## Serienbriefe in LibreChat (Stand 17.09.2026)

Der Agent **Hausverwaltung · GLM 5.3** hat die fünf `agent_mail_merge_*`-Werkzeuge (nur direkt, nicht per
Code) und die Serienbrief-Regeln aus `agent_tools/mail_merge_tools.py` in seiner Anweisung (30 Werkzeuge).
Im Dev-Stack: `hv_agent_link_base_url = http://100.89.21.12:8090`; FAC-API-Benutzer ist `Administrator`,
Entwürfe entstehen daher unter diesem Benutzer. Details in `docs/llm-serienbriefe.md`.
Geprüft: Werkzeuge über MCP gelistet; Vorlagensuche „Bescheinigung“ (1 124 Zeichen) und Steckbrief (1 899
Zeichen) mit echten Vorlagen. `prepare`/`execute` noch nicht über LibreChat getestet. Tests: 17 + 12 grün.
Open WebUI hat die Serienbrief-Werkzeuge nicht.
PDFs im Chat: `agent_mail_merge_get_pdf` (nur `code_execution`) lädt Vorschau- oder Entwurfs-PDFs in die
Code-Sandbox, LibreChat bietet sie als Datei an (Agent jetzt 31 Werkzeuge). Geprüft über MCP ohne Speichern:
Vorlage „Nettokaltmieterhöhung mit BK psch für S“, 2 Seiten, 102 332 Bytes, SHA-256 identisch mit der Vorschau.
Die Vorlage „BKMietschuldenfreiheitsbescheinigung“ wird von der Serienbrief-API mit
`CONTRACT_IDENTITY_INVALID` abgelehnt (verweist auf den aktuellen statt den ausgewählten Mietvertrag).
Tests: `test_fac_output.py` 21, `test_fac_assistant.py` 12 grün; `test_mail_merge_api.py` hat im Dev-Stack
7 Fehler (Mock im Redis-Cache bei `nowdate()`), identisch mit dem unveränderten Stand von `mail_merge_api.py`.

## Kosten und Denk-Stufe in LibreChat (Stand 17.09.2026)

`interface.contextCost` zeigt Tokens und Kosten pro Chat (Kreis-Anzeige am Eingabefeld). Preise für
`zai-glm-5-3` als `tokenConfig` am Mistral-Endpunkt (USD/1M: Input 1,4, Cache 0,14, Output 4,4),
Anzeige in EUR mit festem Kurs 0,85 (aus Mistrals EUR-Preisen).

GLM 5.3 unterstützt `reasoning_effort` nur mit `low`, `high`, `max`; ohne Angabe verhält es sich etwa wie
`max`. Für Agenten filtert LibreChat `reasoning_effort` aus Chat-Parametern, daher zwei Agenten mit
identischen Anweisungen und Werkzeugen, nur `model_parameters.reasoning_effort` unterschiedlich:
**Hausverwaltung · gründlich** (`high`, `hv-agent-id.txt`, Standard) und **Hausverwaltung · schnell**
(`low`, `hv-fast-agent-id.txt`). Änderungen an Anweisungen oder Werkzeugen in beiden Agenten nachziehen.
Die LibreChat-API lehnt Aufrufe ohne Browser-User-Agent mit „Illegal request" ab.
