# KI-Buchungsvorschläge: Aufträge für Orchestrator.inc

Stand 18.11.2026 nach dem Review von Auftrag 1. Die Aufträge laufen nacheinander. Jeder beginnt erst, wenn
Janis den PR des vorigen freigegeben hat.

| Auftrag | Inhalt | Stand |
|---|---|---|
| 1 | Oberfläche im Bankimport mit Mock-Daten | erledigt, PR #51 |
| 1b | Überarbeitung nach dem Review, nur Oberfläche | bereit |
| 2 | Backend im Vorschlags-Kern, Vorschläge-Seite | nach 1b |
| 3 | Regelvorschläge im Regel-Fenster, ohne KI | nach 2 |

## So starten

1. Die Unterlagen liegen in `main` unter `docs/ki-vorschlaege-buchungen/`.
2. Den Auftrag als Issue im privaten Repo anlegen: Titel und Text aus dem Abschnitt unten, Janispe zuweisen,
   Label `agent-ready`. Orchestrator.inc startet daraus eine Sitzung.
3. Der Coding-Agent zweigt von `main` ab und öffnet einen PR gegen `main`. Merge durch Janis.
4. Projektregeln und `AGENTS.md` sind für Rechte, Zugänge und Deployments maßgeblich.

---

## Auftrag 1 (erledigt)

Umgesetzt mit PR #51 (`ao/ki-buchungsvorschlaege/bankimport-ui`). Der ursprüngliche Auftragstext steht in der
Git-Historie dieser Datei.

---

## Auftrag 1b

**Titel:** KI-Buchungsvorschläge im Bankimport: Überarbeitung nach dem Review

### Kontext

