# Parallele Teilaufträge

Gilt für jetzt beauftragte, voneinander unabhängige Teilaufgaben. Für
gespeicherte Serienaufträge gilt stattdessen `instructions/warteschlangen.md`.

## Starten

- Der Hauptchat koordiniert; bis zu fünf native Unteragenten je Auftragschat
  arbeiten gleichzeitig. Das Limit gilt je Chat: keine weiteren Fünfer-Gruppen in
  anderen Chats starten, solange diese noch läuft.
- Vorher einmal `subagents` mit `action=list` prüfen und bereits laufende
  Arbeit nicht erneut starten. Weitere Teilaufträge als wartend in der
  Aufgabenliste notieren; ein Platz wird nach einer Fertigmeldung frei.
- Jeder Unteragent bekommt genau einen Teilauftrag, einen eindeutigen
  `taskName`, ein knappes Ziel und die nötigen Eingabepfade. Beispiel:
  `sessions_spawn({taskName:"mietpruefung",label:"Mietzahlungen prüfen",task:"... konkrete Eingaben, Ziel und tasks/<id>/STATUS.md ...",runtime:"subagent",mode:"run",sandbox:"require",context:"isolated",cleanup:"keep",expectsCompletionMessage:true,runTimeoutSeconds:1800})`
- `completionTarget` weglassen, damit Fertigmeldungen beim Auftraggeber
  ankommen. Kein collect, Swarm oder ACP.
- Danach dem Nutzer die Task-Namen bestätigen und die Antwort beenden.
  Ergebnisse kommen über die native Fertigmeldung, ohne Polling oder
  sleep-Schleifen. `sessions_yield` nur, wenn dieser Turn gesammelt auf die
  Ergebnisse warten soll.

## Was parallel laufen darf

Nur unabhängige Arbeit. Mehrere Schreiber auf denselben ERPNext-Datensätzen
oder Serienbriefläufen sind nicht unabhängig: erst parallel lesen und planen,
dann die Schreibschritte geordnet nacheinander ausführen.

Unteragenten haben dieselben MCP-Rechte und dieselbe Trennung zwischen direkten
Fachwerkzeugen und Code Mode. Keine Host-Shell und keine Gateway-Konfiguration
freigeben.

## Dateien und Ressourcen

- Jeder Teilauftrag arbeitet in `tasks/<eindeutige-id>/`, Ergebnisse unter
  `output/<eindeutige-id>/`. Nicht in Dateien anderer Aufträge, `USER.md`,
  `MEMORY.md` oder `AGENTS.md` schreiben.
- Alle teilen sich dieselbe knappe Sandbox. Aufwendige Python- oder
  Office-Verarbeitung deshalb mit Sperre ausführen, z. B.
  `flock -w 120 /tmp/openclaw-analysis.lock python3 scripts/auswertung.py`.
  Eine abgelaufene Wartezeit als Ressourcenengpass melden, nicht endlos
  wiederholen.

## Rückfragen

Fehlen fachliche Angaben, setzt der Unteragent in STATUS.md `wartet auf
Rückfrage` und endet mit `RUECKFRAGE [taskName]: <konkrete Frage>`. Der
Hauptagent stellt die Frage sofort sichtbar im ursprünglichen Chat; andere
Teilaufträge laufen weiter. Nach der Antwort zuerst den gespeicherten Stand und
bereits erfolgte ERPNext-Schreibschritte prüfen, dann nur die betroffene Aufgabe
fortsetzen. `sessions_send` nur an eigene Kinder.

## Abschluss

- Ein beendeter Unteragent mit Rückfrage ist kein erledigter Auftrag; die
  Aufgabe bleibt `wartet auf Rückfrage`, bis die Antwort verarbeitet ist.
- Vor jeder Fertigmeldung prüft der Hauptagent STATUS.md der Aufgabe.
  Ergebnisdatei und STATUS.md müssen übereinstimmen. Nach einer Fortsetzung steht
  STATUS.md auf `abgeschlossen` und dokumentiert die beantwortete Frage; hat ein
  Kind nur die Ergebnisdatei aktualisiert, korrigiert der Hauptagent den Status.
- „Alle Aufträge abgeschlossen“ erst melden, wenn keine Aufgabe mehr wartet.
- Fertigmeldungen enthalten Task-Name, Ergebnis, Anhänge und offene Punkte.
  Timeout, Abbruch oder Neustart sind kein Erfolg: vorhandenen Stand sichern und
  genau benennen. Keine unkontrollierten Neustarts oder Wiederholungsketten.

## Stoppen

Auf ausdrückliches „stoppe …“ den betroffenen Lauf mit `subagents`
`action=cancel` beenden. `/stop` im Auftragschat stoppt dessen laufende
Kindaufträge.
