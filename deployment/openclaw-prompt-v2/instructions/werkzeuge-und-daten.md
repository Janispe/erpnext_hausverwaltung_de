# Werkzeuge und Daten

Ergänzt die Werkzeugwahl in `AGENTS.md`. Die dortigen Standardaufrufe gelten
unverändert; diese Anleitung beschreibt Details, Code Mode und Antwortgrenzen.

## Direkte Fachwerkzeuge

Die `hausverwaltung__…`-Werkzeuge sind native Toolcalls mit sichtbarem Schema.
Für einfache Einzelabfragen davor keine Code-Mode-Suche und keine Schemaabfrage.

- **Mieter:** Namen mit `search_mieter` oder `hv_search` auflösen, dann
  `hv_get_mieter_overview(identifier=…)` mit exakter Mietvertrag- oder
  Customer-ID, optional `from_date`/`to_date`.
- **Übersichten:** `hv_get_wohnung_overview`, `hv_get_immobilie_overview`,
  `hv_get_invoice_overview`, `hv_get_contact_overview`,
  `hv_get_payment_overview`, jeweils mit exakter `name`-ID.
- **Listen und Zählungen:** `hv_list_records` / `hv_count_records` für die
  Entitäten `immobilien`, `wohnungen`, `mietvertraege`, `kunden`, `kontakte`,
  `adressen`, `rechnungen`, `zahlungen`. Filter laut Schema; ID-Filter sind
  exakt. Listen liefern standardmäßig 20, höchstens 50 Zeilen.
  - `kunden` zählt Mietvertrag-Debitoren, keine Personen.
  - `zahlungen` umfasst nur Customer Payment Entries.
  - Ohne `docstatus`-Filter sind alle Belegzustände enthalten; `docstatus=1`
    heißt gebucht.
- **Welche Werkzeuge gibt es?** `hv_describe_capabilities` zeigt die für den
  aktuellen Benutzer freigeschalteten direkten und Code-Werkzeuge.

## Code Mode

Für allgemeine Dokument- und DocType-Abfragen, `hv_query_view`/`hv_export_view`,
Berichte mit ungewöhnlichen Parametern, große Exporte und PDF-Downloads. Die
Fachwerkzeuge sind dort ebenfalls verfügbar.

- Gezielt mit `catalog.search` suchen. Bei unbekanntem Schema `describe()` am
  zurückgegebenen Handle aufrufen, dann das Handle. `describe()` gehört nicht zur
  direkten Funktion im MCP-Namespace. Handle-Namen nicht raten.
- Datei-, Shell-, Gedächtnis- und Automationswerkzeuge nur über den tatsächlich
  angebotenen Weg aufrufen. Ob `exec` Shell oder JavaScript ausführt, entscheidet
  die aktuelle Werkzeugdefinition, nicht der Name.
- Große Ergebnisse im Code filtern, aggregieren und paginieren; nur die nötige
  Zusammenfassung oder eine Dateireferenz ausgeben, nie große Rohantworten.
- Für Python JSON/CSV über das Dateiwerkzeug in den Workspace schreiben; Python
  liest sie dort ein und hat keine MCP-Zugangsdaten.
- PDFs aus `agent_mail_merge_get_pdf`: Base64 in eine temporäre Workspace-Datei
  schreiben, mit Python dekodieren und die PDF als Anhang liefern. Base64 nie in
  den Chat oder in Shell-Argumente kopieren.
- `hv_query_view` und `hv_export_view` akzeptieren `company`. Für Folgeabfragen
  zu einer Übersicht `rental_terms.company` und den geforderten Zeitraum übernehmen.

## Antwortgrenzen und Vollständigkeit

- Direkte Antworten sind auf 10.000 Zeichen begrenzt, Serienbriefaktionen auf
  40.000. Bei `MODEL_OUTPUT_LIMIT_EXCEEDED` Felder oder `limit` eingrenzen oder
  die Daten im Code verarbeiten.
- Beachte `isError`, `ok`, `success`, `error`, `coverage`, `has_more`,
  `next_offset` und `next`. MCP-JSON aus `structuredContent` oder dem einzelnen
  Textblock dekodieren und gegebenenfalls `success=true`/`result` entpacken.
- Vollständig ist eine Liste nur bei `coverage.complete=true` oder nach
  lückenlosem Sammeln aller Seiten ab Offset 0. `has_more=false` auf einer
  Folgeseite allein beweist keine Gesamtliste.
- `output_truncated`, `candidates_truncated`, nicht steigende Cursor oder ein
  erschöpftes Seitenbudget sind Fehler. Höchstens 100 Seiten sammeln, danach
  Filter eingrenzen. Einen unvollständigen Export nie als fertig melden.

## Übersichten richtig deuten

- `snapshot=false`: kein unveränderlicher Datenbankstand über mehrere Abfragen.
- Summe offener Posten und Mieterkonto-Saldo sind verschiedene Größen. Der
  Bewegungsausschnitt ist kein vollständiges Buchungsjournal.
- Immobilienübersichten umfassen nur direkt zugeordnete Wohnungen, keine
  Unterimmobilien.
- Mietbeträge nach Währung trennen, nie über Währungen addieren. Vertragsmiete
  ist kein gebuchter Umsatz.
- Belegung folgt aus Vertragsbeginn und -ende. Konflikte erscheinen als
  `unresolved`, nicht als Leerstand.

## Serienbriefe

Alle im Adapter als Serienbriefwerkzeug klassifizierten Werkzeuge sind
freigegeben. `agent_mail_merge_execute` erzeugt Entwurfs-PDFs und versendet
keine Briefe oder E-Mails.
