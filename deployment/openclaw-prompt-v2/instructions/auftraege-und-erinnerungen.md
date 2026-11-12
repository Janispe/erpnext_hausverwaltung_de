# Aufträge und Erinnerungen

Eine normale Gateway-Aufgabe läuft weiter, auch wenn der Nutzer die Ansicht
schließt. Für jetzt beauftragte parallele Arbeit gilt
`instructions/parallelauftraege.md`. Diese Anleitung betrifft ausdrücklich
spätere oder wiederkehrende Aufträge und mehrstufige Arbeitsstände.

## Spätere und wiederkehrende Aufträge

`automations` mit begrenzter Laufzeit und klar beschriebenem Auftrag verwenden.

- Aus einem OpenClaw-Chat `sessionTarget: "current"` und
  `delivery.mode: "announce"`; das Ergebnis erscheint im selben Chat. Keinen
  Kanal `webchat` erfinden. Externe Kanäle nur mit eingerichtetem,
  authentifiziertem Empfänger.
- Anlegen heißt in dieser Version `action: "add"`, nicht `create`. Bestätigte
  Form, statt eine Syntax zu erfinden:
  `automations({action:"add",job:{name:"...",schedule:{kind:"at",at:"ISO-8601"},sessionTarget:"current",payload:{kind:"agentTurn",message:"Erinnere den Nutzer jetzt: ...; antworte sichtbar, nicht NO_REPLY.",lightContext:true,toolsAllow:[],timeoutSeconds:60},delivery:{mode:"announce"},deleteAfterRun:true}})`
- Bei reinen Erinnerungen muss der Auftragstext ausdrücklich eine sichtbare
  Nachricht verlangen („antworte sichtbar, nicht NO_REPLY“). Ein nackter
  Erinnerungstext kann sonst still erledigt werden. Ohne nötige Datenabfrage:
  kurze Laufzeit, `lightContext: true`, `toolsAllow: []` im `payload`.
- Datum, Uhrzeit und Zeitzone `Europe/Berlin` bestätigen; das Datum nie aus
  einem alten Verlauf übernehmen. Nach Erfolg den zurückgegebenen Termin nennen.
- Genau den beauftragten Job anlegen, keine vorsorglichen Zusatzjobs.
  Eindeutige, sprechende Job-IDs verwenden, damit eine Wiederholung nichts
  doppelt anlegt.
- Chat-Zustellung und Android-Benachrichtigung sind getrennt: eine zugestellte
  Chatnachricht beweist keine Systembenachrichtigung.

## Hintergrundbefehle

Ergebnis einsammeln oder eine echte Abschlussfortsetzung einrichten. Ein bloß
gestarteter Prozess ist keine Fertigmeldung.

## Mehrstufige Arbeit

`tasks/<id>/STATUS.md` führen: Auftrag, Zeitraum, Status, erledigte Schritte,
ERPNext-Entwurfs-IDs, fehlende Informationen, nächster Schritt. Vor erneutem
Schreiben vorhandene Entwürfe und Arbeitsstände prüfen. Fehlen Angaben, Status
`wartet auf Rückfrage` setzen und eine konkrete Frage im Auftragschat stellen,
statt in einer Wiederholungsschleife weiterzulaufen.
