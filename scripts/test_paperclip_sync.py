from __future__ import annotations

import io
import json
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from scripts import paperclip_sync as pilot

CASE = {
	"name": "PROB-00001",
	"problem_key": "HVP-fixture-1",
	"status": "Offen",
	"severity": "Warnung",
	"description": "Private source text must never be exported",
	"reference": {"doctype": "Mietvertrag", "name": "PRIVATE-CONTRACT"},
}


class ApiHandler(BaseHTTPRequestHandler):
	def log_message(self, *_arguments):
		pass

	def respond(self, body, status=200, **headers):
		self.send_response(status)
		self.send_header("Content-Type", "application/json")
		for name, value in headers.items():
			self.send_header(name, value)
		self.end_headers()
		self.wfile.write(json.dumps(body).encode())

	def do_GET(self):
		self.server.calls.append(("GET", self.path, self.headers.get("Authorization")))
		parts = urlsplit(self.path)
		if parts.path == "/hv" + pilot.ENDPOINT:
			self.respond({"message": {"cases": [CASE], "has_more": False, "next_offset": None}})
		elif parts.path == "/pc/api/companies/company/issues":
			query = parse_qs(parts.query)["q"][0]
			self.respond(
				[issue for issue in self.server.issues.values() if query in issue["description"]],
				**{"X-Paperclip-Has-More": "false"},
			)
		elif parts.path.startswith("/pc/api/issues/"):
			issue = self.server.issues.get(parts.path.rsplit("/", 1)[1])
			self.respond(issue or {}, status=200 if issue else 404)
		elif parts.path == "/pc/redirect":
			self.respond({}, status=302, Location="/pc/leaked-credentials")
		else:
			self.respond({}, status=404)

	def do_POST(self):
		self.server.calls.append(("POST", self.path, self.headers.get("Authorization")))
		if self.path != "/pc/api/companies/company/issues":
			self.respond({}, status=404)
			return
		if self.server.failure == "before_create":
			self.respond({"private_debug": "never print this"}, status=503)
			return
		issue = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
		issue.update(id=f"issue-{len(self.server.issues) + 1}", companyId="company")
		self.server.issues[issue["id"]] = issue
		if self.server.failure == "after_create":
			self.connection.shutdown(socket.SHUT_RDWR)
			self.connection.close()
			return
		self.respond(issue, status=201)


