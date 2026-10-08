"""Assistant block creation and append-only proposals using the regular version history."""

import re

import frappe

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as api
from hausverwaltung.hausverwaltung.agent_tools import template_authoring_api as author
from hausverwaltung.hausverwaltung.agent_tools.contracts import (
	AgentToolError,
	normalize_limit,
	normalize_offset,
	parse_json_if_needed,
)
from hausverwaltung.hausverwaltung.agent_tools.mail_merge_contract import AI_RECORD_DOCTYPES, plain_text

BLOCK = "Serienbrief Textbaustein"
BLOCK_RECORD_DOCTYPES = (*AI_RECORD_DOCTYPES, "Mietvertrag", "Wohnung", "Immobilie")


def _write_access(name=None):
	if not set(frappe.get_roles()).intersection({"System Manager", "Hausverwalter"}):
		raise AgentToolError("PERMISSION_DENIED", "Keine Berechtigung, KI-Textbausteine anzulegen.")
	if name:
		doc = api._read(BLOCK, name)
		doc.check_permission("write")
		return doc
	if not frappe.has_permission(BLOCK, "create"):
		raise frappe.PermissionError


def _revision(doc):
	from mail_merge.mail_merge.utils import textbaustein_versions as tbv
	from mail_merge.mail_merge.utils import versioning

	return "block:" + versioning.snapshot_hash(versioning.build_snapshot(tbv.SPEC, doc))


def _paths(raw, doc):
	paths = parse_json_if_needed(raw)
	if not isinstance(paths, dict) or len(paths) > 20:
		raise AgentToolError(
			"INVALID_ARGUMENT", "standardpfade muss ein Objekt mit höchstens 20 Empfängertypen sein."
		)
	keys = {row.variable for row in doc.get("variables") or []}
	rows = []
	for doctype, mapping in paths.items():
		if doctype not in BLOCK_RECORD_DOCTYPES and doctype != "User":
			raise AgentToolError("INVALID_ARGUMENT", "Empfängertyp für Standardpfade ist nicht freigegeben.")
		api._read("DocType", doctype)
		if not frappe.has_permission(doctype, "read"):
			raise frappe.PermissionError
		if not isinstance(mapping, dict) or set(mapping) - keys:
			raise AgentToolError(
				"INVALID_ARGUMENT", "Standardpfade dürfen nur deklarierte Bausteinvariablen zuordnen."
			)
		for path in mapping.values():
			if (
				not isinstance(path, str)
				or len(path) > 240
				or not author._PATH_RE.fullmatch(path)
				or path.split(".", 1)[0] != "objekt"
			):
				raise AgentToolError(
					"INVALID_ARGUMENT",
					"Standardpfade müssen bei objekt beginnen und dürfen keine internen Attribute enthalten.",
				)
		rows.append({"startobjekt": doctype, "pfad_zuordnung": frappe.as_json(mapping)})
	return rows


def _set_html_source(doc, content):
	from mail_merge.mail_merge.utils.assistant_templates import validate_assistant_source

	try:
		validate_assistant_source(content)
	except frappe.ValidationError as exc:
		raise AgentToolError("INVALID_SOURCE", str(exc)) from None
	# The current block context reserves baustein for metadata and does not
	# provide nested render callbacks. Reject this explicitly instead of saving
	# a source that fails only at preview time.
	from jinja2 import nodes
	from mail_merge.mail_merge.utils.jinja_readonly import readonly_jenv

	compiled_source = re.sub(r"\{\{\$\s*[^{}]+?\s*\$\}\}", "PREVIEW", content)
	if any(
		isinstance(call.node, nodes.Name) and call.node.name in {"baustein", "textbaustein"}
		for call in readonly_jenv().parse(compiled_source).find_all(nodes.Call)
	):
		raise AgentToolError(
			"INVALID_SOURCE",
			"KI-Textbausteine dürfen keine anderen Bausteine aufrufen; binde sie nebeneinander in der Vorlage ein.",
		)
	doc.content_type, doc.html_content, doc.jinja_content, doc.text_content = "HTML + Jinja", content, "", ""
	for field in ("outputs", "pdf_field_mappings"):
		doc.set(field, [])
	doc.pdf_file, doc.pdf_pages = None, None


