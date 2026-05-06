"""Re-extrahiert Saldo + Stichtag aus den CSVs aller Bankauszug-Imports.

Vor Commit ``1d0d703`` las der CSV-Parser fälschlicherweise den
Preamble-Eintrag ``Letzter Kontostand`` (= Eröffnungssaldo der Periode)
in ``saldo_laut_csv``. Korrekt ist die Footer-Zeile ``Kontostand;<datum>;
;;<betrag>;EUR`` (= Schluss-Saldo).

Dieser Patch liest aus jeder verlinkten CSV den Schluss-Saldo neu und
aktualisiert ``saldo_laut_csv``, ``saldo_datum`` sowie ``saldo_laut_erp`` /
``saldo_differenz`` — ohne die Plan-Zeilen anzufassen.

Idempotent: läuft pro Import einmal sauber durch. Wenn keine CSV verlinkt
ist oder die Datei nicht mehr lesbar (gelöscht?), wird der Datensatz
übersprungen.
"""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
	_persist_saldo_fields,
	_refresh_saldo_fields,
	reextract_saldo_from_csv,
)


def execute() -> None:
	names = frappe.get_all("Bankauszug Import", pluck="name")
	if not names:
		return

	updated = 0
	skipped = 0
	errors = 0
	for name in names:
		try:
			doc = frappe.get_doc("Bankauszug Import", name)
			result = reextract_saldo_from_csv(doc)
			if not result.get("applied"):
				skipped += 1
				continue
			_refresh_saldo_fields(doc)
			_persist_saldo_fields(doc)
			updated += 1
		except Exception as exc:
			errors += 1
			print(f"❌  Bankauszug {name}: {exc}")
			frappe.log_error(
				frappe.get_traceback(),
				f"Patch refresh_bankauszug_saldo_from_csv: {name}",
			)

	frappe.db.commit()
	print(
		f"✅  Bankauszug-Saldo refresh: {updated} aktualisiert, "
		f"{skipped} übersprungen, {errors} Fehler"
	)
