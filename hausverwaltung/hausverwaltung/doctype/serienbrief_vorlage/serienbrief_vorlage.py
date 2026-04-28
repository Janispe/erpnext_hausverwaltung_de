from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.exceptions import DuplicateEntryError
from frappe.model.document import Document
from frappe.utils import cint, cstr
from frappe.utils.jinja import get_jenv
from frappe.utils.pdf import get_pdf
from jinja2 import Undefined
from markupsafe import Markup, escape

from hausverwaltung.hausverwaltung.utils.jinja_source_sanitizer import sanitize_richtext_jinja_source


class SerienbriefVorlage(Document):
	def validate(self):
		content_type = (getattr(self, "content_type", "") or "").strip() or "Textbaustein (Rich Text)"
		self.content_type = content_type
		if content_type == "HTML + Jinja":
			self.html_content = cstr(getattr(self, "html_content", "") or "")
			self.jinja_content = cstr(getattr(self, "jinja_content", "") or "")
			return

		# Prevent rich-text editor artifacts (nested placeholder spans, invisible chars)
		# from being persisted. This keeps templates stable across print/PDF rendering.
		if getattr(self, "content", None):
			self.content = sanitize_richtext_jinja_source(cstr(self.content))


def _get_block_template_source(block_doc) -> str:
	content_type = (getattr(block_doc, "content_type", "") or "").strip() or "Textbaustein (Rich Text)"
	if content_type == "PDF Formular":
		title = cstr(getattr(block_doc, "title", "") or getattr(block_doc, "name", "") or "PDF-Formular")
		pages = cstr(getattr(block_doc, "pdf_pages", "") or "").strip()
		page_hint = f" ({pages})" if pages else ""
		return (
			f'<div class="serienbrief-pdf-placeholder" data-block="{cstr(getattr(block_doc, "name", "") or "")}">'
			f"{_('PDF-Formular')}: {escape(title)}{escape(page_hint)}</div>"
		)
	if content_type == "HTML + Jinja":
		parts = [
			cstr(getattr(block_doc, "jinja_content", "") or ""),
			cstr(getattr(block_doc, "html_content", "") or ""),
		]
		return "\n".join([p for p in parts if p.strip()])

	return cstr(getattr(block_doc, "text_content", "") or "")


def _get_template_template_source(template_doc) -> str:
	content_type = (getattr(template_doc, "content_type", "") or "").strip() or "Textbaustein (Rich Text)"
	if content_type == "HTML + Jinja":
		parts = [
			cstr(getattr(template_doc, "jinja_content", "") or ""),
			cstr(getattr(template_doc, "html_content", "") or ""),
		]
		return "\n".join([p for p in parts if p.strip()])

	return sanitize_richtext_jinja_source(cstr(getattr(template_doc, "content", "")).strip())


def _wrap_preview_html(body_html: str) -> str:
	styles = """
		body {
			font-family: "Arial", "Helvetica", sans-serif;
			color: #222;
			font-size: 11pt;
			margin: 24px;
		}
		.hv-preview-field {
			background: #fff2a8;
			border-radius: 2px;
			padding: 0 2px;
		}
		.serienbrief-page {
			min-height: 260mm;
			padding: 0;
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

	return f"""<!DOCTYPE html>
<html>
	<head>
		<meta charset="utf-8">
		<style>{styles}</style>
	</head>
	<body>
		<div class="serienbrief-page">{body_html}</div>
	</body>
