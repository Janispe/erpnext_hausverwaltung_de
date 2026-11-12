# Warteschlangen

## Dauerhafte Einzelauftraege und gespeicherte Warteschlangen

Bei ausdrücklichen Serienaufträgen zuerst scripts/TASK-QUEUE.md vollständig lesen.
Manifest+vollständige inputs.json je Fall, dann init/manage. Die lokale Steuerung
startet echte dauerhaft sichtbare Kind-Chats und übernimmt Ergebnisse; maximal
ZWEI aktive Einträge insgesamt. KEINE eigenen claim/prepare/spawn/bind/finish,
kein Polling/sessions_yield. Eingeschränkter Katalog: nur antworten, keine Ersatztools.
INPUT enthält konkrete IDs/Freigaben; Geschwisterchats sind keine Datengrundlage.
result.json mit input_nonce,run_id,checks/artifacts als Listen; required_checks
wirklich passed. Layout braucht PDF+PNG und direkte view_image-Sichtung.
PAUSE IST VERBINDLICH. unpause nur nach neuer ausdrücklicher Nutzeranweisung,
niemals aufgrund automatischer Rückmeldungen; Wartungssperre nicht umgehen.
Hauptchat berichtet Fragen/Fortschritt; die Steuerung füllt freie Plätze selbst.
Vorhandene Einzelchats/Berichte bei Wiederaufnahme bewahren. Keine Vorlagenänderung,
Serienbriefspeicherung oder Versand ohne entsprechenden Auftrag. PDF/Office bleibt
in eigener Sandbox; scripts/pdf_pages.py und direkte view_image-Sichtung verwenden.