def _set_source(
	doc,
	content,
	variables=None,
	description=None,
	standardpfade=None,
	render_position=None,
	content_type="HTML + Jinja",
	pdf_file=None,
	pdf_pages=None,
	pdf_flatten=None,
	pdf_field_mappings=None,
):
	if content_type not in {"HTML + Jinja", "PDF Formular"}:
		raise AgentToolError("INVALID_ARGUMENT", "Bausteintyp muss HTML + Jinja oder PDF Formular sein.")
	doc.assistant_created = 1
	if variables is not None:
		doc.set("variables", author._variables(variables, record_doctypes=BLOCK_RECORD_DOCTYPES))
		for row in doc.variables:
			if row.reference_doctype:
				api._read("DocType", row.reference_doctype)
				if not frappe.has_permission(row.reference_doctype, "read"):
					raise frappe.PermissionError
	if description is not None:
		doc.description = author._text(description, "description", 4000, False)
	if render_position is not None:
		if render_position not in {"Body", "Footer"}:
			raise AgentToolError("INVALID_ARGUMENT", "render_position muss Body oder Footer sein.")
		doc.render_position = render_position
	if standardpfade is not None:
		doc.set("standardpfade", _paths(standardpfade, doc))
	else:
		# Removing variables must not leave inherited mappings pointing at them.
		keys = {row.variable for row in doc.get("variables") or []}
		for row in doc.get("standardpfade") or []:
			mapping = parse_json_if_needed(row.pfad_zuordnung) or {}
			row.pfad_zuordnung = frappe.as_json({k: v for k, v in mapping.items() if k in keys})
	if content_type == "HTML + Jinja":
		if any(value is not None for value in (pdf_file, pdf_pages, pdf_flatten, pdf_field_mappings)):
			raise AgentToolError("INVALID_ARGUMENT", "PDF-Einstellungen benötigen content_type=PDF Formular.")
		_set_html_source(doc, content)
		return
	if content not in (None, "") or render_position == "Footer":
		raise AgentToolError(
			"INVALID_ARGUMENT", "PDF-Bausteine brauchen keinen HTML-Inhalt und dürfen kein Footer sein."
		)
	from mail_merge.mail_merge.utils.assistant_assets import local_file_content, pdf_info, validate_pdf_block

	if pdf_file is not None:
		file_doc = api._read("File", pdf_file)
		try:
			pdf_info(local_file_content(file_doc))
		except frappe.ValidationError as exc:
			raise AgentToolError("INVALID_ASSET", str(exc)) from None
		doc.pdf_file = file_doc.file_url
	elif doc.content_type != "PDF Formular":
		raise AgentToolError("INVALID_ARGUMENT", "pdf_file benötigt die File-ID aus upload_asset.")
	doc.content_type, doc.html_content, doc.jinja_content, doc.text_content = "PDF Formular", "", "", ""
	doc.render_position = "Body"
	doc.set("outputs", [])
	if pdf_pages is not None:
		doc.pdf_pages = pdf_pages
	if pdf_flatten is not None:
		doc.pdf_flatten = pdf_flatten
	elif doc.pdf_flatten is None:
		doc.pdf_flatten = 1
	if pdf_field_mappings is not None:
		rows = parse_json_if_needed(pdf_field_mappings)
		allowed = {"pdf_field_name", "value_path", "fallback_value", "required", "value_type"}
		if (
			not isinstance(rows, list)
			or len(rows) > 100
			or any(not isinstance(row, dict) or set(row) - allowed for row in rows)
		):
			raise AgentToolError("INVALID_ARGUMENT", "Ungültige PDF-Feldzuordnungen (maximal 100).")
		doc.set("pdf_field_mappings", [{"required": 0, "value_type": "String", **row} for row in rows])
	try:
		validate_pdf_block(doc)
	except frappe.ValidationError as exc:
		raise AgentToolError("INVALID_ARGUMENT", str(exc)) from None


