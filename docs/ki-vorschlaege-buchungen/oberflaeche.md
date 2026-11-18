# KI-Buchungsvorschläge: Oberfläche

Stand 18.11.2026, überarbeitet nach dem Review von Auftrag 1. Vorlage ist der Design-Canvas „KI-Buchungsvorschläge“ (Markup in [mockup/](mockup/), siehe
[README.md](README.md)). Die Datenform steht in [schnittstelle.md](schnittstelle.md).

Teil A betrifft den Bankimport (Auftrag 1, überarbeitet in Auftrag 1b). Teil B betrifft die Vorschläge-Seite
und gehört zu Auftrag 2. Teil C beschreibt die Regelvorschläge im Regel-Fenster (Auftrag 3).

---

# Teil A: Bankimport (`/app/bankimport_v2`)

## Technik

- **Ort:** React-App `HV_Bankimport/src_react`. Build mit `npm run build:frappe`; die gebauten Dateien unter
  `hausverwaltung/public/bankimport_v2/` werden wie bisher mit committet.
- **Neue Komponenten** in `src/components/`:
  - `KiBanner.jsx` – Leiste über dem Phasen-Stepper
  - `KiCell.jsx` – Tabellenzelle „KI-Vorschlag“
  - `KiSuggestion.jsx` – KI-Abschnitt im Seitenpanel mit allen Zuständen
  - `KiBulkDialog.jsx` – Sammeldialog
- **Styles:** neue Datei `src/styles/styles-ki.css`, Klassen mit Präfix `ki-`. Bestehende Klassen
  (`invoice-card suggested`, `conf-row`, `pill`, `btn`, `seg`, `assign-row`, `kbd`) wiederverwenden.
- **Daten:** `row.ki` je Zeile und `meta.ki` je Import, Form in [schnittstelle.md](schnittstelle.md).
  `src/data.js` bekommt Mock-Daten mit allen Zuständen aus dem Canvas (Zeilen r1–r9).
- **Aktionen:** `src/api.js` bekommt `kiAccept`, `kiAcceptMany`, `kiReject`, `kiRequestRevision`. Im
  Mock-Modus (`embedded === false`) werden sie lokal simuliert. Die RPC-Allowlist (`RPC_ACTIONS`) in `bankimport_v2.js`
  bleibt in Auftrag 1 unverändert.

### Sichtbarkeit

- Alles KI-Bezogene erscheint nur, wenn `meta.ki` vorhanden ist. Fehlt es (heutiges Backend), sieht die Seite
  genau so aus wie heute: keine Spalte, kein Banner, kein Filter, kein KI-Abschnitt.
- Gibt es zu einer Zeile einen offenen oder veralteten KI-Vorschlag, entfällt die heuristische
  „Empfohlen“-Karte (`inferBestMode`, `reco-card`) für diese Zeile. Es gibt immer nur eine Empfehlung.

## Zustände eines Vorschlags

| Kern-Status | Anzeige | Pill im Panel | Tabellenzelle |
|---|---|---|---|
| `Pending` | Prüfung offen | `pill phase2` | KI-Marke, Ziel, Art · Sicherheit |
| `Approved` | Freigegeben | `pill phase3` | „Freigegeben · wartet auf Buchung“ |
| `Stale` | Veraltet | `pill danger` | „! Veraltet“, darunter Kurzgrund |
| `Succeeded` | Gebucht | `pill done` | „✓ übernommen“, darunter Belegnummer |
| `Rejected` | Abgelehnt | `pill ghost` | „Abgelehnt“ |
| `Rejected` mit Kategorie `adjusted_booked` | Angepasst gebucht | `pill ghost` „Abgelehnt“ | „Angepasst gebucht“, darunter Belegnummer |
| kein Vorschlag, Agent läuft | Agent prüft … | — | „Agent prüft …“ |
| kein Vorschlag, Agent enthält sich | Kein Vorschlag | — | „Kein Vorschlag“, darunter „Agent unsicher“ |

`Approved` entsteht, wenn jemand auf der Vorschläge-Seite freigibt, aber noch nicht ausführt. Im Panel sieht
es aus wie „Prüfung offen“, mit Pill „Freigegeben“, dem Hinweis „Freigegeben von … am …“ und der Hauptaktion
„Buchen“. Ablehnen gibt es in diesem Zustand nicht.

