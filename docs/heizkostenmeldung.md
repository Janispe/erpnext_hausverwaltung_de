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
3. Nutzernummern, Heizflächen und Meldevorauszahlungen ergänzen bzw. bestätigen.
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
- `hausverwaltung.hausverwaltung.doctype.heizkostenmeldung.test_heizkostenmeldung`

Der DocType-Test benötigt eine initialisierte Frappe-Test-/Entwicklersite mit
mindestens einer Immobilie. Seine Testdokumente werden zurückgerollt. Die
Freigabe-/Dateitests isolieren die ERP-Ermittlung; ein separater Testlauf mit
realer Belegung prüft das Laden und Speichern der Nutzerliste.
