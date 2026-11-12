# Briefe in ERPNext – Konzept und Architektur

Status: Entwurf zur Abstimmung, Stand 2026-10-29. Nichts davon ist umgesetzt.

Betrifft `mail_merge` (Serienbrief-Kern), `hausverwaltung` (Fachlogik, KI-Werkzeuge) und
`hausverwaltung_peters` (einmaliger Import).

## 1. Ziel

Jeder ausgehende Brief liegt in ERPNext: Serienbriefe, Einzelbriefe, KI-Entwürfe und der
Altbestand aus Word. Ein Brief ist über Mietvertrag, Wohnung und Immobilie auffindbar, sein
versendeter Stand ist unveränderlich, und wiederverwendbare Vorlagen holen ihre Daten aktuell
aus ERPNext. Die KI findet selbst heraus, welche Daten es gibt, und baut daraus Texte und
Tabellen, ohne Vorlagen zu verunreinigen oder Rechte zu umgehen.

## Kurzfassung

- **Der Brief wird das Archiv.** Aus `Serienbrief Dokument` wird ein Datensatz je Brief mit
  Status bis „Versendet“, Bezügen zu Mietvertrag, Wohnung und Immobilie und eingefrorener PDF.
- **Einzelbriefe entstehen direkt am Mietvertrag** mit eigenem Text. Die Vorlage bleibt unberührt.
- **Daten kommen über einen Datenkatalog und benannte Datenabfragen** (`daten("…")`). Die KI baut
  sie selbst; ausgeführt wird mit den Rechten des Benutzers.
- **Vorlagen ändern sich nur über Änderungsvorschläge mit Status.** Vorschauen sind flüchtig.
- **Der Word-Altbestand wird importiert und zugeordnet.** Aus wiederkehrenden Briefen entstehen
  Vorlagenkandidaten.
- **Fünf Stufen, jede einzeln nutzbar.** Stufe 1 macht die vorhandenen Briefe sofort auffindbar.

## 2. Ausgangslage

### Beobachtungen

Auswertung einer Produktionskopie (Oktober 2026, nur lesend):

- 42 KI-Vorschläge auf 12 Vorlagen, keiner übernommen. 85 von 100 Briefdokumenten stammen aus
  Vorschlagsversionen; keins davon ist eingereicht.
- Vorschläge dienen als Einzelbriefe: Bezeichnungen und teils der Vorlagentext enthalten Namen und
  Daten eines konkreten Falls.
- Jede Layout-Iteration erzeugt einen neuen Vorschlag, einen Durchlauf und ein Dokument. Ein
  Empfänger hat bis zu 11 Fassungen desselben Briefs vom selben Tag; welche verschickt wurde, ist
  nicht erkennbar.
- Darf die KI keine Vorlage anlegen, landet eine neue, wiederverwendbare Vorlage als Vorschlag in
  der Versionskette einer anderen Vorlage.

Außerhalb von ERPNext liegen sehr viele Briefe als Word-Dateien auf einem PC: ohne Versionen, mit
mühsamem Layout, schwer zu finden.

Datentabellen gibt es nur in wenigen, von Hand gebauten Textbausteinen (z. B. Miethistorie,
Zahlungshistorie). Die Abfragen stehen dort als Jinja-Code (`frappe.get_all`) im Text; diese
Aufrufe prüfen keine Rechte.

### Ursachen

| Ursache | Wirkung |
| --- | --- |
| Kein Begriff „Einzelbrief“ | Fallbezogene Briefe laufen über Vorlagenvorschläge |
| `Serienbrief Dokument.durchlauf` ist Pflicht | Jeder Brief braucht einen Durchlauf |
| `prepare` verlangt für Vorschläge einen gespeicherten Entwurf (`USE_DRAFT`) | Jede Prüfiteration wird gespeichert |
| Vorschläge haben keinen Status; Übernahme nur über „Wiederherstellen“ | Offene, übernommene und verworfene Vorschläge sind ununterscheidbar |
| Vorschläge werden automatisch geschützt; Durchläufe zählen als Nachweis | Testreste lassen sich nicht entfernen |
| Vier Kennungen (revision-Digest, Versions-ID, `content_hash`, `version:<id>`) | Verwechslungen in der KI-Schnittstelle |
| `assistant_created` klebt an der Vorlage | Render-Verhalten hängt an der Herkunft, nicht am Inhalt |
| Bausteine lassen sich auf Vorschlagsversionen fixieren | Aktive Vorlagen können nie übernommene Bausteine rendern |
| `mail_merge_api.execute` speichert keine Versionsangaben am Dokument | Nicht nachvollziehbar, womit ein KI-Brief gerendert wurde |
| Daten nur über Jinja-Code | Die KI müsste Abfragen als Code schreiben; Fachregeln und Rechte bleiben außen vor |

