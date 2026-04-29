from __future__ import annotations

import json
import os
import re
import uuid
from collections import defaultdict
from io import BytesIO
from typing import Any, Dict, List

import frappe
from bs4 import BeautifulSoup
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from jinja2 import TemplateError, UndefinedError
from markupsafe import Markup
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document
from frappe.utils import cstr, format_date, today
from frappe.utils.jinja import get_jenv

from hausverwaltung.hausverwaltung.utils.pdf_engine import render_pdf as get_pdf

from hausverwaltung.hausverwaltung.utils.jinja_source_sanitizer import sanitize_richtext_jinja_source
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import read_file_url_bytes
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import render_pdf_bytes_as_html_fragment
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import render_pdf_form_block


class _IterationEmpfaengerRow:
	def __init__(self, data: dict[str, Any]):
		object.__setattr__(self, "_data", dict(data))

	def __getattr__(self, key: str):
		return self._data.get(key)

	def __setattr__(self, key: str, value):
		if key.startswith("_"):
			object.__setattr__(self, key, value)
		else:
			self._data[key] = value

	def as_dict(self) -> dict[str, Any]:
		return dict(self._data)


def _render_serienbrief_template(template: str, context: Dict[str, Any]) -> str:
	"""Render templates for Serienbrief with clearer errors for missing fields."""
	if not template:
		return ""
	if ".__" in template:
		frappe.throw(_("Illegal template"))
	try:
		return get_jenv().from_string(template).render(context)
	except UndefinedError as exc:
		raw = str(exc) or _("Ein benötigtes Feld fehlt.")
		msg = _("Fehlendes Feld im Serienbrief: {0}").format(frappe.utils.escape_html(raw))
		frappe.throw(title=_("Serienbrief Fehler"), msg=msg)
	except TemplateError:
		frappe.throw(
			title="Jinja Template Error",
			msg=f"<pre>{template}</pre><pre>{frappe.get_traceback()}</pre>",
		)


def _get_template_template_source(template_doc) -> str:
	content_type = (getattr(template_doc, "content_type", "") or "").strip() or "Textbaustein (Rich Text)"
	if content_type == "HTML + Jinja":
		parts = [
			cstr(getattr(template_doc, "jinja_content", "") or ""),
			cstr(getattr(template_doc, "html_content", "") or ""),
		]
		return "\n".join([p for p in parts if p.strip()])

	return sanitize_richtext_jinja_source(cstr(getattr(template_doc, "content", "")).strip())