### KI-Marke und Sicherheit

- **KI-Marke:** kleines Etikett „KI“ in Mono, neutraler Rahmen (`--border-strong`), keine Farbe. Sie steht
  überall, wo ein Wert vom Agenten stammt: Banner, Filter, Tabellenzelle, Panel-Abschnitt.
- **Sicherheit:** drei Stufen hoch, mittel, niedrig. Darstellung als 3-Segment-Balken plus Text, nie nur
  Farbe. Farben `--done`, `--warn`, `--danger`. Eine Prozentzahl wird nirgends angezeigt, auch wenn
  `confidence.score` geliefert wird. Sie stammt vom Agenten und ist keine geprüfte Wahrscheinlichkeit.
- Die Vorschlagskarte nutzt den vorhandenen Stil `invoice-card suggested` (Gold-Tönung). Keine neue
  Akzentfarbe für KI.

## 1. Banner

Zwischen Statistik-Karten und Phasen-Stepper, volle Breite (Artboard A1).

- **Vorschläge da:** links KI-Marke, „n Vorschläge offen für m offene Zeilen“, darunter Agent, Zeitpunkt und
  Paket-ID. In der Mitte Zahlen je Stufe, dazu „veraltet“ und „ohne Vorschlag“. Rechts:
  - „Im Paket ansehen →“ (subtil): öffnet `/app/hv-proposals/<package>` über eine neue Navigationsaktion
    `open_proposals` in `NAV_ACTIONS`. Die Navigation gehört zu Auftrag 1.
  - „Vorschläge übernehmen …“ mit Zahl der hohen Vorschläge: öffnet den Sammeldialog. Sekundärer Button;
    der einzige Primärbutton der Seite bleibt „Neuer Import“.
- **Agent läuft:** Spinner, „Agent prüft den Auszug … x von y Zeilen“, darunter „Startet automatisch nach dem
  CSV-Import · Selbst zuordnen geht jederzeit“. Keine Buttons. Der Agent startet nach jedem CSV-Import von
  selbst; einen Knopf „Vorschläge anfordern“ gibt es nicht. In A1 über den Tweak `banner` zu sehen.
- **Alles erledigt:** einzeilig, gedämpft: „Alle Vorschläge erledigt · n übernommen · m abgelehnt“.
- **Kein Paket:** kein Banner.

Die Zahlen aktualisieren sich nach jeder Aktion aus der neu geladenen Übersicht.

## 2. Filter

Neuer Chip „KI Vorschlag“ mit Zahl, direkt nach „Alle“. Er zeigt Zeilen mit Status `Pending` oder
`Approved`. Bei 0 deaktiviert wie die anderen Chips.

## 3. Tabelle

- Neue Spalte **„KI-Vorschlag“**, 196 px, zwischen „Verwendungszweck“ und „Status“. Inhalt je Zustand siehe
  Tabelle oben. Zwei Zeilen: oben Ziel in Mono (z. B. `SINV-2026-0041`, `Erika Beispiel → SINV-…0052`),
  unten Sicherheitsbalken und Art („Rechnung · hoch“). Lange Werte werden mit „…“ gekürzt, voller Text im
  `title`.
- Die Partei-Spalte zeigt bei Zeilen ohne Partei weiterhin „Keine Partei“ bzw. den Auftraggeber. Ein
  Parteivorschlag steht nur in der KI-Spalte, nie so, als wäre er schon zugeordnet.
- Unter 760 px Breite werden „KI-Vorschlag“ und „Verwendungszweck“ ausgeblendet. Der Betrag bleibt in
  jeder Tabellenzeile sichtbar, die Tabelle scrollt nicht seitlich. Unter der Partei steht dann eine
  kompakte **KI-Marke**: Etikett „KI“, Sicherheitsbalken und Stufe bei `Pending` und `Approved`, „KI
  veraltet“ in Rot bei `Stale`. Andere Zustände zeigen keine Marke (Artboard D2). Der Vorschlag selbst
  steht im Panel unter der Tabelle.
- Unter der Tabelle eine Zeile mit Tastenhinweisen (siehe 6).

## 4. Seitenpanel

Reihenfolge: Kopf (unverändert) → **KI-Abschnitt** → **Selbst zuordnen** (heutiger Inhalt für Phase 1 bzw. 3).
Alle acht Zustände zeigt Artboard B1, die Komponente B2.

