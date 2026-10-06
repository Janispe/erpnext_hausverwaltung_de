# Serienbriefe über die LLM-Schnittstelle

Der bestehende Hausverwaltungs-Assistent kann gespeicherte Serienbriefvorlagen
lesen, deklarierte Eingabefelder befüllen, echte PDF-Vorschauen erzeugen und diese
als Dokumententwürfe speichern. Das funktioniert in den Profilen Classic,
Mistral Agents und Mistral Basic. Der vorhandene Serienbrief-Renderer erzeugt
Inhalt, Bausteine und Layout; das Modell schreibt keinen Ersatzbrief.

Beispielauftrag:

> Erstelle mit der Vorlage „Bescheinigung, dass Mieter nicht gekündigt hat“
> einen Entwurf für den Mietvertrag [exakter Mietvertrag]. Verwende diese
> Angaben: [Werte der Vorlage]. Zeige mir anschließend die Dokumente.

Fehlende Angaben oder mehrdeutige Treffer müssen zuerst geklärt werden.
Ein Auftrag nur zur Vorschau führt nicht zur Speicherung eines Durchlaufs.

## Werkzeuge und HTTP-API

Alle Methoden liegen unter
`/api/method/hausverwaltung.hausverwaltung.agent_tools.mail_merge_api.`.
Authentifizierung und bei Sitzungscookies der CSRF-Schutz entsprechen den
übrigen Frappe-APIs. Vorbereitung und Ausführung verlangen HTTP POST.

| LLM-Werkzeug | HTTP-Methode | Zweck |
| --- | --- | --- |
| `agent_mail_merge_list_templates` | `list_templates` | Suche mit `query`, `limit`, `offset`; `has_more` beachten |
| `agent_mail_merge_get_template` | `get_template` | Kompakten Steckbrief lesen; vollständiger Quelltext optional über `include_source: true` |
| `agent_mail_merge_prepare` | `prepare` | Auswahl und Werte prüfen, PDFs erzeugen, befristetes Token zurückgeben |
| `agent_mail_merge_execute` | `execute` | Geprüfte PDFs einmalig als Entwürfe speichern |
| `agent_mail_merge_get_status` | `get_status` | Status und gespeicherte PDF-Links lesen, ohne Neugenerierung |
| `agent_mail_merge_save_draft` | `save_draft` | Eingaben dauerhaft als Entwurf (Durchlauf) speichern, ohne PDFs |
| `agent_mail_merge_get_draft` | `get_draft` | Aktuellen Stand eines Entwurfs lesen, inklusive `fingerprint` |
| `agent_mail_merge_list_drafts` | `list_drafts` | Nicht eingereichte Durchläufe nach Titel suchen |
| `agent_mail_merge_update_draft` | `update_draft` | Entwurf teilweise ändern, nur mit dem zuletzt gelesenen `fingerprint` |
| `agent_mail_merge_list_textbausteine` | `list_textbausteine` | Lesbare Bausteine mit Pagination suchen |
| `agent_mail_merge_get_textbaustein` | `get_textbaustein` | Variablen, Standardpfade, aktive `revision` und optional Quelle einer bestimmten Version lesen |
| `agent_mail_merge_create_textbaustein` | `create_textbaustein` | Neuen gekennzeichneten KI-Baustein erstellen |
| `agent_mail_merge_propose_textbaustein_version` | `propose_textbaustein_version` | Unveränderlichen KI-Vorschlag erstellen; aktiver Baustein bleibt erhalten |

Antworten verwenden den vorhandenen Vertrag
`{ok, data, error, meta}`. `meta` enthält Anfrage-ID und Laufzeit. Die
Werkzeugprotokolle enthalten Aktionsmetadaten, keine Briefinhalte.

`get_template` liefert standardmäßig einen Steckbrief mit Zweck, Kategorie,
Empfängertyp, `required_inputs`, den einzelnen `inputs` und einem kurzen
Textauszug. Der Zweck stammt aus der gepflegten Beschreibung oder, falls diese
fehlt, aus dem Titel; `purpose_source` macht diese Herkunft sichtbar. Es wird
kein Zweck durch ein Modell erfunden. Der Textauszug ist ungefüllt, enthält
`[Platzhalter]` statt Jinja und ist auf 900 Zeichen begrenzt. Eine Kürzung ist
mit `excerpt_truncated` gekennzeichnet. Bausteine werden mit Name und Titel
aufgeführt; ihre Warnungen fließen auch ohne Quelltext in den Steckbrief ein.

