# Gekuerzte OpenClaw-Arbeitsregeln

Dies ist die erste Fassung als Vergleichsgrundlage. Die weiterentwickelte
Produktionsvorlage liegt unter `../openclaw-prompt-v2/`. Beide Fassungen sind
Vorlagen; ihre Ablage im Repository belegt keine produktive Uebernahme.

Dieses Paket ist eine lokale Vorlage fuer den bestehenden OpenClaw-Workspace.
Es wurde aus der vom Nutzer uebergebenen AGENTS.md erstellt. Es aendert keine
laufende Installation, Werkzeugfreischaltung oder Gateway-Konfiguration.

## Umfang und Aufbau

- Bisherige AGENTS.md: 19.756 Zeichen.
- Neue AGENTS.md: 5.642 Zeichen; 71,4 Prozent weniger staendig geladener Text.
- Acht Anleitungen unter `instructions/` werden nach Anlass mit einem Dateilesewerkzeug gelesen.
- `source/AGENTS.original.md` bewahrt die uebergebene Fassung unveraendert.
- `source/section-map.json` ordnet die bisherigen Abschnitte ihren neuen Dateien zu.

Die Verkleinerung betrifft den AGENTS.md-Anteil. OpenClaws eigene Systemregeln,
Persona, Memory, Skill-Liste und Werkzeugdefinitionen kommen weiterhin hinzu.
Es gibt daher keine Zusage, den gesamten Modellkontext um 75 Prozent zu senken.

## Inhaltliche Aenderungen

Die kurze AGENTS.md enthaelt die Customer/Mietvertrag-Invariante, eine ausdrueckliche
Regel fuer anwendungsspezifische Buchungs-/Formularfragen, die Auswahl tatsaechlich
angebotener Fachwerkzeuge und gemeinsame Regeln fuer Nachweise, Berechtigungen und Daten.
Die Details zu Dateien, Code Mode, Gedaechtnis, Erinnerungen, Parallelauftraegen,
Mahnungen und Warteschlangen sind ausgelagert.

Die Detailabschnitte zu Dateien, Gedaechtnis, Erinnerungen, Parallelauftraegen,
Mahnungen und Warteschlangen bleiben erhalten. Die Werkzeuganleitung wurde
angepasst: keine festen Pflichtnamen fuer Bestandsfragen, keine vorausgesetzten
Freischaltungen oder Antwortbudgets; das aktuelle Schema entscheidet auch, ob
`exec` Shell oder JavaScript ausfuehrt. Die separate Buchungsanleitung ist neu und setzt
keine noch nicht freigeschalteten Werkzeuge voraus. Die Warteschlangen-Anleitung
hat fuer ihre Auftragsart Vorrang vor der nativen Parallel-Anleitung.

Die 1:1-Zuordnung ist eine verbindliche Geschaeftsregel; bestehende Datensaetze
muessen darauf geprueft und Abweichungen gemeldet werden. Nutzerauftragspflicht
bezieht sich ausdruecklich auf ERPNext-Schreibaktionen und Versand. Ergebnisdateien
und erlaubte Erinnerungsnotizen folgen ihren jeweiligen Anleitungen. Fehlende,
unlesbare oder unvollstaendige Anleitungen sind als Luecke zu melden; deren
Inhalt darf nicht erfunden werden.

Der Werkzeugkatalog und die Erreichbarkeit im laufenden OpenClaw-Workspace sind
mit diesem lokalen Paket noch nicht geprueft. Das gehoert zur Uebernahme und Abnahme.

Das Paket ersetzt keine Fachpruefung und repariert keine Trajectory-Aufzeichnung.
Seine Wirksamkeit fuer die Werkzeugwahl wird nach Uebernahme mit neuen Chats geprueft.

## Uebernahme in OpenClaw

Das ZIP ist ein erzeugtes Uebergabeartefakt und wird nicht mitversioniert.
Es laesst sich aus den Textquellen erstellen (vom Repository-Hauptverzeichnis):

```bash
cd deployment/openclaw-prompt
python3 -m zipfile -c openclaw-prompt.zip AGENTS.md instructions source
```

1. `openclaw-prompt.zip` an den Agenten anhaengen, dessen Workspace die verwendete
   AGENTS.md enthaelt. Das ZIP enthaelt AGENTS.md, die acht Anleitungen und zwei
   Dateien unter `source/` fuer den Vergleich mit der bisherigen Fassung.
