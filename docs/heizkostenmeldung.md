# Heizkostenmeldung und Vorlagenversionen

Die Meldung sammelt die Eingaben für den Wärmedienst. Sie erzeugt keine
Buchungen. Die fertige externe Abrechnung wird weiterhin in
**Heizkostenabrechnung Immobilie** verarbeitet und kann mit der Meldung
verknüpft werden.

## Ablauf

1. Unter **Betriebskosten → Heizkostenmeldungen** eine Meldung mit Immobilie,
   Abrechnungszeitraum und freigegebener Vorlagenversion anlegen.
2. **ERP-Daten laden** ermittelt die Wohnungen und sämtliche Mietverhältnisse
   im Zeitraum. Mieterwechsel erhalten getrennte Zeilen; Vertragslücken
   erscheinen als Leerstand. Hauptmieternamen stammen aus den Vertragspartnern.
3. Die **Wohnungsnummer (ERP)** wird aus `Wohnung.id` übernommen und als erste
   Spalte im Excel-Blatt **Nutzer** ausgegeben. Sie bleibt bei Mieterwechseln und
   Leerstand gleich. Eine separate Nutzernummer beim Messdienst ist optional.
   Bestehende Entwürfe einmal mit **ERP-Daten laden** aktualisieren; archivierte
   Exporte bleiben unverändert. Heizflächen und Meldevorauszahlungen bestätigen.
   ERP-Wohnfläche und Heizfläche bleiben getrennt. IST und SOLL kommen aus der
   bestehenden Vorauszahlungsberechnung. Fehlende Rechnungsmonate und andere
   Hinweise benötigen eine dokumentierte Klärung.
4. Heizölbestände, Lieferungen, Heizungsnebenkosten und Zusatzangaben erfassen.
   Eingangsrechnungen/Belege können verknüpft werden. Die Vollständigkeit wird
   ausdrücklich bestätigt; ein bestätigter Nullbetrag ist zulässig.
   Bei Heizöl kann der Messdienst den Endbestandswert bestimmen.
5. **Angaben prüfen** zeigt offene Eingaben. Ein Entwurfsexport enthält diese
   zusätzlich in einem Tabellenblatt. **Freigeben** prüft Pflichtfelder und
   vergleicht die Belegung und ERP-Werte nochmals mit dem Datenstand.
6. Die Freigabe archiviert die XLSX-Datei privat mit SHA-256-Prüfsumme.
   Spätere Downloads liefern dieselben Bytes. **Versand vermerken** speichert
   Zeitpunkt und Benutzer; es versendet keine E-Mail.

Der Zeitraum und die Immobilie sind nach dem Datenladen fest. Bei einer
Änderung von Vertragszeiträumen, durch die vorhandene Nutzerzeilen entfallen,
bleiben die bisherigen Eingaben erhalten und die Anwendung verlangt eine neue
Meldung. Nach Storno kann ein Änderungsentwurf angelegt werden; dabei muss die
Belegung neu geladen und müssen die Beträge erneut bestätigt werden.

## Mieterliste mit Feldauswahl

**Excel herunterladen** öffnet eine Auswahl zwischen **Mieterliste mit
Feldauswahl** und **Vollständige Heizkostenmeldung**. Für die kurze Liste sind
Wohnungsnummer, Mieter, gezahlte HK-Vorauszahlung (ERP-IST) und Wohnfläche
vorausgewählt. Weitere Spalten einschließlich der Nutzer-Zusatzfelder der
Vorlage können einzeln ausgewählt werden. Leerstandszeiträume sind optional.

Die gezahlte Vorauszahlung ist die gespeicherte ERP-IST-Summe für den
Abrechnungszeitraum; SOLL und der bestätigte Meldebetrag sind eigene Felder.
Wohnfläche und bestätigte Heizfläche bleiben getrennt. Je Mietverhältnis
wird eine Zeile ausgegeben, auch bei Mieterwechseln in derselben Wohnung.
Die Mieterliste wird numerisch nach der ERP-Wohnungsnummer und innerhalb einer
Wohnung chronologisch nach Nutzungsbeginn sortiert. Die Wohnungsnummer steht in
Excel als Zahl, damit eine erneute Sortierung in Excel oder Calc ebenfalls
`1, 2, 3, …, 10` ergibt.
Die Liste nutzt den gespeicherten Datenstand; Entwürfe bei Bedarf zuvor über
**ERP-Daten laden** aktualisieren. Die kurze Liste ist ein separater Auszug.
Der vollständige Download freigegebener Meldungen liefert weiterhin die
unveränderte archivierte Datei.

