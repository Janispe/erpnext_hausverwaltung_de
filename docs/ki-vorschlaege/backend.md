# KI-Vorschläge: Backend-Änderungen an PR #44

Stand 17.11.2026. Grundlage: Review von PR #44 (Branch `ao/ki-vorschlaege/mvp`, Stand `47676c52`)
und der Oberflächenentwurf „Pakete mit Graph“ ([oberflaeche.md](oberflaeche.md)).

Umsetzung als eigener Branch von `ao/ki-vorschlaege/mvp` mit einem PR gegen `ao/ki-vorschlaege/mvp`, also
gestapelt auf PR #44. Wie das zu den Projektregeln passt, steht in [README.md](README.md).

Das Sicherheitsmodell aus PR #44 bleibt unverändert:

- Eine Freigabe gilt nur für genau eine Revision mit ihrem Hash.
- Das Prüfprotokoll wird nur ergänzt, nie geändert.
- Ein Vorschlag ist nur lesbar, wenn sein ganzer Vorgänger-Graph lesbar ist.
- Freigeben darf nur ein Mensch mit `HV Proposal Reviewer` ohne `HV Proposal Agent`, über eine echte Browser-Sitzung.
  Ausnahme: `Administrator` bekommt in Frappe jede Rolle. Für die Engine zählt bei ihm die Agentenrolle nicht
  (`frappe_service.roles_of`). Er darf prüfen und übernehmen, aber nie einreichen oder revidieren:
  `submit` und `revise` im Kern sowie die Agenten-Schnittstelle der Bankpakete lehnen ihn ab. Vorschläge, die er
  früher selbst angelegt oder revidiert hat (Prüfprotokoll `Created`/`Revised`), darf er nicht freigeben, nur
  ablehnen. So kann er keine eigenen Vorschläge freigeben.

**Nicht Teil dieses Auftrags:**

- Echte Fachaktionen (Festbetrag, Sales Invoice, Serienbrief). Es bleibt bei der synthetischen Aktion.
  Alle Formate unten sind aber so allgemein, dass weitere Aktionen ohne Formatbruch dazukommen.
- Kopplung an `process_engine`. Das Graph-Format wird nur kompatibel gehalten (Abschnitt 7).

Bestehende synthetische Pilotdaten dürfen verworfen werden. Eine Datenmigration ist nicht nötig.

## 1. Nachbesserungen aus dem Review

1. **SQLite-Pilot aus dem App-Paket nehmen.** `hausverwaltung/proposals/pilot.py`, `local_store.py` und
   `authorization.py` werden nur von `tests/test_proposals_pilot.py` genutzt. Nach `tests/` verschieben oder
   entfernen. Danach gibt es nur noch eine Aktions-Kennung (`domain.ACTION`); heute weicht der Pilot mit
   `synthetic.note.set_label/v1` davon ab.
2. **Lesen ohne Sperren und ohne Schreiben.** Heute sperren auch reine Lesewege Zeilen:
   - `list_proposals` lädt bis zu 100 Vorschläge über `_load` mit `for_update=True`.
   - `view` und `audit` sperren das Paket über `_lock_for` (`SELECT … FOR UPDATE`).
   - `_note` holt das Zieldokument mit `for_update=True`; das passiert auch in `readable_record`, also bei
     jeder Rechteprüfung über den `has_permission`-Hook.
   - `view` kann schreiben: `_checked` setzt „Stale“, schreibt Protokoll und invalidiert Nachfolger.

   Neu: Alle Lesewege (`view`, `audit`, `list_proposals` und die neuen Endpunkte aus Abschnitt 6) lesen ohne
   `FOR UPDATE` und schreiben nichts. „Veraltet“ wird beim Lesen als **effektiver Status** berechnet und
   angezeigt. Persistiert wird es in der nächsten schreibenden Aktion (`review`, `execute`, `revise`,
   `review_many`, `execute_ready`).
3. **Veraltet in schreibenden Aktionen nicht als Fehler.** Heute wirft `_fresh` in `review` einen
   `ValueError`; die Transaktion rollt zurück und der Status bleibt „Pending“. Neu: Status „Stale“ setzen,
   Ursache protokollieren (Abschnitt 5.2), Nachfolger invalidieren und eine normale Antwort mit
   `status: "Stale"` zurückgeben, damit die Transaktion committet.
