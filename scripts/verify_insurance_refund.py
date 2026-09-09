"""8090 fixture integration checks on an isolated database; never run on frontend.

Run with the app import path and Frappe environment configured. The temporary
insurance-test site is a small-table/metadata clone of 8090. All test postings
are rolled back. Schema synchronization affects only that disposable database.
"""

import os

import frappe


def run():
	from hausverwaltung.hausverwaltung.doctype.versicherungsfall.versicherungsfall import create_tenant_claim
	from hausverwaltung.hausverwaltung.patches.post_model_sync.add_insurance_accounting_fields import (
		execute as patch,
	)
	from hausverwaltung.hausverwaltung.report.mieterkonto.mieterkonto import execute as report
	from hausverwaltung.hausverwaltung.utils.tenant_refunds import create_refund_payment, journal_credit

	assert frappe.conf.db_name == "hv_insurance_test_20260909", "Requires disposable test database"
	frappe.reload_doc("hausverwaltung", "doctype", "versicherungsfall_beleg", force=True)
	frappe.reload_doc("hausverwaltung", "doctype", "versicherungsfall", force=True)
	patch()
	frappe.db.commit()
	case = frappe.get_doc(
		dict(
			doctype="Versicherungsfall",
			company="Hausverwaltung Peters",
			schadensart="Glas",
			schadendatum="2026-07-17",
			mietvertrag="W5 | HH | EG rechts | ab: 2022-03-16 - Trujillo Arboleda",
			beguenstigter="Mieter",
			erstattungsart="Auslagenersatz Gebäudereparatur",
			erstattungsbetrag=458.94,
			erstattungskonto="6810 - Instand. Glaser - HP",
			mieterkonto_kategorie="G/N",
			erstattungsbegruendung="TEST Glaserrechnung 266761",
		)
	).insert()
	result = create_tenant_claim(case.name, "2026-07-17")
	je = frappe.get_doc("Journal Entry", result["name"])
	assert je.docstatus == 0
	case.reload()
	assert case.mieteranspruch_gebucht == 0
	je.submit()
	case.reload()
	assert case.mieteranspruch_gebucht == 458.94
	assert journal_credit(je.name, case.kunde, case.company).allocatable_amount == 458.94
	bt = frappe._dict(
		name="TEST-BT",
		party_type="Customer",
		party=case.kunde,
		company=case.company,
		date="2026-07-17",
		deposit=0,
		withdrawal=458.94,
		bank_account="Wilhelmshavener - Postbank, Ndl Deutsche Bank",
		reference_number="TEST",
		description="TEST Erstattung Glaser",
	)
	pe = create_refund_payment(
		bt, [{"name": je.name, "reference_doctype": "Journal Entry", "allocated_amount": 458.94}]
	)
	case.reload()
	assert case.an_mieter_ausgezahlt == 458.94 and case.offen_mieter == 0
	assert journal_credit(je.name, case.kunde, case.company).allocatable_amount == 0
	filters = dict(company=case.company, customer=case.kunde, from_date="2026-07-01", to_date="2026-07-31")
	r = report(filters)
	rows = [x for x in r[1] if x.get("belegnummer") in (je.name, pe.name)]
	print(
		"REPORT",
		[
			{
				k: x.get(k)
				for k in [
					"art",
					"belegnummer",
					"betrag_guthaben_nachzahlungen",
					"betrag_vorauszahlungen",
					"betrag_summe",
				]
			}
			for x in rows
		],
	)
	assert len(rows) == 2
	assert sorted(x["betrag_guthaben_nachzahlungen"] for x in rows) == [-458.94, 458.94]
	assert all(x.get("betrag_vorauszahlungen", 0) == 0 for x in rows)
	case.status = "Abgeschlossen"
	case.save()
	pe.cancel()
	case.reload()
	assert case.status == "Teilweise reguliert" and case.offen_mieter == 458.94
	assert journal_credit(je.name, case.kunde, case.company).allocatable_amount == 458.94

	# Partial payouts, stale selections and the actual Bankimport endpoint.
	def reject(action):
		try:
			action()
		except frappe.ValidationError:
			frappe.clear_messages()
		else:
			raise AssertionError("Expected invalid refund to be rejected")

	reject(
		lambda: create_refund_payment(
			bt, [{"name": je.name, "reference_doctype": "Journal Entry", "allocated_amount": 459}]
		)
	)
	reject(
		lambda: create_refund_payment(
			bt, [{"name": je.name, "reference_doctype": "Journal Entry", "allocated_amount": 200}]
		)
	)
	wrong_customer = frappe.db.get_value("Customer", {"name": ["!=", case.kunde]}, "name")
	reject(lambda: journal_credit(je.name, wrong_customer, case.company))
	partial_bt = frappe._dict(bt)
	partial_bt.withdrawal = 200
	partial = create_refund_payment(
		partial_bt, [{"name": je.name, "reference_doctype": "Journal Entry", "allocated_amount": 200}]
	)
	case.reload()
	assert abs(case.offen_mieter - 258.94) < 0.001
	assert abs(journal_credit(je.name, case.kunde, case.company).allocatable_amount - 258.94) < 0.001
	reject(
		lambda: create_refund_payment(
			bt, [{"name": je.name, "reference_doctype": "Journal Entry", "allocated_amount": 458.94}]
		)
	)
	partial.cancel()
	case.reload()
	bank_transaction = frappe.get_doc(
		dict(
			doctype="Bank Transaction",
			company=case.company,
			date="2026-07-17",
			withdrawal=458.94,
			deposit=0,
			currency="EUR",
			bank_account=bt.bank_account,
			party_type="Customer",
			party=case.kunde,
			description="TEST Erstattung Glaser",
			reference_number="TEST-INSURANCE",
		)
	)
	bank_transaction.insert()
	bank_transaction.submit()
	bank_import = frappe.get_doc(
		dict(
			doctype="Bankauszug Import",
			bank_account=bt.bank_account,
			csv_file="/private/files/test-insurance.csv",
			rows=[
				dict(
					buchungstag="2026-07-17",
					betrag=458.94,
					richtung="Ausgang",
					party_type="Customer",
					party=case.kunde,
					bank_transaction=bank_transaction.name,
					verwendungszweck="TEST Erstattung Glaser",
				)
			],
		)
	).insert()
	from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
		get_open_invoices_for_row,
		manually_reconcile_row,
	)

	candidates = get_open_invoices_for_row(bank_import.name, bank_import.rows[0].name)
	assert any(x.name == je.name and x.reference_doctype == "Journal Entry" for x in candidates["invoices"])
	result = manually_reconcile_row(
		bank_import.name,
		bank_import.rows[0].name,
		frappe.as_json([dict(name=je.name, reference_doctype="Journal Entry", allocated_amount=458.94)]),
	)
	bank_transaction.reload()
	case.reload()
	bank_import.reload()
	assert bank_transaction.status == "Reconciled" and bank_transaction.unallocated_amount == 0
	assert case.offen_mieter == 0 and case.an_mieter_ausgezahlt == 458.94
	assert bank_import.rows[0].payment_entry == result["payment_entry"]
	gl = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Payment Entry", "voucher_no": result["payment_entry"], "is_cancelled": 0},
		fields=["account", "party", "debit", "credit"],
	)
	assert sum(x.debit for x in gl) == 458.94 and sum(x.credit for x in gl) == 458.94
	assert sum(x.debit - x.credit for x in gl if x.party == case.kunde) == 458.94
	print(
		"PASS: draft, claim, partial/full payout, stale/invalid selection, bankimport reconciliation, report category and cancellation"
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
