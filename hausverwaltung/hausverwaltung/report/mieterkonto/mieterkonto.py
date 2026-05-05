from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	is_receivable_writeoff_journal_entry,
)
from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles


CATEGORIES = ("miete", "betriebskosten", "heizkosten", "guthaben_nachzahlungen")
CATEGORY_LABELS = {
	"miete": "Miete",
	"betriebskosten": "BK",
	"heizkosten": "HK",
	"guthaben_nachzahlungen": "G/N",
}
ITEM_CATEGORY_MAP = {
	"Miete": "miete",
	"Untermietzuschlag": "miete",
	"Garage/Stellplatz": "miete",
	"Betriebskosten": "betriebskosten",
	"Heizkosten": "heizkosten",
	"Guthaben/Nachzahlungen": "guthaben_nachzahlungen",
	# BK-Settlement-Items (aus Betriebskostenabrechnung Mieter)
	"BK Nachzahlung": "guthaben_nachzahlungen",
	"BK Guthaben": "guthaben_nachzahlungen",
	# HK-Settlement-Items (aus Heizkostenabrechnung Mieter)
	"HK Nachzahlung": "guthaben_nachzahlungen",
	"HK Guthaben": "guthaben_nachzahlungen",
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
	_apply_defaults(filters)
	_validate_filters(filters)

	invoices = _get_invoices(filters)
	if not invoices:
		return _get_columns(filters), [], None, None, _get_empty_summary()

	transactions = _build_invoice_transactions(invoices)
	transactions.extend(_build_settlement_transactions(invoices, filters))
	transactions.sort(key=_transaction_sort_key)

	rows, summary_totals = _build_rows(transactions, filters)
	columns = _get_columns(filters)
	enrich_link_titles(rows, columns)
	return columns, rows, None, None, _get_report_summary(summary_totals, filters)


def _apply_defaults(filters):
	filters.show_kategorien = cint(filters.get("show_kategorien", 1))


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
				"art": "Forderung",
				"belegart": "Sales Invoice",
				"belegnummer": invoice.name,
				# ``rechnung`` ist intern als Sort-Schlüssel — Rechnung +
				# zugehörige Zahlung sollen pro Datum zusammen erscheinen
				# (siehe ``_transaction_sort_key``). Wird nicht mehr in die
				# Output-Row geschrieben (Spalte wurde entfernt, weil sie für
				# Rechnungs-Zeilen redundant zur ``belegnummer`` war).
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
		voucher_remarks = _fetch_voucher_remarks(rows)
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
					"beschreibung": _get_settlement_description(
					row,
					invoice,
					is_writeoff,
					voucher_remarks.get((row.voucher_type, row.voucher_no)),
				),
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


def _get_settlement_description(
	row,
	invoice,
	is_writeoff: bool,
	voucher_info: dict | None = None,
) -> str:
	# Wenn der Beleg eine User-Anmerkung hat: NUR die zeigen (keine
	# "Zahlung zu ACC-SINV-..."-Vorrede — wirkt sonst doppelt mit der
	# Belegnummer-Spalte). Sonst Default-Label "Zahlung zu <Rechnung>"
	# damit der Bezug zur Forderung nicht verloren geht.
	suffix = _build_voucher_suffix(row.voucher_type, voucher_info or {})
	if suffix:
		return suffix
	label = _("Abschreibung") if is_writeoff else _get_voucher_label(row.voucher_type)
	return _("{0} zu {1}").format(label, invoice.name)


def _build_voucher_suffix(voucher_type: str, info: dict) -> str:
	"""Baut den User-Anmerkungs-Suffix für die Beschreibungs-Spalte.

	Payment Entry: nur dann anzeigen wenn `remarks` echt user-getippt ist —
	Frappes Auto-Pattern beginnt mit 'Amount ', das filtern wir raus.

	Journal Entry / Sales Invoice (Gutschrift): direkt das Remark-Feld.
	"""
	if voucher_type == "Payment Entry":
		remark = (info.get("remarks") or "").strip()
		if remark and not remark.lower().startswith("amount "):
			return remark
		return ""
	return (info.get("user_remark") or info.get("remarks") or "").strip()


# Welche Felder pro Voucher-Type für die Beschreibung relevant sind.
_VOUCHER_INFO_FIELDS = {
	"Payment Entry": ["remarks"],
	"Journal Entry": ["user_remark"],
	"Sales Invoice": ["remarks"],  # bei Gutschriften
}


def _fetch_voucher_remarks(payment_ledger_rows) -> dict[tuple[str, str], dict]:
	"""Bulk-fetch der relevanten Beleg-Felder pro (voucher_type, voucher_no).

	Eine separate Query pro Voucher-Type — vermeidet N+1-Queries bei vielen
	Zahlungen pro Mieter.
	"""
	from collections import defaultdict

	names_by_type: dict[str, set[str]] = defaultdict(set)
	for row in payment_ledger_rows:
		if row.voucher_type in _VOUCHER_INFO_FIELDS:
			names_by_type[row.voucher_type].add(row.voucher_no)

	out: dict[tuple[str, str], dict] = {}
	for voucher_type, names in names_by_type.items():
		fields = ["name"] + _VOUCHER_INFO_FIELDS[voucher_type]
		for r in frappe.get_all(
			voucher_type,
			filters={"name": ("in", list(names))},
			fields=fields,
		):
			out[(voucher_type, r["name"])] = dict(r)
	return out


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
	opening_added = False
	currency_seen: str | None = None

	for transaction in transactions:
		if transaction["date"] > filters.to_date:
			continue
		if transaction["date"] < filters.from_date:
			balance += flt(transaction["delta"])
			_accumulate_totals(all_totals, transaction)
			if transaction.get("currency"):
				currency_seen = transaction["currency"]
			continue

		# Erste in-period-Transaktion → Anfangsbestand davor einblenden
		# (immer, auch bei Saldo 0 — die User wollen die Eröffnung als Anker sehen).
		if not opening_added:
			rows.append(_opening_row(filters, balance, transaction.get("currency") or currency_seen))
			opening_added = True

		balance += flt(transaction["delta"])
		_accumulate_totals(all_totals, transaction)
		_accumulate_totals(period_totals, transaction)
		if transaction.get("currency"):
			currency_seen = transaction["currency"]
		row = _transaction_to_row(transaction, balance)
		if not filters.get("show_kategorien"):
			row = _hide_kategorien_columns(row)
		rows.append(row)

	# Gar keine Bewegung im Zeitraum, aber Vorperiode hat Saldo aufgebaut →
	# trotzdem Eröffnung zeigen, damit der Bericht nicht leer wirkt.
	if not opening_added and abs(balance) > TOLERANCE:
		rows.append(_opening_row(filters, balance, currency_seen or _get_currency(filters.company)))

	# Summenzeile am Ende (nur wenn überhaupt Bewegungen im Zeitraum waren).
	if any(not r.get("is_opening_row") for r in rows):
		rows.append(_total_row(rows, balance, filters))

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
		"beschreibung": _("Anfangsbestand"),
		"kontostand": flt(balance, 2),
		"waehrung": currency or _get_currency(filters.company),
		"is_opening_row": 1,
	}


