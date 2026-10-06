# MCP: direkte Modellwerkzeuge und Code-Zugriff

Die Implementierung enthält acht direkte Such-/Detailwerkzeuge, drei direkte
Bestandswerkzeuge und einen Python-Adapter für einen authentifizierten MCP-Client.
Die Werkzeugklassen veröffentlichen die Routing-Metadaten über `tools/list`;
der Adapter übernimmt daraus die Modell- und Code-Kataloge ohne eigene Namensliste.
Alle elf Fachwerkzeuge sind auf der Produktivsite installiert und aktiviert.
Unit-Tests, Frappe-Integrationstests auf der isolierten Site `fac.localhost`
und der HTTP-MCP-Endpunkt wurden geprüft.

Die OpenClaw-Anbindung liegt außerhalb dieses Repositorys und muss den generischen
Adapter einmalig übernehmen. Danach entdeckt er die freigegebenen Werkzeuge über
den Serverkatalog. `FAC_PROTOTYPE_TOOL_NAMES` und `include_prototype` bleiben nur
als Kompatibilitätsnamen für bestehende Einrichtungsskripte erhalten.

## Direkter Bestand: Listen, Zählen und Belegung

Für bekannte Standardfragen keine Quellen-/Schemaabfrage vorschalten. Die
Datenquelle und die Standardfelder sind bereits im Werkzeug festgelegt.

| Frage | Aufruf | Ziel |
|---|---|---|
| Welche Immobilien haben wir? | `hv_list_records(entity="immobilien")` | Ein Aufruf direkt auf Immobilie, einschließlich Immobilien ohne Wohnungen |
| Welche Wohnungen gehören zu dieser Immobilie? | `hv_list_records(entity="wohnungen", filters={"immobilie_id": "EXAKTE-ID"})` | Direkte Wohnungszuordnung |
| Wie viele Wohnungen sind dort? | `hv_count_records(entity="wohnungen", filters={"immobilie_id": "EXAKTE-ID"})` | Nur eine Zahl, keine Listenübertragung |
| Welche Verträge laufen am Stichtag? | `hv_list_records(entity="mietvertraege", filters={"contract_state": "current"}, as_of="2026-10-05")` | Vertragsdaten statt möglicherweise veraltetem Status |
| Wie viele Wohnungen sind belegt/leer? | `hv_get_portfolio_summary()` | Gemeinsame Bestands-/Belegungszahlen, keine Finanzbeträge |

Die Entitäten sind `immobilien`, `wohnungen`, `mietvertraege`, `kunden`,
`kontakte`, `adressen`, `rechnungen`, `zahlungen`. Felder sind feste kompakte
Profile. Filter sind pro Entität im JSON-Schema eingeschränkt; keine freien
Feldnamen oder SQL-Ausdrücke. ID-Filter sind exakt und lesbar, Suchbegriffe
zuerst durch `hv_search` auflösen. Kunden sind Mietvertrag-Debitoren, keine
Personenzählung. Zahlungen umfassen ausschließlich Customer Payment Entries.
Ohne `docstatus`-Filter enthalten Rechnungen/Zahlungen alle Belegzustände;
`docstatus=1` bedeutet gebucht. Datumsfilter dort betreffen `posting_date`.

Listen: Standard 20, maximal 50 Zeilen, `name asc`, Offset maximal 10000.
`coverage.complete=true` gilt nur bei einer gesamten Liste ab Offset 0 ohne
weitere Seite. `has_more` und `next_offset` beschreiben die nächste Seite;
auch die letzte Seite einer mehrseitigen Liste ist allein keine vollständige
Gesamtliste. Kein stilles Abschneiden: über 10000 Zeichen strukturierter Fehler,
limit verkleinern oder Daten aus Code verarbeiten. Keine Schemasuche und keine
Wohnungsabfrage zur Rekonstruktion einer Immobilienliste.