## 3. Leitlinien

1. **Ein Brief, ein Datensatz.** Egal ob Serie, Einzelfall, KI-Entwurf oder Import.
2. **Vorlagen sind Werkzeuge.** Einzelfalltext gehört in den Brief, nie in die Vorlage.
3. **Was verschickt ist, bleibt so.** Korrekturen sind Storno und Ersatzbrief.
4. **Freigegeben wird, was geprüft wurde.** Die Freigabe übernimmt genau die PDF der letzten
   Vorschau; so arbeitet der Brief-Assistent schon heute.
5. **Daten über beschriebene Abfragen statt Code im Text.** Die KI sieht einen Datenkatalog und baut
   daraus Abfragen; ausgeführt wird mit den Rechten des Benutzers.
6. **Die KI entwirft, ein Mensch gibt frei.** Durchgesetzt über Rollen und Server-Prüfungen, nicht
   über Anweisungen im Prompt.
7. **Generischer Kern, Fachwissen über Hooks.** `mail_merge` kennt keine Mietverträge;
   `hausverwaltung` liefert Bezüge, Katalog-Freigaben und Fachhinweise.
8. **Nichts raten.** Bezüge nur entlang eindeutiger Verknüpfungen. Ein Customer gehört genau einem
   Mietvertrag (CLAUDE.md, „Zentrale Invariante“).

## 4. Zielbild

```
Vorlage ──aktive_revision──► Revision ◄── Änderungsvorschlag
                             │
                             │ Basis (optional); daten("…") ──► Datenabfrage ◄── Datenkatalog
                             │
Durchlauf (N) ─────────┐     │
„Brief schreiben“ (1) ─┤     ▼
KI-Entwurf ────────────┼──►  BRIEF   Entwurf → Freigegeben → Versendet
Briefimport (Word) ────┘       │     (Storno → Ersatzbrief)
                               ├── Bezüge ──► Akte „Korrespondenz“
                               └── Manifest: Revisionen, Abfragen, PDF-Prüfsumme
```

| Objekt | Umsetzung | Rolle |
| --- | --- | --- |
| Brief | `Serienbrief Dokument`, erweitert | Das Archiv: ein Datensatz je Brief und Empfänger |
| Brief-Bezug | neue Kindtabelle am Brief | Zuordnung zu Akten |
| Durchlauf | `Serienbrief Durchlauf` | Auftrag, der viele Briefe erzeugt; kein Vorschauvehikel mehr |
| Vorlage | `Serienbrief Vorlage` + Feld `aktive_revision` | Wiederverwendbarer Brief mit Live-Daten |
| Revision | `Serienbrief Vorlagenversion`, `Serienbrief Textbausteinversion` | Unveränderlicher Stand |
| Änderungsvorschlag | neuer DocType | Vorschlag mit Status, Begründung, Prüfergebnis |
| Datenabfrage | neuer DocType | Benannte, beschriebene Abfrage für Tabellen und Werte |
| Datenkatalog | berechnet, kein DocType | Was es an Daten gibt, aus Sicht des Empfängers |
| Briefimport | neuer DocType | Import des Word-Altbestands mit Zuordnungsvorschlägen |

## 5. Der Brief

`Serienbrief Dokument` wird ausgebaut statt ersetzt. Es ist schon ein Datensatz je Empfänger,
einreichbar, mit PDF, Versionsangaben und Empfängerobjekt (`iteration_doctype`/`objekt`).
Bestehende Datensätze und ihre Namen bleiben.

### Felder

| Bereich | Bestehend | Neu |
| --- | --- | --- |
| Kopf | `title`, `date`, `kategorie` | `betreff`, `herkunft` (Serienbrief, Einzelbrief, Import, Extern bearbeitet) |
| Empfänger | `iteration_doctype`, `objekt`, `recipient_email` | `empfaenger_anschrift`, bei Freigabe eingefroren |
| Inhalt | `vorlage`, `vorlagenversion`, `textbaustein_versionen`, `variablen_werte` | `eigener_inhalt` (Einzelfalltext, nur im Entwurf änderbar) |
| Ergebnis | `html`, `generated_pdf_file` | `pdf_sha256`, `klartext` (Suche, KI), `render_manifest` |
| Versand | – | `versandweg`, `versendet_am`, `versendet_von`, `versandnachweis`, `email_entwurf` |
| Zuordnung | – | Kindtabelle `bezuege` |
| Durchlauf | `durchlauf` (Pflicht) | `durchlauf` optional |

