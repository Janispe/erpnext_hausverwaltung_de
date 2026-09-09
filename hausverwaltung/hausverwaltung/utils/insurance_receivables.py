"""Insurance receivables use an asset account and native Journal Entry references.

The insurer remains a Supplier/contact in this app; Customers belong to leases.
No tenant receivable is used for the insurer's debt.
"""

from __future__ import annotations

import math

import frappe
from frappe.utils import flt, getdate

CLAIM = "Versicherungsforderung"
RECEIPT = "Versicherungseingang"


def _account(name, company, root):
	if not name:
		frappe.throw("Bitte Forderungs- und Ertragskonto der Versicherung auswählen.")
	a = frappe.get_doc("Account", name)
	currency = frappe.db.get_value("Company", company, "default_currency")
	if (
		a.company != company
		or a.root_type != root
		or a.is_group
		or a.disabled
		or a.account_type in {"Receivable", "Payable", "Bank", "Cash"}
		or a.account_currency != currency
	):
		frappe.throw(
			"Versicherungskonto: aktives Sachkonto der richtigen Kontoart und Company-Währung erforderlich."
		)
	return a.name


def _scope(case):
	case._apply_scope()
	cc = frappe.db.get_value("Immobilie", case.immobilie, "kostenstelle")
	if not cc or frappe.db.get_value("Cost Center", cc, "company") != case.company:
		frappe.throw("Die Immobilie benötigt eine Kostenstelle dieser Company.")
	if not case.versicherer:
		frappe.throw("Bitte den Versicherer auswählen.")
	return cc


def _claim_legs(doc):
	if len(doc.accounts) != 2 or doc.multi_currency:
		frappe.throw("Die Versicherungsforderung benötigt genau zwei Zeilen in Company-Währung.")
	debits = [r for r in doc.accounts if flt(r.debit_in_account_currency) > 0]
	credits = [r for r in doc.accounts if flt(r.credit_in_account_currency) > 0]
	if len(debits) != 1 or len(credits) != 1 or debits[0] == credits[0]:
		frappe.throw("Die Versicherungsforderung benötigt eine Soll- und eine Habenzeile.")
	return debits[0], credits[0]


