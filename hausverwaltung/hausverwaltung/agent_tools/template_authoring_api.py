"""Append-only assistant template creation and proposals; never changes a live template."""

import re
from contextlib import contextmanager

import frappe

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as api
from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError, parse_json_if_needed
from hausverwaltung.hausverwaltung.agent_tools.mail_merge_contract import (
	AI_RECORD_DOCTYPES,
	RECORD_TYPES,
	layout_warnings,
)

# Pfadsegmente ohne führenden Unterstrich (keine internen Attribute), optional [] für Listen.
_VARIABLE_TYPES = {"Text", "String", "Zahl", "Bool", "Datum", *RECORD_TYPES}
_PATH_RE = re.compile(r"[A-Za-z]\w*(\[\])?(\.[A-Za-z]\w*(\[\])?)*")


def _write_access(template=None):
	if not set(frappe.get_roles()).intersection({"System Manager", "Hausverwalter"}):
		raise AgentToolError("PERMISSION_DENIED", "Keine Berechtigung, KI-Vorlagen anzulegen.")
	if template:
		doc = api._read(api.TEMPLATE, template)
		doc.check_permission("write")
		return doc
	if not frappe.has_permission(api.TEMPLATE, "create"):
		raise frappe.PermissionError


@contextmanager
def _atomic():
	point = "agent_template_authoring"
	frappe.db.savepoint(point)
	try:
		yield
	except Exception:
		frappe.db.rollback(save_point=point)
		raise


def _text(value, field, max_chars=140, required=True):
	if not isinstance(value, str) or len(value) > max_chars or (required and not value.strip()):
		raise AgentToolError(
			"INVALID_ARGUMENT", f"Ungültiger Wert für {field} (maximal {max_chars} Zeichen)."
		)
	return value.strip()


def _variables(raw):
	rows = parse_json_if_needed(raw)
	if rows is None:
		return []
	if not isinstance(rows, list) or len(rows) > 50:
		raise AgentToolError("INVALID_ARGUMENT", "variables muss eine Liste mit höchstens 50 Einträgen sein.")
	out, seen = [], set()
	for row in rows:
		if not isinstance(row, dict) or set(row) - {
			"variable",
			"variable_type",
			"reference_doctype",
			"label",
			"optional",
			"beschreibung",
		}:
			raise AgentToolError("INVALID_ARGUMENT", "Nur deklarierte Variablenfelder sind erlaubt.")
		name = row.get("variable")
		if (
			not isinstance(name, str)
			or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
			or name in seen
			or name
			in {
				"frappe",
				"objekt",
				"doc",
				"baustein",
				"textbaustein",
				"outputs",
				"serienbrief",
				"datum",
				"datum_iso",
				"empfaenger",
				"namespace",
			}
		):
			raise AgentToolError("INVALID_ARGUMENT", "Variablenname ungültig, reserviert oder doppelt.")
		kind = row.get("variable_type", "Text")
		if kind not in _VARIABLE_TYPES or row.get("optional", False) not in (
			True,
			False,
			0,
			1,
		):
			raise AgentToolError("INVALID_ARGUMENT", "Variablentyp oder optional ungültig.")
		reference_doctype = row.get("reference_doctype") or ""
		if (kind in RECORD_TYPES) != bool(reference_doctype) or (
			reference_doctype and reference_doctype not in AI_RECORD_DOCTYPES
		):
			raise AgentToolError(
				"INVALID_ARGUMENT",
				"Doctype-Variablen brauchen reference_doctype aus: " + ", ".join(AI_RECORD_DOCTYPES) + ".",
			)
		seen.add(name)
		out.append(
			{
				"variable": name,
				"variable_type": kind,
				"reference_doctype": reference_doctype or None,
				"label": _text(row.get("label", name), "label"),
				"optional": int(bool(row.get("optional"))),
				"beschreibung": _text(row.get("beschreibung", ""), "beschreibung", 1000, False),
			}
		)
	return out