`inputs` enthält zusätzlich `required`, `json_type` und bei befüllbaren Feldern
ein Formatbeispiel. **`example` ist ein künstliches Beispiel, kein Vorschlag für
den Briefinhalt.** Nur `default` ist ein gespeicherter Vorlagenwert.
`required_inputs` nennt alle nicht optionalen, befüllbaren Felder, einschließlich
solcher mit einem gespeicherten Standardwert.

Mit `get_template(template=..., include_source=true)` kann man zur gezielten
Diagnose zusätzlich den vollständigen HTML/Jinja-Inhalt und die Bausteinquellen
anfordern. Die Revision und die Berechtigungsprüfung bleiben dabei gleich.

Vorbereitung mit den zuvor gelesenen Namen und der Revision:

```json
{
  "template": "EXAKTER_VORLAGENNAME",
  "revision": "REVISION_AUS_GET_TEMPLATE",
  "recipients": ["EXAKTER_MIETVERTRAGSNAME"],
  "values": {
    "kuendigungsdatum": "2026-09-09",
    "rueckstand": 0,
    "wirkungsdatum": "2026-09-09"
  },
  "per_recipient": {},
  "letter_date": "2026-09-09"
}
```

Die Eingabeschlüssel sind vorlagenspezifisch. Ausschließlich `inputs` mit
`fillable: true` sind veränderbar. Zahlen müssen JSON-Zahlen sein, Boolesche
Werte `true`/`false`, Datumsangaben `YYYY-MM-DD`. Text wird für HTML escaped;
HTML/Jinja, verschachtelte Werte, Datenpfade und unbekannte Schlüssel werden
abgewiesen. Vorhandene Datenpfad-Variablen und Doctype-Variablen bleiben unter
Kontrolle der Vorlage. `per_recipient` ordnet exakte Empfängernamen individuellen
Eingabeobjekten zu; diese überschreiben gemeinsame Werte.

Bei `data.ready: false` enthält `errors` die einzelnen Empfängerfehler. Es gibt
kein Ausführungstoken. Bei Erfolg enthält `previews` den aus dem echten PDF
gelesenen Text, Seitenzahl, SHA-256 und einen angemeldeten Benutzern vorbehaltenen
Vorschaulink. `preview_pdf` ist ein zusätzlicher Download-Endpunkt für diese Links.

Fehlende Eingaben und eindeutig erkennbare Renderer-Fehler sind strukturiert.
Zum Beispiel steht bei einem fehlenden Vertragsabschlussdatum in `errors`:

```json
{
  "recipient": "EXAKTER_MIETVERTRAGSNAME",
  "recipient_doctype": "Mietvertrag",
  "code": "MISSING_DATA",
  "message": "Für EXAKTER_MIETVERTRAGSNAME konnte der Pfad objekt.vertragsabschluss_am nicht aufgelöst werden.",
  "issues": [{
    "field": "vertragsabschluss_am",
    "path": "objekt.vertragsabschluss_am",
    "source": "recipient_data"
  }],
  "action": "check_recipient_data"
}
```

Bei fehlenden Pflichtangaben nennt `MISSING_INPUT` alle zu diesem Zeitpunkt
erkennbaren fehlenden Eingabefelder mit `expected_type` und gegebenenfalls
`format`. Falsche Eingabewerte werden mit `INVALID_INPUT` im äußeren `error`
zurückgewiesen; individuelle Werte nennen auch den betreffenden Empfänger.

| `action` | Bedeutung |
| --- | --- |
| `provide_inputs` | Fehlende freigegebene Eingaben erfragen |
| `correct_inputs` | Feldwert, Typ oder Eingabeschlüssel korrigieren |
| `check_recipient_data` | Genannten Datenpfad am ausgewählten Empfänger prüfen lassen |
| `review_template` | Vorlage im Editor prüfen lassen |

`issues.source` unterscheidet `input`, `recipient_data` und `template`.
Ein Datenpfadfehler gibt dem Modell keine zusätzlichen Schreibrechte. Nicht
eindeutige Renderer-Fehler enthalten eine leere `issues`-Liste; Felder werden
nicht aus Beispieltexten oder Jinja-Zeilenausschnitten geraten. Vollständige
Vorlagenausschnitte und Tracebacks werden in diesen Antworten nicht ausgegeben.