class SerienbriefDurchlauf(Document):
	def on_update(self) -> None:
		# Draft: bei jedem Save Dokumente neu rendern, damit HTML/PDF pro Iteration
		# immer den aktuellen Stand der Variablenwerte widerspiegeln.
		if int(getattr(self, "docstatus", 0) or 0) != 0:
			return
		if not self.vorlage or not (getattr(self, "iteration_objekte", None) or []):
			return
		# strict_variables=False: der User darf noch Werte setzen, ohne beim Save zu werfen.
		self._ensure_dokumente(recreate=True, submit=False, strict_variables=False)

	def on_submit(self) -> None:
		# Finaler Snapshot: Dokumente neu erzeugen und submitten.
		self._ensure_dokumente(recreate=True, submit=True, strict_variables=True)

	def on_cancel(self) -> None:
		# Beim Cancel: verknüpfte Serienbrief Dokumente mit canceln und löschen,
		# damit sie nicht als Waisen stehen bleiben.
		self._remove_linked_dokumente()

	def on_trash(self) -> None:
		# Beim Löschen: verknüpfte Serienbrief Dokumente mit entfernen.
		self._remove_linked_dokumente()

	def _remove_linked_dokumente(self) -> None:
		dokumente = frappe.get_all(
			"Serienbrief Dokument",
			filters={"durchlauf": self.name},
			pluck="name",
		)
		for docname in dokumente:
			doc = frappe.get_doc("Serienbrief Dokument", docname)
			if int(getattr(doc, "docstatus", 0) or 0) == 1:
				try:
					doc.cancel()
				except Exception:
					pass
			frappe.delete_doc(
				"Serienbrief Dokument",
				docname,
				force=1,
				ignore_permissions=True,
				delete_permanently=True,
			)

	def generate_pdf_file(
		self,
		print_format: str | None = None,
		recreate_documents: bool = False,
	) -> str:
		submit_docs = bool(int(getattr(self, "docstatus", 0) or 0))
		# Drafts: immer neu rendern, sonst werden Variablen-Änderungen aus dem
		# Formular nicht berücksichtigt und ein veralteter gespeicherter PDF-Cache
		# der Serienbrief Dokumente landet im Merge.
		recreate = bool(recreate_documents) or not submit_docs
		dokumente = self._ensure_dokumente(
			recreate=recreate,
			submit=submit_docs,
			strict_variables=True,
		)
		pdf_bytes = self._build_merged_pdf(dokumente, print_format=print_format)
		return self._store_pdf(pdf_bytes)

	def generate_html_file(self) -> str:
		# Für Debug/Entwicklung weiterhin das gesamte HTML (alle Seiten) erzeugen.
		full_html = self._render_full_html()
		return self._store_html(full_html)

	def _ensure_dokumente(
		self,
		recreate: bool = False,
		submit: bool = False,
		strict_variables: bool = True,
	) -> list[str]:
		existing = frappe.get_all(
			"Serienbrief Dokument",
			filters={"durchlauf": self.name},
			order_by="creation asc",
			pluck="name",
		)
		if existing and not recreate:
			return list(existing)

		if existing and recreate:
			for name in existing:
				frappe.delete_doc("Serienbrief Dokument", name, force=1, ignore_permissions=True)

		return self._create_dokumente(submit=submit, strict_variables=strict_variables)

	def _create_dokumente(self, *, submit: bool, strict_variables: bool = True) -> list[str]:
		if not self.vorlage:
			frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

		template = frappe.get_cached_doc("Serienbrief Vorlage", self.vorlage)
		iteration_doctype = self.iteration_doctype or template.get("haupt_verteil_objekt")
		if not iteration_doctype:
			frappe.throw(_("Bitte wählen Sie einen Iterations-Doctype."))
		if not self.iteration_doctype:
			self.iteration_doctype = iteration_doctype

		template_requirements = _collect_template_requirements(template, iteration_doctype)
		empfaenger_rows = self._get_empfaenger_rows()
		if not empfaenger_rows:
			frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

		self._validate_required_fields(template_requirements, empfaenger_rows)

		has_blocks = bool(template.get("textbausteine"))
		has_content = bool(_get_template_template_source(template).strip())
		if not has_blocks and not has_content:
			frappe.throw(_("Die gewählte Vorlage enthält keinen Inhalt."))

		created: list[str] = []
		total = len(empfaenger_rows)
		for idx, row in enumerate(empfaenger_rows, start=1):
			context = self._build_context(
				row,
				idx,
				template_requirements,
				template,
				total=total,
				strict_variables=strict_variables,
			)
			segments = self._render_template_content(template, context)
			if not segments:
				continue
			preview_pages = self._render_segments_preview_pages(segments)
			pdf_bytes = self._render_segments_pdf_bytes(segments)
			if not preview_pages and not pdf_bytes:
				continue

			page_html = self._wrap_html_fragment(
				"\n".join(f'<div class="serienbrief-page">{page}</div>' for page in preview_pages)
			)
			title = getattr(row, "anzeigename", None) or getattr(row, "iteration_objekt", None) or ""
			objekt = getattr(row, "iteration_objekt", None) or getattr(row, "objekt", None) or ""
			effective_variablen_werte = _merge_variable_values(
				self.variablen_werte, getattr(row, "_iteration_variablen_werte", None)
			)

			doc = frappe.get_doc(
				{
					"doctype": "Serienbrief Dokument",
					"durchlauf": self.name,
					"vorlage": self.vorlage,
					"kategorie": self.kategorie,
					"iteration_doctype": iteration_doctype,
					"objekt": objekt,
					"title": title,
					"date": self.date,
					"html": page_html,
					"variablen_werte": effective_variablen_werte,
				}
			)
			doc.insert(ignore_permissions=True)
			if pdf_bytes:
				file_url = self._store_document_pdf(doc, pdf_bytes)
				doc.db_set("generated_pdf_file", file_url, update_modified=False)
			if submit and int(getattr(doc, "docstatus", 0) or 0) == 0:
				try:
					doc.submit()
				except Exception:
					# Falls ein System/Role kein submit darf: trotzdem als Historie speichern.
					pass
			created.append(doc.name)

		if not created:
			frappe.throw(_("Kein Serienbrief Dokument erzeugt. Bitte Vorlage/Iterationen prüfen."))

		return created

	def _build_merged_pdf(self, dokumente: list[str], print_format: str | None = None) -> bytes:
		if not dokumente:
			frappe.throw(_("Keine Serienbrief Dokumente zum Drucken."))

		format_name = cstr(print_format or "Serienbrief Dokument").strip() or "Serienbrief Dokument"
		use_print_format = frappe.db.exists("Print Format", format_name)

		merger = PdfMerger()
		try:
			for docname in dokumente:
				doc = frappe.get_doc("Serienbrief Dokument", docname)
				if use_print_format:
					pdf_bytes = self._render_dokument_with_print_format(doc, format_name)
				elif cstr(getattr(doc, "generated_pdf_file", None) or "").strip():
					pdf_bytes = read_file_url_bytes(doc.generated_pdf_file)
				else:
					pdf_bytes = get_pdf(self._wrap_html(doc.html or ""), options=self._default_pdf_options())

				merger.append(BytesIO(pdf_bytes))

			out = BytesIO()
			merger.write(out)
			return out.getvalue()
		finally:
			try:
				merger.close()
			except Exception:
				pass

	def _render_dokument_with_print_format(self, doc, format_name: str) -> bytes:
		hybrid_pdf = self._render_dokument_hybrid_print_pdf(doc, format_name)
		if hybrid_pdf:
			return hybrid_pdf

		if (
			cstr(getattr(doc, "generated_pdf_file", None) or "").strip()
			and "hv-pdf-inline-fragment" in cstr(getattr(doc, "html", None) or "")
		):
			return read_file_url_bytes(doc.generated_pdf_file)

		return frappe.get_print(
			"Serienbrief Dokument",
			doc.name,
			print_format=format_name,
			as_pdf=True,
			pdf_options=self._default_pdf_options(),
		)

	def _render_dokument_hybrid_print_pdf(self, doc, format_name: str) -> bytes | None:
		html = cstr(getattr(doc, "html", None) or "").strip()
		if not html or "hv-pdf-inline-fragment" not in html:
			return None

		snapshot_url = cstr(getattr(doc, "generated_pdf_file", None) or "").strip()
		if not snapshot_url:
			return None

		page_html_list = self._split_preview_pages_from_document_html(html)
		if not page_html_list:
			return None

		try:
			snapshot_reader = PdfReader(BytesIO(read_file_url_bytes(snapshot_url)))
		except Exception:
			return None

		total_snapshot_pages = len(snapshot_reader.pages or [])
		if total_snapshot_pages <= 0:
			return None

		page_cursor = 0
		chunks: list[bytes] = []
		base_doc = doc.as_dict()

		for page_html in page_html_list:
			if "hv-pdf-inline-fragment" in page_html:
				pdf_page_count = self._count_inline_pdf_fragment_pages(page_html)
				if page_cursor + pdf_page_count > total_snapshot_pages:
					return None
				chunks.append(
					self._extract_pdf_pages_from_reader(
						snapshot_reader,
						start_index=page_cursor,
						page_count=pdf_page_count,
					)
				)
				page_cursor += pdf_page_count
				continue

			if page_cursor >= total_snapshot_pages:
				return None

			page_doc_data = dict(base_doc)
			page_doc_data["html"] = self._wrap_html_fragment(f'<div class="serienbrief-page">{page_html}</div>')
			page_doc = frappe.get_doc(page_doc_data)
			chunks.append(
				frappe.get_print(
					"Serienbrief Dokument",
					doc.name,
					print_format=format_name,
					as_pdf=True,
					doc=page_doc,
					pdf_options=self._default_pdf_options(),
				)
			)
			page_cursor += 1

		if not chunks:
			return None
		if page_cursor != total_snapshot_pages:
			return None

		return self._merge_pdf_chunks(chunks)

	def _split_preview_pages_from_document_html(self, html: str) -> list[str]:
		source = cstr(html or "").strip()
		if not source:
			return []

		try:
			soup = BeautifulSoup(source, "html.parser")
			pages = []
			for node in soup.select(".serienbrief-root > .serienbrief-page"):
				page_inner = "".join(str(child) for child in node.contents).strip()
				if page_inner:
					pages.append(page_inner)
			if pages:
				return pages
		except Exception:
			pass

		return [source]

	def _count_inline_pdf_fragment_pages(self, page_html: str) -> int:
		try:
			soup = BeautifulSoup(cstr(page_html or ""), "html.parser")
			# Each .hv-pdf-page-image div corresponds to exactly one PDF page.
			pages = soup.select(".hv-pdf-inline-fragment .hv-pdf-page-image")
			if pages:
				return len(pages)
		except Exception:
			pass
		return 1

	def _extract_pdf_pages_from_reader(
		self,
		reader: PdfReader,
		start_index: int,
		page_count: int,
	) -> bytes:
		writer = PdfWriter()
		for page_no in range(start_index, start_index + max(0, page_count)):
			writer.add_page(reader.pages[page_no])

		out = BytesIO()
		writer.write(out)
		return out.getvalue()

	def _render_full_html(self) -> str:
		"""Render the Serienbrief for all recipients and return the full HTML."""

		if not self.vorlage:
			frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

		template = frappe.get_cached_doc("Serienbrief Vorlage", self.vorlage)
		iteration_doctype = self.iteration_doctype or template.get("haupt_verteil_objekt")
		if not iteration_doctype:
			frappe.throw(_("Bitte wählen Sie einen Iterations-Doctype."))
		if not self.iteration_doctype:
			self.iteration_doctype = iteration_doctype

		template_requirements = _collect_template_requirements(template, iteration_doctype)
		empfaenger_rows = self._get_empfaenger_rows()

		if not empfaenger_rows:
			frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

		self._validate_required_fields(template_requirements, empfaenger_rows)

		has_blocks = bool(template.get("textbausteine"))
		has_content = bool(_get_template_template_source(template).strip())
		if not has_blocks and not has_content:
			frappe.throw(_("Die gewählte Vorlage enthält keinen Inhalt."))

		pages: list[str] = []
		total = len(empfaenger_rows)
		for idx, row in enumerate(empfaenger_rows, start=1):
			context = self._build_context(
				row,
				idx,
				template_requirements,
				template,
				total=total,
				strict_variables=False,
			)
			segments = self._render_template_content(template, context)
			if not segments:
				frappe.throw(
					_(
						"Die gewählte Vorlage liefert keinen renderbaren Inhalt. "
						"Bitte prüfen Sie die Textbausteine."
					)
				)
			for page in self._render_segments_preview_pages(segments):
				pages.append(f'<div class="serienbrief-page">{page}</div>')

		return self._wrap_html("\n".join(pages))

	def _store_document_pdf(self, dokument_doc, content: bytes) -> str:
		safe_title = _scrub_value(dokument_doc.title or dokument_doc.name or "serienbrief-dokument")
		filename = f"{safe_title}-{dokument_doc.name}.pdf"
		file_path = frappe.get_site_path("public", "files", filename)
		os.makedirs(os.path.dirname(file_path), exist_ok=True)
		with open(file_path, "wb") as target:
			target.write(content)

		file_url = f"/files/{filename}"
		existing_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Serienbrief Dokument",
				"attached_to_name": dokument_doc.name,
				"file_url": file_url,
			},
			pluck="name",
		)
		for file_name in existing_files:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Serienbrief Dokument",
				"attached_to_name": dokument_doc.name,
			}
		).insert(ignore_permissions=True)

		return file_url

	def before_validate(self):
		if not getattr(self, "iteration_doctype", None):
			return

		for row in getattr(self, "iteration_objekte", []) or []:
			if not getattr(row, "iteration_doctype", None):
				row.iteration_doctype = self.iteration_doctype

	def _build_context(
		self,
		row,
		index: int,
		requirements: Dict[str, Any] | None = None,
		template=None,
		total: int | None = None,
		strict_variables: bool = True,
	) -> Dict[str, Any]:
		requirements = requirements or {}
		required_fields = requirements.get("required_fields") or []
		auto_fields = requirements.get("auto_fields") or []
		letter_date = self.date or today()

		iteration_doc = getattr(row, "_iteration_doc", None)
		if not getattr(row, "wohnung", None) and getattr(iteration_doc, "doctype", "") == "Wohnung":
			row.wohnung = iteration_doc.name

		wohnungs_doc = self._load_doc("Wohnung", row.wohnung)
		immobilie_doc = self._load_doc("Immobilie", getattr(wohnungs_doc, "immobilie", None))

		mieter_doc = self._load_mieter(row)
		mieter_address = self._extract_address(self._get_mieter_doctype(), row.mieter)
		immobilie_address = self._extract_immobilie_address(immobilie_doc)

		# Mieter wohnt in der gemieteten Wohnung — wenn keine eigene Adresse am
		# Customer/Mieter hinterlegt ist, ist die Wohnungs-(Immobilien-)Adresse die
		# Postanschrift. Dadurch funktioniert der Briefkopf für Mahnungen und alles
		# andere ohne Pflege einer separaten Address-Verknüpfung am Customer.
		if not mieter_address and immobilie_address:
			mieter_address = immobilie_address

		mieter_name = row.anzeigename or self._guess_person_name(mieter_doc)
		wohnung_bezeichnung = ""
		if wohnungs_doc:
			wohnung_bezeichnung = (
				getattr(wohnungs_doc, "name__lage_in_der_immobilie", None) or wohnungs_doc.name or ""
			)

		immobilie_bezeichnung = ""
		if immobilie_doc:
			immobilie_bezeichnung = (
				immobilie_address.get("title")
				or immobilie_address.get("street")
				or cstr(getattr(immobilie_doc, "adresse", None) or "")
				or immobilie_doc.name
				or ""
			)

		empfaenger_data = row.as_dict() if hasattr(row, "as_dict") else {}

		context = frappe._dict(
			serienbrief_doc=self,
			serienbrief=self,
			serienbrief_titel=self.title,
			datum=format_date(letter_date),
			datum_iso=letter_date,
			empfaenger=row,
			empfaenger_data=empfaenger_data,
			empfaenger_index=index,
			empfaenger_anzeigename=row.anzeigename,
			empfaenger_count=total if total is not None else 0,
			wohnung=wohnungs_doc,
			wohnung_doc=wohnungs_doc,
			wohnung_bezeichnung=wohnung_bezeichnung,
			immobilie=immobilie_doc,
			immobilie_doc=immobilie_doc,
			immobilie_bezeichnung=immobilie_bezeichnung,
			mieter=mieter_doc,
			mieter_doc=mieter_doc,
			mieter_name=mieter_name or "",
			mieter_strasse=mieter_address.get("street", ""),
			mieter_plz=mieter_address.get("zip", ""),
			mieter_ort=mieter_address.get("city", ""),
			mieter_plz_ort=mieter_address.get("plz_ort", ""),
			mieter_adresse=mieter_address.get("display", ""),
			immobilie_strasse=immobilie_address.get("street", ""),
			immobilie_plz=immobilie_address.get("zip", ""),
			immobilie_ort=immobilie_address.get("city", ""),
			immobilie_plz_ort=immobilie_address.get("plz_ort", ""),
			immobilie_adresse=immobilie_address.get("display", ""),
			iteration_objekt=iteration_doc,
			iteration_doc=iteration_doc,
		)

		# Convenience alias: allow templates to access the iteration doc via its scrubbed DocType name
		# (e.g. `betriebskostenabrechnung_mieter`) without requiring an explicit reference entry.
		if iteration_doc and getattr(iteration_doc, "doctype", None):
			iteration_key = frappe.scrub(iteration_doc.doctype)
			if iteration_key and iteration_key not in context:
				context[iteration_key] = iteration_doc
			iteration_doc_key = f"{iteration_key}_doc"
			if iteration_key and iteration_doc_key not in context:
				context[iteration_doc_key] = iteration_doc

		self._append_reference_context(context, required_fields, row)
		self._append_auto_reference_context(context, auto_fields, row, requirements)
		if template:
			self._apply_template_variables(context, template)
			self._apply_serienbrief_template_variables(context, template, row)
			if strict_variables:
				self._verify_template_variables_resolved(context, template)
		return context

	def _append_reference_context(
		self,
		context: Dict[str, Any],
		required_fields: List[Dict[str, Any]] | None,
		row,
	) -> None:
		if not required_fields:
			return

		for requirement in required_fields:
			context_key = requirement.get("fieldname")
			if not context_key or context_key in context:
				continue

			row_fieldname = requirement.get("row_fieldname") or context_key
			link_value = getattr(row, row_fieldname, None)
			if not link_value:
				continue

			ref_doctype = requirement.get("doctype")
			doc = self._load_doc(ref_doctype, link_value)
			if doc:
				context[context_key] = doc
				if not requirement.get("is_list"):
					context[f"{context_key}_doc"] = doc

	def _append_auto_reference_context(
		self,
		context: Dict[str, Any],
		auto_fields: List[Dict[str, Any]] | None,
		row,
		requirements: Dict[str, Any] | None = None,
	) -> None:
		if not auto_fields:
			return

		for requirement in auto_fields:
			context_key = requirement.get("fieldname")
			if not context_key or context_key in context:
				continue

			value = self._resolve_auto_reference(
				requirement,
				row,
				requirements,
				context=context,
				as_list=bool(requirement.get("is_list")),
			)
			if value:
				context[context_key] = value
				if not requirement.get("is_list") and getattr(value, "doctype", None):
					context[f"{context_key}_doc"] = value

	def _render_template_content(self, template, context: Dict[str, Any]) -> list[Dict[str, Any]]:
		"""Render die Vorlage in Segmenten: html und pdf."""

		standard_text = _get_template_template_source(template).strip()
		content_position = cstr(getattr(template, "content_position", "")).strip() or "Nach Bausteinen"
		inline_mode = bool(
			standard_text and ("baustein(" in standard_text or "textbaustein(" in standard_text)
		)
		inline_pdf_segments: dict[str, Dict[str, Any]] = {}
		inline_re = re.compile(r"__HV_PDF_BLOCK_([A-Za-z0-9_\\-]+)__")

		def _render_inline_textbaustein(block_name: str | None = None) -> Markup:
			name = cstr(block_name).strip()
			if not name:
				return Markup("")

			try:
				block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", name)
			except frappe.DoesNotExistError:
				return Markup("")

			block_context = frappe._dict(context)
			block_row = next(
				(
					row
					for row in (template.get("textbausteine") or [])
					if cstr(getattr(row, "baustein", "")).strip() == block_doc.name
				),
				None,
			)
			if block_row:
				self._apply_block_variables(block_context, block_doc, block_row)

			segment = self._render_block_segment(block_doc, block_context)
			if not segment:
				return Markup("")
			if segment.get("type") == "html":
				return Markup(segment.get("html") or "")

			token = f"__HV_PDF_BLOCK_{uuid.uuid4().hex}__"
			inline_pdf_segments[token] = segment
			return Markup(token)

		context["baustein"] = _render_inline_textbaustein
		context["textbaustein"] = _render_inline_textbaustein

		segments: list[Dict[str, Any]] = []
		if standard_text:
			rendered_standard = _render_serienbrief_template(standard_text, context)
			if inline_mode:
				last = 0
				for match in inline_re.finditer(rendered_standard):
					before = rendered_standard[last : match.start()]
					if before.strip():
						segments.append(
							{
								"type": "html",
								"html": f'<div class="serienbrief-block serienbrief-content">{before}</div>',
							}
						)
					token = match.group(0)
					pdf_segment = inline_pdf_segments.get(token)
					if pdf_segment:
						segments.append(pdf_segment)
					last = match.end()
				after = rendered_standard[last:]
				if after.strip():
					segments.append(
						{
							"type": "html",
							"html": f'<div class="serienbrief-block serienbrief-content">{after}</div>',
						}
					)
			else:
				segments.append(
					{
						"type": "html",
						"html": f'<div class="serienbrief-block serienbrief-content">{rendered_standard}</div>',
					}
				)

		if inline_mode:
			return segments

		block_segments: list[Dict[str, Any]] = []
		for block_row in template.get("textbausteine") or []:
			if not getattr(block_row, "baustein", None):
				continue

			try:
				block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_row.baustein)
			except frappe.DoesNotExistError:
				frappe.throw(_("Der Textbaustein {0} existiert nicht mehr.").format(block_row.baustein))

			block_context = frappe._dict(context)
			self._apply_block_variables(block_context, block_doc, block_row)
			segment = self._render_block_segment(block_doc, block_context)
			if not segment:
				continue
			block_segments.append(segment)

		if content_position == "Vor Bausteinen":
			return segments + block_segments
		return block_segments + segments

	def _render_segments_preview_html(self, segments: list[Dict[str, Any]]) -> str:
		html_parts: list[str] = []
		for segment in segments or []:
			rendered = self._render_preview_segment_html(segment)
			if rendered:
				html_parts.append(rendered)
		return "\n".join(html_parts)

	def _render_segments_preview_pages(self, segments: list[Dict[str, Any]]) -> list[str]:
		pages: list[str] = []
		html_buffer: list[str] = []

		def flush_html_buffer():
			if not html_buffer:
				return
			joined = "\n".join(html_buffer).strip()
			html_buffer.clear()
			if joined:
				pages.append(joined)

		for segment in segments or []:
			if segment.get("type") == "html":
				value = cstr(segment.get("html") or "").strip()
				if value:
					html_buffer.append(value)
				continue

			flush_html_buffer()
			rendered = self._render_preview_segment_html(segment)
			if rendered:
				pages.append(rendered)

		flush_html_buffer()
		return pages

	def _render_preview_segment_html(self, segment: Dict[str, Any]) -> str:
		if segment.get("type") == "html":
			return cstr(segment.get("html") or "").strip()

		inline_html = cstr(segment.get("preview_html") or "").strip()
		if inline_html:
			return inline_html

		title = cstr(segment.get("title") or segment.get("block") or _("PDF-Formular")).strip()
		pages = cstr(segment.get("pages_label") or "").strip()
		page_hint = f" ({pages})" if pages else ""
		return (
			f'<div class="serienbrief-pdf-placeholder" data-block="{cstr(segment.get("block") or "")}">'
			f'{_("PDF-Formular")}: {frappe.utils.escape_html(title)}{frappe.utils.escape_html(page_hint)}</div>'
		)

	def _render_segments_pdf_bytes(self, segments: list[Dict[str, Any]]) -> bytes:
		pdf_chunks: list[bytes] = []
		html_buffer: list[str] = []

		def flush_html_buffer():
			if not html_buffer:
				return
			joined = "\n".join(html_buffer).strip()
			html_buffer.clear()
			if not joined:
				return
			page_html = self._wrap_html(f'<div class="serienbrief-page">{joined}</div>')
			pdf_chunks.append(get_pdf(page_html, options=self._default_pdf_options()))

		for segment in segments or []:
			if segment.get("type") == "html":
				value = cstr(segment.get("html") or "").strip()
				if value:
					html_buffer.append(value)
				continue

			pdf_bytes = segment.get("pdf_bytes")
			if not pdf_bytes:
				continue
			flush_html_buffer()
			pdf_chunks.append(pdf_bytes)

		flush_html_buffer()
		return self._merge_pdf_chunks(pdf_chunks)

	def _merge_pdf_chunks(self, chunks: list[bytes]) -> bytes:
		if not chunks:
			return b""
		merger = PdfMerger()
		try:
			for chunk in chunks:
				if not chunk:
					continue
				merger.append(BytesIO(chunk))
			out = BytesIO()
			merger.write(out)
			return out.getvalue()
		finally:
			try:
				merger.close()
			except Exception:
				pass

	def _render_block_segment(self, block_doc, context: Dict[str, Any]) -> Dict[str, Any] | None:
		content_type = cstr(getattr(block_doc, "content_type", None) or "").strip() or "Textbaustein (Rich Text)"
		if content_type == "PDF Formular":
			pdf_bytes = render_pdf_form_block(block_doc, context, _resolve_value_path)
			preview_html = render_pdf_bytes_as_html_fragment(pdf_bytes)
			return {
				"type": "pdf",
				"block": cstr(getattr(block_doc, "name", None) or ""),
				"title": cstr(getattr(block_doc, "title", None) or getattr(block_doc, "name", None) or ""),
				"pages_label": cstr(getattr(block_doc, "pdf_pages", None) or _("alle Seiten")),
				"pdf_bytes": pdf_bytes,
				"preview_html": preview_html,
			}

		rendered = self._render_block_html(block_doc, context)
		if not rendered:
			return None
		return {
			"type": "html",
			"block": cstr(getattr(block_doc, "name", None) or ""),
			"title": cstr(getattr(block_doc, "title", None) or getattr(block_doc, "name", None) or ""),
			"html": f'<div class="serienbrief-block" data-block="{cstr(block_doc.name)}">{rendered}</div>',
		}

	def _render_block_html(self, block_doc, context: Dict[str, Any]) -> str:
		template_source = sanitize_richtext_jinja_source(self._get_block_template_source(block_doc).strip())
		if not template_source:
			return ""

		try:
			return _render_serienbrief_template(template_source, context)
		except Exception as exc:
			block_title = getattr(block_doc, "title", None) or getattr(block_doc, "name", None) or _("Textbaustein")
			message = _("Fehler beim Rendern des Textbausteins {0}: {1}").format(
				frappe.bold(block_title),
				frappe.utils.escape_html(str(exc)),
			)
			if "not iterable" in str(exc):
				message += "<br><br>" + _(
					"Hinweis: Im Jinja-Template wird vermutlich über ein einzelnes Dokument iteriert "
					"(z.B. `{% for x in kontakt %}`), obwohl `kontakt` nur ein einzelnes Doc ist."
				)
			frappe.throw(message)

	def _get_block_template_source(self, block_doc) -> str:
		content_type = (block_doc.content_type or "").strip() or "Textbaustein (Rich Text)"
		if content_type == "PDF Formular":
			return ""
		if content_type == "HTML + Jinja":
			parts = [
				block_doc.jinja_content or "",
				block_doc.html_content or "",
			]
			return "\n".join([p for p in parts if p and p.strip()])

		return block_doc.text_content or ""

	def _apply_block_variables(self, context: Dict[str, Any], block_doc, block_row) -> None:
		variable_defs = block_doc.get("variables") or []
		if not variable_defs:
			return

		block_title = block_doc.title or block_doc.name
		mapping = _parse_variable_values(getattr(block_row, "variablen_werte", None))
		missing: list[str] = []

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type != "Text":
				continue

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			entry = mapping.get(key) or {}
			path = cstr(entry.get("path") or "").strip()
			value = entry.get("value")

			resolved = None
			if path:
				resolved = _resolve_value_path(path, context)
				if resolved is None:
					frappe.throw(
						_("Pfad {0} für Variable {1} im Baustein {2} konnte nicht aufgelöst werden.").format(
							frappe.bold(path), frappe.bold(raw_key or key), frappe.bold(block_title)
						)
					)
			if resolved is None and value not in (None, ""):
				resolved = value

			if resolved is None:
				if context.get(key) in (None, ""):
					label = getattr(variable, "label", None) or raw_key or key
					missing.append(f"{label} (<code>{{{{ {key} }}}}</code>)")
				continue

			context[key] = resolved

			if "block_variables" not in context:
				context["block_variables"] = {}
			context["block_variables"][key] = resolved

		if missing:
			frappe.throw(
				_(
					"Im Baustein {0} fehlen Werte für folgende Variablen:<br>{1}<br><br>"
					"Hinweis: Im Vorlagen-Formular unter „Feldpfade & Variablen“ den Baustein auswählen "
					"und pro Variable einen Festwert oder Pfad hinterlegen, oder eine gleichnamige "
					"Vorlagen-Variable mit Wert setzen."
				).format(frappe.bold(block_title), "<br>".join(missing))
			)

	def _apply_template_variables(self, context: Dict[str, Any], template) -> None:
		variable_defs = template.get("variables") or []
		if not variable_defs:
			return

		template_title = template.title or template.name
		mapping = _parse_variable_values(getattr(template, "variablen_werte", None))

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type not in {"String", "Zahl", "Bool", "Datum", "Text"}:
				continue

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			entry = mapping.get(key) or {}
			path = cstr(entry.get("path") or "").strip()
			value = entry.get("value")

			resolved = None
			if path:
				resolved = _resolve_value_path(path, context)
				if resolved is None:
					frappe.throw(
						_("Pfad {0} für Variable {1} in der Vorlage {2} konnte nicht aufgelöst werden.").format(
							frappe.bold(path), frappe.bold(raw_key or key), frappe.bold(template_title)
						)
					)
			if resolved is None and value not in (None, ""):
				resolved = value

			if resolved is None:
				# Variable stays unresolved here; the durchlauf override may still fill it.
				# _verify_template_variables_resolved raises afterwards if it's still missing.
				continue

			context[key] = resolved
			if "template_variables" not in context:
				context["template_variables"] = {}
			context["template_variables"][key] = resolved

	def _apply_serienbrief_template_variables(
		self, context: Dict[str, Any], template, row=None
	) -> None:
		variable_defs = template.get("variables") or []
		if not variable_defs:
			return

		durchlauf_mapping = _parse_variable_values(getattr(self, "variablen_werte", None))
		row_mapping = _parse_variable_values(getattr(row, "_iteration_variablen_werte", None))
		if not durchlauf_mapping and not row_mapping:
			return

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type not in {"String", "Zahl", "Bool", "Datum", "Text"}:
				continue

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			# Row-Override hat Vorrang vor dem Durchlauf-Default.
			entry = row_mapping.get(key) or durchlauf_mapping.get(key) or {}
			path = cstr(entry.get("path") or "").strip()
			value = entry.get("value")

			resolved = None
			if path:
				resolved = _resolve_value_path(path, context)
				if resolved is None:
					frappe.throw(
						_("Pfad {0} für Variable {1} im Serienbrief konnte nicht aufgelöst werden.").format(
							frappe.bold(path), frappe.bold(raw_key or key)
						)
					)
			if resolved is None and value not in (None, ""):
				resolved = value

			if resolved is None:
				continue

			context[key] = resolved
			if "template_variables" not in context:
				context["template_variables"] = {}
			context["template_variables"][key] = resolved

	def _verify_template_variables_resolved(self, context: Dict[str, Any], template) -> None:
		variable_defs = template.get("variables") or []
		if not variable_defs:
			return

		template_title = template.title or template.name
		missing: list[str] = []

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type not in {"String", "Zahl", "Bool", "Datum", "Text"}:
				continue

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			if context.get(key) not in (None, ""):
				continue

			label = getattr(variable, "label", None) or raw_key or key
			missing.append(f"{label} (<code>{{{{ {key} }}}}</code>)")

		if missing:
			frappe.throw(
				_(
					"In der Vorlage {0} fehlen Werte für folgende Variablen:<br>{1}<br><br>"
					"Hinweis: Im Vorlagen-Formular unter „Feldpfade & Variablen“ → „Vorlage“ pro "
					"Variable einen Festwert oder Pfad hinterlegen, oder im Serienbrief Durchlauf "
					"unter „Variablen“ einen Wert setzen."
				).format(frappe.bold(template_title), "<br>".join(missing))
			)

	def _default_css(self) -> str:
		custom_css = """
			@page {
				size: A4;
				margin: 20mm 20mm 20mm 25mm;
			}
			body,
			.serienbrief-root,
			.print-format,
			.print-format .serienbrief-root {
				font-family: "Arial", "Helvetica", sans-serif;
				color: #222;
				font-size: 11pt !important;
				line-height: 1.4;
			}
			/* Serienbrief: Briefkopf-Layout (Inhalt liefert nur Klassen; Layout kommt aus CSS) */
			.sb-letterhead {
				margin-top: 0.7cm;
			}
			.sb-address-window {
				float: left;
				width: 60%;
				padding-top: 3.2cm;
				font-size: 10pt;
				box-sizing: border-box;
			}
			.sb-return-address {
				font-size: 7pt;
				text-decoration: underline;
				margin-bottom: 0.15cm;
			}
			.sb-sender {
				float: right;
				width: 40%;
				text-align: right;
				font-size: 9pt;
				box-sizing: border-box;
			}
			.sb-office-hours {
				font-size: 7.5pt;
				margin-top: 0.15cm;
			}
			.sb-letterhead:after {
				content: "";
				display: block;
				clear: both;
			}
			.sb-date {
				margin-top: 0.5cm;
				text-align: right;
			}
			.print-format {
				margin: 0 !important;
				padding: 0 !important;
				width: 100% !important;
				max-width: 100% !important;
				box-sizing: border-box;
			}
			.serienbrief-page {
				page-break-after: always;
				padding: 0;
			}
			.serienbrief-page:last-child {
				page-break-after: auto;
			}
			.serienbrief-page p {
				margin: 0 0 8px 0;
				line-height: 1.4;
			}
			.serienbrief-block {
				margin-bottom: 12px;
			}
			.serienbrief-block:last-child {
				margin-bottom: 0;
			}
			.serienbrief-pdf-placeholder {
				border: 1px dashed #999;
				background: #f6f6f6;
				color: #444;
				padding: 8px 10px;
				margin: 10px 0;
				font-size: 9.5pt;
			}
		"""
		return custom_css

	def _default_pdf_options(self) -> dict[str, str]:
		return {
			"page-size": "A4",
			"margin-top": "20mm",
			"margin-right": "20mm",
			"margin-bottom": "20mm",
			"margin-left": "25mm",
		}

	def _wrap_html_fragment(self, body_html: str) -> str:
		return f'<div class="serienbrief-root">{body_html}</div>'

	def _wrap_html(self, body_html: str) -> str:
		return f"""<!DOCTYPE html>
<html>
	<head>
		<meta charset="utf-8">
		<style>{self._default_css()}</style>
	</head>
	<body>
		{body_html}
	</body>
</html>"""

	def _store_pdf(self, content: bytes) -> str:
		safe_title = _scrub_value(self.title or "serienbrief")
		filename = f"{safe_title}-{self.name}.pdf"
		file_path = frappe.get_site_path("public", "files", filename)
		os.makedirs(os.path.dirname(file_path), exist_ok=True)

		with open(file_path, "wb") as target:
			target.write(content)

		file_url = f"/files/{filename}"
		existing_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
				"file_url": file_url,
			},
			pluck="name",
		)
		for file_name in existing_files:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
			}
		).insert(ignore_permissions=True)

		return file_url

	def _store_html(self, content: str) -> str:
		safe_title = _scrub_value(self.title or "serienbrief")
		filename = f"{safe_title}-{self.name}.html"
		file_path = frappe.get_site_path("public", "files", filename)
		os.makedirs(os.path.dirname(file_path), exist_ok=True)

		with open(file_path, "w", encoding="utf-8") as target:
			target.write(content)

		file_url = f"/files/{filename}"
		existing_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
				"file_url": file_url,
			},
			pluck="name",
		)
		for file_name in existing_files:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
			}
		).insert(ignore_permissions=True)

		return file_url

	def _get_empfaenger_rows(self) -> list[Any]:
		rows: list[Any] = []
		for iteration_row in getattr(self, "iteration_objekte", []) or []:
			row = self._build_empfaenger_row_from_iteration(iteration_row)
			if row:
				rows.append(row)

		return rows

	def _build_empfaenger_row_from_iteration(self, iteration_row):
		iteration_doctype = getattr(iteration_row, "iteration_doctype", None) or self.iteration_doctype
		if not iteration_doctype or not getattr(iteration_row, "objekt", None):
			return None

		iteration_doc = self._load_doc(iteration_doctype, iteration_row.objekt)
		if not iteration_doc:
			return None

		iteration_meta = frappe.get_meta(iteration_doctype)
		link_fields = [df for df in iteration_meta.fields if df.fieldtype == "Link" and df.options]
		link_map = self._get_iteration_link_field_map(iteration_doctype)

		row_data: dict[str, Any] = {
			"iteration_doctype": iteration_doctype,
			"iteration_objekt": iteration_doc.name,
		}

		target_field = link_map.get(iteration_doctype)
		if target_field:
			row_data[target_field] = iteration_doc.name

		# Fallback: wenn Iterations-Objekt direkt eine Wohnung ist
		if iteration_doctype == "Wohnung" and not row_data.get("wohnung"):
			row_data["wohnung"] = iteration_doc.name

		for df in link_fields:
			value = getattr(iteration_doc, df.fieldname, None)
			if value:
				row_data.setdefault(df.fieldname, value)

		# Mietvertrag-Name merken, damit wir die Mieter-Tabelle (Vertragspartner →
		# Contact) für den Anzeigenamen heranziehen können.
		mietvertrag_name: str | None = None
		if iteration_doctype == "Mietvertrag":
			mietvertrag_name = iteration_doc.name

		# When the iteration doc only knows about a Customer (e.g. Dunning) but
		# not the Mieter/Wohnung directly, derive both via the active Mietvertrag.
		# Without this, mieter/immobilie context vars stay empty and any letterhead
		# block that wants to show the recipient address renders blank.
		if not row_data.get("mieter") or not row_data.get("wohnung"):
			customer_name = (
				getattr(iteration_doc, "kunde", None)
				or getattr(iteration_doc, "customer", None)
				or getattr(iteration_doc, "debitor", None)
			)
			if customer_name and frappe.db.exists("DocType", "Mietvertrag"):
				try:
					mv = frappe.db.sql(
						"""
						SELECT name, wohnung FROM `tabMietvertrag`
						WHERE kunde = %(kunde)s
						  AND (von IS NULL OR von <= CURDATE())
						  AND (bis IS NULL OR bis >= CURDATE())
						ORDER BY COALESCE(von, '1900-01-01') DESC
						LIMIT 1
						""",
						{"kunde": customer_name},
						as_dict=True,
					)
				except Exception:
					mv = []
				if mv:
					row_data.setdefault("wohnung", mv[0].get("wohnung"))
					if not mietvertrag_name:
						mietvertrag_name = mv[0].get("name")
				row_data.setdefault("mieter", customer_name)

		# Bevorzugter Anzeigename: aus der Mieter-Tabelle des Mietvertrags
		# (Vertragspartner → Contact). Nur wenn die leer ist, fällt es auf die
		# Doc-Felder bzw. den technischen Mietvertrag-Namen zurück.
		display_name = self._resolve_mieter_names_from_vertrag(mietvertrag_name)
		if not display_name:
			display_name = (
				getattr(iteration_doc, "anzeigename", None)
				or getattr(iteration_doc, "title", None)
				or getattr(iteration_doc, "customer_name", None)
				or getattr(iteration_doc, "kunden_name", None)
				or getattr(iteration_doc, "name", None)
			)
		if display_name:
			row_data["anzeigename"] = display_name

		row = _IterationEmpfaengerRow(row_data)
		row._iteration_doc = iteration_doc
		row._iteration_rowname = getattr(iteration_row, "name", None)
		row._iteration_variablen_werte = getattr(iteration_row, "variablen_werte", None)

		return row

	def _validate_required_fields(self, requirements: Dict[str, Any], empfaenger_rows: list[Any]) -> None:
		missing_fields = requirements.get("missing_fields") or []
		if missing_fields:
			lines = [
				self._format_requirement_debug(req, include_path_source=True) for req in missing_fields
			]
			frappe.throw(
				_(
					"Die Vorlage benötigt zusätzliche Felder im Iterations-Doctype {0}:<br>{1}<br><br>"
					"Hinweis: Entweder ein passendes Feld im Iterations-Doctype ergänzen (z.B. Link/Child-Tabelle), "
					"oder im Template/Block einen Pfad (Pfad-Zuordnung/Standardpfade) hinterlegen."
				).format(frappe.bold(self.iteration_doctype or ""), "<br>".join(lines))
			)

		required_fields = requirements.get("required_fields") or []
		auto_fields = requirements.get("auto_fields") or []

		missing_rows: list[tuple[int, list[Dict[str, Any]]]] = []
		for idx, row in enumerate(empfaenger_rows, start=1):
			row_missing = [
				req
				for req in required_fields
				if not getattr(row, (req.get("row_fieldname") or req.get("fieldname") or ""), None)
			]
			if row_missing:
				missing_rows.append((idx, row_missing))

		if missing_rows:
			lines = []
			for row_index, row_requirements in missing_rows:
				labels = ", ".join(self._format_requirement_label(req) for req in row_requirements)
				lines.append(f"{row_index}. {labels}")

			frappe.throw(
				_(
					"Bitte ergänzen Sie die fehlenden Felder für die Iterations-Objekte:<br>{0}"
				).format("<br>".join(lines))
			)

		if auto_fields:
			auto_missing: list[tuple[int, list[Dict[str, Any]]]] = []
			for idx, row in enumerate(empfaenger_rows, start=1):
				row_missing = [
					req
					for req in auto_fields
					if not self._resolve_auto_reference(
						req, row, requirements, as_list=bool(req.get("is_list"))
					)
				]
				if row_missing:
					auto_missing.append((idx, row_missing))

			if auto_missing:
				lines = []
				for row_index, row_requirements in auto_missing:
					labels = ", ".join(self._format_requirement_label(req) for req in row_requirements)
					lines.append(f"{row_index}. {labels}")

				frappe.throw(
					_("Automatische Quellen konnten für einige Iterations-Objekte nicht ermittelt werden:<br>{0}").format(
						"<br>".join(lines)
					)
				)

	def _format_requirement_label(self, requirement: Dict[str, Any]) -> str:
		label = cstr(requirement.get("label") or requirement.get("fieldname") or "")
		parts: list[str] = []

		source = cstr(requirement.get("source") or "")
		if source:
			parts.append(source)

		path = requirement.get("path")
		if path:
			parts.append(cstr(path))

		if parts:
			return f"{label} ({', '.join(parts)})"
		return label

	def _format_requirement_debug(self, requirement: Dict[str, Any], include_path_source: bool = False) -> str:
		label = cstr(requirement.get("label") or requirement.get("fieldname") or "")
		context_key = cstr(requirement.get("fieldname") or "").strip()
		row_fieldname = cstr(requirement.get("row_fieldname") or requirement.get("fieldname") or "").strip()
		target_doctype = cstr(requirement.get("doctype") or "").strip()
		source = cstr(requirement.get("source") or "").strip()
		path = cstr(requirement.get("path") or "").strip()
		is_list = bool(requirement.get("is_list"))
		path_source = cstr(requirement.get("path_source") or "").strip()

		parts: list[str] = []
		if source:
			parts.append(_("Quelle: {0}").format(source))
		if context_key:
			parts.append(_("Kontextvariable: {0}").format(frappe.bold(context_key)))
		if row_fieldname and row_fieldname != context_key:
			parts.append(_("Feld im Iterations-Doctype: {0}").format(frappe.bold(row_fieldname)))
		if target_doctype:
			parts.append(_("Doctype: {0}").format(frappe.bold(target_doctype)))
		if is_list:
			parts.append(_("Typ: Liste"))
		if path:
			parts.append(_("Pfad: {0}").format(frappe.bold(path)))
		if include_path_source and path_source:
			parts.append(_("Pfad-Quelle: {0}").format(path_source))

		if parts:
			return f"{label} ({' · '.join(parts)})"
		return label

	def _get_iteration_link_field_map(self, iteration_doctype: str | None = None) -> Dict[str, str]:
		if iteration_doctype and hasattr(self, "_iteration_link_field_map_cache"):
			cache = getattr(self, "_iteration_link_field_map_cache")  # type: ignore[attr-defined]
			if cache.get("_doctype") == iteration_doctype:
				return cache.get("mapping", {})

		if not iteration_doctype:
			iteration_doctype = self.iteration_doctype
		if not iteration_doctype:
			return {}

		meta = frappe.get_meta(iteration_doctype)
		mapping = {cstr(df.options): df.fieldname for df in meta.fields if df.fieldtype == "Link" and df.options}
		self._iteration_link_field_map_cache = {"_doctype": iteration_doctype, "mapping": mapping}  # type: ignore[attr-defined]
		return mapping

	def _resolve_auto_reference(
		self,
		reference: Dict[str, Any],
		row,
		requirements: Dict[str, Any] | None,
		context: Dict[str, Any] | None = None,
		as_list: bool = False,
	):
		path = cstr(reference.get("path") or "").strip()
		if not path:
			return None
		if path == "__self__":
			iteration_doc = getattr(row, "_iteration_doc", None) or self._load_doc(
				self.iteration_doctype, getattr(row, "objekt", None)
			)
			if not iteration_doc:
				return None
			return [iteration_doc] if as_list else iteration_doc

		segments = [seg.strip() for seg in path.split(".") if seg.strip()]
		if not segments:
			return None

		context = context or {}
		if not self.iteration_doctype:
			return None

		current_doc = getattr(row, "_iteration_doc", None) or self._load_doc(self.iteration_doctype, getattr(row, "objekt", None))
		current_doctype = self.iteration_doctype
		if not current_doc:
			return None

		def load_meta(doctype: str):
			try:
				return frappe.get_meta(doctype)
			except Exception:
				return None

		def pick_child_row(child_list: list[Any], lookahead: str | None = None):
			if not child_list:
				return None
			# Wenn eine Zahl folgt, wird diese als Index interpretiert
			if lookahead is not None and lookahead.isdigit():
				idx = int(lookahead)
				if 0 <= idx < len(child_list):
					return child_list[idx], True
			# Sonst nimm die erste Zeile mit einem Wert im Lookahead-Feld (falls gesetzt), sonst die erste Zeile
			if lookahead:
				for item in child_list:
					if getattr(item, lookahead, None):
						return item, False
			return child_list[0], False

		def hydrate_child_list(child_list: list[Any], target_doctype: str | None):
			"""Return a list suitable for Jinja templates.

			When `target_doctype` is set, try to resolve Link fields in each child row that
			point to that DocType and expose them directly (e.g. `row.mieter.first_name`).
			"""
			if not as_list:
				return child_list
			if not child_list:
				return []
			target = cstr(target_doctype or "").strip()
			if not target:
				return child_list

			wrapped: list[Any] = []
			for item in child_list:
				try:
					child_doctype = getattr(item, "doctype", None)
					if not child_doctype:
						wrapped.append(item)
						continue
					meta = load_meta(child_doctype)
					if not meta:
						wrapped.append(item)
						continue

					data = item.as_dict() if hasattr(item, "as_dict") else {}
					for df in meta.fields:
						if df.fieldtype != "Link" or not df.options or cstr(df.options) != target:
							continue
						link_value = getattr(item, df.fieldname, None)
						if not link_value:
							continue
						doc = self._load_doc(target, link_value)
						if not doc:
							continue
						data[df.fieldname] = doc
						data[f"{df.fieldname}_doc"] = doc

					wrapped.append(frappe._dict(data))
				except Exception:
					wrapped.append(item)
			return wrapped

		idx = 0
		while idx < len(segments):
			segment = segments[idx]
			meta = load_meta(current_doctype)
			if not meta:
				return None

			df = meta.get_field(segment)
			if not df:
				return None

			if df.fieldtype == "Link" and df.options:
				link_value = getattr(current_doc, segment, None)
				if not link_value:
					return None
				current_doctype = df.options
				current_doc = self._load_doc(current_doctype, link_value)
				if not current_doc:
					return None
				idx += 1
				continue

			if df.fieldtype == "Table" and df.options:
				child_list = getattr(current_doc, segment, None) or []
				if idx == len(segments) - 1:
					if as_list:
						return hydrate_child_list(child_list, reference.get("doctype"))
					# Fallback: wie bisher erste passende Zeile
					child_row, _consumed_numeric = pick_child_row(child_list, None)
					return child_row

				# Spezialfall: Liste soll über eine Child-Tabelle iterieren, der nächste Pfad-Segment ist ein Link
				# zum Ziel-Doctype (z.B. `mieter.mieter` -> Vertragspartner rows mit Link `mieter` auf Contact).
				# Dann gib direkt die Child-Rows zurück, aber mit "hydratisierten" Link-Dokumenten.
				if as_list:
					target = cstr(reference.get("doctype") or "").strip()
					next_seg = segments[idx + 1] if idx + 1 < len(segments) else None
					if target and next_seg:
						child_meta = load_meta(df.options)
						child_df = child_meta.get_field(next_seg) if child_meta else None
						if child_df and child_df.fieldtype == "Link" and cstr(child_df.options) == target:
							return hydrate_child_list(child_list, target)

				lookahead = segments[idx + 1] if idx + 1 < len(segments) else None
				child_row, consumed_numeric = pick_child_row(child_list, lookahead)
				if not child_row:
					return None
				current_doc = child_row
				current_doctype = df.options
				idx += 1
				if consumed_numeric:
					idx += 1
				continue

			return None

		if as_list:
			if current_doc is None:
				return None
			if isinstance(current_doc, list):
				return current_doc
			return [current_doc]

		return current_doc

	def _load_mieter(self, row):
		if not row.mieter:
			return None

		mieter_doctype = self._get_mieter_doctype()
		# `frappe.get_doc` ruft bei DoesNotExist intern `frappe.throw` →
		# `msgprint` auf, was eine Toast-Nachricht in die Response einfügt
		# (auch wenn die Exception danach gefangen wird). Daher Existenz vorher
		# explizit prüfen, damit kein "X Y nicht gefunden"-Popup leakt.
		if not frappe.db.exists(mieter_doctype, row.mieter):
			return None
		try:
			return frappe.get_doc(mieter_doctype, row.mieter)
		except frappe.DoesNotExistError:
			return None

	def _load_doc(self, doctype: str, name: str | None):
		if not name:
			return None
		# Existenz-Check vor get_doc, sonst leakt frappe.throw eine msgprint-
		# Toast in die Response (siehe Kommentar in _load_mieter).
		if not frappe.db.exists(doctype, name):
			return None
		try:
			return frappe.get_doc(doctype, name)
		except frappe.DoesNotExistError:
			return None

	def _load_address_doc(self, link_doctype: str | None, link_name: str | None):
		if not link_doctype or not link_name:
			return None

		address_name = get_default_address(link_doctype, link_name)
		if not address_name:
			return None

		try:
			return frappe.get_doc("Address", address_name)
		except frappe.DoesNotExistError:
			return None

	def _load_immobilie_address_doc(self, immobilie, fallback_from_row=None):
		immobilie_name = getattr(immobilie, "name", None) if immobilie else None
		if not immobilie_name and isinstance(immobilie, str):
			immobilie_name = immobilie

		if not immobilie_name and fallback_from_row:
			wohnung_name = getattr(fallback_from_row, "wohnung", None)
			if wohnung_name:
				wohnung_doc = self._load_doc("Wohnung", wohnung_name)
				immobilie_name = getattr(wohnung_doc, "immobilie", None) if wohnung_doc else None

		if not immobilie_name:
			return None

		try:
			immobilie_doc = (
				immobilie
				if getattr(immobilie, "doctype", None) == "Immobilie"
				else frappe.get_doc("Immobilie", immobilie_name)
			)
		except frappe.DoesNotExistError:
			return None

		address_link = cstr(immobilie_doc.get("adresse")).strip()
		if address_link:
			try:
				return frappe.get_doc("Address", address_link)
			except frappe.DoesNotExistError:
				pass

		address_name = get_default_address("Immobilie", immobilie_doc.name)
		if not address_name:
			return None

		try:
			return frappe.get_doc("Address", address_name)
		except frappe.DoesNotExistError:
			return None

	def _get_mieter_doctype(self) -> str:
		if hasattr(self, "_mieter_doctype_cache"):
			return self._mieter_doctype_cache  # type: ignore[attr-defined]

		target = ""
		if self.iteration_doctype:
			try:
				meta = frappe.get_meta(self.iteration_doctype)
				field = meta.get_field("mieter")
				if field and field.options:
					# Tabellen-Feld (z.B. Mietvertrag.mieter → Vertragspartner) ist
					# NICHT der Doctype, der in row.mieter landet — dort steht der
					# Customer-Docname (siehe row_data.setdefault("mieter", customer_name)
					# in _build_iteration_empfaenger_row). Daher bei Tabellen-Feldern
					# auf den Customer/Mieter-Doctype zurückfallen.
					if field.fieldtype == "Link":
						target = field.options
			except Exception:
				pass

		# Fallback: bei Iteration-Doctypes ohne direktes Link-Feld `mieter`
		# (Mietvertrag, Dunning, Sales Invoice, …) ist der Empfänger der
		# Customer/Debitor — wir bevorzugen das Legacy-DocType "Mieter" wenn
		# installiert, sonst "Customer".
		if not target:
			if frappe.db.exists("DocType", "Mieter"):
				target = "Mieter"
			else:
				target = "Customer"

		self._mieter_doctype_cache = target  # type: ignore[attr-defined]
		return self._mieter_doctype_cache  # type: ignore[attr-defined]

	def _extract_address(self, link_doctype: str | None, link_name: str | None) -> Dict[str, str]:
		if not link_doctype or not link_name:
			return {}

		address_name = get_default_address(link_doctype, link_name)
		if not address_name:
			return {}

		return self._address_dict_from_name(address_name)

	def _extract_immobilie_address(self, immobilie_doc) -> Dict[str, str]:
		if not immobilie_doc:
			return {}

		linked_address = cstr(immobilie_doc.get("adresse")).strip()
		if linked_address:
			address_data = self._address_dict_from_name(linked_address)
			if address_data:
				return address_data

		address_from_link = self._extract_address("Immobilie", immobilie_doc.name)
		if address_from_link:
			return address_from_link

		street = (
			cstr(immobilie_doc.get("adresse__name"))
			or cstr(immobilie_doc.get("stra\u00dfe"))
			or cstr(immobilie_doc.get("strasse"))
		).strip()
		zip_code = cstr(immobilie_doc.get("plz")).strip()
		city = cstr(immobilie_doc.get("ort")).strip()
		plz_ort = self._format_plz_ort(zip_code, city)

		return {
			"street": street,
			"zip": zip_code,
			"city": city,
			"plz_ort": plz_ort,
		}

	def _address_dict_from_name(self, address_name: str | None) -> Dict[str, str]:
		if not address_name:
			return {}
		try:
			address = frappe.get_doc("Address", address_name)
		except frappe.DoesNotExistError:
			return {}

		street = ", ".join(filter(None, [cstr(address.address_line1).strip(), cstr(address.address_line2).strip()]))
		zip_code = cstr(getattr(address, "pincode", None) or getattr(address, "zip", None)).strip()
		city = cstr(address.city).strip()
		plz_ort = self._format_plz_ort(zip_code, city)

		return {
			"street": street,
			"zip": zip_code,
			"city": city,
			"plz_ort": plz_ort,
			"display": "\n".join(filter(None, [street, plz_ort])),
			"title": cstr(address.address_title).strip(),
			"name": cstr(address.name).strip(),
		}

	def _guess_person_name(self, doc) -> str:
		if not doc:
			return ""

		first = cstr(getattr(doc, "first_name", "")).strip()
		last = cstr(getattr(doc, "last_name", "")).strip()
		full = " ".join(filter(None, [first, last]))
		if full:
			return full

		for field in ("customer_name", "full_name", "name1", "vorname", "nachname", "company_name", "subject", "name"):
			value = cstr(getattr(doc, field, "")).strip()
			if value:
				return value

		return cstr(getattr(doc, "title", "")).strip()

	def _resolve_mieter_names_from_vertrag(self, mietvertrag_name: str | None) -> str:
		"""Personen-Anzeigename aus der ``mieter``-Tabelle eines Mietvertrags
		(Vertragspartner → Contact). Ausgezogene Mieter werden ignoriert."""
		if not mietvertrag_name:
			return ""
		try:
			rows = frappe.db.sql(
				"""
				SELECT vp.mieter
				FROM `tabVertragspartner` vp
				WHERE vp.parent = %(mv)s
				  AND vp.parenttype = 'Mietvertrag'
				  AND vp.parentfield = 'mieter'
				  AND COALESCE(vp.rolle, '') != 'Ausgezogen'
				ORDER BY vp.idx
				""",
				{"mv": mietvertrag_name},
				as_dict=True,
			)
		except Exception:
			return ""
		names: list[str] = []
		for row in rows:
			contact_name = cstr(row.get("mieter")).strip()
			if not contact_name:
				continue
			contact_doc = self._load_doc("Contact", contact_name)
			person = self._guess_person_name(contact_doc)
			if person and person not in names:
				names.append(person)
		return " und ".join(names)

	def _format_plz_ort(self, plz: str, ort: str) -> str:
		parts = [plz, ort]
		return " ".join([p for p in parts if p]).strip()