</html>"""


def _preview_value_from_path(path: str) -> str:
	label = cstr(path or "").strip()
	if not label:
		return "Beispielwert"

	key = label.lower()
	if "salutation" in key or "anrede" in key:
		return "Herr"
	if "first_name" in key:
		return "Max"
	if "last_name" in key:
		return "Mustermann"
	if "datum" in key or "date" in key:
		return "31.12.2024"
	if "plz" in key:
		return "12345"
	if "ort" in key:
		return "Musterstadt"
	if "strasse" in key or "street" in key:
		return "Musterstrasse 12"
	if "adresse" in key or "address" in key:
		return "Musterstrasse 12, 12345 Musterstadt"
	if "name" in key:
		return "Max Mustermann"
	if "email" in key:
		return "max.mustermann@example.de"
	if "telefon" in key or "phone" in key or key.endswith("tel"):
		return "0123 456789"
	if "betrag" in key or "summe" in key or "preis" in key or "kosten" in key or "miete" in key:
		return "1.234,56 EUR"
	if "anteil" in key:
		return "75"
	if "beschreibung" in key or "text" in key or "notiz" in key:
		return f"Beispieltext fuer {label}"

	return "Beispielwert"


class SplitPreviewUndefined(Undefined):
	def _path(self) -> str:
		return cstr(getattr(self, "_undefined_name", "") or "").strip()

	def _derive(self, name) -> "SplitPreviewUndefined":
		base = self._path()
		suffix = cstr(name or "").strip()
		if base and suffix:
			path = f"{base}.{suffix}"
		elif base:
			path = base
		else:
			path = suffix
		return self.__class__(name=path)

	def __str__(self) -> str:
		return _preview_value_from_path(self._path())

	def __html__(self) -> str:
		return _preview_value_from_path(self._path())

	def __iter__(self):
		return iter([self._derive("item1"), self._derive("item2")])

	def __len__(self) -> int:
		return 2

	def __bool__(self) -> bool:
		return True

	def __getattr__(self, name):
		return self._derive(name)

	def __getitem__(self, key):
		return self._derive(key)

	def __call__(self, *args, **kwargs):
		return self._derive("call")

	def __add__(self, other):
		return f"{self}{other}"

	def __radd__(self, other):
		return f"{other}{self}"

	def __int__(self) -> int:
		return 123

	def __float__(self) -> float:
		return 123.45


class SplitPreviewDummy:
	def __init__(self, doctype: str | None = None, name: str | None = None):
		self.doctype = doctype or "Dummy"
		self.name = name or "DUMMY-0001"

	def __getattr__(self, name):
		return SplitPreviewUndefined(name=f"{self.doctype}.{name}")

	def __getitem__(self, key):
		return SplitPreviewUndefined(name=f"{self.doctype}.{key}")

	def __bool__(self) -> bool:
		return True


class SplitPreviewContact:
	def __init__(self):
		self.doctype = "Contact"
		self.name = "CONTACT-0001"
		self.salutation = "Herr"
		self.anrede = "Herr"
		self.first_name = "Max"
		self.last_name = "Mustermann"

	def __getattr__(self, name):
		return SplitPreviewUndefined(name=f"Contact.{name}")

	def __getitem__(self, key):
		return SplitPreviewUndefined(name=f"Contact.{key}")

	def __bool__(self) -> bool:
		return True


class SplitPreviewAddress:
	def __init__(self):
		self.doctype = "Address"
		self.name = "ADDR-0001"
		self.address_line1 = "Tristanstr. 4"
		self.pincode = "14109"
		self.city = "Berlin"

	def __getattr__(self, name):
		return SplitPreviewUndefined(name=f"Address.{name}")

	def __getitem__(self, key):
		return SplitPreviewUndefined(name=f"Address.{key}")

	def __bool__(self) -> bool:
		return True


class SplitPreviewMietvertrag:
	def __init__(self, kontakt: SplitPreviewContact):
		self.doctype = "Mietvertrag"
		self.name = "MV-0001"
		self.mieter = [frappe._dict(mieter=kontakt), frappe._dict(mieter=kontakt)]
		self.anteil = 75

	def __getattr__(self, name):
		return SplitPreviewUndefined(name=f"Mietvertrag.{name}")

	def __getitem__(self, key):
		return SplitPreviewUndefined(name=f"Mietvertrag.{key}")

	def __bool__(self) -> bool:
		return True


class SplitPreviewWohnung:
	def __init__(self):
		self.doctype = "Wohnung"
		self.name = "Wohnung 1.OG links"

	def __getattr__(self, name):
		return SplitPreviewUndefined(name=f"Wohnung.{name}")

	def __getitem__(self, key):
		return SplitPreviewUndefined(name=f"Wohnung.{key}")

	def __bool__(self) -> bool:
		return True


class SplitPreviewFrappeProxy:
	def __getattr__(self, name):
		if name == "get_doc":
			return self.get_doc
		if name == "get_cached_doc":
			return self.get_cached_doc
		return getattr(frappe, name)

	def get_doc(self, doctype, name=None, *args, **kwargs):
		return SplitPreviewDummy(cstr(doctype), cstr(name) if name else None)

	def get_cached_doc(self, doctype, name=None, *args, **kwargs):
		return SplitPreviewDummy(cstr(doctype), cstr(name) if name else None)


def _split_preview_context() -> Dict[str, Any]:
	kontakt = SplitPreviewContact()
	address = SplitPreviewAddress()
	mietvertrag = SplitPreviewMietvertrag(kontakt)
	wohnung = SplitPreviewWohnung()
	empfaenger = frappe._dict(
		name="Hausverwaltung",
		anzeigename="Hausverwaltung",
		strasse=address.address_line1,
		plz=address.pincode,
		ort=address.city,
		adresse=f"{address.address_line1}, {address.pincode} {address.city}",
	)
	return {
		"serienbrief_titel": "Beispiel Serienbrief",
		"datum": "31.12.2024",
		"datum_iso": "2024-12-31",
		"empfaenger": empfaenger,
		"empfaenger_data": empfaenger,
		"empfaenger_anzeigename": "Hausverwaltung",
		"mieter_name": "Erika Mustermann",
		"mieter_strasse": address.address_line1,
		"mieter_plz": address.pincode,
		"mieter_ort": address.city,
		"mieter_plz_ort": f"{address.pincode} {address.city}",
		"mieter_adresse": f"{address.address_line1}, {address.pincode} {address.city}",
		"immobilie_strasse": address.address_line1,
		"immobilie_plz": address.pincode,
		"immobilie_ort": address.city,
		"immobilie_plz_ort": f"{address.pincode} {address.city}",
		"immobilie_adresse": f"{address.address_line1}, {address.pincode} {address.city}",
		"baustein": lambda name=None: f"Beispielbaustein {cstr(name or '').strip()}",
		"textbaustein": lambda name=None: f"Beispielbaustein {cstr(name or '').strip()}",
		"var": [frappe._dict(mieter=kontakt), frappe._dict(mieter=kontakt)],
		"address": address,
		"mietvertrag": mietvertrag,
		"iteration_doc": mietvertrag,
		"mieter": kontakt,
		"wohnung": wohnung,
		"frappe": SplitPreviewFrappeProxy(),
	}


def _render_split_preview_html(html: str) -> str:
	if not html:
		return html
	try:
		env = get_jenv().overlay(
			undefined=SplitPreviewUndefined, finalize=_split_preview_finalize_value
		)
		sanitized = sanitize_richtext_jinja_source(html)
		return env.from_string(sanitized).render(_split_preview_context())
	except Exception:
		return html


def _render_split_preview_source(source: str, extra_context: Dict[str, Any] | None = None) -> str:
	"""Render a single Jinja source (baustein or standard text) with the split preview context,
	optionally overlayed with preview defaults for the currently-rendered block.
	"""
	if not source:
		return source
	try:
		env = get_jenv().overlay(
			undefined=SplitPreviewUndefined, finalize=_split_preview_finalize_value
		)
		ctx = _split_preview_context()
		if extra_context:
			ctx.update(extra_context)
		sanitized = sanitize_richtext_jinja_source(source)
		return env.from_string(sanitized).render(ctx)
	except Exception:
		return source


def _preview_defaults_for_block(block_doc) -> Dict[str, str]:
	"""Collect per-block preview defaults keyed by variable name.

	The values are plain strings; the Jinja finalize wrapper will add the yellow span.
	"""
	defaults: Dict[str, str] = {}
	for row in block_doc.get("variables") or []:
		varname = cstr(getattr(row, "variable", "") or "").strip()
		preview = cstr(getattr(row, "preview_default", "") or "").strip()
		if varname and preview:
			defaults[varname] = preview
	return defaults


def _wrap_with_serienbrief_dokument_print_format(body_html: str) -> str:
	"""Wrap preview HTML with the Serienbrief Dokument print format so the split preview
	matches the rendering users will see in the generated PDF.
	"""
	try:
		pf_html = frappe.db.get_value("Print Format", "Serienbrief Dokument", "html") or ""
	except Exception:
		pf_html = ""

	preview_styles = """
		.hv-preview-field {
			background: #fff2a8;
			border-radius: 2px;
			padding: 0 2px;
		}
	"""

	if not pf_html:
		return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{preview_styles}</style></head>
<body><div class="print-format">{body_html}</div></body>
</html>"""

	tmp_doc = frappe._dict({"docstatus": 0, "html": body_html, "name": "VORSCHAU"})
	try:
		rendered_pf = frappe.render_template(pf_html, {"doc": tmp_doc})
	except Exception:
		rendered_pf = body_html

	return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{preview_styles}</style>