Zählungen sind vollständige Zählungen des berechtigt lesbaren Scopes. Für die
Prüfung individueller Dokumentberechtigungen werden intern maximal 5000
Kandidaten gelesen; darüber Fehler statt Teilzählung. Laufzeitfilter nutzen
Vertragsbeginn/-ende einschließlich Enddatum, Stornos getrennt. Listen und
Zählungen verwenden dieselben Filter und Stichtagsregeln.

Bestandsübersicht: maximal 1000 Wohnungen und 5000 verknüpfte Verträge. Global
umfasst sie lesbare Immobilien mit ALLEN direkt verknüpften Wohnungen und
lesbare Wohnungen ohne Immobilie. Bei nicht lesbaren verknüpften Wohnungen
oder Verträgen wird keine vollständige Belegung behauptet. Optional
`immobilie_id` beschränkt auf genau diese Immobilie ohne Unterimmobilien.
Immobilien ohne direkte Wohnungen, inaktive Wohnungen und Wohnungen ohne
Immobilie werden separat gezählt. Vertrags-/Identitätskonflikte werden als
`unresolved` ausgewiesen, nicht als Leerstand; `occupancy_complete=false`.
Höchstens fünf Konflikthinweise, mit Gesamtanzahl. Keine Mietsummen/Umsätze.
Der Abruf ist kein transaktionaler Datenbank-Snapshot.

## Verbindliche Auswahlregel für OpenClaw

In die Hausverwaltungs-Agentanweisungen aufnehmen:

> Bei Bestandslisten hv_list_records verwenden, bei Anzahlfragen
> hv_count_records, bei Belegungsfragen hv_get_portfolio_summary. Für diese
> Standardfragen keine Katalog-/Schemaabfrage und keinen Code-Aufruf
> vorschalten. Eine bekannte exakte ID direkt mit dem passenden Overview lesen;
> einen unbekannten Namen zunächst suchen und Mehrdeutigkeit nicht raten.
> coverage/has_more prüfen und Ausschnitte niemals als vollständige Liste
> ausgeben. Allgemeine Query-Builder, Berichte mit ungewöhnlichen Parametern
> und große Exporte über den Code-Zugriff bearbeiten.

`hv_query_view`, `hv_describe_query_sources`, `hv_describe_query_source` sind
Code-Werkzeuge. Die Zuordnung kommt ausschließlich vom authentifizierten
Server über `tools/list`, nicht aus einer Namensliste auf dem Pi.

## Serverseitige Routingmetadaten (Version 1)

Jedes eigene Werkzeug trägt im MCP-Tool-Objekt `_meta` mit dem Schlüssel
`hausverwaltung/routing`. Beispiel für ein direktes Werkzeug:

```json
{
  "version": 1,
  "audiences": ["model", "code"],
  "model_max_chars": 10000
}
```

Code-Werkzeuge tragen `audiences=["code"]` und `model_max_chars=null`.
Serienbriefaktionen haben ein Modellbudget von 40000 Zeichen. Die
serverseitigen Toolklassen definieren die Zuordnung: neue OverviewTool-Klassen
sind direkt, Export-/PDF-Klassen nur Code. Kein Client enthält Werkzeugnamen,
FAC-Konstanten oder eine zweite Freigabeliste. Die bestehende FAC-Aktivierung
und Benutzer-/Dokumentberechtigungen werden weiterhin vor der Auslieferung
angewandt; Metadaten ersetzen keine Berechtigungsprüfung.

Das ist eine versionierte Hausverwaltungs-Erweiterung im standardisierten
MCP-Feld `_meta`, keine universelle automatische Modell-/Code-Trennung aller
MCP-Clients. FAC reicht `_meta` mit einem kleinen, idempotenten
Kompatibilitätspatch durch Registry/Adapter/HTTP-Katalog durch. Der Patch ist
in den Image-Builds enthalten und bricht bei unbekannter FAC-Codeform ab.
Normale Clients können `_meta` ignorieren, erhalten weiterhin dieselben Tools
und dieselben Read-only-/Write-Annotations. Unser Adapter muss einmalig auf
Metadatenauswertung umgestellt werden. Danach erfordern neue Tools und
Zuordnungsänderungen keine Client-Codeänderungen.