def _scrub_value(value: str) -> str:
	value = (value or "").lower()
	value = re.sub(r"[^a-z0-9]+", "-", value)
	value = value.strip("-")
	return value or "serienbrief"


def _parse_mapping(raw: str | None) -> dict:
	if not raw:
		return {}
	try:
		data = json.loads(raw)
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _parse_variable_values(raw: str | None) -> dict[str, dict[str, Any]]:
	data = _parse_mapping(raw)
	if not isinstance(data, dict):
		return {}

	parsed: dict[str, dict[str, Any]] = {}
	for key, value in data.items():
		if isinstance(value, dict):
			parsed[key] = {"value": value.get("value"), "path": value.get("path")}
		else:
			parsed[key] = {"value": value, "path": None}

	return parsed


def _merge_variable_values(base_raw: str | None, override_raw: str | None) -> str | None:
	base = _parse_variable_values(base_raw)
	override = _parse_variable_values(override_raw)
	if not base and not override:
		return None
	merged: dict[str, dict[str, Any]] = {}
	merged.update(base)
	merged.update(override)
	return json.dumps(merged) if merged else None


def _serialize_overview_value(value: Any, max_items: int = 5) -> dict[str, Any]:
	if value is None:
		return {"display": "", "is_empty": True}

	if isinstance(value, (list, tuple)):
		items = [_serialize_overview_value(item, max_items=max_items) for item in value[:max_items]]
		labels = [item.get("display") or "" for item in items if item.get("display")]
		display = f"{len(value)} " + _("Einträge")
		if labels:
			display = f"{display}: {', '.join(labels)}"
		return {"display": display, "is_list": True, "count": len(value), "items": items}

	if _is_document_like(value):
		doctype = getattr(value, "doctype", None) or (value.get("doctype") if isinstance(value, dict) else "")
		name = getattr(value, "name", None) or (value.get("name") if isinstance(value, dict) else "")
		title = getattr(value, "title", None) or (value.get("title") if isinstance(value, dict) else "")
		if title and name and title != name:
			display = f"{title} ({name})"
		else:
			display = title or name or cstr(value)
		return {
			"display": display,
			"doctype": doctype or "",
			"name": name or "",
			"title": title or "",
		}

	return {"display": cstr(value)}