Ausführen:

```json
{"preparation_token": "TOKEN_AUS_PREPARE"}
```

Der Benutzer muss die fachliche Dokumenterstellung beauftragt haben. Ein
technisch erfolgreicher Prüflauf ist keine fachliche Prüfung alter Brieftexte,
Beträge oder Fristen. Hinweise auf feste Datumsangaben und mögliche
Ausfüllstellen stehen in `warnings`; das Modell soll unpassende Inhalte melden.

## Entwürfe: vorbereiten, korrigieren, dann erzeugen

Ein Entwurf ist ein `Serienbrief Durchlauf` mit Status „Entwurf“ und gesetztem
„Nicht automatisch rendern“. Er hält nur die Eingaben: Vorlage, optional eine
Vorlagenversion, Empfänger mit eigenen Werten, gemeinsame Werte, Briefdatum und
Titel. Seine ID (z. B. `SBDL-2026-00041`) identifiziert ihn dauerhaft; der
`fingerprint` ist eine Prüfsumme über genau diese Eingaben.

1. Das Modell speichert mit `save_draft`. Unvollständige Entwürfe sind erlaubt,
   `missing_inputs` nennt je Empfänger die fehlenden Pflichtangaben. Werte werden
   wie bei `prepare` geprüft (Typen, kein HTML/Jinja), aber unescaped gespeichert,
   damit sie im Viewer lesbar bleiben. Ein Kommentar vermerkt „Vom Assistenten
   als Entwurf vorbereitet“.
2. Der Nutzer korrigiert im Durchlauf-Viewer. Jede Korrektur wird normal
   gespeichert und steht in der Änderungshistorie des Durchlaufs mit Benutzer,
   altem und neuem Wert. Gerendert wird dabei nicht.
3. Ändert das Modell später weiter, liest es den Entwurf mit `get_draft` neu und
   übergibt bei `update_draft` den zuletzt gesehenen `fingerprint`. Hat jemand
   inzwischen etwas geändert, antwortet die API mit `DRAFT_CHANGED` und dem
   aktuellen Stand (`error.current`); nichts wird überschrieben. `values` und
   `per_recipient` ändern nur die genannten Schlüssel, `null` entfernt einen
   Wert, `recipients` ersetzt die Empfängerliste und behält vorhandene Werte.
4. `prepare` mit nur `draft` rendert die Vorschau aus dem gespeicherten Stand.
   Im Viewer als Text gepflegte Zahlen und Wahrheitswerte werden dabei typisiert.
   `execute` legt die geprüften PDFs im selben Durchlauf ab, ersetzt ältere,
   nicht eingereichte Dokumente des Entwurfs und verweigert mit `DRAFT_CHANGED`,
   wenn der Entwurf nach der Vorschau geändert wurde. Enthält der Entwurf
   eingereichte oder stornierte Dokumente, verweigert es mit `DRAFT_LOCKED`;
   diese storniert oder löscht das Modell nie. `get_draft` meldet danach `rendered:
   "aktuell"`; nach einer weiteren Korrektur `"veraltet"`.

Mit `vorlagenversion` verwendet ein Entwurf (wie jeder Durchlauf) eine ältere
Version der Vorlage: Inhalt aus dem Snapshot der Version, Bausteine im Stand
ihrer Stückliste. `revision` entfällt dann, weil Versionen unveränderlich sind.

Die `revision` einer aktuellen Vorlage ist die Prüfsumme ihres renderbaren
Inhalts und ihrer Bausteine, wie sie die Versionshistorie bildet. Metadaten wie
`modified` oder ein im Hintergrund neu erzeugtes Vorschau-PDF ändern sie nicht.

## Berechtigungen und Wiederholungen

- Lesende Werkzeuge: Rolle `System Manager`, `Hausverwalter` oder
  `Agent Readonly API`, zusätzlich echte Leserechte auf Vorlage, verwendete
  Bausteine und Empfänger. Bei Mietverträgen werden auch Customer und Wohnung
  geprüft. Die Rolle `Agent Readonly API` allein erlaubt keine Ausführung.
