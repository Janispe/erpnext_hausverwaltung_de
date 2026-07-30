from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, nowdate

WRITTEN_OFF_STATUS = "Abgeschrieben"
PARTLY_PAID_AND_WRITTEN_OFF_STATUS = "Teilweise bezahlt und abgeschrieben"
OUTSTANDING_TOLERANCE = 0.01
DEFAULT_WRITE_OFF_ACCOUNT_NAME = "Abschreibungen Mieterforderungen"
HV_WRITEOFF_MARKER_PREFIX = "[HV-WRITEOFF:"
HV_WRITEOFF_MARKER_RE = re.compile(r"^\[HV-WRITEOFF:([^\]\r\n]+)\](?:\s|$)")


def _money_cents(value: Any) -> Decimal:
	try:
		return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Ungültiger Geldbetrag: {0}").format(value))


def _exact_decimal(value: Any) -> Decimal:
	try:
		return Decimal(str(value or 0))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Ungültiger Zahlenwert: {0}").format(value))


def _doctype_has_field(doctype: str, fieldname: str) -> bool:
	return bool(frappe.get_meta(doctype).get_field(fieldname))


def _dict_value(row: Any, fieldname: str) -> Any:
	if isinstance(row, dict):
		return row.get(fieldname)
	getter = getattr(row, "get", None)
	if callable(getter):
		return getter(fieldname)
	return getattr(row, fieldname, None)


def _lock_current_sales_invoice_rows(invoice_names: list[str]) -> dict[str, Any]:
	names = sorted({cstr(name).strip() for name in invoice_names if cstr(name).strip()})
	if not names:
		return {}

	fields = [
		"name",
		"docstatus",
		"is_return",
		"status",
		"outstanding_amount",
		"grand_total",
		"customer",
		"debit_to",
		"company",
		"cost_center",
		"currency",
	]
	for fieldname in ("party_account_currency", "wohnung", "immobilie", "mietvertrag"):
		if _doctype_has_field("Sales Invoice", fieldname):
			fields.append(fieldname)

	rows = frappe.db.sql(
		f"""
		SELECT {", ".join(f"`{fieldname}`" for fieldname in fields)}
		FROM `tabSales Invoice`
		WHERE name IN %(names)s
		ORDER BY name
		FOR UPDATE
		""",
		{"names": tuple(names)},
		as_dict=True,
	)
	by_name = {cstr(row.name): row for row in rows}
	missing = [name for name in names if name not in by_name]
	if missing:
		frappe.throw(
			_("Sales Invoice {0} wurde nicht gefunden.").format(", ".join(missing))
		)
	return by_name


def _lock_current_sales_invoice_items(invoice_names: list[str]) -> dict[str, list[Any]]:
	names = sorted({cstr(name).strip() for name in invoice_names if cstr(name).strip()})
	if not names:
		return {}

	fields = ["name", "parent", "idx", "cost_center"]
	if _doctype_has_field("Sales Invoice Item", "wohnung"):
		fields.append("wohnung")
	rows = frappe.db.sql(
		f"""
		SELECT {", ".join(f"`{fieldname}`" for fieldname in fields)}
		FROM `tabSales Invoice Item`
		WHERE parent IN %(names)s
		  AND parenttype = 'Sales Invoice'
		ORDER BY parent, idx, name
		FOR UPDATE
		""",
		{"names": tuple(names)},
		as_dict=True,
	)
	by_parent: dict[str, list[Any]] = {name: [] for name in names}
	for row in rows:
		by_parent.setdefault(cstr(row.parent), []).append(row)
	return by_parent


def _lock_company(company: str, *, context: str) -> Any:
	values = frappe.db.get_value(
		"Company",
		company,
		["name", "default_currency", "cost_center"],
		as_dict=True,
		for_update=True,
	) or {}
	if not _dict_value(values, "name"):
		frappe.throw(_("{0}: Firma {1} wurde nicht gefunden.").format(context, company))
	if not cstr(_dict_value(values, "default_currency")).strip():
		frappe.throw(
			_("{0}: Firma {1} hat keine Standardwährung.").format(context, company)
		)
	return values


def _validate_locked_cost_center(cost_center: str, company: str, *, context: str) -> str:
	cost_center = cstr(cost_center).strip()
	if not cost_center:
		frappe.throw(_("{0}: Kostenstelle fehlt.").format(context))
	values = frappe.db.get_value(
		"Cost Center",
		cost_center,
		["name", "company", "is_group", "disabled"],
		as_dict=True,
		for_update=True,
	) or {}
	if (
		not _dict_value(values, "name")
		or cstr(_dict_value(values, "company")).strip() != company
		or cint(_dict_value(values, "is_group"))
		or cint(_dict_value(values, "disabled"))
	):
		frappe.throw(
			_(
				"{0}: Kostenstelle {1} ist keine aktive Blatt-Kostenstelle der Firma {2}."
			).format(context, cost_center, company)
		)
	return cost_center