## Vorlagen

**Heizkostenmeldung Vorlage** repräsentiert jeweils eine Version, beispielsweise
`ares-v2`. Die mitgelieferte zweite ares-Version ergänzt die erste Version um
die beim vollständigen Fotoabgleich ermittelten Felder. Sie enthält keine
personenbezogenen Beispieldaten und keine vorgegebenen rechtlichen Antworten.

Für neue Meldungen **ares-v2** auswählen. Bestehende Meldungen mit `ares-v1`
behalten ihre Vorlagendefinition; ein Wechsel erfolgt über eine neue Meldung.
Bereits archivierte Excel-Dateien bleiben unverändert.

## Ergänzte Formularangaben

| Foto / Formularbereich | Eingabe und Export |
| --- | --- |
| Heizkostenermittlung: Abzüge | Allgemeine Abzüge, einmalige Soforthilfe und Brennstoffpreisbremse getrennt unter **Heizkosten**; alle drei Beträge werden einmal abgezogen. Einen bereits im allgemeinen Abzug enthaltenen Betrag zuerst dort herausnehmen. |
| Zusatzangaben Brennstoffkosten | Beliebig viele Zeilen **Steuern, Abgaben und Zölle** mit Bezeichnung, Bruttobetrag, MwSt.-Satz und Bestätigung, auch bei 0 %. Excel-Blatt **Brennstoffabgaben**. |
| Verwaltungsanschrift | Hausbesitzer, Verwaltung/Ansprechpartner, Adresszusatz, Straße, PLZ, Ort, Telefon, E-Mail und Fax in den Zusatzangaben. |
| Bankverbindung | Kontonummer/IBAN, BLZ/BIC, Bank und Kontoinhaber getrennt; führende Nullen bleiben erhalten. |
| Wohnungsliste | Zusätzlich Eigentümer, Warmwasserfläche und weitere Hausbewohner; Summen der Heiz-, Warmwasser- und Nebenkostenflächen sowie der Heiz- und Hausnebenkostenvorauszahlungen im Blatt **Summen**. |
| Abzurechnende Gesamtkosten | Bestätigte Brennstoffkosten nach Abzügen plus zusätzliche Brennstoffabgaben plus Heizungsnebenkosten, vor CO₂-Aufteilung durch den Wärmedienst. |
| Bestätigung auf Heizkosten- und CO₂-Formular | Eigener Reiter **Bestätigung** mit Ort, Datum, Name und separaten Zeichenfeldern für beide Unterschriften. Excel-Blatt **Bestaetigung** enthält die eingegebenen Zeichnungen oder freie Unterschriftszeilen für den Ausdruck. |

Bereits im Brennstoffbetrag enthaltene Steuern/Abgaben werden **nicht erneut
addiert**. Nur bei ausdrücklich gewähltem **Zusätzlich berechnen** fließt eine
Position zusätzlich in die Gesamtkosten ein. Alle Abgabenzeilen müssen vor
Freigabe bestätigt werden. Die bisherigen Zusatzfelder für Umsatzsteuer und
Bevorratungsbeitrag in `ares-v1` bleiben als alte Aufschlüsselung bestehen;
`ares-v2` nutzt dafür die neue Tabelle.

Die Summen zeigen ausschließlich gespeicherte und bestätigte Werte. Flächen
werden einmal je Wohnung gezählt. Weichen Flächen zwischen Nutzungszeiträumen
derselben Wohnung ab oder fehlen Angaben, bleibt die Flächensumme offen und
benennt die betroffenen Wohnungen. Vorauszahlungen werden über die einzelnen
Nutzungszeiträume addiert. Bestimmt der Wärmedienst den Endbestandswert, bleiben
Brennstoff- und Gesamtkosten offen; es wird kein fiktiver Endwert eingesetzt.

Unterschriften werden nur von der ausfüllenden Person gezeichnet, nicht aus
Vorjahresfotos übernommen. Zu einer Zeichnung gehören Name und Datum. Leere
Unterschriftsfelder können nach dem Ausdruck ausgefüllt werden. Jahreswechsel
und Änderungsentwurf übernehmen keine Unterschriften oder Bestätigungsdaten.

## Eigene Zusatzfelder

Eine Vorlagenzeile definiert:

- Feldschlüssel, Bezeichnung, Abschnitt und Einheit;
- Bereich: Meldung, Nutzer, Kosten oder Brennstofflieferung;
- Typ: Text, mehrzeiliger Text, Datum, Ganzzahl, Dezimalzahl, Geldbetrag oder Auswahl;
- Auswahlwerte, optionalen Standardwert und Pflicht bei Freigabe;
- ob ein stabiler Wert ins Folgejahr übernommen werden soll.

Zusatzfelder der Meldung erscheinen als Eingabefelder im Reiter
**Zusatzangaben**. Bei Tabellenzeilen öffnet **Zusatzfelder bearbeiten** die
passenden Eingaben. In Excel erscheinen zeilenbezogene Zusatzfelder als
zusätzliche Spalten; Meldungsfelder stehen im Blatt **Zusatzangaben**.

Freigegebene Versionen sind unveränderlich. **Neue Version** erstellt einen
bearbeitbaren Entwurf. Jede Meldung speichert zusätzlich ihre vollständige
Vorlagendefinition. Es werden keine globalen Frappe-Custom-Fields aus der
Vorlage erzeugt und keine Formeln oder Skripte daraus ausgeführt.

**Folgejahr anlegen** erlaubt die Auswahl einer neuen freigegebenen Version.
Es übernimmt nur ausdrücklich markierte, typkompatible Zusatzfelder sowie
eindeutige Wohnungsstammdaten. Neue Pflichtfelder bleiben sichtbar offen;
Kosten und Jahresverbräuche werden nicht übernommen. Nutzerbezogene Extras
werden ausschließlich bei demselben Mietvertrag übernommen. Bestände und
Flächen müssen erneut bestätigt werden.

## Installation und Prüfungen

Die sieben DocTypes werden beim normalen `bench migrate` synchronisiert. Die
Patches `seed_heizkostenmeldung_vorlage` und `seed_heizkostenmeldung_vorlage_v2`
legen `ares-v1` und `ares-v2` idempotent an; beide Seeds sind auch für
Neuinstallationen registriert. Eine bereits anders belegte `ares-v2` wird
nicht überschrieben; der Patch meldet einen Versionskonflikt. Die Navigation wird über
den vorhandenen Workspace-/Sidebar-Aufbau ergänzt.

Tests:

- `hausverwaltung.hausverwaltung.scripts.heizkosten.test_meldung`
- `hausverwaltung.hausverwaltung.scripts.heizkosten.test_meldung_v2`
- `hausverwaltung.hausverwaltung.scripts.heizkosten.test_meldung_auswahl`
- `hausverwaltung.hausverwaltung.doctype.heizkostenmeldung.test_heizkostenmeldung`

Der DocType-Test benötigt eine initialisierte Frappe-Test-/Entwicklersite mit
mindestens einer Immobilie. Seine Testdokumente werden zurückgerollt. Die
Freigabe-/Dateitests isolieren die ERP-Ermittlung; ein separater Testlauf mit
realer Belegung prüft das Laden und Speichern der Nutzerliste.

## Messdienst-Rücklauf in Heizkostenentwürfe übernehmen

1. In **Heizkostenabrechnung Immobilie** die Immobilie und den Abrechnungszeitraum
   speichern. Unter **Aktionen → Rücklauf importieren** die neunstellige
   Messdienst-Liegenschaftsnummer und die Bruttosumme für Heizung und Warmwasser
   einschließlich Leerstand aus der separaten Abrechnungsübersicht eintragen.
   Die Fundstelle angeben, etwa „Gesamtabrechnung 2025, Seite 2“. Die
   Kontrollsumme direkt aus der Übersicht ablesen.
2. Die DAT-Datei auswählen. Der Upload hängt sie privat an die Abrechnung.
   Die Vorschau zeigt für jeden Satz Kennung, Messdienstwohnung, Nutzungszeit
   und Bruttokosten. Ist der Ordnungsbegriff des Auftraggebers exakt die
   ERP-ID eines Mietvertrags und passt das Nutzungsende, erscheint dieser
   Vertrag automatisch und ist in der Vorschau fest zugeordnet. Andere
   Kennungen anhand der Messdienstunterlagen
   ausdrücklich über **Zuordnen** mit dem Mietvertrag verbinden. Für Leerstand
   **Leerstand** und die zugehörige Wohnung auswählen. Der ERP-Belegungsstand
   muss zum Nutzungsende passen. Der Beginn ergibt sich aus dem für die
   Abrechnung geschnittenen Vertragszeitraum beziehungsweise der Belegungslücke.
