from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	is_receivable_writeoff_journal_entry,
)


CATEGORIES = ("miete", "betriebskosten", "heizkosten", "guthaben_nachzahlungen")
CATEGORY_LABELS = {
	"miete": "Miete",
	"betriebskosten": "BK",
	"heizkosten": "HK",
	"guthaben_nachzahlungen": "Guthaben/Nachzahlungen",
}
ITEM_CATEGORY_MAP = {
	"Miete": "miete",
	"Betriebskosten": "betriebskosten",
	"Heizkosten": "heizkosten",
	"Guthaben/Nachzahlungen": "guthaben_nachzahlungen",
}
TOLERANCE = 0.01


@dataclass
class InvoiceInfo:
	name: str
	posting_date: Any
	due_date: Any
	customer: str
	debit_to: str
	currency: str
	grand_total: float
	outstanding_amount: float
	status: str | None
	cost_center: str | None
	remarks: str | None
	category_amounts: dict[str, float] = field(default_factory=dict)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate_filters(filters)

	invoices = _get_invoices(filters)
	if not invoices:
		return _get_columns(filters), [], None, None, _get_empty_summary()

	transactions = _build_invoice_transactions(invoices)
	transactions.extend(_build_settlement_transactions(invoices, filters))
	transactions.sort(key=_transaction_sort_key)

	rows, summary_totals = _build_rows(transactions, filters)
	return _get_columns(filters), rows, None, None, _get_report_summary(summary_totals)


def _validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("Bitte eine Firma wählen."))
	if not filters.get("customer"):
		frappe.throw(_("Bitte einen Mieter/Debitor wählen."))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Bitte Von und Bis wählen."))

	filters.from_date = getdate(filters.from_date)
	filters.to_date = getdate(filters.to_date)
	if filters.from_date > filters.to_date:
		frappe.throw(_("Von darf nicht nach Bis liegen."))


def _get_invoices(filters) -> dict[str, InvoiceInfo]:
	rows = frappe.get_all(
		"Sales Invoice",
		filters={
			"company": filters.company,
			"customer": filters.customer,
			"docstatus": 1,
			"is_return": 0,
			"posting_date": ("<=", filters.to_date),
		},
		fields=[
			"name",
			"posting_date",
			"due_date",
			"customer",
			"debit_to",
			"currency",
			"grand_total",
			"outstanding_amount",
			"status",
			"cost_center",
			"remarks",
		],
		order_by="posting_date asc, name asc",
	)

	invoices: dict[str, InvoiceInfo] = {}
	for row in rows:
		info = InvoiceInfo(
			name=row.name,
			posting_date=row.posting_date,
			due_date=row.due_date,
			customer=row.customer,
			debit_to=row.debit_to,
			currency=row.currency,
			grand_total=flt(row.grand_total),
			outstanding_amount=flt(row.outstanding_amount),
			status=row.status,
			cost_center=row.cost_center,
			remarks=row.remarks,
			category_amounts=_get_invoice_category_amounts(row.name, flt(row.grand_total)),
		)
		invoices[info.name] = info
	return invoices


def _get_invoice_category_amounts(invoice_name: str, grand_total: float) -> dict[str, float]:
	items = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": invoice_name},
		fields=["item_code", "item_name", "description", "amount", "base_amount"],
		order_by="idx asc",
	)
	amounts = {category: 0.0 for category in CATEGORIES}
	for item in items:
		category = _get_item_category(item)
		amounts[category] += flt(item.get("base_amount") or item.get("amount"))

	item_total = sum(amounts.values())
	if abs(item_total) <= TOLERANCE:
		frappe.throw(
			_("Sales Invoice {0} hat keine auswertbaren Artikelbeträge.").format(invoice_name)
		)

	# Taxes/rounding belong to the same functional categories as the invoice lines.
	if abs(flt(grand_total) - item_total) > TOLERANCE:
		amounts = _allocate_amount(grand_total, amounts)
	return _round_amounts(amounts)


def _get_item_category(item) -> str:
	item_code = item.get("item_code")
	if item_code in ITEM_CATEGORY_MAP:
		return ITEM_CATEGORY_MAP[item_code]

	frappe.throw(
		_(
			"Sales Invoice {0} enthält den nicht zuordenbaren Artikel {1}. "
			"Erlaubt sind: {2}"
		).format(
			item.get("parent"),
			item_code or _("kein Artikel"),
			", ".join(ITEM_CATEGORY_MAP),
		)
	)