`discover_tools(rpc)` lädt alle `tools/list`-Seiten und prüft Metadaten,
Versionen, doppelte Namen und Cursors. Im Code-Host bei Sitzungsbeginn und
vor jedem neuen Nutzerturn ausführen, alternativ bei einer tatsächlich
unterstützten `notifications/tools/list_changed`-Benachrichtigung. Hier wird
keine solche Push-Benachrichtigung vorausgesetzt. Das Modell bekommt nur die
abgeleiteten Schemas, nicht den vollständigen Katalog als Textantwort. Alte
Schemas in bestehenden Sitzungen durch eine neue Sitzung ersetzen.

Metadaten vor Schema-Konvertierung oder Namenspräfixierung auswerten und beim
Dispatch verfügbar halten. Bei nicht unterstützter Routingversion oder
Katalogen ganz ohne Metadaten expliziter Fehler statt still leerem Katalog.
Unklassifizierte Fremdwerkzeuge werden ausgeschlossen; Metadaten nur vom
bereits vertrauenswürdigen, authentifizierten Hausverwaltungs-MCP übernehmen.
Der Client prüft das serverseitig deklarierte Antwortbudget für die komplette
MCP-Antwort und besitzt zusätzlich eine feste Obergrenze von 40000 Zeichen.
Code-Ergebnisse verbleiben unverändert im Code-Runtime.

Das portable `hv_fac_adapter` benötigt ausschließlich Python 3.10+ und
Standardbibliothek; keine fac_contract.py, keine App-Paketstruktur und kein
Frappe. Der Build über scripts/build_fac_openclaw_adapter.py kopiert nur
fac_routing.py, Exports und Anleitung. Auf dem Pi danach die tatsächliche
Werkzeugauswahl anhand einer neuen Sitzung prüfen.

## Direkte Fachwerkzeuge

| Werkzeug | Argumente | Häufige Frage |
|---|---|---|
| `hv_search` | `query`, optional `doctype`, `limit`, `offset` | Welcher Datensatz ist gemeint? |
| `hv_get_mieter_overview` | `identifier`, optional `from_date`, `to_date` | Welche Konditionen und Rückstände hat dieses Mietverhältnis? |
| `hv_get_wohnung_overview` | `name` | Wer wohnt hier, zu welchen Konditionen, und welche Verträge gab/gibt es? |
| `hv_get_immobilie_overview` | `name` | Wie viele Wohnungen sind belegt/leer, und wie hoch ist die monatliche Vertragsmiete? |
| `hv_get_invoice_overview` | `name` | Welche Positionen und aktuellen Buchungszuordnungen hat die Rechnung? |
| `hv_get_contact_overview` | `name` | Wie erreiche ich den Kontakt, welche Adressen und Mietverträge sind verknüpft? |
| `hv_get_payment_overview` | `name` | Welchem Mietverhältnis und welchen Belegen ist diese Customer-Zahlung zugeordnet? |
| `hv_describe_capabilities` | keine | Welche freigeschalteten direkten/Code-Werkzeuge gibt es für diese Frage? |

`name` und `identifier` sind exakte IDs, keine frei aufzulösenden Namen.
`hv_search` liefert höchstens zehn kompakte Treffer. Die Suche ohne DocType
ist eine begrenzte Auswahl über acht wichtige DocTypes; weitere Treffer
durch Auswahl eines DocTypes und Paging lesen. Mehrere Treffer nicht
automatisch auflösen. Allgemeine Sonderfragen bleiben über die bestehenden
Code-Werkzeuge möglich. Das Fähigkeiten-Tool zeigt nur tatsächlich für den
aktuellen Benutzer verfügbare Werkzeuge.

