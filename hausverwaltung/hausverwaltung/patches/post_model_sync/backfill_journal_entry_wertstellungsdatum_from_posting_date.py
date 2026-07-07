import frappe


def execute():
	if not frappe.db.has_column("Journal Entry", "custom_wertstellungsdatum"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry`
		SET custom_wertstellungsdatum = posting_date
		WHERE custom_wertstellungsdatum IS NULL
		  AND posting_date IS NOT NULL
		"""
	)
