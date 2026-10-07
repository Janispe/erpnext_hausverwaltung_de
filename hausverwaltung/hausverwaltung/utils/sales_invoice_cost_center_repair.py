"""Kostenstelle gebuchter Sales Invoices auf die Property-Kostenstelle korrigieren.

Hintergrund: Von Hand angelegte Rechnungen (Mahngebühren, Anwaltskosten,
Kleinreparaturen …) wurden vor den strengeren Buchungsprüfungen teils ohne
Kopf-Kostenstelle oder mit der Company-Standardkostenstelle gebucht. Seit
``validate_mietvertrag_sales_invoice_identity`` jede Rechnung beim Bankimport
gegen die Kostenstelle der Immobilie prüft, blockiert jede solche Rechnung die
komplette Zahlungszuordnung.

``cost_center`` ist auf Sales Invoice und Sales Invoice Item ``allow_on_submit``.
ERPNext erzeugt nach der Änderung die GL Entries über ein Repost Accounting
Ledger neu - keine Stornierung, keine Gutschrift. Ab ERPNext v16 läuft der
Repost immer als Background-Job (Queue ``long``) nach dem Commit. Ein durch
Period Closing Voucher geschlossenes Jahr lehnt ERPNext schon beim Anlegen ab
(die Rechnung wird hier als fehlgeschlagen gemeldet); eine gesperrte Accounting
Period fällt erst im Job auf und steht dann als ``Failed`` im Repost Accounting
Ledger.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr

REPAIR_ROLES = ("Accounts Manager", "System Manager")


def _require_repair_role() -> None:
	if not set(REPAIR_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Nur Accounts Manager oder System Manager dürfen Kostenstellen korrigieren."),
			frappe.PermissionError,
		)


def _normalize_names(invoice_names: str | list[str] | None) -> list[str] | None:
	if invoice_names in (None, ""):
		return None
	if isinstance(invoice_names, str):
		invoice_names = (
			json.loads(invoice_names) if invoice_names.strip().startswith("[") else [invoice_names]
		)
	return sorted({cstr(name).strip() for name in invoice_names if cstr(name).strip()})


def get_cost_center_mismatches(invoice_names: list[str] | None = None) -> list[dict[str, Any]]:
	"""Gebuchte Rechnungen mit Wohnung, deren Kopf- oder Positions-Kostenstelle abweicht."""
	conditions = ""
	values: dict[str, Any] = {}
	if invoice_names is not None:
		if not invoice_names:
			return []
		conditions = "AND si.name IN %(names)s"
		values["names"] = tuple(invoice_names)
	return frappe.db.sql(
		f"""
		SELECT
			si.name,
			si.customer,
			si.company,
			si.posting_date,
			si.grand_total,
			si.outstanding_amount,
			si.remarks,
			si.wohnung,
			w.immobilie,
			si.cost_center AS header_cost_center,
			(
				SELECT GROUP_CONCAT(DISTINCT IFNULL(item.cost_center, '') ORDER BY item.cost_center SEPARATOR ', ')
				FROM `tabSales Invoice Item` item
				WHERE item.parent = si.name
			) AS item_cost_centers,
			i.kostenstelle AS target_cost_center
		FROM `tabSales Invoice` si
		JOIN `tabWohnung` w ON w.name = si.wohnung
		JOIN `tabImmobilie` i ON i.name = w.immobilie
		WHERE si.docstatus = 1
			AND IFNULL(i.kostenstelle, '') != ''
			AND (
				IFNULL(si.cost_center, '') != i.kostenstelle
				OR EXISTS (
					SELECT 1 FROM `tabSales Invoice Item` item
					WHERE item.parent = si.name
						AND IFNULL(item.cost_center, '') != i.kostenstelle
				)
			)
			{conditions}
		ORDER BY si.posting_date ASC, si.name ASC
		""",
		values,
		as_dict=True,
	)


@frappe.whitelist()
def get_cost_center_repair_preview() -> dict[str, Any]:
	_require_repair_role()
	invoices = get_cost_center_mismatches()
	return {"invoices": invoices, "count": len(invoices)}


def repair_sales_invoice_cost_center(invoice_name: str) -> dict[str, Any]:
	"""Setzt Kopf- und Positions-Kostenstelle einer gebuchten Rechnung auf die Property-Kostenstelle."""
	from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
		_lock_property_booking_identity,
	)

	si = frappe.get_doc("Sales Invoice", invoice_name, for_update=True)
	if si.docstatus != 1:
		frappe.throw(_("{0} ist nicht gebucht.").format(invoice_name))
	wohnung = cstr(si.get("wohnung")).strip()
	if not wohnung:
		frappe.throw(_("{0} hat keine Wohnung am Belegkopf.").format(invoice_name))
	foreign_wohnungen = sorted(
		{
			cstr(item.get("wohnung")).strip()
			for item in si.items
			if cstr(item.get("wohnung")).strip() not in ("", wohnung)
		}
	)
	if foreign_wohnungen:
		frappe.throw(
			_("{0}: Positionen gehören zu anderen Wohnungen ({1}); bitte manuell prüfen.").format(
				invoice_name, ", ".join(foreign_wohnungen)
			)
		)

	identity = _lock_property_booking_identity(wohnung)
	if identity.company != si.company:
		frappe.throw(
			_("{0}: Company {1} passt nicht zur Immobilie {2} ({3}).").format(
				invoice_name, si.company, identity.immobilie, identity.company
			)
		)

	target = identity.cost_center
	old_header = cstr(si.get("cost_center")).strip()
	old_items = sorted({cstr(item.get("cost_center")).strip() for item in si.items})
	header_changed = old_header != target
	items_changed = False
	si.cost_center = target
	for item in si.items:
		if cstr(item.get("cost_center")).strip() != target:
			item.cost_center = target
			items_changed = True
	if not header_changed and not items_changed:
		return {"name": invoice_name, "changed": False}

	si.save()
	# ERPNext repostet nur bei Änderungen am Kopf bzw. an Konten der Positionen;
	# reine Positions-Kostenstellen-Änderungen müssen explizit repostet werden.
	if not si.get("needs_repost"):
		si.validate_for_repost()
		si.repost_accounting_entries()

	si.add_comment(
		"Info",
		_(
			"Kostenstelle auf {0} korrigiert (vorher Kopf: {1}, Positionen: {2}); "
			"Buchungssätze wurden neu erzeugt."
		).format(target, old_header or "leer", ", ".join(c or "leer" for c in old_items)),
	)
	return {"name": invoice_name, "changed": True, "cost_center": target}


@frappe.whitelist()
def repair_sales_invoice_cost_centers(invoice_names: str | list[str] | None = None) -> dict[str, Any]:
	"""Repariert alle (oder die angegebenen) abweichenden Rechnungen einzeln.

	Jede Rechnung läuft in einem eigenen Savepoint: eine Rechnung in einem
	gesperrten Zeitraum blockiert die übrigen nicht.
	"""
	_require_repair_role()
	names = _normalize_names(invoice_names)
	candidates = [row.name for row in get_cost_center_mismatches(names)]

	repaired: list[dict[str, Any]] = []
	failed: list[dict[str, str]] = []
	for name in candidates:
		savepoint = "hv_cost_center_repair"
		frappe.db.savepoint(savepoint)
		try:
			result = repair_sales_invoice_cost_center(name)
			if result.get("changed"):
				repaired.append(result)
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_messages()
			failed.append({"name": name, "error": cstr(exc) or exc.__class__.__name__})

	return {
		"repaired": repaired,
		"failed": failed,
		"remaining": len(get_cost_center_mismatches(names)),
	}