def _lock_property_booking_identity(
	wohnung: str,
	company: str,
	*,
	context: str,
) -> dict[str, str]:
	wohnung = cstr(wohnung).strip()
	wohnung_values = frappe.db.get_value(
		"Wohnung",
		wohnung,
		["name", "immobilie"],
		as_dict=True,
		for_update=True,
	) or {}
	immobilie = cstr(_dict_value(wohnung_values, "immobilie")).strip()
	if not _dict_value(wohnung_values, "name") or not immobilie:
		frappe.throw(
			_("{0}: Wohnung {1} wurde nicht gefunden oder hat keine Immobilie.").format(
				context, wohnung
			)
		)

	immobilie_values = frappe.db.get_value(
		"Immobilie",
		immobilie,
		["name", "kostenstelle"],
		as_dict=True,
		for_update=True,
	) or {}
	cost_center = cstr(_dict_value(immobilie_values, "kostenstelle")).strip()
	if not _dict_value(immobilie_values, "name") or not cost_center:
		frappe.throw(
			_(
				"{0}: Immobilie {1} der Wohnung {2} hat keine eindeutige Kostenstelle."
			).format(context, immobilie, wohnung)
		)

	_validate_locked_cost_center(cost_center, company, context=context)
	return {
		"wohnung": wohnung,
		"immobilie": immobilie,
		"cost_center": cost_center,
		"company": company,
	}


def _resolve_locked_invoice_booking_context(invoice: Any, items: list[Any]) -> dict[str, str | None]:
	invoice_name = cstr(_dict_value(invoice, "name")).strip()
	company = cstr(_dict_value(invoice, "company")).strip()
	context = _("Sales Invoice {0}").format(invoice_name)
	if not company:
		frappe.throw(_("{0} hat keine Firma.").format(context))
	company_values = _lock_company(company, context=context)

	if not items:
		frappe.throw(_("{0} enthält keine Rechnungsposition.").format(context))

	header_wohnung = cstr(_dict_value(invoice, "wohnung")).strip()
	item_wohnung_field = _doctype_has_field("Sales Invoice Item", "wohnung")
	item_wohnungen = [
		cstr(_dict_value(item, "wohnung")).strip() if item_wohnung_field else ""
		for item in items
	]
	wohnung = ""
	if header_wohnung:
		if not item_wohnung_field:
			frappe.throw(
				_(
					"{0}: Das Pflichtfeld Wohnung fehlt auf Sales Invoice Item. "
					"Bitte die Custom-Field-Einrichtung reparieren."
				).format(context)
			)
		if any(item_wohnung != header_wohnung for item_wohnung in item_wohnungen):
			frappe.throw(
				_(
					"{0}: Header-Wohnung {1} und die Wohnungen aller Positionen "
					"müssen exakt übereinstimmen."
				).format(context, header_wohnung)
			)
		wohnung = header_wohnung
	elif any(item_wohnungen):
		if any(not item_wohnung for item_wohnung in item_wohnungen) or len(set(item_wohnungen)) != 1:
			frappe.throw(
				_(
					"{0}: Die Positionen enthalten keine eindeutige, vollständig "
					"gesetzte Wohnung."
				).format(context)
			)
		wohnung = item_wohnungen[0]

	header_cost_center = cstr(_dict_value(invoice, "cost_center")).strip()
	if wohnung:
		property_context = _lock_property_booking_identity(
			wohnung,
			company,
			context=context,
		)
		property_cost_center = cstr(property_context["cost_center"])
		if header_cost_center != property_cost_center:
			frappe.throw(
				_(
					"{0}: Header-Kostenstelle muss für Wohnung {1} exakt {2} sein."
				).format(context, wohnung, property_cost_center)
			)
		for item in items:
			if cstr(_dict_value(item, "cost_center")).strip() != property_cost_center:
				frappe.throw(
					_(
						"{0}: Jede Position muss für Wohnung {1} exakt die "
						"Property-Kostenstelle {2} tragen."
					).format(context, wohnung, property_cost_center)
				)
		header_immobilie = cstr(_dict_value(invoice, "immobilie")).strip()
		if header_immobilie and header_immobilie != property_context["immobilie"]:
			frappe.throw(
				_(
					"{0}: Immobilie {1} widerspricht der Wohnung {2}."
				).format(context, header_immobilie, wohnung)
			)
		return property_context

	company_default_cost_center = cstr(
		_dict_value(company_values, "cost_center")
	).strip()
	effective_cost_centers: list[str] = []
	for item in items:
		effective = (
			cstr(_dict_value(item, "cost_center")).strip()
			or header_cost_center
			or company_default_cost_center
		)
		if effective:
			effective_cost_centers.append(effective)
	if not effective_cost_centers:
		fallback = header_cost_center or company_default_cost_center
		if fallback:
			effective_cost_centers.append(fallback)
	if not effective_cost_centers or len(set(effective_cost_centers)) != 1:
		frappe.throw(
			_(
				"{0}: Für eine Rechnung ohne Wohnung muss über alle Positionen "
				"genau eine Kostenstelle bestimmbar sein."
			).format(context)
		)
	cost_center = _validate_locked_cost_center(
		effective_cost_centers[0],
		company,
		context=context,
	)
	return {
		"wohnung": None,
		"immobilie": None,
		"cost_center": cost_center,
		"company": company,
	}


