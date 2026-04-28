"""Rename Abschlagszahlung → Zahlungsplan und Abschlagszahlung Plan → Zahlungsplan Zeile.

Wird in [pre_model_sync] eingehängt: muss VOR dem Sync der DocType-JSONs laufen,
sonst legt Frappe schon eine leere ``tabZahlungsplan`` an und ``rename_doc`` schlägt
fehl, weil das Ziel existiert.

Idempotent: rename wird übersprungen wenn das Quell-DocType nicht (mehr) existiert.
Setzen des Default-``modus`` für migrierte Records passiert in einem separaten
Post-Sync-Patch (``set_default_modus_for_zahlungsplan``), weil die Spalte zum
Zeitpunkt dieses Patches noch nicht existiert.
"""
from __future__ import annotations

import frappe


_RENAMES: tuple[tuple[str, str], ...] = (
	("Abschlagszahlung Plan", "Zahlungsplan Zeile"),
	("Abschlagszahlung", "Zahlungsplan"),
)


def execute() -> None:
	for old_name, new_name in _RENAMES:
		if not frappe.db.exists("DocType", old_name):
			continue
		if frappe.db.exists("DocType", new_name):
			# Bereits umbenannt — nichts zu tun
			continue
		try:
			frappe.rename_doc(
				"DocType",
				old_name,
				new_name,
				force=True,
				show_alert=False,
			)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Patch rename {old_name} -> {new_name} fehlgeschlagen",
			)
			raise

	frappe.db.commit()
