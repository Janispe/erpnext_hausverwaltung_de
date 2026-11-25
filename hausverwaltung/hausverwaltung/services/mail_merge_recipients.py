"""Optional Mail Merge scope for explicit unit and lease assignments."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cstr, getdate, today


def recipient_scope(doctype, filters):
	if doctype not in ("Wohnung", "Mietvertrag"):
		return None
	if set(filters) - {"property", "date", "lease_state"}:
		frappe.throw(_("Ungültige Immobilienfilter."))

	property_id = cstr(filters.get("property")).strip()
	lease = doctype == "Mietvertrag"
	lease_state = filters.get("lease_state") or "on_date"
	if lease_state not in ("on_date", "all"):
		frappe.throw(_("Ungültiger Vertragsstand."))
	date = getdate(filters.get("date") or today()).isoformat() if lease else None

	properties = []
	if frappe.has_permission("Immobilie", "read"):
		properties = frappe.get_list(
			"Immobilie", fields=["name", "bezeichnung", "adresse_titel"],
			order_by="bezeichnung asc, name asc", limit_page_length=0,
		)
		properties = [row for row in properties if frappe.has_permission("Immobilie", "read", doc=row.name)]
	labels = {row.name: row.get("bezeichnung") or row.get("adresse_titel") or row.name for row in properties}
	if property_id and property_id not in labels:
		raise frappe.PermissionError

	options = {
		"properties": [{"id": name, "label": label} for name, label in labels.items()],
		"date": date,
	}
	criteria = []
	if lease:
		criteria.append(["docstatus", "<", 2])
		if lease_state == "on_date":
			criteria.extend([["von", "<=", date], ["von", "is", "set"]])

	location_key = "wohnung" if lease else "name"
	locations = _unit_locations(property_id, labels, linked=lease)
	if property_id:
		criteria.append([location_key, "in", list(locations)])

	return {
		"filters": criteria,
		"fields": ["wohnung", "bis"] if lease else [],
		"location_key": location_key,
		"check_user_permissions_per_document": not lease and _has_virtual_unit_link_permissions(),
		"locations": locations,
		# Open-ended leases have no end date. Keep this OR separate from text search.
		"accept": (lambda row: not row.bis or getdate(row.bis).isoformat() >= date)
		if lease and lease_state == "on_date" else None,
		"options": options,
		"label": labels.get(property_id),
	}


def _unit_locations(property_id, labels, *, linked):
	fields = ["name", "immobilie", "immobilie_knoten", "gebaeudeteil", "name__lage_in_der_immobilie"]
	unit_filters = None
	inside = ancestors = set()
	if property_id:
		inside, ancestors = _property_tree_scope(property_id)
		unit_filters = [["immobilie", "in", list(inside)], ["immobilie_knoten", "in", list(inside)]]

	# Resolve assignment independently of permissions on the linked unit. The
	# picker checks permissions on every iteration object, and unit labels are
	# exposed only when the unit itself is readable.
	can_read_linked_units = not linked or frappe.has_permission("Wohnung", "read")
	locations = {}
	for unit in frappe.get_all("Wohnung", fields=fields, or_filters=unit_filters):
		if property_id and unit.immobilie not in inside:
			if unit.immobilie not in ancestors or unit.immobilie_knoten not in inside:
				continue
		if linked and (not can_read_linked_units or not frappe.has_permission("Wohnung", "read", doc=unit.name)):
			locations[unit.name] = ()
			continue
		locations[unit.name] = (
			labels.get(unit.immobilie, ""),
			unit.get("name__lage_in_der_immobilie") or unit.name,
			labels.get(unit.immobilie_knoten) or unit.get("gebaeudeteil") or "",
		)
	return locations


def _property_tree_scope(property_id):
	parents = {}
	children = defaultdict(list)
	for node in frappe.get_all("Immobilie", fields=["name", "parent_immobilie"]):
		parents[node.name] = node.parent_immobilie
		children[node.parent_immobilie].append(node.name)

	descendants = set()
	pending = [property_id]
	while pending:
		node = pending.pop()
		if node not in descendants:
			descendants.add(node)
			pending.extend(children[node])

	ancestors = set()
	node = parents.get(property_id)
	while node and node not in ancestors and node not in descendants:
		ancestors.add(node)
		node = parents.get(node)
	return descendants, ancestors


def _has_virtual_unit_link_permissions():
	user_permissions = frappe.permissions.get_user_permissions(frappe.session.user)
	return any(
		field.is_virtual and not field.ignore_user_permissions
		and frappe.permissions.get_allowed_docs_for_doctype(user_permissions.get(field.options, []), "Wohnung")
		for field in frappe.get_meta("Wohnung").get_link_fields()
	)
