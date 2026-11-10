# Agent-Pilot für ERPNext

Orchestrator organisiert die Worker und ihre Git-Arbeitskopien. Compose startet eine echte ERPNext-Site für einen Ticket-Stand. Der erste Lauf verwendet einen Preview-Slot und zwei Rollen: Entwicklung und unabhängige Browser-Abnahme.

## Workspace und Docker

- Einen eigenen Ordner mit den Git-Repos `hausverwaltung`, `process_engine` und `mail_merge` als direkten Unterordnern in Orchestrator als **Workspace** öffnen. In **Add project → Open a workspace** vor dem Bestätigen die drei Repos prüfen.
- Orchestrator, die Arbeitskopien und der Dev-Docker-Daemon müssen auf demselben Dev-System verfügbar sein. Der Pilot verlangt den expliziten Docker-Kontext `hv-preview`. Auf einem physischen Host kommt dafür ein eigener Rootless-Daemon unter dem Dev-Benutzer infrage. In einer dedizierten Dev-VM ist auch deren lokaler Standardsocket möglich. In beiden Fällen braucht der Worker eine echte Berechtigungsgrenze gegenüber der Produktion.
- Nur synthetische Geschäftsdaten verwenden. Der Pilot verwendet seine eigenen Datenbank- und Site-Volumes. Produktionsverzeichnisse, Produktionsnetz, Produktionssocket, echte Backups, Zugangsdaten und die private Peters-App gehören außerhalb des Workspaces. Lokale Worker und Freigaben verwenden.

## Eine Vorschau prüfen

Im `hausverwaltung`-Worktree der Orchestrator-Session ausführen, sobald der separate Dev-Daemon bereitsteht:

```bash
./scripts/agent_preview.sh up pilot-1
./scripts/agent_preview.sh seed pilot-1
./scripts/agent_preview.sh test pilot-1
ao preview http://127.0.0.1:8180
```

Der Entwickler öffnet im Desk einen synthetischen Mietvertrag und prüft den betroffenen Ablauf. Bei Python-Änderungen `./scripts/agent_preview.sh restart pilot-1` ausführen. Für Schemaänderungen gibt es `migrate`, für Hausverwaltungs-Assets `build`. Anschließend den Ablauf im Desk wiederholen.

Der QA-Worker erhält die Preview-URL, die Commit-SHAs aller drei Repos und die konkreten Schritte. Für die Abschlussprüfung mit einer frischen Datenbank aus diesen Commits starten und den Ablauf selbst ausführen. Ein AO-PR-Reviewer ergänzt das Code-Review. Die interaktive Abnahme läuft als eigene Worker-Aufgabe. Screenshots und Testausgabe bleiben Belege zum getesteten Stand.

```bash
./scripts/agent_preview.sh status pilot-1
./scripts/agent_preview.sh stop pilot-1
```

`stop` lässt die Volumes und die während der Tests angelegten Datensätze bestehen. Für einen neuen isolierten Ausgangsstand eine neue Ticketkennung verwenden. Bei einem zweiten gleichzeitig laufenden Preview einen anderen freien Loopback-Port über `HV_PREVIEW_HTTP_PORT` setzen und je Ticket die zugehörige URL öffnen.

## Aufgaben für den ersten Durchlauf

1. **Entwicklung:** Eine kleine sichtbare Änderung in einem Formular, ausschließlich im zugehörigen Worktree. Im Desk mit einem Demo-Vertrag prüfen und die drei Git-Stände festhalten.
2. **QA:** Den Ablauf auf der Vorschau desselben Commit-Satzes unabhängig wiederholen und Ergebnis, Beobachtung und gegebenenfalls Screenshot festhalten. Eine Änderung, die mehrere Repos betrifft, in einem Ticket bearbeiten und die zusammengehörigen PRs im Ergebnis verlinken.
