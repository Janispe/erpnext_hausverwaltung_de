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
from hausverwaltung.proposals import domain as d, registry


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

	def test_confidence_is_hash_bound_and_optional_for_existing_revisions(self):
		meta = {"title": "Buchung", "summary": "Test"}
		before = d.metadata(meta)
		self.assertNotIn("confidence", before)
		after = d.metadata(meta | {"confidence": {"level": "hoch", "score": 0.9}})
		self.assertNotEqual(d.digest(before), d.digest(after))
		for invalid in ({"level": "unknown"}, {"level": "hoch", "score": True},
			{"level": "hoch", "score": float("nan")}, {"level": "hoch", "score": 1.1}):
			with self.subTest(invalid=invalid), self.assertRaises(ValueError):
				d.metadata(meta | {"confidence": invalid})

	def test_bank_actions_and_receipt_surface_are_registered(self):
		self.assertEqual({registry.ACTIONS[key].kind for key in registry.BANK_ACTION_NAMES},
			{"party", "invoice", "split", "abschlag", "kredit", "payment", "transfer", "journal"})
		self.assertTrue(registry.public(d.ACTION))
		self.assertFalse(registry.public("hv.cash_receipt.book/v1"))
		self.assertNotIn("confirmed_after_contract_end_invoices",
			registry.ACTIONS["hv.bankimport.reconcile_invoices/v1"].parameters)


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
		self.fake.ValidationError = ValueError
		self.fake.QueryDeadlockError = RuntimeError
		self.fake.DoesNotExistError = Missing
		self.fake.conf = {"hv_proposals_synthetic_enabled": True}
		self.fake.flags = {}
		self.fake.session = self.session
		self.fake.local = SimpleNamespace(request=self.request, login_manager=SimpleNamespace(user=self.session.user), message_log=[])
		self.fake.db = SimpleNamespace(get_value=lambda *a, **kw: self.user)
		self.fake.get_roles = lambda user=None: list(self.roles)
		def throw(message, exception=ValueError):
			self.fake.local.message_log.append({"message": message})
			raise exception(message)
		self.fake.throw = throw
		self.fake.whitelist = lambda **kwargs: lambda f: f
		utils = ModuleType("frappe.utils");utils.now_datetime = lambda: None
		document = ModuleType("frappe.model.document");document.Document = object
		self.modules = patch.dict(sys.modules, {"frappe": self.fake, "frappe.utils": utils,
			"frappe.model": ModuleType("frappe.model"), "frappe.model.document": document})
		self.modules.start()
		for name in ("hausverwaltung.proposals.frappe_service", "hausverwaltung.proposals.frappe_guards", "hausverwaltung.proposals.doc_actions"):
			sys.modules.pop(name, None)
		self.service = importlib.import_module("hausverwaltung.proposals.frappe_service")

	def tearDown(self):
		for name in ("hausverwaltung.proposals.frappe_service", "hausverwaltung.proposals.frappe_guards", "hausverwaltung.proposals.doc_actions"):
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

	def test_administrator_reviews_but_never_acts_as_agent(self):
		# Frappe gibt Administrator jede Rolle, auch die Agentenrolle.
		self.roles.update({"HV Proposal Agent", "System Manager"})
		self.session.user = "Administrator"
		self.fake.local.login_manager.user = "Administrator"
		try:
			self.assertEqual(self.service._actor(human=True), "Administrator")
			self.assertIn("HV Proposal Reviewer", self.service.roles_of("Administrator"))
			self.assertNotIn("HV Proposal Agent", self.service.roles_of("Administrator"))
			self.assertIn("HV Proposal Agent", self.service.roles_of("reviewer-synthetic"))
			# Prüfen ja, einreichen nie: sonst könnte Administrator eigene Vorschläge freigeben.
			with self.assertRaises(self.Denied):
				self.service.submit("admin-key", "ADMIN-PKG", {"label": "x"})
			with self.assertRaises(self.Denied):
				self.service.revise({"id": "HVP-1", "revision": 1, "hash": "0" * 64}, {"label": "x"})
		finally:
			del self.session.user
			self.fake.local.login_manager.user = self.session.user
		with self.assertRaises(self.Denied):
			self.service._actor(human=True)

	def test_administrator_cannot_approve_existing_own_proposal(self):
		# Bestandsvorschläge aus der Zeit, als Administrator noch einreichen konnte.
		from unittest.mock import MagicMock

		self.roles.update({"HV Proposal Agent", "System Manager"})
		self.session.user = "Administrator"
		self.fake.local.login_manager.user = "Administrator"
		admin, agent = "Administrator", "agent-synthetic"
		# (Vorschlag, aktuelle Revision, Ereignisse als (Art, Akteur, Revision))
		cases = {
			"HVP-OWN": (1, [("Created", admin, 1)]),
			"HVP-FOREIGN": (1, [("Created", agent, 1)]),
			"HVP-ADMIN-REVISION": (2, [("Created", agent, 1), ("Revised", admin, 2)]),
			"HVP-SUPERSEDED": (3, [("Created", agent, 1), ("Revised", admin, 2), ("Revised", agent, 3)]),
		}
		audit = [{"proposal": name, "kind": kind, "actor": actor, "number": number, "revision_hash": f"h{number}"}
			for name, (_, events) in cases.items() for kind, actor, number in events]
		self.fake.db.exists = lambda doctype, filters: doctype == self.service.AUDIT and any(
			all(event[key] == value for key, value in filters.items()) for event in audit)
		docs = {name: SimpleNamespace(name=name, action=self.service.domain.ACTION, status="Pending",
			current_revision=revision, revision_hash=f"h{revision}") for name, (revision, _) in cases.items()}
		approve = MagicMock()
		stubs = {"_binding": lambda binding: binding, "_lock_for": lambda name: None,
			"_exact": lambda binding: (docs[binding["id"]], {}), "_target": lambda body, right: None,
			"_checked": lambda doc, body: {"status": "Pending"}, "_fresh": lambda doc, body: None,
			"_approve": approve, "_event": lambda *a, **kw: None, "_invalidate": lambda *a, **kw: None,
			"_response": lambda doc, body: {"status": doc.status}}

		def ref(name):
			return {"id": name, "revision": docs[name].current_revision, "hash": "0" * 64}

		try:
			with patch.multiple(self.service, **stubs):
				for blocked in ("HVP-OWN", "HVP-ADMIN-REVISION"):
					with self.assertRaises(self.Denied):
						self.service.review(ref(blocked), True)
				approve.assert_not_called()
				self.assertEqual(self.service.review(ref("HVP-OWN"), False, "passt nicht")["status"], "Rejected")
				for allowed in ("HVP-FOREIGN", "HVP-SUPERSEDED"):
					self.service.review(ref(allowed), True)
				self.assertEqual([call.args[0].name for call in approve.call_args_list],
					["HVP-FOREIGN", "HVP-SUPERSEDED"])
		finally:
			del self.session.user
			self.fake.local.login_manager.user = self.session.user

	def test_administrator_executes_only_with_browser_session(self):
		from unittest.mock import MagicMock

		class Reached(Exception):
			pass

		self.roles.update({"HV Proposal Agent", "System Manager"})
		self.session.user = "Administrator"
		self.fake.local.login_manager.user = "Administrator"
		ref = {"id": "HVP-1", "revision": 1, "hash": "0" * 64}
		loaded = MagicMock(side_effect=Reached)
		try:
			with patch.multiple(self.service, _binding=loaded, _bindings=loaded):
				# API-Schlüssel statt Browser-Sitzung: abgewiesen, bevor ein Vorschlag geladen wird.
				self.request.headers["Authorization"] = "token synthetic:secret"
				with self.assertRaises(self.Denied):
					self.service.execute(ref)
				with self.assertRaises(self.Denied):
					self.service.execute_ready("PKG", [ref])
				loaded.assert_not_called()
				# Mit echter Browser-Sitzung geht es weiter bis zum Laden.
				self.request.headers.clear()
				with self.assertRaises(Reached):
					self.service.execute(ref)
				with self.assertRaises(Reached):
					self.service.execute_ready("PKG", [ref])
		finally:
			self.request.headers.clear()
			del self.session.user
			self.fake.local.login_manager.user = self.session.user

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

	def test_api_normalizes_core_emitted_messages_and_exception_context(self):
		@self.service._api
		def endpoint(): return self.service._note("SYN-PRIVATE")
		def missing(*args, **kwargs): self.fake.throw("HV Synthetic Note SYN-PRIVATE not found", self.fake.DoesNotExistError)
		self.fake.get_doc = missing
		with self.assertRaises(self.Denied) as absent: endpoint()
		absent_messages = list(self.fake.local.message_log)
		self.assertTrue(absent.exception.__suppress_context__)
		self.fake.local.message_log = []
		self.fake.get_doc = lambda *a, **kw: SimpleNamespace()
		self.fake.has_permission = lambda *a, **kw: False
		with self.assertRaises(self.Denied) as forbidden: endpoint()
		self.assertEqual(self.fake.local.message_log, absent_messages)
		self.assertEqual(absent_messages, [{"message": "Proposal operation unavailable"}])
		self.assertTrue(forbidden.exception.__suppress_context__)

	def test_concurrent_snapshot_error_requires_new_request_and_hides_db_detail(self):
		@self.service._api
		def endpoint(): raise self.fake.QueryDeadlockError("synthetic SQL detail")
		with self.assertRaises(self.service.ConcurrentRevisionRetry) as retry: endpoint()
		self.assertEqual(retry.exception.http_status_code, 409)
		self.assertTrue(retry.exception.__suppress_context__)
		self.assertNotIn("SQL", str(retry.exception))

	def test_response_exposes_direct_bindings_separately_from_transitive_preview(self):
		direct = {"id": "direct", "revision": 2, "hash": "a" * 64}
		body = {"dependencies": [direct], "preview": {"dependencies": [direct, {"id": "ancestor"}]}}
		doc = SimpleNamespace(name="child",current_revision=1,revision_hash="b"*64,status="Pending",package="group",result=None)
		response = self.service._response(doc, body)
		self.assertEqual(response["dependencies"], [direct])
		self.assertEqual(response["package"], "group")
		self.assertNotEqual(response["dependencies"], response["preview"]["dependencies"])

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




