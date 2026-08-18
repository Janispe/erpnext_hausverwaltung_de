from __future__ import annotations

import json

import frappe


TEMPLATE_NAME = "Dunning - Miete - Mahnung (alle Stufen)"
VARIABLE = "rechnungsbemerkung_statt_nummer"

OLD_HEADER = '<thead><tr><th>Rechnung</th><th>Fällig</th><th style="text-align: right">Offen</th></tr></thead>'
INTERMEDIATE_HEADER = '''<thead><tr><th>{% if rechnungsbemerkung_statt_nummer %}Bemerkung{% else %}Rechnung{% endif %}</th><th>Fällig</th><th style="text-align: right">Offen</th></tr></thead>'''
NEW_HEADER = '''<thead><tr><th style="width: 64%; text-align: left; padding-right: 8px">{% if rechnungsbemerkung_statt_nummer %}Bemerkung{% else %}Rechnung{% endif %}</th><th style="width: 18%; text-align: left; padding-right: 8px">Fällig</th><th style="width: 18%; text-align: right">Offen</th></tr></thead>'''
OLD_CELL = '''<tr><td>{{ row.sales_invoice }}</td><td>{{ frappe.utils.formatdate(row.due_date) }}</td><td style="text-align: right">{{ frappe.utils.fmt_money(row.outstanding, currency=currency) }}</td></tr>'''
INTERMEDIATE_CELL = '''<tr><td>{% if rechnungsbemerkung_statt_nummer and row.sales_invoice_remarks %}{{ row.sales_invoice_remarks }}{% else %}{{ row.sales_invoice }}{% endif %}</td><td>{{ frappe.utils.formatdate(row.due_date) }}</td><td style="text-align: right">{{ frappe.utils.fmt_money(row.outstanding, currency=currency) }}</td></tr>'''
NEW_CELL = '''<tr><td style="padding-right: 8px; overflow-wrap: anywhere">{% if rechnungsbemerkung_statt_nummer and row.sales_invoice_remarks %}{{ row.sales_invoice_remarks }}{% else %}{{ row.sales_invoice }}{% endif %}</td><td style="padding-right: 8px; white-space: nowrap">{{ frappe.utils.formatdate(row.due_date) }}</td><td style="text-align: right; white-space: nowrap">{{ frappe.utils.fmt_money(row.outstanding, currency=currency) }}</td></tr>'''


def execute() -> None:
	if not frappe.db.exists("Serienbrief Vorlage", TEMPLATE_NAME):
		return

	template = frappe.get_doc("Serienbrief Vorlage", TEMPLATE_NAME)
	body = template.html_content or ""
	changed = False

	for old_header in (OLD_HEADER, INTERMEDIATE_HEADER):
		if old_header in body:
			body = body.replace(old_header, NEW_HEADER)
			changed = True
	for old_cell in (OLD_CELL, INTERMEDIATE_CELL):
		if old_cell in body:
			body = body.replace(old_cell, NEW_CELL)
			changed = True

	if NEW_HEADER not in body or NEW_CELL not in body:
		frappe.throw(
			f"Serienbrief Vorlage {TEMPLATE_NAME}: Die Postentabelle konnte nicht sicher aktualisiert werden."
		)

	if body != (template.html_content or ""):
		template.html_content = body

	variable = next(
		(row for row in (template.get("variables") or []) if row.variable == VARIABLE),
		None,
	)
	if variable is None:
		template.append(
			"variables",
			{
				"variable": VARIABLE,
				"variable_type": "Bool",
				"label": "Rechnungsbemerkung statt Rechnungsnummer",
				"optional": 1,
				"beschreibung": (
					"Zeigt in der Postentabelle die Rechnungsbemerkung an. "
					"Bei leerer Bemerkung wird die Rechnungsnummer verwendet."
				),
			},
		)
		changed = True

	defaults = json.loads(template.variablen_werte or "{}")
	if VARIABLE not in defaults:
		defaults[VARIABLE] = {"value": "1"}
		template.variablen_werte = json.dumps(defaults, ensure_ascii=False)
		changed = True

	if changed:
		template.save(ignore_permissions=True)

	frappe.db.commit()