Gemeinsam sind `ok`, `meta`, `coverage` und `next`. `meta` enthält den
fachlichen Stichtag, Abrufzeit und `snapshot=false`. Listen-Ausschnitte haben
Anzahl, zurückgegebene Zeilen und eine Vollständigkeitsangabe. Fehler liefern
`ok=false` und `error.code`/`error.message`; die Angaben daraus erklären,
statt einen anderen Datensatz als Ersatz auszuwählen.

## Ein Aufruf für die Mieterkonto-Übersicht

`hv_get_mieter_overview` nimmt `identifier` als exakte Mietvertrag- oder
Customer-ID sowie optional `from_date` und `to_date`. Namen zunächst mit
`search_mieter` suchen; mehrere Treffer vom Nutzer auswählen lassen.

Die Antwort enthält:

- `identity`: geprüfte Mietvertrag-/Customer-/Wohnungs-/Immobilienzuordnung.
- `rental_terms`: Kaltmiete, BK-Regelung, BK/HK, Bruttomiete, Währung,
  Company, wirksamer Konditionsstichtag und Vertragspartner-Contact-IDs.
- `account`: vorhandene Kontozusammenfassung, Zeitraum und Bewegungsausschnitt.
- `open_items`: Summe und Anzahl aktuell offener Rechnungsforderungen,
  höchstens fünf Belege sowie `has_more` und `next_offset`.
- `coverage`: Kennzeichnung des Bewegungsausschnitts und der Datenquellen.
- `next`: fertige Argumente für weitere offene Posten und einen Rechnungsexport.

Die Customer-Zuordnung wird mit dem exakten Resolver in beide Richtungen
geprüft. Fehlende, unlesbare oder widersprüchliche Zuordnungen liefern einen
Fehler statt eines Such-Fallbacks. Mietbeträge nutzen die bestehenden
Controller-Eigenschaften einschließlich BK-Regelung und begrenztem
Vertragsstichtag. Die Kontoberechnung nutzt den vorhandenen Mieterkonto-Report
mit der Company der Immobilie, statt dem Benutzerstandard.
Die OP-Summe ist die Summe offener Rechnungen,
nicht gleichbedeutend mit dem Mieterkonto-Saldo. Der bestehende
Bewegungsausschnitt ist kein vollständiges Buchungsjournal. Es entsteht kein
unveränderlicher Datenbank-Snapshot über die einzelnen Abfragen.

## Bedeutung und Grenzen der weiteren Übersichten

- Belegung wird aus Vertragsbeginn/-ende und nicht aus möglicherweise
  veraltetem Status bestimmt. Stornierte Verträge zählen nicht; zwei
  gleichzeitig laufende Verträge werden abgelehnt. Inaktive Wohnungen
  zählen getrennt vom Leerstand.
- Die Immobilienübersicht umfasst nur direkt mit `wohnung.immobilie`
  verknüpfte Wohnungen; Unterimmobilien sind explizit ausgeschlossen.
  Mietsummen werden je Währung getrennt. Konditionen mit der Art
  `Gesamter Zeitraum` werden nicht als Monatsmiete summiert; ausgeschlossene
  Verträge werden gezählt. Die Summe ist kein gebuchter Umsatz und enthält
  keine Teilmonats-Sollstellung.
- Rechnungen prüfen Customer, Vertragsreferenzen (`mietabrechnung_id`,
  `[MV:...]`) und vorhandene Wohnungs-/Vertragsbezüge am Kopf und in den
  Positionen. Ebenso muss die Company zur Immobilie passen.
- Zahlungs-/Buchungszuordnungen stammen aus dem aktuellen, nicht entkoppelten
  **Payment Ledger**. Die zugeordneten Belege werden auf Lesbarkeit und
  Identität geprüft. Ledger-Beträge sind vorzeichenbehaftete Buchungsbeträge.
  Payment-Entry-Restbetrag und Ledger-Zuordnungen werden als getrennte
  Quellen gekennzeichnet; ursprüngliche Child-Referenzen werden nicht als
  aktuelle Zuordnung ausgegeben.
- Kontaktübersichten finden Verträge über `Vertragspartner` und Adressen
  über direkte Contact-Links. Indirekte Customer-Adressen werden nicht
  geraten. Dieselbe Person kann mehrere Verträge mit jeweils eigenem
  Customer haben.
