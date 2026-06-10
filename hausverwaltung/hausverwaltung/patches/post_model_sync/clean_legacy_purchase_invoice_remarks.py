"""Remove legacy Buchungs-Cockpit prefix from Purchase Invoice remarks."""

from __future__ import annotations

MARKER = "Erfasst über Buchungs-Cockpit"


def execute():
	import frappe

	invoice_rows = frappe.get_all(
		"Purchase Invoice",
		filters={"remarks": ("like", f"{MARKER}%")},
		fields=["name", "remarks"],
		limit_page_length=0,
	)
	gl_rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Purchase Invoice", "remarks": ("like", f"{MARKER}%")},
		fields=["name", "remarks"],
		limit_page_length=0,
	)

	updated_invoices = 0
	for row in invoice_rows:
		old = row.get("remarks") or ""
		new = clean_legacy_remark(old)
		if new != old:
			frappe.db.set_value("Purchase Invoice", row.name, "remarks", new, update_modified=False)
			updated_invoices += 1

	updated_gl_entries = 0
	for row in gl_rows:
		old = row.get("remarks") or ""
		new = clean_legacy_remark(old)
		if new != old:
			frappe.db.set_value("GL Entry", row.name, "remarks", new, update_modified=False)
			updated_gl_entries += 1

	if updated_invoices or updated_gl_entries:
		frappe.db.commit()
	frappe.log(
		f"[clean_legacy_purchase_invoice_remarks] updated {updated_invoices} Purchase Invoice "
		f"and {updated_gl_entries} GL Entry remarks"
	)


def clean_legacy_remark(remark: str | None) -> str:
	value = str(remark or "").strip()
	if not value.startswith(MARKER):
		return value

	tail = value[len(MARKER):]
	return tail.strip(" \t\r\n-|:")
