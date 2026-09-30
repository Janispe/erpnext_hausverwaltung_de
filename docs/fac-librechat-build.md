# FAC und LibreChat auf dem getrennten Produktionsserver aktualisieren

Der Produktionsserver ist von hier aus nicht erreichbar. Diese Dateien liegen deshalb im **Hausverwaltung-Repo**, das auf dem Server per `git pull` aktualisiert wird. Der Server benötigt einen Checkout dieses Repos und seinen bisherigen Frappe-Docker-Stack. Die Befehle unten führt der Betreiber dort selbst aus.

## Ursache und Updateweg

Das laufende FAC-Image enthielt älteren Hausverwaltungs-Code: Serienbrief-Werkzeuge und `hv_export_view` fehlten im MCP-Katalog. Zudem zeigte das lokale Docker-`update.sh` zeitweise auf andere Image-Tags als Compose. Sein Runtime-Build setzte nicht versionierte `local_apps`-Verzeichnisse voraus. Ein `git pull` allein hätte diese Dateien nicht auf einen zweiten Rechner gebracht.

Der portable Weg ist [scripts/update_fac_production.sh](../scripts/update_fac_production.sh). Er baut FAC 2.5.1 auf dem gepinnten Commit `7ddc433772f4ade794d9f5ee30b7d9ea0af2a487` und den **gerade ausgecheckten** Hausverwaltungs-Code auf das bestehende ERP-Image. Er behält damit die übrigen Apps und deren Image-Anpassungen. Ein erzeugter Compose-Override weist Backend, Frontend und Worker demselben neuen Image zu. Die Ausgangs-Compose-Datei und ihre Bind-Mounts werden nicht überschrieben.

Der Basis-Stack muss die benötigten Apps (`erpnext`, `process_engine`, `mail_merge`, `hausverwaltung`) bereits enthalten. Falls das Basis-Image neu gebaut werden soll, zuerst den bisherigen Basis-Build durchführen und danach den FAC-Updateweg ausführen. Ein späterer Start ohne den generierten Compose-Override kann wieder das Basis-Image verwenden.

## Vor dem Update

Die Änderungen dieses Repos müssen zuerst **committet und in den Branch gepusht** sein, den der Produktionsserver per `git pull` bezieht. Uncommittete Dateien vom Entwicklungsrechner sind dort nicht verfügbar. Der Produktions-Checkout muss nach `git pull` sauber sein; das Update-Skript prüft dies.

Auf dem Produktionsserver den Pfad zum Frappe-Docker-Verzeichnis, den Site-Namen und den ERPNext-Benutzer des LibreChat-FAC-API-Schlüssels ermitteln. Im Beispiel heißen sie `/pfad/zum/frappe_docker`, `frontend` und `Administrator`; diese Werte bei Bedarf ersetzen. Das Basis-Compose muss `backend` und `frontend` enthalten. Vorhandene Hotfix-Bind-Mounts auf `hooks.py` müssen weiterhin `FAC_TOOL_HOOKS` registrieren.

## Build ohne Umschalten

```bash
cd /pfad/zum/hausverwaltung
git pull --ff-only
./scripts/update_fac_production.sh \
  --docker-root /pfad/zum/frappe_docker \
  --site frontend --fac-user Administrator --build-only
```

`--build-only` baut und prüft ein neues Kandidaten-Image. Es ändert keine Container und keine Site. Der Basis-Image-Tag wird aus dem `backend` der Ausgangs-Compose-Datei gelesen. Bei einem anderen Basis-Image `--base-image IMAGE` angeben.

## Produktions-Update

```bash
cd /pfad/zum/hausverwaltung
./scripts/update_fac_production.sh \
  --docker-root /pfad/zum/frappe_docker \
  --site frontend --fac-user Administrator
```