- Wenn erforderliche verwandte Datensätze/Felder nicht lesbar sind,
  gibt es keine scheinbar vollständigen Summen oder Leerstandsangaben.
  Umfangsgrenzen: höchstens 500 Wohnungen je Immobilie und grundsätzlich
  1.000 verwandte Datensätze je Abruf. Darüber allgemeine Code-Abfragen
  verwenden; die direkte Übersicht wird abgelehnt.

Zusätzlich bleiben bei `search_mieter` die eigentlichen `matches` erhalten.
Die bisherige allgemeine Ausgabe-Kürzung behandelte diese Suchtreffer als
redundante UI-Daten und entfernte sie aus der direkten MCP-Antwort.

Die Übersicht wird bei Überschreiten des Antwortbudgets abgelehnt, statt
Finanzsummen oder Identitätsfelder wegzukürzen. Andere vorhandene Tools
behalten ihre bisherigen Limits.

## Optional auf einer Testsite aktivieren

Nach Bereitstellung des geänderten App-Codes und Neuladen des FAC-Katalogs
mit einem System-Manager-Kontext ausführen; `TESTSITE` und `API_USER` ersetzen:

```bash
bench --site TESTSITE execute \
  hausverwaltung.hausverwaltung.services.fac_setup.enable_external_tools \
  --kwargs '{"user":"API_USER","include_focused_tools":true}'
```

Das aktiviert wie bisher alle regulären eigenen externen FAC-Tools und
zusätzlich alle acht Fachwerkzeuge. Für eine bestehende Konfiguration können
alternativ die gewünschten Werkzeuge in **FAC Tool Configuration** aktiviert
werden. Sie sind nicht Teil der eingebauten Assistant-Kataloge.
Die Registrierungs-Hooks enthalten sie; ob eine neue
Registrierung in einer konkreten FAC-Installation zunächst aktiviert ist,
hängt von deren Registry ab. Vor dem Live-Einsatz den tatsächlichen
`tools/list`-Katalog prüfen.

## Einbau in den OpenClaw-Code-Adapter

`fac_routing.py` benötigt weder Frappe noch zusätzliche Python-Pakete.
Mit dem portablen Paket muss nur hv_fac_adapter im Python-Importpfad liegen. `rpc(method, params)` bezeichnet
hier den **vorhandenen** authentifizierten MCP-Client von OpenClaw; diese
Beispiele implementieren keinen neuen Transport.

```python
from hv_fac_adapter import (
    call_tool, collect_pages, decode_result, discover_tools, tool_catalog,
)

# Im Host vor jedem neuen Nutzerturn ausführen; keine Katalogtexte ans Modell.
tools = discover_tools(rpc)

model_tools = tool_catalog(tools, audience="model")
code_tools = tool_catalog(tools, audience="code")

# Dem Modell nur model_tools als Funktionsschemas anbieten.
# Auch beim Dispatch die Auswahl erzwingen:
result = call_tool(rpc, tools, "hv_get_mieter_overview",
                   {"identifier": "EXAKTE-MIETVERTRAG-ID"}, audience="model")
```

Der Modellkatalog enthält Bestands-, Such-/Detailwerkzeuge, Reports und
Serienbriefaktionen. Allgemeine Query-/Quellen-/DocType-/Dokumentzugriffe und die drei
Export-/PDF-Werkzeuge sind ausschließlich im Code-Katalog. Der Code-Katalog
enthält zusätzlich alle Modellwerkzeuge. Unbekannte Tools anderer Plugins
werden ausgeschlossen; Berechtigungen werden nicht durch den Adapter erweitert.
Schemas werden ausschließlich aus dem tatsächlich gelieferten Katalog übernommen.

