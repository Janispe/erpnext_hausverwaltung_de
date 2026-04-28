import frappe


def execute():
	immobilien = frappe.get_all(
		"Immobilie",
		fields=["name", "adresse", "adresse_titel"],
		limit_page_length=0,
	)

	for immobilie in immobilien:
		if not immobilie.adresse:
			continue
		if immobilie.adresse_titel:
			continue

		address_title = frappe.db.get_value("Address", immobilie.adresse, "address_title")
		if not address_title:
			continue

		frappe.db.set_value(
			"Immobilie",
			immobilie.name,
			"adresse_titel",
			address_title,
			update_modified=False,
		)