class _LinkResolvingRow:
	"""Proxy für Child-Tabellen-Zeilen, der Link-Felder automatisch auflöst."""
	def __init__(self, source: Any):
		object.__setattr__(self, "_source", source)
		meta = None
		try:
			doctype = getattr(source, "doctype", None) or (source.get("doctype") if isinstance(source, dict) else None)
			if doctype:
				meta = frappe.get_meta(doctype)
		except Exception:
			meta = None
		object.__setattr__(self, "_meta", meta)

	def __getattr__(self, key: str):
		source = object.__getattribute__(self, "_source")
		value = _dig_attr(source, key)
		meta = object.__getattribute__(self, "_meta")
		if meta:
			df = meta.get_field(key)
			if df and df.fieldtype == "Link" and df.options and isinstance(value, str):
				try:
					return frappe.get_cached_doc(df.options, value)
				except Exception:
					return value
		return value

	def __getitem__(self, key: str):
		return self.__getattr__(key)

	def as_dict(self):
		source = object.__getattribute__(self, "_source")
		if hasattr(source, "as_dict"):
			try:
				return source.as_dict()
			except Exception:
				return {}
		if isinstance(source, dict):
			return dict(source)
		return {}

	def __repr__(self):
		source = object.__getattribute__(self, "_source")
		return f"<LinkResolvingRow {source!r}>"