def _baustein_pfade(raw, doc):
	"""Leitet Eingaben verwendeter Bausteine um, z. B. Briefkopf an einen gewählten Kontakt.

	Pfade beginnen bei ``objekt`` oder einer Doctype-Variable der Vorlage; der Datensatz
	selbst kommt erst beim Vorbereiten als geprüfter Wert hinzu.
	"""
	data = parse_json_if_needed(raw)
	if not data:
		return {}
	if not isinstance(data, dict) or len(data) > 10:
		raise AgentToolError(
			"INVALID_ARGUMENT", "baustein_pfade muss ein Objekt mit höchstens 10 Bausteinen sein."
		)
	core = api._renderer()
	used = set(core._extract_inline_block_names(core._get_template_template_source(doc)))
	roots = {"objekt"} | {
		frappe.scrub(row.variable) for row in doc.get("variables") or [] if row.variable_type in RECORD_TYPES
	}
	out = {}
	for block_name, mapping in data.items():
		if block_name not in used:
			raise AgentToolError(
				"INVALID_ARGUMENT", f"Baustein {block_name} wird im Inhalt nicht per baustein() verwendet."
			)
		if not isinstance(mapping, dict) or not 1 <= len(mapping) <= 20:
			raise AgentToolError(
				"INVALID_ARGUMENT", f"Pfade für {block_name} müssen ein Objekt mit 1 bis 20 Einträgen sein."
			)
		block = core.get_textbaustein(block_name, template=doc)
		inputs = {frappe.scrub(row.variable) for row in block.get("variables") or [] if row.variable}
		clean = {}
		for key, path in mapping.items():
			if key not in inputs:
				raise AgentToolError("INVALID_ARGUMENT", f"Baustein {block_name} hat keine Eingabe {key}.")
			path = path.strip() if isinstance(path, str) else ""
			if len(path) > 200 or not _PATH_RE.fullmatch(path):
				raise AgentToolError("INVALID_ARGUMENT", f"Ungültiger Pfad für {block_name}.{key}.")
			if path.split(".")[0].removesuffix("[]") not in roots:
				raise AgentToolError(
					"INVALID_ARGUMENT",
					f"Pfad für {block_name}.{key} muss bei objekt oder einer Doctype-Variable der Vorlage beginnen.",
				)
			clean[key] = path
		out[block_name] = clean
	return out


def _set_source(doc, content, variables=None, description=None, baustein_pfade=None):
	from mail_merge.mail_merge.utils.assistant_templates import validate_assistant_source

	try:
		validate_assistant_source(content)
	except frappe.ValidationError as exc:
		raise AgentToolError("INVALID_SOURCE", str(exc)) from None
	doc.content_type = "HTML + Jinja"
	doc.html_content = content
	doc.jinja_content = ""
	doc.content = ""
	doc.assistant_created = 1
	if variables is not None:
		doc.set("variables", _variables(variables))
	if description is not None:
		doc.description = _text(description, "description", 4000, False)
	# Only existing blocks may be referenced. Reads honour user permissions.
	api._collect_blocks(doc)
	if baustein_pfade is not None:
		pfade = _baustein_pfade(baustein_pfade, doc)
		doc.inline_baustein_pfade = frappe.as_json(pfade) if pfade else ""


def _result(doc, version, *, proposal):
	return {
		"template": doc.name,
		"vorlagenversion": version.name,
		"version_number": version.version_number,
		"source": version.source,
		"assistant_created": True,
		"is_proposal": proposal,
		"based_on": version.get("based_on"),
		"live_template_changed": not proposal,
		"revision": f"version:{version.name}" if proposal else api._template(doc.name)[2],
		"url": f"/app/serienbrief-vorlage/{doc.name}",
		"warnings": layout_warnings(doc.html_content),
	}