### Prüfung offen

Karte `invoice-card suggested`, kompakt (Artboard B1, Zustände 1–5):

1. Kopfzeile: KI-Marke, „Vorschlag“, Badge „Rev. n“, Pill „Prüfung offen“.
2. Art als Etikett, z. B. „Rechnung zuordnen“, „Partei und Rechnung · 2 Schritte“, „Buchungssatz“.
3. **Schritte** als nummerierte Liste (1 oder 2): Art, Ziel fett, Unterzeile, Betrag rechts.
4. **Sicherheit** als Balken plus Stufe.
5. **Details**, aufklappbar:
   - **Buchung (Vorschau):** Tabelle Konto | Soll | Haben aus `postings`, darunter ein Satz zur Wirkung
     (`effect`), z. B. „Zahlung wird angelegt und gebucht. SINV-2026-0041 ist danach ausgeglichen.“
   - **Begründung** kursiv in Anführungszeichen, darunter „Belege:“ mit Links (`DocLink`).
6. Umschalter am Kartenende: Button mit `aria-expanded`, Text „Details · Buchung, Begründung, Belege ▾“
   bzw. „Details ausblenden ▴“.

Startzustand der Details: bei Sicherheit `hoch` eingeklappt, bei `mittel` und `niedrig` aufgeklappt. Die
Wahl des Benutzers gilt nur für die aktuelle Zeile; beim Zeilenwechsel gilt wieder der Startzustand. Das
Gleiche gilt für `Approved`. Die kompakte Karte einschließlich Kopfzeile und Aktionen ist bei einem Schritt
höchstens 320 px hoch.

Darunter die Aktionen:

| Aktion | Wirkung |
|---|---|
| **Übernehmen & buchen** (primär, `↵`) | `kiAccept`: Freigabe und Ausführung in einem Request. Bei zwei Schritten heißt der Button „Beide übernehmen & buchen“ und führt in Reihenfolge aus. |
| **Anpassen** | Klappt „Selbst zuordnen“ auf, wählt den passenden Modus und füllt ihn vor: Rechnung angehakt, Gegenkonto und Kostenstelle eingetragen, Abschlags- bzw. Kreditrate gewählt. Gebucht wird dann mit den heutigen Knöpfen. Über dem Formular steht der Hinweis „Vom KI-Vorschlag vorausgefüllt. Wird hier abweichend gebucht, schließt das den Vorschlag automatisch als ‚Abgelehnt‘ mit dem Grund ‚Angepasst gebucht: Beleg‘. Das geht als Rückmeldung an den Agenten.“ (B1, Zustand 7) |
| **Ablehnen …** (`R`) | Wechselt die Karte in das Ablehnungsformular. |

Fußzeile: „Freigabe und Buchung werden einzeln für Revision n protokolliert. Im Paket ansehen →“.

Fehlen dem Benutzer die Rechte (`meta.ki.canAccept === false`), stehen statt „Übernehmen“ und „Ablehnen“
der Hinweis „Nur Prüfer können Vorschläge übernehmen.“ und nur „Anpassen“.

### Ablehnen

Inline in der Karte, kein Dialog:

- Frage „Was stimmt nicht?“ mit Radio-Chips: Falsche Partei · Falscher Beleg · Anderes Konto · Nicht buchen ·
  Sonstiges.
- Feld „Begründung (Pflicht)“, 1–1000 Zeichen. „Ablehnen“ ist deaktiviert, solange es leer ist.
- Hinweis „Geht als Rückmeldung an den Agenten. Die Zeile bleibt offen.“
- Buttons „Ablehnen“ (danger) und „Abbrechen“ (`Esc`).
- Danach: Karte wird zur Notiz „Abgelehnt von … · Zeit: Grund“, „Selbst zuordnen“ ist aufgeklappt.

### Veraltet

Karte mit gestricheltem roten Rand, Ziel durchgestrichen, Ursache als Satz aus `staleText`, z. B. „Die
vorgeschlagene Rechnung ACC-PINV-2026-0090 wurde am 17.04. mit PE-2026-0052 ausgeglichen.“ Einzige Aktion
„Neue Revision anfordern“. „Selbst zuordnen“ ist aufgeklappt.

### Gebucht aus Vorschlag

