"""DB-free contracts only; these are not authenticated Frappe/site acceptance."""
import ast
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "hausverwaltung"
sys.path.insert(0, str(APP.parent))
from hausverwaltung.proposals import domain as d


class ProjectionContracts(unittest.TestCase):
	def ref(self, pid, number=1):
		return {"id": pid, "revision": number, "hash": "a" * 64}

	def node(self, pid, target, before, label, deps=None, status="Pending"):
		return {"id": pid, "revision": 1, "hash": "a" * 64, "status": status,
			"body": {"action": d.ACTION, "policy": d.POLICY, "payload": {"target": target, "label": label},
			"dependencies": deps or [], "preview": {"before": before,
				"after": {"label": label, "generation": before["generation"] + 1}}}, "result": None}

	def test_diamond_is_exact_and_common_node_once(self):
		old = {"label": "old", "generation": 0}
		nodes = {"a": self.node("a", "SYN-A", old, "a")}
		nodes["b"] = self.node("b", "SYN-B", old, "b", [self.ref("a")])
		nodes["c"] = self.node("c", "SYN-C", old, "c", [self.ref("a")])
		ordered = d.ordered_graph([self.ref("b"), self.ref("c")], lambda ref: nodes[ref["id"]])
		self.assertEqual([n["id"] for n in ordered], ["a", "b", "c"])
		preview = d.project({t: old for t in ("SYN-A", "SYN-B", "SYN-C")}, ordered, {"target": "SYN-A", "label": "next"})
		self.assertEqual(preview["before"], {"label": "a", "generation": 1})
		self.assertEqual(preview["after"]["generation"], 2)

	def test_real_predecessor_not_projected_twice(self):
		node = self.node("a", "SYN-A", {"label": "old", "generation": 0}, "a", status="Succeeded")
		node["result"] = {"doctype": "HV Synthetic Note", "id": "SYN-A", "state": node["body"]["preview"]["after"]}
		nodes = d.ordered_graph([self.ref("a")], lambda _: node)
		preview = d.project({"SYN-A": {"label": "a", "generation": 1}}, nodes, {"target": "SYN-A", "label": "b"})
		self.assertEqual(preview["after"]["generation"], 2)
		self.assertEqual(preview["dependencies"][0]["mode"], "real")
		node["result"]["id"] = "SYN-WRONG"
		with self.assertRaises(ValueError):
			d.project({"SYN-A": {"label": "a", "generation": 1}}, nodes, {"target": "SYN-A", "label": "b"})

	def test_cycle_conflicting_bindings_and_node_limit(self):
		node = self.node("a", "SYN-A", {"label": "old", "generation": 0}, "a", [self.ref("a")])
		with self.assertRaisesRegex(ValueError, "cycle"):
			d.ordered_graph([self.ref("a")], lambda _: node)
		node["body"]["dependencies"] = []
		with self.assertRaisesRegex(ValueError, "Conflicting"):
			d.ordered_graph([self.ref("a"), self.ref("a", 2)], lambda _: node)
		with self.assertRaises(ValueError):
			d.ordered_graph([self.ref(str(i)) for i in range(65)], lambda _: node)

	def test_rejected_stale_unordered_and_policy_block(self):
		old = {"label": "old", "generation": 0}
		a, b = self.node("a", "SYN-A", old, "a"), self.node("b", "SYN-A", old, "b")
		ordered = d.ordered_graph([self.ref("a"), self.ref("b")], lambda ref: {"a": a, "b": b}[ref["id"]])
		with self.assertRaisesRegex(ValueError, "Unordered"):
			d.project({"SYN-A": old}, ordered, {"target": "SYN-A", "label": "next"})
		for status in ["Rejected", "Stale"]:
			a["status"] = status
			with self.assertRaises(ValueError):
				d.project({"SYN-A": old}, [a | {"ancestors": set()}], {"target": "SYN-A", "label": "next"})

	def test_exact_payload_binding_and_revision_digest(self):
		for value in [{"target": "Customer", "label": "x"}, {"target": "SYN-A", "label": " x"},
			{"target": "SYN-A", "label": "x", "doctype": "Customer"}]:
			with self.assertRaises(ValueError): d.payload(value)
		with self.assertRaises(ValueError): d.binding(self.ref("a") | {"revision": True})
		self.assertNotEqual(d.digest({"revision": 1}), d.digest({"revision": 2}))


