import frappe


def execute():
	"""Add composite invoice indexes used by OP workflow date filters."""
	_add_index_if_missing(
		"Sales Invoice",
		["company", "docstatus", "due_date", "customer", "name"],
		"hv_si_op_due_idx",
	)
	_add_index_if_missing(
		"Purchase Invoice",
		["company", "docstatus", "due_date", "supplier", "name"],
		"hv_pi_op_due_idx",
	)
	_add_index_if_missing(
		"Payment Ledger Entry",
		["company", "account", "delinked", "posting_date", "party"],
		"hv_ple_op_report_idx",
	)


def _add_index_if_missing(doctype: str, fields: list[str], index_name: str) -> None:
	table = f"tab{doctype}"
	if frappe.db.has_index(table, index_name):
		return
	frappe.db.add_index(doctype, fields, index_name)
