import frappe


def execute():
	if not frappe.db.has_column("Sales Invoice", "hv_sollstellung_titel"):
		return

	from hausverwaltung.hausverwaltung.utils.sollstellung_titel import build_sollstellung_titel

	for row in frappe.get_all(
		"Sales Invoice",
		filters={"hv_sollstellung_titel": ("in", ["", None])},
		fields=["name"],
		limit_page_length=0,
	):
		doc = frappe.get_doc("Sales Invoice", row.name)
		title = build_sollstellung_titel(doc)
		if title:
			frappe.db.set_value(
				"Sales Invoice",
				doc.name,
				"hv_sollstellung_titel",
				title,
				update_modified=False,
			)