def _allocate_amount(amount: float, base_amounts: dict[str, float]) -> dict[str, float]:
	total = sum(abs(flt(value)) for value in base_amounts.values())
	if total <= TOLERANCE:
		frappe.throw(_("Betrag kann nicht auf Artikelkategorien verteilt werden."))

	allocated = {category: 0.0 for category in CATEGORIES}
	remaining = flt(amount)
	non_zero_categories = [
		category for category in CATEGORIES if abs(flt(base_amounts.get(category))) > TOLERANCE
	]
	for category in non_zero_categories[:-1]:
		share = abs(flt(base_amounts.get(category))) / total
		allocated[category] = flt(amount * share, 2)
		remaining -= allocated[category]
	if non_zero_categories:
		allocated[non_zero_categories[-1]] = flt(remaining, 2)
	return allocated


def _round_amounts(amounts: dict[str, float]) -> dict[str, float]:
	return {category: flt(amounts.get(category), 2) for category in CATEGORIES}


def _build_invoice_transactions(invoices: dict[str, InvoiceInfo]) -> list[dict[str, Any]]:
	transactions = []
	for invoice in invoices.values():
		transactions.append(
			{
				"date": getdate(invoice.posting_date),
				"sort_order": 10,
				"art": "Rechnung",
				"belegart": "Sales Invoice",
				"belegnummer": invoice.name,
				"rechnung": invoice.name,
				"beschreibung": invoice.remarks or _("Rechnung"),
				"due_date": invoice.due_date,
				"status": invoice.status,
				"currency": invoice.currency,
				"invoice_amounts": invoice.category_amounts,
				"paid_amounts": {},
				"written_off_amounts": {},
				"delta": sum(invoice.category_amounts.values()),
			}
		)
	return transactions


def _build_settlement_transactions(
	invoices: dict[str, InvoiceInfo],
	filters,
) -> list[dict[str, Any]]:
	invoice_names = list(invoices)
	if not invoice_names:
		return []

	transactions = []
	for chunk in _chunks(invoice_names, 500):
		rows = frappe.get_all(
			"Payment Ledger Entry",
			filters={
				"company": filters.company,
				"party_type": "Customer",
				"party": filters.customer,
				"against_voucher_type": "Sales Invoice",
				"against_voucher_no": ("in", chunk),
				"posting_date": ("<=", filters.to_date),
				"delinked": 0,
			},
			fields=[
				"posting_date",
				"voucher_type",
				"voucher_no",
				"against_voucher_no",
				"amount",
				"account",
				"remarks",
			],
			order_by="posting_date asc, creation asc, name asc",
		)
		for row in rows:
			invoice = invoices.get(row.against_voucher_no)
			if not invoice or row.voucher_no == invoice.name:
				continue

			amount = flt(row.amount)
			if abs(amount) <= TOLERANCE:
				continue

			is_writeoff = (
				row.voucher_type == "Journal Entry"
				and amount < 0
				and is_receivable_writeoff_journal_entry(
					row.voucher_no,
					receivable_account=invoice.debit_to,
				)
			)
			is_credit_note = row.voucher_type == "Sales Invoice"
			reduction = abs(amount) if amount < 0 else -abs(amount)
			allocated = _allocate_amount(reduction, invoice.category_amounts)

			transactions.append(
				{
					"date": getdate(row.posting_date),
					"sort_order": 30 if is_writeoff else 20,
					"art": "Abschreibung" if is_writeoff else ("Gutschrift" if is_credit_note else "Zahlung"),
					"belegart": row.voucher_type,
					"belegnummer": row.voucher_no,
					"rechnung": invoice.name,
					"beschreibung": _get_settlement_description(row, invoice.name, is_writeoff),
					"due_date": invoice.due_date,
					"status": invoice.status,
					"currency": invoice.currency,
					"invoice_amounts": {},
					"paid_amounts": {} if is_writeoff else allocated,
					"written_off_amounts": allocated if is_writeoff else {},
					"delta": -sum(allocated.values()),
				}
			)
	return transactions


def _chunks(values: list[str], size: int):
	for index in range(0, len(values), size):
		yield values[index : index + size]


