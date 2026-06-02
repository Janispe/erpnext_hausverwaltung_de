import re

import frappe


PATTERNS = (
	(
		re.compile(r"innerhalb von drei Tagen nach (?:Eingang|Erhalt) dieses Schreibens", re.I),
		"innerhalb von 3 Tagen nach Erhalt des Schreibens",
	),
	(
		re.compile(r"innerhalb von drei Tagen nach (?:Eingang|Erhalt) des Schreibens", re.I),
		"innerhalb von 3 Tagen nach Erhalt des Schreibens",
	),
	(
		re.compile(r"innerhalb der nächsten drei Tage", re.I),
		"innerhalb von 3 Tagen nach Erhalt des Schreibens",
	),
	(
		re.compile(r"spätestens innerhalb von drei Tagen nach (?:Eingang|Erhalt) dieses Schreibens", re.I),
		"spätestens innerhalb von 3 Tagen nach Erhalt des Schreibens",
	),
)


def execute():
	fields = ("jinja_content", "html_content", "content", "variablen_werte")
	for row in frappe.get_all(
		"Serienbrief Vorlage",
		filters={"kategorie": "Mahnungen-System"},
		fields=["name", *fields],
	):
		changes = {}
		for fieldname in fields:
			value = row.get(fieldname)
			if not isinstance(value, str):
				continue
			new_value = value
			for pattern, replacement in PATTERNS:
				new_value = pattern.sub(replacement, new_value)
			if new_value != value:
				changes[fieldname] = new_value
		if changes:
			frappe.db.set_value("Serienbrief Vorlage", row.name, changes, update_modified=False)