3. Die Zuordnungen, Beträge und Prüfsumme vergleichen und **Freigeben und in
   Entwürfe übernehmen** wählen. Der Import nutzt vorhandene Mieterentwürfe
   oder erstellt sie mit den ERP-Vorauszahlungen. Er übernimmt die Bruttokosten
   ohne Abzug von Vorauszahlungen. Leerstand wird separat im Rücklaufprotokoll
   aufgeführt. Rechnungen entstehen erst beim späteren Einreichen der
   Heizkostenabrechnung. Bereits eingereichte Abrechnungen und Mieterzeilen
   blockieren die Übernahme. Beim Einreichen werden die bestätigten
   Miet- und Leerstandszeiten erneut gegen den aktuellen Belegungsstand
   geprüft.

Unter **Messdienst-Rücklauf** stehen die freigegebenen Zeilen und ihre
Entwurfsbezüge, der Dateibezug mit SHA-256, die Kontrollsumme mit Fundstelle
sowie Freigabezeit und Benutzer. Die verwendete private D-Datei ist dort
verlinkt und gegen Entfernen und Veröffentlichung geschützt. Pro Entwurf gibt
es eine Freigabe. Nachträgliche
fachliche Berichtigungen erfolgen über die vorhandenen Abrechnungsabläufe.

### Unterstütztes Dateiprofil

[Bved-Standard-Datenaustausch 3.10, dritte Erweiterung, Kapitel 2 und 8 sowie Tabelle K](https://bved.info/wp-content/uploads/2025/12/2025-09-10_bved_datenaustausch_310_dritte-Erweiterung.pdf)

- D-Satz `D03.10`, 1.024 Zeichen je Satz einschließlich abschließendem `D`,
  ISO-8859-15, CRLF gemäß Spezifikation oder LF. Eine Liegenschaft und ein
  Messdienstkonto je Datei. Dateigröße bis 5 MiB.
- Ein Satz je Nutzerzeitraum oder Leerstandszeitraum. Feld 5 enthält die neun
  Stellen der Messdienst-Liegenschaft und vier Stellen der Messdienstwohnung.
  Feld 6 enthält den Ordnungsbegriff des Auftraggebers, Feld 7 das Nutzungsende
  im Format TTMMJJ. Die Messdienstwohnung dient der Konsistenzprüfung der
  Zuordnungen.
- Kostenschlüssel **231** (Heizung und Warmwasser) in Feld 17, Währung **EUR**
  in Feld 22. Übernommen wird ausschließlich **Feld 8**, Stellen 58–67,
  Bruttokosten in impliziten Cent. Netto in Feld 9, die Vorauszahlungen in
  Feldern 10–13, Umlageausfallwagnis in Feld 14, Saldo in Feldern 15–16 und
  die CO₂-Teilbeträge in Feldern 23–28 fließen nicht separat ein.
- Gesamtkosten über mehrere Kostenarten (Schlüssel 230), Dateien mit
  Einzelkostenarten und E898 für Einzel-PDFs liegen außerhalb dieses Profils.
  Die Kompatibilität mit dem tatsächlichen Anbieter muss anhand eines
  Originalrücklaufs und der zugehörigen Abrechnungsübersicht geprüft werden.

### Synthetisches Beispiel

Die [Beispieldatei](beispiele/DTD310_20261004090000000.DAT) verwendet
Liegenschaft `123456789` und den Abrechnungszeitraum 01.01.–31.12.2025.
Für den Test in einer synthetischen Immobilie zwei Verträge mit jeweils eigenem
Customer in derselben Wohnung anlegen. Die Nutzungskennungen bei Bedarf
manuell den Vertrags-IDs zuordnen.

| Kennung | Nutzung | Bruttokosten |
| --- | --- | ---: |
| TEST-MV-ALT | 01.01.–30.04.2025 | 321,01 EUR |
| TEST-LEERSTAND | 01.05.–31.05.2025 | 75,07 EUR |
| TEST-MV-NEU | 01.06.–31.12.2025 | 428,13 EUR |

Kontrollwert der synthetischen Abrechnungsübersicht: **824,21 EUR** für
Heizung und Warmwasser. Die beiden Mieterentwürfe enthalten zusammen
749,14 EUR. Die 75,07 EUR Leerstand stehen im Importprotokoll.