def _result(doc, version, proposal):
	return {
		"baustein": doc.name,
		"bausteinversion": version.name,
		"version_number": version.version_number,
		"source": version.source,
		"assistant_created": True,
		"is_proposal": proposal,
		"based_on": version.get("based_on"),
		"live_block_changed": not proposal,
		"revision": _revision(api._read(BLOCK, doc.name)),
		"url": f"/app/serienbrief-textbaustein/{doc.name}",
		"preview_instruction": "Für eine echte PDF-Vorschau in einem Vorlagenvorschlag baustein_versionen mit diesem Namen und version_number fixieren, save_draft mit der Vorlagenversion aufrufen, dann prepare(draft).",
	}


@frappe.whitelist()
@api._endpoint
def list_textbausteine(query=None, limit=20, offset=0):
	limit, offset = normalize_limit(limit), normalize_offset(offset)
	if query is not None and (not isinstance(query, str) or len(query) > 140):
		raise AgentToolError("INVALID_ARGUMENT", "Ungültiger Suchbegriff.")
	rows = frappe.get_list(
		BLOCK,
		filters={"title": ["like", f"%{query}%"]} if query else {},
		fields=["name", "title", "content_type", "render_position", "assistant_created", "modified"],
		order_by="modified desc, name asc",
		limit_start=offset,
		limit_page_length=limit + 1,
	)
	return {"bausteine": rows[:limit], "has_more": len(rows) > limit, "next_offset": offset + limit}


@frappe.whitelist()
@api._endpoint
def get_textbaustein(baustein, include_source=False, version_number=None):
	from mail_merge.mail_merge.utils import textbaustein_versions as tbv
	from mail_merge.mail_merge.utils import versioning

	if include_source not in (True, False, 0, 1, "0", "1", "true", "false"):
		raise AgentToolError("INVALID_ARGUMENT", "include_source muss ein Boolean sein.")
	live = api._read(BLOCK, baustein)
	doc, version = live, versioning.latest_version(tbv.SPEC, live.name)
	current_version = version.name if version else ""
	if version_number is not None:
		if type(version_number) is not int or version_number < 1:
			raise AgentToolError("INVALID_ARGUMENT", "version_number muss eine positive Ganzzahl sein.")
		version = tbv.version_by_number(live.name, version_number)
		if not version:
			raise AgentToolError("NOT_FOUND", "Bausteinversion existiert nicht.")
		version = versioning.require_version(tbv.SPEC, version.name, live.name)
		doc = tbv.doc_from_snapshot(live.name, versioning.parse_snapshot(tbv.SPEC, version.snapshot))
	source = tbv.snapshot_content(doc.as_dict())
	excerpt, truncated = plain_text(source, 900)
	result = {
		"baustein": live.name,
		"title": doc.title,
		"description": doc.description,
		"content_type": doc.content_type,
		"render_position": doc.render_position,
		"assistant_created": bool(doc.get("assistant_created")),
		"revision": _revision(live),
		"version": versioning.version_metadata(
			version, current_hash=_revision(live).split(":", 1)[1], current_version=current_version
		)
		if version
		else None,
		"content_excerpt": excerpt,
		"excerpt_truncated": truncated,
		"excerpt_is_unrendered": True,
		"variables": [versioning.snapshot_child_row(row) for row in doc.get("variables") or []],
		"standardpfade": {
			row.startobjekt: parse_json_if_needed(row.pfad_zuordnung) or {}
			for row in doc.get("standardpfade") or []
		},
	}
	if include_source in (True, 1, "1", "true"):
		result["source"] = source
	if doc.content_type == "PDF Formular":
		from mail_merge.mail_merge.utils.assistant_assets import pdf_file_info

		result["pdf"] = {
			"file_url": doc.pdf_file,
			"pages": doc.pdf_pages or "",
			"flatten": bool(doc.pdf_flatten),
			"field_mappings": [
				versioning.snapshot_child_row(row) for row in doc.get("pdf_field_mappings") or []
			],
			**pdf_file_info(doc.pdf_file),
		}
	return result


