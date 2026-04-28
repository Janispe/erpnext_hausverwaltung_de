import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


FIELDNAME = "hv_serienbrief_vorlage"


def _upsert_custom_field(doctype: str, custom_field: dict) -> None:
	existing = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": custom_field["fieldname"]})
	if existing:
		doc = frappe.get_doc("Custom Field", existing)
		updated = False
		for key, value in custom_field.items():
			if doc.get(key) != value:
				doc.set(key, value)
				updated = True

		if updated:
			doc.save()
		return

	create_custom_field(doctype, custom_field, ignore_validate=True)


def execute():
	"""Ensure Dunning and Dunning Type can reference Serienbrief Vorlagen."""
	dunning_type_field = {
		"fieldname": FIELDNAME,
		"label": "Serienbrief Vorlage",
		"fieldtype": "Link",
		"options": "Serienbrief Vorlage",
		"insert_after": "dunning_letter_text",
		"description": "Optionale Default-Vorlage für Mahnungen dieser Stufe.",
	}

	dunning_field = {
		"fieldname": FIELDNAME,
		"label": "Serienbrief Vorlage",
		"fieldtype": "Link",
		"options": "Serienbrief Vorlage",
		"insert_after": "dunning_type",
		"fetch_from": f"dunning_type.{FIELDNAME}",
		"fetch_if_empty": 1,
		"description": "Konkrete Serienbrief Vorlage für dieses Mahnschreiben.",
	}

	_upsert_custom_field("Dunning Type", dunning_type_field)
	_upsert_custom_field("Dunning", dunning_field)