Das Render-Manifest hält Vorlagen-Revision, Baustein-Revisionen, Abfrage-Revisionen mit ihren
gebundenen Werten und den Renderzeitpunkt fest, für jeden Erzeugungsweg gleich.

Der technische Renderstatus (`status`: Ausstehend, Generiert, Übersprungen, Fehler) bleibt und
heißt in der Oberfläche „Renderstatus“. Der fachliche Status ergibt sich aus `docstatus` und den
Versandfeldern.

### Lebenslauf

```
Entwurf (docstatus 0)       Text, Werte, Empfänger änderbar; Vorschau beliebig oft, ohne neue Datensätze
   │ Freigeben (Submit)     übernimmt die zuletzt geprüfte PDF; Prüfsumme, Klartext, Manifest, Anschrift
   ▼
Freigegeben (docstatus 1)   unveränderlich bis auf die Versandfelder (allow_on_submit)
   │ Versand erfassen       Post, Einschreiben, Bote, persönlich – oder E-Mail über Email Entwurf
   ▼
Versendet
   Storno (Cancel mit Grund) ──► Ersatzbrief (Amend, amended_from)
```

- Die Briefnummer (`SBDOC-JJJJ-NNNNN`) steht als „Unser Zeichen“ auf dem Brief. Wer ein Papier in
  der Hand hat, findet den Datensatz.
- Ein Entwurf darf gelöscht werden; er ist noch kein Brief. Als Nachweis für eine Revision zählen nur
  freigegebene Briefe.
- Versand per E-Mail läuft über den vorhandenen `Email Entwurf` mit Referenz auf den Brief und der
  PDF als Anhang. Der Brief gilt als versendet, sobald der E-Mail-Entwurf gesendet ist.
  `Mietvertrag.bevorzugter_versandweg` (Email, Post) liefert die Voreinstellung.

### Bezüge

Kindtabelle mit `link_doctype`, `link_name` und `art` (Primär, Abgeleitet, Manuell). `mail_merge`
ruft beim Anlegen und bei Empfängerwechsel einen Hook auf, nach dem Muster von
`mail_merge_print_profile`:

```python
# hausverwaltung/hooks.py
mail_merge_letter_references = (
	"hausverwaltung.hausverwaltung.services.mail_merge_extensions.letter_references"
)
```

Regeln der Hausverwaltung:

| Empfängerobjekt | Abgeleitete Bezüge |
| --- | --- |
| Mietvertrag | Wohnung, Immobilie, `kunde` (Customer), Contacts der Vertragspartner außer „Ausgezogen“ |
| Wohnung | Immobilie; kein Mietvertrag, weil über die Zeit nicht eindeutig |
| Immobilie | Contacts der Eigentümer |
| Contact | nur der Contact; ein Mietvertrag wird ausdrücklich gewählt, nie geraten |

## 6. Wie Briefe entstehen

### Einzelbrief

Schaltfläche „Brief schreiben“ an Mietvertrag, Wohnung, Immobilie und Contact. Grundlage ist der
vorhandene Brief-Assistent (`letter_composer`, siehe `mail_merge/docs/brief-erstellen-prototyp.md`),
der heute noch einen Durchlauf mit Dokumenten anlegt.

1. Vorlage wählen oder „Freier Brief“ (nur Briefbogen mit Briefkopf und Unterschrift).
2. Empfänger und Anschrift sind vorbelegt; Angaben ausfüllen.
3. Text im TipTap-Editor anpassen. Die Änderung landet in `eigener_inhalt`, die Vorlage bleibt
   unberührt. Platzhalter und Datentabellen bleiben bis zur Freigabe live.
4. Vorschau, flüchtig wie heute (Token 30 Minuten).
5. Als Entwurf speichern, freigeben, Versand erfassen.

Iterationen ändern denselben Entwurf. Erweist sich eine Änderung als allgemein gültig, macht „Als
Vorlagenvorschlag übernehmen“ daraus einen Änderungsvorschlag (Abschnitt 8). Das ist der einzige
Weg vom Einzelfall zur Vorlage.

Messlatte: Ein Einzelbrief vom Mietvertrag aus ist schneller fertig als in Word.

### Serienbrief

