"""Nine fictional statement lines for the Bankimport proposal acceptance tests."""
import argparse
import json
from uuid import uuid4

import frappe

from hausverwaltung import cypress_fixtures as fixtures
from hausverwaltung.hausverwaltung.utils.bankimport_rules import BUILDER_RULE_CODE
from hausverwaltung.proposals import bank_action


def _step(imp, row, action, title, params, level="hoch"):
	return {"action": f"hv.bankimport.{action}/v1", "payload": {"import_name": imp.name, "row": row.name,
		"fingerprint": bank_action.fingerprint(row), "parameters": params},
		"metadata": {"lane": {"key": row.name, "label": f"{row.buchungstag} · {row.auftraggeber}"},
			"title": title, "summary": f"{title} · {row.auftraggeber}",
			"rationale": "Synthetischer Kontoauszug", "confidence": {"level": level, "score": .97}}}


def _statement(bank, key):
	file = frappe.get_doc({"doctype": "File", "file_name": f"ki-{key}.csv",
		"content": "Buchungstag;Betrag\n03.04.2026;100,00\n", "is_private": 1}).insert()
	return frappe.get_doc({"doctype": "Bankauszug Import", "bank_account": bank, "csv_file": file.file_url})


def _matrix(bank, key):
	company = bank["company"]
	tenancy = fixtures.seed_bankimport_over_under("ki-matrix-" + key, company)
	bank_doc = frappe.get_doc("Bank Account", bank["bank_account"])
	bank_parent = frappe.db.get_value("Account", bank_doc.account, "parent_account")
	account = frappe.get_doc({"doctype": "Account", "account_name": f"KI Testbank {key}",
		"company": company, "parent_account": bank_parent, "account_type": "Bank"}).insert()
	frappe.get_doc({"doctype": "Bank Account", "account_name": account.account_name,
		"company": company, "is_company_account": 1, "account": account.name, "bank": bank_doc.bank}).insert()
	property_doc = frappe.get_doc("Immobilie", tenancy["immobilie"])
	property_doc.append("bankkonten", {"konto": account.name, "ist_hauptkonto": 1})
	property_doc.save()
	other_bank = property_doc.reload().haupt_bank_account

	supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": f"Elbwerke {key}",
		"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")}).insert().name
	expense = fixtures._leaf_account(company, root_type="Expense")
	cost_type = frappe.get_doc({"doctype": "Kostenart nicht umlagefaehig", "name1": f"KI Test {key}",
		"konto": expense}).insert().name
	plan = frappe.get_doc({"doctype": "Zahlungsplan", "bezeichnung": f"Abschlag {key}", "company": company,
		"modus": "Abschlagsplan", "lieferant": supplier, "bank_account": other_bank, "immobilie": property_doc.name,
		"cost_center": tenancy["cost_center"], "kostenart_nicht_umlagefaehig": cost_type,
		"plan": [{"faelligkeitsdatum": "2026-04-07", "betrag": 50}]}).insert()
	for user in ("bank-agent@hv4.invalid", "bank-reviewer@hv4.invalid"):
		frappe.share.add("Zahlungsplan", plan.name, user=user, read=1)
	liabilities = frappe.db.get_value("Account", {"company": company, "root_type": "Liability", "is_group": 1}, "name")
	principal = frappe.get_doc({"doctype": "Account", "account_name": f"KI Testdarlehen {key}", "company": company,
		"parent_account": liabilities}).insert().name
	loan = {"doctype": "Kreditvertrag", "company": company, "lieferant": supplier,
		"bank_account": other_bank, "darlehenskonto": principal, "zinsaufwandskonto": expense,
		"anfangs_restschuld": 10000, "cost_center": tenancy["cost_center"]}
	credit = frappe.get_doc(loan | {"bezeichnung": f"Kredit {key}",
		"plan": [{"faelligkeitsdatum": "2026-04-08", "zinsanteil": 50, "tilgungsanteil": 200}]}).insert()
	statement_contract = frappe.get_doc(loan | {"bezeichnung": f"Kontoauszug-Vertrag {key}",
		"vertragsnummer": f"AZ{key}"}).insert()
	competing_contract = frappe.get_doc(loan | {"bezeichnung": f"Anderer Vertrag {key}",
		"vertragsnummer": f"AB{key}", "plan": [{"faelligkeitsdatum": "2026-04-09",
			"zinsanteil": 30, "tilgungsanteil": 270}]}).insert()
	customer = ("Customer", tenancy["customer"])
	vendor = ("Supplier", supplier)
	cases = [
		("reconcile_split", "Eingang", 100, customer, {"invoice_allocations": [
			{"name": tenancy["april_invoice"], "allocated_amount": 100}]}),
		("standalone_payment", "Eingang", 29, customer, {}),
		("internal_transfer", "Eingang", 37, (None, None), {"other_bank_account": bank_doc.name}),
		("assign_abschlag", "Ausgang", 50, vendor, {"plan_name": plan.name, "plan_row_name": plan.plan[0].name}),
		("assign_kreditrate", "Ausgang", 250, vendor, {"kreditvertrag": credit.name, "rate_name": credit.plan[0].name}),
		("assign_kreditrate", "Ausgang", 300, vendor, {"kreditvertrag": statement_contract.name, "from_statement": True}),
	]
	imp = _statement(other_bank, "matrix-" + key)
	for index, (action, direction, amount, party, _) in enumerate(cases):
		purpose = f"AZ AZ{key}, IN EUR: Tilgung 240,00 Zinsen 60,00" if index == 5 else f"{action} {key}"
		imp.append("rows", {"buchungstag": f"2026-04-{index + 4:02d}", "betrag": amount,
			"richtung": direction, "auftraggeber": f"KI Test {index}", "verwendungszweck": purpose,
			"currency": "EUR", "party_type": party[0], "party": party[1]})
	imp.insert()
	lanes = [{"row": row.name, "steps": [_step(imp, row, action, action, params)]}
		for row, (action, _, _, _, params) in zip(imp.rows, cases)]
	return {"import_name": imp.name, "package": f"BANK-MATRIX-{key}", "lanes": lanes,
		"statement_contract": statement_contract.name, "competing_contract": competing_contract.name}