def lock_current_sales_invoice_contexts(
	invoice_names: list[str],
) -> dict[str, dict[str, Any]]:
	"""Lock current invoice/item rows and derive one fail-closed booking identity."""
	rows = _lock_current_sales_invoice_rows(invoice_names)
	items_by_parent = _lock_current_sales_invoice_items(list(rows))
	contexts: dict[str, dict[str, Any]] = {}
	for invoice_name in sorted(rows):
		invoice = rows[invoice_name]
		items = items_by_parent.get(invoice_name) or []
		booking = _resolve_locked_invoice_booking_context(invoice, items)
		contexts[invoice_name] = {
			"invoice": invoice,
			"items": items,
			**booking,
		}
	return contexts


def build_hv_writeoff_remark(invoice_name: str, detail: str | None = None) -> str:
	invoice_name = cstr(invoice_name).strip()
	if not invoice_name or "]" in invoice_name or "\n" in invoice_name or "\r" in invoice_name:
		frappe.throw(_("Ungültige Sales-Invoice-Referenz für die Abschreibung."))
	marker = f"{HV_WRITEOFF_MARKER_PREFIX}{invoice_name}]"
	detail = cstr(detail).strip()
	return f"{marker} {detail}" if detail else marker


def get_hv_writeoff_marker_invoice(doc) -> str | None:
	if cstr(_dict_value(doc, "voucher_type")).strip() != "Write Off Entry":
		return None
	remark = cstr(
		_dict_value(doc, "user_remark") or _dict_value(doc, "remark")
	).strip()
	match = HV_WRITEOFF_MARKER_RE.match(remark)
	return match.group(1).strip() if match else None


def _get_persisted_hv_writeoff_marker_invoice(doc) -> str | None:
	name = cstr(_dict_value(doc, "name")).strip()
	if not name or bool(_dict_value(doc, "__islocal")):
		return None
	rows = frappe.db.sql(
		"""
		SELECT voucher_type, user_remark
		FROM `tabJournal Entry`
		WHERE name = %(name)s
		  AND docstatus = 0
		FOR UPDATE
		""",
		{"name": name},
		as_dict=True,
	)
	if not rows:
		return None
	return get_hv_writeoff_marker_invoice(rows[0])


def _get_owned_hv_writeoff_invoice(doc) -> str | None:
	current_invoice = get_hv_writeoff_marker_invoice(doc)
	persisted_invoice = _get_persisted_hv_writeoff_marker_invoice(doc)
	if not persisted_invoice:
		return current_invoice
	if (
		cstr(_dict_value(doc, "voucher_type")).strip() != "Write Off Entry"
		or current_invoice != persisted_invoice
	):
		frappe.throw(
			_(
				"Der technische HV-Abschreibungsmarker bzw. Belegtyp des Drafts "
				"darf nicht entfernt oder auf eine andere Rechnung geändert werden."
			)
		)
	return persisted_invoice


def protect_hv_writeoff_draft_ownership(doc, method=None) -> None:
	"""Prevent an app-created draft from shedding its persisted ownership marker."""
	_get_owned_hv_writeoff_invoice(doc)


def is_sales_invoice_written_off_by_journal_entry(
	invoice_name: str,
	*,
	outstanding_amount: float | None = None,
) -> bool:
	"""Return true only for submitted Sales Invoices closed by a bad-debt Journal Entry."""
	if not invoice_name:
		return False

	invoice = frappe.db.get_value(
		"Sales Invoice",
		invoice_name,
		["docstatus", "is_return", "outstanding_amount"],
		as_dict=True,
	)
	if not invoice or int(invoice.get("docstatus") or 0) != 1 or int(invoice.get("is_return") or 0):
		return False

	outstanding = invoice.get("outstanding_amount") if outstanding_amount is None else outstanding_amount
	if abs(flt(outstanding)) > OUTSTANDING_TOLERANCE:
		return False

	return bool(get_sales_invoice_writeoff_journal_entries(invoice_name))


def get_sales_invoice_writeoff_status(
	invoice_name: str,
	*,
	outstanding_amount: float | None = None,
) -> str | None:
	"""Return the write-off status for a Sales Invoice, if a qualifying Journal Entry closed it."""
	if not is_sales_invoice_written_off_by_journal_entry(
		invoice_name,
		outstanding_amount=outstanding_amount,
	):
		return None

	if has_non_writeoff_settlement(invoice_name):
		return PARTLY_PAID_AND_WRITTEN_OFF_STATUS

	return WRITTEN_OFF_STATUS


