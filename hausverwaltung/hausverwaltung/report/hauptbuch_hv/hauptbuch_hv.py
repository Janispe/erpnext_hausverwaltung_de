from __future__ import annotations

import json

import frappe
from frappe import _

from erpnext.accounts.report.general_ledger import general_ledger


HIDDEN_COLUMNS = {
	"voucher_subtype",
	"party_type",
	"against_voucher_type",
	"bill_no",
	"project",
}


def execute(filters=None):
	filters = _with_hv_defaults(filters)
	hide_account = _has_single_selected_account(filters)
	columns, data = general_ledger.execute(filters)
	return _filter_columns(columns, hide_account=hide_account), data


def _with_hv_defaults(filters=None):
	filters = frappe._dict(filters or {})

	filters["show_remarks"] = 1
	filters["include_dimensions"] = 1
	filters["include_default_book_entries"] = 1

	if not filters.get("categorize_by"):
		filters["categorize_by"] = "Categorize by Voucher (Consolidated)"

	if filters.get("party") and not filters.get("party_type"):
		filters["party_type"] = "Customer"

	return filters


def _filter_columns(columns, *, hide_account: bool = False):
	filtered = []
	for column in columns or []:
		if column.get("fieldname") in HIDDEN_COLUMNS:
			continue
		if hide_account and column.get("fieldname") == "account":
			continue
		if column.get("fieldname") == "remarks":
			column = dict(column)
			column["label"] = _("Anmerkungen")
			column["width"] = max(int(column.get("width") or 0), 400)
		filtered.append(column)
	return filtered


def _has_single_selected_account(filters) -> bool:
	account = filters.get("account")
	if not account:
		return False
	if isinstance(account, str):
		try:
			account = json.loads(account)
		except Exception:
			account = [part.strip() for part in account.split(",") if part.strip()]
	return isinstance(account, list) and len(account) == 1
