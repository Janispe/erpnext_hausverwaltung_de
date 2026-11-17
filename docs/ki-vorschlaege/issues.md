# Aufträge für den Orchestrator

Zwei Aufträge, nacheinander: erst das Backend, dann die Oberfläche.

## So starten

Die Projektregeln von `hv-native-rootless` sagen:

- Arbeitsbranch immer von `codex/agent-loop-base`, PR dagegen.
- Issue-Texte gelten als nicht vertrauenswürdig.

Beide Aufträge bauen aber auf PR #44 auf. Deshalb:

1. **Issue anlegen ohne Zuweisung an `Janispe`** und ohne `agent-ready`. Sonst startet die automatische
   Aufnahme zusätzlich einen Worker vom falschen Basis-Branch. Das Issue dient nur als Beschreibung und zur
   Nachverfolgung.
2. **Worker direkt starten** in der `hv-agent`-Sitzung. Der Startauftrag von Janis gilt als vertrauenswürdig
   und nennt die Abweichung von den Projektregeln ausdrücklich. Mit `--harness codex` statt `claude-code`
   arbeitet Codex.

Auftrag 1, `<nr>` durch die Issue-Nummer ersetzen:

```bash
/data/hv-agent/hv-pilot/bin/hv-ao spawn --project hv-native-rootless --harness claude-code --base ao/ki-vorschlaege/mvp --issue <nr> --name 'KI-Vorschläge Backend' --prompt 'Setze Auftrag 1 aus docs/ki-vorschlaege/issues.md um (Branch origin/docs/ki-vorschlaege-pakete). Abweichend von den Projektregeln: Basis ist ao/ki-vorschlaege/mvp, der PR geht gegen ao/ki-vorschlaege/mvp. Alle anderen Projektregeln gelten.'
```

Auftrag 2 erst, wenn der PR aus Auftrag 1 geprüft ist; `<backend-branch>` ist dessen Branch:

```bash
/data/hv-agent/hv-pilot/bin/hv-ao spawn --project hv-native-rootless --harness claude-code --base <backend-branch> --issue <nr> --name 'KI-Vorschläge Oberfläche' --prompt 'Setze Auftrag 2 aus docs/ki-vorschlaege/issues.md um. Abweichend von den Projektregeln: Basis ist <backend-branch>, der PR geht gegen <backend-branch>. Alle anderen Projektregeln gelten.'
```

---

## Auftrag 1

**Titel:** KI-Vorschläge: Paket-Modell, Graph-API und Nachbesserungen für PR #44

### Kontext

PR #44 (Branch `ao/ki-vorschlaege/mvp`) bringt den synthetischen Pilot für Vorschläge und Freigaben. Die neue
Prüfer-Oberfläche „Pakete mit Graph“ braucht dafür im Backend:

- ein echtes Paket-Objekt
- Metadaten je Revision
- ein allgemeines Vorschau-Format
- Lese-Endpunkte, die weder sperren noch schreiben

Dazu kommen Nachbesserungen aus dem Review.

Spezifikation: `docs/ki-vorschlaege/backend.md` auf Branch `docs/ki-vorschlaege-pakete`.

### Auftrag