- Ausführung: `System Manager` oder `Hausverwalter` sowie Erstellen-, Lesen-
  und Schreibrechte für Serienbrief Durchlauf und Serienbrief Dokument.
- Empfänger werden explizit angegeben, höchstens zehn pro Vorbereitung.
  Unterstützt sind Mietvertrag, Betriebskostenabrechnung Mieter und Dunning.
  Eine mehrdeutige Customer-Zuordnung wird abgewiesen; historische Verträge
  werden nicht durch den aktuell wohnenden Mieter ersetzt.
- Vorbereitung speichert keine fachlichen Datensätze. Die geprüften PDF-Bytes
  liegen benutzergebunden maximal 30 Minuten im Site-Cache, insgesamt höchstens
  10 MiB. Bei geleertem Cache oder Ablauf muss neu vorbereitet werden.
- Vor der Speicherung werden Berechtigungen, Vorlagen-/Bausteinrevision und
  Änderungsstand der ausgewählten Empfänger erneut geprüft. Die PDFs bleiben
  der eingefrorene Stand der Vorbereitung; verknüpfte Stammdaten werden nicht
  noch einmal in einen anderen Brief hineingerendert.
- Eine Sperre und der deterministische Durchlaufname verhindern doppelte
  Speicherung desselben Tokens. Nach Antwortverlust dasselbe Token wiederholen.
  Nach erfolgreicher Ausführung liefert die Antwort `reused: true`.
- PDF, Dokumente und Durchlauf werden zusammen committed. Bei einem Fehler
  erfolgt ein Rollback einschließlich der Attachment-Dateien. `execute` ist
  deshalb eine eigene Transaktionsgrenze und darf nicht als Unterfunktion einer
  größeren, noch uncommitteten Geschäftsoperation verwendet werden.
- Gespeicherte Durchläufe und Dokumente bleiben `docstatus = 0`. PDFs sind
  private Frappe-Attachments. Die API bietet weder Versand noch Submit,
  Buchungen, Löschung oder Änderung der Vorlage an.

Eigene Vorlagen können im Vorlageneditor oder auf ausdrücklichen Auftrag über
die unten beschriebenen KI-Vorlagenwerkzeuge gepflegt werden. Veränderbare
Angaben müssen als Vorlagenvariablen deklariert sein. Änderungen an
Textbaustein-Definitionen gehören nicht zum LLM-Eingabevertrag.

## Audit-Korrekturen

Die Migration `fix_audited_serienbrief_paths` korrigiert ausschließlich die
nachgewiesenen Pfadfehler in den beiden Nettokaltmieterhöhungen für S und K mit
Untermietzuschlag, im Schreiben „Schornstein und Thermen-Sanierung - W- SF“ und
in „Staffelmiete-0-Zahlungserinnerung“. Sie ist wiederholbar und speichert über
die normalen Vorlagen-Versionierungshooks. Der WinCASA-Import verwendet für
Wohnungsgröße und Immobilienadresse ebenfalls explizite Pfade.

Fehlende Vertragsabschlussdaten, Mülltrennungskonfigurationen oder andere
Stammdaten werden nicht erfunden. Alte feste Termine/Beträge und redaktionell
unvollständige Brieftexte benötigen weiterhin eine fachliche Überarbeitung.

## Validierung

`test_mail_merge_api.py` prüft Typen, HTML/Jinja-Abweisung, Berechtigungen,
Customer-Invariante, Vorlagenrevisionen, fehlende Pflichtwerte, PDF-Platzhalter,
Teilfehler, Tokenbindung, Wiederholung und Rollback. Die bestehende
Assistenten-Testsuite prüft weiterhin die bisherigen Werkzeuge. Der echte
Renderer wurde zusätzlich auf 8090 mit Vorschau, privater PDF-Speicherung,
Bytevergleich und wiederholter Ausführung getestet; Testdaten wurden entfernt.

Auf 8090 wurden die Python-Dateien in Backend, beide Queue-Worker und Scheduler
eingespielt und die Dienste neu gestartet. Die vier Vorlagenkorrekturen sind
in der Datenbank gespeichert. Das Docker-Image wurde dabei nicht neu gebaut:
Für eine spätere Container-Neuerstellung muss der Code-Commit im verwendeten
Image enthalten sein. Ein gewöhnlicher Container-Neustart behält den Hotfix.

