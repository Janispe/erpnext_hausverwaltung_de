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
`ares-v1`. Die mitgelieferte erste ares-Version bildet die Zusatzangaben der
bereitgestellten Heizöl-, Nutzerlisten- und CO₂-Formulare ab. Sie enthält keine
personenbezogenen Beispieldaten und keine vorgegebenen rechtlichen Antworten.

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

Die sechs DocTypes werden beim normalen `bench migrate` synchronisiert. Der
Patch `seed_heizkostenmeldung_vorlage` legt `ares-v1` idempotent an; derselbe
Seed ist auch für Neuinstallationen registriert. Die Navigation wird über
den vorhandenen Workspace-/Sidebar-Aufbau ergänzt.

Tests:

- `hausverwaltung.hausverwaltung.scripts.heizkosten.test_meldung`
- `hausverwaltung.hausverwaltung.doctype.heizkostenmeldung.test_heizkostenmeldung`

Der zweite Test benötigt eine initialisierte Frappe-Test-/Entwicklersite mit
mindestens einer Immobilie. Seine Testdokumente werden zurückgerollt. Die
Freigabe-/Dateitests isolieren die ERP-Ermittlung; ein separater Testlauf mit
realer Belegung prüft das Laden und Speichern der Nutzerliste.
