"""Read an explicitly approved, private pre-upgrade invoice inventory.

Provisioning this inventory is a separate, authorized server operation against an
actual authoritative source. This module never captures today's planless records,
accepts client flags, changes invoices, or writes the inventory/configuration.
"""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import frappe
from frappe import _

_INVENTORY_FILENAME = "hv_legacy_dunning_inventory.json"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 8 * 1024 * 1024
_IDENTITY = ("creation", "posting_date", "customer", "company", "currency")
_AMOUNTS = ("grand_total", "base_grand_total")
_CRITERIA = "submitted-nonreturn-no-payment-schedule-v1"


def _target_binding():
	return {"site_sha256": hashlib.sha256(str(frappe.local.site).encode()).hexdigest(),
		"db_sha256": hashlib.sha256(str(frappe.conf.db_name).encode()).hexdigest()}


def _synthetic_mode():
	return (frappe.local.site == "synthetic.local" and frappe.conf.db_name == "hv_qa_synthetic_4"
		and frappe.conf.hv_isolated_integration_test and frappe.conf.mute_emails
		and frappe.conf.pause_scheduler and frappe.conf.disable_scheduler)


def _identity(field, value):
	if value is None or value == "":
		raise ValueError("Missing identity")
	if field == "creation":
		return datetime.fromisoformat(str(value)).isoformat(timespec="microseconds")
	if field == "posting_date":
		return date.fromisoformat(str(value)[:10]).isoformat()
	return str(value)


def _money(value):
	amount = Decimal(str(value))
	if not amount.is_finite():
		raise ValueError("Nonfinite identity amount")
	return amount.normalize()


def _valid_source(source):
	if not isinstance(source, dict) or not _HASH.fullmatch(str(source.get("sha256", ""))) or source.get("criteria") != _CRITERIA:
		return False
	if source.get("kind") == "synthetic-regression-inventory":
		return bool(_synthetic_mode() and source.get("fixture_id"))
	if source.get("kind") != "verified-pre-upgrade-inventory":
		return False
	if not all(_HASH.fullmatch(str(source.get(field, ""))) for field in (
		"backup_sha256", "extraction_sha256", "query_sha256", "baseline_identity_sha256", "baseline_versions_sha256")):
		return False
	try:
		return datetime.fromisoformat(source["captured_at"]).tzinfo is not None
	except (KeyError, TypeError, ValueError):
		return False


def _deny():
	frappe.throw(_("Für diese Rechnung fehlt ein verifizierter serverseitiger Altbestandsbeleg. Die Altmahnung wurde nicht freigegeben."))


def require_legacy_origin(invoice):
	"""Fail closed unless a hash-approved inventory proves this exact identity."""
	expected = frappe.conf.get("hv_legacy_dunning_inventory_sha256")
	if not isinstance(expected, str) or not _HASH.fullmatch(expected):
		_deny()
	try:
		root = Path(frappe.get_site_path()).resolve()
		private = root / "private"
		path = private / _INVENTORY_FILENAME
		# Outside private/files: ordinary upload/attachment APIs cannot supply it.
		if private.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root):
			_deny()
		if not path.is_file() or path.stat().st_size > _MAX_BYTES:
			_deny()
		content = path.read_bytes()
		if hashlib.sha256(content).hexdigest() != expected:
			_deny()
		inventory = json.loads(content)
	except (OSError, ValueError, TypeError):
		_deny()
	if not isinstance(inventory, dict) or inventory.get("schema") != 1:
		_deny()
	if inventory.get("target") != _target_binding():
		_deny()
	source = inventory.get("source")
	if not _valid_source(source):
		_deny()
	records = inventory.get("invoices")
	record = records.get(invoice.name) if isinstance(records, dict) else None
	if (not isinstance(record, dict) or record.get("had_payment_schedule") is not False
		or record.get("docstatus") != 1 or record.get("is_return") != 0):
		_deny()
	try:
		if any(_identity(field, record.get(field)) != _identity(field, invoice.get(field)) for field in _IDENTITY):
			_deny()
		if any(_money(record.get(field)) != _money(invoice.get(field)) for field in _AMOUNTS):
			_deny()
	except (ValueError, TypeError, InvalidOperation):
		_deny()
	return {"inventory_sha256": expected, "source_sha256": source["sha256"], "invoice_creation": record["creation"]}
