"""Synthetic SQLite persistence and local transaction boundary.

One connection per service/thread. BEGIN IMMEDIATE serializes the complete
read/check/write/audit unit across connections. The service owns no nested or
independent commits. This adapter does not model Frappe transaction semantics.
"""
from contextlib import contextmanager
import sqlite3


class SQLiteStore:
	def __init__(self, path):
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
	def transaction(self):
		self.db.execute("BEGIN IMMEDIATE")
		try:
			yield
			self.db.execute("COMMIT")
		except BaseException:
			self.db.execute("ROLLBACK")
			raise