def get_sales_invoice_writeoff_journal_entries(invoice_name: str) -> list[str]:
	"""Find submitted Journal Entries that write off the given Sales Invoice to expense."""
	if not invoice_name:
		return []

	rows = frappe.db.sql(
		"""
		SELECT DISTINCT je.name
		FROM `tabJournal Entry` je
		INNER JOIN `tabJournal Entry Account` receivable
			ON receivable.parent = je.name
		WHERE je.docstatus = 1
		  AND receivable.docstatus = 1
		  AND receivable.reference_type = 'Sales Invoice'
		  AND receivable.reference_name = %(invoice_name)s
		  AND receivable.party_type = 'Customer'
		  AND receivable.credit > 0
		  AND EXISTS (
		  	SELECT 1
		  	FROM `tabJournal Entry Account` expense
		  	INNER JOIN `tabAccount` expense_account
		  		ON expense_account.name = expense.account
		  	WHERE expense.parent = je.name
		  	  AND expense.docstatus = 1
		  	  AND expense.debit > 0
		  	  AND expense_account.root_type = 'Expense'
		  )
		  AND NOT EXISTS (
		  	SELECT 1
		  	FROM `tabJournal Entry Account` bank_cash
		  	INNER JOIN `tabAccount` bank_cash_account
		  		ON bank_cash_account.name = bank_cash.account
		  	WHERE bank_cash.parent = je.name
		  	  AND bank_cash.docstatus = 1
		  	  AND bank_cash_account.account_type IN ('Bank', 'Cash')
		  )
		ORDER BY je.posting_date, je.name
		""",
		{"invoice_name": invoice_name},
		as_dict=True,
	)
	return [row.name for row in rows]


def has_non_writeoff_settlement(invoice_name: str) -> bool:
	"""Return true when something other than a Journal Entry also settled the invoice."""
	if not invoice_name:
		return False

	return bool(
		frappe.db.exists(
			"Payment Ledger Entry",
			{
				"against_voucher_type": "Sales Invoice",
				"against_voucher_no": invoice_name,
				"delinked": 0,
				"voucher_type": ["!=", "Journal Entry"],
				"voucher_no": ["!=", invoice_name],
			},
		)
	)


def is_receivable_writeoff_journal_entry(
	journal_entry: str,
	*,
	receivable_account: str | None = None,
) -> bool:
	"""Allow only Journal Entries that credit a Sales Invoice receivable to an expense account."""
	if not journal_entry:
		return False

	params: dict[str, Any] = {"journal_entry": journal_entry}
	receivable_account_clause = ""
	if receivable_account:
		params["receivable_account"] = receivable_account
		receivable_account_clause = "AND receivable.account = %(receivable_account)s"

	rows = frappe.db.sql(
		f"""
		SELECT receivable.reference_name AS sales_invoice
		FROM `tabJournal Entry` je
		INNER JOIN `tabJournal Entry Account` receivable
			ON receivable.parent = je.name
		WHERE je.name = %(journal_entry)s
		  AND je.docstatus = 1
		  AND receivable.docstatus = 1
		  AND receivable.reference_type = 'Sales Invoice'
		  AND receivable.reference_name IS NOT NULL
		  AND receivable.reference_name != ''
		  AND receivable.party_type = 'Customer'
		  AND receivable.credit > 0
		  {receivable_account_clause}
		  AND EXISTS (
		  	SELECT 1
		  	FROM `tabJournal Entry Account` expense
		  	INNER JOIN `tabAccount` expense_account
		  		ON expense_account.name = expense.account
		  	WHERE expense.parent = je.name
		  	  AND expense.docstatus = 1
		  	  AND expense.debit > 0
		  	  AND expense_account.root_type = 'Expense'
		  )
		  AND NOT EXISTS (
		  	SELECT 1
		  	FROM `tabJournal Entry Account` bank_cash
		  	INNER JOIN `tabAccount` bank_cash_account
		  		ON bank_cash_account.name = bank_cash.account
		  	WHERE bank_cash.parent = je.name
		  	  AND bank_cash.docstatus = 1
		  	  AND bank_cash_account.account_type IN ('Bank', 'Cash')
		  )
		LIMIT 1
		""",
		params,
		as_dict=True,
	)
	return bool(rows)


@frappe.whitelist()
def get_writeoff_preview(invoice_names: str | list[str]) -> dict[str, Any]:
	"""Return validated write-off data for the confirmation dialogs."""
	entries = _validate_writeoff_request(invoice_names)
	return {
		"count": len(entries),
		"total": sum(flt(entry["amount"]) for entry in entries),
		"writeoff_account": entries[0]["writeoff_account"] if entries else None,
		"posting_date": nowdate(),
		"invoices": [
			{
				"sales_invoice": entry["sales_invoice"],
				"customer": entry["customer"],
				"company": entry["company"],
				"amount": entry["amount"],
				"cost_center": entry["cost_center"],
				"writeoff_account": entry["writeoff_account"],
				"currency": entry["currency"],
			}
			for entry in entries
		],
	}


