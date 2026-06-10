"""Remove legacy Buchungs-Cockpit prefix from Purchase Invoice remarks."""

from __future__ import annotations

MARKER = "Erfasst über Buchungs-Cockpit"


def execute():
	import frappe

	rows = frappe.get_all(
		"Purchase Invoice",
		filters={"remarks": ("like", f"{MARKER}%")},
		fields=["name", "remarks"],
		limit_page_length=0,
	)

	updated = 0
	for row in rows:
		old = row.get("remarks") or ""
		new = clean_legacy_remark(old)
		if new != old:
			frappe.db.set_value("Purchase Invoice", row.name, "remarks", new, update_modified=False)
			updated += 1

	if updated:
		frappe.db.commit()
	frappe.log(f"[clean_legacy_purchase_invoice_remarks] updated {updated} Purchase Invoice remarks")


def clean_legacy_remark(remark: str | None) -> str:
	value = str(remark or "").strip()
	if not value.startswith(MARKER):
		return value

	tail = value[len(MARKER):]
	return tail.strip(" \t\r\n-|:")