```python
# Im Code-Runtime ausführen, nicht die rohen Seiten an das Modell ausgeben.
def fetch_page(offset):
    response = call_tool(rpc, tools, "hv_export_view", {
        "view": "invoices",
        "fields": ["invoice", "grand_total", "currency"],
        "filters": {"customer": "EXAKTE-CUSTOMER-ID"},
        "offset": offset, "limit": 1000,
    }, audience="code")
    return decode_result(response)

rows = collect_pages(fetch_page)
# Nur eine knappe Antwort ausgeben; keine Beträge verschiedener Währungen addieren.
answer = {"invoice_count": len(rows)}
```

Bei `hv_query_view` und `hv_export_view` kann zusätzlich `company` mit einer
exakten lesbaren Company angegeben werden. Für Folgeabfragen zu einer
Übersicht `rental_terms.company` übernehmen. Ohne diesen Parameter bleibt
der bisherige Benutzerstandard erhalten. Die Mieterkonto-Übersicht liefert
entsprechende Company-Argumente bereits unter `next`.

`collect_pages` bricht bei Fehlern, Kandidatenlimit, gekürzten Antworten,
stehenden Cursorn und mehr als 100 Seiten ab. Offset-Paging kann bei
gleichzeitigen Datenänderungen trotzdem Zeilen verschieben. Der Adapter
behält vollständige **gelieferte** MCP-Ergebnisse im Code; er hebt keine
serverseitigen Limits auf. Die Trennung wird erst wirksam, wenn OpenClaw
den projizierten Katalog und den passenden Dispatcher nutzt. Ein
Beschreibungstext „nur aus Code“ allein erzwingt sie nicht.

Der Dispatcher prüft außerdem die **komplette serialisierte MCP-Antwort**:
direkte Modellaufrufe höchstens 10.000 Zeichen, Serienbriefaufrufe höchstens
40.000 Zeichen. Das umfasst auch Fehlermeldungen und gleichzeitig vorhandene
Text-/Structured-Antworten. Überschreitungen werden durch eine kleine
`MODEL_OUTPUT_LIMIT_EXCEEDED`-Fehlermeldung ersetzt, ohne Originaldaten oder
Vorschau. Im Code-Runtime bleibt die gelieferte Antwort unverändert.
Die Grenzen gelten pro Aufruf und messen Zeichen, keine exakten Modelltokens.
Ein Gesamtbudget für mehrere Aufrufe innerhalb eines Turns muss OpenClaw
zusätzlich verwalten. Auch eine spätere Host-Formatierung muss vermieden
werden, die Ergebnisse wieder vervielfacht oder Code-Rohdaten ausgibt.

## Lokale Prüfung ohne Site

```bash
python -m unittest \
  hausverwaltung.hausverwaltung.agent_tools.test_fac_overviews \
  hausverwaltung.hausverwaltung.agent_tools.test_fac_routing \
  hausverwaltung.hausverwaltung.agent_tools.test_fac_output.TestFacOutput \
  hausverwaltung.hausverwaltung.agent_tools.test_fac_output.TestFacContract
```

Für den Live-Test zusätzlich mit dem tatsächlichen API-Benutzer die Übersicht
für eine bekannte Mietvertrag-ID abrufen und Identität, Saldo und OP-Summe
mit dem ERPNext-Mieterkonto und OP-Bericht vergleichen. PDF-/FAC-Integration
benötigt eine Frappe-Testumgebung.

Die zusätzliche Suite `test_fac_overviews_site` läuft nur mit einer
initialisierten Verbindung zu `fac.localhost`. Sie erzeugt synthetische
Fixtures mit `db_insert`, um keine Buchungs-/Mail-Workflows auszulösen,
und rollt jeden Test auf seinen Savepoint zurück. Sie prüft echte
Dokument-/Feldzugriffe, Controller-Konditionen, Report-Abruf, Ledger-Daten,
Mehr-Company-Zuordnung, Suchtreffer und FAC-Wrapper. Ein HTTP-Smoke-Test
hat Registrierung aller acht Werkzeuge, Katalogaufteilung, Fähigkeiten
und Suchaufruf am FAC-MCP-Endpunkt bestätigt.
