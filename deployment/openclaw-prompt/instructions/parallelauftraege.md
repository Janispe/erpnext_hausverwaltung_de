# Parallelauftraege

## Parallele Hintergrundauftraege

Der Hauptchat koordiniert, bis zu fuenf native Unteragenten je Auftragchat arbeiten
gleichzeitig. Jeder bekommt nur einen konkret beauftragten Teilauftrag, einen
eindeutigen `taskName`, ein knappes Ziel und die benoetigten Eingabepfade. Setze
`runtime: "subagent"`, `mode: "run"`, `sandbox: "require"`, `context: "isolated"`,
`expectsCompletionMessage: true`, `cleanup: "keep"` und einen begrenzten
`runTimeoutSeconds` (standardmaessig 1800). `completionTarget` weglassen, damit
normale Fertigmeldungen beim Auftraggeber ankommen; kein collect/Swarm/ACP verwenden.
Beispiel: `sessions_spawn({taskName:"mietpruefung",label:"Mietzahlungen pruefen",
task:"... konkrete Eingaben, Ziel und tasks/<id>/STATUS.md ...",runtime:"subagent",
mode:"run",sandbox:"require",context:"isolated",cleanup:"keep",
expectsCompletionMessage:true,runTimeoutSeconds:1800})`.

Nur unabhaengige Arbeit parallelisieren. Mehrere Schreiber auf denselben ERPNext-
Datensaetzen/Serienbrief-Laeufen sind nicht unabhaengig: erst lesen/planen, dann
Schreibschritte geordnet ausfuehren. Kein Unteragent darf weitere Unteragenten,
Termine oder Kontrollroutinen anlegen. Alle behalten die vorhandenen MCP-Rechte;
Die gleiche Trennung zwischen direkten Fachwerkzeugen und Code Mode gilt fuer Unteragenten. Keine Host-Shell/Gateway-Konfiguration freigeben.

Jeder Auftrag arbeitet in `tasks/<eindeutige-id>/`, Ergebnisse unter
`output/<eindeutige-id>/`. Nicht in Dateien anderer Auftraege, USER.md, MEMORY.md
oder AGENTS.md schreiben; der Hauptagent uebernimmt neue gemeinsame Notizen.
Aufwendige Python-/Office-Verarbeitung teilen sich alle in derselben begrenzten
Sandbox. Dafuer `flock -w 120 /tmp/openclaw-analysis.lock <Befehl>` verwenden,
z.B. `flock -w 120 /tmp/openclaw-analysis.lock python3 scripts/auswertung.py`.
Lock-Wartefehler als Ressourcenwartezeit melden, nicht endlos neu versuchen.

Nach Annahme der gestarteten Unteragenten dem Nutzer die Task-Namen bestaetigen
und die normale Antwort beenden. Ergebnisse kommen durch die native
Fertigmeldungs-Kette, ohne Status-Polling oder sleep-Schleifen. Verwende
`sessions_yield` nur wenn dieser Turn gesammelt auf die Ergebnisse warten soll.
Bei neuen Auftraegen zuerst einmal `subagents` mit action=list pruefen: bereits
laufende Arbeit nicht erneut starten. Weitere Auftraege als wartend in der
Aufgabenliste speichern; ein freier Slot wird nach einer Fertigmeldung neu belegt.
Das native Limit ist je Auftragchat, kein globaler Grenzwert: keine weiteren
Fuenfer-Batches in anderen Chats starten, solange dieser Batch noch laeuft.

Bei fehlenden fachlichen Eingaben schreibt der Unteragent STATUS=wartet auf
Rueckfrage und beendet seinen Lauf mit `RUECKFRAGE [taskName]: <konkrete Frage>`.
Der Hauptagent stellt diese Frage sofort sichtbar im urspruenglichen Chat;
andere Auftraege duerfen weiterlaufen. Nicht still auf eine spaetere Nachricht
warten. Nach der Nutzerantwort den gespeicherten Stand und schon erfolgte
ERPNext-Schreibschritte pruefen, dann nur die betroffene Aufgabe fortsetzen.
`sessions_send` darf nur eigene Kinder steuern/fortsetzen; keine fremden Sessions.

Ein beendeter Unteragent mit Rueckfrage ist KEIN abgeschlossener Fachauftrag.
Die Aufgabe bleibt `wartet auf Rueckfrage`, bis die Antwort verarbeitet ist.
Vor jeder fachlichen Fertigmeldung prueft der Hauptagent STATUS.md der betroffenen
Aufgabe. Ergebnisdatei und STATUS.md muessen uebereinstimmen. Nach einer Fortsetzung
muss STATUS.md auf `abgeschlossen` stehen und die beantwortete Frage dokumentieren;
dies ist Pflicht, keine optionale Notiz. Hat ein Kind nur die Ergebnisdatei
aktualisiert, korrigiert der Hauptagent genau diesen Status vor seiner Fertigmeldung.
Nicht "alle Auftraege abgeschlossen" behaupten, solange eine Aufgabe noch wartet.

Fertigmeldungen enthalten Task-Name, Ergebnis, vorhandene Dateianhaenge und offene
Punkte. Timeout/Abbruch/Neustart sind kein Erfolg; vorhandenen Stand sichern und
genau benennen. Keine unkontrollierten Neustarts oder Retry-Ketten. Auf ausdrueckliches
"stoppe ..." den betroffenen nativen Run mit `subagents` action=cancel stoppen;
`/stop` im Auftragchat stoppt dessen laufende Kindauftraege.
