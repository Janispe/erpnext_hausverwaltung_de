from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

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
	if cint(filters.get("mietlauf_zusammenfassen")):
		data = _aggregate_mietlauf_rows(data)
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

	if "mietlauf_zusammenfassen" not in filters:
		filters["mietlauf_zusammenfassen"] = 1

	return filters


def _aggregate_mietlauf_rows(data):
	"""Fasst SI-GL-Zeilen einer Mietabrechnung pro Konto zu einer Zeile.

	Hintergrund: Pro Mietvertrag und Monat erzeugt der Mietlauf 4 separate
	Sales Invoices (Miete/BK/HK/UMZ). Im Hauptbuch HV erscheinen daher pro
	Monat 4 Forderungs-Buchungen gegen den Debitor. Diese werden — bei
	gleicher `mietabrechnung_id` und gleichem Konto — zu einer Zeile summiert.
	Die Erlös-Seiten (verschiedene Konten) bleiben automatisch getrennt.

	Eingabe-Rows haben Felder wie `voucher_type`, `voucher_no`,
	`posting_date`, `account`, `party`, `debit`, `credit`, `against`,
	`remarks`. Section-Header- und Opening/Closing-Rows haben kein
	`voucher_type` und werden unverändert durchgereicht.
	"""
	if not data:
		return data

	# 1. Bulk-Lookup voucher_no → mietabrechnung_id für alle SI-Rows.
	si_names = {
		row.get("voucher_no")
		for row in data
		if isinstance(row, dict)
		and row.get("voucher_type") == "Sales Invoice"
		and row.get("voucher_no")
	}
	if not si_names:
		return data

	mab_map: dict[str, str] = {}
	if frappe.db.has_column("Sales Invoice", "mietabrechnung_id"):
		for r in frappe.get_all(
			"Sales Invoice",
			filters={"name": ("in", list(si_names))},
			fields=["name", "mietabrechnung_id"],
		):
			value = (r.get("mietabrechnung_id") or "").strip()
			if value:
				mab_map[r["name"]] = value

	if not mab_map:
		return data

	# 2. Row-Walk: für jede aggregierbare SI-Row → Bucket; sonst Pass-Through.
	# Bucket-Key: (mietabrechnung_id, account, posting_date, party).
	# Mehrere SIs eines Monats gegen das gleiche Konto/Party werden summiert.
	buckets: dict[tuple, dict] = {}
	out: list = []
	bucket_position: dict[tuple, int] = {}

	for row in data:
		if not isinstance(row, dict):
			out.append(row)
			continue

		mab_id = mab_map.get(row.get("voucher_no")) if row.get("voucher_type") == "Sales Invoice" else None
		if not mab_id:
			out.append(row)
			continue

		key = (
			mab_id,
			row.get("account"),
			row.get("posting_date"),
			row.get("party"),
		)

		if key not in buckets:
			# Erstes Member an Original-Position einsetzen — Reihenfolge bleibt.
			merged = dict(row)
			merged["_member_count"] = 1
			merged["_member_against"] = {row.get("against")} if row.get("against") else set()
			merged["_member_voucher_nos"] = [row.get("voucher_no")]
			buckets[key] = merged
			bucket_position[key] = len(out)
			out.append(merged)
		else:
			merged = buckets[key]
			merged["debit"] = flt(merged.get("debit")) + flt(row.get("debit"))
			merged["credit"] = flt(merged.get("credit")) + flt(row.get("credit"))
			merged["_member_count"] += 1
			if row.get("against"):
				merged["_member_against"].add(row.get("against"))
			merged["_member_voucher_nos"].append(row.get("voucher_no"))
			# Diese Row entfällt im Output (ist im Aggregat gemerged).

	# 3. Aggregat-Rows finalisieren: Beschreibung mit "(+N weitere)" und
	# Pipe-getrennte against-Liste; Helper-Felder droppen.
	for merged in buckets.values():
		count = merged.pop("_member_count", 1)
		against_set = merged.pop("_member_against", set())
		voucher_nos = merged.pop("_member_voucher_nos", [])
		if count > 1:
			# remarks: Original beibehalten und Hinweis anhängen.
			extra = f" (+{count - 1} weitere SI: {', '.join(sorted(voucher_nos[1:]))})"
			merged["remarks"] = (merged.get("remarks") or "") + extra
			# against: alle Erlöskonten der Members anzeigen.
			if against_set:
				merged["against"] = " | ".join(sorted(against_set))

	return out



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
