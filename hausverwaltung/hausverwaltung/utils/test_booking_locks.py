import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils.booking_locks import lock_accounting_scope
from hausverwaltung.hausverwaltung.utils import booking_locks


class TestBookingLocks(unittest.TestCase):
	def test_multi_company_transfer_acquires_companies_in_one_stable_order(self):
		with patch.object(frappe.db, "sql", return_value=[("A",), ("B",)]) as sql:
			lock_accounting_scope(["B", "A", "B"])
		self.assertEqual(sql.call_args.args[1], {"companies": ("A", "B")})
		self.assertIn("ORDER BY name FOR UPDATE", sql.call_args.args[0])

	def test_bulk_rent_run_locks_all_companies_before_visiting_contracts(self):
		with patch.object(frappe.db, "sql", return_value=[("A",), ("B",)]) as sql:
			lock_accounting_scope()
		self.assertNotIn("WHERE", sql.call_args.args[0])
		self.assertIn("ORDER BY name FOR UPDATE", sql.call_args.args[0])

	def test_missing_company_stops_booking(self):
		with patch.object(frappe.db, "sql", return_value=[]):
			with self.assertRaises(frappe.ValidationError):
				lock_accounting_scope(["MISSING"])


@unittest.skipUnless(os.environ.get("HV_BOOKING_LOCK_TEST_HOST"), "requires an isolated MariaDB test server")
class TestBookingLockConcurrency(unittest.TestCase):
	"""Real InnoDB locks, exclusively on an explicitly supplied test server."""

	@classmethod
	def connect(cls, **kwargs):
		import MySQLdb
		return MySQLdb.connect(
			host=os.environ["HV_BOOKING_LOCK_TEST_HOST"], user="root",
			passwd=os.environ["HV_BOOKING_LOCK_TEST_PASSWORD"], **kwargs,
		)

	@classmethod
	def setUpClass(cls):
		with cls.connect() as connection:
			with connection.cursor() as cursor:
				cursor.execute("CREATE DATABASE hv_booking_lock_regression")
				cursor.execute("USE hv_booking_lock_regression")
				for table in ("tabCompany", "tabBank Account", "tabMietvertrag"):
					cursor.execute(f"CREATE TABLE `{table}` (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
					cursor.execute(f"INSERT INTO `{table}` VALUES ('TEST')")
			connection.commit()

	@classmethod
	def tearDownClass(cls):
		with cls.connect() as connection:
			with connection.cursor() as cursor:
				cursor.execute("DROP DATABASE hv_booking_lock_regression")

	def _race(self, use_entry_lock):
		start = threading.Barrier(2)
		first_locked = threading.Barrier(2)
		thread_state = threading.local()
		errors = []
		completed = []

		class FrappeFacade:
			@property
			def db(self):
				return thread_state.db

			@staticmethod
			def throw(message):
				raise AssertionError(message)

		def worker(tables, bulk):
			connection = self.connect(db="hv_booking_lock_regression")
			try:
				with connection.cursor() as cursor:
					cursor.execute("SET innodb_lock_wait_timeout = 5")

					def sql(query, values=None):
						cursor.execute(query, values)
						return cursor.fetchall()

					thread_state.db = SimpleNamespace(sql=sql)
					start.wait(timeout=5)
					if use_entry_lock:
						lock_accounting_scope(None if bulk else ["TEST"])
					for index, table in enumerate(tables):
						sql(f"SELECT name FROM `{table}` WHERE name='TEST' FOR UPDATE")
						if index == 0:
							if use_entry_lock:
								time.sleep(0.02)
							else:
								first_locked.wait(timeout=5)
					connection.commit()
					completed.append(tables[0])
			except Exception as error:
				errors.append(error)
			finally:
				connection.rollback()
				connection.close()

		threads = [
			threading.Thread(target=worker, args=(("tabBank Account", "tabMietvertrag"), False)),
			threading.Thread(target=worker, args=(("tabMietvertrag", "tabBank Account"), True)),
		]
		with patch.object(booking_locks, "frappe", FrappeFacade()):
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(timeout=15)
			self.assertTrue(all(not thread.is_alive() for thread in threads))
		return completed, errors

	def test_old_inverted_order_reproduces_deadlock(self):
		completed, errors = self._race(False)
		self.assertEqual(len(completed), 1)
		self.assertEqual(len(errors), 1)
		self.assertEqual(errors[0].args[0], 1213)

	def test_entry_lock_prevents_deadlock_with_opposite_row_orders(self):
		for _ in range(5):
			completed, errors = self._race(True)
			self.assertEqual(errors, [])
			self.assertEqual(len(completed), 2)