def _is_document_like(value: Any) -> bool:
	if getattr(value, "doctype", None):
		return True
	return isinstance(value, dict) and bool(value.get("doctype"))


def _wrap_preserved_list(values: list[Any] | tuple[Any, ...]) -> list[Any]:
	"""Stellt sicher, dass Listen aus Pfaden mit [] Link-Felder als Dokumente liefern."""
	wrapped: list[Any] = []
	for item in values:
		if _is_document_like(item):
			wrapped.append(_LinkResolvingRow(item))
		else:
			wrapped.append(item)
	return wrapped


def _dig_attr(source: Any, key: str) -> Any:
	if source is None:
		return None

	if isinstance(source, dict):
		return source.get(key)

	if isinstance(source, (list, tuple)) and key.isdigit():
		idx = int(key)
		if 0 <= idx < len(source):
			return source[idx]
		return None

	return getattr(source, key, None)


def _resolve_value_path(path: str, context: Dict[str, Any]) -> Any:
	raw_segments = [seg.strip() for seg in cstr(path).split(".") if seg.strip()]
	if not raw_segments:
		return None

	preserve_list = False
	if raw_segments and raw_segments[-1].endswith("[]"):
		raw_segments[-1] = raw_segments[-1][:-2].strip()
		preserve_list = True
		if not raw_segments[-1]:
			return None

	segments = raw_segments
	if not segments:
		return None

	def pick_child_row(child_list: list[Any], lookahead: str | None = None) -> tuple[Any | None, bool]:
		"""Pick a child row from a child table. Returns (row, consumed_numeric)."""
		if not child_list:
			return None, False

		if lookahead is not None and lookahead.isdigit():
			idx = int(lookahead)
			if 0 <= idx < len(child_list):
				return child_list[idx], True

		if lookahead:
			for item in child_list:
				if getattr(item, lookahead, None):
					return item, False

		return child_list[0], False

	def resolve_from_root(root: Any) -> Any:
		current: Any = root
		idx = 0
		while idx < len(segments):
			segment = segments[idx]

			if isinstance(current, dict):
				current = current.get(segment)
				if current is None:
					return None
				if preserve_list and idx == len(segments) - 1 and isinstance(current, (list, tuple)):
					return current
				idx += 1
				continue

			if isinstance(current, (list, tuple)):
				if preserve_list and idx == len(segments) - 1:
					return current
				lookahead = segments[idx + 1] if idx + 1 < len(segments) else None
				row, consumed_numeric = pick_child_row(list(current), lookahead)
				if row is None:
					return None
				current = row
				idx += 1
				if consumed_numeric:
					idx += 1
				continue

			# Follow Link/Table fields using DocType meta so Pfade aus dem Wizard funktionieren.
			doctype = getattr(current, "doctype", None)
			meta = None
			if doctype:
				try:
					meta = frappe.get_meta(doctype)
				except Exception:
					meta = None

			if meta:
				df = meta.get_field(segment)
				if df:
					if df.fieldtype == "Link" and df.options:
						link_value = getattr(current, segment, None)
						if not link_value:
							return None
						try:
							current = frappe.get_cached_doc(df.options, link_value)
						except Exception:
							return None
						idx += 1
						continue

					if df.fieldtype == "Table" and df.options:
						child_list = getattr(current, segment, None) or []
						if preserve_list and idx == len(segments) - 1:
							return list(child_list)
						lookahead = segments[idx + 1] if idx + 1 < len(segments) else None
						child_row, consumed_numeric = pick_child_row(child_list, lookahead)
						if not child_row:
							return None
						current = child_row
						idx += 1
						if consumed_numeric:
							idx += 1
						continue

			current = _dig_attr(current, segment)
			if current is None:
				return None
			if preserve_list and idx == len(segments) - 1 and isinstance(current, (list, tuple)):
				return current
			idx += 1

		return current

	primary = resolve_from_root(context)
	if preserve_list and isinstance(primary, (list, tuple)):
		return _wrap_preserved_list(list(primary))
	if primary is not None:
		return primary

	if isinstance(context, dict):
		for alt_root in (context.get("iteration_doc"), context.get("iteration_objekt")):
			if alt_root is None:
				continue
			alt_value = resolve_from_root(alt_root)
			if alt_value is not None:
				if preserve_list and isinstance(alt_value, (list, tuple)):
					return _wrap_preserved_list(list(alt_value))
				return alt_value

	return None