Ein Durchlauf erzeugt aus der aktiven Revision einer Vorlage N Briefe als Entwürfe, nach Prüfung
gemeinsam freigegeben, und ein Sammel-PDF zum Drucken. Wird ein Brief der Serie angepasst, bekommt
nur dieser Brief `eigener_inhalt`.

### KI-Entwurf

Die KI legt Briefentwürfe an und ändert sie (Abschnitt 10). Sie gibt nicht frei und versendet
nicht.

### Word, wenn es doch sein muss

Der vorhandene Word-/ODT-Export (`office_export.py`) bekommt einen Rückweg: Die bearbeitete
Endfassung (DOCX oder PDF) wird im Entwurf hochgeladen und wird zur offiziellen PDF. `herkunft`
wird „Extern bearbeitet“, der Klartext kommt aus der Datei. Neu rendern würde die Word-Änderungen
verwerfen und braucht deshalb eine ausdrückliche Bestätigung.

### Altbestand aus Word

Der `Briefimport` übernimmt die Dateien vom PC:

1. Ordner oder ZIP hochladen, alternativ ein lokales Sync-Skript in `hausverwaltung_peters`.
   Dubletten werden über SHA-256 erkannt.
2. Je Datei entsteht ein Brief mit `herkunft = Import`: Original als Anhang, PDF über LibreOffice,
   Klartext.
3. Datum, Betreff und Empfänger werden aus Text und Dateidaten gelesen.
4. Ein Zuordnungsvorschlag zu Mietvertrag oder Contact nutzt Name, Anschrift und Vertragszeitraum,
   mit Konfidenz und Begründung. Vorgeschlagen werden nur eindeutige Treffer. Muster wie
   `Mail Filing Suggestion` (Vorgeschlagen, Angenommen, Korrigiert, Verworfen).
5. In einer Prüfliste werden Vorschläge gesammelt bestätigt. Danach ist der Brief freigegeben und
   versendet, mit dem Datum aus dem Brief.
6. Vorlagenkandidaten: Ähnliche Briefe werden gruppiert, mit lokalen Embeddings über Ollama wie im
   Mail-Archiv. Die Liste zeigt, welche Brieftypen wie oft vorkommen. Aus einer Gruppe kann ein
   Vorschlag „Neue Vorlage“ entstehen.

## 7. Daten in Briefen

Die KI soll selbst sehen, welche Daten es gibt, und daraus Abfragen bauen. Sie schreibt dafür
keinen Code, sondern eine beschriebene Abfrage, die eine zentrale Engine mit den Rechten des
Benutzers ausführt.

### Datenkatalog

Der Katalog beantwortet „Was gibt es, ausgehend vom Empfänger?“ und wird aus den Frappe-Metadaten
berechnet:

- erreichbare DocTypes entlang von Link-Feldern und Kindtabellen, z. B. Mietvertrag → `kunde` →
  Sales Invoice (`customer`) und Payment Entry (`party`), Mietvertrag → `wohnung` → Zähler,
- Felder mit Bezeichnung, Typ und Beschreibung,
- fertige Ansichten (heute `HV_QUERY_VIEWS`: apartments, tenant_contracts, invoices, open_items,
  payments),
- Berichte mit ihren Pflichtfiltern,
- kuratierte Quellen aus Python (siehe Quellenarten),
- **Fachhinweise**, gepflegt in `hausverwaltung`. Beispiele: `custom_wertstellungsdatum` ist der
  Leistungszeitraum, nicht der Zahlungseingang (dafür `posting_date`). Die Laufzeit eines
  Mietvertrags folgt aus `von`/`bis`; stornierte Verträge sind auszuschließen. Ein Customer gehört
  genau einem Mietvertrag.

Welche DocTypes und Felder lesbar sind, steuert eine Freigabeliste per Hook
(`mail_merge_data_catalog`). Passwort-, Code- und Systemfelder sind nie enthalten. Grundlage sind
die vorhandenen `HV_READABLE_DOCTYPES` und die Schema-Werkzeuge `agent_list_doctypes` und
`agent_get_doctype_schema`.

### Datenabfrage

Neuer DocType `Serienbrief Datenabfrage`:

| Feld | Inhalt |
| --- | --- |
| Name | z. B. „Offene Posten des Mietvertrags“ |
| Beschreibung | In Worten, was die Abfrage liefert; für Menschen und KI |
| Startobjekt | DocType, an den die Abfrage gebunden ist, z. B. Mietvertrag |
| Quelle | DocType, Ansicht, Bericht oder kuratierte Quelle |
| Definition | JSON im Format von `hv_query_docs` plus Bindungen |
| Spalten | Name, Bezeichnung, Typ (für einheitliche Darstellung von Datum und Beträgen) |
| Herkunft, geprüft | KI oder Mensch; „geprüft“ nimmt die Abfrage in die Auswahl des Editors auf |