4. **Testnachweis.** Nach den Projektregeln tragen alle Commits `[skip ci]`; die GitHub-CI läuft also
   nicht. Nachweis über die lokale CI mit Rootless Docker auf dem finalen Commit:
   - Unit-, Vertrags- und HTTP-Tests (`tests/test_proposals_*.py`, `tests/proposals_http_contracts.py`)
   - Playwright gegen eine frische synthetische Site (`tests/proposals_playwright_e2e.py`)
   - zusätzlich die bestehenden Mietvertragstests

   Die Protokolle kommen als Artefakt in die Sitzung und als Zusammenfassung in die PR-Beschreibung.

## 2. Paket als fachliches Objekt

`HV Proposal Package` bekommt Felder:

| Feld | Typ | Bedeutung |
|---|---|---|
| `package_id` | bestehend | Kennung |
| `title` | Data, Pflicht | z. B. „BK-Abrechnung 2025 · Lindenstraße 14“ |
| `agent` | Link User | einreichender Agent (erste Einreichung) |
| `reason` | Small Text | Anlass, z. B. „Abrechnungsfrist 31.12.2026“ |
| `reference_doctype`, `reference_name` | Dynamic Link, optional | fachlicher Bezug |
| `lane_label` | Data, optional | Name der Zeilen-Dimension, z. B. „Mietverträge“ |

- `submit(…, package_meta=None)`: Bei der ersten Einreichung in ein neues Paket ist `package_meta` mit
  `title` Pflicht. Spätere Einreichungen lassen es weg oder senden identische Werte, sonst Fehler.
- Der Paketstatus wird berechnet, nicht gespeichert:
  - **offen**: mindestens ein Vorschlag „Pending“ oder „Stale“
  - **wartet auf Ausführung**: keiner offen, mindestens einer „Approved“
  - **abgeschlossen**: nur noch „Succeeded“ und „Rejected“
- Leserecht: Ein Paket ist sichtbar, wenn mindestens ein Vorschlag darin lesbar ist. Alle Zahlen beziehen
  sich nur auf lesbare Vorschläge. Die Zahl unsichtbarer Vorschläge wird nicht verraten.
  `readable_record` liefert für Pakete heute immer `False`; das wird entsprechend angepasst.

## 3. Metadaten je Revision

Neue Felder im Revisionskörper. Sie gehören zum gehashten Inhalt, eine Freigabe deckt sie also mit ab.
Validierung in `domain.py` wie bei `payload()`.

| Feld | Grenze | Beispiel |
|---|---|---|
| `title` | 1–80 Zeichen | „Vorauszahlung anpassen“ |
| `summary` | 1–140 Zeichen | „95,00 € → 110,00 €“ |
| `lane` | optional, `{key ≤ 80, label ≤ 140}` | `{"key": "MV-0182", "label": "MV-0182 · VH 2. OG links · Fam. Özdemir"}` |
| `rationale` | 0–2000 Zeichen | Begründung des Agenten |
| `sources` | höchstens 10 × `{label ≤ 200, doctype?, name?}` | Belege |

Die Bezeichnung des Zieldokuments liefert der Server beim Lesen selbst, nicht der Agent:
`target: {doctype, name, label}`, mit normaler Rechteprüfung.

## 4. Allgemeines Vorschau-Format

`preview` bekommt zusätzlich `changes`:

```json
"changes": [
  {"field": "label", "label": "Bezeichnung", "before": "Alt", "after": "Neu", "kind": "value"}
]
```

- `kind` ist `value` oder `text`. Bei `text` darf zusätzlich `segments` mitkommen:
  `[{"op": "same|del|ins", "text": "…"}]`.
- `effects` und `limits` bleiben.
- Die synthetische Aktion füllt `changes` aus `before`/`after` der Bezeichnung.
- `_fresh` vergleicht weiterhin `before`, `after` und `projection_version`.

## 5. Prüfer-Aktionen

1. **`review(binding, approve, reason=None)`**: Bei `approve=False` ist `reason` Pflicht (1–1000 Zeichen).
   Der Grund steht im Protokoll-Detail; die Antwort liefert `reject_reason`.
2. **Ursache bei „Veraltet“**: Jeder Übergang nach „Stale“ schreibt im Protokoll-Detail
   `{"cause": "dependency_rejected" | "dependency_revised" | "dependency_stale" | "baseline_changed",
   "proposal": "<id oder null>", "detail": "<kurzer Text>"}`. `_invalidate_metadata` schreibt heute nur
   `{"cause": parent}`. Lesewege liefern `stale_cause`.
3. **`request_revision(binding, note)`**: nur bei „Pending“ oder „Stale“. Schreibt das Protokoll-Ereignis
   `RevisionRequested` mit Notiz, der Status bleibt. Lesewege liefern `revision_requested: true`, bis eine
   neue Revision eingeht.
