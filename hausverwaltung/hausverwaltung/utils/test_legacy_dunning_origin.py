"""Protected inventory is proof input, never inferred from an absent schedule."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import legacy_dunning_origin as origin


class TestLegacyDunningOrigin(unittest.TestCase):
	def setUp(self):
		directory = self.enterContext(tempfile.TemporaryDirectory(prefix="hv-origin-", dir="/tmp"))
		self.root = Path(directory) / "synthetic.local"
		(self.root / "private").mkdir(parents=True, mode=0o700)
		self.path = self.root / "private" / origin._INVENTORY_FILENAME
		self.conf = frappe._dict(db_name="unit-db")
		self.enterContext(patch.object(origin.frappe, "conf", self.conf))
		self.enterContext(patch.object(origin.frappe, "get_site_path", return_value=str(self.root)))
		self.invoice = frappe._dict(name="SI-OLD", creation="2025-01-01 10:00:00.000000",
			customer="CUSTOMER-OLD", company="CO-1", currency="EUR", posting_date="2025-01-01", grand_total=100, base_grand_total=100, payment_schedule=[])
		self.inventory = {"schema": 1, "target": origin._target_binding(), "source": {
			"kind": "verified-pre-upgrade-inventory", "sha256": "a" * 64,
			"criteria": origin._CRITERIA, "captured_at": "2026-11-11T00:00:00+00:00",
			**{field: "b" * 64 for field in ("backup_sha256", "extraction_sha256", "query_sha256", "baseline_identity_sha256", "baseline_versions_sha256")}},
			"invoices": {self.invoice.name: {field: str(self.invoice[field]) for field in origin._IDENTITY}
				| {"had_payment_schedule": False, "docstatus": 1, "is_return": 0}
				| {field: str(self.invoice[field]) for field in origin._AMOUNTS}}}

	def approve(self):
		content = json.dumps(self.inventory, sort_keys=True).encode()
		self.path.write_bytes(content)
		self.conf.hv_legacy_dunning_inventory_sha256 = hashlib.sha256(content).hexdigest()

	def test_matching_authoritative_record_is_accepted(self):
		self.approve()
		result = origin.require_legacy_origin(self.invoice)
		self.assertEqual(result["inventory_sha256"], self.conf.hv_legacy_dunning_inventory_sha256)
		self.assertEqual(result["source_sha256"], "a" * 64)

	def test_missing_server_approval_or_file_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)
		self.conf.hv_legacy_dunning_inventory_sha256 = "a" * 64
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)

	def test_new_planless_invoice_and_client_flag_are_not_legacy_proof(self):
		self.approve()
		self.invoice.name = "SI-NEW"
		self.invoice.hv_legacy_confirmed = True
		self.invoice.posting_date = "2000-01-01"
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)

	def test_reused_name_with_changed_identity_is_rejected(self):
		self.approve()
		for field in origin._IDENTITY:
			previous = self.invoice[field]
			self.invoice[field] = "changed"
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				origin.require_legacy_origin(self.invoice)
			self.invoice[field] = previous

	def test_other_site_database_or_changed_identity_amount_is_rejected(self):
		for field in ("site_sha256", "db_sha256"):
			previous = self.inventory["target"][field]
			self.inventory["target"][field] = "c" * 64
			self.approve()
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				origin.require_legacy_origin(self.invoice)
			self.inventory["target"][field] = previous
		self.approve()
		self.invoice.grand_total = 101
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)

	def test_missing_provenance_or_test_inventory_outside_test_site_is_rejected(self):
		self.inventory["source"].pop("backup_sha256")
		self.approve()
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)
		self.inventory["source"]["kind"] = "synthetic-regression-inventory"
		self.inventory["source"]["fixture_id"] = "honest-synthetic-fixture"
		self.approve()
		with patch.object(origin, "_synthetic_mode", return_value=False), self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)

	def test_file_changed_after_approval_is_rejected(self):
		self.approve()
		self.path.write_bytes(self.path.read_bytes() + b" ")
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)

	def test_upload_location_or_symlink_cannot_supply_server_inventory(self):
		self.approve()
		uploads = self.root / "private" / "files"
		uploads.mkdir()
		moved = uploads / self.path.name
		self.path.rename(moved)
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)
		self.path.symlink_to(moved)
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)

	def test_unverified_source_or_prior_schedule_is_rejected(self):
		self.inventory["source"]["kind"] = "current-planless-invoices"
		self.approve()
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)
		self.inventory["source"]["kind"] = "verified-pre-upgrade-inventory"
		self.inventory["invoices"][self.invoice.name]["had_payment_schedule"] = True
		self.approve()
		with self.assertRaises(frappe.ValidationError):
			origin.require_legacy_origin(self.invoice)