Das Skript erstellt zunächst ein Site-Backup **mit Dateien**. Es prüft danach das Kandidaten-Image auf FAC und die benötigten Werkzeuge, schreibt im Docker-Verzeichnis `compose.fac.generated.json`, startet die App-Dienste mit diesem Override, installiert FAC bei Bedarf, migriert die Site und aktiviert nur die Hausverwaltungs-FAC-Werkzeuge für den angegebenen API-Benutzer. Andere FAC-Plugins bleiben konfiguriert. `agent_mail_merge_execute` ist das einzige schreibende Hausverwaltungswerkzeug und speichert nur geprüfte Serienbrief-Entwürfe; die bestehenden ERPNext-Berechtigungen gelten weiter.

Für spätere Compose-Befehle beide Dateien verwenden:

```bash
cd /pfad/zum/frappe_docker
docker compose -p hvp -f compose.custom.yaml -f compose.fac.generated.json ps
```

Wenn der Basis-Stack später erneut mit seinem eigenen Update-Skript gebaut oder gestartet wird, anschließend `update_fac_production.sh` erneut ausführen. Der neue Basisstand wird dadurch wieder mit FAC und dem aktuellen Hausverwaltungs-Checkout kombiniert.

## MCP mit dem LibreChat-Benutzer abnehmen

Den vollständigen Wert des LibreChat-`FAC_AUTH_HEADER` verdeckt eingeben. Keine API-Schlüssel in Befehlszeilen, Dateien oder Chatnachrichten schreiben:

```bash
cd /pfad/zum/frappe_docker
export FAC_MCP_URL='http://frontend:8080/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp'
read -rsp 'FAC_AUTH_HEADER: ' FAC_AUTH_HEADER; printf '\n'
export FAC_AUTH_HEADER
docker compose -p hvp -f compose.custom.yaml -f compose.fac.generated.json exec -T \
  -e FAC_MCP_URL -e FAC_AUTH_HEADER backend \
  ./env/bin/python apps/hausverwaltung/scripts/verify_fac_mcp.py
unset FAC_AUTH_HEADER
```

Die Prüfung ruft `tools/list`, die Serienbrief-Vorlagenliste und eine Exportseite auf und erkennt auch fachliche Fehler innerhalb einer erfolgreichen HTTP-Antwort. Sie erstellt keinen Serienbrief und ruft kein LLM auf. Die isolierte Testsite liefert 41 Werkzeuge; auf Produktion können weitere FAC-Plugins die Anzahl verändern. Danach einen neuen LibreChat-Chat beginnen, damit die Werkzeugliste neu geladen wird.

Für große Datenmengen `hv_export_view` innerhalb von `run_tools_with_bash` seitenweise verarbeiten und nur das Ergebnis der Auswertung ausgeben. Die bereitgestellten Bash-Werkzeugfunktionen gelten im laufenden Shell-Prozess. `bash datei.sh` startet einen Kindprozess ohne diese Funktionen; ein Skript muss im selben Prozess geladen werden. `candidates_truncated=true` bedeutet, dass der Export nicht vollständig ist. Gleichzeitige Datenänderungen können Offset-Seiten verschieben; für revisionsfeste Abrechnungen einen unveränderlichen Datenstand verwenden.

## Rückkehr zum vorherigen Image

Das Update-Skript sichert einen vorhandenen Override als `compose.fac.generated.json.bak.<Zeitstempel>`. Bei einem fehlgeschlagenen App-Start den alten Override wiederherstellen und `docker compose -p hvp -f compose.custom.yaml -f compose.fac.generated.json up -d` ausführen. Nach einer bereits ausgeführten Datenbankmigration erst deren Auswirkungen prüfen; ein reiner Image-Rollback macht Datenbankänderungen nicht rückgängig. Das vor dem Update erzeugte Site-Backup bleibt dafür verfügbar.

Ein vorhandenes `apps.json` mit eingebettetem GitHub-Zugangstoken sollte separat bereinigt und der Token rotiert werden. Der FAC-Overlay-Build liest diese Datei nicht.