</head>
<body>
<div class="print-format">
{rendered_pf}
</div>
</body>
</html>"""


def _split_preview_finalize_value(value) -> Markup | str:
	# Frappe's jenv has autoescape=False, so macros return plain ``str`` (Markup
	# stringifies on concatenation). Escaping here would turn HTML produced
	# inside expressions — macros, ``{{ sep | safe }}`` separators, manually
	# joined ``<br/>`` address strings — into literal ``&lt;br/&gt;`` in the
	# preview. Leaving the value raw mirrors the real render flow.
	if value is None:
		return ""
	if isinstance(value, SplitPreviewUndefined):
		value = str(value)
	if isinstance(value, Markup):
		return Markup(f'<span class="hv-preview-field">{value}</span>')
	text = cstr(value)
	if not text:
		return ""
	return Markup(f'<span class="hv-preview-field">{text}</span>')


def _load_template_doc(template: str | None = None, template_doc: Dict[str, Any] | None = None):
	if isinstance(template_doc, str):
		try:
			template_doc = json.loads(template_doc)
		except Exception:
			template_doc = None

	if template_doc:
		return frappe.get_doc(template_doc)
	if template:
		return frappe.get_doc("Serienbrief Vorlage", template)

	frappe.throw(_("Bitte wählen Sie eine Vorlage."))


def _build_raw_template_html(template_doc) -> str:
	standard_text = _get_template_template_source(template_doc).strip()
	content_position = cstr(getattr(template_doc, "content_position", "")).strip() or "Nach Bausteinen"
	inline_mode = bool(standard_text and ("baustein(" in standard_text or "textbaustein(" in standard_text))

	def render_raw_block(block_name: str) -> str:
		name = cstr(block_name).strip()
		if not name:
			return ""

		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", name)
		except frappe.DoesNotExistError:
			return ""

		template_source = _get_block_template_source(block_doc).strip()
		if not template_source:
			return ""

		return f'<div class="serienbrief-block" data-block="{cstr(block_doc.name)}">{template_source}</div>'

	def replace_inline_blocks(text: str) -> str:
		if not text:
			return ""
		pattern = r"\{\{\s*(?:baustein|textbaustein)\(\s*['\\\"]([^'\\\"]+)['\\\"]\s*\)\s*\}\}"
		return re.sub(pattern, lambda m: render_raw_block(m.group(1)), text)

	standard_body = replace_inline_blocks(standard_text) if inline_mode else standard_text
	standard_html = (
		f'<div class="serienbrief-block serienbrief-content" data-block="standardtext">{standard_body}</div>'
		if standard_body
		else ""
	)

	if inline_mode:
		if not standard_html:
			return ""
		return _wrap_preview_html(standard_html)

	blocks: list[str] = []

	for row in template_doc.get("textbausteine") or []:
		block_name = getattr(row, "baustein", None)
		if not block_name:
			continue

		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_name)
		except frappe.DoesNotExistError:
			continue

		rendered = render_raw_block(cstr(block_doc.name))
		if rendered:
			blocks.append(rendered)

	html_blocks: list[str] = []
	if content_position == "Vor Bausteinen":
		if standard_html:
			html_blocks.append(standard_html)
		html_blocks.extend(blocks)
	else:
		html_blocks.extend(blocks)
		if standard_html:
			html_blocks.append(standard_html)

	if not html_blocks:
		return ""

	return _wrap_preview_html("\n".join(html_blocks))


def _build_split_preview_html(template_doc) -> str:
	"""Build the split preview HTML by pre-rendering each Textbaustein with its own
	preview defaults, rendering the template's standard text with the base context,
	and assembling the result without a further outer Jinja pass.
	"""
	standard_text = _get_template_template_source(template_doc).strip()
	content_position = cstr(getattr(template_doc, "content_position", "")).strip() or "Nach Bausteinen"
	inline_mode = bool(standard_text and ("baustein(" in standard_text or "textbaustein(" in standard_text))

	def render_block(block_name: str) -> str:
		name = cstr(block_name).strip()
		if not name:
			return ""
		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", name)
		except frappe.DoesNotExistError:
			return ""
		source = _get_block_template_source(block_doc).strip()
		if not source:
			return ""
		defaults = _preview_defaults_for_block(block_doc)
		rendered = _render_split_preview_source(source, extra_context=defaults)
		return f'<div class="serienbrief-block" data-block="{cstr(block_doc.name)}">{rendered}</div>'

	if inline_mode:
		pattern = re.compile(
			r"\{\{\s*(?:baustein|textbaustein)\(\s*['\\\"]([^'\\\"]+)['\\\"]\s*\)\s*\}\}"
		)
		# Protect already-rendered baustein HTML from the outer Jinja pass over standard text.
		rendered_blocks: list[str] = []

		def _placeholder(match) -> str:
			rendered_blocks.append(render_block(match.group(1)))
			return f"<!--HV_BLOCK_{len(rendered_blocks) - 1}-->"

		standard_with_placeholders = pattern.sub(_placeholder, standard_text)
		rendered_standard = _render_split_preview_source(standard_with_placeholders)

		def _restore(match) -> str:
			idx = int(match.group(1))
			return rendered_blocks[idx] if 0 <= idx < len(rendered_blocks) else ""

		body = re.sub(r"<!--HV_BLOCK_(\d+)-->", _restore, rendered_standard)
		if not body:
			return ""
		return f'<div class="serienbrief-block serienbrief-content" data-block="standardtext">{body}</div>'

	blocks: list[str] = []
	for row in template_doc.get("textbausteine") or []:
		block_name = getattr(row, "baustein", None)
		if not block_name:
			continue
		rendered = render_block(cstr(block_name))
		if rendered:
			blocks.append(rendered)

	rendered_standard_body = (
		_render_split_preview_source(standard_text) if standard_text else ""
	)
	standard_html = (
		f'<div class="serienbrief-block serienbrief-content" data-block="standardtext">{rendered_standard_body}</div>'
		if rendered_standard_body
		else ""
	)

	html_blocks: list[str] = []
	if content_position == "Vor Bausteinen":
		if standard_html:
			html_blocks.append(standard_html)
		html_blocks.extend(blocks)
	else:
		html_blocks.extend(blocks)
		if standard_html:
			html_blocks.append(standard_html)

	return "\n".join(html_blocks)


@frappe.whitelist()
def render_template_preview_pdf(
	template: str | None = None,
	template_doc: Dict[str, Any] | None = None,
	split_preview: bool | None = None,
) -> Dict[str, str]:
	doc = _load_template_doc(template, template_doc)

	if split_preview:
		body = _build_split_preview_html(doc)
		if not body:
			frappe.throw(_("Die Vorlage enthält keinen Inhalt."))
		html = _wrap_with_serienbrief_dokument_print_format(body)
	else:
		html = _build_raw_template_html(doc)
		if not html:
			frappe.throw(_("Die Vorlage enthält keinen Inhalt."))

	pdf_bytes = get_pdf(html)
	filename = f"vorlage-preview-{frappe.scrub(doc.name or doc.title or 'vorlage')}.pdf"

	return {
		"pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
		"filename": filename,
	}


@frappe.whitelist()
def render_template_preview_html(
	template: str | None = None, template_doc: Dict[str, Any] | None = None
) -> Dict[str, str]:
	doc = _load_template_doc(template, template_doc)
	html = _build_raw_template_html(doc)

	if not html:
		frappe.throw(_("Die Vorlage enthält keinen Inhalt."))

	return {"html": html}


@frappe.whitelist()
def copy_serienbrief_vorlage(
	template: str | None = None, new_title: str | None = None
) -> Dict[str, str]:
	template_name = (template or "").strip()
	target_title = (new_title or "").strip()

	if not template_name:
		frappe.throw(_("Bitte wählen Sie eine Vorlage, die kopiert werden soll."))

	if not target_title:
		frappe.throw(_("Bitte gib einen Titel für die neue Vorlage ein."))

	if not frappe.has_permission("Serienbrief Vorlage", "read", doc=template_name):
		frappe.throw(_("Keine Berechtigung, die Vorlage zu lesen."), frappe.PermissionError)

	if not frappe.has_permission("Serienbrief Vorlage", "create"):
		frappe.throw(_("Keine Berechtigung, eine neue Vorlage anzulegen."), frappe.PermissionError)

	source_doc = frappe.get_doc("Serienbrief Vorlage", template_name)
	new_doc = frappe.copy_doc(source_doc)
	new_doc.title = target_title
	new_doc.name = None

	try:
		new_doc.insert()
	except DuplicateEntryError:
		frappe.throw(_("Eine Vorlage mit diesem Titel existiert bereits. Bitte wähle einen anderen Titel."))

	return {"name": new_doc.name, "title": new_doc.title}


@frappe.whitelist()
def search_serienbrief_vorlagen(query: str | None = None, limit: int = 20) -> List[Dict[str, str]]:
	"""Suche Vorlagen per Volltext in Titel, Notizen und verknüpften Textbausteinen."""

	search_text = (query or "").strip()
	if not search_text:
		return []

	if len(search_text) < 3:
		frappe.throw(_("Bitte gib mindestens 3 Zeichen als Suchtext ein."))

	if not frappe.has_permission("Serienbrief Vorlage", "read"):
		frappe.throw(_("Keine Berechtigung, Serienbrief Vorlagen zu lesen."), frappe.PermissionError)

	limit_value = max(1, min(50, cint(limit or 20)))
	like_param = f"%{search_text}%"
	params = {"like": like_param, "limit": limit_value}

	templates = frappe.db.sql(
		"""
		select
			template.name,
			template.title,
			template.description,
			template.content,
			template.html_content,
			template.jinja_content,
			template.modified
		from `tabSerienbrief Vorlage` template
		where template.docstatus < 2
		  and (
			  template.title like %(like)s
			  or template.description like %(like)s
			  or template.content like %(like)s
			  or template.html_content like %(like)s
			  or template.jinja_content like %(like)s
			  or exists (
				  select 1
				  from `tabSerienbrief Vorlagenbaustein` vb
				  join `tabSerienbrief Textbaustein` block on block.name = vb.baustein
				  where vb.parent = template.name
				    and (
						block.title like %(like)s
						or block.text_content like %(like)s
						or block.html_content like %(like)s
						or block.jinja_content like %(like)s
				    )
			  )
		  )
		order by template.modified desc
		limit %(limit)s
		""",
		params,
		as_dict=True,
	)

	if not templates:
		return []

	template_names = [tpl["name"] for tpl in templates]
	blocks_by_template = _load_blocks_for_templates(template_names)

	results: list[dict[str, str]] = []
	for tpl in templates:
		snippet, source = _extract_snippet(search_text, tpl, blocks_by_template.get(tpl["name"], []))
		results.append(
			{
				"name": tpl["name"],
				"title": tpl.get("title") or tpl["name"],
				"description": tpl.get("description") or "",
				"matched_block": source or "",
				"snippet": snippet or "",
			}
		)

	return results


def _load_blocks_for_templates(template_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
	if not template_names:
		return {}

	links = frappe.get_all(
		"Serienbrief Vorlagenbaustein",
		filters={"parent": ["in", template_names]},
		fields=["parent", "baustein"],
	)
	block_names = [link.get("baustein") for link in links if link.get("baustein")]

	blocks = []
	if block_names:
		blocks = frappe.get_all(
			"Serienbrief Textbaustein",
			filters={"name": ["in", block_names]},
			fields=["name", "title", "text_content", "html_content", "jinja_content"],
		)

	block_by_name = {block.get("name"): block for block in blocks}
	blocks_by_template: Dict[str, List[Dict[str, Any]]] = {}
	for link in links:
		block = block_by_name.get(link.get("baustein"))
		if not block:
			continue
		blocks_by_template.setdefault(link.get("parent"), []).append(block)

	return blocks_by_template


def _extract_snippet(
	search_text: str, template_row: Dict[str, Any], blocks: List[Dict[str, Any]] | None = None
) -> tuple[str | None, str | None]:
	text_sources: list[tuple[str, str]] = []

	if template_row.get("title"):
		text_sources.append((_("Titel"), _normalize_text(template_row.get("title"))))

	if template_row.get("description"):
		text_sources.append((_("Interne Notiz"), _normalize_text(template_row.get("description"))))

	if template_row.get("content"):
		text_sources.append((_("Standardtext"), _normalize_text(template_row.get("content"))))
	if template_row.get("html_content"):
		text_sources.append((_("HTML"), _normalize_text(template_row.get("html_content"))))
	if template_row.get("jinja_content"):
		text_sources.append((_("Jinja"), _normalize_text(template_row.get("jinja_content"))))

	for block in blocks or []:
		label = block.get("title") or block.get("name")
		for field in ("text_content", "html_content", "jinja_content"):
			raw = block.get(field)
			if raw:
				normalized = _normalize_text(raw)
				if normalized:
					text_sources.append((label, normalized))

	for label, text in text_sources:
		snippet = _build_snippet(text, search_text)
		if snippet:
			return snippet, label

	return None, None


def _normalize_text(value: Any) -> str:
	text = cstr(value or "")
	text = re.sub(r"<[^>]+>", " ", text)
	text = re.sub(r"\s+", " ", text)
	return text.strip()


def _build_snippet(text: str, query: str, context: int = 60) -> str | None:
	if not text or not query:
		return None

	haystack = text.lower()
	needle = query.lower()
	idx = haystack.find(needle)
	if idx == -1:
		return None

	start = max(0, idx - context)
	end = min(len(text), idx + len(query) + context)

	snippet = text[start:end].strip()
	if start > 0:
		snippet = f"... {snippet}"
	if end < len(text):
		snippet = f"{snippet} ..."
	return snippet