class PackageContracts(unittest.TestCase):
	setUp = AdapterContracts.setUp
	tearDown = AdapterContracts.tearDown
	def test_metadata_limits_and_hash_binding(self):
		base = {"title": "T", "summary": "S"}
		valid = d.metadata(base | {"lane":{"key":"K","label":"L"},"sources":[{"label":"Evidence"}]})
		for field, maximum in (("title",80),("summary",140),("rationale",2000)):
			with self.assertRaises(ValueError): d.metadata(base | {field:"x"*(maximum+1)})
		with self.assertRaises(ValueError): d.metadata(base | {"sources":[{"label":"x"}]*11})
		with self.assertRaises(ValueError): d.metadata(base | {"lane":{"key":"x"*81,"label":"x"}})
		for field in ("title","summary","rationale","sources","lane"):
			other = valid | {field: "different"}
			self.assertNotEqual(d.digest(valid),d.digest(other))

	def test_read_endpoints_never_enable_write_context(self):
		for method,args,helper in [("view",("p",),"_load"),("audit",("p",),"_load"),
			("list_proposals",(),"get_all"),("list_packages",(),"get_all"),("package_graph",("g",),"_visible")]:
			def guard(*a, **kw):
				self.assertFalse(self.service._writing.get())
				raise LookupError("read reached")
			target = self.fake if helper == "get_all" else self.service
			with patch.object(target,helper,guard,create=True):
				with self.assertRaises(LookupError): getattr(self.service,method)(*args)

	def test_note_and_body_read_without_rowlocks(self):
		calls=[]
		note=SimpleNamespace(docstatus=0,synthetic_id="SYN-A",meta=SimpleNamespace(get_permitted_fieldnames=lambda **kw:{"label","generation","synthetic_id"}))
		body={"dependencies":[]}
		rev=SimpleNamespace(body=json.dumps(body),revision_hash=d.digest(body))
		def get_doc(doctype,*a,**kw):
			calls.append(kw);return note if doctype==self.service.NOTE else rev
		self.fake.get_doc=get_doc;self.fake.has_permission=lambda *a,**kw:True;self.fake.parse_json=json.loads
		self.service._note("SYN-A");self.service._body(SimpleNamespace(name="p",current_revision=1,revision_hash=rev.revision_hash))
		self.assertTrue(all(c.get("for_update") is False for c in calls))

	def test_effective_stale_read_does_not_write_and_write_returns_normally(self):
		doc=SimpleNamespace(name="p",current_revision=1,revision_hash="a"*64,status="Pending",package="g",result=None)
		cause={"cause":"baseline_changed","proposal":None,"detail":"changed"}
		with patch.object(self.service,"_stale_cause",return_value=cause),patch.object(self.service,"_event") as event,patch.object(self.service,"_invalidate"):
			self.assertEqual(self.service._checked(doc,{"preview":{},"dependencies":[]},persist=False)["status"],"Stale")
			self.assertEqual(doc.status,"Pending");event.assert_not_called()
			self.assertEqual(self.service._checked(doc,{"preview":{},"dependencies":[]})["status"],"Stale")
			event.assert_called_once_with(doc,"Stale",cause)

	def test_rejection_requires_reason_before_any_lock(self):
		with patch.object(self.service,"_lock_for") as lock:
			with self.assertRaises(ValueError): self.service.review({"id":"p","revision":1,"hash":"a"*64},False)
			lock.assert_not_called()

	def test_review_many_savepoint_partial_success(self):
		self.fake.db.savepoint=lambda x:None;rolled=[];self.fake.db.rollback=lambda **kw:rolled.append(kw)
		refs=[{"id":x,"revision":1,"hash":"a"*64} for x in "abc"]
		with patch.object(self.service,"review",side_effect=[{"status":"Approved"},ValueError("bad"),{"status":"Stale"}]):
			result=self.service.review_many(refs)
		self.assertEqual([r["ok"] for r in result],[True,False,False]);self.assertEqual(len(rolled),1)

	def test_execute_ready_topological_skip_and_stop(self):
		refs={x:{"id":x,"revision":1,"hash":"a"*64} for x in "abc"}
		docs={x:SimpleNamespace(name=x,target="SYN-"+x,package="g",status="Approved") for x in refs}
		bodies={x:{"action":d.ACTION,"payload":{"target":"SYN-"+x},"dependencies":[refs["a"]] if x=="b" else []} for x in refs}
		self.fake.db.savepoint=lambda x:None;self.fake.db.rollback=lambda **kw:None
		def execute(ref):
			if ref["id"]=="b": raise ValueError("stop")
			docs[ref["id"]].status="Succeeded";return {"status":"Succeeded"}
		with patch.object(self.service,"_note"),patch.object(self.service,"_checked",side_effect=lambda doc,body:{"status":doc.status}),patch.object(self.service,"_lock_package"),patch.object(self.service,"_exact",side_effect=lambda ref:(docs[ref["id"]],bodies[ref["id"]])),patch.object(self.service,"execute",side_effect=execute):
			result=self.service.execute_ready("g",[refs[x] for x in "bac"])
		self.assertEqual([r["id"] for r in result],["a","b"])
		self.assertTrue(result[0]["ok"]);self.assertFalse(result[1]["ok"])

	def test_each_dependency_stale_cause(self):
		ref={"id":"parent","revision":1,"hash":"a"*64}
		doc=SimpleNamespace(name="child",status="Pending")
		parent=SimpleNamespace(name="parent",target="SYN-PARENT",current_revision=1,revision_hash="a"*64,status="Rejected")
		with patch.object(self.fake,"get_doc",return_value=parent,create=True),patch.object(self.service,"_note"):
			self.assertEqual(self.service._stale_cause(doc,{"dependencies":[ref]})["cause"],"dependency_rejected")
			parent.status="Stale"
			self.assertEqual(self.service._stale_cause(doc,{"dependencies":[ref]})["cause"],"dependency_stale")
			parent.current_revision=2
			self.assertEqual(self.service._stale_cause(doc,{"dependencies":[ref]})["cause"],"dependency_revised")

	def test_invalidation_audit_has_cause_id_and_detail(self):
		child=SimpleNamespace(name="child",event_sequence=1,target="SYN-B",current_revision=1,revision_hash="a"*64)
		queries=[];self.fake.db.sql=lambda query,args:queries.append((query,args));self.fake.clear_document_cache=lambda *a:None
		for cause in ("dependency_rejected","dependency_revised","dependency_stale"):
			self.service._invalidate_metadata(child,"parent",cause)
			detail=json.loads(queries[-1][1][-1])
			self.assertEqual(detail["cause"],cause);self.assertEqual(detail["proposal"],"parent");self.assertTrue(detail["detail"])

	def test_core_has_no_pe_or_sqlite_import_and_one_action(self):
		for path in (APP / "proposals").glob("*.py"):
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node,ast.Import): names=[a.name for a in node.names]
				elif isinstance(node,ast.ImportFrom): names=[node.module or ""]
				else: continue
				self.assertFalse(any(n.startswith(("process_engine","sqlite3")) for n in names))
		self.assertEqual(d.ACTION,"hv.synthetic_note.set_label/v1")

	def test_generic_package_read_requires_reference_rights_for_requested_user(self):
		doc=SimpleNamespace(doctype=self.service.PACKAGE,name="package",reference_doctype="HV Synthetic Note",reference_name="SYN-PRIVATE")
		self.fake.local.message_log=[{"message":"existing"}]
		self.fake.flags["has_permission_check_logs"]=["existing permission"]
		def deny_reference(*args,**kwargs):
			self.fake.flags["has_permission_check_logs"].append("private reference name")
			self.fake.throw("private reference",self.Denied)
		with patch.object(self.service,"_visible",return_value=[object()]),patch.object(self.service,"_reference",side_effect=deny_reference) as reference:
			self.assertFalse(self.service.readable_record(doc,"other-user"))
			reference.assert_called_once_with("HV Synthetic Note","SYN-PRIVATE",user="other-user")
		self.assertEqual(self.fake.local.message_log,[{"message":"existing"}])
		self.assertEqual(self.fake.flags["has_permission_check_logs"],["existing permission"])
		with patch.object(self.service,"_visible",return_value=[object()]),patch.object(self.service,"_reference",return_value=None):
			self.assertTrue(self.service.readable_record(doc,"other-user"))

	def test_doc_payload_validation_and_target_generation(self):
		created = d.doc_payload(d.DOC_CREATE_ACTION, {"doctype": "Customer", "values": {"customer_name": "Test"}})
		self.assertEqual(created, {"doctype": "Customer", "values": {"customer_name": "Test"}, "submit": False})
		self.assertEqual(d.doc_target(d.DOC_CREATE_ACTION, created), "NEW:Customer")
		updated = d.doc_payload(d.DOC_UPDATE_ACTION, {"doctype": "Customer", "name": "C-1", "values": {"customer_name": "Neu"}})
		self.assertEqual(d.doc_target(d.DOC_UPDATE_ACTION, updated), "C-1")
		submitted = d.doc_payload(d.DOC_SUBMIT_ACTION, {"doctype": "Sales Invoice", "name": "SINV-1"})
		self.assertEqual(d.doc_target(d.DOC_SUBMIT_ACTION, submitted), "SINV-1")
		for bad_action, bad_payload in (
			(d.DOC_CREATE_ACTION, {"doctype": "Customer", "values": {}}),
			(d.DOC_CREATE_ACTION, {"doctype": "Customer", "values": {"a": 1}, "submit": "yes"}),
			(d.DOC_UPDATE_ACTION, {"doctype": "Customer", "values": {"a": 1}}),
			(d.DOC_SUBMIT_ACTION, {"doctype": "Sales Invoice", "name": "SINV-1", "values": {"a": 1}}),
		):
			with self.assertRaises(ValueError):
				d.doc_payload(bad_action, bad_payload)

	def test_production_and_synthetic_flags_stay_isolated(self):
		self.fake.conf = {"hv_proposals_enabled": True}
		self.assertEqual(self.service._enabled_actions(), list(d.DOC_ACTIONS))
		with self.assertRaises(self.Denied):
			self.service.enabled(d.ACTION)
		self.service.enabled(d.DOC_CREATE_ACTION)
		self.fake.conf = {"hv_proposals_synthetic_enabled": True}
		self.assertEqual(self.service._enabled_actions(), [d.ACTION, *registry.BANK_ACTION_NAMES])
		with self.assertRaises(self.Denied):
			self.service.enabled(d.DOC_CREATE_ACTION)

	def test_bank_response_hides_internal_state_from_public_result(self):
		doc = SimpleNamespace(
			name="HVP-BANK-1",
			current_revision=1,
			revision_hash="a" * 64,
			status="Succeeded",
			package="BANK-1",
			action="hv.bankimport.assign_party/v1",
			result=json.dumps({
				"doctype": "Bank Transaction",
				"id": "BT-1",
				"name": "BT-1",
				"by": "rev@hv4.invalid",
				"at": "2026-11-18",
				"state": {"bank_transaction": "BT-1", "allocated": 100},
			}),
		)
		body = {"action": doc.action, "dependencies": [], "preview": {}}
		with patch.object(self.fake, "parse_json", json.loads, create=True):
			response = self.service._response(doc, body)
		self.assertEqual(set(response["result"]), {"doctype", "id", "name", "by", "at"})
		self.assertNotIn("state", response["result"])

	def test_doc_actions_module_has_no_bypass_and_blocks_sensitive_doctypes(self):
		doc_actions = importlib.import_module("hausverwaltung.proposals.doc_actions")
		tree = ast.parse((APP / "proposals/doc_actions.py").read_text())
		for node in ast.walk(tree):
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
				self.assertNotIn(node.func.attr, {"commit", "set_user"})
				self.assertFalse(any(kw.arg == "ignore_permissions" for kw in node.keywords))
		for blocked in ("User", "Has Role", "User Permission", "Server Script", "HV Action Proposal", "FAC Tool Configuration"):
			with self.assertRaises(self.Denied):
				doc_actions._allowed_doctype(blocked)

	def test_doc_actions_execute_requires_human_session(self):
		self.fake.conf = {"hv_proposals_enabled": True}
		self.roles = {"HV Proposal Agent"}
		self.session.user = "agent-doc"
		doc = SimpleNamespace(name="HVP-1", current_revision=1, revision_hash="a" * 64, action=d.DOC_CREATE_ACTION, package="pkg", status="Approved", target="NEW:Customer")
		body = {"action": d.DOC_CREATE_ACTION, "policy": d.DOC_POLICY, "payload": {"doctype": "Customer", "values": {"customer_name": "A"}, "submit": False}, "dependencies": [], "preview": {}}
		with patch.object(self.service, "_lock_for"), patch.object(self.service, "_exact", return_value=(doc, body)):
			with self.assertRaises(self.Denied):
				self.service.execute({"id": "HVP-1", "revision": 1, "hash": "a" * 64})

	def test_doc_actions_read_checks_field_and_table_permissions(self):
		doc_actions = importlib.import_module("hausverwaltung.proposals.doc_actions")
		child_meta = SimpleNamespace(
			istable=True,
			is_virtual=False,
			fields=[SimpleNamespace(fieldname="phone", fieldtype="Data"), SimpleNamespace(fieldname="secret_col", fieldtype="Data")],
			get_permitted_fieldnames=lambda parenttype=None, user=None, permission_type="read": (
				{"phone", "secret_col"} if user == "privileged" else {"phone"}
			),
		)
		parent_meta = SimpleNamespace(
			name="Contact",
			module="Contacts",
			issingle=False,
			istable=False,
			is_virtual=False,
			is_submittable=False,
			get_field=lambda f: {
				"first_name": SimpleNamespace(fieldname="first_name", fieldtype="Data"),
				"secret_note": SimpleNamespace(fieldname="secret_note", fieldtype="Data"),
				"phone_nos": SimpleNamespace(fieldname="phone_nos", fieldtype="Table", options="Contact Phone"),
			}.get(f),
			get_permitted_fieldnames=lambda user=None, permission_type="read": (
				{"first_name", "secret_note", "phone_nos"} if user == "privileged" else {"first_name", "phone_nos"}
			),
		)
		target_doc = SimpleNamespace(
			doctype="Contact",
			name="CON-1",
			docstatus=0,
			get=lambda f: [{"phone": "123", "secret_col": "hidden"}] if f == "phone_nos" else None,
		)
		self.fake.get_meta = lambda dt: child_meta if dt == "Contact Phone" else parent_meta
		self.fake.get_doc = lambda *a, **kw: target_doc
		self.fake.has_permission = lambda *a, **kw: True

		scalar_payload = {"doctype": "Contact", "name": "CON-1", "values": {"secret_note": "neu"}}
		scalar_preview = {"changes": [{"field": "secret_note", "before": "alt", "after": "neu"}]}
		self.assertIs(
			doc_actions.check_read_access(d.DOC_UPDATE_ACTION, scalar_payload, user="privileged", preview=scalar_preview),
			target_doc,
		)
		with self.assertRaises(self.Denied):
			doc_actions.check_read_access(d.DOC_UPDATE_ACTION, scalar_payload, user="restricted", preview=scalar_preview)

		table_payload = {"doctype": "Contact", "name": "CON-1", "values": {"phone_nos": [{"phone": "456"}]}}
		self.assertIs(
			doc_actions.check_read_access(d.DOC_UPDATE_ACTION, table_payload, user="privileged"),
			target_doc,
		)
		with self.assertRaises(self.Denied):
			doc_actions.check_read_access(d.DOC_UPDATE_ACTION, table_payload, user="restricted")

		cleaned_doc = SimpleNamespace(doctype="Contact", name="CON-1", docstatus=0, get=lambda f: [] if f == "phone_nos" else None)
		self.fake.get_doc = lambda *a, **kw: cleaned_doc
		cleaned_payload = {"doctype": "Contact", "name": "CON-1", "values": {"phone_nos": [{"phone": "789"}]}}
		snapshot_preview = {
			"before": {"child_fields": {"phone_nos": ["phone", "secret_col"]}},
			"changes": [{"field": "phone_nos", "before": '[{"phone": "123", "secret_col": "hidden"}]', "after": '[{"phone": "789"}]'}],
		}
		self.assertIs(
			doc_actions.check_read_access(d.DOC_UPDATE_ACTION, cleaned_payload, user="privileged", preview=snapshot_preview),
			cleaned_doc,
		)
		with self.assertRaises(self.Denied):
			doc_actions.check_read_access(d.DOC_UPDATE_ACTION, cleaned_payload, user="restricted", preview=snapshot_preview)
		with self.assertRaises(self.Denied):
			doc_actions.check_read_access(
				d.DOC_UPDATE_ACTION,
				cleaned_payload,
				user="restricted",
				preview={"changes": snapshot_preview["changes"]},
			)

	def test_doc_actions_preview_formats_full_tables_and_long_strings(self):
		doc_actions = importlib.import_module("hausverwaltung.proposals.doc_actions")
		table_a = doc_actions._format_value([{"account": "4000", "amount": 100}, {"account": "4100", "amount": 200}])
		table_b = doc_actions._format_value([{"account": "4000", "amount": 100}, {"account": "4100", "amount": 999}])
		self.assertNotEqual(table_a, table_b)
		self.assertIn("999", table_b)
		self.assertIn("200", table_a)
		long_a = "A" * 300 + "TAIL_ONE"
		long_b = "A" * 300 + "TAIL_TWO"
		self.assertEqual(doc_actions._format_value(long_a), long_a)
		self.assertNotEqual(doc_actions._format_value(long_a), doc_actions._format_value(long_b))


if __name__ == "__main__": unittest.main()
