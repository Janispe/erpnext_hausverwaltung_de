"""Private synthetic proof fixtures; not a production inventory capture utility."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import legacy_dunning_origin as origin


_INVENTORY_CONFIG = "hv_legacy_dunning_inventory_sha256"


def approve_synthetic_legacy_invoice(test, invoice):
	"""Model an independently captured historical identity in the disposable site.

	The file is unique to this testcase, outside upload paths. Only this Python
	test process trusts its hash; no persistent Site Config or existing file is
	changed, and no production eligibility is inferred from today's DB state.
	"""
	if not (frappe.local.site == "synthetic.local" and frappe.conf.db_name == "hv_qa_synthetic_4"
		and frappe.conf.hv_isolated_integration_test and frappe.are_emails_muted()
		and frappe.conf.pause_scheduler and frappe.conf.disable_scheduler):
		raise RuntimeError("Synthetic origin fixture is forbidden outside the explicit isolated site")
	if invoice.get("payment_schedule") or invoice.docstatus != 1:
		raise RuntimeError("Expected explicitly historical synthetic planless invoice fixture")
	state = getattr(test, "_legacy_origin_fixture", None)
	if state is None:
		name = "hv_legacy_origin_test_" + frappe.generate_hash(length=16) + ".json"
		path = Path(frappe.get_site_path("private", name))
		path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
		fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
		os.close(fd)
		test.addCleanup(lambda: path.unlink(missing_ok=True))
		conf = frappe.local.conf
		present, old = _INVENTORY_CONFIG in conf, conf.get(_INVENTORY_CONFIG)
		def restore_config():
			if present:
				conf[_INVENTORY_CONFIG] = old
			else:
				conf.pop(_INVENTORY_CONFIG, None)
		test.addCleanup(restore_config)
		test.enterContext(patch.object(origin, "_INVENTORY_FILENAME", name))
		state = {"path": path, "invoices": {}}
		test._legacy_origin_fixture = state
	state["invoices"][invoice.name] = {field: str(invoice.get(field)) for field in origin._IDENTITY} | {
		"docstatus": 1, "is_return": 0, "had_payment_schedule": False,
	} | {field: str(invoice.get(field)) for field in origin._AMOUNTS}
	# Digest of this synthetic source inventory, never an asserted real backup.
	source = json.dumps(state["invoices"], sort_keys=True).encode()
	inventory = {"schema": 1, "source": {"kind": "synthetic-regression-inventory", "fixture_id": state["path"].name,
		"criteria": origin._CRITERIA, "sha256": hashlib.sha256(b"synthetic-historical-fixture:" + source).hexdigest()},
		"target": origin._target_binding(), "invoices": state["invoices"]}
	content = json.dumps(inventory, sort_keys=True).encode()
	state["path"].write_bytes(content)
	frappe.conf[_INVENTORY_CONFIG] = hashlib.sha256(content).hexdigest()