## Externe Chat-Clients über FAC (LibreChat)

Dieselben Werkzeuge stehen zusätzlich über den FAC-MCP-Endpunkt zur Verfügung
(`agent_tools/fac_contract.py`, `FAC_MAIL_MERGE_TOOL_NAMES`). Es sind die einzigen schreibenden
FAC-Werkzeuge; `save_draft`, `update_draft` und `execute` sind als `write` markiert
(`FAC_MAIL_MERGE_WRITE_TOOL_NAMES`) und speichern nur Entwürfe: Eingaben oder die PDFs einer zuvor
erfolgreich vorbereiteten Vorschau. Fehler bleiben strukturiert (`issues`, `action`),
statt in eine FAC-Fehlermeldung umgewandelt zu werden.

Links (`url`, `pdf_url`) sind in ERPNext relativ und werden für externe Clients mit dem
Site-Config-Key `hv_agent_link_base_url` absolut gemacht (Fallback: `frappe.utils.get_url()`):

```bash
bench --site frontend set-config hv_agent_link_base_url "http://<erpnext-host>:<port>"
```

Die Vorschau-Links sind an den ERPNext-Benutzer des FAC-API-Schlüssels gebunden. Im Browser muss
man daher in ERPNext mit diesem Benutzer angemeldet sein. LibreChat v0.8.7 hat keine Freigabe von
Werkzeugaufrufen in der Oberfläche; die Agentenanweisung verlangt einen ausdrücklichen Auftrag
zum Erstellen, bevor `execute` aufgerufen wird.

### PDFs als Datei im Chat

`mail_merge_api.get_pdf` liefert ein PDF als `content_base64` mit `filename`, `size_bytes` und `sha256`:
entweder aus einer Vorschau (`preparation_token` + `recipient`, dieselbe Benutzer-, Ablauf- und
Änderungsprüfung wie `preview_pdf`) oder aus einem gespeicherten `Serienbrief Dokument` (Leserecht auf das
Dokument, nur die dort angehängte Datei). Es ist kein Werkzeug des eingebauten Assistenten, weil der
base64-Inhalt nicht in einen Modellkontext gehört. Über FAC heißt es `agent_mail_merge_get_pdf` und steht in
`FAC_CODE_TOOL_NAMES`; LibreChat ruft es nur aus `run_tools_with_bash` auf, dekodiert das PDF in der Sandbox und
bietet es als Datei im Chat an. Über FAC werden höchstens 8 MB base64 übergeben.

## KI-Vorlagen und Vorschlagsversionen

### Eigene Textbausteine

Die Bausteinmethoden liegen unter
`hausverwaltung.hausverwaltung.agent_tools.block_authoring_api`. Schreibzugriff
erfordert Hausverwalter/System-Manager-Rolle und die normalen Erstellungs- bzw.
Schreibrechte am Baustein. Lesezugriff folgt den normalen Bausteinrechten,
auch für historische Quellen und Vorschläge.

`create_textbaustein(title, content, variables?, standardpfade?, description?,
render_position?)` erstellt einen neuen Baustein mit unverlierbarer
KI-Kennzeichnung und normaler Ausgangsversion `KI-Erstellung`. Erlaubt sind
passives HTML/Jinja, deklarierte Variablen und `Body`/`Footer`. Die
Doctype-Variablen können Contact, Address, Customer, Supplier, Mietvertrag,
Wohnung und Immobilie lesen. Standardpfade beginnen bei `objekt`, etwa
`{"Mietvertrag": {"vertrag": "objekt"}}`; sie ordnen ausschließlich deklarierte
Variablen zu. Die 1:1-Zuordnung zwischen Customer, Mietvertrag und Wohnung
wird dadurch nicht verändert.

`get_textbaustein(baustein, include_source?, version_number?)` liefert die aktive
`revision` auch dann, wenn eine Vorschlagsquelle gelesen wird.
`propose_textbaustein_version(baustein, revision, content, base_version?, ...)`
prüft diese Revision unter einer Dokumentsperre und erzeugt ausschließlich
einen neuen Snapshot mit Herkunft `KI-Vorschlag` und `based_on`. Solche
Vorschläge gelten nie als aktueller Bausteinstand, werden nicht mit normalen
Speicherungen zusammengefasst und halten ihre Basisversion unveränderlich.
Eine zwischenzeitliche Bearbeitung liefert `BLOCK_CHANGED`.