def claim_balance(name, *, for_update=False, exclude_receipt=None):
	doc = frappe.get_doc("Journal Entry", name, for_update=for_update)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.get("custom_versicherungsbuchung") != CLAIM:
		frappe.throw("Bitte eine eingereichte Versicherungsforderung auswählen.")
	debit, credit = _claim_legs(doc)
	# Native references provide a voucher-specific balance even on a non-party asset account.
	paid = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(a.credit_in_account_currency - a.debit_in_account_currency), 0)
		FROM `tabJournal Entry Account` a JOIN `tabJournal Entry` j ON j.name=a.parent
		WHERE j.docstatus=1 AND j.company=%s AND a.account=%s
		AND a.reference_type='Journal Entry' AND a.reference_name=%s AND j.name != %s
	""",
		(doc.company, debit.account, name, exclude_receipt or ""),
	)[0][0]
	return frappe._dict(
		name=name,
		reference_doctype="Journal Entry",
		company=doc.company,
		versicherungsfall=doc.custom_versicherungsfall,
		account=debit.account,
		income_account=credit.account,
		cost_center=debit.cost_center,
		posting_date=doc.posting_date,
		amount=flt(debit.debit_in_account_currency),
		outstanding_amount=flt(debit.debit_in_account_currency) - flt(paid),
		remarks=doc.user_remark,
	)


@frappe.whitelist()
def create_insurance_claim(name, posting_date):
	case = frappe.get_doc("Versicherungsfall", name, for_update=True)
	case.check_permission("write")
	cc = _scope(case)
	amount = flt(case.bewilligter_betrag)
	if (
		case.status in {"Abgeschlossen", "Abgelehnt"}
		or not posting_date
		or not math.isfinite(amount)
		or amount <= 0
	):
		frappe.throw("Bitte einen offenen Fall, Buchungsdatum und positiven bewilligten Betrag angeben.")
	if not case.bewilligungsnachweis or not case.schadennummer:
		frappe.throw("Bitte Regulierungszusage und Schadennummer als Grundlage der Forderung hinterlegen.")
	if frappe.db.exists(
		"Journal Entry",
		{"custom_versicherungsfall": name, "custom_versicherungsbuchung": CLAIM, "docstatus": ["!=", 2]},
	):
		frappe.throw("Eine Versicherungsforderung besteht bereits. Bitte den vorhandenen Beleg verwenden.")
	if flt(case.versicherung_erhalten) > 0:
		frappe.throw(
			"Ein Versicherungseingang ist bereits erfasst. Diesen zuerst prüfen, damit kein doppelter Ertrag entsteht."
		)
	asset = _account(case.versicherungsforderungskonto, case.company, "Asset")
	income = _account(case.versicherungsertragskonto, case.company, "Income")
	je = frappe.get_doc(
		dict(
			doctype="Journal Entry",
			company=case.company,
			posting_date=getdate(posting_date),
			custom_versicherungsfall=name,
			custom_versicherungsbuchung=CLAIM,
			user_remark=f"Versicherungsforderung {name}, {case.versicherer}, Schaden {case.schadennummer}",
			accounts=[
				dict(account=asset, debit_in_account_currency=amount, cost_center=cc),
				dict(account=income, credit_in_account_currency=amount, cost_center=cc),
			],
		)
	)
	je.insert()
	case.append("belege", dict(belegart=CLAIM, referenz_doctype="Journal Entry", referenz=je.name))
	case.save()
	return {"doctype": "Journal Entry", "name": je.name}


def validate_journal(doc):
	role = doc.get("custom_versicherungsbuchung")
	if role not in {CLAIM, RECEIPT}:
		return
	case = frappe.get_doc("Versicherungsfall", doc.custom_versicherungsfall, for_update=True)
	cc = _scope(case)
	if doc.company != case.company or case.status in {"Abgeschlossen", "Abgelehnt"}:
		frappe.throw("Versicherungsbuchung benötigt einen offenen Fall derselben Company.")
	debit, credit = _claim_legs(doc)
	currency = frappe.db.get_value("Company", case.company, "default_currency")
	for r in doc.accounts:
		if (
			r.party
			or r.party_type
			or r.cost_center != cc
			or r.account_currency != currency
			or flt(r.exchange_rate) != 1
		):
			frappe.throw(
				"Versicherungsbuchungen benötigen Sachkonten ohne Mieter-Party in der Kostenstelle und Währung des Falls."
			)
	if role == CLAIM:
		if (
			debit.account != _account(case.versicherungsforderungskonto, case.company, "Asset")
			or credit.account != _account(case.versicherungsertragskonto, case.company, "Income")
			or flt(debit.debit_in_account_currency) != flt(case.bewilligter_betrag)
			or not case.bewilligungsnachweis
			or not case.schadennummer
			or any(r.reference_type or r.reference_name for r in doc.accounts)
		):
			frappe.throw(
				"Forderung stimmt nicht mit Bewilligung, Betrag oder Konten des Versicherungsfalls überein."
			)
		if frappe.db.exists(
			"Journal Entry",
			{
				"custom_versicherungsfall": case.name,
				"custom_versicherungsbuchung": CLAIM,
				"docstatus": ["!=", 2],
				"name": ["!=", doc.name],
			},
		):
			frappe.throw("Für diesen Fall besteht bereits eine Versicherungsforderung.")
	else:
		if credit.reference_type != "Journal Entry" or not credit.reference_name:
			frappe.throw("Der Versicherungseingang muss die gebuchte Versicherungsforderung ausgleichen.")
		claim = claim_balance(credit.reference_name, for_update=True, exclude_receipt=doc.name)
		if (
			claim.versicherungsfall != case.name
			or credit.account != claim.account
			or getdate(doc.posting_date) < getdate(claim.posting_date)
			or flt(credit.credit_in_account_currency) > claim.outstanding_amount + 0.001
			or frappe.db.get_value("Account", debit.account, "account_type") != "Bank"
			or debit.reference_type
			or debit.reference_name
		):
			frappe.throw(
				"Versicherungseingang passt nicht zur Forderung oder übersteigt deren offenen Betrag."
			)


def validate_case(case):
	"""Freeze accounting identity after a claim exists and require real receipt references."""
	claims = frappe.get_all(
		"Journal Entry",
		filters={
			"custom_versicherungsfall": case.name,
			"custom_versicherungsbuchung": CLAIM,
			"docstatus": ["!=", 2],
		},
		fields=["name", "docstatus"],
	)
	for info in claims:
		doc = frappe.get_doc("Journal Entry", info.name)
		debit, credit = _claim_legs(doc)
		cc = frappe.db.get_value("Immobilie", case.immobilie, "kostenstelle")
		if (
			doc.company != case.company
			or debit.account != case.versicherungsforderungskonto
			or credit.account != case.versicherungsertragskonto
			or debit.cost_center != cc
			or flt(debit.debit_in_account_currency) != flt(case.bewilligter_betrag)
		):
			frappe.throw(
				"Bei bestehender Versicherungsforderung Betrag, Company, Immobilie und Konten nicht ändern; zuerst den Buchungsbeleg korrigieren."
			)
		if not any(r.belegart == CLAIM and r.referenz == doc.name for r in case.belege):
			frappe.throw("Die gebuchte Versicherungsforderung darf nicht aus dem Fall entfernt werden.")
	for receipt in frappe.get_all(
		"Journal Entry",
		filters={
			"custom_versicherungsfall": case.name,
			"custom_versicherungsbuchung": RECEIPT,
			"docstatus": 1,
		},
		fields=["name"],
	):
		if not any(
			r.belegart == RECEIPT and r.referenz_doctype == "Journal Entry" and r.referenz == receipt.name
			for r in case.belege
		):
			frappe.throw("Ein gebuchter Versicherungseingang darf nicht aus dem Fall entfernt werden.")
	old = case.get_doc_before_save()
	if claims and old and (old.versicherer != case.versicherer or old.immobilie != case.immobilie):
		frappe.throw("Der Versicherer einer bestehenden Forderung darf nicht geändert werden.")
	for row in case.belege:
		if row.belegart not in {CLAIM, RECEIPT} or row.referenz_doctype != "Journal Entry":
			continue
		doc = frappe.get_doc("Journal Entry", row.referenz)
		if doc.docstatus == 2:
			continue
		if doc.get("custom_versicherungsbuchung") in {CLAIM, RECEIPT}:
			if doc.custom_versicherungsfall != case.name or doc.custom_versicherungsbuchung != row.belegart:
				frappe.throw("Versicherungsbeleg gehört zu einem anderen Fall oder einer anderen Belegrolle.")
			if abs(flt(row.betrag) - flt(doc.total_debit)) > 0.001:
				frappe.throw("Der Fall muss den vollständigen Betrag seines Versicherungsbelegs enthalten.")
		elif claims and row.belegart == RECEIPT:
			frappe.throw(
				"Bei gebuchter Versicherungsforderung den Eingang über deren Zuordnung erfassen, damit die Forderung ausgeglichen wird."
			)


def get_candidates(supplier, company, cost_center):
	if not frappe.get_meta("Journal Entry").has_field("custom_versicherungsbuchung"):
		return []
	rows = frappe.get_list(
		"Versicherungsfall",
		filters={
			"versicherer": supplier,
			"company": company,
			"status": ["not in", ["Abgeschlossen", "Abgelehnt"]],
		},
		fields=["name", "immobilie"],
	)
	out = []
	for case in rows:
		if frappe.db.get_value("Immobilie", case.immobilie, "kostenstelle") != cost_center:
			continue
		for j in frappe.get_list(
			"Journal Entry",
			filters={
				"custom_versicherungsfall": case.name,
				"custom_versicherungsbuchung": CLAIM,
				"docstatus": 1,
			},
			fields=["name"],
		):
			balance = claim_balance(j.name)
			if balance.outstanding_amount > 0.001:
				balance.allocatable_amount = balance.outstanding_amount
				out.append(balance)
	return out


def create_receipt(bt, items):
	from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
		_bank_transaction_shape,
		_resolve_company_and_bank_account,
		_resolve_expected_cost_center_for_bt,
	)

	shape = _bank_transaction_shape(bt)
	if shape.direction != "in" or bt.party_type != "Supplier" or not bt.party:
		frappe.throw("Versicherungseingang benötigt einen Eingang vom Versicherer (Supplier).")
	if len(items) != 1 or items[0].get("reference_doctype") != "Journal Entry":
		frappe.throw("Bitte diesen Bankeingang genau einer Versicherungsforderung zuordnen.")
	name = items[0].get("name")
	case_name = frappe.db.get_value("Journal Entry", name, "custom_versicherungsfall")
	case = frappe.get_doc("Versicherungsfall", case_name, for_update=True)
	case.check_permission("write")
	company, bank = _resolve_company_and_bank_account(bt)
	cc = _resolve_expected_cost_center_for_bt(bt, require_property=True, for_update=True)
	claim = claim_balance(name, for_update=True)
	amount = flt(items[0].get("allocated_amount"))
	currency = frappe.db.get_value("Company", company, "default_currency")
	if (
		case.versicherer != bt.party
		or case.company != company
		or claim.cost_center != cc
		or frappe.db.get_value("Account", bank.account, "account_currency") != currency
		or (bt.get("currency") and bt.currency != currency)
		or not math.isfinite(amount)
		or amount <= 0
		or abs(amount - shape.amount) > 0.001
		or amount > claim.outstanding_amount + 0.001
	):
		frappe.throw(
			"Eingang, Versicherer, Company, Immobilie oder Betrag passen nicht zur offenen Forderung."
		)
	je = frappe.get_doc(
		dict(
			doctype="Journal Entry",
			voucher_type="Bank Entry",
			company=company,
			posting_date=bt.date,
			custom_versicherungsfall=case.name,
			custom_versicherungsbuchung=RECEIPT,
			cheque_no=bt.reference_number or bt.name,
			cheque_date=bt.date,
			user_remark=f"Versicherungseingang {case.name}: {bt.description or ''}",
			accounts=[
				dict(account=bank.account, debit_in_account_currency=amount, cost_center=cc),
				dict(
					account=claim.account,
					credit_in_account_currency=amount,
					cost_center=cc,
					reference_type="Journal Entry",
					reference_name=claim.name,
				),
			],
		)
	)
	je.insert()
	je.submit()
	return je


def reclassify_cash_entries(entries, company, from_date, to_date, bank_accounts, cost_centers=None):
	"""Cash-basis account attribution, without posting a second income/expense.

	Recognized claims have no bank leg and are excluded. On settlement use the
	original claim's income/expense account, at the settlement date and amount.
	"""
	if not frappe.get_meta("Journal Entry").has_field("custom_versicherungsbuchung"):
		return entries
	params = {
		"company": company,
		"banks": tuple(sorted(bank_accounts)),
		"from_date": from_date or "1900-01-01",
		"to_date": to_date or "9999-12-31",
	}
	cc_condition = ""
	if cost_centers:
		cc_condition = " AND gle.cost_center IN %(cost_centers)s"
		params["cost_centers"] = tuple(cost_centers)
	cash = frappe.db.sql(
		"""
		SELECT DISTINCT gle.voucher_type, gle.voucher_no FROM `tabGL Entry` gle
		WHERE gle.company=%(company)s AND gle.is_cancelled=0 AND gle.docstatus=1
		AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		AND gle.account IN %(banks)s
	"""
		+ cc_condition,
		params,
		as_dict=True,
	)
	je_names = tuple(r.voucher_no for r in cash if r.voucher_type == "Journal Entry")
	pe_names = tuple(r.voucher_no for r in cash if r.voucher_type == "Payment Entry")
	mapped = []
	if je_names:
		mapped.extend(
			frappe.db.sql(
				"""
			SELECT j.name AS voucher_no, 'Journal Entry' AS voucher_type, j.posting_date,
			j.user_remark AS remarks, a.account AS source_account, income.account,
			a.credit_in_account_currency AS income, 0 AS expense, 'Income' AS root_type
			FROM `tabJournal Entry` j
			JOIN `tabJournal Entry Account` a ON a.parent=j.name AND a.reference_type='Journal Entry'
			JOIN `tabJournal Entry` claim ON claim.name=a.reference_name AND claim.docstatus=1
			JOIN `tabJournal Entry Account` income ON income.parent=claim.name AND income.credit>0
			WHERE j.name IN %s AND j.docstatus=1 AND j.custom_versicherungsbuchung='Versicherungseingang'
			AND claim.custom_versicherungsbuchung='Versicherungsforderung'
		""",
				(je_names,),
				as_dict=True,
			)
		)
	if pe_names:
		mapped.extend(
			frappe.db.sql(
				"""
			SELECT pe.name AS voucher_no, 'Payment Entry' AS voucher_type, pe.posting_date,
			pe.remarks, pe.paid_to AS source_account, expense.account,
			0 AS income, -ref.allocated_amount AS expense, acc.root_type
			FROM `tabPayment Entry` pe
			JOIN `tabPayment Entry Reference` ref ON ref.parent=pe.name AND ref.reference_doctype='Journal Entry' AND ref.allocated_amount<0
			JOIN `tabJournal Entry` claim ON claim.name=ref.reference_name AND claim.docstatus=1
			JOIN `tabVersicherungsfall Beleg` link ON link.referenz=claim.name AND link.referenz_doctype='Journal Entry' AND link.belegart='Mietererstattungsanspruch'
			JOIN `tabJournal Entry Account` expense ON expense.parent=claim.name AND expense.debit>0
			JOIN `tabAccount` acc ON acc.name=expense.account
			WHERE pe.name IN %s AND pe.docstatus=1 AND pe.party_type='Customer' AND pe.payment_type='Pay'
			AND claim.custom_versicherungsfall=link.parent
		""",
				(pe_names,),
				as_dict=True,
			)
		)
	return _replace_cash_accounts(entries, mapped)


def _replace_cash_accounts(entries, mapped):
	entries = [dict(e) for e in entries]
	for mapping in mapped:
		# The old report may have attributed this portion to the intermediary
		# asset account / generic tenant credit bucket. Remove exactly that
		# portion; invoice allocations on a mixed voucher remain untouched.
		field = "income" if flt(mapping.get("income")) else "expense"
		remaining = flt(mapping.get(field))
		for entry in entries:
			if (
				entry.get("voucher_type") == mapping.get("voucher_type")
				and entry.get("voucher_no") == mapping.get("voucher_no")
				and entry.get("account") in {mapping.get("source_account"), "Guthaben Mieter"}
			):
				used = min(max(flt(entry.get(field)), 0), remaining)
				entry[field] = flt(entry.get(field)) - used
				remaining -= used
		item = dict(mapping)
		item.pop("source_account", None)
		entries.append(item)
	return [e for e in entries if abs(flt(e.get("income"))) > 0.0001 or abs(flt(e.get("expense"))) > 0.0001]


def prevent_claim_cancel(doc, method=None):
	if doc.get("custom_versicherungsbuchung") != CLAIM:
		return
	frappe.get_doc("Versicherungsfall", doc.custom_versicherungsfall, for_update=True)
	if frappe.db.sql(
		"""SELECT a.name FROM `tabJournal Entry Account` a
		JOIN `tabJournal Entry` j ON j.name=a.parent
		WHERE j.docstatus=1 AND a.reference_type='Journal Entry' AND a.reference_name=%s LIMIT 1
	""",
		(doc.name,),
	):
		frappe.throw(
			"Die Versicherungsforderung ist bereits durch einen Eingang ausgeglichen. Bitte zuerst die zugeordneten Eingänge stornieren."
		)
