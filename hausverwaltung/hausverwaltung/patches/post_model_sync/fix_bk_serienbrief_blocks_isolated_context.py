from __future__ import annotations

import frappe
from frappe.utils import cstr


REPLACEMENTS = {
	"BK-Abrechnung-Einleitung": {
		"html_content": {
			"{{$ objekt.wohnung.immobilie.address.adresse $}}": "{{$ wohnung.immobilie.address.adresse $}}",
		},
	},
	"Betriebskostenabrechnungsposten": {
		"jinja_content": {
			"{% set objekt = betriebskostenabrechnung_mieter or objekt %}": "{% set objekt = betriebskostenabrechnung_mieter %}",
		},
		"html_content": {
			'{{ immobilie_bezeichnung or "" }}': '{{ objekt.wohnung.immobilie.bezeichnung or objekt.wohnung.immobilie.name or "" }}',
			'{{ wohnung_bezeichnung or "" }}': '{{ objekt.wohnung.name__lage_in_der_immobilie or objekt.wohnung.name or "" }}',
		},
	},
}


def execute():
	for block_name, fields in REPLACEMENTS.items():
		if not frappe.db.exists("Serienbrief Textbaustein", block_name):
			continue

		updates = {}
		for fieldname, replacements in fields.items():
			value = cstr(frappe.db.get_value("Serienbrief Textbaustein", block_name, fieldname) or "")
			updated = value
			for old, new in replacements.items():
				updated = updated.replace(old, new)
			if updated != value:
				updates[fieldname] = updated

		if updates:
			frappe.db.set_value("Serienbrief Textbaustein", block_name, updates, update_modified=False)
