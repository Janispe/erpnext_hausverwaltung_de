# Agent-Pilot für ERPNext

Orchestrator organisiert die Worker und ihre Git-Arbeitskopien. Compose startet eine echte ERPNext-Site für einen Ticket-Stand. Der erste Lauf verwendet einen Preview-Slot und zwei Rollen: Entwicklung und unabhängige Browser-Abnahme.

## Workspace und Docker

- Einen eigenen Ordner mit den Git-Repos `hausverwaltung`, `process_engine`, `mail_merge` und `thunderbird_hausverwaltung` als direkten Unterordnern in Orchestrator als **Workspace** öffnen. In **Add project → Open a workspace** vor dem Bestätigen die vier Repos prüfen.
- Die Arbeitskopien müssen auf dem Rechner des Docker-Daemons liegen. Auf dem freigegebenen Dev-Rechner aktiviert `HV_PREVIEW_LOCAL_DOCKER=1` den lokalen Docker-Kontext `default`. Jede Vorschau verwendet ein eigenes `hv-qa-<ticket>`-Compose-Projekt. Die vorhandene Dev-Site auf 8090 bleibt separat. Für einen dedizierten Daemon unterstützt der Launcher weiterhin den Kontext `hv-preview`.
- Nur synthetische Geschäftsdaten verwenden. Der Pilot verwendet seine eigenen Datenbank- und Site-Volumes. Produktionsverzeichnisse, Produktionsnetz, Produktionssocket, echte Backups, Zugangsdaten und die private Peters-App gehören außerhalb des Workspaces. Lokale Worker und Freigaben verwenden.

## Eine Vorschau prüfen

Im `hausverwaltung`-Worktree der Orchestrator-Session ausführen, auf dem freigegebenen Dev-Rechner.

```bash
export HV_PREVIEW_LOCAL_DOCKER=1
./scripts/agent_preview.sh up pilot-1
./scripts/agent_preview.sh seed pilot-1
./scripts/agent_preview.sh test pilot-1
ao preview http://127.0.0.1:8180
```

Für einen Desk-Test mit bereits lokal vorhandenen Images `HV_PREVIEW_USE_BASE_IMAGE=1` zusammen mit `HV_PREVIEW_LOCAL_DOCKER=1` setzen. Damit startet Compose das in der Konfiguration gepinnte ERPNext-Basisimage und überspringt den zusätzlichen Chromium-Image-Build. Die PDF-Ausgabe wird in diesem Modus separat geprüft.

Beim Anlegen der Vorschau baut Bench die Assets der vier eingebundenen Apps. Frappe und ERPNext verwenden die zum Image passenden CSS- und JavaScript-Dateien.

Der Entwickler öffnet im Desk einen synthetischen Mietvertrag und prüft den betroffenen Ablauf. Bei Python-Änderungen `./scripts/agent_preview.sh restart pilot-1` ausführen. Für Schemaänderungen gibt es `migrate`, für Assets der vier Apps `build`. Anschließend den Ablauf im Desk wiederholen.

Der QA-Worker erhält die Preview-URL, die Commit-SHAs aller vier Repos und die konkreten Schritte. Für die Abschlussprüfung mit einer frischen Datenbank aus diesen Commits starten und den Ablauf selbst ausführen. Ein AO-PR-Reviewer ergänzt das Code-Review. Die interaktive Abnahme läuft als eigene Worker-Aufgabe. Screenshots und Testausgabe bleiben Belege zum getesteten Stand.

```bash
./scripts/agent_preview.sh status pilot-1
./scripts/agent_preview.sh stop pilot-1
```

`stop` lässt die Volumes und die während der Tests angelegten Datensätze bestehen. Für einen neuen isolierten Ausgangsstand eine neue Ticketkennung verwenden. Bei einem zweiten gleichzeitig laufenden Preview einen anderen freien Loopback-Port über `HV_PREVIEW_HTTP_PORT` setzen und je Ticket die zugehörige URL öffnen.

## Tests

Alle Tests laufen über einen Einstieg: `./scripts/agent_ci.sh`. Er baut für jeden Lauf eine frische Site aus den committeten Ständen der vier Repos auf, führt die gewählte Stufe mit `scripts/hv_tests.sh` aus und entfernt Site, Container und Volumes danach wieder.

```bash
./scripts/agent_ci.sh                # quick: Smoke-Test Mietvertrag, Standard vor jedem Push
./scripts/agent_ci.sh --python       # alle Python-Tests der App und unter tests/
./scripts/agent_ci.sh --e2e          # KI-Vorschläge (HTTP, Nur-Lesen, Playwright), Bankimport (Vitest, Playwright), Node-Tests
./scripts/agent_ci.sh --all          # python und e2e, je auf einer frischen Site
./scripts/agent_ci.sh --build-image  # CI-Image mit Chrome-Bibliotheken bauen (einmalig und nach ERPNext-Updates)
```

- Getestet wird der Commit, nicht der Arbeitsbaum. Vorher committen.
- Bericht und Protokolle je Schritt: `.git/agent-ci/reports/<Zeit>-<Stufe>-<Commit>/summary.txt`, dazu `python-app.junit.xml` und Playwright-Screenshots bei Fehlern.
- Das CI-Image `hausverwaltung/frappe-chrome:ci` ergänzt das Basisimage aus `compose.dev.yml` (`frappe/erpnext:v16.14.0`) um die Chrome-Bibliotheken; ein anderes Basisimage über `HV_CI_BASE_IMAGE`. Ohne dieses Image nimmt die CI das Basisimage aus `compose.dev.yml`; dann schlagen die PDF-Tests fehl.
- Für `--e2e` braucht der Rechner Node 20 oder neuer (`HV_TEST_NODE_DIR` oder `~/.local/node/current/bin`), `uv` und Internet für npm und die Playwright-Browser.
- Parallele Läufe aus verschiedenen Arbeitsordnern brauchen verschiedene Ports über `HV_PREVIEW_HTTP_PORT`.
- Fehlersuche: `HV_TEST_MODULE=<modul> ./scripts/agent_ci.sh` führt statt des Smoke-Tests ein einzelnes Testmodul aus. Abgefangene Fehler der Site stehen in `error-log.json` im Bericht.
- Ein Schritt kann „übersprungen“ melden. Derzeit betrifft das Playwright für die KI-Vorschläge: Der Test wechselt das Theme über den Einstellungsdialog neuerer Frappe-Versionen (Produktion 16.55), den das CI-Image mit Frappe 16.16 noch nicht hat. Er läuft wieder mit, sobald Dev und CI ein produktionsnahes Image nutzen.
- Die alten Cypress-Specs unter `cypress/` laufen nicht mit. Sie werden nach Playwright umgezogen.

## Aufgaben für den ersten Durchlauf

1. **Entwicklung:** Eine kleine sichtbare Änderung in einem Formular, ausschließlich im zugehörigen Worktree. Im Desk mit einem Demo-Vertrag prüfen und die vier Git-Stände festhalten.
2. **QA:** Den Ablauf auf der Vorschau desselben Commit-Satzes unabhängig wiederholen und Ergebnis, Beobachtung und gegebenenfalls Screenshot festhalten. Eine Änderung, die mehrere Repos betrifft, in einem Ticket bearbeiten und die zusammengehörigen PRs im Ergebnis verlinken.

Bei Änderungen an Thunderbird den Bridge-Test mit synthetischen Daten ausführen.

```bash
./scripts/agent_preview.sh test pilot-1 thunderbird_hausverwaltung.thunderbird_hausverwaltung.integrations.test_thunderbird_bridge
```
