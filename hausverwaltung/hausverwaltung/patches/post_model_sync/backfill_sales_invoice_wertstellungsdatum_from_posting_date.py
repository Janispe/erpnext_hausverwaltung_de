import frappe


def execute():
	if not frappe.db.has_column("Sales Invoice", "custom_wertstellungsdatum"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabSales Invoice`
		SET custom_wertstellungsdatum = posting_date
		WHERE custom_wertstellungsdatum IS NULL
		  AND posting_date IS NOT NULL
		"""
	)
