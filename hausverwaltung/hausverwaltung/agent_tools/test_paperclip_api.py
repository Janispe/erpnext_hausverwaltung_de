"""Exercise the pilot's access boundary and cursor behavior without a site database."""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.agent_tools import paperclip_api as api


def problem(name, **values):
	return {
		"name": name,
		"problem_schluessel": f"key-{name}",
		"status": "Offen",
		"schweregrad": "Warnung",
		"problemtyp_code": "invoice.identity",
		"bezug_doctype": "Mietvertrag",
		"bezug_name": "MV-1",
		"weiterer_bezug_doctype": "Sales Invoice",
		"weiterer_bezug_name": "SI-1",
		"titel": "Private title",
		"beschreibung": "Private description",
		"details_json": '{"private":"details"}',
		**values,
	}


class TestPaperclipProblemAPI(TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		self.roles = stack.enter_context(
			patch.object(api.frappe, "get_roles", return_value=[api.READER_ROLE])
		)
		stack.enter_context(
			patch.object(api.frappe, "session", SimpleNamespace(user="paperclip@test.invalid"))
		)
		self.permission = stack.enter_context(patch.object(api.frappe, "has_permission", return_value=True))
		self.permitted_fields = stack.enter_context(
			patch.object(api, "get_permitted_fields", return_value=list(api.PROBLEM_FIELDS))
		)
		self.get_list = stack.enter_context(patch.object(api.frappe, "get_list"))
		self.candidates = []
		self.get_list.side_effect = self.visible_rows
		self.get_doc = stack.enter_context(patch.object(api.frappe, "get_doc"))
		self.get_all = stack.enter_context(patch.object(api.frappe, "get_all"))
		self.addCleanup(self.get_doc.assert_not_called)
		self.addCleanup(self.get_all.assert_not_called)

	def visible_rows(self, doctype, **kwargs):
		if doctype == api.PROBLEM_DOCTYPE:
			start = kwargs["start"]
			return [
				{field: row[field] for field in kwargs["fields"]}
				for row in self.candidates[start : start + kwargs["page_length"]]
			]
		return [{"name": kwargs["filters"]["name"]}]

	def test_requires_dedicated_role_even_for_administrative_roles(self):
		for roles in ([], ["System Manager"], ["Hausverwalter"], ["Agent Readonly API"]):
			with self.subTest(roles=roles):
				self.roles.return_value = roles
				with self.assertRaises(frappe.PermissionError):
					api.list_problem_cases()
		self.get_list.assert_not_called()

	def test_rejects_guest_even_with_reader_role(self):
		api.frappe.session.user = "Guest"
		with self.assertRaises(frappe.PermissionError):
			api.list_problem_cases()
		self.get_list.assert_not_called()

	def test_requires_doctype_permission_before_query(self):
		self.permission.side_effect = frappe.PermissionError("denied")
		with self.assertRaises(frappe.PermissionError):
			api.list_problem_cases()
		self.permission.assert_called_once_with(api.PROBLEM_DOCTYPE, "read", throw=True)
		self.get_list.assert_not_called()

	def test_checks_required_and_optional_field_permissions_before_query(self):
		self.candidates = [problem("P-1")]
		self.permitted_fields.return_value = list(api.CASE_FIELDS)
		result = api.list_problem_cases()
		self.assertIsNone(result["cases"][0]["reference"])
		self.assertIsNone(result["cases"][0]["secondary_reference"])
		self.get_list.assert_called_once()
		self.assertEqual(self.get_list.call_args.kwargs["fields"], list(api.CASE_FIELDS))

		self.get_list.reset_mock()
		self.permitted_fields.return_value.remove("problem_schluessel")
		with self.assertRaises(frappe.PermissionError):
			api.list_problem_cases()
		self.get_list.assert_not_called()

	def test_lists_only_open_visible_candidates_and_minimal_payload(self):
		self.candidates = [problem("P-1")]
		result = api.list_problem_cases()
		self.assertEqual(
			result,
			{
				"cases": [
					{
						"name": "P-1",
						"problem_key": "key-P-1",
						"status": "Offen",
						"severity": "Warnung",
						"problem_type_code": "invoice.identity",
						"reference": {"doctype": "Mietvertrag", "name": "MV-1"},
						"secondary_reference": {"doctype": "Sales Invoice", "name": "SI-1"},
					}
				],
				"has_more": False,
				"next_offset": None,
			},
		)
		query = self.get_list.call_args_list[0]
		self.assertEqual(query.args, (api.PROBLEM_DOCTYPE,))
		self.assertEqual(query.kwargs["filters"], {"status": ["in", ["In Bearbeitung", "Offen"]]})
		self.assertEqual(query.kwargs["fields"], list(api.PROBLEM_FIELDS))
		self.assertTrue(set(query.kwargs["fields"]).isdisjoint({"titel", "beschreibung", "details_json"}))
		self.assertEqual(query.kwargs["order_by"], "name asc")
		self.assertEqual(query.kwargs["page_length"], 51)

	def test_empty_denied_page_advances_by_candidates_without_skipping_next_case(self):
		self.candidates = [problem("P-1"), problem("P-2"), problem("P-3")]
		self.permission.side_effect = lambda doctype, _permission, doc=None, **kwargs: doc != "P-1"
		first = api.list_problem_cases(limit=1)
		self.assertEqual(first, {"cases": [], "has_more": True, "next_offset": 1})
		second = api.list_problem_cases(limit=1, offset=first["next_offset"])
		self.assertEqual([row["name"] for row in second["cases"]], ["P-2"])
		self.assertTrue(second["has_more"])
		self.assertEqual(second["next_offset"], 2)
		last = api.list_problem_cases(limit=1, offset=second["next_offset"])
		self.assertEqual([row["name"] for row in last["cases"]], ["P-3"])
		self.assertFalse(last["has_more"])
		self.assertIsNone(last["next_offset"])

	def test_reference_requires_both_list_visibility_and_document_permission(self):
		self.candidates = [problem("P-1")]
		self.permission.side_effect = lambda doctype, _permission, doc=None, **kwargs: doc != "SI-1"

		def rows(doctype, **kwargs):
			if doctype == "Mietvertrag":
				return []
			return self.visible_rows(doctype, **kwargs)

		self.get_list.side_effect = rows
		result = api.list_problem_cases()
		self.assertIsNone(result["cases"][0]["reference"])
		self.assertIsNone(result["cases"][0]["secondary_reference"])

	def test_reference_without_doctype_access_is_hidden_without_query(self):
		self.candidates = [problem("P-1", weiterer_bezug_doctype=None, weiterer_bezug_name=None)]
		self.permission.side_effect = lambda doctype, _permission, **kwargs: doctype != "Mietvertrag"
		result = api.list_problem_cases()
		self.assertIsNone(result["cases"][0]["reference"])
		self.get_list.assert_called_once()

	def test_deleted_or_inaccessible_reference_does_not_expose_identity_or_break_page(self):
		self.candidates = [problem("P-1")]

		def permission(doctype, _permission, **kwargs):
			if doctype == "Mietvertrag":
				raise frappe.DoesNotExistError("deleted")
			if doctype == "Sales Invoice":
				raise frappe.PermissionError("denied")
			return True

		self.permission.side_effect = permission
		result = api.list_problem_cases()
		self.assertEqual(len(result["cases"]), 1)
		self.assertIsNone(result["cases"][0]["reference"])
		self.assertIsNone(result["cases"][0]["secondary_reference"])

	def test_accepts_http_integer_strings_and_handles_exhausted_page(self):
		self.candidates = [problem("P-1")]
		self.assertEqual(
			api.list_problem_cases(limit="100", offset="1"),
			{"cases": [], "has_more": False, "next_offset": None},
		)
		self.assertEqual(self.get_list.call_args.kwargs["start"], 1)
		self.assertEqual(self.get_list.call_args.kwargs["page_length"], 101)

	def test_rejects_invalid_pagination_before_query(self):
		for kwargs in (
			{"limit": 0},
			{"limit": 101},
			{"limit": True},
			{"limit": 1.5},
			{"limit": "1.5"},
			{"offset": -1},
			{"offset": True},
			{"offset": 1.5},
			{"offset": "wrong"},
		):
			with self.subTest(kwargs=kwargs), self.assertRaises(frappe.ValidationError):
				api.list_problem_cases(**kwargs)
		self.get_list.assert_not_called()
