# KI-Buchungsvorschläge: Aufträge für Orchestrator.inc

Zwei Aufträge, nacheinander. Auftrag 2 erst, wenn Janis den PR aus Auftrag 1 freigegeben hat.

## So starten

1. Die Unterlagen liegen auf Branch `design/ki-vorschlaege-buchungen`. Der Coding-Agent übernimmt den
   Ordner `docs/ki-vorschlaege-buchungen/` vom Design-Branch auf seinen Arbeitsbranch von `main`.
2. Den jeweiligen Auftrag als eigene Sitzung im Hausverwaltungs-Projekt von Orchestrator.inc starten.
   Titel und Abnahme stehen in den Abschnitten unten.
3. Der Coding-Agent arbeitet im Worktree der Sitzung und öffnet einen PR gegen `main`. Merge durch Janis.
4. Projektregeln und `AGENTS.md` sind für Rechte, Zugänge und Deployments maßgeblich.

---

## Auftrag 1

**Titel:** KI-Buchungsvorschläge im Bankimport: Oberfläche mit Mock-Daten

### Kontext

Ein Agent soll später für die Zeilen eines Kontoauszugs Zuordnungen und Buchungen vorschlagen. Die Vorschläge
sollen direkt im Bankimport an der Zeile erscheinen und mit einem Klick übernommen werden können. Das Backend
kommt in Auftrag 2. Hier entsteht die Oberfläche in der React-App des Bankimports, getrieben von Mock-Daten.

Unterlagen: `docs/ki-vorschlaege-buchungen/` – vor allem `oberflaeche.md` Teil A und `schnittstelle.md`
Abschnitte 1 und 2. Referenz-Markup in `mockup/` (Artboards A1, A2, B1, B2).

### Auftrag

1. Branch von `main`, PR gegen `main`.
2. In `HV_Bankimport/src_react` umsetzen, was `oberflaeche.md` Teil A beschreibt:
   - Banner, Filter-Chip, Tabellenspalte „KI-Vorschlag“
   - KI-Abschnitt im Seitenpanel mit allen Zuständen, „Anpassen“ mit Vorbelegung, Ablehnen inline
   - Sammeldialog mit leerer Startauswahl und bewusster Auswahl „Hohe Sicherheit“
   - auf schmalen Ansichten sichtbare Buchungsbeträge
   - Tastatur `J`/`K`/`↵`/`R`/`Esc`
   - tiefer Link `?row=`
3. Mock-Daten in `src/data.js` genau in der Form aus `schnittstelle.md` Abschnitt 1, mit den Zeilen r1–r9 aus
   dem Canvas. Mit Varianten für `Approved` und `Rejected` die in Teil A beschriebenen Zustände abdecken.
   Ein zweiter Mock-Datensatz ohne `ki` dient dem Regressionstest.
4. `src/api.js`: `kiAccept`, `kiAcceptMany`, `kiReject`, `kiRequestRevision` mit den Parametern aus
   `schnittstelle.md` Abschnitt 2; im Mock-Modus lokal simuliert (Erfolg, `Stale`, Fehler in Schritt 2).
5. In `hausverwaltung/hausverwaltung/page/bankimport_v2/bankimport_v2.js` die Navigationsaktion
   `open_proposals` ergänzen und `row` für den Zeilenlink ans iframe weitergeben. `RPC_ACTIONS` bleibt unverändert.
6. `npm run build:frappe` und die gebauten Dateien unter `hausverwaltung/public/bankimport_v2/` committen.

### Nicht Teil dieses Auftrags

- Python-Code, DocTypes, Vorschlags-Kern, `get_overview`
- Vorschläge-Seite (`hv_proposals.js`)
- der Agent, der Vorschläge erzeugt

### Abnahme

- Abschnitt „Abnahme Teil A“ in `oberflaeche.md`: Vitest, Playwright gegen den Mock-Dev-Server, Regression
  ohne `ki`.
- Ohne `ki`-Daten ist die Seite unverändert. Das ist die wichtigste Bedingung, weil der PR vor dem Backend
  nach `main` gehen kann.
- Befehle, alle grün:

  ```bash
  cd HV_Bankimport/src_react && npm ci && npm test && npm run test:e2e && npm run build:frappe
  ```

- Bilder im PR wie in `oberflaeche.md` beschrieben. Sichtvergleich mit dem Canvas: gleiche Struktur, Texte und
  Zustände; Abstände dürfen sich an die vorhandenen Bankimport-Styles anpassen.
- PR-Beschreibung: was umgesetzt ist, was bewusst fehlt, welche offenen Entscheidungen aus `README.md`
  betroffen sind und wie sie im Code vorläufig gelöst sind.

---

## Auftrag 2

**Titel:** KI-Buchungsvorschläge: Backend im Vorschlags-Kern und Anzeige auf der Vorschläge-Seite

### Kontext

Auftrag 1 hat die Oberfläche im Bankimport gebaut. Jetzt liefert das Backend echte Daten und führt
Übernahmen aus. Die Vorschläge liegen im bestehenden Vorschlags-Kern (`hausverwaltung/proposals/`) und
erscheinen dadurch auch auf der Vorschläge-Seite.

Unterlagen: `docs/ki-vorschlaege-buchungen/schnittstelle.md` (alle Abschnitte), `oberflaeche.md` Teil B,
dazu `docs/ki-vorschlaege/backend.md` für die Regeln des Kerns.

### Vor dem Bau

Erst einen kurzen Plan als Kommentar im Issue vorlegen und auf Janis' Antwort warten:

- Aktions-Registry im Kern: Form, Ort, Umgang mit der synthetischen Aktion
- Lösung für Enthaltungen (`schnittstelle.md` 4.4)
- Vorschlag zu den offenen Entscheidungen 1, 2 und 4 aus `README.md`
- Transaktionsgrenzen, Status und Audit bei bereits freigegebenen Vorschlägen und bei Fehlern in Schritt 2

### Auftrag

1. Branch von `main`, PR gegen `main`.
2. `schnittstelle.md` Abschnitte 3 bis 5 umsetzen: Registry, Buchungsaktionen, `confidence`, `postings`,
   Frische-Prüfung, Paket je Import.
3. `get_overview` um `import.ki` und `rows[].ki` erweitern (Abschnitt 1), ohne Sperren und ohne Schreiben.
4. Die RPC-Aktionen aus Abschnitt 2 im Adapter `bankimport_v2.py` und in `RPC_ACTIONS` ergänzen.
5. Vorschläge-Seite nach `oberflaeche.md` Teil B ergänzen.
6. Synthetische Testdaten nach Abschnitt 6.

### Nicht Teil dieses Auftrags

- der Agent, der Vorschläge erzeugt, und sein Auslöser
- Änderungen an der Buchungslogik in `bankauszug_import.py`; Ausführen ruft nur die vorhandenen Funktionen

### Abnahme

- Unit- und HTTP-Tests für jede Buchungsaktion: Freigabe nur durch Prüfer, Hash-Bindung, `Stale` bei
  geänderter Ausgangslage, Ausführung mit den Rechten des Menschen, Verkettung Partei → Beleg.
- Teilfehler und Wiederholung im isolierten Stack: Parteizuordnung gelingt, Schritt 2 scheitert. Die
  Zuordnung bleibt erhalten, Schritt 2 bleibt freigegeben und ein erneuter Versuch bucht genau einmal.
  Bereits freigegebene Schritte verwenden die bestehende Freigabe der gebundenen Revision. Eine
  Sammelübernahme stoppt beim ersten Fehler und weist verbleibende Zeilen als übersprungen aus.
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