2. Die aktuelle AGENTS.md im Ziel-Workspace lesen und sichern. Pruefen, ob sie
   seit der hier archivierten Nutzerfassung veraendert wurde. In diesem Fall
   neue Regeln gezielt abgleichen statt die Datei blind zu ersetzen. Die
   SHA-256 der Archivfassung steht in `source/section-map.json`.
3. Vorhandene gleichnamige `instructions/`-Dateien pruefen und sichern. Nur die
   neun Arbeitsdateien ins Workspace uebernehmen; `source/` dient nur dem
   Vergleich und der Sicherung. Andere Dateien erhalten.
   Ein gemeinsamer Workspace kann mehrere Agenten betreffen. Vor Uebernahme
   bestaetigen, dass dies der beabsichtigte gemeinsame Geltungsbereich ist.
4. Relative Dateiverweise aus der Sandbox pruefen: alle acht Anleitungen muessen
   mit den verfuegbaren Dateilesewerkzeugen vollstaendig erreichbar sein.
   `source/section-map.json` enthaelt die SHA-256-Werte aller neun Arbeitsdateien
   zum Vergleich nach dem Kopieren. Fehlende Dateien oder abweichende Inhalte
   klaeren, bevor der betroffene Ablauf eingesetzt wird. Bestehende
   `scripts/TASK-QUEUE.md` und `scripts/pdf_pages.py` sind Referenzen der bisherigen
   Anleitungen und werden durch dieses Paket nicht ersetzt.
5. Einen neuen Chat beginnen und den Kontextbericht pruefen: die gekuerzte
   AGENTS.md wird geladen; die Detailanleitungen werden nicht alle vorab in
   Systemkontext oder Memory kopiert. Fuer die reine Workspace-Aenderung ist
   kein Gateway-Neustart Teil dieser Anleitung.

Das folgende ist ein konkreter Auftrag, der zusammen mit dem ZIP gesendet werden kann:

> Uebernimm das beigefuegte OpenClaw-Promptpaket in den Workspace dieses Agenten.
> Pruefe und sichere zuerst die bisherige AGENTS.md und vorhandene gleichnamige
> instructions-Dateien. Gleiche zwischenzeitliche Regeln gegen die beigefuegte
> Archivfassung ab. Uebernimm die neue AGENTS.md und die acht instructions-Dateien
> zusammen. Pruefe alle relativen Verweise und melde den betroffenen Workspace,
> vorhandene Abweichungen und die Sicherungspfade. Gateway-Konfiguration ist nicht
> Teil dieses Auftrags.

Die Archivfassung und der Abschnittsvergleich liegen im ZIP und im Repository.
Der Auftrag autorisiert die
Workspace-Dateiaenderung; OpenClaws tatsaechliche Werkzeugrichtlinien bleiben
massgeblich.

## Abnahme mit frischen Chats

| Frage/Auftrag | Erwartete Pruefung |
| --- | --- |
| "Welche Immobilien haben wir?" | Passendes angebotenes Fachwerkzeug direkt nutzen; fehlt es, gezielt Katalog/Schema pruefen. Keine Werkzeugnamen raten. |
| "Ein Mieter erstattet Anwaltskosten in Raten. Wie buchen wir das?" | Buchungsanleitung lesen, passende verfuegbare Metadaten pruefen, konkreten Beleg/Felder nennen; keine Buchung anlegen. |
| "Wo hinterlege ich den Zahlungsplan?" | Formular-/Schemawerkzeuge nutzen; Zahlungsplantabelle einer Ausgangsrechnung und Lieferanten-DocType unterscheiden, soweit belegt. |
| "Merke dir diese dauerhaft geltende Praeferenz ..." | Gedaechtnisanleitung lesen und eine nachgewiesene Dateiaktualisierung vornehmen. |
| "Erinnere mich morgen ..." | Erinnerungsanleitung lesen, den exakten Auftrag einmal anlegen, keine Zusatzjobs. |
| "Erstelle Mahnungsentwuerfe ..." | Mahnungsanleitung und passende Skill-/Werkzeugregeln beachten; Daten pruefen, Entwuerfe von Versand unterscheiden. |
| Ein gespeicherter Serienauftrag wird fortgesetzt | Warteschlangen-Anleitung plus bestehende TASK-QUEUE lesen; keine eigene native Fuenfer-Parallelsteuerung starten. |

Nicht nur den Antworttext vergleichen. Die Werkzeugaufrufe, gelesenen Anleitungen,
offenen Rueckfragen und tatsaechlichen Ergebnisse pruefen. Gleiche Modellwahl,
Werkzeugfreigaben und Ausgangsfrage fuer den Vergleich beibehalten.