Der Agent prüft die zurückgegebene `version_number` vor der Übernahme in einer
passenden Vorlage: Vorlagenvorschlag mit
`baustein_versionen={Bausteinname: version_number}`, dann
`save_draft(vorlagenversion=...)` und `prepare(draft=...)`. Dies rendert genau
den vorgeschlagenen Baustein bis zur echten PDF. Pflichtangaben und Empfänger
müssen belegt sein; bis dahin bleibt der Vorschlag ungeprüft. Der Nutzer
übernimmt ihn anschließend über den vorhandenen Baustein-Versionseditor.

KI-Bausteine werden auch in gewöhnlichen Vorlagen mit HTML-Escaping und dem
Schreibschutz gerendert. Die API unterstützt keine PDF-Formular-Dateien oder
Output-Provider; entsprechende Alt-Felder werden im Vorschlag entfernt.
Aufrufe anderer Bausteine innerhalb eines KI-Bausteins werden ausdrücklich
abgewiesen, da der aktuelle Bausteinkontext diesen Renderpfad nicht unterstützt.
Mehrere Bausteine können nebeneinander in der Vorlage eingebunden werden.

### Vorlagen

`agent_mail_merge_create_template` legt eine neue Vorlage mit dauerhafter
Kennzeichnung „Vom Assistenten erstellt“ und einer ersten Version „KI-Erstellung“
an. Ein vorhandener Titel wird nie überschrieben. `agent_mail_merge_propose_template_version`
legt bei gültiger aktueller `revision` ausschließlich eine geschützte Version
„KI-Vorschlag“ mit `based_on` an; die aktive Vorlage bleibt unverändert.
`agent_mail_merge_list_template_versions` zeigt die IDs, KI-Herkunft und den aktiven
Stand. `get_template(vorlagenversion=...)` liest den vorgeschlagenen Inhalt.
Mit `save_draft(vorlagenversion=...)`, anschließend `prepare(draft=...)`, kann
man ihn mit echten Empfängern testen. Der Nutzer übernimmt im Versionseditor;
der Herkunftsverweis bleibt erhalten. Vorschläge zählen nicht als Live-Stand,
werden nicht mit gewöhnlichen Speicherungen zusammengefasst und ihre Basis
wird durch spätere schnelle Speicherungen nicht verändert.

Die Agentenanweisung verlangt diese Renderprüfung für neue KI-Vorlagen und
KI-Vorschläge bereits vor der Übernahme, sobald Testempfänger und Pflichtangaben
vorliegen. Fehlende Angaben werden erfragt; bis dahin ist der Vorschlag als
noch nicht rendergeprüft zu kennzeichnen. Bei einem Vorschlag ist exakt die
zurückgegebene `vorlagenversion` im Testentwurf zu verwenden. `prepare` erzeugt
daraus die echte PDF mit dem Bausteinstand des Vorschlags und liefert ihren
Text sowie `pdf_url`. Über `agent_mail_merge_get_pdf` kann ein FAC-Code-Client
die Vorschau auch als Datei im Chat ausgeben. `execute` ist für diese Prüfung
nicht erforderlich. Renderfehler werden je Empfänger zurückgegeben. Auch bei
`RENDER_FAILED` enthält `diagnostic` den ursprünglichen Fehlertyp, eine technische
Erklärung und die Phase (`context`, `jinja`, `pdf` oder `pdf_validation`). Soweit
bekannt werden `baustein`, `line` und `pdf_engine` ergänzt. Die Jinja-Zeile bezieht
sich auf den vorverarbeiteten Quelltext (`line_reference=jinja_processed`);
eingefügte Zeilen können gegenüber dem Editor zu Abweichungen führen. Bekannte
Fehlerstellen stehen auch in `issues`, ohne daraus ein fehlendes Feld abzuleiten.
`template` und gegebenenfalls `vorlagenversion` benennen den geprüften Stand.
Vollständige Tracebacks, gerenderte Inhalte und beliebige Exception-Strings
werden nicht an den Agenten übermittelt.