4. **`review_many(bindings)`**: nur Freigabe; Ablehnen geht nur einzeln mit Grund.
   - Jede Bindung wird geprüft wie in `review` und bekommt ihr eigenes Protokoll-Ereignis.
   - Jedes Element läuft in einem eigenen Savepoint: Ein veralteter Vorschlag blockiert nicht die übrigen.
   - Höchstens 128 Bindungen.
   - Antwort je Element: `{id, ok, status, error?}`.
   - Freigegeben wird genau das, was der Client gesendet hat, also das, was der Prüfer gesehen hat.
5. **`execute_ready(package, bindings)`**: führt die übergebenen freigegebenen Vorschläge in topologischer
   Reihenfolge mit der Logik von `execute` aus.
   - Vorschläge mit unerfüllten Vorgängern werden übersprungen.
   - Beim ersten Fehler stoppt der Lauf.
   - Antwort je Element: `{id, ok, status, skipped_reason?, error?}`.

## 6. Lese-Endpunkte

Alle ohne Sperren und ohne Schreiben (siehe 1.2). Es erscheinen nur Vorschläge, deren ganzer
Vorgänger-Graph lesbar ist. Ausgelassene Vorschläge fehlen ganz, auch als Kanten-Enden.

1. **`list_packages(status=None, agent=None, start=0, limit=50)`** liefert je Paket:
   - `package`, `title`, `agent` (mit Anzeigename), `reason`, `reference {doctype, name, label}`
   - `status` (berechnet, siehe 2), `counts {Pending, Approved, Succeeded, Stale, Rejected}`, `total`
   - `has_edges`, `lanes` (Anzahl verschiedener `lane.key`), `lane_label`
   - `created`, `last_event_at`

   Sortiert nach `last_event_at` absteigend.
2. **`package_graph(package)`** liefert:
   - `package`: wie oben
   - `nodes` (topologisch sortiert): `id`, `revision`, `hash`, `status` (effektiv), `title`, `summary`,
     `lane` oder `null`, `column` (längster Pfad von einer Wurzel, ab 0), `target {doctype, name, label}`,
     `approvable`, `executable` (freigegeben und alle Vorgänger ausgeführt), `revision_requested`
   - `edges`: `{from, to, satisfied}`, wobei `satisfied` heißt: Vorgänger ausgeführt
3. **`view(proposal_id)`** zusätzlich:
   - `title`, `summary`, `lane`, `rationale`, `sources`, `changes`, `effects`, `limits`
   - `stale_cause`, `reject_reason`, `decision_by` (mit Anzeigename), `decision_at`
   - `predecessors` und `successors` mit Kurzinfo, nur lesbare
   - `result` mit Link-Ziel
4. **`audit(proposal_id)`**: unverändert, zusätzlich der Anzeigename des Akteurs.

## 7. Kompatibilität zur Process Engine (nur vorbereiten)

Das Graph-Format ist so gewählt, dass ein späterer Adapter es auf das Lesemodell von
`process_engine/src_react/instance-graph.jsx` abbilden kann:

| Vorschläge | Process Engine |
|---|---|
| Knoten | Schritt (`step_key` = `id`, `titel` = `title`) |
| Kante | `schritt_io` vom Typ `step_input` |
| Pending, Approved, Succeeded, Stale, Rejected | ready, in_progress, done, blocked, skipped |

Der Kern importiert `process_engine` weiterhin nicht. Der bestehende Test dafür bleibt.

## 8. Tests

- **Unit und Vertrag:**
  - Grenzen der Metadaten
  - der Hash deckt die Metadaten ab
  - Ablehnen ohne Grund schlägt fehl
  - jede Stale-Ursache wird geschrieben
  - `review_many` mit Teilerfolg
  - `execute_ready` hält die Reihenfolge ein und stoppt beim ersten Fehler
  - Lesewege setzen kein `FOR UPDATE` und schreiben nichts
  - ein Vorschlag mit unlesbarem Vorgänger fehlt im Graph
- **HTTP-Kontrakte** für alle neuen Endpunkte, mit getrennten Logins für Prüfer und Agent wie bisher.
- **Synthetische Testdaten**: ein Paket „Synthetik · 3 Zeilen“ mit einer Wurzel und 3 Zeilen × 3 Schritten
  über `HV Synthetic Note`, mit gesetzten `lane`-Werten. Die Oberfläche testet damit.