def _total_row(rows: list[dict[str, Any]], balance: float, filters) -> dict[str, Any]:
	"""Letzte Zeile mit Spalten-Summen über alle in-period-Transaktionen +
	finalem Kontostand. Zeile wird im JS-Formatter fett dargestellt."""
	total: dict[str, Any] = {
		"datum": filters.to_date,
		"art": "",
		"beschreibung": _("Σ Zeitraum"),
		"kontostand": flt(balance, 2),
		"is_total_row": 1,
	}
	# Nur über die echten Transaktions-Zeilen summieren — Opening und vorherige
	# Total-Zeilen ausnehmen.
	tx_rows = [r for r in rows if not r.get("is_opening_row") and not r.get("is_total_row")]
	for category in CATEGORIES:
		total[f"betrag_{category}"] = flt(
			sum(flt(r.get(f"betrag_{category}")) for r in tx_rows), 2
		)
	total["betrag_summe"] = flt(
		sum(flt(r.get("betrag_summe")) for r in tx_rows), 2
	)
	if not filters.get("show_kategorien"):
		total = _hide_kategorien_columns(total)
	return total


def _transaction_to_row(transaction: dict[str, Any], balance: float) -> dict[str, Any]:
	row = {
		"datum": transaction["date"],
		"art": transaction["art"],
		"belegart": transaction["belegart"],
		"belegnummer": transaction["belegnummer"],
		"beschreibung": transaction["beschreibung"],
		"faellig_am": transaction.get("due_date"),
		"status": transaction.get("status"),
		"kontostand": flt(balance, 2),
		"waehrung": transaction.get("currency"),
	}
	# Signed per-category Spalte: +Soll (Rechnung), -Bezahlt (Zahlung),
	# -Abgeschrieben. Pro Transaktion ist nur eine Quelle ≠ 0, das Vorzeichen
	# fällt also natürlich richtig raus. Die "Art"-Pille (Rechnung/Zahlung/
	# Abschreibung) sagt zusätzlich was es ist.
	invoice = transaction.get("invoice_amounts") or {}
	paid = transaction.get("paid_amounts") or {}
	written_off = transaction.get("written_off_amounts") or {}
	for category in CATEGORIES:
		row[f"betrag_{category}"] = flt(
			flt(invoice.get(category)) - flt(paid.get(category)) - flt(written_off.get(category)),
			2,
		)
	row["betrag_summe"] = flt(
		sum(flt(row.get(f"betrag_{category}")) for category in CATEGORIES),
		2,
	)
	return row


