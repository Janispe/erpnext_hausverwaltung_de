from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import today

from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	SerienbriefDurchlauf,
)
from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_collect_template_requirements,
)
from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_get_template_template_source,
)

SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"


def scrub_value(value) -> str:
	"""Minimal scrub replacement; uses frappe.scrub when available."""
	scrub_fn = getattr(frappe, "scrub", None)
	if callable(scrub_fn):
		try:
			return scrub_fn(value)
		except Exception:
			pass

	text = str(value or "")
	cleaned = []
	for char in text:
		if char.isalnum() or char in ("-", "_", "."):
			cleaned.append(char)
		else:
			cleaned.append("-")
	return "".join(cleaned).strip("-").lower()


def normalize_print_format_name(value: str | None) -> str | None:
	"""Return a usable print format name or None to fall back to defaults."""
	if not value:
		return None

	name = str(value).strip()
	if not name:
		return None

	# Treat the built-in "Standard" format as implicit; avoid failing lookups.
	if name.lower() == "standard":
		return None

	if not frappe.db.exists("Print Format", name):
		return None

	return name


def render_serienbrief_for_print_format(
	print_format: str | None,
	doc: Any = None,
	docname: str | None = None,
	doctype: str | None = None,
) -> str | None:
	"""Render Serienbrief HTML when the Print Format is linked to a Serienbrief Vorlage.

	Returns ``None`` when no Serienbrief Vorlage is configured on the Print Format so that
	the caller can fall back to the standard printing logic.
	"""
	context = _resolve_serienbrief_print_context(
		print_format=print_format,
		doc=doc,
		docname=docname,
		doctype=doctype,
	)
	if not context:
		return None

	template, serienbrief_doc = context
	return serienbrief_doc._render_full_html()


def render_serienbrief_pdf_for_print_format(
	print_format: str | None,
	doc: Any = None,
	docname: str | None = None,
	doctype: str | None = None,
) -> bytes | None:
	"""Render the final Serienbrief PDF, including merged PDF form blocks."""
	context = _resolve_serienbrief_print_context(
		print_format=print_format,
		doc=doc,
		docname=docname,
		doctype=doctype,
	)
	if not context:
		return None

	template, serienbrief_doc = context
	iteration_doctype = (serienbrief_doc.iteration_doctype or "").strip()
	template_requirements = _collect_template_requirements(template, iteration_doctype)
	empfaenger_rows = serienbrief_doc._get_empfaenger_rows()

	if not empfaenger_rows:
		frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

	serienbrief_doc._validate_required_fields(template_requirements, empfaenger_rows)

	has_blocks = bool(template.get("textbausteine"))
	has_content = bool(_get_template_template_source(template).strip())
	if not has_blocks and not has_content:
		frappe.throw(_("Die gewählte Vorlage enthält keinen Inhalt."))

	pdf_chunks: list[bytes] = []
	total = len(empfaenger_rows)
	for idx, row in enumerate(empfaenger_rows, start=1):
		context_data = serienbrief_doc._build_context(
			row, idx, template_requirements, template, total=total
		)
		segments = serienbrief_doc._render_template_content(template, context_data)
		if not segments:
			frappe.throw(
				_(
					"Die gewählte Vorlage liefert keinen renderbaren Inhalt. "
					"Bitte prüfen Sie die Textbausteine."
				)
			)
		pdf_chunks.append(serienbrief_doc._render_segments_pdf_bytes(segments))

	return serienbrief_doc._merge_pdf_chunks(pdf_chunks)


def _resolve_serienbrief_print_context(
	print_format: str | None,
	doc: Any = None,
	docname: str | None = None,
	doctype: str | None = None,
) -> tuple[Any, SerienbriefDurchlauf] | None:
	"""Resolve linked Serienbrief Vorlage and build an in-memory Serienbrief Durchlauf."""

	target_doctype = (
		doctype
		or (doc.get("doctype") if isinstance(doc, dict) else None)
		or getattr(doc, "doctype", None)
		or ""
	).strip()

	print_format_name = (print_format or "").strip()
	if not print_format_name and target_doctype:
		try:
			print_format_name = (frappe.get_meta(target_doctype).default_print_format or "").strip()
		except frappe.DoesNotExistError:
			print_format_name = ""

	print_format_name = normalize_print_format_name(print_format_name)
	if not print_format_name:
		# Without a concrete Print Format we cannot look up the Serienbrief setting.
		return None

	try:
		pf_doc = frappe.get_cached_doc("Print Format", print_format_name)
	except frappe.DoesNotExistError:
		return None

	target_doc = _coerce_doc(doc, doctype or pf_doc.doc_type or target_doctype, docname)
	if not target_doc:
		return None

	template_name = (
		(pf_doc.get(SERIENBRIEF_FIELDNAME) or "").strip()
		or (getattr(target_doc, SERIENBRIEF_FIELDNAME, None) or "").strip()
	)
	if not template_name:
		return None

	template = frappe.get_cached_doc("Serienbrief Vorlage", template_name)
	iteration_doctype = _determine_iteration_doctype(template, pf_doc, target_doc)

	serienbrief_doc = _build_serienbrief_doc(template, iteration_doctype, target_doc)
	return template, serienbrief_doc


def _determine_iteration_doctype(template, pf_doc, target_doc) -> str:
	template_dt = (template.get("haupt_verteil_objekt") or "").strip()
	print_format_dt = (pf_doc.get("doc_type") or "").strip()
	target_dt = (getattr(target_doc, "doctype", None) or "").strip()

	iteration_doctype = template_dt or print_format_dt or target_dt
	if iteration_doctype and target_dt and iteration_doctype != target_dt:
		frappe.throw(
			_("Serienbrief Vorlage {0} erwartet Doctype {1}, Druckdokument ist aber {2}.").format(
				scrub_value(template.name), iteration_doctype, target_dt
			)
		)

	return iteration_doctype or target_dt


def _coerce_doc(doc: Any, doctype: str | None, docname: str | None):
	if isinstance(doc, str):
		try:
			doc = json.loads(doc)
		except Exception:
			doc = None

	if isinstance(doc, dict):
		return frappe.get_doc(doc)

	if doc and getattr(doc, "doctype", None):
		return doc

	if doctype and docname:
		return frappe.get_doc(doctype, docname)

	return None


def _pick_letter_date(doc) -> str:
	for field in ("date", "posting_date", "transaction_date", "due_date"):
		value = getattr(doc, field, None)
		if value:
			return value
	return today()


def _build_serienbrief_doc(template, iteration_doctype: str, target_doc) -> SerienbriefDurchlauf:
	title = (
		getattr(target_doc, "title", None)
		or getattr(target_doc, "subject", None)
		or getattr(target_doc, "name", None)
	)
	serienbrief_doc = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"title": title,
			"vorlage": template.name,
			"kategorie": getattr(template, "kategorie", None),
			"iteration_doctype": iteration_doctype,
			"date": _pick_letter_date(target_doc),
			"iteration_objekte": [
				{
					"doctype": "Serienbrief Iterationsobjekt",
					"iteration_doctype": iteration_doctype,
					"objekt": target_doc.name,
				}
			],
		}
	)
	serienbrief_doc.flags.ignore_mandatory = True
	serienbrief_doc.flags.ignore_permissions = True
	return serienbrief_doc