Die PDF-Endpunkte des Editors und der Versionshistorie liefern zusätzlich
`ready`, `inputs` und `errors`. Fehlende deklarierte Pflichtwerte ergeben
`MISSING_INPUT` mit allen offenen Feldern und `action=provide_inputs`; nicht
auflösbare Datenpfade ergeben `MISSING_DATA`/`UNRESOLVED_PATH`. Fehlerhafte
Eingabetypen werden als `INVALID_INPUT` gemeldet. Bei `ready=false` ist
`pdf_base64` leer: Ein Fehlertext wird nicht mehr zu einem scheinbar fertigen
PDF. Echte Vorlagen- und PDF-Fehler enthalten die gemeinsame technische
Diagnose. Die Versionshistorie zählt ausschließlich erfolgreiche PDFs als
bereit und bietet typisierte, transiente Vorschauwerte per `preview_values`
an. Diese Werte werden weder in der Vorlage noch im Versionssnapshot
abgelegt. Der Editor bietet zusätzlich `placeholder_mode=1`: Fehlende deklarierte
skalare Pflichtwerte ohne Datenpfad werden im PDF als `[variablenname]`
gezeigt. Jinja-Ausgaben mit solchen Werten werden nur im ephemeren AST
ersetzt; Bedingungen verwenden typisierte Beispiele. Die Antwort enthält
`placeholder_mode`, `placeholders` und `warnings` mit `LAYOUT_ONLY`, das PDF
einen sichtbaren Layout-Hinweis. Der Modus überspringt den gemeinsamen
PDF-Cache und zählt in der Historie separat als Platzhaltervorschau. Er
ersetzt weder fehlende Datensätze/Datenpfade noch unbekannte Variablen und
ändert den Versandpfad nicht. Die Prüfung mit echten Werten bleibt nötig.

Der Versandpfad des Agenten bleibt `save_draft` → `prepare`.

Der Agent liest bei Vorlagenfehlern die betroffene Quelle mit
`get_template(include_source=true, vorlagenversion=...)`, korrigiert einen
eigenen Vorschlag als neue Vorschlagsversion und rendert erneut. Der Fehlercode
bleibt für bestehende Clients kompatibel. `action=check_pdf_renderer` verweist
auf die PDF-Verarbeitung; dafür soll der Agent keine Vorlagenänderung erfinden.

Schreibende Vorlagenwerkzeuge erfordern Hausverwalter/System-Manager-Rolle und die normalen
Vorlagenrechte. Sie erlauben Inhalt, Beschreibung, skalare Variablendefinitionen,
Doctype-/Doctype-Liste-Variablen für Contact, Address, Customer und Supplier sowie
Eingabepfade und Versionsfixierungen vorhandener Bausteine. Sie erlauben keine
frei wählbaren DocTypes zum Schreiben, Python-Provider, Dokumentaktionen oder
Bausteinänderungen. Beim Anlegen wird kein Inhalt gerendert.
Die Jinja-Sandbox erlaubt nur geprüfte Lesefunktionen. Aktives HTML, Ereignishandler,
dynamische Ressourcen, `safe`/`attr`, interne Namen und Jinja-Imports werden für
KI-Inhalte zusätzlich abgelehnt; variable Ausgaben werden HTML-escaped.

Der Chat ist damit lesend mit ausdrücklich erlaubten Serienbrief-Schreibaktionen.
`execute` kann weiterhin die nicht eingereichten Dokumente/PDFs desselben Entwurfs
bei einer Neugenerierung ersetzen. Es ist daher falsch, den gesamten Chat als
„rein lesend“ oder „ohne jede Löschung“ zu beschreiben. Eingereichte Dokumente,
allgemeine Löschwerkzeuge und Stammdatenänderungen bleiben gesperrt.

### Bestimmte Textbausteinversionen verwenden

Die KI-Vorlagenmethoden liegen unter
`/api/method/hausverwaltung.hausverwaltung.agent_tools.template_authoring_api.`
und stehen auch als FAC-MCP-Werkzeuge zur Verfügung:

| Werkzeug | HTTP-Methode | Zweck |
| --- | --- | --- |
| `agent_mail_merge_list_textbaustein_versions` | `list_textbaustein_versions` | Versionen eines exakten `baustein` lesen; `limit` maximal 20, `offset`, `has_more` und `next_offset` |
| `agent_mail_merge_create_template` | `create_template` (POST) | Neue Vorlage einschließlich gewählter Bausteinfixierungen anlegen |
| `agent_mail_merge_propose_template_version` | `propose_template_version` (POST) | Fixierungen ausschließlich in einer KI-Vorschlagsversion ändern |

