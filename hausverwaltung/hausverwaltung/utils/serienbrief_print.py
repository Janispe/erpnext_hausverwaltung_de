from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import today
from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	SerienbriefDurchlauf,
	_collect_template_requirements,
	_get_template_template_source,
)

SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"
INVOICE_REMARKS_OVERRIDES_VARIABLE = "rechnungsbemerkungen"


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
	"""Render Serienbrief HTML when the print context resolves to a Serienbrief Vorlage.

	Returns ``None`` when no Serienbrief Vorlage is configured so that the caller can
	fall back to the standard printing logic.
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
	target_doc = getattr(serienbrief_doc, "_hv_target_doc", None)
	iteration_rows = (
		[_build_target_row(serienbrief_doc, iteration_doctype, target_doc)]
		if target_doc is not None
		else serienbrief_doc._get_iteration_rows()
	)

	if not iteration_rows:
		frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

	has_blocks = bool(template.get("textbausteine"))
	has_content = bool(_get_template_template_source(template).strip())
	if not has_blocks and not has_content:
		frappe.throw(_("Die gewählte Vorlage enthält keinen Inhalt."))

	pdf_chunks: list[bytes] = []
	total = len(iteration_rows)
	for idx, row in enumerate(iteration_rows, start=1):
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
		footer_doc = frappe._dict(
			vorlage=serienbrief_doc.vorlage,
			iteration_doctype=iteration_doctype,
			objekt=getattr(row, "objekt", None),
			date=serienbrief_doc.date,
		)
		footer_doc._iteration_doc = getattr(row, "_iteration_doc", None)
		pdf_chunks.append(serienbrief_doc._render_segments_pdf_bytes(segments, footer_doc=footer_doc))

	return serienbrief_doc._merge_pdf_chunks(pdf_chunks)


def _resolve_serienbrief_print_context(
	print_format: str | None,
	doc: Any = None,
	docname: str | None = None,
	doctype: str | None = None,
) -> tuple[Any, SerienbriefDurchlauf] | None:
	"""Resolve a Serienbrief Vorlage and build an in-memory Serienbrief Durchlauf."""

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
	pf_doc = None
	if print_format_name:
		try:
			pf_doc = frappe.get_cached_doc("Print Format", print_format_name)
		except frappe.DoesNotExistError:
			pf_doc = None

	target_doc = _coerce_doc(
		doc,
		doctype or getattr(pf_doc, "doc_type", None) or target_doctype,
		docname,
	)
	if not target_doc:
		return None

	template_name = (
		_get_direct_dunning_template(target_doc)
		or ((pf_doc.get(SERIENBRIEF_FIELDNAME) or "").strip() if pf_doc else "")
		or (getattr(target_doc, SERIENBRIEF_FIELDNAME, None) or "").strip()
	)
	if not template_name:
		return None

	template = frappe.get_cached_doc("Serienbrief Vorlage", template_name)
	iteration_doctype = _determine_iteration_doctype(template, pf_doc, target_doc)

	serienbrief_doc = _build_serienbrief_doc(template, iteration_doctype, target_doc)
	return template, serienbrief_doc


def _get_direct_dunning_template(target_doc) -> str:
	"""Return the template configured on a Dunning document, if any.

	Mahnungen are the one case where the business configuration lives on the
	document or Dunning Type, not primarily on the selected Print Format.
	"""
	if (getattr(target_doc, "doctype", None) or "").strip() != "Dunning":
		return ""
	template = (getattr(target_doc, SERIENBRIEF_FIELDNAME, None) or "").strip()
	if template:
		return template

	dunning_type = (getattr(target_doc, "dunning_type", None) or "").strip()
	if not dunning_type:
		return ""

	try:
		if not frappe.db.has_column("Dunning Type", SERIENBRIEF_FIELDNAME):
			return ""
		return (frappe.db.get_value("Dunning Type", dunning_type, SERIENBRIEF_FIELDNAME) or "").strip()
	except Exception:
		return ""


def _determine_iteration_doctype(template, pf_doc, target_doc) -> str:
	template_dt = (template.get("haupt_verteil_objekt") or "").strip()
	print_format_dt = (pf_doc.get("doc_type") or "").strip() if pf_doc else ""
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
	iteration_values = None
	if getattr(target_doc, "doctype", None) == "Dunning":
		from hausverwaltung.hausverwaltung.doctype.dunning import collect_serienbrief_werte

		_attach_dunning_contract(target_doc)
		werte = collect_serienbrief_werte(target_doc)
		iteration_values = frappe.as_json(werte) if werte else None

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
					"variablen_werte": iteration_values,
				}
			],
		}
	)
	serienbrief_doc.flags.ignore_mandatory = True
	serienbrief_doc.flags.ignore_permissions = True
	serienbrief_doc._hv_target_doc = target_doc
	return serienbrief_doc


def _attach_dunning_contract(dunning) -> None:
	"""Expose invoice labels and the one contract shared by all dunned invoices."""
	contracts: dict[str, Any] = {}
	remark_overrides = get_dunning_invoice_remark_overrides(dunning)
	for payment in dunning.get("overdue_payments") or []:
		invoice_name = (payment.get("sales_invoice") or "").strip()
		if not invoice_name:
			continue
		invoice = frappe.get_cached_doc("Sales Invoice", invoice_name)
		remarks = (
			remark_overrides[invoice_name]
			if invoice_name in remark_overrides
			else (getattr(invoice, "remarks", None) or "").strip()
		)
		# ``Overdue Payment`` has no field for the human-readable invoice text.
		# Attach it only for the in-memory Serienbrief context; the Dunning schema
		# and the persisted accounting reference remain unchanged.
		payment.sales_invoice_remarks = remarks
		resolver = getattr(invoice, "resolve_serienbrief_path_segment", None)
		contract = resolver("mietvertrag") if callable(resolver) else None
		if contract is not None:
			contracts[contract.name] = contract

	if len(contracts) > 1:
		frappe.throw(
			_("Die Rechnungen der Mahnung gehören zu unterschiedlichen Mietverträgen."),
			frappe.ValidationError,
		)
	if contracts:
		dunning.mietvertrag = next(iter(contracts.values()))


def get_dunning_invoice_remark_overrides(dunning) -> dict[str, str]:
	"""Read per-invoice display texts persisted with one Dunning document."""
	for row in dunning.get("hv_serienbrief_werte") or []:
		variable = (row.get("variable") or "").strip()
		if frappe.scrub(variable) != INVOICE_REMARKS_OVERRIDES_VARIABLE:
			continue
		raw = row.get("wert")
		if isinstance(raw, str):
			try:
				raw = json.loads(raw or "{}")
			except (TypeError, ValueError):
				return {}
		if not isinstance(raw, dict):
			return {}
		return {
			str(invoice_name).strip(): str(remark or "").strip()
			for invoice_name, remark in raw.items()
			if str(invoice_name or "").strip()
		}
	return {}


def _build_target_row(serienbrief_doc, iteration_doctype: str, target_doc):
	"""Baut eine Iterationszeile direkt aus einem gespeicherten oder ephemeren Doc."""
	row_data: dict[str, Any] = {
		"iteration_doctype": iteration_doctype,
		"iteration_objekt": target_doc.name,
		"objekt": target_doc.name,
	}
	link_map = serienbrief_doc._get_iteration_link_field_map(iteration_doctype)
	target_field = link_map.get(iteration_doctype)
	if target_field:
		row_data[target_field] = target_doc.name

	for field in frappe.get_meta(iteration_doctype).fields:
		if field.fieldtype != "Link" or not field.options:
			continue
		value = getattr(target_doc, field.fieldname, None)
		if value:
			row_data.setdefault(field.fieldname, value)

	display_name = (
		getattr(target_doc, "anzeigename", None)
		or getattr(target_doc, "title", None)
		or getattr(target_doc, "customer_name", None)
		or getattr(target_doc, "name", None)
	)
	if display_name:
		row_data["anzeigename"] = display_name

	row = frappe._dict(row_data)
	row._iteration_doc = target_doc
	row._iteration_rowname = None
	iteration_values = None
	for iteration_row in getattr(serienbrief_doc, "iteration_objekte", []) or []:
		iteration_values = getattr(iteration_row, "variablen_werte", None)
		break
	row._iteration_variablen_werte = iteration_values
	return row