def seed():
	bank = fixtures.ensure_bankimport_bank_account()
	key = uuid4().hex[:10]
	tenancy = fixtures.seed_bankimport_over_under("ki-" + key, bank["company"])
	account = fixtures._ensure_income_account(bank["company"])
	imp = _statement(bank["bank_account"], key)
	test_iban = fixtures._make_de_iban_from_run_id("bank-proposals-" + key)
	names = ["Mara Sommer", "Wiesenpark GmbH", "Jonas Lind", "Elif Graf", "Stadtwerke Nord",
		"Paul Grün", "Nora Berg", "Karl Licht", "Lina Wolf"]
	for index, name in enumerate(names):
		imp.append("rows", {"buchungstag": f"2026-04-{index + 3:02d}", "betrag": 100 if index in (0, 6) else 20 + index,
			"richtung": "Eingang", "auftraggeber": name, "verwendungszweck": f"Testumsatz {key} {index}",
			"currency": "EUR", "iban": test_iban if index in (0, 6) else None})
	imp.insert()
	bank_action.booking.create_bank_transaction_for_row(imp.name, imp.rows[2].name,
		allow_missing_party=1, skip_auto_match=1)

	journal = {"account": account, "cost_center": tenancy["cost_center"]}
	frappe.get_doc({"doctype": "Bankimport Buchungsregel", "rule_key": f"ki-test-{key}",
		"title": "Synthetische Buchungsregel", "priority": 1, "rule_code": BUILDER_RULE_CODE,
		"parameters_json": json.dumps({"builder": {"conditions": [{"field": "zweck", "op": "=",
			"value": imp.rows[2].verwendungszweck}]}, "action": {"type": "booking", **journal}})}).insert()
	lanes = [{"row": row.name, "steps": [_step(imp, row, "journal_entry", "Buchungssatz", journal,
		"mittel" if index == 4 else "niedrig" if index == 8 else "hoch")]}
		for index, row in enumerate(imp.rows)]
	for index, invoice in ((0, "april_invoice"), (6, "may_invoice")):
		row = imp.rows[index]
		lanes[index]["steps"] = [
			_step(imp, row, "assign_party", "Partei zuordnen", {"party": tenancy["customer"], "party_type": "Customer"}),
			_step(imp, row, "reconcile_invoices", "Miete zuordnen", {"invoice_names": [
				{"name": tenancy[invoice], "allocated_amount": 100}]}),
		]
	lanes[8] = {"row": imp.rows[8].name, "note": "Zuordnung unklar."}
	abstention_answer = [_step(imp, imp.rows[8], "journal_entry", "Nachgereichter Buchungssatz", journal, "niedrig")]

	matrix = _matrix(bank, key)
	frappe.db.commit()
	return {"import_name": imp.name, "package": f"BANK-{key}", "lanes": lanes, "abstention_answer": abstention_answer,
		"journal": journal, "matrix": matrix}


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--site", required=True)
	args = parser.parse_args()
	frappe.init(site=args.site, sites_path=".")
	frappe.connect()
	try:
		fixtures._check_disposable_site()
		frappe.set_user("Administrator")
		print(json.dumps(seed()))
	finally:
		frappe.destroy()
