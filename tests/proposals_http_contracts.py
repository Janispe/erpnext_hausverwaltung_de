"""Opt-in real HTTP contracts for a NEW isolated synthetic site only.

Run explicitly with --synthetic, loopback --base-url and --auth-file produced
by this worker's NEW disposable bootstrap. No environment/old-site credentials.
Passwords, cookies, CSRF tokens and raw login/HTTP bodies are never printed.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
import json
from pathlib import Path
import re
import unittest
from urllib import error, parse, request
from uuid import uuid4

PREFIX = "/api/method/hausverwaltung.proposals.frappe_service."


class HTTPFailure(Exception):
	def __init__(self, status, body):
		self.status, self.body = status, body
		super().__init__(f"HTTP {status}, type {body.get('exc_type', 'unknown')}")


class Client:
	def __init__(self, base):
		self.base = base
		self.jar = http.cookiejar.CookieJar()
		self.opener = request.build_opener(request.HTTPCookieProcessor(self.jar))
		self.csrf = None

	def call(self, path, data=None, method=None):
		headers = {"Content-Type": "application/json"}
		if self.csrf: headers["X-Frappe-CSRF-Token"] = self.csrf
		body = None if data is None else json.dumps(data).encode()
		req = request.Request(self.base + path, data=body, headers=headers, method=method)
		try:
			with self.opener.open(req, timeout=45) as response:
				raw = response.read()
				return json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw.decode()
		except error.HTTPError as failed:
			try: body = json.loads(failed.read())
			except ValueError: body = {}
			raise HTTPFailure(failed.code, body) from None

	def login(self, user, password):
		self.call("/api/method/login", {"usr": user, "pwd": password})
		html = self.call("/desk/hv-proposals")
		match = re.search(r'frappe\.csrf_token\s*=\s*["\']([^"\']+)', html)
		if not match: raise RuntimeError("Normal Desk CSRF bootstrap missing")
		self.csrf = match.group(1)

	def api(self, method, **data):
		return self.call(PREFIX + method, data)["message"]

	def resource(self, doctype, name=None, data=None, method=None):
		path = "/api/resource/" + parse.quote(doctype, safe="")
		if name is not None: path += "/" + parse.quote(name, safe="")
		return self.call(path, data, method)["data"]


def binding(proposal): return {key: proposal[key] for key in ("id", "revision", "hash")}


class SiteContracts(unittest.TestCase):
	base = None
	auth = None

	@classmethod
	def setUpClass(cls):
		cls.clients = {}
		for account in ("agent", "reviewer", "blocked", "admin"):
			client = Client(cls.base)
			client.login("Administrator" if account == "admin" else account + "@hv4.invalid",
				cls.auth["agent" if account == "blocked" else account])
			cls.clients[account] = client

	def setUp(self):
		self.agent, self.reviewer, self.admin = (self.clients[n] for n in ("agent", "reviewer", "admin"))
		self.target = "SYN-HTTP-" + uuid4().hex[:12]
		self.package = "http-" + uuid4().hex[:12]
		self.reviewer.resource("HV Synthetic Note", data={"synthetic_id": self.target, "label": "before"})

	def submit(self, label="after", deps=None, target=None, key=None):
		return self.agent.api("submit", key=key or uuid4().hex, package=self.package,
			payload={"target": target or self.target, "label": label}, dependencies=deps or [])

	def approve(self, proposal): return self.reviewer.api("review", binding=binding(proposal), approve=True)
	def execute(self, proposal): return self.agent.api("execute", binding=binding(proposal))
	def note(self): return self.agent.resource("HV Synthetic Note", self.target)

	def test_01_preview_does_not_save_and_human_save_audit_retry(self):
		before = self.note()
		p = self.submit()
		after_preview = self.note()
		self.assertEqual((after_preview["label"], after_preview["generation"], after_preview["modified"]),
			(before["label"], before["generation"], before["modified"]))
		self.assertEqual(p["preview"]["before"], {"label": "before", "generation": 0})
		self.assertEqual(p["preview"]["after"], {"label": "after", "generation": 1})
		with self.assertRaises(HTTPFailure): self.execute(p)
		with self.assertRaises(HTTPFailure) as blocked:
			self.agent.api("review", binding=binding(p), approve=True)
		self.assertEqual(blocked.exception.status, 403)
		self.approve(p)
		result = self.execute(p)
		self.assertEqual(result["status"], "Succeeded")
		self.assertEqual(self.note()["label"], "after")
		self.assertEqual(self.note()["generation"], 1)
		self.assertEqual(self.execute(p)["result"], result["result"])
		self.assertEqual(self.note()["generation"], 1)
		events = self.agent.api("audit", proposal_id=p["id"])
		self.assertEqual([e["kind"] for e in events], ["Created", "Approved", "Succeeded", "ResultReused"])

	def test_02_reject_revision_hash_and_direct_mutation(self):
		p = self.submit()
		wrong = binding(p) | {"hash": "0" * 64}
		with self.assertRaises(HTTPFailure): self.reviewer.api("review", binding=wrong, approve=True)
		self.reviewer.api("review", binding=binding(p), approve=False)
		with self.assertRaises(HTTPFailure): self.execute(p)
		r = self.agent.api("revise", binding=binding(p), payload={"target": self.target, "label": "revised"})
		self.assertEqual(r["revision"], 2)
		with self.assertRaises(HTTPFailure): self.reviewer.api("review", binding=binding(p), approve=True)
		with self.assertRaises(HTTPFailure): self.agent.resource("HV Action Proposal", p["id"], {"status": "Approved"}, "PUT")
		self.assertEqual(self.note()["generation"], 0)

	def test_03_dag_projection_real_predecessors_and_stale(self):
		a = self.submit("a")
		b = self.submit("b", [binding(a)])
		self.assertEqual(b["preview"]["before"], {"label": "a", "generation": 1})
		self.approve(a); self.approve(b)
		with self.assertRaises(HTTPFailure): self.execute(b)
		self.execute(a); self.execute(b)
		self.assertEqual(self.note()["generation"], 2)
		c = self.submit("c", [binding(b)])
		self.assertTrue(all(dep["mode"] == "real" for dep in c["preview"]["dependencies"]))
		self.approve(c); self.execute(c)
		self.assertEqual(self.note()["generation"], 3)
		x = self.submit("x"); y = self.submit("y", [binding(x)])
		self.agent.api("revise", binding=binding(x), payload={"target": self.target, "label": "x2"})
		self.assertEqual(self.agent.api("view", proposal_id=y["id"])["status"], "Stale")

	def test_04_current_reviewer_role_revocation(self):
		p = self.submit(); self.approve(p)
		doc = self.admin.resource("User", "reviewer@hv4.invalid")
		roles = [{"role": r["role"]} for r in doc["roles"]]
		try:
			self.admin.resource("User", "reviewer@hv4.invalid", {"roles": []}, "PUT")
			with self.assertRaises(HTTPFailure): self.execute(p)
			self.assertEqual(self.note()["generation"], 0)
		finally:
			self.admin.resource("User", "reviewer@hv4.invalid", {"roles": roles}, "PUT")
			self.reviewer.login("reviewer@hv4.invalid", self.auth["reviewer"])

	def test_05_request_idempotency_and_changed_baseline(self):
		key = uuid4().hex
		p = self.submit(key=key)
		self.assertEqual(self.submit(key=key)["id"], p["id"])
		with self.assertRaises(HTTPFailure): self.submit("different", key=key)
		self.approve(p)
		self.reviewer.resource("HV Synthetic Note", self.target, {"label": "concurrent"}, "PUT")
		with self.assertRaises(HTTPFailure): self.execute(p)
		self.assertEqual(self.agent.api("view", proposal_id=p["id"])["status"], "Stale")

	def test_06_object_permissions_missing_and_hidden_http_messages(self):
		allowed = self.reviewer.resource("HV Synthetic Note", data={"synthetic_id": "SYN-ALLOW-" + uuid4().hex[:10], "label": "allowed"})
		permission = self.admin.resource("User Permission", data={"user": "blocked@hv4.invalid", "allow": "HV Synthetic Note", "for_value": allowed["name"], "apply_to_all_doctypes": 1})
		responses = []
		try:
			for target in (self.target, "SYN-MISSING-" + uuid4().hex[:12]):
				with self.assertRaises(HTTPFailure) as failure:
					self.clients["blocked"].api("submit", key=uuid4().hex, package=self.package,
						payload={"target": target, "label": "unavailable"})
				body = failure.exception.body
				messages = [json.loads(v)["message"] for v in json.loads(body.get("_server_messages", "[]"))]
				responses.append((failure.exception.status, body.get("exc_type"), messages))
			self.assertEqual(responses[0], responses[1])
			self.assertEqual(responses[0][0], 403)
			self.assertEqual(responses[0][2], ["Proposal operation unavailable"])
		finally:
			self.admin.resource("User Permission", permission["name"], method="DELETE")

	def permission(self, doctype, role, level, ptype, value):
		self.admin.call("/api/method/frappe.core.page.permission_manager.permission_manager.update",
			{"doctype": doctype, "role": role, "permlevel": level, "ptype": ptype, "value": str(value)})

	def test_07_current_label_field_rights(self):
		p = self.submit(); self.approve(p)
		try:
			self.permission("HV Synthetic Note", "HV Proposal Agent", 1, "write", 0)
			with self.assertRaises(HTTPFailure) as denied: self.execute(p)
			self.assertEqual(denied.exception.status, 403)
			self.assertEqual(self.note()["generation"], 0)
		finally:
			self.permission("HV Synthetic Note", "HV Proposal Agent", 1, "write", 1)
		self.assertEqual(self.execute(p)["status"], "Succeeded")

	def test_08_parallel_execute_runs_once(self):
		p = self.submit(); self.approve(p)
		clients = []
		for _ in range(2):
			client = Client(self.base)
			for cookie in self.agent.jar: client.jar.set_cookie(copy.copy(cookie))
			client.csrf = self.agent.csrf; clients.append(client)
		def attempt(client):
			try: return client.api("execute", binding=binding(p))
			except HTTPFailure as failure:
				self.assertEqual(failure.status, 409)
				self.assertEqual(failure.body.get("exc_type"), "ConcurrentRevisionRetry")
				return None
		with ThreadPoolExecutor(max_workers=2) as pool:
			results = list(pool.map(attempt, clients))
		self.assertTrue(any(results))
		# Explicit new request, same revision/hash; never retry within old transaction.
		results = [result or client.api("execute", binding=binding(p)) for client, result in zip(clients, results)]
		self.assertEqual(results[0]["result"], results[1]["result"])
		self.assertEqual(self.note()["generation"], 1)

	def test_09_audit_failure_rolls_back_normal_note_save(self):
		p = self.submit(); self.approve(p)
		try:
			self.permission("HV Proposal Audit", "HV Proposal Agent", 0, "create", 0)
			with self.assertRaises(HTTPFailure): self.execute(p)
			self.assertEqual(self.note()["label"], "before")
			self.assertEqual(self.note()["generation"], 0)
			self.assertEqual(self.agent.api("view", proposal_id=p["id"])["status"], "Approved")
		finally:
			self.permission("HV Proposal Audit", "HV Proposal Agent", 0, "create", 1)
		self.assertEqual(self.execute(p)["status"], "Succeeded")
		self.assertEqual(self.note()["generation"], 1)

	def upstream_only_editor(self, reject):
		# Exactly two users: reviewer A may see only target A; agent B can read A
		# and creates a dependent proposal for target B. No downstream business
		# rights are granted to A, before or after graph invalidation.
		target_b = "SYN-DOWNSTREAM-" + uuid4().hex[:12]
		note_b = self.reviewer.resource("HV Synthetic Note", data={"synthetic_id":target_b,"label":"private downstream"})
		permission = self.admin.resource("User Permission", data={"user":"reviewer@hv4.invalid","allow":"HV Synthetic Note","for_value":self.target,"apply_to_all_doctypes":1})
		try:
			a = self.reviewer.api("submit",key=uuid4().hex,package=self.package,payload={"target":self.target,"label":"upstream"})
			b = self.agent.api("submit",key=uuid4().hex,package=self.package,payload={"target":target_b,"label":"downstream planned"},dependencies=[binding(a)])
			with self.assertRaises(HTTPFailure): self.reviewer.resource("HV Synthetic Note",target_b)
			if reject:
				changed = self.reviewer.api("review",binding=binding(a),approve=False)
				self.assertEqual(changed["status"],"Rejected")
			else:
				changed = self.reviewer.api("revise",binding=binding(a),payload={"target":self.target,"label":"upstream revised"})
				self.assertEqual(changed["revision"],2)
			self.assertNotIn(target_b,json.dumps(changed))
			self.assertNotIn(b["id"],json.dumps(changed))
			self.assertEqual(self.agent.api("view",proposal_id=b["id"])["status"],"Stale")
			events = self.agent.api("audit",proposal_id=b["id"])
			self.assertEqual(events[-1]["kind"],"Stale")
			self.assertEqual(events[-1]["actor"],"reviewer@hv4.invalid")
			with self.assertRaises(HTTPFailure): self.reviewer.resource("HV Synthetic Note",target_b)
			with self.assertRaises(HTTPFailure): self.reviewer.api("view",proposal_id=b["id"])
			visible = self.reviewer.call(PREFIX+"list_proposals",{})
			self.assertNotIn(b["id"],json.dumps(visible))
			self.assertNotIn("_server_messages",visible)
			after = self.agent.resource("HV Synthetic Note",target_b)
			self.assertEqual({k:after[k] for k in ("label","generation","modified")},{k:note_b[k] for k in ("label","generation","modified")})
		finally:
			self.admin.resource("User Permission",permission["name"],method="DELETE")

	def test_10_upstream_revision_invalidates_unreadable_downstream(self):
		self.upstream_only_editor(reject=False)

	def test_11_upstream_rejection_invalidates_unreadable_downstream(self):
		self.upstream_only_editor(reject=True)


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--synthetic", action="store_true", required=True)
	parser.add_argument("--base-url", required=True)
	parser.add_argument("--auth-file", required=True)
	args = parser.parse_args()
	url = parse.urlsplit(args.base_url)
	if url.scheme != "http" or url.hostname != "127.0.0.1": parser.error("Loopback HTTP only")
	auth = json.loads(Path(args.auth_file).read_text())
	if auth.get("purpose") != "hv-proposals-disposable-testauth": parser.error("New marked disposable TESTAUTH required")
	SiteContracts.base, SiteContracts.auth = args.base_url, auth
	result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SiteContracts))
	raise SystemExit(0 if result.wasSuccessful() else 1)