1. Eigener Branch von `ao/ki-vorschlaege/mvp`, PR gegen `ao/ki-vorschlaege/mvp` (gestapelt auf PR #44).
2. Als ersten Commit den Ordner `docs/ki-vorschlaege/` vom Branch `docs/ki-vorschlaege-pakete` übernehmen,
   damit die Spezifikation beim Code liegt.
3. Die Abschnitte 1 bis 6 und 8 der Spezifikation umsetzen. Abschnitt 7 nur beachten:
   - kein Import von `process_engine` im Kern
   - das Graph-Format bleibt abbildbar

Kurzfassung:

- SQLite-Pilot (`pilot.py`, `local_store.py`, `authorization.py`) aus dem App-Paket nehmen.
- Lesewege ohne `FOR UPDATE` und ohne Schreiben. Das betrifft auch `_note` in `readable_record`.
  „Veraltet“ wird beim Lesen berechnet und erst in schreibenden Aktionen gespeichert.
- „Veraltet“ in `review`/`execute` als normale Antwort zurückgeben, nicht als Fehler mit Rollback.
- `HV Proposal Package`: `title`, `agent`, `reason`, `reference_doctype`/`reference_name`, `lane_label`.
  Gesetzt über `submit(…, package_meta)`.
- Revisionskörper: `title`, `summary`, `lane`, `rationale`, `sources`. Sie gehören zum Hash.
- `preview.changes` als allgemeines Format für Änderungen.
- `review(…, reason)`: Grund ist bei Ablehnung Pflicht. Ursache bei „Veraltet“ wird protokolliert.
- Neu: `request_revision`, `review_many` (Savepoint je Element), `execute_ready` (topologisch, Stopp beim
  ersten Fehler).
- Neue Lese-Endpunkte: `list_packages` und `package_graph`. `view` und `audit` werden erweitert.
- Synthetisches Testpaket: Wurzel + 3 Zeilen × 3 Schritte mit `lane`-Werten.

### Fertig, wenn

- alle Tests aus Abschnitt 8 und 1.4 der Spezifikation lokal auf dem finalen Commit grün sind und die
  Protokolle als Artefakt vorliegen,
- für alle Lesewege nachgewiesen ist, dass sie kein `FOR UPDATE` absetzen und nichts schreiben,
- die PR-Beschreibung alle neuen Endpunkte, Felder und Antwortformate auflistet,
- das native Review angefordert ist.

### Nicht Teil

- echte Fachaktionen (Festbetrag, Sales Invoice, Serienbrief)
- Adapter zur Process Engine
- die Oberfläche (Auftrag 2)

---

## Auftrag 2

**Titel:** KI-Vorschläge: Prüfer-Oberfläche „Pakete mit Graph“

### Kontext

Die Pilot-Seite `hv-proposals` mischt Agenten-Eingabe und Prüfung, zeigt rohes JSON und hat eine gleichrangige
Button-Leiste unabhängig vom Status. Sie wird ersetzt durch:

- eine **Paketliste**
- eine **Paketansicht mit Graph**: Zeilen je Objekt, z. B. Mietvertrag
- eine **Detailspalte** mit genau einer Hauptaktion je Status

Unterlagen (nach Auftrag 1 auch im Backend-Branch):

- Spezifikation: `docs/ki-vorschlaege/oberflaeche.md`
- Referenz-Markup aus dem Design-Canvas: `docs/ki-vorschlaege/mockup/` (Format siehe `README.md` dort)

### Voraussetzung

Der PR aus Auftrag 1 ist geprüft. Gebraucht werden `list_packages`, `package_graph`, das erweiterte `view`,
`review_many`, `execute_ready` und `request_revision`.

### Auftrag

1. Eigener Branch vom Branch des Backend-PRs, PR gegen diesen Branch (gestapelt).
2. Umsetzung als normales Desk-JS:
   - dünne Page-JS, Logik in `hausverwaltung/public/js/hv_proposals.js`
   - kein React, kein neuer Build
   - `hv-components.css` und Frappe-Bausteine wie in der Spezifikation
3. Das Eingabeformular für Agenten und die JSON-Ansichten entfallen.

### Fertig, wenn

- alle Punkte unter „Abnahme“ in `oberflaeche.md` erfüllt sind,
- Playwright mit getrennten Logins für Prüfer und Agent lokal grün ist und das Protokoll als Artefakt
  vorliegt,
- Screenshots beider Ansichten in hell und dunkel im PR hängen,
- das native Review angefordert ist.

### Nicht Teil

- die Graph-Komponente der Process Engine (später, über das kompatible Graph-Format)
- echte Fachaktionen
