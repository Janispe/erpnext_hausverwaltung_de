"""Bemerkungen alter BK-Nachzahlungsrechnungen und -gutschriften nachtragen."""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	_build_settlement_remark,
)

BK_SETTLEMENT_ITEMS = ("BK Nachzahlung", "BK Guthaben")


def execute():
	linked_periods = _get_linked_invoice_periods()
	item_invoice_names = frappe.get_all(
		"Sales Invoice Item",
		filters={"item_code": ("in", BK_SETTLEMENT_ITEMS)},
		pluck="parent",
		limit_page_length=0,
	)
	invoice_names = sorted(set(linked_periods) | set(item_invoice_names or []))
	if not invoice_names:
		return

	fields = ["name", "remarks", "posting_date"]
	if frappe.db.has_column("Sales Invoice", "custom_wertstellungsdatum"):
		fields.append("custom_wertstellungsdatum")

	updated = 0
	for invoice in frappe.get_all(
		"Sales Invoice",
		filters={"name": ("in", invoice_names)},
		fields=fields,
		limit_page_length=0,
	):
		if str(invoice.get("remarks") or "").strip():
			continue

		period = linked_periods.get(invoice.name)
		if period:
			remark = _build_settlement_remark(period.get("von"), period.get("bis"))
		else:
			# Bei alten, nicht mehr verknuepften Belegen ist nur das Leistungs-/
			# Wertstellungsdatum verfuegbar. Das Jahr ist hier die sicherste Aussage.
			reference_date = invoice.get("custom_wertstellungsdatum") or invoice.get("posting_date")
			remark = _build_settlement_remark(None, reference_date)

		frappe.db.set_value("Sales Invoice", invoice.name, "remarks", remark, update_modified=False)
		updated += 1

	frappe.log(f"[backfill_bk_settlement_invoice_remarks] updated {updated} Sales Invoice remarks")


def _get_linked_invoice_periods() -> dict[str, dict]:
	periods: dict[str, dict] = {}
	for row in frappe.get_all(
		"Betriebskostenabrechnung Mieter",
		fields=["sales_invoice", "credit_note", "von", "bis"],
		limit_page_length=0,
	):
		period = {"von": row.get("von"), "bis": row.get("bis")}
		for fieldname in ("sales_invoice", "credit_note"):
			invoice_name = str(row.get(fieldname) or "").strip()
			if invoice_name:
				periods[invoice_name] = period
	return periods
