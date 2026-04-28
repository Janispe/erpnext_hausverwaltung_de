from __future__ import annotations

import frappe


TITLE = "Zahlungshistorie letzte 5 Mieten"

JINJA_CONTENT = """
{%- set kunde = iteration_doc.kunde if iteration_doc is defined and iteration_doc and iteration_doc.doctype == 'Mietvertrag' else None -%}
{%- set miete_si_names = frappe.get_all('Sales Invoice Item',
    filters={'item_code': 'Miete', 'parenttype': 'Sales Invoice'},
    pluck='parent'
) if kunde else [] -%}
{%- set invoices = frappe.get_all(
    'Sales Invoice',
    filters={'customer': kunde, 'docstatus': 1, 'name': ['in', miete_si_names]},
    fields=['name', 'posting_date', 'outstanding_amount'],
    order_by='posting_date desc',
    limit_page_length=5
) if (kunde and miete_si_names) else [] -%}
{%- set rows = [] -%}
{%- for si in invoices -%}
  {%- set pay_date = None -%}
  {%- set jea = frappe.get_all('Journal Entry Account',
        filters={'reference_type': 'Sales Invoice', 'reference_name': si.name, 'docstatus': 1},
        fields=['parent'], order_by='creation desc', limit_page_length=1) -%}
  {%- if jea -%}
    {%- set pay_date = frappe.db.get_value('Journal Entry', jea[0].parent, 'posting_date') -%}
  {%- else -%}
    {%- set per = frappe.get_all('Payment Entry Reference',
          filters={'reference_doctype': 'Sales Invoice', 'reference_name': si.name, 'docstatus': 1},
          fields=['parent'], order_by='creation desc', limit_page_length=1) -%}
    {%- if per -%}
      {%- set pay_date = frappe.db.get_value('Payment Entry', per[0].parent, 'posting_date') -%}
    {%- endif -%}
  {%- endif -%}
  {%- set _ = rows.append({'posting_date': si.posting_date, 'pay_date': pay_date, 'outstanding': si.outstanding_amount}) -%}
{%- endfor -%}
""".strip()

HTML_CONTENT = """
<table style="width:60%; border-collapse:collapse; margin:10px 0;">
  <thead>
    <tr>
      <th style="text-align:left; border-bottom:1px solid #000; padding:4px 0;">Monat</th>
      <th style="text-align:left; border-bottom:1px solid #000; padding:4px 0;">Zahlungseingang</th>
    </tr>
  </thead>
  <tbody>
    {% for r in rows|reverse %}
    <tr>
      <td style="padding:3px 0;">{{ frappe.utils.formatdate(r.posting_date, 'MMMM yyyy') }}</td>
      <td style="padding:3px 0;">
        {% if r.pay_date %}{{ frappe.utils.formatdate(r.pay_date) }}
        {% elif (r.outstanding or 0) > 0 %}offen
        {% else %}—{% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
""".strip()

DESCRIPTION = (
	"Listet die letzten 5 Miet-Rechnungen des Mietvertrags-Kunden mit Monat "
	"und Zahlungseingang (posting_date des verknüpften Journal/Payment Entry). "
	"Iteration: Mietvertrag."
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return

	payload = {
		"content_type": "HTML + Jinja",
		"html_content": HTML_CONTENT,
		"jinja_content": JINJA_CONTENT,
		"description": DESCRIPTION,
	}

	if frappe.db.exists("Serienbrief Textbaustein", TITLE):
		doc = frappe.get_doc("Serienbrief Textbaustein", TITLE)
		changed = False
		for fieldname, value in payload.items():
			if getattr(doc, fieldname, None) != value:
				setattr(doc, fieldname, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return

	frappe.get_doc(
		{
			"doctype": "Serienbrief Textbaustein",
			"title": TITLE,
			**payload,
		}
	).insert(ignore_permissions=True)