Abfragen werden versioniert wie Textbausteine (`utils/versioning.py`). Briefe und Revisionen halten
die verwendete Abfrage-Version im Manifest fest.

Beispiel:

```json
{
  "doctype": "Sales Invoice",
  "fields": ["name", "posting_date", "due_date", "grand_total", "outstanding_amount"],
  "filters": {"and": [
    {"field": "customer", "op": "=", "value": {"$objekt": "kunde"}},
    {"field": "outstanding_amount", "op": ">", "value": 0}
  ]},
  "order_by": {"field": "due_date", "direction": "asc"},
  "limit": 50
}
```

Bindungen: `{"$objekt": "feld"}` (Empfängerobjekt), `{"$var": "name"}` (Vorlagenvariable),
`{"$datum": "-12 months"}` (relativ zum Briefdatum).

In Vorlage und Brief wird eine Abfrage wie ein Baustein mit festem Namen eingebunden:

```jinja
{% for p in daten("Offene Posten des Mietvertrags") %}<tr><td>{{ p.name }}</td><td>{{ p.due_date }}</td><td>{{ p.outstanding_amount }}</td></tr>{% endfor %}
```

Diese Form, eine Tabellenzeile in einer Schleife, faltet der TipTap-Editor schon heute zu einer
wiederholten Zeile (`data-hv-loop`). Neu im Editor ist „Tabelle aus Daten“: Abfrage wählen, Spalten
wählen, fertig.

### Quellenarten

| Quelle | Wann | Beispiel |
| --- | --- | --- |
| DocType-Abfrage | Normalfall, auch frei von der KI gebaut | Offene Rechnungen eines Mietvertrags |
| Ansicht | Vorgefertigte Verknüpfungen | `open_items`, `payments` |
| Bericht | Die Logik steckt schon in einem ERPNext- oder HV-Bericht | Debitorenbericht mit Filter auf den Customer |
| Kuratierte Quelle | Heikle Fachlogik, in Python getestet | Zahlungszuordnung je Mietmonat, BK-Kostenmatrix |

Kuratierte Quellen registriert `hausverwaltung` per Hook (`mail_merge_data_sources`). Die KI sieht
sie im Katalog wie jede andere Quelle.

### Engine und Regeln

- **Eine Engine für Chat und Briefe.** Die Logik von `hv_query_docs` wandert in den Kern;
  `hv_query_docs` ruft sie nur noch auf. Was die KI im Chat findet, übernimmt sie unverändert in
  einen Brief.
- **Rechte des Benutzers.** Ausgeführt wird über `frappe.get_list`. Fehlt das Leserecht für eine
  Quelle, ist das ein Renderfehler, keine leere Tabelle.
- **Nur gebuchte Belege.** Für einreichbare DocTypes gilt standardmäßig `docstatus = 1`.
- **Immer mit Bezug.** Jede DocType-Abfrage braucht mindestens eine Bindung an Empfänger oder
  Variable, sonst gilt sie als „Abfrage ohne Bezug“.
- **Grenzen.** Zeilen- und Zeitlimit sowie ein Zwischenspeicher je Durchlauf für gleiche Abfrage
  mit gleicher Bindung.
- **Kein Datencode in neuen KI-Texten.** Neue KI-Quelltexte dürfen `frappe.get_all` und
  `frappe.db.*` nicht mehr verwenden, nur `daten()`. Bestehende Vorlagen laufen unverändert weiter.

### Prüfung

`datenabfrage_testen` führt eine Definition gegen einen echten Empfänger aus und liefert die
Zeilen, die aufgelösten Filter und passende Fachhinweise. In einem Brief prüft der Mensch die Daten
mit der Freigabe. In eine Vorlage gelangt eine Abfrage nur über einen Änderungsvorschlag.

## 8. Vorlagen pflegen

- **Revisionen sind unveränderlich**, sobald etwas auf sie verweist. Davor darf der Editor wie heute
  Speicherstände desselben Autors zusammenfassen.
- **`aktive_revision`** an der Vorlage zeigt auf den gültigen Stand. Briefe entstehen nur aus der
  aktiven Revision oder aus ihrem eigenen Inhalt.