def _collect_template_requirements(template, base_doctype: str | None = None) -> Dict[str, Any]:
	base_doctype = base_doctype or template.get("haupt_verteil_objekt")
	if not base_doctype:
		frappe.throw(_("Bitte hinterlegen Sie ein Haupt-Verteil-Objekt in der Vorlage."))

	meta = frappe.get_meta(base_doctype)
	grid_fields = {df.fieldname: df for df in meta.fields}
	link_fields_by_doctype = {cstr(df.options): df for df in meta.fields if df.fieldtype == "Link" and df.options}

	references, block_requirements = _extract_template_reference_fields(
		template, grid_fields, link_fields_by_doctype, base_doctype=base_doctype
	)

	grouped: dict[str, list[Dict[str, Any]]] = defaultdict(list)
	for reference in references:
		if not reference.get("fieldname"):
			continue
		grouped[reference["fieldname"]].append(reference)

	required_fields: list[Dict[str, Any]] = []
	auto_fields: list[Dict[str, Any]] = []
	missing_fields: list[Dict[str, Any]] = []
	template_requirements: list[Dict[str, Any]] = []
	template_requirements_seen: set[str] = set()

	for fieldname, refs in grouped.items():
		manual_refs = [r for r in refs if not r.get("resolved_in_template")]
		use_refs = manual_refs or refs
		base = use_refs[0]

		row_fieldname = base.get("row_fieldname") or fieldname
		docfield = grid_fields.get(row_fieldname)
		label = (
			docfield.label
			if docfield
			else base.get("field_label")
			or base.get("label")
			or fieldname.replace("_", " ").title()
		)

		entry = {
			"fieldname": fieldname,
			"row_fieldname": row_fieldname,
			"doctype": base.get("doctype"),
			"label": label,
			"is_list": bool(base.get("is_list")),
			"source": ", ".join(
				sorted({cstr(r.get("source") or "") for r in use_refs if r.get("source")})
			),
			"resolved_via_default": base.get("resolved_via_default"),
			"path_source": base.get("path_source"),
		}

		if not manual_refs and base.get("path"):
			entry["path"] = base.get("path")
			auto_fields.append(entry)
			continue

		required_fields.append(entry)
		if not docfield:
			missing_fields.append(entry)

	for ref in references:
		if ref.get("origin") != "template_variable":
			continue
		req_key = cstr(ref.get("req_key") or "").strip()
		if not req_key or req_key in template_requirements_seen:
			continue
		template_requirements_seen.add(req_key)
		template_requirements.append(
			{
				"fieldname": ref.get("fieldname"),
				"doctype": ref.get("doctype"),
				"label": ref.get("label") or ref.get("fieldname"),
				"req_key": ref.get("req_key"),
				"is_list": bool(ref.get("is_list")),
				"source": ref.get("source"),
				"path": ref.get("path"),
				"resolved_in_template": ref.get("resolved_in_template"),
				"resolved_via_default": ref.get("resolved_via_default"),
				"path_source": ref.get("path_source"),
			}
		)

	empfaenger_links = [
		{"fieldname": df.fieldname, "doctype": df.options, "label": df.label or df.fieldname}
		for df in meta.fields
		if df.fieldtype == "Link" and df.options
	]

	template_variables = _collect_template_variables(template)
	template_variable_defaults = _parse_variable_values(getattr(template, "variablen_werte", None))
	block_variables = _collect_block_variables(template)
	pdf_block_mappings = _collect_pdf_block_mappings(template)

	return {
		"required_fields": required_fields,
		"auto_fields": auto_fields,
		"missing_fields": missing_fields,
		"block_requirements": block_requirements,
		"template_requirements": template_requirements,
		"template_variables": template_variables,
		"template_variable_defaults": template_variable_defaults,
		"block_variables": block_variables,
		"pdf_block_mappings": pdf_block_mappings,
		"haupt_verteil_objekt": template.get("haupt_verteil_objekt"),
		"empfaenger_links": empfaenger_links,
	}


