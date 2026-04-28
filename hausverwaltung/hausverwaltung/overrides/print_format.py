from __future__ import annotations

from typing import Literal

import frappe
from frappe.utils import print_format as core_print_format
from frappe.www.printview import validate_print_permission

from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_pdf_for_print_format
from hausverwaltung.hausverwaltung.utils.serienbrief_print import scrub_value as hv_scrub


@frappe.whitelist(allow_guest=True)
def download_pdf(
	doctype: str,
	name: str,
	format=None,
	doc=None,
	no_letterhead=0,
	language=None,
	letterhead=None,
	pdf_generator: Literal["wkhtmltopdf", "chrome"] | None = None,
):
	doc = doc or frappe.get_doc(doctype, name)
	validate_print_permission(doc)

	serienbrief_pdf = render_serienbrief_pdf_for_print_format(
		format,
		doc=doc,
		docname=name,
		doctype=doctype,
	)
	if serienbrief_pdf:
		frappe.local.response.filename = f"{hv_scrub(name or '')}.pdf"
		frappe.local.response.filecontent = serienbrief_pdf
		frappe.local.response.type = "pdf"
		return

	return core_print_format.download_pdf(
		doctype=doctype,
		name=name,
		format=format,
		doc=doc,
		no_letterhead=no_letterhead,
		language=language,
		letterhead=letterhead,
		pdf_generator=pdf_generator,
	)
