"""Real SQLite contracts, synthetic data only; no Frappe imports or site."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "hausverwaltung/proposals/pilot.py"
sys.path.insert(0, str(SOURCE.parents[2]))
from hausverwaltung.proposals import pilot as m


def bind(p):
	return {k: p[k] for k in ("id", "revision", "hash")}


class PilotContracts(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.path = str(Path(self.tmp.name) / "synthetic.sqlite")
		self.p = m.Pilot(self.path, synthetic=True)
		self.ai = m.Identity("agent")
		self.human = m.Identity("reviewer", human=True)
		self.grants = {"agent": ["read", "propose", "execute"], "reviewer": ["read", "approve"]}
		for target in ("SYN-A", "SYN-B", "SYN-C"):
			self.p.seed(target, "old", self.grants)

	def tearDown(self):
		self.p.close()
		self.tmp.cleanup()

	def create(self, label="new", deps=None, target="SYN-A", key=None, package="package"):
		return self.p.create(self.ai, key or label, package, {"target": target, "label": label}, deps)

	def approve(self, p):
		return self.p.decide(self.human, bind(p), approve=True)

	def execute(self, p):
		return self.p.execute(self.ai, bind(p))

	def state(self, target="SYN-A"):
		return dict(self.p.db.execute("SELECT label,version FROM note WHERE id=?", (target,)).fetchone())

	def test_preview_is_direct_and_never_writes_target(self):
		p = self.create()
		self.assertEqual(self.state(), {"label": "old", "version": 0})
		self.assertEqual(p["preview"]["before"], self.state())
		self.assertEqual(p["preview"]["after"], {"label": "new", "version": 1})
		self.assertEqual(p["preview"]["effects"], [])
		self.assertTrue(p["preview"]["limits"])
		p["preview"]["after"]["label"] = "tamper"
		self.assertEqual(self.p.get(self.ai, p["id"])["preview"]["after"]["label"], "new")

	def test_explicit_optin_and_static_registry(self):
		with self.assertRaises(m.Denied):
			m.Pilot(":memory:")
		with self.assertRaises(ValueError):
			self.p.create(self.ai, "k", "p", {"target": "SYN-A", "label": "x"}, action="frappe.get_doc")
		for data in ({"target": "SYN-A", "label": "x", "doctype": "Customer"},
					 {"target": "Customer", "label": "x"}, {"target": "SYN-A", "label": 1}):
			with self.assertRaises(ValueError):
				self.p.create(self.ai, "k", "p", data)

	def test_human_and_exact_revision_required(self):
		p = self.create()
		with self.assertRaises(m.Conflict):
			self.execute(p)
		with self.assertRaises(m.Denied):
			self.p.decide(self.ai, bind(p), approve=True)
		wrong = bind(p) | {"hash": "wrong"}
		with self.assertRaises(m.Conflict):
			self.p.decide(self.human, wrong, approve=True)
		self.approve(p)
		self.assertEqual(self.execute(p)["status"], "Succeeded")

	def test_revise_invalidates_approval_and_immutable_db_history(self):
		p = self.create()
		self.approve(p)
		revised = self.p.revise(self.ai, bind(p), {"target": "SYN-A", "label": "revised"})
		self.assertEqual(revised["revision"], 2)
		self.assertEqual(revised["status"], "Pending")
		with self.assertRaises(m.Conflict):
			self.execute(p)
		with self.assertRaises(m.Conflict):
			self.execute(revised)
		with self.assertRaises(sqlite3.IntegrityError):
			self.p.db.execute("UPDATE revision SET hash='fake'")
		with self.assertRaises(sqlite3.IntegrityError):
			self.p.db.execute("DELETE FROM event")
		self.assertEqual(self.p.db.execute("SELECT COUNT(*) FROM revision").fetchone()[0], 2)

	def test_permissions_rechecked_on_preview_decision_execute_retry(self):
		p = self.create()
		self.p.db.execute("DELETE FROM grant_rule WHERE actor='reviewer' AND capability='approve'")
		with self.assertRaises(m.Denied):
			self.approve(p)
		self.p.db.execute("INSERT INTO grant_rule VALUES('reviewer','SYN-A','approve')")
		self.approve(p)
		self.p.db.execute("DELETE FROM grant_rule WHERE actor='agent' AND capability='execute'")
		with self.assertRaises(m.Denied):
			self.execute(p)
		self.assertEqual(self.state()["label"], "old")
		self.p.db.execute("DELETE FROM grant_rule WHERE actor='agent' AND capability='read'")
		with self.assertRaises(m.Denied):
			self.p.get(self.ai, p["id"])

	def test_baseline_change_requires_new_review(self):
		p = self.create()
		self.approve(p)
		self.p.db.execute("UPDATE note SET label='concurrent',version=1 WHERE id='SYN-A'")
		with self.assertRaises(m.Conflict):
			self.execute(p)
		self.assertEqual(self.p.get(self.ai, p["id"])["status"], "Stale")

	def test_idempotency_and_lost_answer_durable_retry(self):
		p = self.create(key="request")
		self.assertEqual(self.create(key="request")["id"], p["id"])
		with self.assertRaises(m.Conflict):
			self.create("other", key="request")
		self.approve(p)
		result = self.execute(p)
		self.p.close()
		self.p = m.Pilot(self.path, synthetic=True)
		self.assertEqual(self.execute(p)["result"], result["result"])
		self.assertEqual(self.state()["version"], 1)
		self.assertEqual([e["kind"] for e in self.p.audit(self.ai, p["id"])],
						 ["Created", "Approved", "Succeeded", "ResultReused"])

	def test_audit_failure_rolls_back_effect_and_allows_safe_retry(self):
		p = self.create()
		self.approve(p)
		self.p.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON event WHEN NEW.kind='Succeeded' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
		with self.assertRaises(sqlite3.IntegrityError):
			self.execute(p)
		self.assertEqual(self.state()["version"], 0)
		self.assertEqual(self.p.get(self.ai, p["id"])["status"], "Approved")
		self.p.db.execute("DROP TRIGGER fail_audit")
		self.assertEqual(self.execute(p)["status"], "Succeeded")

	def test_concurrent_execute_serializes_and_runs_once(self):
		p = self.create()
		self.approve(p)
		def execute():
			service = m.Pilot(self.path, synthetic=True)
			try:
				return service.execute(self.ai, bind(p))["result"]
			finally:
				service.close()
		with ThreadPoolExecutor(max_workers=2) as pool:
			results = list(pool.map(lambda _: execute(), range(2)))
		self.assertEqual(results[0], results[1])
		self.assertEqual(self.state()["version"], 1)

	def test_projected_then_real_predecessor_never_double_applied(self):
		a = self.create("first")
		b = self.create("second", [bind(a)])
		self.assertEqual(b["preview"]["before"], {"label": "first", "version": 1})
		self.approve(a)
		self.approve(b)
		with self.assertRaises(m.Conflict):
			self.execute(b)
		self.execute(a)
		self.execute(b)
		self.assertEqual(self.state(), {"label": "second", "version": 2})
		c = self.create("third", [bind(b)])
		self.assertEqual([d["mode"] for d in c["preview"]["dependencies"]], ["real", "real"])
		self.assertEqual(c["preview"]["before"]["version"], 2)
		self.approve(c)
		self.execute(c)
		self.assertEqual(self.state()["version"], 3)

	def test_transitive_stale_only_affected_descendants(self):
		a = self.create("a")
		b = self.create("b", [bind(a)])
		c = self.create("c", [bind(b)])
		unrelated = self.create("unrelated", target="SYN-B")
		self.p.revise(self.ai, bind(a), {"target": "SYN-A", "label": "a2"})
		for item in (b, c):
			self.assertEqual(self.p.get(self.ai, item["id"])["status"], "Stale")
		self.assertEqual(self.p.get(self.ai, unrelated["id"])["status"], "Pending")

	def test_reject_invalidates_descendants(self):
		a = self.create("a")
		b = self.create("b", [bind(a)])
		self.p.decide(self.human, bind(a), approve=False)
		self.assertEqual(self.p.get(self.ai, b["id"])["status"], "Stale")

	def test_dag_diamond_counts_common_ancestor_once(self):
		a = self.create("a")
		b = self.create("b", [bind(a)], target="SYN-B")
		c = self.create("c", [bind(a)], target="SYN-C")
		d = self.create("d", [bind(b), bind(c)])
		ids = [dep["id"] for dep in d["preview"]["dependencies"]]
		self.assertEqual(len(ids), 3)
		self.assertEqual(ids.count(a["id"]), 1)

	def test_cycles_wrong_binding_package_and_unordered_writers_block(self):
		a = self.create("a")
		b = self.create("b", [bind(a)])
		with self.assertRaises(m.Conflict):
			self.p.revise(self.ai, bind(a), {"target": "SYN-A", "label": "cycle"}, [bind(b)])
		with self.assertRaises(m.Conflict):
			self.create("wrong", [bind(a) | {"hash": "wrong"}])
		with self.assertRaises(m.Conflict):
			self.create("foreign", [bind(a)], package="other")
		independent = self.create("independent")
		with self.assertRaises(m.Conflict):
			self.create("ambiguous", [bind(a), bind(independent)])

	def test_real_mapping_and_data_tampering_blocks_successor(self):
		a = self.create("a")
		self.approve(a)
		self.execute(a)
		self.p.db.execute("UPDATE proposal SET result=? WHERE id=?", (m.encode({"id": "SYN-WRONG"}), a["id"]))
		with self.assertRaises(m.Conflict):
			self.create("b", [bind(a)])

	def test_dependency_rights_even_after_cache_hit(self):
		a = self.create("a", target="SYN-B")
		b = self.create("b", [bind(a)])
		self.p.db.execute("DELETE FROM grant_rule WHERE target='SYN-B' AND actor='agent'")
		with self.assertRaises(m.Denied):
			self.p.get(self.ai, b["id"])
		with self.assertRaises(m.Denied):
			self.create("b", [bind(a)])

	def test_success_retry_still_checks_dependency_read_rights(self):
		a = self.create("a", target="SYN-B")
		b = self.create("b", [bind(a)])
		for item in (a, b):
			self.approve(item)
			self.execute(item)
		self.p.db.execute("DELETE FROM grant_rule WHERE actor='agent' AND target='SYN-B'")
		for operation in (lambda: self.execute(b), lambda: self.p.get(self.ai, b["id"]),
						  lambda: self.p.audit(self.ai, b["id"])):
			with self.assertRaises(m.Denied):
				operation()

	def test_stale_replay_is_not_approvable_and_audited(self):
		a = self.create(key="key")
		self.p.db.execute("UPDATE note SET version=1 WHERE id='SYN-A'")
		replay = self.create(key="key")
		self.assertEqual(replay["status"], "Stale")
		self.assertFalse(replay["approvable"])
		self.assertTrue(replay["conflicts"])
		self.assertEqual(self.p.audit(self.ai, a["id"])[-1]["kind"], "Stale")

	def test_reviewer_revocation_and_real_data_change_block(self):
		a = self.create("a")
		self.approve(a)
		self.p.db.execute("DELETE FROM grant_rule WHERE actor='reviewer' AND capability='approve'")
		with self.assertRaises(m.Denied):
			self.execute(a)
		self.p.db.execute("INSERT INTO grant_rule VALUES('reviewer','SYN-A','approve')")
		self.execute(a)
		self.p.db.execute("UPDATE note SET label='unexpected' WHERE id='SYN-A'")
		with self.assertRaises(m.Conflict):
			self.create("b", [bind(a)])

	def test_preview_and_revision_only_change_kernel_tables(self):
		before = list(self.p.db.execute("SELECT * FROM note ORDER BY id"))
		grants = list(self.p.db.execute("SELECT * FROM grant_rule ORDER BY actor,target,capability"))
		a = self.create("a")
		self.p.revise(self.ai, bind(a), {"target": "SYN-A", "label": "revised"})
		self.assertEqual(list(self.p.db.execute("SELECT * FROM note ORDER BY id")), before)
		self.assertEqual(list(self.p.db.execute("SELECT * FROM grant_rule ORDER BY actor,target,capability")), grants)

	def test_normal_package_import_without_pe_or_frappe(self):
		package_root = str(SOURCE.parents[2])
		program = ("import sys; sys.path.insert(0, " + repr(package_root) + "); "
				   "from hausverwaltung.proposals.pilot import Pilot, Identity; "
				   "assert 'process_engine' not in sys.modules; "
				   "assert 'frappe' not in sys.modules; "
				   "p=Pilot(':memory:', synthetic=True); p.close()")
		subprocess.run([sys.executable, "-I", "-c", program], check=True, capture_output=True, text=True)


if __name__ == "__main__":
	unittest.main()