Die Versionsliste liefert `items` mit `name` (Versions-ID), `number`
(Versionsnummer), Bezeichnung, Herkunft, Änderungen, Erstellungszeitpunkt,
`is_current`, `sealed` und einem ungefüllten Textauszug. Sie verändert und
versiegelt keine Versionen. Das Leserecht auf den Textbaustein wird geprüft,
wie bei der bestehenden Editor-Versionshistorie; `Agent Readonly API` darf
die Liste bei vorhandenen Leserechten ebenfalls verwenden.

Bei `create_template` und `propose_template_version` ist
`baustein_versionen` eine optionale Zuordnung:

```json
{
  "baustein_versionen": {
    "Briefkopf": 3,
    "Grußformel": 2,
    "Hinweis": null
  }
}
```

Es gelten die exakten Bausteinnamen und positiven ganzzahligen **Versionsnummern**,
nicht Versions-IDs. Nur genannte Zuordnungen werden geändert; `null` entfernt
die Fixierung und wählt den aktuellen Bausteinstand. Ohne Angabe beziehungsweise
mit `{}` bleiben die Fixierungen verwendeter Bausteine der Ausgangsversion
erhalten. Fixierungen nicht mehr verwendeter Bausteine werden aus dem Vorschlag
entfernt. Explizite Angaben für unbenutzte Bausteine, ungültige Nummern oder
fehlende Versionen werden mit `INVALID_ARGUMENT` zurückgewiesen. Leserechte
werden für alle tatsächlich verwendeten Bausteine geprüft, auch verschachtelte;
deren Erreichbarkeit richtet sich nach dem ausgewählten Bausteinstand.
Gewählte Versionen werden vor der Auflösung atomar festgeschrieben; bei einer
gleichzeitigen Änderung eines noch nicht festgeschriebenen Arbeitsstands meldet
die API `BLOCK_VERSION_CHANGED`. Dann muss die Versionsliste neu gelesen werden.
Abgewiesene Schreibaktionen rollen auch diese Festschreibung zurück.

Die Antworten der Schreibwerkzeuge enthalten die resultierende Zuordnung als
`baustein_versionen`. `get_template` zeigt je Baustein `fixierte_version`,
`version_number` und `version_source` (`fixed`, `historic` oder `current`;
beim nicht fixierten aktuellen Stand ist `version_number` leer).
Vorschläge lassen sich über `save_draft(vorlagenversion=...)` und `prepare(draft=...)`
mit ihren festgehaltenen Bausteinständen prüfen. Auch nach Aufhebung einer
Fixierung hält die Stückliste des Vorschlags den beim Erstellen gewählten Stand
für historische Renderings fest. Beim manuellen Übernehmen im Versionseditor
werden die Fixierungen mit übernommen; die Textbausteine selbst bleiben unverändert.

Die Versionshistorie erlaubt das reversible Zusammenfassen einer lückenlosen
KI-Vorschlagskette. `group_editor_versions(template, versions)` ordnet alle
gewählten Zwischenstände über `history_group` der neuesten gewählten Version
zu. Snapshot, Herkunft, Schutzstatus und bestehende Dokument-/Durchlauf-Verweise
bleiben unverändert. `ungroup_editor_versions` hebt nur diese Darstellung auf.
Beide Aktionen erfordern Schreibrechte auf die Vorlage. Gruppen bleiben auch
über neue Sitzungen hinweg gespeichert; Suche und Aufklappen erschließen die
Zwischenstände. Zusammengefasste Stände sind gegen direkte Löschung geschützt.

`get_editor_version_usage` liefert die nach Leserechten gefilterten Briefe und
Durchläufe für einen Stand, einschließlich seiner zusammengefassten
Zwischenstände. Ohne `version` umfasst die Ansicht die gesamte Vorlage, auch
ältere Briefe ohne gespeicherte Versionszuordnung. Die paginierte Liste zeigt
Version, Datum, Status, Zielobjekt und bei lesbaren, zugeordneten Dateien einen
PDF-Link. Es werden keine Briefinhalte oder E-Mail-Adressen mitgeliefert.