@frappe.whitelist(methods=["POST"])
@api._endpoint
def create_template(
	title, category, recipient_doctype, content, variables=None, description=None, baustein_pfade=None
):
	_write_access()
	title = _text(title, "title")
	category = _text(category, "category", 240)
	recipient_doctype = _text(recipient_doctype, "recipient_doctype", 140)
	api._read("Serienbrief Kategorie", category)
	api._read("DocType", recipient_doctype)
	if not frappe.has_permission(recipient_doctype, "read"):
		raise frappe.PermissionError
	if frappe.db.exists(api.TEMPLATE, title):
		raise AgentToolError(
			"TEMPLATE_EXISTS", "Titel existiert bereits. Für Änderungen einen KI-Vorschlag anlegen."
		)
	with _atomic():
		doc = frappe.get_doc(
			{
				"doctype": api.TEMPLATE,
				"title": title,
				"kategorie": category,
				"haupt_verteil_objekt": recipient_doctype,
			}
		)
		_set_source(doc, content, variables if variables is not None else [], description, baustein_pfade)
		doc.flags.version_source = "KI-Erstellung"
		doc.flags.version_label = "Vom Assistenten erstellt"
		doc.insert()
		from mail_merge.mail_merge.doctype.serienbrief_vorlage.serienbrief_vorlage import (
			TEMPLATE_VERSION_SPEC,
		)
		from mail_merge.mail_merge.utils import versioning

		version = versioning.latest_version(TEMPLATE_VERSION_SPEC, doc.name)
		if not version:
			raise AgentToolError("NOT_READY", "Versionshistorie fehlt; zuerst migrieren.")
		return _result(doc, version, proposal=False)


@frappe.whitelist(methods=["POST"])
@api._endpoint
def propose_template_version(
	template,
	revision,
	content,
	base_version=None,
	variables=None,
	description=None,
	label=None,
	baustein_pfade=None,
):
	live = _write_access(template)
	from mail_merge.mail_merge.doctype.serienbrief_vorlage.serienbrief_vorlage import TEMPLATE_VERSION_SPEC
	from mail_merge.mail_merge.utils import versioning
	from mail_merge.mail_merge.utils.textbaustein_versions import template_at_version

	with _atomic():
		frappe.db.sql("select name from `tabSerienbrief Vorlage` where name=%s for update", live.name)
		live, _, current_revision = api._template(live.name)
		if revision != current_revision:
			raise AgentToolError(
				"TEMPLATE_CHANGED",
				"revision passt nicht zum aktiven Stand: den Wert revision aus get_template (ohne vorlagenversion) "
				"verwenden, keine Versions-ID und keinen content_hash. Bei Änderungen durch andere neu lesen.",
			)
		base_version = base_version or versioning.ensure_current_version(TEMPLATE_VERSION_SPEC, live)
		if not base_version:
			raise AgentToolError("NOT_READY", "Versionshistorie fehlt; zuerst migrieren.")
		try:
			versioning.require_version(TEMPLATE_VERSION_SPEC, base_version, live.name)
		except frappe.ValidationError as exc:
			raise AgentToolError(
				"INVALID_ARGUMENT",
				f"{exc} base_version ist eine Versions-ID (name) aus list_template_versions; "
				"weglassen, um auf dem aktiven Stand aufzubauen.",
			) from None
		candidate = template_at_version(live.name, base_version)
		_set_source(candidate, content, variables, description, baustein_pfade)
		# Candidate references keep the baseline block snapshots; new references
		# resolve to existing readable blocks and are frozen by the new bill.
		version_name = versioning.create_version(
			TEMPLATE_VERSION_SPEC,
			candidate,
			source="KI-Vorschlag",
			label=_text(label or "KI-Vorschlag", "label"),
			based_on=base_version,
			force=True,
		)
		if not version_name:
			raise AgentToolError("NOT_READY", "Versionshistorie fehlt; zuerst migrieren.")
		version = frappe.get_doc(TEMPLATE_VERSION_SPEC.version_doctype, version_name)
		return _result(candidate, version, proposal=True)


@frappe.whitelist()
@api._endpoint
def list_template_versions(template):
	doc = api._read(api.TEMPLATE, template)
	from mail_merge.mail_merge.doctype.serienbrief_vorlage.serienbrief_vorlage import get_editor_versions

	return get_editor_versions(doc.name)
