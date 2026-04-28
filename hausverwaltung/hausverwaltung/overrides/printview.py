from __future__ import annotations

import frappe
from frappe.www import printview as core_printview

from frappe.utils import cstr

from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_for_print_format
from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_pdf_for_print_format
from hausverwaltung.hausverwaltung.utils.serienbrief_print import scrub_value as hv_scrub
from hausverwaltung.hausverwaltung.utils.serienbrief_print import normalize_print_format_name


@frappe.whitelist()
def get_html_and_style(
	doc=None,
	name=None,
	print_format=None,
	style=None,
	trigger_print: int | str = 0,
	no_letterhead: int | str = 0,
	letterhead=None,
	doctype=None,
	**kwargs,
):
	doc_dict = None
	docname = name
	doc_doctype = doctype

	if doc:
		doc_dict = doc
		if isinstance(doc, str):
			try:
				doc_dict = frappe.parse_json(doc)
			except Exception:
				doc_dict = None
		if isinstance(doc_dict, dict):
			docname = docname or doc_dict.get("name")
			doc_doctype = doc_doctype or doc_dict.get("doctype")

	serienbrief_html = render_serienbrief_for_print_format(
		print_format, doc=doc_dict or doc, docname=docname, doctype=doc_doctype
	)
	if serienbrief_html:
		return {"html": serienbrief_html, "style": style}

	# Align with Frappe signature; drop unsupported kwargs like lang.
	fallback_format = normalize_print_format_name(print_format)

	return core_printview.get_html_and_style(
		doc_doctype or doc,
		docname,
		print_format=fallback_format,
		style=style,
		trigger_print=trigger_print,
		no_letterhead=no_letterhead,
		letterhead=letterhead,
	)


@frappe.whitelist()
def download_pdf(
	doctype=None,
	name=None,
	format=None,
	doc=None,
	no_letterhead: int | str = 0,
	letterhead=None,
	**kwargs,
):
	doc_dict = None
	docname = name
	doc_doctype = doctype

	if doc:
		doc_dict = doc
		if isinstance(doc, str):
			try:
				doc_dict = frappe.parse_json(doc)
			except Exception:
				doc_dict = None
		if isinstance(doc_dict, dict):
			docname = docname or doc_dict.get("name")
			doc_doctype = doc_doctype or doc_dict.get("doctype")

	serienbrief_pdf = render_serienbrief_pdf_for_print_format(
		format, doc=doc_dict or doc, docname=docname, doctype=doc_doctype
	)
	if serienbrief_pdf:
		frappe.local.response.filename = f"{hv_scrub(docname or '')}.pdf"
		frappe.local.response.filecontent = serienbrief_pdf
		frappe.local.response.type = "pdf"
		return

	fallback_format = normalize_print_format_name(format)

	# Serienbrief Dokument: re-render PDF on-the-fly from the Vorlage so that
	# PDF form pages are always correctly included.  The HTML preview uses
	# <embed> tags which wkhtmltopdf cannot render, so we must bypass HTML
	# and render segments (HTML→wkhtmltopdf + raw PDF bytes) directly.
	if (doc_doctype or "").strip() == "Serienbrief Dokument" and docname:
		pdf_content = _render_serienbrief_dokument_pdf(docname)
		if pdf_content:
			frappe.local.response.filename = f"{hv_scrub(docname or '')}.pdf"
			frappe.local.response.filecontent = pdf_content
			frappe.local.response.type = "pdf"
			return

	return core_printview.download_pdf(
		doc_doctype or doc,
		docname,
		format=fallback_format,
		doc=doc_dict or doc,
		no_letterhead=no_letterhead,
		letterhead=letterhead,
	)


def _render_serienbrief_dokument_pdf(docname: str) -> bytes | None:
	"""Re-render a Serienbrief Dokument PDF from its Vorlage + objekt.

	This builds an in-memory Durchlauf with the single iteration object and
	renders the template segments (HTML→wkhtmltopdf + raw PDF form bytes),
	so the result always contains the correctly merged PDF form pages.
	"""
	from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
		SerienbriefDurchlauf,
		_collect_template_requirements,
	)

	try:
		target_doc = frappe.get_doc("Serienbrief Dokument", docname)
	except frappe.DoesNotExistError:
		return None

	vorlage_name = cstr(getattr(target_doc, "vorlage", None) or "").strip()
	objekt = cstr(getattr(target_doc, "objekt", None) or "").strip()
	iteration_doctype = cstr(getattr(target_doc, "iteration_doctype", None) or "").strip()

	if not vorlage_name or not objekt or not iteration_doctype:
		# Fall back to cached file if we can't re-render.
		return _read_cached_pdf(target_doc)

	try:
		template = frappe.get_cached_doc("Serienbrief Vorlage", vorlage_name)
	except frappe.DoesNotExistError:
		return _read_cached_pdf(target_doc)

	durchlauf: SerienbriefDurchlauf = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"vorlage": vorlage_name,
			"iteration_doctype": iteration_doctype,
			"date": getattr(target_doc, "date", None) or frappe.utils.today(),
			"variablen_werte": getattr(target_doc, "variablen_werte", None),
			"iteration_objekte": [
				{
					"doctype": "Serienbrief Iterationsobjekt",
					"iteration_doctype": iteration_doctype,
					"objekt": objekt,
				}
			],
		}
	)
	durchlauf.flags.ignore_mandatory = True
	durchlauf.flags.ignore_permissions = True

	try:
		empfaenger_rows = durchlauf._get_empfaenger_rows()
		if not empfaenger_rows:
			return _read_cached_pdf(target_doc)

		template_requirements = _collect_template_requirements(template, iteration_doctype)
		row = empfaenger_rows[0]
		context = durchlauf._build_context(row, 1, template_requirements, template, total=1)
		segments = durchlauf._render_template_content(template, context)
		if not segments:
			return _read_cached_pdf(target_doc)

		return durchlauf._render_segments_pdf_bytes(segments)
	except Exception:
		frappe.log_error(
			title="Serienbrief PDF Re-Render",
			message=f"Failed to re-render Serienbrief Dokument {docname}",
		)
		return _read_cached_pdf(target_doc)


def _read_cached_pdf(target_doc) -> bytes | None:
	"""Read the cached generated_pdf_file as fallback."""
	from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import read_file_url_bytes

	pdf_url = cstr(getattr(target_doc, "generated_pdf_file", None) or "").strip()
	if not pdf_url:
		return None
	try:
		return read_file_url_bytes(pdf_url)
	except Exception:
		return None
