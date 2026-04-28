import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Party Type"):
		return

	party_type_name = "Eigentuemer"
	account_type = "Payable"

	if frappe.db.exists("Party Type", party_type_name):
		doc = frappe.get_doc("Party Type", party_type_name)
		if doc.account_type != account_type:
			doc.account_type = account_type
			doc.save(ignore_permissions=True)
		return

	doc = frappe.get_doc(
		{
			"doctype": "Party Type",
			"party_type": party_type_name,
			"account_type": account_type,
		}
	)
	doc.insert(ignore_permissions=True)
