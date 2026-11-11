# Altdaten für die Buchungsprüfungen vorbereiten

Die beiden manuellen Reparaturen ergänzen fehlende Kopfkostenstellen bzw.
berichtigen Rechnungsreferenzen nach einer ausdrücklich bestätigten
Vertragsumbenennung. Sie sind nicht in `patches.txt` eingetragen und laufen
standardmäßig als reiner Trockenlauf. Die Aufrufe benötigen einen System Manager.

Alte Payment-/Journal-Referenzen dürfen leere Wohnungs- und Kostenstellenfelder
behalten, wenn Customer, Firma und die eindeutige Mietvertragszuordnung passen.
Nichtleere Widersprüche werden weiter abgelehnt. Beim nachträglichen Abgleich
werden diese Felder weder ergänzt noch verändert; neue Buchungen erhalten
weiterhin die maßgeblichen Vertragsdimensionen. Die Rechnungsprüfungen bleiben
streng, weshalb die beiden folgenden Metadatenreparaturen getrennt vorliegen.

`SITE`, `BELEG-ID`, `ALTER-VERTRAGSNAME` und `NEUER-VERTRAGSNAME` in den Beispielen
durch die zuvor geprüften, exakten IDs ersetzen. Die Namen werden weder aus
Personennamen noch aus einem ähnlichen Vertragsnamen abgeleitet.

## Fehlende Kopfkostenstelle

```bash
bench --site SITE execute \
  hausverwaltung.hausverwaltung.patches.post_model_sync.repair_legacy_sales_invoice_cost_center.execute \
  --kwargs '{"invoice_names": ["BELEG-ID"], "dry_run": True}'
```

Ohne `invoice_names` prüft der Trockenlauf alle eingereichten Ausgangsrechnungen
mit leerer Kopfkostenstelle. Eine Ergänzung wird nur geplant, wenn sämtliche
Positionen dieselbe Kostenstelle tragen und diese zur eindeutigen
Customer-/Mietvertrag-/Immobilien-/Firmenzuordnung gehört. Vorhandene
Widersprüche führen zu einem Eintrag unter `skipped`.

Der Patch ändert ausschließlich das leere Feld `Sales Invoice.cost_center`.
Er verändert keine Positionen, Beträge, Konten, Buchungsdaten oder GL-Zeilen.
Er ist keine Migration historischer GL-Dimensionen.

## Marker nach einer Vertragsumbenennung

```bash
bench --site SITE execute \
  hausverwaltung.hausverwaltung.patches.post_model_sync.repair_renamed_mietvertrag_invoice_markers.execute \
  --kwargs '{"renames": {"ALTER-VERTRAGSNAME": "NEUER-VERTRAGSNAME"}, "invoice_names": ["BELEG-ID"], "dry_run": True}'
```

Ohne `invoice_names` werden die eingereichten Rechnungen des eindeutig
zugeordneten Customers geprüft. Der alte Vertrag darf nicht mehr existieren;
der neue Vertrag muss die eindeutige Buchungsidentität des Customers sein.
Die Zuordnung der Rechnung zu Customer, Wohnung und Firma muss passen.
Fremde oder beschädigte Referenzen werden mit Begründung ausgelassen.

Geändert werden ausschließlich vollständige `[MV:ALTER-VERTRAGSNAME]`-Marker
in `remarks` und der Vertragsanteil einer gültigen `mietabrechnung_id`.
Der Abrechnungsmonat und der übrige Freitext bleiben erhalten. Der Patch
aktiviert keine Fallback-Auflösung im normalen Buchungs- oder Korrekturpfad.

## Geprüfte Auswahl anwenden

Beide Routinen liefern `planned`, `applied` und `skipped` mit den betroffenen
IDs und Gründen bzw. Vorher-/Nachherwerten. Den Trockenlauf prüfen und
aufbewahren. Für eine bestätigte Auswahl denselben Aufruf mit der expliziten
Belegliste und `"dry_run": False` verwenden. `bench execute --kwargs` erwartet
hier Python-Werte, also `True`/`False` statt JSON-`true`/`false`.
Bei Rechnungen, die beide
Reparaturen benötigen, kann zunächst die Markerreparatur erforderlich sein,
weil ein veralteter Marker die Kostenstellenprüfung blockiert.

Die Anwendung liest unter Buchungssperren erneut und überschreibt keine
inzwischen gesetzten oder widersprüchlichen Werte. Wiederholte Anwendung
derselben Reparatur erzeugt keine weiteren Änderungen. Die Routinen führen
keinen eigenen Commit aus; `bench execute` bestätigt die Transaktion nach
erfolgreichem Abschluss. In einer Python-/Rollback-Prüfung steuert der Aufrufer
die Transaktion. Das Änderungsprotokoll wird als Rückgabewert geliefert und
sollte zusammen mit dem Trockenlauf archiviert werden.

## Regressionstests

Die Tests liegen im Repository neben den beiden Reparaturen. Die echten
Datenbankfälle benötigen eine ausdrücklich als Wegwerf-Testsite konfigurierte
`fac.localhost` mit `allow_tests`, `hv_isolated_integration_test` und einer
eingerichteten ERPNext-Testfirma. Sie erstellen synthetische Altbelege und
rollen die Änderungen wieder zurück. Dafür keine produktive Site verwenden.

```bash
bench --site fac.localhost run-tests --module hausverwaltung.hausverwaltung.patches.post_model_sync.test_repair_legacy_sales_invoice_cost_center
bench --site fac.localhost run-tests --module hausverwaltung.hausverwaltung.patches.post_model_sync.test_repair_legacy_sales_invoice_cost_center_integration
bench --site fac.localhost run-tests --module hausverwaltung.hausverwaltung.patches.post_model_sync.test_repair_renamed_mietvertrag_invoice_markers
bench --site fac.localhost run-tests --module hausverwaltung.hausverwaltung.overrides.test_payment_entry_integration
```

Die Datenbanktests vergleichen die GL-Datensätze vor und nach der Reparatur
bzw. dem Zahlungsabgleich. Sie prüfen auch, dass die betroffenen Rechnungen
nach der Metadatenreparatur wieder die normalen Identitätsprüfungen bestehen.
