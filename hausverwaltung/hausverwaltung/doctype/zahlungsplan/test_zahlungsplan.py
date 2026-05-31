import frappe
from types import SimpleNamespace
from unittest.mock import patch

from hausverwaltung.hausverwaltung.doctype.zahlungsplan import zahlungsplan as zp


def test_importable():
	# Basic smoke test: module loads
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import Zahlungsplan  # noqa: F401
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan_zeile.zahlungsplan_zeile import ZahlungsplanZeile  # noqa: F401


def test_sync_cancelled_payment_entry_links_clears_plan_row():
	rows = [
		frappe._dict({
			"name": "ZP-ROW-1",
			"parent": "ZP-1",
			"payment_entry": "PE-CANCELLED",
		})
	]

	with patch.object(zp.frappe.db, "sql", return_value=rows), \
		patch.object(zp.frappe.db, "get_value", return_value=2), \
		patch.object(zp.frappe.db, "set_value") as set_value, \
		patch.object(zp, "_recompute_zahlungsplan_status") as recompute:
		res = zp.sync_cancelled_payment_entry_links("PE-CANCELLED")

	assert res["cleared"] == 1
	assert set_value.call_args[0][0] == "Zahlungsplan Zeile"
	updates = set_value.call_args[0][2]
	assert updates["payment_entry"] is None
	assert updates["bank_transaction"] is None
	assert updates["gebucht_am"] is None
	recompute.assert_called_once_with("ZP-1")


def test_sync_cancelled_purchase_invoice_links_clears_row_and_jahresabrechnung():
	def _sql(query, values=None, as_dict=False):
		if "FROM `tabZahlungsplan Zeile`" in query:
			return [
				frappe._dict({
					"name": "ZP-ROW-PI",
					"parent": "ZP-1",
					"purchase_invoice": "PI-CANCELLED",
				})
			]
		if "FROM `tabZahlungsplan`" in query:
			return [
				frappe._dict({
					"name": "ZP-1",
					"ja_purchase_invoice": "PI-CANCELLED",
				})
			]
		return []

	with patch.object(zp.frappe.db, "sql", side_effect=_sql), \
		patch.object(zp.frappe.db, "get_value", return_value=2), \
		patch.object(zp.frappe.db, "set_value") as set_value, \
		patch.object(zp, "_recompute_zahlungsplan_status") as recompute:
		res = zp.sync_cancelled_purchase_invoice_links("PI-CANCELLED")

	assert res["cleared_rows"] == ["ZP-ROW-PI"]
	assert res["cleared_plans"] == ["ZP-1"]
	row_updates = set_value.call_args_list[0][0][2]
	assert row_updates["purchase_invoice"] is None
	assert row_updates["pi_erstellt_am"] is None
	plan_updates = set_value.call_args_list[1][0][2]
	assert plan_updates["ja_purchase_invoice"] is None
	assert plan_updates["ja_status"] is None
	assert plan_updates["ja_differenz"] is None
	recompute.assert_called_once_with("ZP-1")


def test_create_due_purchase_invoices_ignores_cancelled_existing_pi():
	class _FakeRow:
		name = "ZP-ROW-DUE"
		idx = 1
		faelligkeitsdatum = "2026-01-01"
		betrag = 100
		purchase_invoice = "PI-CANCELLED"

		def __init__(self):
			self.updates = {}

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			self.updates[fieldname] = value
			setattr(self, fieldname, value)

	row = _FakeRow()
	doc = SimpleNamespace(
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		check_permission=lambda ptype: None,
		db_set=lambda *args, **kwargs: None,
		get=lambda key, default=None: getattr(doc, key, default),
	)
	pi = SimpleNamespace(name="PI-NEW")

	with patch.object(zp.frappe.db, "get_value", return_value=2), \
		patch.object(zp.frappe.db, "commit"), \
		patch.object(zp, "_create_purchase_invoice_for_plan_row", return_value=pi) as create_pi:
		res = zp.Zahlungsplan.create_due_purchase_invoices(doc)

	create_pi.assert_called_once_with(doc, row)
	assert res["created"] == ["PI-NEW"]
	assert row.updates["purchase_invoice"] == "PI-NEW"
	assert row.updates["pi_erstellt_am"] is not None