@frappe.whitelist(methods=["POST"])
@api._endpoint
def create_textbaustein(
	title,
	content=None,
	variables=None,
	description=None,
	standardpfade=None,
	render_position="Body",
	content_type="HTML + Jinja",
	pdf_file=None,
	pdf_pages=None,
	pdf_flatten=None,
	pdf_field_mappings=None,
):
	from mail_merge.mail_merge.utils import textbaustein_versions as tbv
	from mail_merge.mail_merge.utils import versioning

	_write_access()
	title = author._text(title, "title")
	if frappe.db.exists(BLOCK, title):
		raise AgentToolError("BLOCK_EXISTS", "Baustein existiert bereits; eine Vorschlagsversion anlegen.")
	with author._atomic():
		doc = frappe.get_doc({"doctype": BLOCK, "title": title})
		_set_source(
			doc,
			content,
			variables if variables is not None else [],
			description,
			standardpfade,
			render_position,
			content_type,
			pdf_file,
			pdf_pages,
			pdf_flatten,
			pdf_field_mappings,
		)
		doc.flags.version_source, doc.flags.version_label = "KI-Erstellung", "Vom Assistenten erstellt"
		doc.insert()
		version = versioning.latest_version(tbv.SPEC, doc.name)
		if not version:
			raise AgentToolError("NOT_READY", "Versionshistorie fehlt; zuerst migrieren.")
		return _result(doc, version, False)


@frappe.whitelist(methods=["POST"])
@api._endpoint
def propose_textbaustein_version(
	baustein,
	revision,
	content=None,
	base_version=None,
	variables=None,
	description=None,
	standardpfade=None,
	render_position=None,
	label=None,
	content_type="HTML + Jinja",
	pdf_file=None,
	pdf_pages=None,
	pdf_flatten=None,
	pdf_field_mappings=None,
):
	from mail_merge.mail_merge.utils import textbaustein_versions as tbv
	from mail_merge.mail_merge.utils import versioning

	live = _write_access(baustein)
	with author._atomic():
		frappe.db.sql("select name from `tabSerienbrief Textbaustein` where name=%s for update", live.name)
		live = api._read(BLOCK, live.name)
		if revision != _revision(live):
			raise AgentToolError(
				"BLOCK_CHANGED", "Baustein wurde geändert; revision aus get_textbaustein neu lesen."
			)
		base_version = base_version or versioning.ensure_current_version(tbv.SPEC, live)
		if not base_version:
			raise AgentToolError("NOT_READY", "Versionshistorie fehlt; zuerst migrieren.")
		try:
			base = versioning.require_version(tbv.SPEC, base_version, live.name)
		except frappe.ValidationError as exc:
			raise AgentToolError("INVALID_ARGUMENT", str(exc)) from None
		candidate = tbv.doc_from_snapshot(live.name, versioning.parse_snapshot(tbv.SPEC, base.snapshot))
		_set_source(
			candidate,
			content,
			variables,
			description,
			standardpfade,
			render_position,
			content_type,
			pdf_file,
			pdf_pages,
			pdf_flatten,
			pdf_field_mappings,
		)
		name = versioning.create_version(
			tbv.SPEC,
			candidate,
			source="KI-Vorschlag",
			label=author._text(label or "KI-Vorschlag", "label"),
			based_on=base.name,
			force=True,
		)
		if not name:
			raise AgentToolError("NOT_READY", "Versionshistorie fehlt; zuerst migrieren.")
		return _result(candidate, frappe.get_doc(tbv.VERSION_DOCTYPE, name), True)
