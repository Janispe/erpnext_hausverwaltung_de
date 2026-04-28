from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


WRITTEN_OFF_STATUS = "Abgeschrieben"
PARTLY_PAID_AND_WRITTEN_OFF_STATUS = "Teilweise bezahlt und abgeschrieben"
OUTSTANDING_TOLERANCE = 0.01
DEFAULT_WRITE_OFF_ACCOUNT_NAME = "Abschreibungen Mieterforderungen"


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
		je.voucher_type = "Journal Entry"
		je.company = entry["company"]
		je.posting_date = posting_date
		je.remark = _("Abschreibung Sales Invoice {0}").format(entry["sales_invoice"])

		je.append(
			"accounts",
			{
				"account": entry["writeoff_account"],
				"debit_in_account_currency": entry["amount"],
				"cost_center": entry["cost_center"],
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

	entries = []
	for invoice_name in names:
		entries.append(_validate_sales_invoice_for_writeoff(invoice_name))
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


def _validate_sales_invoice_for_writeoff(invoice_name: str) -> dict[str, Any]:
	invoice = frappe.db.get_value(
		"Sales Invoice",
		invoice_name,
		[
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
		],
		as_dict=True,
	)
	if not invoice:
		frappe.throw(_("Sales Invoice {0} wurde nicht gefunden.").format(invoice_name))

	if int(invoice.get("docstatus") or 0) != 1:
		frappe.throw(_("Sales Invoice {0} ist nicht eingereicht.").format(invoice_name))
	if int(invoice.get("is_return") or 0):
		frappe.throw(_("Sales Invoice {0} ist eine Return/Credit Note und kann nicht abgeschrieben werden.").format(invoice_name))
	if invoice.get("status") in (WRITTEN_OFF_STATUS, PARTLY_PAID_AND_WRITTEN_OFF_STATUS):
		frappe.throw(_("Sales Invoice {0} ist bereits abgeschrieben.").format(invoice_name))

	amount = flt(invoice.get("outstanding_amount"))
	if amount <= OUTSTANDING_TOLERANCE:
		frappe.throw(_("Sales Invoice {0} hat keinen offenen Forderungsbetrag.").format(invoice_name))

	if not invoice.get("customer"):
		frappe.throw(_("Sales Invoice {0} hat keinen Kunden.").format(invoice_name))
	if not invoice.get("debit_to"):
		frappe.throw(_("Sales Invoice {0} hat kein Forderungskonto.").format(invoice_name))
	if not invoice.get("company"):
		frappe.throw(_("Sales Invoice {0} hat keine Firma.").format(invoice_name))

	_validate_receivable_account(invoice.get("debit_to"), invoice.get("company"), invoice_name)
	cost_center = _get_writeoff_cost_center(invoice)
	writeoff_account = _get_writeoff_account(invoice.get("company"))

	return {
		"sales_invoice": invoice_name,
		"customer": invoice.get("customer"),
		"company": invoice.get("company"),
		"receivable_account": invoice.get("debit_to"),
		"writeoff_account": writeoff_account,
		"cost_center": cost_center,
		"amount": amount,
		"currency": invoice.get("currency"),
	}


def _validate_receivable_account(account: str, company: str, invoice_name: str) -> None:
	account_details = frappe.db.get_value(
		"Account",
		account,
		["account_type", "company", "is_group", "disabled"],
		as_dict=True,
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


def _get_writeoff_account(company: str) -> str:
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

	account_details = frappe.db.get_value(
		"Account",
		account,
		["root_type", "company", "is_group", "disabled"],
		as_dict=True,
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

	return account


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
