# KI-Buchungsvorschläge: Schnittstelle

Stand 18.11.2026. Abschnitt 1 und 2 sind verbindlich: Die Oberfläche aus Auftrag 1 baut ihre Mock-Daten genau
so, und das Backend aus Auftrag 2 liefert genau das. Abschnitt 3 bis 6 skizzieren das Backend; Auftrag 2
präzisiert sie und legt Abweichungen vor dem Bau Janis vor.

## 1. Lesen: Erweiterung von `get_overview`

`hausverwaltung/hausverwaltung/page/bankimport_v2/bankimport_v2.py` liefert heute `{import, rows,
phaseCounts}`. Neu sind `import.ki` und `rows[].ki`. In der App heißt `import` intern `meta`.

Beide Felder fehlen oder sind `null`, solange es zum Import kein Vorschlagspaket gibt, die Funktion abgeschaltet
ist oder der Benutzer keine Vorschläge lesen darf. Dann zeigt die Oberfläche nichts KI-Bezogenes.

### `import.ki`

```json
{
  "package": "HVP-PKG-0031",
  "agent": "Buchhaltungs-Agent",
  "submittedAt": "2026-04-30 09:12:00",
  "running": false,
  "progress": {"done": 9, "total": 9},
  "counts": {"Pending": 6, "Approved": 0, "Stale": 1, "Succeeded": 1, "Rejected": 0, "none": 1},
  "confidence": {"hoch": 3, "mittel": 2, "niedrig": 1},
  "canAccept": true
}
```

- `agent` ist der Anzeigename, nicht die Benutzer-ID.
- `counts` und `confidence` zählen nur Vorschläge zu Zeilen, die der Benutzer lesen darf. `confidence` zählt nur
  `Pending` und `Approved`.
- `none` ist die Zahl der Zeilen, für die sich der Agent ausdrücklich enthalten hat (siehe 4.4).
- `running` und `progress` nur, solange der Agent arbeitet; sonst `running: false`.
- `canAccept`: Benutzer hat `HV Proposal Reviewer`, nicht `HV Proposal Agent`, und darf `Payment Entry` und
  `Journal Entry` anlegen und buchen.

### `rows[].ki`

Je Zeile ein Objekt oder `null`. Hat eine Zeile zwei verkettete Vorschläge (Partei, dann Beleg), stehen beide
in `steps`; `status` ist dann der zusammengefasste Status (erster nicht ausgeführter Schritt).

```json
{
  "state": "proposal",
  "status": "Pending",
  "kind": "invoice",
  "kindLabel": "Rechnung zuordnen",
  "summary": "SINV-2026-0041 · 720,00 €",
  "confidence": {"level": "hoch", "score": 0.97},
  "steps": [
    {
      "proposal": "HVP-0412",
      "revision": 1,
      "hash": "a3f9c2e1…",
      "status": "Pending",
      "kind": "invoice",
      "title": "Rechnung",
      "target": "SINV-2026-0041",
      "targetRef": {"doctype": "Sales Invoice", "name": "SINV-2026-0041"},
      "sub": "Miete April 2026 · offen 720,00 €",
      "amount": 720.0,
      "prefill": {"mode": "invoice", "invoices": [{"name": "SINV-2026-0041", "allocated": 720.0}]}
    }
  ],
  "postings": [
    {"account": "1812 - Bank Wilhelmshavener - HV", "label": "Bank Wilhelmshavener (1812)", "debit": 720.0, "credit": 0},
    {"account": "1400 - Forderungen - HV", "label": "Forderungen · Max Mustermann", "debit": 0, "credit": 720.0}
  ],
  "effect": "Zahlung wird angelegt und gebucht. SINV-2026-0041 ist danach ausgeglichen.",
  "rationale": "Rechnungsnummer im Verwendungszweck, Betrag exakt, IBAN ist MV-0182 zugeordnet.",
  "sources": [{"label": "SINV-2026-0041", "doctype": "Sales Invoice", "name": "SINV-2026-0041"}],
  "decision": null,
  "staleText": null,
  "result": null
}
```

