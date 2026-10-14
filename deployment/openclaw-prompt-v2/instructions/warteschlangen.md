# Serienaufträge und gespeicherte Warteschlangen

Gilt für ausdrückliche Serienaufträge und dauerhaft gespeicherte Einzelaufträge.
Hat Vorrang vor `instructions/parallelauftraege.md`.

## Vorbereitung

- Zuerst `scripts/TASK-QUEUE.md` vollständig lesen; dort steht die Bedienung.
- Je Fall ein Manifest und eine vollständige `inputs.json` anlegen, dann
  `init`/`manage` der lokalen Steuerung verwenden.
- `INPUT` enthält die konkreten IDs und Freigaben. Andere Kind-Chats derselben
  Serie sind keine Datengrundlage.

## Steuerung

- Die lokale Steuerung startet echte, dauerhaft sichtbare Kind-Chats, übernimmt
  deren Ergebnisse und füllt freie Plätze selbst. Höchstens **zwei** aktive
  Einträge insgesamt.
- Keine eigenen `claim`/`prepare`/`spawn`/`bind`/`finish`-Schritte, kein Polling
  und kein `sessions_yield`.
- Die Kind-Chats haben einen eingeschränkten Werkzeugkatalog: Fehlt ein
  Werkzeug, nur antworten und keine Ersatzwerkzeuge suchen.
- Der Hauptchat berichtet Fragen und Fortschritt.

## Ergebnis und Prüfungen

- `result.json` enthält `input_nonce`, `run_id` sowie `checks` und `artifacts`
  als Listen. Alle `required_checks` müssen tatsächlich bestanden sein.
- Layoutprüfungen brauchen PDF und PNG sowie eine direkte Sichtung per
  `view_image`; Seitenbilder mit `scripts/pdf_pages.py` erzeugen. PDF- und
  Office-Arbeit bleibt in der eigenen Sandbox.

## Pause und Wiederaufnahme

- **Eine Pause ist verbindlich.** `unpause` nur nach einer neuen, ausdrücklichen
  Anweisung des Nutzers, nie wegen automatischer Rückmeldungen. Eine
  Wartungssperre nicht umgehen.
- Bei Wiederaufnahme vorhandene Kind-Chats und Berichte erhalten.
- Keine Vorlagenänderung, kein Speichern von Serienbriefen und kein Versand ohne
  entsprechenden Auftrag.
