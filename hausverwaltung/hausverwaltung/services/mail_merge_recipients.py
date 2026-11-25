"""Optional Mail Merge scope for explicit unit and lease assignments."""

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
		left, right = frappe.db.get_value("Immobilie", property_id, ["lft", "rgt"])
		inside = set(frappe.get_all("Immobilie", filters={"lft": [">=", left], "rgt": ["<=", right]}, pluck="name"))
		ancestors = set(frappe.get_all("Immobilie", filters={"lft": ["<=", left], "rgt": [">=", right]}, pluck="name"))
		ancestors -= inside
		unit_filters = [["immobilie", "in", list(inside)], ["immobilie_knoten", "in", list(inside)]]

	# Resolve assignment independently of permissions on the linked unit. The
	# picker checks permissions on every iteration object, and unit labels are
	# exposed only when the unit itself is readable.
	readable_units = _readable_linked_units(unit_filters) if linked else None
	locations = {}
	for unit in frappe.get_all("Wohnung", fields=fields, or_filters=unit_filters):
		if property_id and unit.immobilie not in inside:
			if unit.immobilie not in ancestors or unit.immobilie_knoten not in inside:
				continue
		if readable_units is not None and unit.name not in readable_units:
			locations[unit.name] = ()
			continue
		locations[unit.name] = (
			labels.get(unit.immobilie, ""),
			unit.get("name__lage_in_der_immobilie") or unit.name,
			labels.get(unit.immobilie_knoten) or unit.get("gebaeudeteil") or "",
		)
	return locations


def _readable_linked_units(or_filters):
	if not frappe.has_permission("Wohnung", "read"):
		return set()
	virtual_links = {
		field.options for field in frappe.get_meta("Wohnung").get_link_fields()
		if field.is_virtual and not field.ignore_user_permissions
	}
	# Frappe 16's list permission filters cannot query virtual link columns.
	# Keep these auxiliary labels private when such a filter would be needed.
	if virtual_links.intersection(frappe.permissions.get_user_permissions(frappe.session.user)):
		return set()
	return set(frappe.get_list("Wohnung", pluck="name", or_filters=or_filters, limit=0))
