from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr, formatdate

try:
	from pypdf import PdfReader, PdfWriter
	from pypdf.generic import NameObject, NumberObject
except Exception:  # pragma: no cover - fallback for older environments
	from PyPDF2 import PdfReader, PdfWriter
	from PyPDF2.generic import NameObject, NumberObject


def resolve_file_url_path(file_url: str) -> str:
	url = cstr(file_url).strip()
	if not url:
		frappe.throw(_("PDF-Datei fehlt."))

	if url.startswith("/private/files/"):
		rel = url.replace("/private/files/", "", 1)
		path = frappe.get_site_path("private", "files", rel)
	elif url.startswith("/files/"):
		rel = url.replace("/files/", "", 1)
		path = frappe.get_site_path("public", "files", rel)
	else:
		path = url

	if not Path(path).exists():
		frappe.throw(_("PDF-Datei nicht gefunden: {0}").format(frappe.bold(url)))

	return path


def read_file_url_bytes(file_url: str) -> bytes:
	path = resolve_file_url_path(file_url)
	with open(path, "rb") as handle:
		return handle.read()


def parse_pdf_pages(page_spec: str | None, total_pages: int) -> list[int]:
	if total_pages <= 0:
		return []

	spec = cstr(page_spec or "").strip()
	if not spec:
		return list(range(total_pages))

	selected: list[int] = []
	seen: set[int] = set()
	parts = [p.strip() for p in spec.split(",") if p.strip()]

	for part in parts:
		if "-" in part:
			start_str, end_str = [cstr(x).strip() for x in part.split("-", 1)]
			if not start_str.isdigit() or not end_str.isdigit():
				frappe.throw(_("Ungültiger Seitenbereich: {0}").format(frappe.bold(part)))
			start = int(start_str)
			end = int(end_str)
			if start <= 0 or end <= 0 or end < start:
				frappe.throw(_("Ungültiger Seitenbereich: {0}").format(frappe.bold(part)))
			for page_no in range(start, end + 1):
				index = page_no - 1
				if index >= total_pages:
					frappe.throw(
						_("Seite {0} ist außerhalb des PDFs (maximal {1}).").format(page_no, total_pages)
					)
				if index not in seen:
					seen.add(index)
					selected.append(index)
			continue

		if not part.isdigit():
			frappe.throw(_("Ungültige Seitenangabe: {0}").format(frappe.bold(part)))
		page_no = int(part)
		if page_no <= 0:
			frappe.throw(_("Ungültige Seitenangabe: {0}").format(frappe.bold(part)))
		index = page_no - 1
		if index >= total_pages:
			frappe.throw(_("Seite {0} ist außerhalb des PDFs (maximal {1}).").format(page_no, total_pages))
		if index not in seen:
			seen.add(index)
			selected.append(index)

	if not selected:
		frappe.throw(_("Die Seitenauswahl ergibt keine gültigen Seiten."))
	return selected


def extract_pdf_form_field_names(file_url: str) -> list[str]:
	reader = PdfReader(BytesIO(read_file_url_bytes(file_url)))
	fields = reader.get_fields() or {}
	return sorted([cstr(name).strip() for name in fields.keys() if cstr(name).strip()])


def _normalize_mapping_value(value: Any, value_type: str) -> Any:
	kind = cstr(value_type or "String").strip() or "String"
	if value is None:
		return None

	if kind == "Zahl":
		text = cstr(value).strip().replace(",", ".")
		if not text:
			return None
		try:
			return float(text)
		except Exception:
			frappe.throw(_("Ungültiger Zahlenwert: {0}").format(frappe.bold(cstr(value))))

	if kind == "Bool":
		if isinstance(value, bool):
			return value
		text = cstr(value).strip().lower()
		if text in {"1", "true", "wahr", "ja", "yes"}:
			return True
		if text in {"0", "false", "falsch", "nein", "no"}:
			return False
		frappe.throw(_("Ungültiger Bool-Wert: {0}").format(frappe.bold(cstr(value))))

	if kind == "Datum":
		text = cstr(value).strip()
		if not text:
			return None
		try:
			return formatdate(text)
		except Exception:
			return text

	return cstr(value)


def _set_fields_read_only(writer: PdfWriter) -> None:
	for page in writer.pages:
		annots = page.get("/Annots")
		if not annots:
			continue
		for annot_ref in annots:
			try:
				annot = annot_ref.get_object()
			except Exception:
				continue
			if cstr(annot.get("/Subtype")) != "/Widget":
				continue
			flags = int(annot.get("/Ff", 0) or 0)
			annot.update({NameObject("/Ff"): NumberObject(flags | 1)})


