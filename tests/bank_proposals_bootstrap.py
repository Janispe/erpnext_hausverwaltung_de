"""Nine fictional statement lines for the Bankimport proposal acceptance tests."""
import argparse
import json
from uuid import uuid4

import frappe

from hausverwaltung import cypress_fixtures as fixtures
from hausverwaltung.proposals import bank_action


def seed():
	bank = fixtures.ensure_bankimport_bank_account()
	key = uuid4().hex[:10]
	tenancy = fixtures.seed_bankimport_over_under("ki-" + key, bank["company"])
	account = fixtures._ensure_income_account(bank["company"])
	file = frappe.get_doc({"doctype": "File", "file_name": f"ki-{key}.csv",
		"content": "Buchungstag;Betrag\n03.04.2026;100,00\n", "is_private": 1}).insert()
	imp = frappe.get_doc({"doctype": "Bankauszug Import", "bank_account": bank["bank_account"], "csv_file": file.file_url})
	names = ["Mara Sommer", "Wiesenpark GmbH", "Jonas Lind", "Elif Graf", "Stadtwerke Nord",
		"Paul Grün", "Nora Berg", "Karl Licht", "Lina Wolf"]
	for index, name in enumerate(names):
		imp.append("rows", {"buchungstag": f"2026-04-{index + 3:02d}", "betrag": 100 if index in (0, 6) else 20 + index,
			"richtung": "Eingang", "auftraggeber": name, "verwendungszweck": f"Testumsatz {key} {index}",
			"currency": "EUR", "iban": tenancy["iban"] if index in (0, 6) else None})
	imp.insert()
	bank_action.booking.create_bank_transaction_for_row(imp.name, imp.rows[2].name,
		allow_missing_party=1, skip_auto_match=1)

	def step(row, action, title, params, level="hoch"):
		return {"action": f"hv.bankimport.{action}/v1", "payload": {"import_name": imp.name, "row": row.name,
			"fingerprint": bank_action.fingerprint(row), "parameters": params},
			"metadata": {"lane": {"key": row.name, "label": f"{row.buchungstag} · {row.auftraggeber}"},
				"title": title, "summary": f"{title} · {row.auftraggeber}",
				"rationale": "Synthetischer Kontoauszug", "confidence": {"level": level, "score": .97}}}

	journal = {"account": account, "cost_center": tenancy["cost_center"]}
	lanes = [{"row": row.name, "steps": [step(row, "journal_entry", "Buchungssatz", journal,
		"mittel" if index == 4 else "niedrig" if index == 8 else "hoch")]}
		for index, row in enumerate(imp.rows)]
	for index, invoice in ((0, "april_invoice"), (6, "may_invoice")):
		row = imp.rows[index]
		lanes[index]["steps"] = [
			step(row, "assign_party", "Partei zuordnen", {"party": tenancy["customer"], "party_type": "Customer"}),
			step(row, "reconcile_invoices", "Miete zuordnen", {"invoice_names": [
				{"name": tenancy[invoice], "allocated_amount": 100}]}),
		]
	lanes[8] = {"row": imp.rows[8].name, "note": "Zuordnung unklar."}
	abstention_answer = [step(imp.rows[8], "journal_entry", "Nachgereichter Buchungssatz", journal, "niedrig")]

	frappe.db.commit()
	return {"import_name": imp.name, "package": f"BANK-{key}", "lanes": lanes, "abstention_answer": abstention_answer,
		"journal": journal, "invoice": tenancy["april_invoice"]}


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--site", required=True)
	args = parser.parse_args()
	frappe.init(site=args.site, sites_path=".")
	frappe.connect()
	try:
		fixtures._check_disposable_site()
		print(json.dumps(seed()))
	finally:
		frappe.destroy()