Wie die heutigen erledigten Zeilen (`assign-row done-row` für Bank-Tx und Beleg), dazu die Herkunft:
„Freigegeben und gebucht von M. Krüger · Zeit · Vorschlag HVP-… →“. „Beleg lösen …“ bleibt wie heute.

### Angepasst gebucht

`Rejected` mit `decision.category = "adjusted_booked"` (B1, Zustand 8). Aufbau wie „Gebucht aus Vorschlag“,
aber mit Pill „Abgelehnt“ (`pill ghost`) und statt der Herkunft:

- „Selbst gebucht: <`decision.voucher.summary`>“
- „Vorschlag war: <`summary`>“, durchgestrichen
- „Automatisch abgelehnt mit Grund ‚Angepasst gebucht: <Beleg>‘ · <wer> · <wann> · Vorschlag HVP-… →“
- „Beleg lösen …“ wie heute

### Agent prüft / Kein Vorschlag

- **Agent prüft:** gestrichelter Kasten mit Spinner „Agent prüft diese Zeile …“ und Hinweis „Selbst zuordnen
  geht jederzeit. Kommt der Vorschlag danach, gilt er als veraltet.“
- **Kein Vorschlag:** die Begründung des Agenten kursiv, darunter Agent und Zeit, Button „Erneut anfordern“.
  Er ruft `kiRequestRevision` ohne Bindung auf; danach zeigt die Zeile „Agent prüft …“.

In beiden Fällen ist „Selbst zuordnen“ aufgeklappt.

### Selbst zuordnen

- Bei „Prüfung offen“ und „Freigegeben“ eingeklappt: ein Button mit `aria-expanded`, Titel „Selbst
  zuordnen“ und den Modi als Kurztext („Rechnung · Aufteilen · Abschlag · …“).
- In allen anderen Zuständen aufgeklappt, Inhalt wie heute (`PartyAssign` bzw. `BookingActions`).
- Wird manuell gebucht, während ein Vorschlag `Pending` oder `Approved` ist, schließt das Backend ihn als
  `Rejected` mit Kategorie `adjusted_booked` (schnittstelle.md 4.6). Die Oberfläche lädt danach nur neu und
  zeigt „Angepasst gebucht“.

### Nach dem Übernehmen

- Erfolgsmeldung je Art, z. B. „Zahlung gebucht · SINV-2026-0041 ausgeglichen“, „Buchungssatz gebucht ·
  JV-2026-0044“.
- Danach springt die Auswahl zur nächsten Zeile mit offenem Vorschlag (wie heute `onActionDone`).
- Antwort `Stale`: nichts gebucht, Meldung „Vorschlag ist veraltet, nichts gebucht.“, Zeile zeigt „Veraltet“.
- HTTP 409: „Die Daten haben sich gleichzeitig geändert. Bitte erneut versuchen.“, Übersicht neu laden.
- Zwei Schritte, Schritt 2 scheitert: „Partei zugeordnet, Buchung fehlgeschlagen: …“. Schritt 2 steht danach
  auf „Freigegeben“ und lässt sich mit „Buchen“ erneut versuchen.
- Andere Fehler: Servermeldung als Fehlermeldung, Zeile bleibt unverändert.

## 5. Sammeldialog

Artboard A2. Öffnet über den Banner.

- Kopf: KI-Marke, „Vorschläge übernehmen“, darunter Bankkonto, Zeitraum, Paket-ID. Schließen-Button.
- Auswahl-Leiste: Segment „Hohe Sicherheit | Alle | Keine“, rechts „n ausgewählt · Eingang … · Ausgang …“.
- Liste aller Vorschläge mit Status `Pending` oder `Approved` zu offenen Zeilen: Checkbox, Datum, Betrag,
  Zeile, Vorschlag (Ziel und Art), Sicherheit. Beim Öffnen ist die Auswahl leer. „Hohe Sicherheit“ wählt
  die Vorschläge mit hoher Sicherheit auf Klick aus.
- Unter der Liste: „Nicht auswählbar: n veraltete Vorschläge und m Zeilen ohne Vorschlag.“ und der Hinweis
  „Jeder Vorschlag wird einzeln für seine Revision freigegeben und danach in Datumsreihenfolge gebucht. Bei
  zwei Schritten erst Partei, dann Buchung. Bei einem Fehler stoppt der Lauf, bereits Gebuchtes bleibt
  gebucht.“
