"""Explicit refunds of tenant credits, including reimbursement Journal Entries."""

from __future__ import annotations

import math

import frappe
from frappe.utils import flt, getdate


def tenant_contract(customer, *, for_update=False):
	rows = frappe.db.sql(
		"SELECT name, kunde, wohnung FROM `tabMietvertrag` WHERE kunde=%s AND docstatus != 2 "
		"ORDER BY name LIMIT 2" + (" FOR UPDATE" if for_update else ""),
		(customer,),
		as_dict=True,
	)
	if len(rows) != 1 or not rows[0].wohnung:
		frappe.throw("Der Mieter benötigt genau einen eindeutig zugeordneten Mietvertrag mit Wohnung.")
	return rows[0]


def journal_credit(name, customer, company, *, for_update=False):
	"""Validate the actual receivable leg and use current ledger outstanding."""
	doc = frappe.get_doc("Journal Entry", name, for_update=for_update)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.company != company or doc.multi_currency:
		frappe.throw(
			"Das Erstattungsguthaben muss eingereicht sein und zur Company in deren Währung gehören."
		)
	party_rows = [r for r in doc.accounts if r.party_type or r.party]
	if len(party_rows) != 1 or party_rows[0].party_type != "Customer" or party_rows[0].party != customer:
		frappe.throw("Der Erstattungsbeleg muss genau einen Debitorenposten für diesen Mieter enthalten.")
	row = party_rows[0]
	if frappe.db.get_value("Account", row.account, "account_type") != "Receivable":
		frappe.throw("Der Erstattungsbeleg muss über ein Debitorenkonto gebucht sein.")
	if row.reference_type or row.reference_name or flt(row.credit) <= 0 or flt(row.debit):
		frappe.throw("Der Journal Entry ist kein eigenständiger Erstattungsanspruch des Mieters.")
	currency = frappe.db.get_value("Company", company, "default_currency")
	if row.account_currency != currency or flt(row.exchange_rate) != 1:
		frappe.throw("Das Erstattungsguthaben muss in der Company-Währung gebucht sein.")
	outstanding = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(amount_in_account_currency), 0)
		FROM `tabPayment Ledger Entry`
		WHERE company=%s AND party_type='Customer' AND party=%s AND account=%s
		AND against_voucher_type='Journal Entry' AND against_voucher_no=%s AND delinked=0
	""",
		(company, customer, row.account, name),
	)[0][0]
	return frappe._dict(
		name=name,
		reference_doctype="Journal Entry",
		posting_date=doc.posting_date,
		outstanding_amount=flt(outstanding),
		allocatable_amount=max(-flt(outstanding), 0),
		remarks=doc.user_remark,
		account=row.account,
		cost_center=row.cost_center,
		versicherungsfall=doc.get("custom_versicherungsfall"),
	)


def get_journal_refund_candidates(customer, company):
	tenant_contract(customer)
	rows = frappe.db.sql(
		"""
		SELECT against_voucher_no AS name FROM `tabPayment Ledger Entry`
		WHERE company=%s AND party_type='Customer' AND party=%s
		AND against_voucher_type='Journal Entry' AND delinked=0
		GROUP BY against_voucher_no HAVING SUM(amount_in_account_currency) < -0.01
		ORDER BY MIN(posting_date), against_voucher_no LIMIT 200
	""",
		(company, customer),
		as_dict=True,
	)
	candidates = []
	for row in rows:
		try:
			credit = journal_credit(row.name, customer, company)
		except (frappe.ValidationError, frappe.PermissionError):
			continue
		if credit.allocatable_amount > 0.01:
			candidates.append(credit)
	return candidates


def create_refund_payment(bt, items):
	"""Create and submit one fully allocated refund, locking every source first."""
	from erpnext.accounts.party import get_party_account

	from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
		_bank_transaction_shape,
		_customer_invoice_identity,
		_get_company_currency,
		_lock_and_validate_invoices,
		_require_company_currency_account,
		_resolve_company_and_bank_account,
		_resolve_expected_cost_center_for_bt,
	)

	if bt.party_type != "Customer" or not bt.party or _bank_transaction_shape(bt).direction != "out":
		frappe.throw("Ein Erstattungsguthaben kann nur einem Mieterausgang zugeordnet werden.")
	contract = tenant_contract(bt.party, for_update=True)
	company, bank = _resolve_company_and_bank_account(bt)
	currency = _get_company_currency(company)
	cc = _resolve_expected_cost_center_for_bt(bt, require_property=True, for_update=True)
	property_name = frappe.db.get_value("Wohnung", contract.wohnung, "immobilie")
	if frappe.db.get_value("Immobilie", property_name, "kostenstelle") != cc:
		frappe.throw("Bankkonto und Mietvertrag gehören nicht zur gleichen Immobilie.")
	party_account = get_party_account("Customer", bt.party, company)
	_require_company_currency_account(
		party_account, company=company, company_currency=currency, label="Mieterdebitor"
	)
	seen, references, cases = set(), [], set()
	for item in sorted(
		items, key=lambda i: (i.get("reference_doctype") or "Sales Invoice", i.get("name") or "")
	):
		dt = item.get("reference_doctype") or "Sales Invoice"
		name = item.get("name")
		if dt not in {"Journal Entry", "Sales Invoice"} or not name or (dt, name) in seen:
			frappe.throw("Die Guthabenauswahl enthält einen ungültigen oder doppelten Beleg.")
		seen.add((dt, name))
		if dt == "Journal Entry":
			credit = journal_credit(name, bt.party, company, for_update=True)
			if credit.account != party_account or credit.cost_center != cc:
				frappe.throw(
					"Erstattungsguthaben und Auszahlung müssen dasselbe Debitorenkonto und dieselbe Kostenstelle verwenden."
				)
			if credit.versicherungsfall:
				cases.add(credit.versicherungsfall)
		else:
			credit = _lock_and_validate_invoices(
				invoices=[item],
				invoice_doctype=dt,
				company=company,
				party=bt.party,
				company_currency=currency,
				credit_notes=True,
			)[0]
			if _customer_invoice_identity(credit, bt.party, for_update=True) != (
				contract.name,
				contract.wohnung,
			):
				frappe.throw("Die Gutschrift passt nicht zum Mietvertrag.")
			if frappe.db.get_value(dt, name, "debit_to") != party_account:
				frappe.throw("Die Gutschrift verwendet ein anderes Debitorenkonto.")
		if getdate(credit.posting_date) > getdate(bt.date):
			frappe.throw("Der Erstattungsanspruch darf nicht nach der Auszahlung gebucht sein.")
		available = -flt(credit.outstanding_amount)
		amount = available if item.get("allocated_amount") is None else flt(item.get("allocated_amount"))
		if not math.isfinite(amount) or amount <= 0 or amount > available + 0.001:
			frappe.throw("Die Zuweisung übersteigt das aktuell offene Erstattungsguthaben oder ist ungültig.")
		references.append(dict(reference_doctype=dt, reference_name=name, allocated_amount=-amount))
	amount = _bank_transaction_shape(bt).amount
	if not references or abs(sum(-r["allocated_amount"] for r in references) - amount) > 0.001:
		frappe.throw("Die Auszahlung muss vollständig offenen Guthaben zugeordnet sein.")
	pe = frappe.get_doc(
		dict(
			doctype="Payment Entry",
			payment_type="Pay",
			company=company,
			posting_date=bt.date,
			party_type="Customer",
			party=bt.party,
			bank_account=bt.bank_account,
			paid_from=bank.account,
			paid_to=party_account,
			paid_amount=amount,
			received_amount=amount,
			reference_no=bt.reference_number or bt.name,
			reference_date=bt.date,
			cost_center=cc,
			custom_remarks=1,
			remarks=bt.description or "Auszahlung Erstattung",
			references=references,
		)
	)
	pe.insert()
	pe.submit()
	return pe