def _get_settlement_description(row, invoice_name: str, is_writeoff: bool) -> str:
	if is_writeoff:
		return _("Abschreibung zu {0}").format(invoice_name)
	return _("{0} zu {1}").format(_get_voucher_label(row.voucher_type), invoice_name)


def _get_voucher_label(voucher_type: str | None) -> str:
	if voucher_type == "Payment Entry":
		return _("Zahlung")
	if voucher_type == "Journal Entry":
		return _("Journal Entry")
	if voucher_type == "Sales Invoice":
		return _("Gutschrift")
	return voucher_type or ""


def _build_rows(transactions: list[dict[str, Any]], filters) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	rows = []
	balance = 0.0
	all_totals = _new_totals()
	period_totals = _new_totals()

	for transaction in transactions:
		if transaction["date"] > filters.to_date:
			continue
		if transaction["date"] < filters.from_date:
			balance += flt(transaction["delta"])
			_accumulate_totals(all_totals, transaction)
			continue

		if not rows and abs(balance) > TOLERANCE:
			rows.append(_opening_row(filters, balance, transaction.get("currency")))

		balance += flt(transaction["delta"])
		_accumulate_totals(all_totals, transaction)
		_accumulate_totals(period_totals, transaction)
		row = _transaction_to_row(transaction, balance)
		if not filters.get("show_invoice_details"):
			row = _hide_invoice_detail_columns(row)
		rows.append(row)

	if not rows and abs(balance) > TOLERANCE:
		rows.append(_opening_row(filters, balance, _get_currency(filters.company)))

	all_totals["balance"] = flt(balance, 2)
	return rows, {"all": all_totals, "period": period_totals}


def _new_totals() -> dict[str, Any]:
	return {
		"invoice": defaultdict(float),
		"paid": defaultdict(float),
		"written_off": defaultdict(float),
		"balance": 0.0,
		"currency": None,
	}


def _accumulate_totals(totals: dict[str, Any], transaction: dict[str, Any]) -> None:
	if transaction.get("currency"):
		totals["currency"] = transaction["currency"]
	for target, source in (
		("invoice", "invoice_amounts"),
		("paid", "paid_amounts"),
		("written_off", "written_off_amounts"),
	):
		for category, amount in (transaction.get(source) or {}).items():
			totals[target][category] += flt(amount)


def _opening_row(filters, balance: float, currency: str | None) -> dict[str, Any]:
	return {
		"datum": filters.from_date,
		"art": "Eröffnung",
		"beschreibung": _("Saldo vor Zeitraum"),
		"kontostand": flt(balance, 2),
		"waehrung": currency or _get_currency(filters.company),
	}


def _transaction_to_row(transaction: dict[str, Any], balance: float) -> dict[str, Any]:
	row = {
		"datum": transaction["date"],
		"art": transaction["art"],
		"belegart": transaction["belegart"],
		"belegnummer": transaction["belegnummer"],
		"rechnung": transaction["rechnung"],
		"beschreibung": transaction["beschreibung"],
		"faellig_am": transaction.get("due_date"),
		"status": transaction.get("status"),
		"kontostand": flt(balance, 2),
		"waehrung": transaction.get("currency"),
	}
	for prefix, source in (
		("soll", transaction.get("invoice_amounts") or {}),
		("bezahlt", transaction.get("paid_amounts") or {}),
		("abgeschrieben", transaction.get("written_off_amounts") or {}),
	):
		for category in CATEGORIES:
			row[f"{prefix}_{category}"] = flt(source.get(category), 2)

	row["soll_summe"] = sum(flt(row.get(f"soll_{category}")) for category in CATEGORIES)
	row["bezahlt_summe"] = sum(flt(row.get(f"bezahlt_{category}")) for category in CATEGORIES)
	row["abgeschrieben_summe"] = sum(
		flt(row.get(f"abgeschrieben_{category}")) for category in CATEGORIES
	)
	return row


def _hide_invoice_detail_columns(row: dict[str, Any]) -> dict[str, Any]:
	for category in CATEGORIES:
		row.pop(f"soll_{category}", None)
	return row


def _transaction_sort_key(transaction: dict[str, Any]):
	return (
		transaction["date"],
		transaction.get("rechnung") or "",
		transaction.get("sort_order") or 99,
		transaction.get("belegnummer") or "",
	)


