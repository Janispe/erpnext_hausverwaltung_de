"""Minimal read access to active problems for the Paperclip pilot."""

from __future__ import annotations

import frappe
from frappe.model import get_permitted_fields

from hausverwaltung.hausverwaltung.doctype.hausverwaltung_problem.hausverwaltung_problem import (
	OPEN_STATUSES,
)

PROBLEM_DOCTYPE = "Hausverwaltung Problem"
READER_ROLE = "Paperclip Problem Reader"
CASE_FIELDS = (
	"name",
	"problem_schluessel",
	"status",
	"schweregrad",
	"problemtyp_code",
)
PROBLEM_FIELDS = (
	*CASE_FIELDS,
	"bezug_doctype",
	"bezug_name",
	"weiterer_bezug_doctype",
	"weiterer_bezug_name",
)


def _integer(value: int | str, label: str, minimum: int, maximum: int | None = None) -> int:
	if isinstance(value, str):
		value = value.strip()
		if not value.isascii() or not value.isdecimal():
			raise frappe.ValidationError(f"{label} muss eine ganze Zahl sein.")
		value = int(value)
	if isinstance(value, bool) or not isinstance(value, int):
		raise frappe.ValidationError(f"{label} muss eine ganze Zahl sein.")
	if value < minimum or (maximum is not None and value > maximum):
		raise frappe.ValidationError(f"{label} liegt außerhalb des erlaubten Bereichs.")
	return value


def _readable_reference(doctype: str | None, name: str | None) -> dict[str, str] | None:
	if not doctype or not name:
		return None
	try:
		if not frappe.has_permission(doctype, "read"):
			return None
		rows = frappe.get_list(doctype, filters={"name": name}, fields=["name"], page_length=1)
		if not rows or not frappe.has_permission(doctype, "read", doc=name):
			return None
	except (frappe.DoesNotExistError, frappe.PermissionError):
		return None
	return {"doctype": doctype, "name": name}


@frappe.whitelist(methods=["GET"])
def list_problem_cases(limit: int | str = 50, offset: int | str = 0) -> dict:
	"""Page active cases using offsets into the permission-filtered candidate list.

	A page can contain fewer cases than its limit when document hooks deny rows
	that passed the list query. Always follow next_offset while has_more is true.
	"""
	if frappe.session.user == "Guest" or READER_ROLE not in frappe.get_roles():
		raise frappe.PermissionError("Die Rolle Paperclip Problem Reader ist erforderlich.")
	frappe.has_permission(PROBLEM_DOCTYPE, "read", throw=True)
	limit = _integer(limit, "limit", 1, 100)
	offset = _integer(offset, "offset", 0)
	permitted_fields = set(get_permitted_fields(PROBLEM_DOCTYPE, permission_type="read", ignore_virtual=True))
	if not permitted_fields.issuperset(CASE_FIELDS):
		raise frappe.PermissionError("Die Paperclip-Fallfelder müssen lesbar sein.")
	fields = [field for field in PROBLEM_FIELDS if field in permitted_fields]
	rows = frappe.get_list(
		PROBLEM_DOCTYPE,
		filters={"status": ["in", sorted(OPEN_STATUSES)]},
		fields=fields,
		order_by="name asc",
		start=offset,
		page_length=limit + 1,
	)
	page = rows[:limit]
	cases = []
	for row in page:
		if not frappe.has_permission(PROBLEM_DOCTYPE, "read", doc=row["name"]):
			continue
		cases.append(
			{
				"name": row["name"],
				"problem_key": row.get("problem_schluessel"),
				"status": row.get("status"),
				"severity": row.get("schweregrad"),
				"problem_type_code": row.get("problemtyp_code"),
				"reference": _readable_reference(row.get("bezug_doctype"), row.get("bezug_name")),
				"secondary_reference": _readable_reference(
					row.get("weiterer_bezug_doctype"), row.get("weiterer_bezug_name")
				),
			}
		)
	has_more = len(rows) > limit
	return {
		"cases": cases,
		"has_more": has_more,
		"next_offset": offset + len(page) if has_more else None,
	}