@frappe.whitelist()
def write_off_sales_invoices(
	invoice_names: str | list[str],
	posting_date: str | None = None,
) -> dict[str, Any]:
	"""Write off open Sales Invoice receivables with one submitted Journal Entry per invoice."""
	entries = _validate_writeoff_request(invoice_names)
	posting_date = getdate(posting_date or nowdate())

	results = []
	for entry in entries:
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Write Off Entry"
		je.company = entry["company"]
		je.posting_date = posting_date
		je.user_remark = build_hv_writeoff_remark(
			entry["sales_invoice"],
			_("Abschreibung Sales Invoice {0}").format(entry["sales_invoice"]),
		)
		dimensions = get_writeoff_journal_entry_dimensions(entry)

		je.append(
			"accounts",
			{
				"account": entry["writeoff_account"],
				"debit_in_account_currency": entry["amount"],
				**dimensions,
			},
		)
		je.append(
			"accounts",
			{
				"account": entry["receivable_account"],
				"party_type": "Customer",
				"party": entry["customer"],
				"reference_type": "Sales Invoice",
				"reference_name": entry["sales_invoice"],
				"credit_in_account_currency": entry["amount"],
				**dimensions,
			},
		)

		je.insert()
		je.submit()

		invoice = frappe.get_doc("Sales Invoice", entry["sales_invoice"])
		invoice.set_status(update=True)
		results.append(
			{
				"sales_invoice": entry["sales_invoice"],
				"journal_entry": je.name,
				"amount": entry["amount"],
				"status": invoice.status,
			}
		)

	return {
		"count": len(results),
		"total": sum(flt(result["amount"]) for result in results),
		"journal_entries": results,
	}


def _validate_writeoff_request(invoice_names: str | list[str]) -> list[dict[str, Any]]:
	names = _normalize_invoice_names(invoice_names)
	if not names:
		frappe.throw(_("Bitte mindestens eine Rechnung auswählen."))

	locked_contexts = lock_current_sales_invoice_contexts(names)
	entries = []
	for invoice_name in names:
		entries.append(
			_validate_sales_invoice_for_writeoff(
				invoice_name,
				locked_context=locked_contexts[invoice_name],
			)
		)
	return entries


def _normalize_invoice_names(invoice_names: str | list[str]) -> list[str]:
	if isinstance(invoice_names, str):
		try:
			parsed = json.loads(invoice_names)
		except ValueError:
			parsed = invoice_names
	else:
		parsed = invoice_names

	if isinstance(parsed, str):
		values = [value.strip() for value in parsed.split(",")]
	else:
		values = [str(value).strip() for value in parsed or []]

	names = []
	seen = set()
	for value in values:
		if value and value not in seen:
			names.append(value)
			seen.add(value)
	return names


def _validate_sales_invoice_for_writeoff(
	invoice_name: str,
	*,
	locked_context: dict[str, Any] | None = None,
	writeoff_account: str | None = None,
) -> dict[str, Any]:
	locked_context = locked_context or lock_current_sales_invoice_contexts(
		[invoice_name]
	).get(invoice_name)
	if not locked_context:
		frappe.throw(_("Sales Invoice {0} wurde nicht gefunden.").format(invoice_name))
	invoice = locked_context["invoice"]

	if int(invoice.get("docstatus") or 0) != 1:
		frappe.throw(_("Sales Invoice {0} ist nicht eingereicht.").format(invoice_name))
	if int(invoice.get("is_return") or 0):
		frappe.throw(_("Sales Invoice {0} ist ein Guthaben und kann nicht abgeschrieben werden.").format(invoice_name))
	if invoice.get("status") in (WRITTEN_OFF_STATUS, PARTLY_PAID_AND_WRITTEN_OFF_STATUS):
		frappe.throw(_("Sales Invoice {0} ist bereits abgeschrieben.").format(invoice_name))

	amount_cents = _money_cents(invoice.get("outstanding_amount"))
	if amount_cents <= Decimal("0.00"):
		frappe.throw(_("Sales Invoice {0} hat keinen offenen Forderungsbetrag.").format(invoice_name))
	amount = float(amount_cents)

	if not invoice.get("customer"):
		frappe.throw(_("Sales Invoice {0} hat keinen Kunden.").format(invoice_name))
	if not invoice.get("debit_to"):
		frappe.throw(_("Sales Invoice {0} hat kein Forderungskonto.").format(invoice_name))
	if not invoice.get("company"):
		frappe.throw(_("Sales Invoice {0} hat keine Firma.").format(invoice_name))

	company = cstr(invoice.get("company")).strip()
	company_values = _lock_company(
		company,
		context=_("Sales Invoice {0}").format(invoice_name),
	)
	company_currency = cstr(company_values.get("default_currency")).strip()
	invoice_currency = cstr(invoice.get("currency")).strip()
	party_account_currency = cstr(invoice.get("party_account_currency")).strip()
	if invoice_currency != company_currency or (
		party_account_currency and party_account_currency != company_currency
	):
		frappe.throw(
			_(
				"Sales Invoice {0} ist eine Fremdwährungsrechnung. "
				"Dieser Abschreibungsworkflow unterstützt ausschließlich die Firmenwährung {1}."
			).format(invoice_name, company_currency)
		)

	_validate_receivable_account(
		invoice.get("debit_to"),
		company,
		invoice_name,
		company_currency=company_currency,
	)
	cost_center = cstr(locked_context.get("cost_center")).strip()
	if not cost_center:
		frappe.throw(_("Sales Invoice {0} hat keine eindeutige Kostenstelle.").format(invoice_name))
	writeoff_account = writeoff_account or _get_writeoff_account(
		company,
		company_currency=company_currency,
	)
	_validate_writeoff_expense_account(
		writeoff_account,
		company,
		company_currency=company_currency,
	)

	return {
		"sales_invoice": invoice_name,
		"customer": invoice.get("customer"),
		"company": company,
		"receivable_account": invoice.get("debit_to"),
		"writeoff_account": writeoff_account,
		"cost_center": cost_center,
		"wohnung": locked_context.get("wohnung"),
		"immobilie": locked_context.get("immobilie"),
		"amount": amount,
		"currency": company_currency,
	}