- **Änderungsvorschlag** als neuer DocType:

  | Feld | Inhalt |
  | --- | --- |
  | Ziel | Vorlage, Textbaustein, Datenabfrage oder „Neue Vorlage“; optional ein Paket aus mehreren Zielen |
  | Basis | Revision, auf der der Vorschlag aufsetzt |
  | Vorschlag | Neue Revision(en) |
  | Status | Offen, Übernommen, Verworfen, Ersetzt |
  | Begründung | Pflicht; der Zweck der Vorlage (`description`) bleibt unberührt |
  | Herkunft | KI, Mensch oder „aus Brief“ |
  | Prüfergebnis | Testempfänger, Erfolg oder Fehler, Vorschau-PDF |

  Übernehmen setzt `aktive_revision`, wenn die Basis noch aktiv ist; sonst muss der Vorschlag neu
  aufsetzen. Ein Paket wird ganz oder gar nicht übernommen. Ein neuer Vorschlag desselben Autors
  auf dieselbe Basis ersetzt den alten.
- **Vorschau ist flüchtig.** `prepare` arbeitet direkt mit einer Revision, ohne Entwurf und ohne
  Durchlauf; `USE_DRAFT` entfällt.
- **Einzelfall-Bremse.** Enthält ein Vorschlag Namen, Anschrift oder Daten des Testempfängers als
  festen Text, antwortet die Schnittstelle „sieht nach Einzelbrief aus“ und verweist auf den
  Brief-Weg.
- **Render-Modus je Revision** statt `assistant_created` an der Vorlage. Der Modus folgt aus der
  Prüfung des Inhalts, nicht aus der Herkunft. Ziel ist der strenge Modus für alles.
- **Eine Kennung:** die Revisions-ID. Sie dient auch als Basis für optimistisches Sperren.
- **Fixierungen** von Bausteinen nur auf übernommene Revisionen, außer innerhalb eines Pakets.

## 9. Akte und Suche

- Abschnitt „Korrespondenz“ an Mietvertrag, Wohnung, Immobilie und Contact: alle Briefe über die
  Bezüge, neueste zuerst, mit Status und PDF.
- Liste „Briefe“ mit Filtern (Immobilie, Mietvertrag, Kategorie, Zeitraum, Status, Herkunft) und
  Volltextsuche über Betreff und Klartext.
- KI-Werkzeug `briefe_suchen` für Fragen wie „Was haben wir dem Mieter zuletzt geschrieben?“.
- Später in derselben Akte: E-Mails aus dem Mail-Archiv (dessen Ordner tragen schon
  `reference_doctype`/`reference_name`) und eingehende Post aus Paperless.

## 10. KI: Rechte und Werkzeuge

Die KI arbeitet unter einem eigenen Benutzer mit eigener Rolle; in Produktion gibt es den eigenen
Benutzer schon.

| Darf | Darf nicht |
| --- | --- |
| Katalog und freigegebene Daten lesen | Briefe freigeben, stornieren, versenden |
| Briefentwürfe anlegen und ändern | Vorlagen, Bausteine und Revisionen direkt ändern |
| Datenabfragen anlegen und testen | Datensätze löschen |
| Änderungsvorschläge anlegen, auch „Neue Vorlage“ | Vorschläge übernehmen |

Werkzeuge:

| Bereich | Werkzeuge |
| --- | --- |
| Akte | `briefe_suchen`, `brief_lesen` |
| Brief | `brief_entwurf_anlegen`, `brief_entwurf_aendern` (mit Stand-Prüfung), `brief_vorschau` |
| Daten | `datenkatalog`, `datenabfrage_testen`, `datenabfrage_speichern`, `datenabfragen_suchen` |
| Vorlagen | `vorlagen_suchen`, `vorlage_lesen`, `vorlage_vorschau`, `aenderung_vorschlagen`, `vorschlag_aus_brief` |
| Serie | `durchlauf_vorbereiten` (aus der aktiven Revision, als Entwurf) |

Entscheidungsregel für die KI: Gibt es einen konkreten Empfänger oder Fall, entsteht ein Brief. Ein
Änderungsvorschlag entsteht nur, wenn ausdrücklich die Vorlage für künftige Briefe geändert werden
soll.

Die heutigen Werkzeuge (`prepare`, `save_draft`, `execute`, `propose_template_version` …) bleiben
während der Umstellung erhalten und werden danach abgelöst.

Ablauf am Beispiel „Zahlungserinnerung mit offenen Posten“:

1. `datenkatalog(startobjekt="Mietvertrag", suche="offene Rechnungen")` findet die Ansicht
   `open_items` und Sales Invoice samt Fachhinweisen.
2. `datenabfrage_testen(…, test_objekt=<Mietvertrag>)` liefert drei Zeilen.
3. `brief_entwurf_anlegen(vorlage="Zahlungserinnerung", objekt=<Mietvertrag>, …)` bindet
   `daten("Offene Posten des Mietvertrags")` ein.
4. `brief_vorschau` liefert die PDF. Der Benutzer ändert, gibt frei und erfasst den Versand.

## 11. Aufteilung auf die Apps

| App | Inhalt |
| --- | --- |
| `mail_merge` | Brief-Erweiterung, Bezüge-Tabelle, Status und Versand, flüchtige Vorschau, Datenabfrage mit Engine und `daten()`, Änderungsvorschlag, Word-Rückweg, Import-Grundgerüst (Konvertierung, Klartext, Dubletten) |
| `hausverwaltung` | Bezüge-Hook, Katalog-Freigaben und Fachhinweise, Ansichten und kuratierte Quellen, Korrespondenz an Mietvertrag, Wohnung und Immobilie, KI-Rolle und Werkzeuge (`agent_tools`), Zuordnungsvorschläge für den Import |
| `hausverwaltung_peters` | Import des konkreten PC-Ordners, einmalige Bereinigung der Produktionsdaten |

Public-Code importiert nie aus `hausverwaltung_peters` (CLAUDE.md).

## 12. Migration des Bestands

Alle Schemaänderungen sind additiv. Nichts wird automatisch gelöscht, Namen bleiben.

- **Briefdokumente:** Bezüge aus `objekt` nachtragen. Eingereichte gelten als freigegeben, mit
  unbekanntem Versanddatum. Nicht eingereichte bleiben Entwürfe.
- **Was wurde verschickt?** Vermutlich wurden auch nicht eingereichte Entwürfe gedruckt und
  verschickt; aus den Daten ist das nicht erkennbar. Eine Klärungsliste gruppiert sie nach
  Empfänger und Tag („Welche Fassung ging raus?“). Erst danach wird freigegeben, als versendet
  markiert oder gelöscht.
- **Vorlagen:** `aktive_revision` auf die Revision setzen, die dem heutigen Inhalt entspricht.
- **KI-Vorschläge:** als Änderungsvorschläge mit Status Offen anlegen. Vorschläge, die als
  Einzelbrief dienten, werden zur Bestätigung als „Verworfen – als Einzelbrief genutzt“
  vorgeschlagen. Ihre Revisionen bleiben, weil Briefe darauf verweisen.
- **Leere Durchläufe** ohne Dokument (in der Produktionskopie 12) nach Bestätigung löschen.
- **Trockenlauf** auf einer Produktionskopie im Dev-Stack, mit Zählung vorher und nachher.

## 13. Umsetzung in Stufen

Jede Stufe ist für sich nutzbar.

| Stufe | Inhalt | Nutzen |
| --- | --- | --- |
| 1 Auffinden | `durchlauf` optional, Bezüge mit Nachtrag, Status- und Versandfelder, Briefnummer auf dem PDF, Klartext, Korrespondenz-Abschnitt, Briefliste, `briefe_suchen` | Vorhandene Briefe sind sofort auffindbar; kein Ablauf ändert sich |
| 2 Einzelbrief | „Brief schreiben“, `eigener_inhalt`, flüchtige Vorschau auch für Revisionen, Freigabe der geprüften PDF, Versand inklusive E-Mail, Word-Rückweg, KI-Rolle und Brief-Werkzeuge, Einzelfall-Bremse | Einzelbriefe ohne Word; Vorlagenvorschläge werden nicht mehr zweckentfremdet |
| 3 Daten | Datenkatalog, Datenabfrage mit Engine und `daten()`, „Tabelle aus Daten“, KI-Datenwerkzeuge, Umbau der vorhandenen Daten-Bausteine | Tabellen mit Live-Daten, auch von der KI gebaut |
| 4 Altbestand | Briefimport, Zuordnungsvorschläge, Vorlagenkandidaten | Word-Ordner abgelöst; Liste fehlender Vorlagen |
| 5 Vorlagenpflege | `aktive_revision`, Änderungsvorschlag mit Paket, Render-Modus je Revision, eine Kennung, Migration der Vorschläge | Saubere Versionsgeschichte |

## 14. Offene Entscheidungen