def _get_currency(company: str) -> str | None:
	return frappe.db.get_value("Company", company, "default_currency")


def _get_report_summary(totals: dict[str, Any]) -> list[dict[str, Any]]:
	all_totals = totals["all"]
	period_totals = totals["period"]
	currency = all_totals.get("currency") or period_totals.get("currency")
	paid_period = period_totals["paid"]
	written_off_period = period_totals["written_off"]
	paid_all = all_totals["paid"]
	written_off_all = all_totals["written_off"]
	invoice_all = all_totals["invoice"]
	return [
		{
			"value": all_totals["balance"],
			"indicator": "Red" if flt(all_totals["balance"]) > TOLERANCE else "Green",
			"label": _("Kontostand"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": sum(flt(paid_period.get(category)) for category in CATEGORIES),
			"indicator": "Green",
			"label": _("Bezahlt im Zeitraum"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": sum(flt(written_off_period.get(category)) for category in CATEGORIES),
			"indicator": "Orange",
			"label": _("Abgeschrieben im Zeitraum"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": _open_category_amount(all_totals, "miete"),
			"indicator": "Blue",
			"label": _("Miete offen"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": _open_category_amount(all_totals, "betriebskosten"),
			"indicator": "Blue",
			"label": _("BK offen"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": _open_category_amount(all_totals, "heizkosten"),
			"indicator": "Blue",
			"label": _("HK offen"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": _open_category_amount(all_totals, "guthaben_nachzahlungen"),
			"indicator": "Blue",
			"label": _("Guthaben/Nachzahlungen offen"),
			"datatype": "Currency",
			"currency": currency,
		},
	]


def _open_category_amount(totals: dict[str, Any], category: str) -> float:
	return flt(
		flt(totals["invoice"].get(category))
		- flt(totals["paid"].get(category))
		- flt(totals["written_off"].get(category)),
		2,
	)


def _get_empty_summary() -> list[dict[str, Any]]:
	return [
		{
			"value": 0,
			"indicator": "Green",
			"label": _("Kontostand"),
			"datatype": "Currency",
		}
	]


def _get_columns(filters):
	columns = [
		{"label": _("Datum"), "fieldname": "datum", "fieldtype": "Date", "width": 100},
		{"label": _("Art"), "fieldname": "art", "fieldtype": "Data", "width": 105},
		{"label": _("Belegart"), "fieldname": "belegart", "fieldtype": "Data", "width": 120},
		{
			"label": _("Belegnummer"),
			"fieldname": "belegnummer",
			"fieldtype": "Dynamic Link",
			"options": "belegart",
			"width": 180,
		},
		{
			"label": _("Rechnung"),
			"fieldname": "rechnung",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 170,
		},
		{"label": _("Beschreibung"), "fieldname": "beschreibung", "fieldtype": "Data", "width": 240},
	]

	if filters.get("show_invoice_details"):
		for category in CATEGORIES:
			columns.append(_currency_column(_("Soll {0}").format(CATEGORY_LABELS[category]), f"soll_{category}"))
	else:
		columns.append(_currency_column(_("Soll"), "soll_summe"))

	for category in CATEGORIES:
		columns.append(
			_currency_column(
				_("{0} bezahlt").format(CATEGORY_LABELS[category]),
				f"bezahlt_{category}",
			)
		)
	for category in CATEGORIES:
		columns.append(
			_currency_column(
				_("{0} abgeschrieben").format(CATEGORY_LABELS[category]),
				f"abgeschrieben_{category}",
			)
		)

	columns.extend(
		[
			_currency_column(_("Bezahlt gesamt"), "bezahlt_summe"),
			_currency_column(_("Abgeschrieben gesamt"), "abgeschrieben_summe"),
			_currency_column(_("Kontostand"), "kontostand", width=125),
			{"label": _("Fällig am"), "fieldname": "faellig_am", "fieldtype": "Date", "width": 100},
			{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 150},
			{
				"label": _("Währung"),
				"fieldname": "waehrung",
				"fieldtype": "Link",
				"options": "Currency",
				"width": 80,
			},
		]
	)
	return columns


def _currency_column(label: str, fieldname: str, width: int = 115) -> dict[str, Any]:
	return {
		"label": label,
		"fieldname": fieldname,
		"fieldtype": "Currency",
		"options": "waehrung",
		"width": width,
	}