- Buttons „Abbrechen“ und „n übernehmen und buchen“ (primär, bei 0 deaktiviert).
- Ergebnis im selben Dialog: Zusammenfassung „n gebucht · m übersprungen“, je Zeile Ergebnis mit Belegnummer
  oder Grund. Buttons „Zurück zur Auswahl“ und „Schließen“. Beim Schließen wird die Übersicht neu geladen.
- Gesendet werden genau die angezeigten Bindungen (ID, Revision, Hash), höchstens 128.

## 6. Tastatur

Neu im Bankimport, nur wenn der Fokus in Tabelle oder Panel liegt und nicht in einem Eingabefeld:

- `J` / `K`: nächste / vorherige Zeile
- `↵`: „Übernehmen & buchen“, nur wenn die Karte „Prüfung offen“ im sichtbaren Bereich liegt. Liegt sie
  außerhalb (schmale Ansicht), scrollt `↵` zuerst die Karte ins Bild und bucht erst beim nächsten `↵`.
- `R`: Ablehnungsformular öffnen
- `Esc`: Ablehnungsformular schließen

Der Handler hängt am App-Wurzelelement im iframe, nicht an `window` der Desk-Seite.

**Schmale Ansicht** (Artboard D1): Unter 1100 px steht das Panel unter der Tabelle. Jeder Zeilenwechsel per
Klick, `J`/`K` oder Zeilenlink scrollt das Panel ins Bild (`scrollIntoView`, Anfang des Panels oben). Ab
1100 px steht das Panel wie heute daneben und es wird nicht gescrollt.

## 7. Tiefer Link

`/app/bankimport_v2?import=<name>&row=<row>` wählt die Zeile vor. `bankimport_v2.js` übernimmt `row`
aus der Desk-URL und gibt es zusammen mit `import` URL-kodiert an das iframe weiter. `bridge.js` liest
`row` aus der iframe-URL. Die App wählt die Zeile nach dem Laden des Imports aus und öffnet ihr Panel.
Ein unbekanntes `row` lässt den Import normal öffnen. Die Vorschläge-Seite nutzt den Link in Teil B.

## 8. Abnahme Teil A

- **Vitest** (`npm test` in `HV_Bankimport/src_react`):
  - `KiCell` und `KiSuggestion` für alle Zustände aus der Tabelle oben
  - Sicherheit wird als Text ausgegeben, nicht nur als Farbe
  - ohne `meta.ki` erscheinen weder Spalte noch Banner noch Chip noch KI-Abschnitt
  - „Ablehnen“ ist ohne Begründung deaktiviert
  - Sammeldialog: leere Startauswahl, Auswahl durch „Hohe Sicherheit“, Summen, veraltete Vorschläge nicht auswählbar
  - bestehende Tests bleiben grün
- **Playwright** gegen den Mock-Dev-Server (`npm run test:e2e`):
  1. Zeile wählen → „Übernehmen & buchen“ → Meldung, Zeile „Gebucht“, nächste offene Zeile gewählt
  2. Ablehnen mit Kategorie und Grund → Notiz, „Selbst zuordnen“ aufgeklappt
  3. „Anpassen“ bei einer Rechnungszeile → Rechnungsmodus, Rechnung vorausgewählt
  4. Sammeldialog öffnet leer und die Buchungsaktion ist deaktiviert → „Hohe Sicherheit“ → 3 übernehmen → Ergebnisliste
  5. Filter „KI Vorschlag“
  6. Unter 760 px bleibt der Betrag jeder Zeile sichtbar.
- **Zeilenlink:** Test für die Weitergabe von `row` in die iframe-URL und Playwright-Test für die Auswahl der
  Zeile mit `row` in der Mock-App. Der Sprung von der echten Vorschläge-Seite wird in Teil B geprüft.
- **Regression:** `tests/e2e/bankimport.spec.js` läuft unverändert mit Mock-Daten ohne `ki`.
- **Bilder im PR:** A1-Zustand bei 1440 px und bei 1100 px (Panel unter der Tabelle), Panel in allen acht
  Zuständen, Sammeldialog vor und nach dem Lauf.

## 9. Abnahme Auftrag 1b

