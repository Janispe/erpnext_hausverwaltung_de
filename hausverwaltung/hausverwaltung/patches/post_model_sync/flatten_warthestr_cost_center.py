from __future__ import annotations

import frappe
from frappe.utils.nestedset import rebuild_tree


PARENT_COST_CENTER = "Warthestr. 65 - HP"


def execute() -> None:
	"""Use the Warthestr. 65 cost center directly instead of child cost centers.

	Warthestr. 65 was imported as a group cost center with transactional child
	cost centers. For Hausverwaltung workflows the Immobilie cost center itself
	is the accounting dimension, so all existing references are moved to the
	parent cost center and the lower nodes are removed.
	"""

	if not frappe.db.exists("Cost Center", PARENT_COST_CENTER):
		return

	parent = frappe.db.get_value(
		"Cost Center",
		PARENT_COST_CENTER,
		["name", "company", "lft", "rgt"],
		as_dict=True,
	)
	if not parent:
		return

	children = _get_descendant_cost_centers(parent)
	if children:
		_replace_cost_center_links(children, PARENT_COST_CENTER)
		_delete_cost_centers(children)

	frappe.db.set_value("Cost Center", PARENT_COST_CENTER, "is_group", 0, update_modified=False)
	rebuild_tree("Cost Center")
	frappe.db.commit()


def _get_descendant_cost_centers(parent: dict) -> list[str]:
	if not parent.get("lft") or not parent.get("rgt"):
		return frappe.get_all(
			"Cost Center",
			filters={"parent_cost_center": parent["name"]},
			pluck="name",
			limit_page_length=0,
		)

	return frappe.db.sql_list(
		"""
		SELECT name
		FROM `tabCost Center`
		WHERE company = %(company)s
		  AND lft > %(lft)s
		  AND rgt < %(rgt)s
		ORDER BY lft DESC
		""",
		parent,
	)


def _replace_cost_center_links(old_cost_centers: list[str], new_cost_center: str) -> None:
	old_cost_centers_tuple = tuple(old_cost_centers)
	for doctype, fieldname in _cost_center_link_fields():
		if doctype == "Cost Center":
			continue
		table = f"tab{doctype}"
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, fieldname):
			continue

		frappe.db.sql(
			f"""
			UPDATE `{table}`
			SET `{fieldname}` = %(new_cost_center)s
			WHERE `{fieldname}` IN %(old_cost_centers)s
			""",
			{"new_cost_center": new_cost_center, "old_cost_centers": old_cost_centers_tuple},
		)

	frappe.db.sql(
		"""
		UPDATE `tabSingles`
		SET value = %(new_cost_center)s
		WHERE value IN %(old_cost_centers)s
		""",
		{"new_cost_center": new_cost_center, "old_cost_centers": old_cost_centers_tuple},
	)


def _cost_center_link_fields() -> set[tuple[str, str]]:
	fields: set[tuple[str, str]] = set()
	for doctype in frappe.get_all("DocType", pluck="name", limit_page_length=0):
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			continue

		for df in meta.fields:
			if df.fieldtype == "Link" and df.options == "Cost Center" and df.fieldname:
				fields.add((doctype, df.fieldname))
	return fields


def _delete_cost_centers(cost_centers: list[str]) -> None:
	frappe.db.sql(
		"""
		DELETE FROM `tabCost Center`
		WHERE name IN %(cost_centers)s
		""",
		{"cost_centers": tuple(cost_centers)},
	)