def _extract_template_reference_fields(
	template,
	grid_fields=None,
	link_fields_by_doctype=None,
	base_doctype: str | None = None,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
	references: list[Dict[str, Any]] = []
	block_requirements: list[Dict[str, Any]] = []
	grid_fields = grid_fields or {}
	link_fields_by_doctype = link_fields_by_doctype or {}
	global_default_mapping = _get_global_default_path_map(base_doctype)
	template_mapping = _parse_mapping(getattr(template, "pfad_zuordnung", None))

	table_fields_by_doctype: dict[str, Any] = {}
	table_fields: list[Any] = []
	if base_doctype:
		try:
			meta = frappe.get_meta(base_doctype)
		except Exception:
			meta = None
		if meta:
			for df in meta.fields:
				if df.fieldtype == "Table" and df.options and cstr(df.options):
					table_fields_by_doctype.setdefault(cstr(df.options), df)
					table_fields.append(df)

	def resolve_field(doctype: str, suggested: str | None = None) -> tuple[str, str | None, bool]:
		link_df = link_fields_by_doctype.get(doctype)
		if link_df:
			return link_df.fieldname, link_df.label, True

		if suggested:
			return suggested, None, False

		return frappe.scrub(doctype), None, False

	def pick_mapping_value(mapping: dict[str, Any] | None, req_key: str, reference=None):
		if not mapping:
			return None

		keys = [
			req_key,
			cstr(reference.get("reference_doctype") if isinstance(reference, dict) else getattr(reference, "reference_doctype", None) or ""),
			cstr(reference.get("context_variable") if isinstance(reference, dict) else getattr(reference, "context_variable", None) or ""),
			cstr(reference.get("fieldname") if isinstance(reference, dict) else ""),
		]

		for key in keys:
			if not key:
				continue
			value = mapping.get(key)
			if value not in (None, ""):
				return value

		return None

	if template.get("haupt_verteil_objekt"):
		fieldname, field_label, _has_direct_link = resolve_field(template.haupt_verteil_objekt)
		path = None
		path_source = None
		if base_doctype and template.haupt_verteil_objekt == base_doctype:
			# The iteration doc itself is already available in the context (e.g. `mietvertrag`).
			path = "__self__"
			path_source = "self"
		references.append(
			{
				"fieldname": fieldname,
				"doctype": template.haupt_verteil_objekt,
				"source": _("Vorlage"),
				"label": field_label or template.haupt_verteil_objekt,
				"field_label": field_label,
				"req_key": f"template::{template.get('name') or 'vorlage'}::{fieldname}",
				"path": path,
				"resolved_in_template": bool(path),
				"resolved_via_default": bool(path),
				"path_source": path_source,
			}
		)

	for variable in template.get("variables") or []:
		variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
		if variable_type not in {"Doctype", "Doctype Liste"}:
			continue
		ref_doctype = cstr(getattr(variable, "reference_doctype", None) or "").strip()
		if not ref_doctype:
			continue

		context_variable = cstr(
			getattr(variable, "variable", None)
			or getattr(variable, "label", None)
			or ref_doctype
			or ""
		).strip()
		fieldname = frappe.scrub(context_variable or ref_doctype)
		if not fieldname:
			continue

		rowname = cstr(getattr(variable, "name", None) or "").strip()
		use_rowname = bool(rowname and not rowname.startswith("new"))
		req_key = rowname if use_rowname else ref_doctype or fieldname
		is_list = variable_type == "Doctype Liste"

		row_fieldname, row_field_label, has_direct_link = resolve_field(ref_doctype, fieldname)
		direct_path = row_fieldname if has_direct_link else None
		if base_doctype and ref_doctype == base_doctype:
			direct_path = "__self__"

		if is_list:
			table_df = table_fields_by_doctype.get(ref_doctype)
			if table_df and getattr(table_df, "fieldname", None):
				direct_path = table_df.fieldname
				row_fieldname = table_df.fieldname
				row_field_label = getattr(table_df, "label", None)
			if not direct_path and table_fields:
				for candidate in table_fields:
					child_dt = cstr(getattr(candidate, "options", None) or "").strip()
					if not child_dt:
						continue
					try:
						child_meta = frappe.get_meta(child_dt)
					except Exception:
						child_meta = None
					if not child_meta:
						continue
					match = next(
						(
							df
							for df in child_meta.fields
							if df.fieldtype == "Link"
							and cstr(getattr(df, "options", None) or "").strip() == ref_doctype
						),
						None,
					)
					if not match:
						continue
					direct_path = candidate.fieldname
					row_fieldname = candidate.fieldname
					row_field_label = getattr(candidate, "label", None)
					break

		spec = {
			"reference_doctype": ref_doctype,
			"context_variable": context_variable,
			"fieldname": fieldname,
		}

		path_from_template = pick_mapping_value(template_mapping, req_key, spec)
		path_from_global = (
			None if path_from_template else pick_mapping_value(global_default_mapping, req_key, spec)
		)
		path_from_direct = None if (path_from_template or path_from_global) else direct_path
		path = path_from_template or path_from_global or path_from_direct
		path_source = (
			"template"
			if path_from_template
			else "global_default"
			if path_from_global
			else "direct"
			if path_from_direct
			else ""
		)

		references.append(
			{
				"fieldname": fieldname,
				"row_fieldname": row_fieldname,
				"field_label": row_field_label,
				"doctype": ref_doctype,
				"source": _("Vorlage"),
				"label": getattr(variable, "label", None) or context_variable or ref_doctype,
				"req_key": req_key,
				"is_list": is_list,
				"resolved_in_template": bool(path),
				"resolved_via_default": path_source in {"global_default", "direct"},
				"path_source": path_source,
				"path": path,
				"origin": "template_variable",
			}
		)

	for row in template.get("textbausteine") or []:
		if not getattr(row, "baustein", None):
			continue

		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", row.baustein)
		except frappe.DoesNotExistError:
			continue

		mapping = _parse_mapping(row.get("pfad_zuordnung"))
		default_mapping = _get_block_default_path_map(block_doc, base_doctype)

		block_refs: list[Dict[str, Any]] = []
		legacy_refs = block_doc.get("reference_doctypes") or []
		legacy_by_key: dict[tuple[str, str], Any] = {}
		for legacy in legacy_refs:
			dt = cstr(getattr(legacy, "reference_doctype", None) or "").strip()
			cv = cstr(getattr(legacy, "context_variable", None) or dt).strip()
			key = (dt, frappe.scrub(cv or dt))
			if dt and key not in legacy_by_key:
				legacy_by_key[key] = legacy

		reference_specs: list[dict[str, Any]] = []
		for variable in block_doc.get("variables") or []:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type == "Text":
				continue
			ref_doctype = cstr(getattr(variable, "reference_doctype", None) or "").strip()
			if not ref_doctype:
				continue
			context_variable = cstr(
				getattr(variable, "variable", None)
				or getattr(variable, "label", None)
				or ref_doctype
				or ""
			).strip()
			fieldname = frappe.scrub(context_variable or ref_doctype)
			if not fieldname:
				continue
			rowname = cstr(getattr(variable, "name", None) or "").strip()
			use_rowname = bool(rowname and not rowname.startswith("new"))
			req_key = rowname if use_rowname else ref_doctype or fieldname

			legacy = legacy_by_key.get((ref_doctype, fieldname))
			if legacy and getattr(legacy, "name", None):
				req_key = cstr(legacy.name)

			reference_specs.append(
				{
					"reference_doctype": ref_doctype,
					"context_variable": context_variable,
					"fieldname": fieldname,
					"req_key": req_key,
					"is_list": variable_type == "Doctype Liste",
				}
			)

		# Fallback: legacy reference_doctypes
		for legacy in legacy_refs:
			ref_doctype = cstr(getattr(legacy, "reference_doctype", None) or "").strip()
			context_variable = cstr(getattr(legacy, "context_variable", None) or ref_doctype or "").strip()
			fieldname = frappe.scrub(context_variable or ref_doctype)
			if not ref_doctype or not fieldname:
				continue
			if any(spec.get("reference_doctype") == ref_doctype and spec.get("fieldname") == fieldname for spec in reference_specs):
				continue
			req_key = cstr(getattr(legacy, "name", None) or ref_doctype or fieldname)
			reference_specs.append(
				{
					"reference_doctype": ref_doctype,
					"context_variable": context_variable,
					"fieldname": fieldname,
					"req_key": req_key,
					"is_list": False,
				}
			)

		for spec in reference_specs:
			ref_doctype = spec["reference_doctype"]
			fieldname = spec["fieldname"]
			req_key = spec["req_key"]
			is_list = bool(spec.get("is_list"))

			row_fieldname, row_field_label, has_direct_link = resolve_field(ref_doctype, fieldname)
			direct_path = row_fieldname if has_direct_link else None
			if base_doctype and ref_doctype == base_doctype:
				direct_path = "__self__"
			if is_list:
				table_df = table_fields_by_doctype.get(ref_doctype)
				if table_df and getattr(table_df, "fieldname", None):
					direct_path = table_df.fieldname
					row_fieldname = table_df.fieldname
					row_field_label = getattr(table_df, "label", None)
				if not direct_path and table_fields:
					# Indirect list: base has a Table whose child has a Link to the desired DocType.
					for candidate in table_fields:
						child_dt = cstr(getattr(candidate, "options", None) or "").strip()
						if not child_dt:
							continue
						try:
							child_meta = frappe.get_meta(child_dt)
						except Exception:
							child_meta = None
						if not child_meta:
							continue
						match = next(
							(
								df
								for df in child_meta.fields
								if df.fieldtype == "Link"
								and cstr(getattr(df, "options", None) or "").strip() == ref_doctype
							),
							None,
						)
						if not match:
							continue
						direct_path = candidate.fieldname
						row_fieldname = candidate.fieldname
						row_field_label = getattr(candidate, "label", None)
						break

			path_from_template = pick_mapping_value(mapping, req_key, spec)
			path_from_default = pick_mapping_value(default_mapping, req_key, spec) if default_mapping else None
			path_from_global = (
				None
				if path_from_template or path_from_default
				else pick_mapping_value(global_default_mapping, req_key, spec)
			)
			path_from_direct = None if (path_from_template or path_from_default or path_from_global) else direct_path
			path = path_from_template or path_from_default or path_from_global or path_from_direct
			path_source = (
				"template"
				if path_from_template
				else "default"
				if path_from_default
				else "global_default"
				if path_from_global
				else "direct"
				if path_from_direct
				else ""
			)

			entry = {
				"fieldname": fieldname,
				"row_fieldname": row_fieldname,
				"field_label": row_field_label,
				"doctype": ref_doctype,
				"source": block_doc.title or block_doc.name,
				"label": row_field_label or ref_doctype,
				"block": block_doc.name,
				"block_title": block_doc.title or block_doc.name,
				"block_rowname": row.name,
				"req_key": req_key,
				"is_list": is_list,
				"resolved_in_template": bool(path),
				"resolved_via_default": path_source in {"default", "global_default", "direct"},
				"path_source": path_source,
				"path": path,
			}
			block_refs.append(entry)
			references.append(entry)

		if block_refs:
			block_requirements.append(
				{
					"block": block_doc.name,
					"block_title": block_doc.title or block_doc.name,
					"rowname": row.name,
					"requirements": block_refs,
				}
		)

	return references, block_requirements


_GLOBAL_STANDARD_PATHS: dict[str, dict[str, str]] = {
	# Von Wohnung zu den üblichen Verknüpfungen
	"Wohnung": {
		"Immobilie": "immobilie",
		"Address": "immobilie.adresse",
		"Contact": "immobilie.hausmeister",
	},
	# Mietvertrag liefert Wohnung und erste(r) Vertragspartner als Contact
	"Mietvertrag": {
		"Wohnung": "wohnung",
		"Immobilie": "wohnung.immobilie",
		"Address": "wohnung.immobilie.adresse",
		"Contact": "mieter.mieter",
		"Vertragspartner": "mieter",
	},
	# Immobilie direkt
	"Immobilie": {
		"Address": "adresse",
		"Contact": "hausmeister",
	},
	# BK Mieter: spiegelt die Mietvertrag-Pfade über das verknüpfte mietvertrag-Feld
	"Betriebskostenabrechnung Mieter": {
		"Mietvertrag": "mietvertrag",
		"Wohnung": "wohnung",
		"Immobilie": "wohnung.immobilie",
		"Address": "wohnung.immobilie.adresse",
		"Contact": "mietvertrag.mieter.mieter",
		"Vertragspartner": "mietvertrag.mieter",
	},
}


def _get_global_default_path_map(base_doctype: str | None = None) -> dict[str, str]:
	"""Globale Standardpfade je Start-Doctype, falls Vorlage und Baustein nichts vorgeben."""

	if not base_doctype:
		return {}

	settings_mapping = _get_settings_global_path_map(base_doctype)
	if settings_mapping:
		return settings_mapping

	return _GLOBAL_STANDARD_PATHS.get(base_doctype, {})


def _get_settings_global_path_map(base_doctype: str | None = None) -> dict[str, str]:
	"""Load globale Pfade aus Serienbrief Einstellungen (falls gepflegt)."""

	if not base_doctype:
		return {}

	try:
		settings = frappe.get_cached_doc("Serienbrief Einstellungen")
	except Exception:
		return {}

	rows = getattr(settings, "standardpfade", None) or []
	fallback: dict[str, str] | None = None

	for row in rows:
		startobjekt = cstr(getattr(row, "startobjekt", None) or "").strip()
		mapping = _parse_mapping(getattr(row, "pfad_zuordnung", None))
		if startobjekt and startobjekt == base_doctype and mapping:
			return mapping
		if not startobjekt and mapping:
			fallback = mapping

	return fallback or {}


def _get_block_default_path_map(block_doc, base_doctype: str | None = None) -> dict[str, str]:
	"""Return default path mapping for a Textbaustein for the given start DocType."""

	rows = getattr(block_doc, "standardpfade", None) or []
	if not rows and isinstance(block_doc, dict):
		rows = block_doc.get("standardpfade") or []

	if not rows:
		return {}

	fallback: dict[str, str] | None = None
	for row in rows:
		startobjekt = cstr(
			getattr(row, "startobjekt", None)
			or (row.get("startobjekt") if isinstance(row, dict) else None)
			or ""
		)
		mapping = _parse_mapping(
			getattr(row, "pfad_zuordnung", None) if not isinstance(row, dict) else row.get("pfad_zuordnung")
		)
		if startobjekt and base_doctype and startobjekt == base_doctype and isinstance(mapping, dict):
			return mapping

		if not startobjekt and isinstance(mapping, dict) and mapping:
			fallback = mapping

	if fallback and isinstance(fallback, dict):
		return fallback

	return {}


def _collect_block_variables(template) -> list[Dict[str, Any]]:
	results: list[Dict[str, Any]] = []

	for row in template.get("textbausteine") or []:
		if not getattr(row, "baustein", None):
			continue

		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", row.baustein)
		except frappe.DoesNotExistError:
			continue

		variables: list[Dict[str, Any]] = []
		for variable in block_doc.get("variables") or []:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type != "Text":
				continue

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			variables.append(
				{
					"key": key,
					"variable": raw_key,
					"label": getattr(variable, "label", None) or raw_key,
					"description": getattr(variable, "beschreibung", None) or "",
				}
			)

		if not variables:
			continue

		results.append(
			{
				"block": block_doc.name,
				"block_title": block_doc.title or block_doc.name,
				"rowname": row.name,
				"variables": variables,
				"values": _parse_variable_values(getattr(row, "variablen_werte", None)),
			}
		)

	return results


def _collect_pdf_block_mappings(template) -> list[Dict[str, Any]]:
	results: list[Dict[str, Any]] = []
	for row in template.get("textbausteine") or []:
		block_name = cstr(getattr(row, "baustein", None) or "").strip()
		if not block_name:
			continue
		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_name)
		except frappe.DoesNotExistError:
			continue

		content_type = cstr(getattr(block_doc, "content_type", None) or "").strip() or "Textbaustein (Rich Text)"
		if content_type != "PDF Formular":
			continue

		fields: list[Dict[str, Any]] = []
		for mapping in getattr(block_doc, "pdf_field_mappings", []) or []:
			field_name = cstr(getattr(mapping, "pdf_field_name", None) or "").strip()
			if not field_name:
				continue
			path = cstr(getattr(mapping, "value_path", None) or "").strip()
			fields.append(
				{
					"pdf_field_name": field_name,
					"value_path": path,
					"fallback_value": getattr(mapping, "fallback_value", None),
					"required": bool(int(getattr(mapping, "required", 0) or 0)),
					"value_type": cstr(getattr(mapping, "value_type", None) or "String").strip() or "String",
				}
			)
		if not fields:
			continue
		results.append(
			{
				"block": block_doc.name,
				"block_title": block_doc.title or block_doc.name,
				"rowname": row.name,
				"fields": fields,
			}
		)
	return results