- **Vitest:**
  - Details bei `hoch` eingeklappt, bei `mittel` und `niedrig` aufgeklappt; Umschalten mit `aria-expanded`;
    beim Zeilenwechsel wieder Startzustand
  - `KiConfidence` gibt nie eine Prozentzahl aus, auch nicht mit `score`
  - „Angepasst gebucht“ aus `Rejected` mit `adjusted_booked`, in Panel und Tabellenzelle
  - „Erneut anfordern“ bei `state: "none"` ruft `kiRequestRevision` ohne Bindung auf
- **Playwright** gegen den Mock-Dev-Server:
  1. Zeile mit hoher Sicherheit: Details zu, kompakte Karte mit Aktionen höchstens 320 px hoch
  2. Zeile mit mittlerer Sicherheit: Details offen; Umschalten und Zeilenwechsel setzen zurück
  3. „Anpassen“ zeigt den Hinweis zur abweichenden Buchung
  4. Bei 1024 px scrollt ein Zeilenklick das Panel ins Bild. `↵` bei nicht sichtbarer Karte bucht nicht,
     sondern scrollt; das zweite `↵` bucht.
  5. Bei 390 px zeigt jede Zeile mit offenem Vorschlag die KI-Marke mit Stufe. Alle Beträge sichtbar, kein
     seitliches Scrollen.
  6. „Kein Vorschlag“ → „Erneut anfordern“ → „Agent prüft …“
- **Regression:** alle Tests aus Abschnitt 8 bleiben grün.
- **Bilder im PR:** Karte kompakt und aufgeklappt, „Anpassen“ mit Hinweis, „Angepasst gebucht“, Bankimport
  bei 1024 px und 390 px.

---

# Teil B: Vorschläge-Seite (`/app/hv-proposals`), Auftrag 2

Baut auf `hausverwaltung/public/js/hv_proposals.js` auf. Artboards C1 und C2. Kein neues Layout, nur
Ergänzungen. Jede Ergänzung erscheint nur, wenn die Daten dafür da sind.

## Paketliste

- Neuer Filter **„Art“** neben „Agent“: Alle Arten · Buchungen · Verträge · Briefe. „Buchungen“ sind Pakete,
  deren Vorschläge Aktionen mit Präfix `hv.bankimport.` haben.
- Bei Paketen mit Bezug `Bankauszug Import`: unter dem Titel neben der Bezugskennung der Link „im Bankimport
  öffnen“.

## Paketansicht

- Kopf: zusätzlicher Button **„Im Bankimport öffnen →“** links von „Offene freigeben …“.
- Zeilen-Beschriftung aus `lane.label`, z. B. „01.04. · +720,00 € · Max Mustermann“. Keine Wurzel; Pakete
  ohne Wurzel beginnen links mit den Zeilen.
- Detailspalte, zusätzlich:
  - **„Buchung (Vorschau)“** aus `preview.postings` als Tabelle Konto | Soll | Haben, nach „Änderung“
  - **Sicherheit** (KI-Marke, Balken, Stufe, keine Prozentzahl) als erste Zeile in „Begründung des Agenten“
  - Zieldokument-Link führt auf die Bankimport-Zeile (`?import=…&row=…`)
  - Hinweis bei offenen Buchungsvorschlägen: „Ausgeführt wird über dieselbe Logik wie ‚Übernehmen &
    buchen‘ im Bankimport.“
  - Beim Ausführen (`effects`) deutsche Texte für die neuen Aktionen in `translateEffect`
- Verlauf: Freigaben aus dem Bankimport zeigen den Zusatz „(im Bankimport)“.

## Abnahme Teil B

- Playwright gegen einen frischen isolierten Stack mit einem synthetischen Buchungspaket (siehe
  [schnittstelle.md](schnittstelle.md), Abschnitt „Testdaten“): Paket in der Liste mit Art „Buchungen“,
  Paketansicht mit Zeilen, Detail mit „Buchung (Vorschau)“, Sprung in den Bankimport auf die richtige Zeile.
- Bestehende Proposals-Tests (`tests/proposals_*`) bleiben grün.

---

# Teil C: Regelvorschläge im Regel-Fenster, Auftrag 3

Artboard E1. Wiederkehrende Muster in gebuchten Zeilen werden als Bankimport-Regel vorgeschlagen, damit
solche Zeilen künftig ohne KI zugeordnet werden. Kein Agent, kein LLM.

## Ort

- Das bestehende Regel-Fenster (`RulePanel.jsx`, Knopf „Regeln“ in der Kopfleiste). Neben „Liste“ und
  „Graph“ kommt eine dritte Ansicht **„Vorschläge“** mit der Zahl offener Vorschläge.