| Feld | Werte, Bedeutung |
|---|---|
| `state` | `proposal` (es gibt Vorschläge), `running` (Agent arbeitet an der Zeile), `none` (Agent enthält sich) |
| `status` | Kern-Status `Pending`, `Approved`, `Stale`, `Succeeded`, `Rejected` |
| `kind` | `party`, `invoice`, `split`, `abschlag`, `kredit`, `payment`, `transfer`, `journal`; bei zwei Schritten der Buchungsschritt. Entspricht den Modus-IDs in `MatchPanel.jsx`. |
| `confidence.level` | `hoch`, `mittel`, `niedrig`; `score` optional, 0–1 |
| `steps[].prefill` | Werte für „Anpassen“, Schlüssel je Modus wie die heutigen Formulare |
| `postings` | Vorschau, nur Anzeige. Beträge als Zahl, Formatierung macht die Oberfläche. |
| `decision` | bei `Approved`/`Rejected`: `{"by": "M. Krüger", "at": "…", "reason": "…", "category": "wrong_document"}` |
| `staleText` | bei `Stale`: Ursache als deutscher Satz |
| `result` | bei `Succeeded`: `{"doctype": "Payment Entry", "name": "PE-2026-0058", "at": "…", "by": "M. Krüger"}` |
| `note` | bei `state: "none"`: Begründung des Agenten |

## 2. Schreiben: neue RPC-Aktionen

Die Oberfläche ruft über die Bridge kurze Aktionsnamen auf. Auftrag 2 trägt sie in `RPC_ACTIONS` in
`bankimport_v2.js` ein und legt die Methoden im Adapter `bankimport_v2.py` an. Alle als `POST`.

| Aktion | Parameter | Antwort |
|---|---|---|
| `ki_accept` | `import_name`, `row`, `bindings: [{id, revision, hash}]` | `{ok, status, results: [{id, ok, status, result?, error?}]}` |
| `ki_accept_many` | `import_name`, `items: [{row, bindings}]` (≤ 128 Bindungen) | `{results: [{row, ok, status, result?, error?, skipped_reason?}]}` |
| `ki_reject` | `import_name`, `row`, `binding`, `category`, `reason` (1–1000) | `{ok, status: "Rejected"}` |
| `ki_request_revision` | `import_name`, `row`, `binding`, `note` | `{ok}` |

- `bindings` sind genau die Bindungen, die der Benutzer gesehen hat. Der Server prüft Revision und Hash wie
  `review`.
- `category`: `wrong_party`, `wrong_document`, `wrong_account`, `do_not_book`, `other`.
- Ist ein Vorschlag inzwischen veraltet, antwortet der Server mit `status: "Stale"` und `ok: false`, ohne
  Fehler zu werfen (wie im Kern, [../ki-vorschlaege/backend.md](../ki-vorschlaege/backend.md) Abschnitt 1.3).
- Gleichzeitige Änderung: HTTP 409 wie `ConcurrentRevisionRetry`.
- Navigation: neue `NAV_ACTIONS`-Aktion `open_proposals` mit `{package, proposal?}` → Route
  `hv-proposals/<package>` mit `?vorschlag=<proposal>`. Sie gehört schon zu Auftrag 1.

## 3. Backend-Skizze: Aktionen im Vorschlags-Kern

Der Kern kennt heute genau eine Aktion (`domain.ACTION = "hv.synthetic_note.set_label/v1"`). Auftrag 2 führt
eine Aktions-Registry ein und registriert die Buchungsaktionen. Die synthetische Aktion bleibt für die Tests.

| Aktion | Ausführung über `bankauszug_import.py` |
|---|---|
| `hv.bankimport.assign_party/v1` | `apply_party_to_row_and_relink`, danach `create_bank_transaction_for_row` |
| `hv.bankimport.reconcile_invoices/v1` | `manually_reconcile_row` |
| `hv.bankimport.reconcile_split/v1` | `reconcile_split_row` |
| `hv.bankimport.assign_abschlag/v1` | `assign_abschlagsplan_row` |
| `hv.bankimport.assign_kreditrate/v1` | `assign_kreditrate_to_bank_row` bzw. `book_kreditrate_from_statement_for_row` |
| `hv.bankimport.standalone_payment/v1` | `create_standalone_payment_for_row` |
| `hv.bankimport.internal_transfer/v1` | `create_internal_transfer_for_row` |
| `hv.bankimport.journal_entry/v1` | `create_journal_entry_for_row` |

Jede Aktion definiert:

- **Payload:** `import_name`, `row`, ein **Zeilen-Fingerabdruck** (Buchungstag, Betrag, Richtung, IBAN, Hash des
  Verwendungszwecks) und die Parameter der jeweiligen Funktion.
- **Ausgangslage** für die Frische-Prüfung (`_fresh`): Partei, Bank-Transaktion und Beleg der Zeile sowie der
  offene Betrag der Zielbelege. Weicht etwas ab, wird der Vorschlag `Stale` mit Ursache `baseline_changed` und
  einem deutschen `detail`, das als `staleText` erscheint.