def _collect_template_variables(template) -> list[Dict[str, Any]]:
	results: list[Dict[str, Any]] = []

	for variable in template.get("variables") or []:
		variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
		if variable_type not in {"String", "Zahl", "Bool", "Datum", "Text"}:
			continue

		raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
		key = frappe.scrub(raw_key) if raw_key else ""
		if not key:
			continue

		results.append(
			{
				"key": key,
				"variable": raw_key,
				"label": getattr(variable, "label", None) or raw_key,
				"description": getattr(variable, "beschreibung", None) or "",
				"variable_type": variable_type,
			}
		)

	return results


@frappe.whitelist()
def get_template_requirements(template: str | None = None, template_doc: Dict[str, Any] | None = None) -> Dict[str, Any]:
	if isinstance(template_doc, str):
		try:
			template_doc = json.loads(template_doc)
		except Exception:
			template_doc = None

	if template_doc:
		doc = frappe.get_doc(template_doc)
	elif template:
		doc = frappe.get_cached_doc("Serienbrief Vorlage", template)
	else:
		frappe.throw(_("Bitte wählen Sie eine Vorlage."))

	return _collect_template_requirements(doc, getattr(doc, "haupt_verteil_objekt", None))


@frappe.whitelist()
def get_serienbrief_assignments(
	doc: str | dict | None = None, docname: str | None = None
) -> Dict[str, Any]:
	if isinstance(doc, str):
		try:
			doc = json.loads(doc)
		except Exception:
			doc = None

	if doc:
		serienbrief = frappe.get_doc(doc)
	elif docname:
		serienbrief = frappe.get_doc("Serienbrief Durchlauf", docname)
	else:
		frappe.throw(_("Bitte übergebe einen Serienbrief."))

	if not serienbrief.vorlage:
		frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

	template = frappe.get_cached_doc("Serienbrief Vorlage", serienbrief.vorlage)
	iteration_doctype = serienbrief.iteration_doctype or template.get("haupt_verteil_objekt")
	if not iteration_doctype:
		frappe.throw(_("Bitte wählen Sie einen Iterations-Doctype."))

	requirements = _collect_template_requirements(template, iteration_doctype)
	empfaenger_rows = serienbrief._get_empfaenger_rows()

	def collect_requirement_entries(reqs: list[Dict[str, Any]], context: Dict[str, Any], is_auto: bool = False):
		entries: list[Dict[str, Any]] = []
		for req in reqs or []:
			fieldname = cstr(req.get("fieldname") or "").strip()
			value = context.get(fieldname) if fieldname else None
			entries.append(
				{
					"label": req.get("label") or fieldname,
					"fieldname": fieldname,
					"doctype": req.get("doctype"),
					"path": req.get("path"),
					"source": req.get("source"),
					"resolved_via_default": req.get("resolved_via_default"),
					"is_list": bool(req.get("is_list")),
					"is_auto": is_auto,
					"value": _serialize_overview_value(value),
				}
			)
		return entries

	template_variable_defs = requirements.get("template_variables") or []
	template_blocks = list(template.get("textbausteine") or [])
	block_requirement_map = {
		entry.get("rowname"): entry for entry in requirements.get("block_requirements") or []
	}
	block_variable_map = {
		entry.get("rowname"): entry for entry in requirements.get("block_variables") or []
	}
	pdf_block_map = {entry.get("rowname"): entry for entry in requirements.get("pdf_block_mappings") or []}

	rows_payload: list[Dict[str, Any]] = []
	total = len(empfaenger_rows)
	for idx, row in enumerate(empfaenger_rows, start=1):
		context = serienbrief._build_context(
			row, idx, requirements, template, total=total, strict_variables=False
		)
		label = (
			getattr(row, "anzeigename", None)
			or getattr(row, "iteration_objekt", None)
			or getattr(row, "objekt", None)
			or cstr(getattr(row, "name", "") or "")
		)

		template_fields = []
		template_fields.extend(collect_requirement_entries(requirements.get("required_fields"), context))
		template_fields.extend(
			collect_requirement_entries(requirements.get("auto_fields"), context, is_auto=True)
		)

		template_variables: list[Dict[str, Any]] = []
		for variable in template_variable_defs:
			key = (
				variable.get("key")
				or frappe.scrub(cstr(variable.get("variable") or variable.get("label") or ""))
			)
			if not key:
				continue
			value = context.get(key)
			template_variables.append(
				{
					"key": key,
					"label": variable.get("label") or variable.get("variable") or key,
					"value": _serialize_overview_value(value),
				}
			)

		blocks_payload: list[Dict[str, Any]] = []
		for block_row in template_blocks:
			rowname = getattr(block_row, "name", None)
			block_name = getattr(block_row, "baustein", None)
			block_title = block_name or rowname
			requirement_entry = block_requirement_map.get(rowname) or {}
			variable_entry = block_variable_map.get(rowname) or {}
			pdf_entry = pdf_block_map.get(rowname) or {}

			block_context = frappe._dict(context)
			if block_name:
				try:
					block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_name)
					serienbrief._apply_block_variables(block_context, block_doc, block_row)
				except Exception:
					pass

			block_variables: list[Dict[str, Any]] = []
			for variable in variable_entry.get("variables") or []:
				key = (
					variable.get("key")
					or frappe.scrub(cstr(variable.get("variable") or variable.get("label") or ""))
				)
				if not key:
					continue
				value = block_context.get(key)
				block_variables.append(
					{
						"key": key,
						"label": variable.get("label") or variable.get("variable") or key,
						"value": _serialize_overview_value(value),
					}
				)

			pdf_fields: list[Dict[str, Any]] = []
			for mapping in pdf_entry.get("fields") or []:
				path = cstr(mapping.get("value_path") or "").strip()
				value = _resolve_value_path(path, block_context) if path else None
				if value in (None, ""):
					value = mapping.get("fallback_value")
				pdf_fields.append(
					{
						"pdf_field_name": mapping.get("pdf_field_name"),
						"value_path": path,
						"required": bool(mapping.get("required")),
						"value_type": mapping.get("value_type"),
						"value": _serialize_overview_value(value),
					}
				)

			blocks_payload.append(
				{
					"rowname": rowname,
					"block": block_name,
					"block_title": block_title,
					"requirements": collect_requirement_entries(
						requirement_entry.get("requirements") or [], context
					),
					"variables": block_variables,
					"pdf_fields": pdf_fields,
				}
			)

		rows_payload.append(
			{
				"index": idx,
				"label": label,
				"iteration": {
					"doctype": getattr(row, "iteration_doctype", None),
					"name": getattr(row, "iteration_objekt", None),
				},
				"template_fields": template_fields,
				"template_variables": template_variables,
				"blocks": blocks_payload,
			}
		)

	return {
		"vorlage": serienbrief.vorlage,
		"iteration_doctype": iteration_doctype,
		"rows": rows_payload,
	}


@frappe.whitelist()
def generate_pdf(
	docname: str,
	print_format: str | None = None,
	recreate_documents: int | str = 0,
) -> str:
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError
	recreate_flag = bool(int(recreate_documents or 0))
	return doc.generate_pdf_file(
		print_format=print_format,
		recreate_documents=recreate_flag,
	)


@frappe.whitelist()
def generate_html(docname: str) -> str:
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError
	return doc.generate_html_file()


@frappe.whitelist()
def regenerate_dokumente(docname: str, submit_documents: int | str = 0) -> list[str]:
	durchlauf = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", durchlauf):
		raise frappe.PermissionError

	submit_flag = bool(int(submit_documents or 0))
	return durchlauf._ensure_dokumente(recreate=True, submit=submit_flag)


@frappe.whitelist()
def render_preview(doc: str | dict | None = None, docname: str | None = None) -> Dict[str, str]:
	"""Render Serienbrief HTML für den Editor, ohne Dateien zu speichern."""

	doc_data: dict[str, Any] | None = None
	if isinstance(doc, str):
		try:
			doc_data = json.loads(doc)
		except Exception:
			doc_data = None
	elif isinstance(doc, dict):
		doc_data = doc

	if doc_data:
		serienbrief = frappe.get_doc(doc_data)
	elif docname:
		serienbrief = frappe.get_doc("Serienbrief Durchlauf", docname)
	else:
		frappe.throw(_("Bitte übergebe einen Serienbrief."))

	html = serienbrief._render_full_html()
	return {"html": html}
