import frappe


def execute():
	if not frappe.db.exists("Page", "buchen_cockpit"):
		return

	page = frappe.get_doc("Page", "buchen_cockpit")
	current_roles = {
		row.role
		for row in page.get("roles") or []
		if row.role
	}
	target_roles = {"Hausverwalter (Buchung)"}
	if current_roles == target_roles:
		return

	page.set("roles", [])
	page.append("roles", {"role": "Hausverwalter (Buchung)"})
	page.save(ignore_permissions=True)
