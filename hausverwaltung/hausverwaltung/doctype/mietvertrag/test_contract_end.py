"""The process end-date operation keeps all checks inside the flat lock."""

import unittest
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.mietvertrag import mietvertrag as domain


class TestContractEnd(unittest.TestCase):
	def _contract(self, events, **values):
		return frappe._dict({"name": "MV-A", "wohnung": "W-A", "docstatus": 0,
			"von": "2027-01-01", "bis": "2027-01-31", "miete_teilmonate": [],
			**{field: [field] for field in domain.STAFFEL_FIELD_BY_KOSTENART.values()},
			"check_permission": lambda permission: events.append(("permission", permission)),
			"_validate_wohnung_contract_period": lambda: events.append("interval"), **values})

	def test_lock_fresh_read_checks_all_charges_before_single_field_write(self):
		events = []
		contract = self._contract(events)
		def sql(query, params):
			self.assertIn("FOR UPDATE", query)
			self.assertEqual(params, ("W-A",))
			events.append("flat_lock")
			return [("W-A",)]
		def get_doc(*args, **kwargs):
			self.assertEqual(args, ("Mietvertrag", "MV-A"))
			self.assertEqual(kwargs, {"for_update": True})
			events.append("fresh_contract")
			return contract
		with patch.object(frappe.db, "sql", side_effect=sql), patch.object(frappe, "get_doc", side_effect=get_doc), \
			patch.object(domain, "validate_contract_charges", side_effect=lambda *args: events.append("charges")) as charges, \
			patch.object(frappe.db, "set_value", side_effect=lambda *args, **kw: events.append("write")) as write:
			end = domain.update_contract_end("MV-A", "2027-01-30", "W-A")
		self.assertEqual(events, ["flat_lock", "fresh_contract", ("permission", "write"), "interval", "charges", "write"])
		self.assertEqual(charges.call_args.args[2], {kind: [field] for kind, field in domain.STAFFEL_FIELD_BY_KOSTENART.items()})
		write.assert_called_once_with("Mietvertrag", "MV-A", "bis", end, update_modified=False)

	def test_unchanged_end_still_validates_and_never_writes(self):
		events = []
		with patch.object(frappe.db, "sql", return_value=[("W-A",)]), \
			patch.object(frappe, "get_doc", return_value=self._contract(events)), \
			patch.object(domain, "validate_contract_charges") as charges, patch.object(frappe.db, "set_value") as write:
			domain.update_contract_end("MV-A", "2027-01-31", "W-A")
		self.assertIn("interval", events)
		charges.assert_called_once()
		write.assert_not_called()

	def test_wrong_flat_cancelled_invalid_begin_permission_and_charge_failure_never_write(self):
		for problem in ("flat", "cancelled", "begin", "permission", "charges"):
			with self.subTest(problem=problem):
				contract = self._contract([])
				if problem == "flat": contract.wohnung = "OTHER"
				if problem == "cancelled": contract.docstatus = 2
				if problem == "begin": contract.von = "2027-02-01"
				if problem == "permission": contract.check_permission = Mock(side_effect=frappe.PermissionError)
				with patch.object(frappe.db, "sql", return_value=[("W-A",)]), patch.object(frappe, "get_doc", return_value=contract), \
					patch.object(domain, "validate_contract_charges", side_effect=frappe.ValidationError if problem == "charges" else None), \
					patch.object(frappe.db, "set_value") as write, self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
					domain.update_contract_end("MV-A", "2027-01-31", "W-A")
				write.assert_not_called()
