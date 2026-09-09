"""End-to-end insurance/tenant cash-basis checks on the disposable fixture DB only."""

import os

import frappe
from frappe.utils import flt


def run():
	assert frappe.conf.db_name == "hv_insurance_test_20260909"
	from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
		get_open_invoices_for_row,
		manually_reconcile_row,
	)
	from hausverwaltung.hausverwaltung.doctype.versicherungsfall.versicherungsfall import create_tenant_claim
	from hausverwaltung.hausverwaltung.report.euer.euer import get_data
	from hausverwaltung.hausverwaltung.utils.insurance_receivables import (
		claim_balance,
		create_insurance_claim,
	)
	from hausverwaltung.hausverwaltung.utils.tenant_refunds import create_refund_payment

	def reject(fn):
		try:
			fn()
		except frappe.ValidationError:
			frappe.clear_messages()
		else:
			raise AssertionError("Expected validation failure")

	def account(template, title):
		a = frappe.copy_doc(frappe.get_doc("Account", template))
		a.account_name = title
		a.account_number = None
		a.insert()
		return a.name

	asset = account("1400 - Nachz. alter Mieter - HP", "TEST Versicherungsforderungen")
	income = account("4100 - Miete - HP", "TEST Versicherungserstattungen")
	case = frappe.get_doc(
		dict(
			doctype="Versicherungsfall",
			company="Hausverwaltung Peters",
			schadensart="Glas",
			schadendatum="2026-07-01",
			status="Bewilligt",
			beguenstigter="Mieter",
			mietvertrag="W5 | HH | EG rechts | ab: 2022-03-16 - Trujillo Arboleda",
			versicherer="Signal Iduna (Versicherung)",
			schadennummer="TEST-INSURANCE-RECEIVABLE",
			bewilligter_betrag=458.94,
			bewilligungsnachweis="/private/files/test-bewilligung.pdf",
			versicherungsforderungskonto=asset,
			versicherungsertragskonto=income,
			erstattungsart="Auslagenersatz Gebäudereparatur",
			erstattungsbetrag=458.94,
			erstattungskonto="6810 - Instand. Glaser - HP",
			mieterkonto_kategorie="G/N",
			erstattungsbegruendung="TEST Glaserrechnung 266761",
		)
	).insert()
	claim = frappe.get_doc("Journal Entry", create_insurance_claim(case.name, "2026-07-01")["name"])
	assert claim.docstatus == 0
	case.reload()
	assert case.versicherungsforderung_gebucht == 0
	reject(lambda: create_insurance_claim(case.name, "2026-07-01"))
	claim.submit()
	case.reload()
	assert case.versicherungsforderung_gebucht == 458.94 and case.versicherungsforderung_offen == 458.94
	tenant = frappe.get_doc("Journal Entry", create_tenant_claim(case.name, "2026-07-01")["name"])
	tenant.submit()

	def euer(start, end, non_euer=0):
		return get_data(
			frappe._dict(
				company=case.company,
				immobilie=case.immobilie,
				from_date=start,
				to_date=end,
				include_non_euer_accounts=non_euer,
				show_details=1,
			)
		)[0]

	for mode in [0, 1]:
		rows = euer("2026-07-01", "2026-07-01", mode)
		assert not any(r.get("voucher_no") in {claim.name, tenant.name} for r in rows), rows

	def receipt(amount, date):
		bt = frappe.get_doc(
			dict(
				doctype="Bank Transaction",
				company=case.company,
				date=date,
				deposit=amount,
				withdrawal=0,
				currency="EUR",
				party_type="Supplier",
				party=case.versicherer,
				bank_account="Wilhelmshavener - Postbank, Ndl Deutsche Bank",
				description="TEST Versicherungseingang",
			)
		)
		bt.insert()
		bt.submit()
		imp = frappe.get_doc(
			dict(
				doctype="Bankauszug Import",
				bank_account=bt.bank_account,
				csv_file="/private/files/test-insurance.csv",
				rows=[
					dict(
						buchungstag=date,
						betrag=amount,
						richtung="Eingang",
						party_type="Supplier",
						party=case.versicherer,
						bank_transaction=bt.name,
					)
				],
			)
		).insert()
		choices = get_open_invoices_for_row(imp.name, imp.rows[0].name)
		assert choices["allocation_mode"] == "insurance_receipt"
		assert any(x.name == claim.name for x in choices["invoices"])
		res = manually_reconcile_row(
			imp.name,
			imp.rows[0].name,
			frappe.as_json(
				[dict(name=claim.name, reference_doctype="Journal Entry", allocated_amount=amount)]
			),
		)
		bt.reload()
		assert bt.unallocated_amount == 0 and bt.status == "Reconciled"
		return frappe.get_doc("Journal Entry", res["journal_entry"])

	from hausverwaltung.hausverwaltung.utils.insurance_receivables import create_receipt

	incoming = frappe._dict(
		name="TEST-INCOMING",
		company=case.company,
		date="2026-07-17",
		deposit=458.94,
		withdrawal=0,
		currency="EUR",
		party_type="Supplier",
		party=case.versicherer,
		bank_account="Wilhelmshavener - Postbank, Ndl Deutsche Bank",
		description="TEST",
		reference_number="TEST",
	)
	selection = [dict(name=claim.name, reference_doctype="Journal Entry", allocated_amount=458.94)]
	wrong = frappe._dict(incoming)
	wrong.party = "OTHER-INSURER"
	reject(lambda: create_receipt(wrong, selection))
	wrong = frappe._dict(incoming)
	wrong.date = "2026-06-30"
	reject(lambda: create_receipt(wrong, selection))
	wrong = frappe._dict(incoming)
	wrong.currency = "USD"
	reject(lambda: create_receipt(wrong, selection))
	reject(
		lambda: create_receipt(
			incoming, [dict(name=claim.name, reference_doctype="Journal Entry", allocated_amount=200)]
		)
	)
	first = receipt(200, "2026-07-17")
	case.reload()
	assert abs(case.versicherungsforderung_offen - 258.94) < 0.001
	assert abs(claim_balance(claim.name).outstanding_amount - 258.94) < 0.001
	for mode in [0, 1]:
		rows = euer("2026-07-17", "2026-07-17", mode)
		own = [r for r in rows if r.get("voucher_no") == first.name]
		assert len(own) == 1 and own[0]["account"] == income and own[0]["income"] == 200, own
	reject(lambda: create_receipt(incoming, selection))
	second = receipt(258.94, "2026-08-03")
	case.reload()
	assert case.versicherungsforderung_offen == 0 and claim_balance(claim.name).outstanding_amount == 0
	reject(lambda: claim.cancel())
	bt = frappe._dict(
		name="TEST-PAYOUT",
		party_type="Customer",
		party=case.kunde,
		company=case.company,
		date="2026-08-05",
		deposit=0,
		withdrawal=458.94,
		reference_number="TEST",
		description="TEST Glasererstattung",
		bank_account="Wilhelmshavener - Postbank, Ndl Deutsche Bank",
	)
	payment = create_refund_payment(
		bt, [dict(name=tenant.name, reference_doctype="Journal Entry", allocated_amount=458.94)]
	)
	assert payment.unallocated_amount == 0
	for mode in [0, 1]:
		rows = euer("2026-07-01", "2026-08-31", mode)
		own = [
			r
			for r in rows
			if r.get("voucher_no") in {claim.name, tenant.name, first.name, second.name, payment.name}
		]
		assert len(own) == 3, own
		assert abs(sum(flt(r.get("income")) for r in own) - 458.94) < 0.001, own
		assert abs(sum(flt(r.get("expense")) for r in own) - 458.94) < 0.001, own
		assert next(r for r in own if r["voucher_no"] == payment.name)["account"] == case.erstattungskonto
	case.reload()
	case.status = "Abgeschlossen"
	case.save()
	second.cancel()
	case.reload()
	assert case.status == "Teilweise reguliert" and abs(case.versicherungsforderung_offen - 258.94) < 0.001
	for mode in [0, 1]:
		assert not any(r.get("voucher_no") == second.name for r in euer("2026-08-01", "2026-08-31", mode))
	print(
		"PASS insurance claim draft/submission, partial/full bankimport settlement, native references, cancellation, EÜR income/expense in both modes and correct cash dates"
	)


if __name__ == "__main__":
	os.chdir("/tmp/hv-insurance-sites")
	frappe.init(site="insurance-test", sites_path="/tmp/hv-insurance-sites")
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		run()
	finally:
		frappe.db.rollback()
		frappe.destroy()
