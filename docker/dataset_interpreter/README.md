# Lokaler Dataset-Interpreter

Der Dienst fuehrt vom Mistral-Basic-Agenten erzeugten Python-Code auf einem bereits lokal
materialisierten und berechtigungsgeprueften Dataset aus. Er hat keine Datenbank-Zugangsdaten,
kein Netzwerk und keinen Docker-Socket. Die Kommunikation mit Frappe erfolgt nur ueber einen
Unix-Socket in einem gemeinsamen Docker-Volume.

Die Compose-Erweiterung `compose.dataset-interpreter.yaml` wird zusaetzlich zur normalen
Frappe-Compose-Datei geladen. Compose loest relative Build-Pfade am Verzeichnis der ersten
Compose-Datei auf. Liegt die App dort nicht unter `apps/hausverwaltung`, muss deshalb der
absolute Build-Kontext gesetzt werden:

```bash
HV_DATASET_INTERPRETER_CONTEXT=/absoluter/pfad/apps/hausverwaltung/docker/dataset_interpreter \
docker compose -f compose.yaml -f /absoluter/pfad/apps/hausverwaltung/compose.dataset-interpreter.yaml up -d --build
```

Die Frappe-Container muessen als Gruppe `1000` auf den Socket zugreifen koennen. Fuer Images
mit einer anderen GID wird `HV_DATASET_INTERPRETER_SOCKET_GID` beim Sidecar entsprechend
angepasst.

## Grenzen

- maximal 5.000 Zeilen pro lokalem Dataset (durch die Dataset-API)
- maximal 8 MiB Eingabe und 20.000 Zeichen Python-Code
- maximal 12 Sekunden Laufzeit, 1 CPU, 768 MiB RAM und 64 Prozesse
- maximal 64 KiB strukturiertes Ergebnis
- `result` muss JSON-kompatibel sein; `stdout` ist auf 16.000 Zeichen begrenzt

Der Code erhaelt `rows`, `field_types`, `pd`, `np`, `math`, `statistics`, `datetime` und
`Decimal`. Echte Dokument-IDs sind nur enthalten, wenn das Modell beim Tool-Aufruf das Feld
`name` ausdruecklich anfordert.
