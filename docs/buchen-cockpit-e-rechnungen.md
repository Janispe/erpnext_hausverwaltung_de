# E-Rechnungen im Buchen-Cockpit

## Einrichtung auf ERPNext v16

Installiere [ALYF eu_einvoice](https://github.com/alyf-de/eu_einvoice/tree/version-16) im selben Bench und auf derselben Site wie Hausverwaltung. Prüfe vor der Installation die Frappe-, ERPNext- und Python-Vorgaben der gewählten ALYF-Version in ihrer `pyproject.toml`.

```sh
bench get-app --branch version-16 https://github.com/alyf-de/eu_einvoice.git
bench --site <site> install-app eu_einvoice
bench --site <site> migrate
```

Bei einer Containerinstallation muss das Bench-Image die App und ihre Python-Abhängigkeiten enthalten. Das Cockpit nutzt ALYFs Profilerkennung und Schematron-Validierung. Auf einer Site ohne ALYF stehen der manuelle Eingang und die PDF-Analyse weiter zur Verfügung.

Für den Import braucht der Benutzer Zugriff auf den privaten Originalbeleg, die Berechtigung zum Anlegen einer Eingangsrechnung und Leserechte auf die ausgewählten Stammdaten. Die Firma benötigt einen EUR-Kontenrahmen mit aktiven Vorsteuerkonten vom Typ `Tax` und geeigneten Objekt-Kostenstellen und Kostenarten.

## Bedienung

1. Öffne den Datei-Upload im Buchen-Cockpit und lade eine CII-XML oder ein ZUGFeRD-/Factur-X-PDF hoch.
2. Öffne den Beleg über **E-Rechnung prüfen**. Vergleiche Rechnungsnummer, Datum, Lieferant und Empfänger, Originalpositionen und Steuersummen mit dem Originalbeleg. Bestätige den ERPNext-Lieferanten und die Firma.
3. Wähle je Position die Objekt-Kostenstelle, die Umlagefähigkeit und die Kostenart. Gib bei Einzelverteilung eine Wohnung an. Ordne jeden ausgewiesenen Steuerbetrag dem passenden Vorsteuerkonto zu.
4. Wähle **Eingangsrechnung als Entwurf speichern**. Der Entwurf wird mit dem privaten Original geöffnet. Originalmengen und Einheiten stehen in der Positionsbeschreibung. Die Buchungsposition übernimmt den geprüften CII-Nettozeilenbetrag. Gutschriften werden als Retouren mit negativen Beträgen gespeichert.
5. Für gewöhnliche PDFs wähle **PDF-Analyse starten**. Rechnerisch fehlerhafte Belege, unbekannte Profile und UBL-XRechnungen zeigen einen Fehler mit einem Hinweis auf **Eingangsrechnung** zur manuellen Erfassung und Ablage des Originals.

Der automatisierte Entwurf ist auf EUR-Belege ohne Kopfzu- und -abschläge, Vorauszahlungen oder eigenen Rundungsbetrag ausgelegt. Steuerfälle mit zusätzlichem Buchungsbedarf, etwa Reverse Charge, gehen ebenfalls in die manuelle Erfassung.

## Isolierter Test

Mit installiertem ALYF auf einer Wegwerf-Site mit synthetischen ERPNext-Stammdaten:

```sh
bench --site <testsite> set-config --parse allow_tests 1
bench --site <testsite> set-config --parse hv_isolated_integration_test 1
bench --site <testsite> run-tests --module hausverwaltung.hausverwaltung.page.buchen_cockpit.test_structured_invoice_integration
```
