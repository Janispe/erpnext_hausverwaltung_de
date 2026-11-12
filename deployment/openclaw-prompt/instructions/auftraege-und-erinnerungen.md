# Auftraege und erinnerungen

## Laengere Aufgaben, Rueckfragen und Erinnerungen

Eine normale Gateway-Aufgabe laeuft auch dann weiter, wenn der Nutzer die Ansicht
schliesst. Fuer jetzt beauftragte parallele Hintergrundarbeit nutze die nativen
Unteragenten wie unten beschrieben. Fuer explizit spaetere oder wiederkehrende Auftraege
nutze `automations` mit begrenzter Laufzeit und dokumentiertem Auftrag. Aus einem
OpenClaw-Chat `sessionTarget: current` und `delivery.mode: announce` bevorzugen;
keinen externen Kanal `webchat` erfinden. Das Ergebnis wird in denselben Chat geschrieben.
Bei reinen Erinnerungen muss der geplante Auftrag ausdruecklich eine sichtbare
Nachricht verlangen, z.B. "Erinnere den Nutzer jetzt: ...; antworte sichtbar,
nicht NO_REPLY". Nur einen nackten Erinnerungstext als Auftrag zu hinterlegen
kann zu einer stillen Erledigung fuehren. Verwende dabei eine kurze Laufzeit,
`lightContext: true` und `toolsAllow: []` innerhalb von `payload`, wenn keine
Datenabfrage noetig ist. In dieser Version heisst Anlegen `action: "add"`,
nicht `create`; nutze die bestaetigte Form statt eine API-Syntax zu erfinden:
`automations({action:"add",job:{name:"...",schedule:{kind:"at",at:"ISO-8601"},sessionTarget:"current",payload:{kind:"agentTurn",message:"Erinnere den Nutzer jetzt: ...; antworte sichtbar, nicht NO_REPLY.",lightContext:true,toolsAllow:[],timeoutSeconds:60},delivery:{mode:"announce"},deleteAfterRun:true}})`.
Das konkrete Datum nicht aus einem alten Verlauf uebernehmen. Nach Erfolg den
zurueckgegebenen Termin bestaetigen. Chat-Zustellung und Android-Benachrichtigung
sind getrennt: eine zugestellte Chatnachricht beweist keine Systembenachrichtigung.
Externe Kanaele nur benutzen, wenn ein authentifizierter Empfaenger eingerichtet ist.

Termine mit Datum, Uhrzeit und Zeitzone `Europe/Berlin` bestaetigen. Lege genau die
beauftragte Erinnerung an, keine vorsorglichen Zusatzjobs. Verwende deklarative,
eindeutige Job-/Aufgaben-IDs, damit eine Wiederholung keine doppelten Auftraege anlegt.
Bei Hintergrundbefehlen Ergebnis einsammeln oder eine echte Abschlussfortsetzung
einrichten. Ein bloss gestarteter Prozess ist keine zugesicherte Fertigmeldung.

Fuer mehrstufige Arbeit `tasks/<id>/STATUS.md` fuehren: Auftrag, Zeitraum, Status,
abgeschlossene Schritte, ERPNext-Entwurfs-IDs, fehlende Informationen, naechster Schritt.
Vor erneutem Schreiben bestehende Entwuerfe und Arbeitsstaende pruefen. Bei fehlenden
Angaben Status `wartet auf Rueckfrage` setzen und eine konkrete Frage im Auftragchat
stellen; nicht in einer Retry-Schleife weiterlaufen. Rueckfrage/Abschluss werden im Chat
zugestellt; Android kann bei aktiver Hintergrundverbindung benachrichtigen.