def _hide_kategorien_columns(row: dict[str, Any]) -> dict[str, Any]:
	for category in CATEGORIES:
		row.pop(f"betrag_{category}", None)
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


def _get_report_summary(totals: dict[str, Any], filters) -> list[dict[str, Any]]:
	all_totals = totals["all"]
	period_totals = totals["period"]
	currency = all_totals.get("currency") or period_totals.get("currency")
	paid_period = period_totals["paid"]
	written_off_period = period_totals["written_off"]
	paid_all = all_totals["paid"]
	written_off_all = all_totals["written_off"]
	invoice_all = all_totals["invoice"]
	summary = [
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
	# Abgeschrieben-Card nur einblenden wenn im Zeitraum überhaupt was
	# abgeschrieben wurde — sonst Lärm.
	written_off_total = sum(flt(written_off_period.get(category)) for category in CATEGORIES)
	if abs(written_off_total) > TOLERANCE:
		summary.insert(
			2,
			{
				"value": written_off_total,
				"indicator": "Orange",
				"label": _("Abgeschrieben im Zeitraum"),
				"datatype": "Currency",
				"currency": currency,
			},
		)
	return summary


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
		{
			# Dynamic Link liest belegart aus dem Row-Dict — Spalte muss nicht
			# sichtbar sein, das Feld reicht.
			"label": _("Belegnummer"),
			"fieldname": "belegnummer",
			"fieldtype": "Dynamic Link",
			"options": "belegart",
			"width": 180,
		},
		{"label": _("Beschreibung"), "fieldname": "beschreibung", "fieldtype": "Data", "width": 280},
	]

	# Pro Kategorie eine signed Spalte: positiv = Forderung, negativ =
	# Zahlung/Abschreibung. Die "Art"-Pille zeigt zusätzlich was es ist.
	if filters.get("show_kategorien"):
		for category in CATEGORIES:
			columns.append(
				_currency_column(CATEGORY_LABELS[category], f"betrag_{category}")
			)
	columns.append(_currency_column(_("Summe"), "betrag_summe"))

	columns.append(_currency_column(_("Kontostand"), "kontostand", width=125))
	return columns


def _currency_column(label: str, fieldname: str, width: int = 115) -> dict[str, Any]:
	return {
		"label": label,
		"fieldname": fieldname,
		"fieldtype": "Currency",
		"options": "waehrung",
		"width": width,
	}