- Der Knopf „Regeln“ zeigt die Zahl offener Regelvorschläge als `kbd`-Badge. Sind welche offen, öffnet das
  Fenster direkt auf „Vorschläge“.
- Nicht auf der Vorschläge-Seite (`hv-proposals`). Dort stehen Agenten-Pakete mit Freigabe und
  Prüfprotokoll.

## Aufbau der Ansicht

- Leiste oben: Marke „MUSTER“ (gestrichelter Rahmen, bewusst nicht „KI“), „n offene Regelvorschläge aus
  gebuchten Zeilen der letzten 12 Monate“, daneben „Mustersuche ohne KI · läuft nach jedem Import · zuletzt
  <Zeit> · m Muster früher verworfen“.
- Links die Vorschläge als Karten: Gruppe („Party Matching“ oder „Buchungs-Matching“), Pill „Neu“,
  „Angelegt“ oder „Verworfen“, Titel, Kurzform der Regel, Balken „x von n gleich gebucht“ (grün gleich, gelb
  abweichend).
- Rechts das Detail des gewählten Vorschlags:
  1. Kopf: Gruppe und Regelart, Titel, vorgeschlagene Priorität mit Einordnung, z. B. „vor ‚Zur Prüfung
     markieren‘“.
  2. **Regel** im Format der Regelkarten: „ƒ wenn <Bedingungen> → <Aktion>“, optional ein Hinweis, z. B.
     warum die IBAN allein nicht reicht.
  3. **Beleg aus der Historie:** „n Treffer seit MM/JJJJ · x genauso gebucht · y abweichend“, Monatsleiste
     über 12 Monate (grün gleich gebucht, gelb abweichend, gestrichelt kein Treffer), die letzten vier
     Treffer mit Datum, Betrag, Beleg und „Gebucht als“, darunter „+ k weitere Treffer“. Abweichungen als
     gelber Hinweis mit Datum, Betrag, Beleg und Erklärung.
  4. **Wirkung:** Treffer im aktuellen Auszug, Überschneidung mit bestehenden Regeln bzw. Bindung an einen
     Mietvertrag.
  5. **Anlegen als:** Radio „Zur Prüfung vorlegen (empfohlen)“ und „Automatisch buchen“ (Buchungsregel) bzw.
     „Automatisch zuordnen“ (Party-Regel). Standard ist „Zur Prüfung vorlegen“. Gibt es eine Abweichung, ist
     „Automatisch“ deaktiviert und erklärt warum.
  6. Aktionen: „Regel anlegen“ (primär), „Bearbeiten …“ (öffnet den bestehenden `RuleEditor`
     vorausgefüllt), „Verwerfen …“.
- **Verwerfen** inline: Radio-Chips „Zufall, kein echtes Muster“ · „Ändert sich bald“ · „Lieber von Hand“ ·
  „Sonstiges“, Checkbox „Dieses Muster nicht wieder vorschlagen“ (vorausgewählt), Buttons „Verwerfen“ und
  „Abbrechen“.
- Nach dem Anlegen: Erfolgszeile „✓ Regel angelegt · <Schlüssel> · aktiv, Treffer zur Prüfung“ bzw. „…
  bucht automatisch“, Hinweis auf die Liste, Button „Rückgängig“. Nach dem Verwerfen: „Verworfen · wird
  nicht wieder vorgeschlagen“, Button „Wiederherstellen“.
- Unter 900 px stehen Liste und Detail untereinander, die Spalte „Gebucht als“ entfällt.

## Was „Regel anlegen“ erzeugt

Eine normale `Bankimport Party Regel` bzw. `Bankimport Buchungsregel` im Builder-Format, wie sie der
`RuleEditor` heute speichert: Bedingungen, Aktion, Priorität und `requires_review` bzw. `auto_apply` nach der
Wahl „Anlegen als“. Danach steht sie in Liste und Graph wie jede andere Regel.

## Abnahme Teil C

- Vitest für Liste, Detail, Anlegen, Verwerfen, Rückgängig und das deaktivierte „Automatisch“ bei
  Abweichung.
- Playwright gegen den Mock-Dev-Server mit den drei Vorschlägen aus E1.
- Bestehende Regel-Tests bleiben grün.
