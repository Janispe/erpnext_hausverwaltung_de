"""Run only on the disposable insurance fixture DB. All test postings roll back."""

import os
from unittest.mock import patch

import frappe
from frappe.utils import flt


def run():
	assert frappe.conf.db_name == "hv_insurance_test_20260909"
	from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry

	from hausverwaltung.hausverwaltung.doctype.versicherungsfall.versicherungsfall import create_tenant_claim
	from hausverwaltung.hausverwaltung.utils.insurance_receivables import (
		create_insurance_claim,
		create_receipt,
	)
	from hausverwaltung.hausverwaltung.utils.insurance_workflow import book_claims

	def case_for(suffix):
		return frappe.get_doc(
			dict(
				doctype="Versicherungsfall",
				company="Hausverwaltung Peters",
				schadensart="Glas",
				schadendatum="2026-07-01",
				status="Bewilligt",
				beguenstigter="Mieter",
				mietvertrag="W5 | HH | EG rechts | ab: 2022-03-16 - Trujillo Arboleda",
				versicherer="Signal Iduna (Versicherung)",
				schadennummer="WORKFLOW-TEST-" + suffix,
				bewilligter_betrag=458.94,
				bewilligungsnachweis="/private/files/test-bewilligung.pdf",
				versicherungsforderungskonto="Forderungen gegen Versicherungen - HP",
				versicherungsertragskonto="Versicherungserstattungen - HP",
				erstattungsart="Auslagenersatz Gebäudereparatur",
				erstattungsbetrag=458.94,
				erstattungskonto="6810 - Instand. Glaser - HP",
				mieterkonto_kategorie="G/N",
				erstattungsbegruendung="TEST Glaserrechnung 266761",
			)
		).insert()

	def reject(fn, text=None):
		try:
			fn()
		except frappe.ValidationError as e:
			if text:
				assert text in str(e), str(e)
			frappe.clear_messages()
		else:
			raise AssertionError("Expected validation failure")

	def execute(case, date, reason=None, expected=None):
		if expected is None:
			case.reload()
			expected = str(case.modified)
		return book_claims(
			case.name,
			insurance_date=date,
			tenant_date=date,
			expected_modified=expected,
			correction_reason=reason,
		)

	case = case_for("CORRECTION")
	stale = str(case.modified)
	first = execute(case, "2026-09-09")
	assert len(first["claims"]) == 2
	old = [r["name"] for r in first["claims"]]
	assert all(frappe.db.get_value("Journal Entry", n, "docstatus") == 1 for n in old)
	case.reload()
	assert case.versicherungsforderung_gebucht == 458.94 and case.mieteranspruch_gebucht == 458.94
	assert [r["name"] for r in execute(case, "2026-09-09")["claims"]] == old
	reject(lambda: execute(case, "2026-07-17", expected=stale), "zwischenzeitlich")
	reject(lambda: execute(case, "2026-07-17"), "Grund")
	assert all(frappe.db.get_value("Journal Entry", n, "docstatus") == 1 for n in old)
	second = execute(case, "2026-07-17", "Erfassungsdatum statt Anspruchsdatum verwendet")
	new = [r["name"] for r in second["claims"]]
	assert set(old).isdisjoint(new)
	for i, name in enumerate(new):
		doc = frappe.get_doc("Journal Entry", name)
		assert doc.docstatus == 1 and str(doc.posting_date) == "2026-07-17" and doc.amended_from == old[i]
		assert doc.custom_versicherungsfall == case.name and doc.total_debit == 458.94
	assert all(frappe.db.get_value("Journal Entry", n, "docstatus") == 2 for n in old)
	case.reload()
	assert {r.referenz for r in case.belege} == set(old + new)
	assert case.versicherungsforderung_gebucht == 458.94 and case.mieteranspruch_gebucht == 458.94

	# Reuse already created drafts; do not create duplicates or lose their case links.
	draft_case = case_for("DRAFTS")
	drafts = [
		create_insurance_claim(draft_case.name, "2026-09-09")["name"],
		create_tenant_claim(draft_case.name, "2026-09-09")["name"],
	]
	result = execute(draft_case, "2026-07-17")
	assert [r["name"] for r in result["claims"]] == drafts
	assert all(frappe.db.get_value("Journal Entry", n, "docstatus") == 1 for n in drafts)

	# Failure on the second submit must roll back the first one and all newly created links.
	failure_case = case_for("ATOMIC")
	original_submit = JournalEntry.submit

	def failing_submit(doc, *args, **kwargs):
		if (
			doc.doctype == "Journal Entry"
			and doc.get("custom_versicherungsfall") == failure_case.name
			and not doc.get("custom_versicherungsbuchung")
		):
			frappe.throw("TEST second claim failure")
		return original_submit(doc, *args, **kwargs)

	with patch.object(JournalEntry, "submit", failing_submit):
		reject(lambda: execute(failure_case, "2026-07-17"), "TEST second claim failure")
	assert not frappe.db.exists("Journal Entry", {"custom_versicherungsfall": failure_case.name})
	failure_case.reload()
	assert len(failure_case.belege) == 0
	# The same all-or-nothing boundary applies when replacing submitted claims.
	failure_case = case
	with patch.object(JournalEntry, "submit", failing_submit):
		reject(lambda: execute(case, "2026-07-16", "TEST rollback replacement"), "TEST second claim failure")
	case.reload()
	assert {r.referenz for r in case.belege} == set(old + new)
	assert all(frappe.db.get_value("Journal Entry", n, "docstatus") == 1 for n in new)

	# A submitted receipt prevents date correction and keeps both claims and payment untouched.
	incoming = frappe._dict(
		name="TEST-BANK-IN",
		company=case.company,
		date="2026-07-17",
		deposit=200,
		withdrawal=0,
		currency="EUR",
		party_type="Supplier",
		party=case.versicherer,
		bank_account="Wilhelmshavener - Postbank, Ndl Deutsche Bank",
		reference_number="TEST",
		description="TEST receipt",
	)
	payment = create_receipt(
		incoming, [dict(name=new[0], reference_doctype="Journal Entry", allocated_amount=200)]
	)
	reject(lambda: execute(case, "2026-07-16", "TEST paid correction"), payment.name)
	assert frappe.db.get_value("Journal Entry", payment.name, "docstatus") == 1
	assert all(frappe.db.get_value("Journal Entry", n, "docstatus") == 1 for n in new)
	case.reload()
	assert abs(case.versicherungsforderung_offen - 258.94) < 0.001
	print(
		"PASS: combined booking, draft reuse, repeated/stale requests, linked amendments, atomic rollback of creation and correction, paid-claim protection"
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
