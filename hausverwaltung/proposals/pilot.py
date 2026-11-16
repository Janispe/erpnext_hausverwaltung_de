"""Explicitly synthetic, durable local vertical slice.

Only trusted local Python callers may construct this service/Identity. This is
not an authentication adapter, RPC endpoint, or production ERPNext executor.
All data in the supplied SQLite file must be synthetic. No dynamic handlers.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from uuid import uuid4


ACTION = "synthetic.note.set_label/v1"
POLICY = "synthetic-human-review/v1"
LIMITS = ["Synthetic local data only", "No ERPNext hooks simulated", "No external effects"]


class Conflict(ValueError):
	pass


class Denied(PermissionError):
	pass


def encode(value):
	return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
	return hashlib.sha256(encode(value).encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
	"""Trusted host identity, never deserialize this from agent/client input."""

	name: str
	human: bool = False


class Pilot:
	def __init__(self, path, *, synthetic=False):
		if synthetic is not True:
			raise Denied("Explicit synthetic opt-in required")
		self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
		self.db.row_factory = sqlite3.Row
		self.db.executescript("""
			PRAGMA foreign_keys=ON;
			CREATE TABLE IF NOT EXISTS note(id TEXT PRIMARY KEY, label TEXT NOT NULL, version INTEGER NOT NULL);
			CREATE TABLE IF NOT EXISTS grant_rule(actor TEXT, target TEXT, capability TEXT,
				PRIMARY KEY(actor,target,capability));
			CREATE TABLE IF NOT EXISTS proposal(id TEXT PRIMARY KEY, package TEXT NOT NULL,
				revision INTEGER NOT NULL, status TEXT NOT NULL, decision_actor TEXT, result TEXT);
			CREATE TABLE IF NOT EXISTS revision(proposal TEXT REFERENCES proposal(id), number INTEGER,
				hash TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(proposal,number));
			CREATE TABLE IF NOT EXISTS request(actor TEXT, key TEXT, hash TEXT, proposal TEXT,
				PRIMARY KEY(actor,key));
			CREATE TABLE IF NOT EXISTS event(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
				proposal TEXT, actor TEXT, kind TEXT, revision INTEGER, hash TEXT, detail TEXT,
				at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
			CREATE TRIGGER IF NOT EXISTS revision_no_update BEFORE UPDATE ON revision
				BEGIN SELECT RAISE(ABORT,'immutable revision'); END;
			CREATE TRIGGER IF NOT EXISTS revision_no_delete BEFORE DELETE ON revision
				BEGIN SELECT RAISE(ABORT,'immutable revision'); END;
			CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON event
				BEGIN SELECT RAISE(ABORT,'append only audit'); END;
			CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON event
				BEGIN SELECT RAISE(ABORT,'append only audit'); END;
		""")

	def close(self):
		self.db.close()

	@contextmanager
	def _transaction(self):
		self.db.execute("BEGIN IMMEDIATE")
		try:
			yield
			self.db.execute("COMMIT")
		except BaseException:
			self.db.execute("ROLLBACK")
			raise

	def seed(self, target, label, grants):
		"""Trusted fixture setup only, deliberately absent from any client API."""
		if not isinstance(target, str) or not target.startswith("SYN-"):
			raise ValueError("Synthetic target name required")
		self._validate({"target": target, "label": label})
		with self._transaction():
			self.db.execute("INSERT INTO note VALUES(?,?,0)", (target, label))
			for actor, capabilities in grants.items():
				for capability in capabilities:
					if capability not in {"read", "propose", "approve", "execute"}:
						raise ValueError("Unknown capability")
					self.db.execute("INSERT INTO grant_rule VALUES(?,?,?)", (actor, target, capability))

	def _permission(self, actor, target, capability):
		if not isinstance(actor, Identity) or not actor.name:
			raise Denied("Authenticated host identity required")
		if not self.db.execute("SELECT 1 FROM grant_rule WHERE actor=? AND target=? AND capability=?",
							   (actor.name, target, capability)).fetchone():
			raise Denied("Operation unavailable")

	def _validate(self, payload):
		if not isinstance(payload, dict) or set(payload) != {"target", "label"}:
			raise ValueError("Only target and label are accepted")
		if not isinstance(payload["target"], str) or not payload["target"].startswith("SYN-"):
			raise ValueError("Synthetic target required")
		if not isinstance(payload["label"], str) or not 1 <= len(payload["label"]) <= 120:
			raise ValueError("Label must contain 1..120 characters")
		return json.loads(encode(payload))

	def _load(self, pid):
		row = self.db.execute("SELECT * FROM proposal WHERE id=?", (pid,)).fetchone()
		if row is None:
			raise Denied("Operation unavailable")
		revision = self.db.execute("SELECT * FROM revision WHERE proposal=? AND number=?",
								   (pid, row["revision"])).fetchone()
		return dict(row), json.loads(revision["body"]), revision["hash"]

	def _binding(self, binding):
		if (not isinstance(binding, dict) or set(binding) != {"id", "revision", "hash"}
				or not isinstance(binding["id"], str) or not 1 <= len(binding["id"]) <= 120
				or type(binding["revision"]) is not int or binding["revision"] < 1
				or not isinstance(binding["hash"], str) or len(binding["hash"]) != 64
				or any(c not in "0123456789abcdef" for c in binding["hash"])):
			raise Conflict("Exact revision binding required")

	def _bound(self, binding, actor, package):
		self._binding(binding)
		row, body, sha = self._load(binding["id"])
		self._permission(actor, body["payload"]["target"], "read")
		if row["package"] != package or row["revision"] != binding["revision"] or sha != binding["hash"]:
			raise Conflict("Dependency binding changed")
		if row["status"] in {"Stale", "Rejected"}:
			raise Conflict("Dependency unavailable")
		if body["action"] != ACTION or body["policy"] != POLICY:
			raise Conflict("Dependency policy changed")
		return row, body, sha

	def _preview(self, actor, package, payload, dependencies, own_id=None):
		self._permission(actor, payload["target"], "read")
		ordered, visiting, seen, bindings = [], set(), set(), {}

		def visit(binding):
			pid = binding["id"] if isinstance(binding, dict) and "id" in binding else None
			if pid == own_id or pid in visiting:
				raise Conflict("Dependency cycle")
			row, body, sha = self._bound(binding, actor, package)
			if pid in bindings and bindings[pid] != binding:
				raise Conflict("Conflicting dependency revisions")
			bindings[pid] = binding
			if pid in seen:
				return
			visiting.add(pid)
			for parent in body["dependencies"]:
				visit(parent)
			visiting.remove(pid)
			seen.add(pid)
			ordered.append((row, body, sha))
			if len(seen) > 64:
				raise Conflict("At most 64 dependency nodes")

		if not isinstance(dependencies, list) or len(dependencies) > 64:
			raise ValueError("Dependency list required, maximum 64")
		for binding in dependencies:
			visit(binding)
		targets = {payload["target"]} | {body["payload"]["target"] for _, body, _ in ordered}
		states = {}
		for target in targets:
			self._permission(actor, target, "read")
			note = self.db.execute("SELECT label,version FROM note WHERE id=?", (target,)).fetchone()
			if note is None:
				raise Conflict("Synthetic target unavailable")
			states[target] = dict(note)
		real = json.loads(encode(states))
		modes, latest_real, writers = [], {}, {}
		for row, body, sha in ordered:
			target = body["payload"]["target"]
			# Multiple writers must be explicitly ordered by ancestry, never ID order.
			ancestors = set()
			stack = list(body["dependencies"])
			while stack:
				parent = stack.pop()
				if parent["id"] not in ancestors:
					ancestors.add(parent["id"])
					stack.extend(self._load(parent["id"])[1]["dependencies"])
			if target in writers and writers[target] not in ancestors:
				raise Conflict("Unordered overlapping projections")
			writers[target] = row["id"]
			if row["status"] == "Succeeded":
				result = json.loads(row["result"])
				expected = {"doctype": "Synthetic Note", "id": target, "state": body["preview"]["after"]}
				if result != expected:
					raise Conflict("Real result mapping differs")
				latest_real[target] = result["state"]
				mode = "real"
			else:
				if states[target] != body["preview"]["before"]:
					raise Conflict("Projection baseline changed")
				states[target] = body["preview"]["after"].copy()
				mode = "projected"
			modes.append({"id": row["id"], "revision": row["revision"], "hash": sha, "mode": mode})
		for target, expected in latest_real.items():
			if real[target] != expected:
				raise Conflict("Real predecessor data differs")
		before = states[payload["target"]]
		after = {"label": payload["label"], "version": before["version"] + 1}
		return {"doctype": "Synthetic Note", "target": payload["target"],
				"real": real[payload["target"]], "before": before, "after": after,
				"effects": [], "limits": LIMITS, "dependencies": modes, "conflicts": [],
				"complete": True, "projection_version": ACTION}

	def _audit(self, actor, pid, kind, number, sha, detail=None):
		self.db.execute("INSERT INTO event(proposal,actor,kind,revision,hash,detail) VALUES(?,?,?,?,?,?)",
						(pid, actor.name, kind, number, sha, encode(detail)))

	def _invalidate(self, pid, actor):
		pending, visited = [pid], {pid}
		while pending:
			parent = pending.pop()
			for row in self.db.execute("SELECT id FROM proposal WHERE status != 'Succeeded'").fetchall():
				child, body, sha = self._load(row["id"])
				if child["id"] not in visited and any(d["id"] == parent for d in body["dependencies"]):
					visited.add(child["id"])
					pending.append(child["id"])
					self.db.execute("UPDATE proposal SET status='Stale',decision_actor=NULL WHERE id=?", (child["id"],))
					self._audit(actor, child["id"], "Stale", child["revision"], sha)

	def _read_dependencies(self, actor, body, seen=None):
		seen = set() if seen is None else seen
		for dep in body["dependencies"]:
			token = (dep["id"], dep["revision"])
			if token in seen:
				continue
			seen.add(token)
			historical = self.db.execute(
				"SELECT body FROM revision WHERE proposal=? AND number=?", token
			).fetchone()
			if historical is None:
				raise Denied("Operation unavailable")
			dep_body = json.loads(historical["body"])
			self._permission(actor, dep_body["payload"]["target"], "read")
			self._read_dependencies(actor, dep_body, seen)

	def _snapshot(self, pid):
		row, body, sha = self._load(pid)
		return {"id": pid, "revision": row["revision"], "hash": sha,
				"approvable": row["status"] in {"Pending", "Approved"},
				"conflicts": ["New revision and human review required"] if row["status"] == "Stale" else [],
				"status": row["status"], "preview": body["preview"], "result": json.loads(row["result"]) if row["result"] else None}

	def create(self, actor, key, package, payload, dependencies=None, *, action=ACTION):
		if action != ACTION:
			raise ValueError("Unregistered action")
		payload = self._validate(payload)
		dependencies = json.loads(encode(dependencies if dependencies is not None else []))
		if not all(isinstance(v, str) and 1 <= len(v) <= 120 for v in (key, package)):
			raise ValueError("Bounded key and package required")
		with self._transaction():
			self._permission(actor, payload["target"], "propose")
			request_hash = digest([action, package, payload, dependencies])
			previous = self.db.execute("SELECT * FROM request WHERE actor=? AND key=?", (actor.name, key)).fetchone()
			if previous:
				if previous["hash"] != request_hash:
					raise Conflict("Request key reused")
				return self._checked_snapshot(actor, previous["proposal"])
			pid = str(uuid4())
			preview = self._preview(actor, package, payload, dependencies, pid)
			body = {"action": action, "policy": POLICY, "payload": payload, "dependencies": dependencies,
					"preview": preview, "proposal": pid, "revision": 1}
			sha = digest(body)
			self.db.execute("INSERT INTO proposal VALUES(?,?,1,'Pending',NULL,NULL)", (pid, package))
			self.db.execute("INSERT INTO revision VALUES(?,?,?,?)", (pid, 1, sha, encode(body)))
			self.db.execute("INSERT INTO request VALUES(?,?,?,?)", (actor.name, key, request_hash, pid))
			self._audit(actor, pid, "Created", 1, sha)
			return self._snapshot(pid)

	def _exact(self, actor, binding, capability):
		self._binding(binding)
		row, body, sha = self._load(binding["id"])
		self._permission(actor, body["payload"]["target"], "read")
		self._permission(actor, body["payload"]["target"], capability)
		self._read_dependencies(actor, body)
		if row["revision"] != binding["revision"] or sha != binding["hash"]:
			raise Conflict("Revision changed")
		return row, body, sha

	def _current(self, actor, row, body):
		if body["policy"] != POLICY or body["action"] != ACTION:
			raise Conflict("Policy changed")
		fresh = self._preview(actor, row["package"], body["payload"], body["dependencies"], row["id"])
		if any(fresh[k] != body["preview"][k] for k in ("before", "after", "projection_version")):
			raise Conflict("Baseline changed; new revision required")
		return fresh

	def _checked_snapshot(self, actor, pid):
		row, body, _ = self._load(pid)
		self._permission(actor, body["payload"]["target"], "read")
		self._read_dependencies(actor, body)
		if row["status"] in {"Pending", "Approved"}:
			try:
				self._current(actor, row, body)
			except Conflict:
				self.db.execute("UPDATE proposal SET status='Stale',decision_actor=NULL WHERE id=?", (pid,))
				self._audit(actor, pid, "Stale", row["revision"], self._load(pid)[2])
				self._invalidate(pid, actor)
		return self._snapshot(pid)

	def get(self, actor, pid):
		with self._transaction():
			return self._checked_snapshot(actor, pid)

	def revise(self, actor, binding, payload, dependencies=None):
		payload = self._validate(payload)
		dependencies = json.loads(encode(dependencies if dependencies is not None else []))
		with self._transaction():
			row, old, _ = self._exact(actor, binding, "propose")
			if row["status"] == "Succeeded":
				raise Conflict("Executed proposal is final")
			if payload["target"] != old["payload"]["target"]:
				raise Conflict("Primary target cannot change")
			preview = self._preview(actor, row["package"], payload, dependencies, row["id"])
			number = row["revision"] + 1
			body = {"action": ACTION, "policy": POLICY, "payload": payload, "dependencies": dependencies,
					"preview": preview, "proposal": row["id"], "revision": number}
			sha = digest(body)
			self.db.execute("INSERT INTO revision VALUES(?,?,?,?)", (row["id"], number, sha, encode(body)))
			self.db.execute("UPDATE proposal SET revision=?,status='Pending',decision_actor=NULL WHERE id=?", (number, row["id"]))
			self._invalidate(row["id"], actor)
			self._audit(actor, row["id"], "Revised", number, sha)
			return self._snapshot(row["id"])

	def decide(self, actor, binding, *, approve):
		if not isinstance(actor, Identity) or actor.human is not True or type(approve) is not bool:
			raise Denied("Human decision required")
		with self._transaction():
			row, body, sha = self._exact(actor, binding, "approve")
			if row["status"] != "Pending":
				raise Conflict("Decision requires pending revision")
			self._current(actor, row, body)
			status = "Approved" if approve else "Rejected"
			self.db.execute("UPDATE proposal SET status=?,decision_actor=? WHERE id=?", (status, actor.name, row["id"]))
			if not approve:
				self._invalidate(row["id"], actor)
			self._audit(actor, row["id"], status, row["revision"], sha)
			return self._snapshot(row["id"])

	def execute(self, actor, binding):
		with self._transaction():
			row, body, sha = self._exact(actor, binding, "execute")
			if row["status"] == "Succeeded":
				self._audit(actor, row["id"], "ResultReused", row["revision"], sha)
				return self._snapshot(row["id"])
			if row["status"] != "Approved":
				raise Conflict("Exact human approval required")
			# Approval identity and current rights remain necessary at execution.
			reviewer = Identity(row["decision_actor"], human=True)
			self._permission(reviewer, body["payload"]["target"], "approve")
			self._permission(reviewer, body["payload"]["target"], "read")
			fresh = self._current(actor, row, body)
			for dependency in fresh["dependencies"]:
				parent, parent_body, _ = self._load(dependency["id"])
				if parent["status"] != "Succeeded":
					raise Conflict("Predecessor not executed")
				self._permission(actor, parent_body["payload"]["target"], "read")
			target = body["payload"]["target"]
			result = {"doctype": "Synthetic Note", "id": target, "state": fresh["after"]}
			self.db.execute("UPDATE note SET label=?,version=? WHERE id=?", (fresh["after"]["label"], fresh["after"]["version"], target))
			self.db.execute("UPDATE proposal SET status='Succeeded',result=? WHERE id=?", (encode(result), row["id"]))
			self._audit(actor, row["id"], "Succeeded", row["revision"], sha, result)
			return self._snapshot(row["id"])

	def audit(self, actor, pid):
		with self._transaction():
			row, body, _ = self._load(pid)
			self._permission(actor, body["payload"]["target"], "read")
			# Check dependency rights before returning preview-bearing historical material.
			for revision in self.db.execute("SELECT body FROM revision WHERE proposal=?", (pid,)).fetchall():
				self._read_dependencies(actor, json.loads(revision["body"]))
			return [dict(event) for event in self.db.execute("SELECT * FROM event WHERE proposal=? ORDER BY sequence", (pid,))]