class AdapterContracts(unittest.TestCase):
	def setUp(self):
		class Denied(Exception): pass
		class Missing(Exception): pass
		self.Denied = Denied
		self.roles = {"HV Proposal Reviewer"}
		self.user = SimpleNamespace(enabled=1, user_type="System User")
		class Session(dict):
			user = "reviewer-synthetic"
		self.session = Session(sid="synthetic-session")
		self.request = SimpleNamespace(cookies={"sid": "synthetic-session"}, headers={})
		self.fake = ModuleType("frappe")
		self.fake.PermissionError = Denied
		self.fake.DoesNotExistError = Missing
		self.fake.conf = {"hv_proposals_synthetic_enabled": True}
		self.fake.session = self.session
		self.fake.local = SimpleNamespace(request=self.request, login_manager=SimpleNamespace(user=self.session.user))
		self.fake.db = SimpleNamespace(get_value=lambda *a, **kw: self.user)
		self.fake.get_roles = lambda user=None: list(self.roles)
		def throw(message, exception=ValueError): raise exception(message)
		self.fake.throw = throw
		self.fake.whitelist = lambda **kwargs: lambda f: f
		utils = ModuleType("frappe.utils");utils.now_datetime = lambda: None
		document = ModuleType("frappe.model.document");document.Document = object
		self.modules = patch.dict(sys.modules, {"frappe": self.fake, "frappe.utils": utils,
			"frappe.model": ModuleType("frappe.model"), "frappe.model.document": document})
		self.modules.start()
		for name in ("hausverwaltung.proposals.frappe_service", "hausverwaltung.proposals.frappe_guards"):
			sys.modules.pop(name, None)
		self.service = importlib.import_module("hausverwaltung.proposals.frappe_service")

	def tearDown(self):
		for name in ("hausverwaltung.proposals.frappe_service", "hausverwaltung.proposals.frappe_guards"):
			sys.modules.pop(name, None)
		self.modules.stop()

	def test_human_gate_uses_server_session_and_separate_roles(self):
		self.assertEqual(self.service._actor(human=True), self.session.user)
		self.roles.add("HV Proposal Agent")
		with self.assertRaises(self.Denied): self.service._actor(human=True)
		self.roles.remove("HV Proposal Agent")
		self.request.headers["Authorization"] = "synthetic-header"
		with self.assertRaises(self.Denied): self.service._actor(human=True)
		self.request.headers.clear();self.request.cookies.clear()
		with self.assertRaises(self.Denied): self.service._actor(human=True)

	def test_disabled_guest_disabled_user_and_website_user_block(self):
		self.fake.conf["hv_proposals_synthetic_enabled"] = False
		with self.assertRaises(self.Denied): self.service._actor()
		self.fake.conf["hv_proposals_synthetic_enabled"] = True
		self.user.enabled = 0
		with self.assertRaises(self.Denied): self.service._actor()
		self.user.enabled = 1;self.user.user_type = "Website User"
		with self.assertRaises(self.Denied): self.service._actor()

	def test_current_object_and_field_rights_are_required(self):
		allowed = {"label", "generation", "synthetic_id"}
		note = SimpleNamespace(docstatus=0, synthetic_id="SYN-A", meta=SimpleNamespace(get_permitted_fieldnames=lambda **kw: allowed))
		self.fake.get_doc = lambda *a, **kw: note
		self.fake.has_permission = lambda *a, **kw: True
		self.assertIs(self.service._note("SYN-A", "write"), note)
		allowed.remove("label")
		with self.assertRaises(self.Denied): self.service._note("SYN-A", "write")
		allowed.add("label");self.fake.has_permission = lambda *a, **kw: False
		with self.assertRaises(self.Denied): self.service._note("SYN-A", "write")

	def test_missing_and_forbidden_targets_have_identical_error(self):
		def missing(*args, **kwargs): raise self.fake.DoesNotExistError("synthetic missing")
		self.fake.get_doc = missing
		with self.assertRaises(self.Denied) as absent:
			self.service._note("SYN-MISSING")
		self.fake.get_doc = lambda *a, **kw: SimpleNamespace()
		self.fake.has_permission = lambda *a, **kw: False
		with self.assertRaises(self.Denied) as forbidden:
			self.service._note("SYN-HIDDEN")
		self.assertEqual(str(absent.exception), str(forbidden.exception))

	def test_managed_records_reject_direct_mutation_and_history_edits(self):
		guards = importlib.import_module("hausverwaltung.proposals.frappe_guards")
		doc = guards.ManagedDocument();doc.is_new = lambda: True
		with self.assertRaises(self.Denied): doc.validate()
		with guards.service_scope(): doc.validate()
		doc.immutable = True;doc.is_new = lambda: False
		with guards.service_scope():
			with self.assertRaises(self.Denied): doc.validate()
		with self.assertRaises(self.Denied): doc.on_trash()

	def test_permission_hook_does_not_replace_normal_write_rights(self):
		guards = importlib.import_module("hausverwaltung.proposals.frappe_guards")
		self.assertIs(guards.can_read(SimpleNamespace(), ptype="write"), True)
		self.assertEqual(guards.no_generic_listing(), "1=0")

	def test_no_identity_claims_or_bypass_in_service_and_normal_save(self):
		tree = ast.parse((APP / "proposals/frappe_service.py").read_text())
		for node in ast.walk(tree):
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
				self.assertNotIn(node.func.attr, {"commit", "set_user"})
				self.assertFalse(any(kw.arg == "ignore_permissions" for kw in node.keywords))
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				self.assertFalse(any(a.arg in {"human", "roles", "user", "identity"} for a in node.args.args) if node.name in {"submit", "review", "execute", "revise"} else False)
		execute = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
		self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "save" and not n.keywords for n in ast.walk(execute)))

	def test_schemas_label_requires_field_level_rights_and_history_no_write(self):
		base = APP / "hv_proposals/doctype"
		note = json.loads((base / "hv_synthetic_note/hv_synthetic_note.json").read_text())
		self.assertEqual(next(f for f in note["fields"] if f["fieldname"] == "label")["permlevel"], 1)
		for slug in ["hv_proposal_revision", "hv_proposal_audit"]:
			schema = json.loads((base / slug / (slug + ".json")).read_text())
			self.assertTrue(all(not perm["write"] for perm in schema["permissions"]))


if __name__ == "__main__": unittest.main()