- **Vorschau:** `changes`, `postings`, `effects` (Abschnitt 5).
- **Ausführung** mit den Rechten des freigebenden Menschen, nicht des Agenten. Die bestehenden Prüfungen der
  Funktionen (Firma, Kostenstelle, Mietvertrag, Rechnungsdatum nach Vertragsende …) gelten unverändert. Eine
  Rückfrage, die heute im Formular bestätigt wird, führt beim Übernehmen zu `ok: false` mit Grund; der
  Benutzer bucht dann über „Anpassen“.
- Für `assign_party` gilt die Invariante aus `AGENTS.md`: nur ein exakter Customer eines Mietvertrags, keine
  Auswahl unter mehreren.

`ki_accept` verarbeitet die gebundenen Schritte in topologischer Reihenfolge. `Pending` wird für genau diese
Revision freigegeben und dann ausgeführt. `Approved` verwendet die vorhandene Freigabe derselben Revision
und führt direkt aus. Bei einem schon ausgeführten Vorgänger wird das bestehende Ergebnis verwendet.
Eine neue Freigabe erhält im Prüfprotokoll `{"surface": "bankimport"}`, die Ausführung ein eigenes Ereignis.

Für den Teilfehler „Partei zugeordnet, Buchung fehlgeschlagen“ benennt Auftrag 2 die Transaktionsgrenzen
im Plan. Die erfolgreiche Zuordnung und eine gültige Freigabe des zweiten Schritts bleiben erhalten.
Ein erneuter Versuch prüft dieselbe Bindung und die aktuelle Ausgangslage und führt nur den offenen
Schritt aus. Die Frische-Prüfung berücksichtigt die erwartete Änderung durch den ausgeführten Vorgänger.

## 4. Backend-Skizze: Paket und Zeilen

1. **Ein Paket je Import und Agentenlauf**, `package_meta`: Titel „Kontoauszug <Monat Jahr> · <Bankkonto>“,
   `reference_doctype = "Bankauszug Import"`, `reference_name`, `lane_label = "Importzeilen"`.
2. **Zeile im Graph** = Importzeile: `lane = {key: row.name, label: "01.04. · +720,00 € · Max Mustermann"}`.
3. **Verkettung:** Parteivorschlag → Belegvorschlag als Abhängigkeit im Kern. Ausführen des Belegs erst nach
   ausgeführter Partei.
4. **Enthaltung:** Der Kern kennt keine Enthaltung. Vorschlag: Kindtabelle am `HV Proposal Package` mit
   `lane_key` und `note`. Nur Anzeige, keine Freigabe. Alternative bitte vor dem Bau vorlegen.
5. **Zuordnung beim Lesen:** `get_overview` sucht das jüngste Paket mit Bezug auf den Import und ordnet
   Vorschläge über `lane.key` den Zeilen zu. Ohne `FOR UPDATE`, ohne Schreiben (Kern-Regel 1.2).
6. **Manuelles Buchen bei offenem Vorschlag:** offene Entscheidung 2 in [README.md](README.md).

## 5. Backend-Skizze: neue Metadaten und Vorschau-Felder

- **`confidence`** als neues Feld der Revisions-Metadaten (`domain.metadata`):
  `{"level": "hoch"|"mittel"|"niedrig", "score": 0..1 optional}`. Gehört zum gehashten Inhalt.
- **`preview.postings`**: Liste von `{account, label, debit, credit, cost_center?}`, höchstens 12 Einträge,
  Summe Soll = Summe Haben. Wird vom Server aus der Aktion berechnet, nicht vom Agenten übernommen.
- **`preview.changes`** wie bisher, z. B. `{"field": "outstanding", "label": "SINV-2026-0041", "before":
  "offen 720,00", "after": "offen 0,00", "kind": "value"}`.
- **`effects`** als kurze englische Schlüssel mit deutscher Übersetzung in `hv_proposals.js`
  (`translateEffect`) und im Bankimport.

## 6. Testdaten

Für Auftrag 2 ein Bootstrap analog `tests/proposals_bootstrap.py`: ein Bankauszug-Import mit 9 Zeilen wie im
Canvas (fiktive Namen), ein Paket mit allen Zuständen aus [oberflaeche.md](oberflaeche.md), getrennte Logins
für Prüfer und Agent. Nur auf einem frischen isolierten Stack, nicht auf 8090.
