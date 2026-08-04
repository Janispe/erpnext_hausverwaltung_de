"""Add readable remarks to existing HK settlement invoices and credit notes."""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.scripts.heizkosten.settlement import (
	_build_hk_settlement_remark,
	_hk_settlement_marker,
)

HK_SETTLEMENT_ITEMS = ("HK Nachzahlung", "HK Guthaben")


def execute():
	linked_periods = _get_linked_invoice_periods()
	item_invoice_names = frappe.get_all(
		"Sales Invoice Item",
		filters={"item_code": ("in", HK_SETTLEMENT_ITEMS)},
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
		current_remark = str(invoice.get("remarks") or "").strip()
		period = linked_periods.get(invoice.name)
		if period:
			owner = period["name"]
			legacy_marker = _hk_settlement_marker(owner)
			# Preserve any genuinely user-authored or otherwise unexpected remark.
			if current_remark and current_remark != legacy_marker:
				continue
			remark = _build_hk_settlement_remark(
				period.get("von"),
				period.get("bis"),
				abrechnung=owner,
			)
		else:
			if current_remark:
				continue
			reference_date = (
				invoice.get("custom_wertstellungsdatum") or invoice.get("posting_date")
			)
			remark = _build_hk_settlement_remark(None, reference_date)

		frappe.db.set_value(
			"Sales Invoice",
			invoice.name,
			"remarks",
			remark,
			update_modified=False,
		)
		updated += 1

	frappe.log(
		f"[backfill_hk_settlement_invoice_remarks] updated {updated} Sales Invoice remarks"
	)


def _get_linked_invoice_periods() -> dict[str, dict]:
	periods: dict[str, dict] = {}
	for row in frappe.get_all(
		"Heizkostenabrechnung Mieter",
		fields=["name", "sales_invoice", "credit_note", "von", "bis"],
		limit_page_length=0,
	):
		period = {"name": row.name, "von": row.get("von"), "bis": row.get("bis")}
		for fieldname in ("sales_invoice", "credit_note"):
			invoice_name = str(row.get(fieldname) or "").strip()
			if invoice_name:
				periods[invoice_name] = period
	return periods