def get_locked_sales_invoice_writeoff_entry(
	invoice_name: str,
	*,
	writeoff_account: str | None = None,
	use_company_default_account: bool = False,
) -> dict[str, Any]:
	locked_context = lock_current_sales_invoice_contexts([invoice_name]).get(invoice_name)
	if not locked_context:
		frappe.throw(_("Sales Invoice {0} wurde nicht gefunden.").format(invoice_name))
	if not writeoff_account and use_company_default_account:
		company = cstr(locked_context["invoice"].get("company")).strip()
		writeoff_account = frappe.db.get_value(
			"Company",
			company,
			"write_off_account",
			for_update=True,
		)
		if not writeoff_account:
			frappe.throw(_("Für die Firma ist kein Write Off Account hinterlegt."))
	return _validate_sales_invoice_for_writeoff(
		invoice_name,
		locked_context=locked_context,
		writeoff_account=writeoff_account,
	)


def _resolved_account_currency(account_details: Any, company_currency: str) -> str:
	return cstr(_dict_value(account_details, "account_currency")).strip() or company_currency


def _validate_receivable_account(
	account: str,
	company: str,
	invoice_name: str,
	*,
	company_currency: str | None = None,
) -> None:
	account_details = frappe.db.get_value(
		"Account",
		account,
		["account_type", "company", "is_group", "disabled", "account_currency"],
		as_dict=True,
		for_update=True,
	)
	if not account_details:
		frappe.throw(_("Forderungskonto {0} aus Sales Invoice {1} wurde nicht gefunden.").format(account, invoice_name))
	if int(account_details.get("is_group") or 0):
		frappe.throw(_("Forderungskonto {0} aus Sales Invoice {1} ist kein Blattkonto.").format(account, invoice_name))
	if int(account_details.get("disabled") or 0):
		frappe.throw(_("Forderungskonto {0} aus Sales Invoice {1} ist deaktiviert.").format(account, invoice_name))
	if account_details.get("company") != company:
		frappe.throw(_("Forderungskonto {0} gehört nicht zur Firma {1}.").format(account, company))
	if account_details.get("account_type") != "Receivable":
		frappe.throw(_("Forderungskonto {0} ist kein Receivable-Konto.").format(account))
	if company_currency and _resolved_account_currency(account_details, company_currency) != company_currency:
		frappe.throw(
			_(
				"Forderungskonto {0} aus Sales Invoice {1} hat eine Fremdwährung. "
				"Die Abschreibung wird abgebrochen."
			).format(account, invoice_name)
		)


def _get_writeoff_cost_center(invoice: dict[str, Any]) -> str:
	cost_center = invoice.get("cost_center") or frappe.db.get_value(
		"Company",
		invoice.get("company"),
		"cost_center",
	)
	if not cost_center:
		frappe.throw(
			_(
				"Für Sales Invoice {0} ist keine Kostenstelle gesetzt und die Firma {1} hat keine Standard-Kostenstelle."
			).format(invoice.get("name"), invoice.get("company"))
		)

	cost_center_company = frappe.db.get_value("Cost Center", cost_center, "company")
	if not cost_center_company:
		frappe.throw(_("Kostenstelle {0} wurde nicht gefunden.").format(cost_center))
	if cost_center_company != invoice.get("company"):
		frappe.throw(_("Kostenstelle {0} gehört nicht zur Firma {1}.").format(cost_center, invoice.get("company")))
	return cost_center


def _get_writeoff_account(
	company: str,
	*,
	company_currency: str | None = None,
) -> str:
	account = frappe.db.get_single_value(
		"Hausverwaltung Einstellungen",
		"abschreibungskonto_forderungen",
	)
	if not account:
		frappe.throw(
			_(
				"Bitte in Hausverwaltung Einstellungen ein Abschreibungskonto für Forderungen hinterlegen."
			)
		)

	_validate_writeoff_expense_account(
		account,
		company,
		company_currency=company_currency,
	)
	return account


