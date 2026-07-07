import frappe


def execute():
	if not frappe.db.has_column("Purchase Invoice", "custom_wertstellungsdatum"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabPurchase Invoice`
		SET custom_wertstellungsdatum = due_date
		WHERE custom_wertstellungsdatum IS NULL
		  AND due_date IS NOT NULL
		"""
	)
