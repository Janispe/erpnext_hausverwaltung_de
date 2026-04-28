import frappe


@frappe.whitelist()
def ping():
	return {"ok": True}
