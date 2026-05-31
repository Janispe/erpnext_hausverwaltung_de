import frappe


def execute():
	"""Add composite indexes used by the Mieterkonto workflow report."""
	_add_index_if_missing(
		"Sales Invoice",
		["company", "customer", "docstatus", "posting_date", "name"],
		"hv_si_mk_customer_posting_idx",
	)
	_add_index_if_missing(
		"Payment Ledger Entry",
		[
			"company",
			"party_type",
			"party",
			"against_voucher_type",
			"against_voucher_no",
			"posting_date",
			"delinked",
		],
		"hv_ple_mk_settlement_idx",
	)
	_add_index_if_missing(
		"GL Entry",
		["party_type", "party", "account", "posting_date", "is_cancelled"],
		"hv_gl_mk_party_account_idx",
	)


def _add_index_if_missing(doctype: str, fields: list[str], index_name: str) -> None:
	table = f"tab{doctype}"
	if frappe.db.has_index(table, index_name):
		return
	frappe.db.add_index(doctype, fields, index_name)