def _validate_writeoff_expense_account(
	account: str,
	company: str,
	*,
	company_currency: str | None = None,
) -> None:
	account_details = frappe.db.get_value(
		"Account",
		account,
		["root_type", "account_type", "company", "is_group", "disabled", "account_currency"],
		as_dict=True,
		for_update=True,
	)
	if not account_details:
		frappe.throw(_("Abschreibungskonto {0} wurde nicht gefunden.").format(account))
	if int(account_details.get("is_group") or 0):
		frappe.throw(_("Abschreibungskonto {0} muss ein Blattkonto sein.").format(account))
	if int(account_details.get("disabled") or 0):
		frappe.throw(_("Abschreibungskonto {0} ist deaktiviert.").format(account))
	if account_details.get("root_type") != "Expense":
		frappe.throw(_("Abschreibungskonto {0} muss ein Aufwandskonto sein.").format(account))
	if account_details.get("company") != company:
		frappe.throw(_("Abschreibungskonto {0} gehört nicht zur Firma {1}.").format(account, company))
	if company_currency and _resolved_account_currency(account_details, company_currency) != company_currency:
		frappe.throw(
			_(
				"Abschreibungskonto {0} hat eine Fremdwährung. "
				"Dieser Workflow unterstützt ausschließlich {1}."
			).format(account, company_currency)
		)


def get_writeoff_journal_entry_dimensions(entry: dict[str, Any]) -> dict[str, Any]:
	dimensions: dict[str, Any] = {"cost_center": entry["cost_center"]}
	wohnung = cstr(entry.get("wohnung")).strip()
	if wohnung:
		if not _doctype_has_field("Journal Entry Account", "wohnung"):
			frappe.throw(
				_(
					"Das Pflichtfeld Wohnung fehlt auf Journal Entry Account. "
					"Bitte die Custom-Field-Einrichtung reparieren."
				)
			)
		dimensions["wohnung"] = wohnung
	return dimensions


def _validate_writeoff_line_dimensions(
	row: Any,
	entry: dict[str, Any],
	*,
	label: str,
) -> None:
	expected_cost_center = cstr(entry.get("cost_center")).strip()
	if cstr(_dict_value(row, "cost_center")).strip() != expected_cost_center:
		frappe.throw(
			_("{0}: Kostenstelle muss exakt {1} sein.").format(label, expected_cost_center)
		)
	expected_wohnung = cstr(entry.get("wohnung")).strip()
	if expected_wohnung and not _doctype_has_field("Journal Entry Account", "wohnung"):
		frappe.throw(
			_(
				"Das Pflichtfeld Wohnung fehlt auf Journal Entry Account. "
				"Bitte die Custom-Field-Einrichtung reparieren."
			)
		)
	if cstr(_dict_value(row, "wohnung")).strip() != expected_wohnung:
		frappe.throw(
			_("{0}: Wohnung muss exakt {1} sein.").format(
				label,
				expected_wohnung or _("leer"),
			)
		)


