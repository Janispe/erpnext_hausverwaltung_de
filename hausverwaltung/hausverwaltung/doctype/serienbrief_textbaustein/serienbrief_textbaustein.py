from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import extract_pdf_form_field_names


class SerienbriefTextbaustein(Document):
	def validate(self):
		content_type = cstr(getattr(self, "content_type", None) or "").strip() or "Textbaustein (Rich Text)"
		self.content_type = content_type
		if content_type != "PDF Formular":
			return

		if not cstr(getattr(self, "pdf_file", None) or "").strip():
			frappe.throw(_("Bitte eine PDF-Datei auswählen."))


@frappe.whitelist()
def get_pdf_form_fields(docname: str | None = None, pdf_file: str | None = None) -> list[str]:
	file_url = cstr(pdf_file or "").strip()
	if not file_url and docname:
		doc = frappe.get_doc("Serienbrief Textbaustein", docname)
		file_url = cstr(getattr(doc, "pdf_file", None) or "").strip()
	if not file_url:
		frappe.throw(_("Bitte eine PDF-Datei auswählen."))
	return extract_pdf_form_field_names(file_url)