| Frage | Empfehlung |
| --- | --- |
| Heißt der DocType künftig „Brief“? | Zunächst nur der Anzeigename über die deutsche Übersetzung; echte Umbenennung später oder nie |
| Akte als eigener Abschnitt oder über die Frappe-Timeline (Communication)? | Eigener Abschnitt; Communication nur beim E-Mail-Versand |
| Gehen ausgehende Briefe zusätzlich nach Paperless? | ERPNext ist führend für den Ausgang; Export nach Paperless optional |
| Wer darf freigeben und versenden? | Eigene Rolle, z. B. „Briefe freigeben“ |
| Dürfen ungeprüfte KI-Abfragen in Briefe? | Ja, der Mensch prüft den Brief bei der Freigabe; in Vorlagen nur über Vorschläge |
| Altbestand vollständig oder ab einem Jahr? | Nach Aufbewahrungsfristen und Nutzen entscheiden, Fristen mit dem Steuerberater klären |
| Darf ein Cloud-Modell Briefinhalte sehen (Import, Vorlagenkandidaten)? | Import und Gruppierung lokal; ein Cloud-Modell nur nach ausdrücklicher Entscheidung |
| Wie genau wird der Versand nachgewiesen? | Versandweg und Datum Pflicht; Einlieferungsbeleg optional als Anhang |

## 15. Risiken

| Risiko | Gegenmaßnahme |
| --- | --- |
| Abfragen je Empfänger machen große Durchläufe langsam | Pflicht-Bindung, Limits, Zwischenspeicher je Durchlauf, Indizes |
| Rechte filtern Zeilen stillschweigend weg | Leserecht je Quelle vorab prüfen; Fehler statt leerer Tabelle |
| Die KI deutet Felder fachlich falsch | Fachhinweise im Katalog, Testlauf mit echtem Empfänger, Freigabe durch einen Menschen, kuratierte Quellen für heikle Logik |
| Editor-Round-Trip bricht an neuen Schleifenformen | `daten()` nur in der Einzeilen-Form erzeugen; Round-Trip-Tests erweitern |
| Fehlzuordnung im Import | Nur eindeutige Vorschläge, Bestätigung durch einen Menschen, Customer-Invariante |
| Migration trifft Produktionsdaten | Trockenlauf auf einer Kopie, Klärungslisten statt automatischer Löschung |

## 16. Nicht-Ziele

- Kein Ersatz für Paperless bei der Eingangspost.
- Keine Änderung am Customer-Modell (ein Customer je Mietvertrag).
- Kein freies SQL oder Python für die KI.
- Kein Versand durch die KI.

## 17. Anknüpfungspunkte im Code

Pfade relativ zu `frappe_docker/apps/`.

| Thema | Stelle |
| --- | --- |
| Briefdokument | `mail_merge/mail_merge/mail_merge/doctype/serienbrief_dokument/` |
| Brief-Assistent (Prototyp) | `mail_merge/mail_merge/mail_merge/utils/letter_composer.py`, `mail_merge/docs/brief-erstellen-prototyp.md` |
| Versionierung | `mail_merge/mail_merge/mail_merge/utils/versioning.py`; `serienbrief_vorlage.py` (`save_editor_template`, `_versions_used_by_documents`) |
| Prüfung von KI-Quelltexten | `mail_merge/mail_merge/mail_merge/utils/assistant_templates.py` |
| Lesende Jinja-Umgebung | `mail_merge/mail_merge/mail_merge/utils/jinja_readonly.py` |
| Editor-Schleifen | `mail_merge/mail_merge_frontend/src_react/src/tiptap/tokens.js` |
| Word-Export | `mail_merge/mail_merge/mail_merge/utils/office_export.py` |
| Bestehende Hooks | `hausverwaltung/hausverwaltung/hooks.py` (`mail_merge_print_profile`, `mail_merge_transform_html`) |
| KI-Schnittstelle Serienbriefe | `hausverwaltung/hausverwaltung/hausverwaltung/agent_tools/` (`mail_merge_api.py`, `template_authoring_api.py`, `block_authoring_api.py`, `mail_merge_tools.py`) |
| Abfrage-Engine und Ansichten | `hausverwaltung/hausverwaltung/hausverwaltung/services/assistant.py` (`hv_query_docs`, `HV_READABLE_DOCTYPES`, `HV_QUERY_VIEWS`) |
| E-Mail-Versand | `hausverwaltung/hausverwaltung/hausverwaltung/doctype/email_entwurf/` |
| Zuordnungsmuster | `thunderbird_hausverwaltung/…/doctype/mail_filing_suggestion/` |