def render_pdf_form_block(block_doc, context: dict[str, Any], resolve_value_path) -> bytes:
	file_url = cstr(getattr(block_doc, "pdf_file", None) or "").strip()
	if not file_url:
		frappe.throw(
			_("PDF-Datei fehlt im Textbaustein {0}.").format(
				frappe.bold(getattr(block_doc, "title", None) or getattr(block_doc, "name", ""))
			)
		)

	reader = PdfReader(BytesIO(read_file_url_bytes(file_url)))
	if not reader.pages:
		frappe.throw(_("PDF-Datei enthält keine Seiten."))

	acro_form = None
	try:
		acro_form = reader.trailer.get("/Root", {}).get("/AcroForm")
	except Exception:
		acro_form = None
	if acro_form and acro_form.get("/XFA"):
		frappe.throw(_("XFA-Formulare werden aktuell nicht unterstützt."))

	selected_pages = parse_pdf_pages(getattr(block_doc, "pdf_pages", None), len(reader.pages))
	writer = PdfWriter()
	for idx in selected_pages:
		writer.add_page(reader.pages[idx])

	# Ensure the writer has an AcroForm so update_page_form_field_values works.
	if "/AcroForm" not in writer._root_object:
		if acro_form is not None:
			writer._root_object[NameObject("/AcroForm")] = acro_form
		else:
			from pypdf.generic import ArrayObject, DictionaryObject
			writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
				{NameObject("/Fields"): ArrayObject()}
			)

	form_fields = reader.get_fields() or {}
	field_values: dict[str, Any] = {}
	for row in getattr(block_doc, "pdf_field_mappings", []) or []:
		field_name = cstr(getattr(row, "pdf_field_name", None) or "").strip()
		if not field_name:
			continue

		if form_fields and field_name not in form_fields:
			frappe.throw(
				_("PDF-Feld {0} existiert nicht in Baustein {1}.").format(
					frappe.bold(field_name),
					frappe.bold(getattr(block_doc, "title", None) or getattr(block_doc, "name", "")),
				)
			)

		path = cstr(getattr(row, "value_path", None) or "").strip()
		fallback = getattr(row, "fallback_value", None)
		required = bool(int(getattr(row, "required", 0) or 0))
		value_type = cstr(getattr(row, "value_type", None) or "String").strip() or "String"

		resolved = resolve_value_path(path, context) if path else None
		if resolved in (None, ""):
			resolved = fallback

		if resolved in (None, ""):
			if required:
				frappe.throw(
					_("Pflichtfeld {0} im PDF-Baustein {1} konnte nicht befüllt werden.").format(
						frappe.bold(field_name),
						frappe.bold(getattr(block_doc, "title", None) or getattr(block_doc, "name", "")),
					)
				)
			continue

		field_values[field_name] = _normalize_mapping_value(resolved, value_type)

	if field_values:
		for page in writer.pages:
			try:
				writer.update_page_form_field_values(page, field_values, auto_regenerate=False)
			except TypeError:
				writer.update_page_form_field_values(page, field_values)

	if bool(int(getattr(block_doc, "pdf_flatten", 1) or 0)):
		_set_fields_read_only(writer)

	out = BytesIO()
	writer.write(out)
	return out.getvalue()


def render_pdf_bytes_as_html_fragment(pdf_bytes: bytes) -> str:
	"""Convert PDF bytes to a self-contained HTML fragment for inline preview.

	Embeds the PDF directly via an ``<embed>`` tag so the browser renders
	the real PDF with full text search and selection support.
	Each page is represented by one ``hv-pdf-page-image`` marker div
	(used by the hybrid renderer to count pages).
	"""
	if not pdf_bytes:
		return ""

	import base64

	reader = PdfReader(BytesIO(pdf_bytes))
	page_count = len(reader.pages) if reader.pages else 1

	b64 = base64.b64encode(pdf_bytes).decode("ascii")
	# Height heuristic: ~1100px per A4 page.
	height = max(600, page_count * 1100)

	page_markers = "".join(
		'<div class="hv-pdf-page-image"></div>' for _ in range(page_count)
	)

	return (
		'<div class="hv-pdf-inline-fragment">'
		f'<embed src="data:application/pdf;base64,{b64}" '
		f'type="application/pdf" '
		f'style="width:100%;height:{height}px;display:block;page-break-before:always;" />'
		f"{page_markers}"
		"</div>"
	)


def _pdf_html_error_fragment(title: str, details: str | None = None) -> str:
	escaped_title = frappe.utils.escape_html(cstr(title or "").strip() or _("Unbekannter Fehler"))
	escaped_details = frappe.utils.escape_html(cstr(details or "").strip())[:8000]
	details_html = (
		f'<pre style="margin:8px 0 0; white-space:pre-wrap;">{escaped_details}</pre>'
		if escaped_details
		else ""
	)
	return (
		'<div class="hv-pdf-inline-error" '
		'style="border:1px solid #c53030; background:#fff5f5; color:#742a2a; '
		'padding:10px; margin:10px 0; font-size:11px;">'
		f'<strong>PDF->HTML Fehler:</strong> {escaped_title}'
		f"{details_html}</div>"
	)
