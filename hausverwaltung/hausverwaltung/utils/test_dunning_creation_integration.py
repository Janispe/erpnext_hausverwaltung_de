"""Two real connections against an explicitly enabled disposable MariaDB only.

Run with HV_DUNNING_REGRESSION_DB_PORT=33307. The server must use the test-only
password below; no Frappe site connection or business database is accessed.
"""

import os
import threading
import unittest
import uuid
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.utils import dunning_creation as guard


class TestDunningConcurrency(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if os.environ.get("HV_DUNNING_REGRESSION_DB_PORT") != "33307":
			raise unittest.SkipTest("Requires disposable MariaDB on the explicit regression-test port")
		import pymysql

		cls.pymysql = pymysql
		cls.database = "hv_dunning_regression_" + uuid.uuid4().hex
		with cls._connection() as connection:
			with connection.cursor() as cursor:
				cursor.execute(f"CREATE DATABASE `{cls.database}`")
		cls.addClassCleanup(cls._drop_database)

	@classmethod
	def _connection(cls, *, database=False):
		return cls.pymysql.connect(
			host="127.0.0.1", port=33307, user="root", password="hv-dunning-isolated-test-only",
			database=cls.database if database else None, autocommit=False,
			cursorclass=cls.pymysql.cursors.DictCursor, connect_timeout=5,
		)

	@classmethod
	def _drop_database(cls):
		with cls._connection() as connection:
			with connection.cursor() as cursor:
				cursor.execute(f"DROP DATABASE `{cls.database}`")

	def setUp(self):
		with self._connection(database=True) as connection:
			with connection.cursor() as cursor:
				for table in ("tabOverdue Payment", "tabDunning", "tabSales Invoice"):
					cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
				cursor.execute("CREATE TABLE `tabSales Invoice` (name VARCHAR(140) PRIMARY KEY, docstatus INT, outstanding_amount DECIMAL(18,2), due_date DATE) ENGINE=InnoDB")
				cursor.execute("CREATE TABLE `tabDunning` (name VARCHAR(140) PRIMARY KEY, docstatus INT, posting_date DATE) ENGINE=InnoDB")
				cursor.execute("CREATE TABLE `tabOverdue Payment` (parent VARCHAR(140), parenttype VARCHAR(140), sales_invoice VARCHAR(140), INDEX(sales_invoice)) ENGINE=InnoDB")
				cursor.execute("INSERT INTO `tabSales Invoice` VALUES ('SI-1',1,600,'2026-10-01')")
			connection.commit()

	def _race(self, *, first_commits):
		local = threading.local()
		first_ready, second_reading, release_first = (threading.Event() for _ in range(3))
		results = Queue()

		def sql(query, params, **kwargs):
			with local.connection.cursor() as cursor:
				cursor.execute(query, params)
				return [frappe._dict(row) for row in cursor.fetchall()]

		def get_doc(doctype, name, *, for_update):
			self.assertEqual(doctype, "Sales Invoice")
			self.assertTrue(for_update)
			if local.worker == "second":
				second_reading.set()
			row = sql("SELECT * FROM `tabSales Invoice` WHERE name=%s FOR UPDATE", (name,))[0]
			row.check_permission = MagicMock()
			return row

		def insert_letter(name):
			sql("INSERT INTO `tabDunning` VALUES (%s,1,'2026-10-16')", (name,))
			sql("INSERT INTO `tabOverdue Payment` VALUES (%s,'Dunning','SI-1')", (name,))

		def worker(name):
			with self._connection(database=True) as connection:
				local.connection, local.worker = connection, name
				try:
					sql("SET SESSION innodb_snapshot_isolation=ON", ())
					connection.begin()
					# Open an older repeatable-read snapshot before waiting on SI-1.
					sql("SELECT COUNT(*) AS n FROM `tabDunning`", ())
					guard.lock_dunning_invoices(["SI-1"], "2026-10-16")
					guard.reject_duplicate_dunning(["SI-1"], "2026-10-16")
					insert_letter("DUN-" + name)
					if name == "first":
						first_ready.set()
						if not release_first.wait(10):
							raise AssertionError("Timed out waiting to release first transaction")
						if not first_commits:
							connection.rollback()
							results.put((name, "rolled_back"))
							return
					connection.commit()
					results.put((name, "created"))
				except BaseException as exc:
					connection.rollback()
					if name == "second" and isinstance(exc, self.pymysql.OperationalError) and exc.args[0] in (1020, 1213):
						# Match a fresh HTTP retry after Frappe rolls back a snapshot
						# conflict. Never continue inside the aborted transaction.
						try:
							connection.begin()
							guard.lock_dunning_invoices(["SI-1"], "2026-10-16")
							guard.reject_duplicate_dunning(["SI-1"], "2026-10-16")
						except BaseException as retry_error:
							exc = retry_error
						finally:
							connection.rollback()
					results.put((name, exc))

		def throw(message):
			raise frappe.ValidationError(message)

		with patch.object(guard.frappe, "get_doc", side_effect=get_doc), \
			patch.object(guard.frappe, "db", SimpleNamespace(sql=sql)), \
			patch.object(guard.frappe, "throw", side_effect=throw), \
			patch.object(guard, "_", side_effect=lambda text: text):
			first = threading.Thread(target=worker, args=("first",), daemon=True)
			second = threading.Thread(target=worker, args=("second",), daemon=True)
			first.start()
			try:
				self.assertTrue(first_ready.wait(10), "First request did not prepare its letter")
				second.start()
				self.assertTrue(second_reading.wait(10), "Second request did not try its invoice lock")
			finally:
				release_first.set()
				first.join(15)
				if second.ident is not None:
					second.join(15)
			self.assertFalse(first.is_alive() or second.is_alive())
		outcomes = dict(results.get_nowait() for _ in range(2))
		self.assertEqual(outcomes["first"], "created" if first_commits else "rolled_back")
		if first_commits:
			self.assertIsInstance(outcomes["second"], frappe.ValidationError)
			self.assertIn("bereits Mahnung", str(outcomes["second"]))
		else:
			self.assertEqual(outcomes["second"], "created")
		with self._connection(database=True) as connection:
			with connection.cursor() as cursor:
				cursor.execute("SELECT COUNT(*) AS n FROM `tabDunning`")
				self.assertEqual(cursor.fetchone()["n"], 1)

	def test_competing_request_sees_committed_letter_despite_older_snapshot(self):
		self._race(first_commits=True)

	def test_rolled_back_attempt_does_not_prevent_a_later_success(self):
		self._race(first_commits=False)
