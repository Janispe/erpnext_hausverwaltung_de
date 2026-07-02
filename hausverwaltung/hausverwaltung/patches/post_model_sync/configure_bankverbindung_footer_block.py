from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


BLOCK_NAME = "Bankverbindung Immobilie"

TOKEN_RE = re.compile(
	r"""
	(?:<p[^>]*>\s*)?
	\{\{\s*(?:baustein|textbaustein)\(\s*["']Bankverbindung\ Immobilie["']\s*\)\s*\}\}
	(?:\s*<br\s*/?>)?
	(?:\s*</p>)?
	""",
	flags=re.I | re.S | re.X,
)

BANKVERBINDUNG_FOOTER_BODY = """\
{%- set konto = None -%}
{%- set nutzt_bank_konto = false -%}
{%- if immobilie and immobilie.iban is defined and immobilie.iban -%}
{%- set konto = immobilie -%}
{%- elif immobilie and immobilie.bank_konto is defined -%}
{%- set konto = immobilie.bank_konto -%}
{%- set nutzt_bank_konto = true -%}
{%- endif -%}
{%- if not konto -%}
{{ frappe.throw("Für die Immobilie ist kein Bankkonto hinterlegt — die Bankverbindung kann nicht gerendert werden.") }}
{%- endif -%}
Bankverbindung:
{%- if nutzt_bank_konto and konto.account_name %} {{ konto.account_name }}{% endif -%}
{%- if konto.iban %} IBAN {{ konto.iban }}{% endif -%}
{%- if konto.bic %} · BIC {{ konto.bic }}{% endif -%}
{%- if nutzt_bank_konto and konto.bank %} · {{ konto.bank.bank_name if konto.bank.bank_name is defined else konto.bank }}{%- elif not nutzt_bank_konto and konto.bank_name is defined and konto.bank_name %} · {{ konto.bank_name }}{% endif -%}
"""


def _clean_value(value: str) -> str:
	cleaned = TOKEN_RE.sub("", value or "")
	cleaned = re.sub(r"(?:<p[^>]*>\s*</p>\s*){2,}", "<p></p>", cleaned, flags=re.I | re.S)
	return cleaned


def _clean_template_body_tokens() -> set[str]:
	if not frappe.db.exists("DocType", "Serienbrief Vorlage"):
		return set()
	affected_templates = set()
	for row in frappe.get_all("Serienbrief Vorlage", fields=["name", "content", "html_content", "jinja_content"]):
		changes = {}
		for fieldname in ("content", "html_content", "jinja_content"):
			old_value = cstr(row.get(fieldname) or "")
			new_value = _clean_value(old_value)
			if new_value != old_value:
				changes[fieldname] = new_value
				affected_templates.add(row.name)
		if changes:
			frappe.db.set_value("Serienbrief Vorlage", row.name, changes, update_modified=False)
	return affected_templates


def _set_child_table(parent, table_field: str, rows: list[dict[str, str]]) -> None:
	parent.set(table_field, [])
	for row in rows:
		parent.append(table_field, row)


def _configure_block() -> None:
	if not frappe.db.exists("Serienbrief Textbaustein", BLOCK_NAME):
		return
	doc = frappe.get_doc("Serienbrief Textbaustein", BLOCK_NAME)
	changed = False
	for fieldname, value in {
		"content_type": "HTML + Jinja",
		"render_position": "Footer",
		"html_content": BANKVERBINDUNG_FOOTER_BODY,
	}.items():
		if getattr(doc, fieldname, None) != value:
			setattr(doc, fieldname, value)
			changed = True

	variables = [
		{
			"variable": "immobilie",
			"label": "Immobilie",
			"reference_doctype": "Immobilie",
			"variable_type": "Doctype",
		}
	]
	standardpfade = [
		{"startobjekt": "Mietvertrag", "pfad_zuordnung": '{"immobilie": "objekt.wohnung.immobilie"}'},
		{
			"startobjekt": "Betriebskostenabrechnung Mieter",
			"pfad_zuordnung": '{"immobilie": "objekt.mietvertrag.wohnung.immobilie"}',
		},
		{
			"startobjekt": "Dunning",
			"pfad_zuordnung": '{"immobilie": "objekt.overdue_payments.sales_invoice.mietvertrag.wohnung.immobilie"}',
		},
	]
	if [row.as_dict() for row in doc.get("variables") or []] != variables:
		_set_child_table(doc, "variables", variables)
		changed = True
	if [
		{"startobjekt": row.startobjekt, "pfad_zuordnung": row.pfad_zuordnung}
		for row in doc.get("standardpfade") or []
	] != standardpfade:
		_set_child_table(doc, "standardpfade", standardpfade)
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_footer_rows(template_names: set[str]) -> None:
	if not frappe.db.exists("DocType", "Serienbrief Vorlagenbaustein"):
		return
	for template_name in sorted(template_names):
		if not frappe.db.exists("Serienbrief Vorlage", template_name):
			continue
		doc = frappe.get_doc("Serienbrief Vorlage", template_name)
		rows = [row for row in (doc.get("textbausteine") or []) if row.baustein == BLOCK_NAME]
		if rows:
			changed = False
			first = rows[0]
			if first.baustein_key != "bankverbindung_immobilie":
				first.baustein_key = "bankverbindung_immobilie"
				changed = True
			for duplicate in rows[1:]:
				doc.get("textbausteine").remove(duplicate)
				changed = True
			if changed:
				doc.save(ignore_permissions=True)
			continue
		doc.append(
			"textbausteine",
			{
				"baustein": BLOCK_NAME,
				"baustein_key": "bankverbindung_immobilie",
			},
		)
		doc.save(ignore_permissions=True)


def _deduplicate_footer_rows() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Vorlagenbaustein"):
		return
	rows = frappe.get_all(
		"Serienbrief Vorlagenbaustein",
		filters={"baustein": BLOCK_NAME, "baustein_key": "bankverbindung_immobilie"},
		fields=["parent"],
	)
	for template_name in sorted({row.parent for row in rows if row.parent}):
		_ensure_footer_rows({template_name})


def execute() -> None:
	_configure_block()
	_deduplicate_footer_rows()
	frappe.clear_cache(doctype="Serienbrief Vorlage")
	frappe.clear_cache(doctype="Serienbrief Textbaustein")
