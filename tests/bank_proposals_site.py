"""Authenticated Bankimport contracts on a disposable site's WSGI application."""
import argparse
import inspect
import json
from pathlib import Path
import re
from unittest.mock import patch

CORE = "/api/method/hausverwaltung.proposals.frappe_service."
BANK = "/api/method/hausverwaltung.proposals.bank_packages."
PAGE = "/api/method/hausverwaltung.hausverwaltung.page.bankimport_v2.bankimport_v2."
BOOKING = "/api/method/hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import."


def run(site, auth_file, fixture_file):
	import frappe
	import frappe.app
	from frappe.database.database import Database
	from werkzeug.test import Client
	from werkzeug.wrappers import Response
	from hausverwaltung.proposals import bank_action

	auth = json.loads(Path(auth_file).read_text())
	assert auth["purpose"] == "hv-proposals-disposable-testauth"
	fixture = json.loads(Path(fixture_file).read_text())
	import_name, package, lanes = (fixture[key] for key in ("import_name", "package", "lanes"))
	frappe.app._site = site
	frappe.app._sites_path = str(Path.cwd())

	def session(role):
		client = Client(frappe.app.application, Response)
		login = client.post("/api/method/login", json={"usr": f"bank-{role}@hv4.invalid", "pwd": auth[role]})
		assert login.status_code == 200
		desk = client.get("/desk/hv-proposals").get_data(as_text=True)
		csrf = re.search(r'frappe\.csrf_token\s*=\s*["\']([^"\']+)', desk).group(1)

		def post(path, data=None, status=200):
			response = (client.get(path) if data is None else
				client.post(path, json=data, headers={"X-Frappe-CSRF-Token": csrf}))
			assert response.status_code == status, (
				f"{path.rsplit('.', 1)[-1]}: HTTP {response.status_code}, "
				f"{(response.json or {}).get('exc_type', '')}")
			return (response.json or {}).get("message" if data is not None else "data")

		return post

	agent, reviewer = session("agent"), session("reviewer")

	def overview(actor=reviewer):
		return actor(PAGE + "get_overview", {"import_name": import_name})

	def row(index):
		name = lanes[index]["row"]
		return next(row for row in overview()["rows"] if row["id"] == name)

	def bindings(item):
		return [{"id": step["proposal"], "revision": step["revision"], "hash": step["hash"]}
			for step in item["ki"]["steps"]]

	def request(index, **values):
		return {"import_name": import_name, "row": lanes[index]["row"], **values}

	assert "ki" not in overview()["import"]
	agent(BANK + "publish", {"import_name": import_name, "package": package, "lanes": lanes})
	assert overview()["import"]["ki"]["package"] == package
	assert not overview(agent)["import"]["ki"]["canAccept"]

	observed = []
	original = Database.sql

	def checked_sql(db, query, *args, **kwargs):
		if any(frame.function == "get_overview" for frame in inspect.stack()):
			statement = str(query)
			assert "FOR UPDATE" not in statement.upper()
			assert not re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER|CREATE|DROP|TRUNCATE)\b", statement, re.I)
			observed.append(statement.split()[0])
		return original(db, query, *args, **kwargs)

	with patch.object(Database, "sql", checked_sql):
		assert overview()["import"]["ki"]["counts"]["none"] == 1
	assert observed, "SQL observer did not see the overview query"

	chain = bindings(row(0))
	agent(PAGE + "ki_accept", request(0, bindings=chain), status=403)
	wrong_hash = [chain[0] | {"hash": "0" * 64}, chain[1]]
	reviewer(PAGE + "ki_accept", request(0, bindings=wrong_hash), status=417)
	assert row(0)["ki"]["status"] == "Pending"
	reviewer(CORE + "review", {"binding": chain[1], "approve": True})
	failed_step = request(0, bindings=chain)
	batch = {"import_name": import_name, "items": [{"row": lanes[0]["row"], "bindings": chain},
		{"row": lanes[1]["row"], "bindings": bindings(row(1))}]}
	with patch.object(bank_action.booking, "manually_reconcile_row", side_effect=frappe.ValidationError("Test failure")):
		results = reviewer(PAGE + "ki_accept_many", batch)["results"]
	assert results[0]["status"] == "Approved" and results[1]["status"] == "Skipped"
	completed_party = row(0)
	assert completed_party["party"] and completed_party["bankTransaction"]
	unrelated = row(6)
	assert unrelated["iban"] == completed_party["iban"]
	assert not unrelated["party"] and not unrelated["bankTransaction"]
	assert unrelated["ki"]["status"] == "Pending"
	assert [step["status"] for step in completed_party["ki"]["steps"]] == ["Succeeded", "Approved"]
	assert not completed_party["paymentEntry"]
	booked = reviewer(PAGE + "ki_accept", failed_step)
	assert booked["ok"] and booked["results"][-1]["result"]["doctype"] == "Payment Entry"
	assert reviewer(PAGE + "ki_accept", failed_step)["results"][-1]["result"] == booked["results"][-1]["result"]
	audit = reviewer(CORE + "audit", {"proposal_id": chain[1]["id"]})
	assert [event["kind"] for event in audit].count("Approved") == 1
	assert [event["kind"] for event in audit].count("Succeeded") == 1
	assert [event["kind"] for event in audit].count("ExecutionFailed") == 1

	rule_row = row(2)
	ruled = reviewer(BOOKING + "retry_auto_match", {"docname": import_name, "row_name": rule_row["id"]})
	assert len(ruled["matched"]) == 1
	assert row(2)["ki"]["decision"]["category"] == "adjusted_booked"
	audit = reviewer(CORE + "audit", {"proposal_id": bindings(rule_row)[0]["id"]})
	detail = json.loads(audit[-1]["detail"])
	assert detail["source"] == "rule" and detail["auto"]
	assert audit[-1]["actor"] == "bank-reviewer@hv4.invalid"

	manual = row(3)
	reviewer(BOOKING + "create_journal_entry_for_row", {
		"docname": import_name, "row_name": manual["id"], **fixture["journal"]})
	assert row(3)["ki"]["decision"]["category"] == "adjusted_booked"

	unchanged = bindings(row(4))
	assert reviewer(PAGE + "ki_request_revision", request(8))["state"] == "running"
	assert row(8)["ki"]["state"] == "running"
	agent(BANK + "answer_abstention", request(8, package=package, steps=fixture["abstention_answer"]))
	assert row(8)["ki"]["status"] == "Pending"
	assert bindings(row(4)) == unchanged
	assert overview()["import"]["ki"]["package"] == package

	stale = bindings(row(5))[0]
	original_fingerprint = bank_action.fingerprint

	def changed_fingerprint(row):
		value = original_fingerprint(row)
		return value | {"purpose_hash": "changed"} if row.name == lanes[5]["row"] else value

	with patch.object(bank_action, "fingerprint", changed_fingerprint):
		assert reviewer(PAGE + "ki_accept", request(5, bindings=[stale]))["status"] == "Stale"
	assert reviewer(PAGE + "ki_request_revision", request(5, binding=stale))["state"] == "running"
	updated = agent(CORE + "revise", {"binding": stale, **{key: lanes[5]["steps"][0][key]
		for key in ("payload", "metadata")}})
	assert updated["revision"] == stale["revision"] + 1
	assert bindings(row(4)) == unchanged
	reviewer(CORE + "review", {"binding": bindings(row(5))[0], "approve": True})
	next_lanes = [{"row": lane["row"], "note": "Bereits bearbeitet."} if index in (0, 2, 3)
		else lane for index, lane in enumerate(lanes)]
	agent(BANK + "publish", {"import_name": import_name, "package": package + "-NEXT", "lanes": next_lanes})
	assert overview()["import"]["ki"]["package"] == package + "-NEXT"
	for proposal in (unchanged[0]["id"], updated["id"]):
		view = reviewer(CORE + "view", {"proposal_id": proposal})
		assert view["status"] == "Stale" and view["stale_cause"]["cause"] == "superseded"
	party_ref, document_ref = bindings(row(6))
	party_step = lanes[6]["steps"][0]
	new_party = agent(CORE + "revise", {"binding": party_ref, "payload": party_step["payload"],
		"metadata": party_step["metadata"]})
	new_party_ref = {key: new_party[key] for key in ("id", "revision", "hash")}
	earlier_ref = bindings(row(4))
	stale_chain = reviewer(PAGE + "ki_accept_many", {"import_name": import_name,
		"items": [{"row": lanes[4]["row"], "bindings": earlier_ref},
			{"row": lanes[6]["row"], "bindings": [new_party_ref, document_ref]}]})["results"]
	assert [item["status"] for item in stale_chain] == ["Succeeded", "Stale"]
	assert row(4)["journalEntry"]
	assert row(6)["party"] and row(6)["ki"]["status"] == "Stale" and not row(6)["paymentEntry"]

	matrix = fixture["matrix"]
	agent(BANK + "publish", {key: matrix[key] for key in ("import_name", "package", "lanes")})
	matrix_import = matrix["import_name"]
	for lane in matrix["lanes"]:
		step = lane["steps"][0]
		action = step["action"]
		matrix_row = lane["row"]
		data = {"import_name": matrix_import, "row": matrix_row}
		current = reviewer(PAGE + "get_overview", {"import_name": matrix_import})
		ref = bindings(next(row for row in current["rows"] if row["id"] == matrix_row))[0]
		agent(CORE + "review", {"binding": ref, "approve": True}, status=403)
		reviewer(PAGE + "ki_accept", data | {"bindings": [ref | {"hash": "0" * 64}]}, status=417)

		def changed_matrix_fingerprint(row):
			value = original_fingerprint(row)
			return value | {"purpose_hash": "changed"} if row.name == matrix_row else value

		with patch.object(bank_action, "fingerprint", changed_matrix_fingerprint):
			assert reviewer(PAGE + "ki_accept", data | {"bindings": [ref]})["status"] == "Stale", action
		revised = agent(CORE + "revise", {"binding": ref, "payload": step["payload"], "metadata": step["metadata"]})
		ref = {key: revised[key] for key in ("id", "revision", "hash")}
		result = reviewer(PAGE + "ki_accept", data | {"bindings": [ref]})
		assert result["ok"], action
		voucher = result["results"][0]["result"]
		assert voucher["doctype"] == ("Journal Entry" if "kredit" in action else "Payment Entry"), action
		assert voucher["by"] == "bank-reviewer@hv4.invalid", action

	expected_contract = reviewer("/api/resource/Kreditvertrag/" + matrix["statement_contract"])
	competing_contract = reviewer("/api/resource/Kreditvertrag/" + matrix["competing_contract"])
	assert expected_contract["plan"][0]["journal_entry"]
	assert expected_contract["plan"][0]["zinsanteil"] == 60 and expected_contract["plan"][0]["tilgungsanteil"] == 240
	assert not competing_contract["plan"][0].get("journal_entry")
	advance = fixture["advance"]
	args = {key: advance[key] for key in ("import_name", "package", "lanes")}
	assert advance["account"] != advance["other_account"]
	agent(BANK + "publish", args, status=417)
	check = reviewer(PAGE + "get_overview", {"import_name": advance["import_name"]})
	assert "ki" not in check["import"], "Eine unzulässige Folgeaktion darf kein Paket hinterlassen"
	advance_lane = advance["lanes"][0]
	advance_lane["steps"][1]["payload"]["parameters"]["party"] = advance["customer"]
	agent(BANK + "publish", args)
	check = reviewer(PAGE + "get_overview", {"import_name": advance["import_name"]})
	assert advance["account"] in {line["account"] for line in check["rows"][0]["ki"]["postings"]}
	assert advance["other_account"] not in {line["account"] for line in check["rows"][0]["ki"]["postings"]}
	booked_advance = reviewer(PAGE + "ki_accept", {"import_name": advance["import_name"], "row": advance_lane["row"],
		"bindings": bindings(check["rows"][0])})
	assert booked_advance["ok"]
	payment = reviewer("/api/resource/Payment%20Entry/" + booked_advance["results"][1]["result"]["name"])
	assert payment["party"] == advance["customer"]
	assert payment["paid_from"] == advance["account"]
	print(json.dumps({"read_queries": len(observed), "party_then_invoice": "passed", "retry": "passed",
		"manual_booking": "passed", "rule_booking": "passed", "abstention_answer": "passed",
		"bound_answer": "passed", "superseded": "passed", "additional_bookings": len(matrix["lanes"]),
		"revised_predecessor": "passed", "row_only_party": "passed", "statement_credit_binding": "passed", "advance_party_binding": "passed"}))


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--site", required=True)
	parser.add_argument("--auth-file", required=True)
	parser.add_argument("--fixture-file", required=True)
	args = parser.parse_args()
	config = json.loads((Path(args.site) / "site_config.json").read_text())
	assert config.get("hv_disposable_test_site") and config.get("allow_tests")
	run(args.site, args.auth_file, args.fixture_file)