Auftrag 1 (PR #51) hat die KI-Vorschläge im Bankimport mit Mock-Daten gebaut. Im Review hat Janis
Änderungen entschieden (`README.md`, Entscheidungen 5 bis 9). Sie betreffen nur die Oberfläche in
`HV_Bankimport/src_react`. Ein Backend gibt es weiterhin nicht.

Unterlagen: `docs/ki-vorschlaege-buchungen/oberflaeche.md` Teil A (überarbeitet), `schnittstelle.md`
Abschnitte 1 und 2. Referenz-Markup in `mockup/`: `Matchpanel.dc.html` und `Zustaende.dc.html` (B2, B1),
`Main.dc.html` (A1), `Schmal-1024.dc.html` und `Schmal-390.dc.html` (D1, D2).

### Auftrag

1. Branch von `main`, PR gegen `main`.
2. **Kompakte Karte** in `KiSuggestion.jsx` nach `oberflaeche.md` Abschnitt 4, „Prüfung offen“:
   Buchungsvorschau, Wirkung, Begründung und Belege in einen aufklappbaren Bereich „Details“. Startzustand
   nach Sicherheit, Rücksetzen beim Zeilenwechsel. Gilt auch für `Approved`.
3. **Sicherheit nur als Stufe:** `KiConfidence` zeigt nie eine Prozentzahl; `showScore` entfällt.
4. **Anpassen:** Hinweis über dem vorausgefüllten Formular, Text aus der Aktionstabelle in Abschnitt 4.
5. **Angepasst gebucht:** neuer Zustand in Panel und Tabellenzelle für `Rejected` mit
   `decision.category = "adjusted_booked"` (`oberflaeche.md` „Angepasst gebucht“, `schnittstelle.md`
   Feld `decision`). Eine Mock-Zeile dafür in der Variante `&ki=states`.
6. **Erneut anfordern** bei „Kein Vorschlag“: `kiRequestRevision` ohne Bindung, danach „Agent prüft …“.
   Im Mock lokal simuliert.
7. **Banner „Agent läuft“:** zweite Zeile „Startet automatisch nach dem CSV-Import · Selbst zuordnen geht
   jederzeit“.
8. **Schmale Ansicht** nach `oberflaeche.md` Abschnitt 3 und 6:
   - unter 760 px die KI-Marke mit Sicherheitsbalken unter der Partei
   - unter 1100 px scrollt jeder Zeilenwechsel (Klick, `J`/`K`, Zeilenlink) das Panel ins Bild
   - `↵` bucht nur bei sichtbarer Karte, sonst scrollt es zuerst zur Karte
9. Tests nach `oberflaeche.md` Abschnitt 9. Danach `npm run build:frappe` und die gebauten Dateien unter
   `hausverwaltung/public/bankimport_v2/` committen.

### Nicht Teil dieses Auftrags

- Python-Code, DocTypes, Vorschlags-Kern, `get_overview`, `RPC_ACTIONS`
- Vorschläge-Seite und Regelvorschläge

### Abnahme

- `oberflaeche.md` Abschnitt 9 und weiterhin Abschnitt 8.
- Ohne `ki`-Daten ist die Seite unverändert.
- Befehle, alle grün:

  ```bash
  cd HV_Bankimport/src_react && npm ci && npm test && npm run test:e2e && npm run build:frappe
  ```

- Bilder im PR wie in Abschnitt 9 beschrieben.
- PR-Beschreibung: was umgesetzt ist und wo der Code bewusst von den Mockups abweicht.

---

## Auftrag 2

**Titel:** KI-Buchungsvorschläge: Backend im Vorschlags-Kern und Anzeige auf der Vorschläge-Seite

### Kontext

Auftrag 1 und 1b haben die Oberfläche im Bankimport gebaut. Jetzt liefert das Backend echte Daten und führt
Übernahmen aus. Die Vorschläge liegen im bestehenden Vorschlags-Kern (`hausverwaltung/proposals/`) und
erscheinen dadurch auch auf der Vorschläge-Seite.

Unterlagen: `docs/ki-vorschlaege-buchungen/schnittstelle.md` Abschnitte 1 bis 6, `oberflaeche.md` Teil B,
dazu `docs/ki-vorschlaege/backend.md` für die Regeln des Kerns.

### Vor dem Bau

Erst einen kurzen Plan als Kommentar im Issue vorlegen und auf Janis' Antwort warten:

- Aktions-Registry im Kern: Form, Ort, Umgang mit der synthetischen Aktion
- Lösung für Enthaltungen (`schnittstelle.md` 4.4)
- Ort des Hakens für „Angepasst gebucht“ (4.6) und Ablage offener Anforderungen (4.7)
- Transaktionsgrenzen, Status und Audit bei bereits freigegebenen Vorschlägen und bei Fehlern in Schritt 2

### Auftrag

1. Branch von `main`, PR gegen `main`.
2. `schnittstelle.md` Abschnitte 3 bis 5 umsetzen: Registry, Buchungsaktionen, `confidence`, `postings`,
   Frische-Prüfung, Paket je Import.
3. `get_overview` um `import.ki` und `rows[].ki` erweitern (Abschnitt 1), ohne Sperren und ohne Schreiben.
4. Die RPC-Aktionen aus Abschnitt 2 im Adapter `bankimport_v2.py` und in `RPC_ACTIONS` ergänzen,
   `ki_request_revision` mit und ohne Bindung.
5. „Angepasst gebucht“ nach Abschnitt 4.6 und offene Anforderungen nach 4.7.
6. Vorschläge-Seite nach `oberflaeche.md` Teil B ergänzen.
7. Synthetische Testdaten nach Abschnitt 6.

### Nicht Teil dieses Auftrags

- der Agent, der Vorschläge erzeugt, und sein automatischer Start nach dem Import
- Änderungen an der Buchungslogik in `bankauszug_import.py`; Ausführen ruft nur die vorhandenen Funktionen
- Regelvorschläge

### Abnahme

- Unit- und HTTP-Tests für jede Buchungsaktion: Freigabe nur durch Prüfer, Hash-Bindung, `Stale` bei
  geänderter Ausgangslage, Ausführung mit den Rechten des Menschen, Verkettung Partei → Beleg.
- Teilfehler und Wiederholung im isolierten Stack: Parteizuordnung gelingt, Schritt 2 scheitert. Die
  Zuordnung bleibt erhalten, Schritt 2 bleibt freigegeben und ein erneuter Versuch bucht genau einmal.
  Bereits freigegebene Schritte verwenden die bestehende Freigabe der gebundenen Revision. Eine
  Sammelübernahme stoppt beim ersten Fehler und weist verbleibende Zeilen als übersprungen aus.
- Manuelle Buchung bei offenem Vorschlag setzt ihn auf `Rejected` mit `adjusted_booked` und Beleg; der
  Bankimport zeigt danach „Angepasst gebucht“.
- Ein Lesetest zeigt: `get_overview` setzt kein `FOR UPDATE` und schreibt nichts.
- Ohne Paket liefert `get_overview` dieselbe Form wie vor dem Auftrag.
- Playwright: Bankimport mit echtem Paket (Übernehmen, Ablehnen, Sammeldialog) und Vorschläge-Seite
  (`oberflaeche.md`, Abnahme Teil B).
- Bestehende Tests grün, besonders `tests/proposals_*`, `test_bankimport_v2.py` und die Bankauszug-Tests.
- Nachweis aus dem isolierten Stack, nicht von der Dev-Site 8090:

  ```bash
  ./scripts/agent_ci.sh --python
  ```

  ```bash
  ./scripts/agent_ci.sh --e2e
  ```

---

## Auftrag 3

**Titel:** Bankimport: Regelvorschläge aus wiederkehrenden Mustern

### Kontext

Wiederkehrende Zahlungen wie Gebühren, Hausgeld oder Zahlungen Dritter für Mieter werden jeden Monat gleich
gebucht. Eine Mustersuche ohne KI schlägt daraus Bankimport-Regeln vor, die ein Mensch im Regel-Fenster
anlegt oder verwirft.

Unterlagen: `oberflaeche.md` Teil C, `schnittstelle.md` Abschnitt 7, Referenz-Markup
`mockup/Regelvorschlaege.dc.html` (Artboard E1).

### Vor dem Bau

Erst einen kurzen Plan als Kommentar im Issue vorlegen und auf Janis' Antwort warten:

- Mustersuche: Gruppierung, Normalisierung des Verwendungszwecks, Zeitpunkt, Schwellen
- Ablage der Vorschläge und Unterdrückung verworfener Muster
- Bindung von Party-Regeln an einen Mietvertrag und Verhalten nach Vertragsende

### Auftrag

1. Branch von `main`, PR gegen `main`.
2. Backend nach `schnittstelle.md` Abschnitt 7.
3. Ansicht „Vorschläge“ in `RulePanel.jsx` und Badge am Knopf „Regeln“ nach `oberflaeche.md` Teil C.

### Nicht Teil dieses Auftrags

- KI oder LLM jeder Art
- Änderungen an bestehenden Regeln oder ihrer Auswertung, außer der Mietvertragsbindung aus dem Plan

### Abnahme

- Unit-Tests der Mustersuche: Schwellen, Abweichungen, Überschneidung, Unterdrückung, gleiches Ergebnis bei
  gleichen Daten.
- Eine angelegte Regel greift beim nächsten Import wie eine von Hand angelegte.
- `oberflaeche.md` „Abnahme Teil C“.
- Nachweis aus dem isolierten Stack mit `./scripts/agent_ci.sh --python` und `./scripts/agent_ci.sh --e2e`.