def validate_hv_writeoff_journal_entry_before_submit(doc, method=None) -> None:
	"""Revalidate app-created write-off drafts under a current invoice row lock."""
	invoice_name = _get_owned_hv_writeoff_invoice(doc)
	if not invoice_name:
		return

	accounts = list(doc.get("accounts") or [])
	if len(accounts) != 2:
		frappe.throw(
			_(
				"HV-Abschreibung {0} muss exakt eine Aufwands- und eine "
				"Forderungszeile enthalten."
			).format(invoice_name)
		)

	debit_rows = [
		row
		for row in accounts
		if _money_cents(_dict_value(row, "debit_in_account_currency")) > Decimal("0.00")
		or _money_cents(_dict_value(row, "debit")) > Decimal("0.00")
	]
	credit_rows = [
		row
		for row in accounts
		if _money_cents(_dict_value(row, "credit_in_account_currency")) > Decimal("0.00")
		or _money_cents(_dict_value(row, "credit")) > Decimal("0.00")
	]
	if len(debit_rows) != 1 or len(credit_rows) != 1 or debit_rows[0] is credit_rows[0]:
		frappe.throw(
			_(
				"HV-Abschreibung {0} muss exakt eine Debit- und eine Credit-Zeile enthalten."
			).format(invoice_name)
		)
	debit_row = debit_rows[0]
	credit_row = credit_rows[0]
	if (
		_money_cents(_dict_value(debit_row, "credit_in_account_currency")) != Decimal("0.00")
		or _money_cents(_dict_value(debit_row, "credit")) != Decimal("0.00")
		or _money_cents(_dict_value(credit_row, "debit_in_account_currency")) != Decimal("0.00")
		or _money_cents(_dict_value(credit_row, "debit")) != Decimal("0.00")
	):
		frappe.throw(_("HV-Abschreibung enthält eine gemischte Debit-/Credit-Zeile."))

	writeoff_account = cstr(_dict_value(debit_row, "account")).strip()
	entry = get_locked_sales_invoice_writeoff_entry(
		invoice_name,
		writeoff_account=writeoff_account,
	)
	if cstr(_dict_value(doc, "company")).strip() != entry["company"]:
		frappe.throw(
			_(
				"Journal Entry und Sales Invoice {0} gehören nicht zur selben Firma."
			).format(invoice_name)
		)
	if cint(_dict_value(doc, "multi_currency")):
		frappe.throw(_("HV-Abschreibungen in Fremdwährung sind nicht erlaubt."))
	expected_amount = _money_cents(entry["amount"])
	debit_amount = _money_cents(_dict_value(debit_row, "debit_in_account_currency"))
	credit_amount = _money_cents(_dict_value(credit_row, "credit_in_account_currency"))
	if (
		debit_amount != expected_amount
		or credit_amount != expected_amount
		or debit_amount != credit_amount
	):
		frappe.throw(
			_(
				"Der aktuelle OP von Sales Invoice {0} beträgt {1}; "
				"der Journal Entry ist veraltet oder falsch."
			).format(invoice_name, expected_amount)
		)

	for row, amount, label, base_fieldname in (
		(debit_row, debit_amount, _("Aufwandszeile"), "debit"),
		(credit_row, credit_amount, _("Forderungszeile"), "credit"),
	):
		base_amount = _money_cents(_dict_value(row, base_fieldname))
		if base_amount != amount:
			frappe.throw(
				_("{0}: Basis- und Kontowährungsbetrag stimmen nicht überein.").format(
					label
				)
			)
		if _exact_decimal(_dict_value(row, "exchange_rate")) != Decimal("1"):
			frappe.throw(
				_("{0}: Fremdwährungskurs ist in diesem Workflow nicht erlaubt.").format(
					label
				)
			)
		_validate_writeoff_line_dimensions(row, entry, label=label)

	if (
		cstr(_dict_value(credit_row, "account")).strip() != entry["receivable_account"]
		or cstr(_dict_value(credit_row, "party_type")).strip() != "Customer"
		or cstr(_dict_value(credit_row, "party")).strip() != entry["customer"]
		or cstr(_dict_value(credit_row, "reference_type")).strip() != "Sales Invoice"
		or cstr(_dict_value(credit_row, "reference_name")).strip() != invoice_name
	):
		frappe.throw(
			_("Die Forderungszeile der HV-Abschreibung passt nicht zur Sales Invoice {0}.").format(
				invoice_name
			)
		)
	if any(
		cstr(_dict_value(debit_row, fieldname)).strip()
		for fieldname in ("party_type", "party", "reference_type", "reference_name")
	):
		frappe.throw(_("Die Aufwandszeile der HV-Abschreibung darf keine Belegreferenz tragen."))


def ensure_writeoff_account_for_company(
	company: str,
	*,
	set_as_default: bool = True,
) -> str:
	"""Ensure the default tenant receivables write-off expense account exists."""
	if not company:
		frappe.throw(_("Bitte eine Firma angeben."))

	if not frappe.db.exists("Company", company):
		frappe.throw(_("Firma {0} wurde nicht gefunden.").format(company))

	account = _find_existing_writeoff_account(company)
	if not account:
		account = _create_writeoff_account(company)

	if set_as_default:
		settings = frappe.get_single("Hausverwaltung Einstellungen")
		if getattr(settings, "abschreibungskonto_forderungen", None) != account:
			settings.abschreibungskonto_forderungen = account
			settings.save(ignore_permissions=True)

	return account


def _find_existing_writeoff_account(company: str) -> str | None:
	return frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_name": DEFAULT_WRITE_OFF_ACCOUNT_NAME,
			"is_group": 0,
		},
		"name",
	)


def _create_writeoff_account(company: str) -> str:
	parent_account = _get_writeoff_parent_account(company)
	default_currency = frappe.db.get_value("Company", company, "default_currency")
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": DEFAULT_WRITE_OFF_ACCOUNT_NAME,
			"company": company,
			"is_group": 0,
			"root_type": "Expense",
			"report_type": "Profit and Loss",
			"parent_account": parent_account,
			"account_currency": default_currency,
		}
	)
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	return doc.name


def _get_writeoff_parent_account(company: str) -> str:
	for account_name in ("Nicht Umlagefähig", "Sonstige betriebliche Aufwendungen"):
		parent = frappe.db.get_value(
			"Account",
			{
				"company": company,
				"account_name": account_name,
				"is_group": 1,
				"root_type": "Expense",
			},
			"name",
		)
		if parent:
			return parent

	parent = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"is_group": 1,
			"root_type": "Expense",
			"parent_account": ["in", ["", None]],
		},
		"name",
	)
	if parent:
		return parent

	frappe.throw(_("Für Firma {0} wurde kein Aufwandsgruppen-Konto gefunden.").format(company))