class TestPaperclipSync(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
		cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
		cls.thread.start()

	@classmethod
	def tearDownClass(cls):
		cls.server.shutdown()
		cls.server.server_close()
		cls.thread.join()

	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.path = Path(self.temporary.name) / "state.json"
		self.server.calls = []
		self.server.issues = {}
		self.server.failure = ""
		url = f"http://127.0.0.1:{self.server.server_port}"
		self.config = pilot.Config(url + "/hv", url + "/pc", "company", "token hv:secret", "Bearer pc-secret")
		self.client = pilot.JsonClient(
			self.config.paperclip_url, self.config.paperclip_authorization, "Paperclip"
		)

	def run_sync(self, apply=True):
		with pilot.state_lock(self.path):
			return pilot.sync_cases(
				self.config,
				[CASE],
				self.client,
				pilot.load_state(self.path, self.config),
				self.path,
				apply=apply,
			)

	def test_read_only_preview_uses_real_http_and_creates_no_state_or_ticket(self):
		hv = pilot.JsonClient(self.config.hv_url, self.config.hv_authorization, "ERPNext")
		cases = pilot.read_cases(hv)
		result = pilot.sync_cases(
			self.config, cases, self.client, pilot.load_state(self.path, self.config), self.path, apply=False
		)
		self.assertEqual(result[0]["action"], "would_create")
		self.assertFalse(self.path.exists())
		self.assertEqual(self.server.issues, {})
		self.assertTrue(all(method == "GET" for method, _path, _auth in self.server.calls))
		self.assertEqual(self.server.calls[0][2], "token hv:secret")
		self.assertEqual(self.server.calls[1][2], "Bearer pc-secret")

	def test_repeat_import_preserves_human_notes_status_and_assignment(self):
		first = self.run_sync()[0]
		issue = self.server.issues[first["issue_id"]]
		self.assertEqual(issue["status"], "backlog")
		issue.update(status="done", assigneeUserId="human")
		issue["description"] += "\nHuman review notes"
		second = self.run_sync()[0]
		self.assertEqual(second["action"], "existing")
		self.assertEqual(second["issue_id"], first["issue_id"])
		self.assertEqual(issue["status"], "done")
		self.assertEqual(issue["assigneeUserId"], "human")
		self.assertIn("Human review notes", issue["description"])
		self.assertEqual(sum(method == "POST" for method, _path, _auth in self.server.calls), 1)
		self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

	def test_lost_state_recovers_closed_issue_by_exact_marker(self):
		created = self.run_sync()[0]
		self.server.issues[created["issue_id"]]["status"] = "done"
		self.path.unlink()
		self.assertEqual(self.run_sync()[0]["issue_id"], created["issue_id"])
		self.assertEqual(len(self.server.issues), 1)

	def test_response_lost_after_commit_recovers_pending_create(self):
		self.server.failure = "after_create"
		with self.assertRaises(pilot.SyncError):
			self.run_sync()
		state = pilot.load_state(self.path, self.config)
		self.assertEqual(next(iter(state["issues"].values())), {"state": "pending"})
		self.server.failure = ""
		self.assertEqual(self.run_sync()[0]["action"], "existing")
		self.assertEqual(len(self.server.issues), 1)

	def test_uncertain_create_without_match_stops_before_retry(self):
		self.server.failure = "before_create"
		with self.assertRaisesRegex(pilot.SyncError, "HTTP 503"):
			self.run_sync()
		self.server.failure = ""
		with self.assertRaisesRegex(pilot.SyncError, "ungeklärten Ausgang"):
			self.run_sync()
		self.assertEqual(sum(method == "POST" for method, _path, _auth in self.server.calls), 1)
		self.assertFalse(self.server.issues)

	def test_duplicate_remote_markers_and_deleted_linked_issues_require_resolution(self):
		created = self.run_sync()[0]
		issue = self.server.issues[created["issue_id"]]
		self.server.issues["duplicate"] = dict(issue, id="duplicate")
		self.path.unlink()
		with self.assertRaisesRegex(pilot.SyncError, "Mehrere Tickets"):
			self.run_sync()
		self.server.issues.pop("duplicate")
		self.run_sync()
		self.server.issues.clear()
		with self.assertRaisesRegex(pilot.SyncError, "HTTP 404"):
			self.run_sync()

	def test_mismatched_company_or_changed_marker_rejects_link(self):
		created = self.run_sync()[0]
		issue = self.server.issues[created["issue_id"]]
		issue["companyId"] = "another-company"
		with self.assertRaisesRegex(pilot.SyncError, "nicht eindeutig"):
			self.run_sync()
		issue.update(companyId="company", description="Operator removed the import marker")
		with self.assertRaisesRegex(pilot.SyncError, "nicht eindeutig"):
			self.run_sync()

	def test_redirect_does_not_forward_authorization(self):
		with self.assertRaisesRegex(pilot.SyncError, "HTTP 302"):
			self.client.request("GET", "/redirect")
		self.assertEqual(len(self.server.calls), 1)

	def test_state_lock_and_configuration_binding_prevent_cross_import(self):
		with pilot.state_lock(self.path):
			with self.assertRaisesRegex(pilot.SyncError, "bereits ein Import"):
				with pilot.state_lock(self.path):
					self.fail("The second lock must fail")
		self.run_sync()
		with self.assertRaisesRegex(pilot.SyncError, "anderen Konfiguration"):
			pilot.load_state(self.path, replace(self.config, company_id="another-company"))

	def test_payload_is_minimal_and_ids_are_stable_per_site_and_case(self):
		marker, payload = pilot.make_payload(self.config, CASE)
		self.assertNotIn("Private source text", json.dumps(payload))
		self.assertNotIn("PRIVATE-CONTRACT", json.dumps(payload))
		self.assertNotIn("pc-secret", repr(self.config))
		self.assertNotIn("hv:secret", repr(self.config))
		self.assertEqual(payload["idempotencyKey"], marker)
		self.assertNotEqual(
			marker, pilot.make_payload(replace(self.config, hv_url="https://another.example"), CASE)[0]
		)
		self.assertEqual(pilot.make_payload(self.config, dict(CASE, severity="Kritisch"))[0], marker)
		self.assertEqual(
			pilot.make_payload(self.config, dict(CASE, name="A/B (1)"))[1]["description"].splitlines()[0],
			f"[Fall in ERPNext öffnen]({self.config.hv_url}/desk/hausverwaltung-problem/A%2FB%20%281%29)",
		)

	def test_empty_filtered_page_is_followed_and_invalid_paging_fails(self):
		client = Mock()
		client.request.side_effect = [
			({"message": {"cases": [], "has_more": True, "next_offset": 100}}, {}),
			({"message": {"cases": [CASE], "has_more": False, "next_offset": None}}, {}),
		]
		self.assertEqual(pilot.read_cases(client), [CASE])
		self.assertEqual(client.request.call_args.kwargs["query"]["offset"], 100)
		client.request.side_effect = None
		client.request.return_value = ({"message": {"cases": [], "has_more": True, "next_offset": 0}}, {})
		with self.assertRaisesRegex(pilot.SyncError, "Seitennavigation"):
			pilot.read_cases(client)

	def test_issue_search_checks_exact_markers_and_all_pages(self):
		marker, payload = pilot.make_payload(self.config, CASE)
		issue = dict(payload, id="match", companyId="company")
		client = Mock()
		client.request.side_effect = [
			(
				[dict(issue, description="Similar " + marker)],
				{"X-Paperclip-Has-More": "true", "X-Paperclip-Next-Offset": "100"},
			),
			([issue], {"X-Paperclip-Has-More": "false"}),
		]
		self.assertEqual(pilot.find_issue(client, "company", marker)["id"], "match")
		self.assertEqual(client.request.call_args.kwargs["query"]["offset"], 100)

	def test_legacy_saturated_search_aborts_instead_of_assuming_absence(self):
		client = Mock()
		client.request.return_value = ([{}] * 100, {})
		with self.assertRaisesRegex(pilot.SyncError, "unvollständig"):
			pilot.find_issue(client, "company", "marker")

	def test_environment_is_read_as_data_and_errors_hide_secrets(self):
		path = Path(self.temporary.name) / "config.env"
		path.write_text("HV_API_KEY='file-key'\nHV_API_SECRET=$(never-execute)\n", encoding="utf-8")
		with patch.dict("os.environ", {"HV_API_KEY": "environment-key"}, clear=True):
			values = pilot.load_environment(path)
		self.assertEqual(values["HV_API_KEY"], "environment-key")
		self.assertEqual(values["HV_API_SECRET"], "$(never-execute)")
		path.write_text("TYPO=private-secret\n", encoding="utf-8")
		with self.assertRaises(pilot.SyncError) as error:
			pilot.load_environment(path)
		self.assertNotIn("private-secret", str(error.exception))
		for url in (
			"https://user:secret@example.org",
			"https://example.org?secret=x",
			"https://[bad",
			"file:///etc/passwd",
		):
			with self.subTest(url=url), self.assertRaises(pilot.SyncError):
				pilot.base_url(url)

	def test_demo_runs_without_configuration_network_or_files(self):
		output = io.StringIO()
		with (
			patch.object(pilot.JsonClient, "request", side_effect=AssertionError("Unexpected network")),
			patch.object(pilot, "load_state", side_effect=AssertionError("Unexpected state")),
			redirect_stdout(output),
		):
			pilot.main(["--demo"])
		self.assertEqual(json.loads(output.getvalue())["results"][0]["action"], "would_create")


if __name__ == "__main__":
	unittest.main()
