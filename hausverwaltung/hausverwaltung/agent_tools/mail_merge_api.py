"""Bounded agent workflow for saved templates: inspect, prepare, persist draft PDFs.

Preparation freezes the actual PDF bytes for 30 minutes in the site Redis cache.
Execution consumes that user-bound snapshot, never arbitrary HTML or Jinja. It is
a transaction boundary: the draft and its private attachments commit together.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
import time
import uuid
from datetime import date
from functools import wraps
from io import BytesIO
from urllib.parse import urlencode

import frappe
from frappe.utils import now_datetime, nowdate

from hausverwaltung.hausverwaltung.agent_tools import read_api
from hausverwaltung.hausverwaltung.agent_tools.contracts import (
	AgentToolError,
	normalize_limit,
	normalize_offset,
	parse_json_if_needed,
)
from hausverwaltung.hausverwaltung.agent_tools.mail_merge_contract import (
	JSON_TYPES,
	MailMergeError,
	input_description,
	input_issue,
	missing_inputs,
	plain_text,
	render_error,
)

TEMPLATE = "Serienbrief Vorlage"
RUN = "Serienbrief Durchlauf"
DOCUMENT = "Serienbrief Dokument"
MAX_RECIPIENTS = 10
PREPARATION_TTL = 1800
MAX_PDF_BYTES = 10 * 1024 * 1024
API_PATH = "hausverwaltung.hausverwaltung.agent_tools.mail_merge_api"


def _endpoint(fn):
	@wraps(fn)
	def wrapped(*args, **kwargs):
		started = time.perf_counter()
		request_id = uuid.uuid4().hex
		try:
			_access()
			result = read_api._ok(request_id, started, fn(*args, **kwargs))
		except AgentToolError as exc:
			result = read_api._error(request_id, started, exc.code, exc.message)
			result["error"].update(getattr(exc, "details", {}))
		except frappe.PermissionError:
			result = read_api._error(request_id, started, "PERMISSION_DENIED", "Berechtigung fehlt.")
		except frappe.DoesNotExistError:
			result = read_api._error(request_id, started, "NOT_FOUND", "Datensatz nicht verfügbar.")
		except Exception:
			frappe.log_error(title="Agent Serienbrief", message=frappe.get_traceback())
			result = read_api._error(
				request_id, started, "INTERNAL_ERROR", "Serienbrief-Aktion fehlgeschlagen."
			)
		read_api._finalize_log(
			tool=fn.__name__,
			request_id=request_id,
			started_at=started,
			success=result["ok"],
			error_code=(result.get("error") or {}).get("code"),
		)
		return result

	return wrapped


def _access(*, write=False):
	roles = set(frappe.get_roles())
	allowed = {"System Manager", "Hausverwalter"}
	if not write:
		allowed.add("Agent Readonly API")
	if frappe.session.user == "Guest" or not roles.intersection(allowed):
		raise AgentToolError("PERMISSION_DENIED", "Keine Berechtigung für diese Serienbrief-Aktion.")
	if write:
		for doctype in (RUN, DOCUMENT):
			for permission in ("create", "read", "write"):
				if not frappe.has_permission(doctype, permission):
					raise AgentToolError(
						"PERMISSION_DENIED", f"{permission}-Berechtigung für {doctype} fehlt."
					)


def _read(doctype, name):
	if not isinstance(name, str) or not name.strip() or len(name) > 240:
		raise AgentToolError("INVALID_ARGUMENT", "Ein exakter Datensatzname ist erforderlich.")
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return doc


def _renderer():
	from mail_merge.mail_merge.doctype.serienbrief_durchlauf import serienbrief_durchlauf

	return serienbrief_durchlauf


def _digest(value):
	return hashlib.sha256(
		json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
	).hexdigest()


def _content_warnings(text):
	"""Flag editorial findings without guessing new dates or changing wording."""
	warnings = []
	dates = sorted(set(re.findall(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\b", text)))
	if dates:
		warnings.append(
			{
				"code": "FIXED_DATES",
				"message": "Enthält feste Datumsangaben; fachlich prüfen.",
				"dates": dates,
			}
		)
	if re.search(r"[.\u2026_]{5,}|falls n[oö]tig", text, re.IGNORECASE):
		warnings.append(
			{
				"code": "MANUAL_CONTENT",
				"message": "Enthält mögliche Ausfüllstellen oder Bearbeitungshinweise; vor Verwendung prüfen.",
			}
		)
	return warnings


def _template(template):
	doc = _read(TEMPLATE, template)
	core = _renderer()
	blocks = []
	seen = set()
	queue = [r.baustein for r in doc.get("textbausteine") or [] if r.baustein]
	source = core._get_template_template_source(doc)
	queue.extend(core._extract_inline_block_names(source))
	while queue:
		name = queue.pop(0)
		if name in seen:
			continue
		seen.add(name)
		if len(seen) > 100:
			raise AgentToolError("TEMPLATE_INVALID", "Zu viele verknüpfte Textbausteine.")
		block = _read("Serienbrief Textbaustein", name)
		blocks.append(block)
		queue.extend(core._extract_inline_block_names(core._get_textbaustein_template_source(block)))
	return doc, blocks, _digest([doc.as_dict(), *[b.as_dict() for b in blocks]])


def _inputs(template):
	from mail_merge.mail_merge.utils.render_inputs import input_fields
	return [{"key": field["name"], "path": field["path"], "label": field["label"], "type": field["type"], "optional": not field["required"], "description": field["description"], "fillable": True, "default": field["default"]} for field in input_fields(template)]


def _values(raw, fields, *, recipient=None):
	values = parse_json_if_needed(raw)
	if values is None:
		values = {}
	if not isinstance(values, dict):
		raise AgentToolError("INVALID_ARGUMENT", "values muss ein Objekt sein.")
	allowed = {f["key"]: f for f in fields if f["fillable"]}
	out = {}
	for key, value in values.items():
		if key not in allowed:
			raise MailMergeError(
				"INVALID_INPUT",
				f"Eingabe nicht freigegeben: {key}.",
				issues=[input_issue(key)],
				action="correct_inputs",
				recipient=recipient,
			)
		field = allowed[key]
		kind = field["type"]
		valid = value is not None
		if kind == "Bool":
			valid = type(value) is bool
		elif kind == "Zahl":
			valid = type(value) in (int, float) and math.isfinite(value)
		elif kind == "Datum":
			try:
				valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
			except ValueError:
				valid = False
		else:
			valid = isinstance(value, str) and len(value) <= 4000
		if not valid or (isinstance(value, str) and not value.strip() and not field["optional"]):
			raise MailMergeError(
				"INVALID_INPUT",
				f"Ungültiger Wert für {key} ({kind}).",
				issues=[
					input_issue(
						key, expected_type=JSON_TYPES[kind], format="YYYY-MM-DD" if kind == "Datum" else None
					)
				],
				action="correct_inputs",
				recipient=recipient,
			)
		if isinstance(value, str):
			# The renderer preprocesses path tokens before Jinja evaluation. Reject
			# template syntax even when HTML-encoded; escape text for HTML attributes.
			decoded = html.unescape(value)
			if re.search(r"\{[\{%#]|[<>]", decoded):
				raise MailMergeError(
					"INVALID_INPUT",
					f"{key} darf nur Text ohne HTML/Jinja enthalten.",
					issues=[input_issue(key, expected_type="string")],
					action="correct_inputs",
					recipient=recipient,
				)
			value = html.escape(value, quote=True)
		out[key] = {"value": value}
	return out


def _targets(template, recipients):
	names = parse_json_if_needed(recipients)
	if not isinstance(names, list) or not 1 <= len(names) <= MAX_RECIPIENTS:
		raise AgentToolError("INVALID_ARGUMENT", f"Bitte 1 bis {MAX_RECIPIENTS} exakte Empfänger angeben.")
	if any(not isinstance(n, str) for n in names) or len(set(names)) != len(names):
		raise AgentToolError("INVALID_ARGUMENT", "Empfängernamen müssen eindeutig sein.")
	docs = [_read(template.haupt_verteil_objekt, name) for name in names]
	return docs


def _cache_key(token):
	if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
		raise AgentToolError("INVALID_ARGUMENT", "Ungültiges Vorbereitungstoken.")
	return f"agent-mail-merge:{frappe.session.user}:{token}"


def _prepared(token):
	data = frappe.cache.get_value(_cache_key(token))
	if not data or data["expires_at"] <= time.time():
		raise AgentToolError("PREPARATION_EXPIRED", "Vorschau abgelaufen; bitte erneut vorbereiten.")
	if data["owner"] != frappe.session.user:
		raise AgentToolError("PERMISSION_DENIED", "Vorschau gehört einem anderen Benutzer.")
	return data


@frappe.whitelist()
@_endpoint
def list_templates(query=None, limit=20, offset=0):
	limit, offset = normalize_limit(limit), normalize_offset(offset)
	if query is not None and (not isinstance(query, str) or len(query) > 140):
		raise AgentToolError("INVALID_ARGUMENT", "Ungültiger Suchbegriff.")
	filters = {}
	if query:
		filters["title"] = ["like", f"%{query}%"]
	rows = frappe.get_list(
		TEMPLATE,
		filters=filters,
		fields=["name", "title", "haupt_verteil_objekt", "modified"],
		order_by="modified desc, name asc",
		limit_start=offset,
		limit_page_length=limit + 1,
	)
	return {
		"templates": rows[:limit],
		"has_more": len(rows) > limit,
		"next_offset": offset + limit,
		"max_recipients": MAX_RECIPIENTS,
	}


@frappe.whitelist()
@_endpoint
def get_template(template, include_source=False):
	if include_source not in (True, False, 0, 1, "0", "1", "true", "false"):
		raise AgentToolError("INVALID_ARGUMENT", "include_source muss true oder false sein.")
	include_source = include_source in (True, 1, "1", "true")
	doc, blocks, revision = _template(template)
	core = _renderer()
	source = core._get_template_template_source(doc)
	block_sources = [core._get_textbaustein_template_source(b) for b in blocks]
	description, purpose_truncated = plain_text(doc.get("description") or "", 600)
	excerpt, excerpt_truncated = plain_text(source, 900)
	fields = [input_description(field) for field in _inputs(doc)]
	result = {
		"name": doc.name,
		"title": doc.title,
		"purpose": description or doc.title,
		"purpose_source": "description" if description else "title",
		"purpose_truncated": purpose_truncated,
		"category": doc.kategorie,
		"revision": revision,
		"recipient_doctype": doc.haupt_verteil_objekt,
		"inputs": fields,
		"required_inputs": [f["key"] for f in fields if f["fillable"] and f["required"]],
		"examples_are_illustrative": True,
		"content_excerpt": excerpt,
		"excerpt_truncated": excerpt_truncated,
		"excerpt_is_unrendered": True,
		"source_included": include_source,
		"warnings": _content_warnings("\n".join([source, *block_sources])),
		"blocks": [{"name": b.name, "title": b.title or b.name} for b in blocks],
		"can_execute": bool(set(frappe.get_roles()).intersection({"System Manager", "Hausverwalter"}))
		and all(frappe.has_permission(dt, p) for dt in (RUN, DOCUMENT) for p in ("create", "read", "write")),
		"policy": "Nur bestehende Vorlage, deklarierte Eingaben und explizite Empfänger; Speicherung als Entwurf.",
	}
	if include_source:
		result["source"] = source
		for block, block_source in zip(result["blocks"], block_sources, strict=True):
			block["source"] = block_source
	return result


@frappe.whitelist(methods=["POST"])
@_endpoint
def prepare(template, revision, recipients, values=None, per_recipient=None, letter_date=None):
	doc, blocks, current_revision = _template(template)
	if revision != current_revision:
		raise AgentToolError("TEMPLATE_CHANGED", "Vorlage geändert; bitte erneut lesen.")
	core = _renderer()
	sources = [
		core._get_template_template_source(doc),
		*[core._get_textbaustein_template_source(b) for b in blocks],
	]
	targets = _targets(doc, recipients)
	fields = _inputs(doc)
	common = _values(values, fields)
	per = parse_json_if_needed(per_recipient)
	if per is None:
		per = {}
	if not isinstance(per, dict) or set(per) - {t.name for t in targets}:
		raise AgentToolError("INVALID_INPUT", "Empfängerwerte gehören nicht zur Auswahl.")
	individual = {name: _values(v, fields, recipient=name) for name, v in per.items()}
	letter_date = letter_date or nowdate()
	try:
		if date.fromisoformat(letter_date).isoformat() != letter_date:
			raise ValueError
	except (ValueError, TypeError):
		raise MailMergeError(
			"INVALID_INPUT",
			"Briefdatum muss YYYY-MM-DD sein.",
			issues=[input_issue("letter_date", expected_type="string", format="YYYY-MM-DD")],
			action="correct_inputs",
		)
	token = uuid.uuid4().hex
	run_name = "SBDL-LLM-" + token
	run_data = {
		"doctype": RUN,
		"name": run_name,
		"title": doc.title,
		"vorlage": doc.name,
		"kategorie": doc.kategorie,
		"date": letter_date,
		"iteration_doctype": doc.haupt_verteil_objekt,
		"status": "Läuft",
		"variablen_werte": json.dumps(common),
		"iteration_objekte": [
			{
				"objekt": t.name,
				"iteration_doctype": t.doctype,
				"variablen_werte": json.dumps(individual.get(t.name, {})),
			}
			for t in targets
		],
	}
	run = frappe.get_doc(run_data)
	rows = run._get_iteration_rows()
	if len(rows) != len(targets):
		raise AgentToolError("NOT_FOUND", "Nicht alle Empfänger konnten geladen werden.")
	outputs, errors = [], []
	for index, row in enumerate(rows, 1):
		try:
			# Report all missing fillable fields before the core's generic variable
			# error; retain its strict check for every other declared variable.
			context = run._build_context(row, index, template=doc, total=len(rows), strict_variables=False)
			missing = [
				f
				for f in fields
				if f["fillable"]
				and not f["optional"]
				and (
					core._resolve_value_path(f["key"], context) is None
					or (isinstance(core._resolve_value_path(f["key"], context), str) and not core._resolve_value_path(f["key"], context).strip())
				)
			]
			if missing:
				raise missing_inputs(missing)
			run._verify_template_variables_resolved(context, doc)
			segments = run._render_template_content(doc, context)
			if not segments:
				raise AgentToolError("EMPTY_DOCUMENT", "Vorlage liefert keinen Inhalt.")
			page_html = run._wrap_html_fragment("\n".join(run._render_segments_preview_pages(segments)))
			footer = frappe._dict(
				vorlage=doc.name,
				iteration_doctype=doc.haupt_verteil_objekt,
				objekt=row.iteration_objekt,
				date=letter_date,
				variablen_werte=json.dumps({**common, **individual.get(row.iteration_objekt, {})}),
			)
			pdf = run._render_segments_pdf_bytes(segments, footer_doc=footer)
			from pypdf import PdfReader

			reader = PdfReader(BytesIO(pdf))
			text = "\n".join(page.extract_text() or "" for page in reader.pages)
			if not reader.pages or re.search(r"«[^»\n]{1,160}»|\{\{|\{%", text):
				raise AgentToolError(
					"UNRESOLVED_PLACEHOLDER", "PDF ist leer oder enthält nicht aufgelöste Platzhalter."
				)
			outputs.append(
				{
					"recipient": row.iteration_objekt,
					"recipient_email": run._resolve_recipient_email(row) or "",
					"values": json.dumps({**common, **individual.get(row.iteration_objekt, {})}),
					"pdf": base64.b64encode(pdf).decode(),
					"pdf_sha256": hashlib.sha256(pdf).hexdigest(),
					"html": page_html,
					"text": text,
					"pages": len(reader.pages),
				}
			)
		except Exception as exc:
			errors.append(
				render_error(exc, recipient=row.iteration_objekt, recipient_doctype=doc.haupt_verteil_objekt)
			)
	if errors:
		return {"ready": False, "errors": errors, "checked": len(rows), "prepared": len(outputs)}
	if sum(len(o["pdf"]) for o in outputs) > MAX_PDF_BYTES * 4 // 3:
		raise AgentToolError("LIMIT_EXCEEDED", "PDFs sind zu groß; bitte Empfängerauswahl verkleinern.")
	payload = {
		"owner": frappe.session.user,
		"expires_at": time.time() + PREPARATION_TTL,
		"revision": revision,
		"run": run_data,
		"outputs": outputs,
		"targets": {t.name: str(t.modified) for t in targets},
	}
	frappe.cache.set_value(_cache_key(token), payload, expires_in_sec=PREPARATION_TTL)
	return {
		"ready": True,
		"preparation_token": token,
		"expires_in_seconds": PREPARATION_TTL,
		"template": doc.name,
		"date": letter_date,
		"recipient_doctype": doc.haupt_verteil_objekt,
		"previews": [
			{
				"recipient": o["recipient"],
				"pages": o["pages"],
				"text": o["text"],
				"warnings": _content_warnings("\n".join(sources)),
				"pdf_sha256": o["pdf_sha256"],
				"pdf_url": f"/api/method/{API_PATH}.preview_pdf?"
				+ urlencode({"token": token, "recipient": o["recipient"]}),
			}
			for o in outputs
		],
	}


def _recheck(payload):
	doc, _, revision = _template(payload["run"]["vorlage"])
	if revision != payload["revision"]:
		raise AgentToolError("TEMPLATE_CHANGED", "Vorlage geändert; bitte erneut vorbereiten.")
	targets = _targets(doc, list(payload["targets"]))
	if any(str(t.modified) != payload["targets"][t.name] for t in targets):
		raise AgentToolError("RECIPIENT_CHANGED", "Empfängerdaten geändert; bitte erneut vorbereiten.")


@frappe.whitelist()
def preview_pdf(token, recipient):
	_access()
	payload = _prepared(token)
	_recheck(payload)
	output = next((o for o in payload["outputs"] if o["recipient"] == recipient), None)
	if not output:
		raise frappe.DoesNotExistError
	frappe.local.response.filename = "serienbrief-vorschau.pdf"
	frappe.local.response.filecontent = base64.b64decode(output["pdf"])
	frappe.local.response.type = "pdf"


def _pdf_filename(label):
	stem = re.sub(r"[^0-9A-Za-zÄÖÜäöüß._-]+", "_", str(label or "")).strip("._")[:120] or "serienbrief"
	return f"{stem}.pdf"


def _pdf_payload(content, label, source):
	if len(content) > MAX_PDF_BYTES:
		raise AgentToolError("LIMIT_EXCEEDED", "PDF ist zu groß für die Übergabe.")
	return {
		"source": source,
		"filename": _pdf_filename(label),
		"mime_type": "application/pdf",
		"size_bytes": len(content),
		"sha256": hashlib.sha256(content).hexdigest(),
		"content_base64": base64.b64encode(content).decode(),
	}


@_endpoint
def get_pdf(preparation_token=None, recipient=None, document=None):
	"""PDF bytes for code callers: a prepared preview (token + recipient) or a stored draft document.

	Deliberately not a model-facing tool of the built-in assistant; the base64 payload belongs in a
	sandbox file, not in a model context.
	"""
	if bool(document) == bool(preparation_token):
		raise AgentToolError(
			"INVALID_ARGUMENT", "Entweder preparation_token mit recipient oder document angeben."
		)
	if document:
		doc = _read(DOCUMENT, document)
		file_url = doc.generated_pdf_file
		if not file_url:
			raise AgentToolError("NOT_FOUND", "Für dieses Serienbrief-Dokument ist kein PDF gespeichert.")
		file_name = frappe.db.get_value(
			"File", {"file_url": file_url, "attached_to_doctype": DOCUMENT, "attached_to_name": doc.name}
		)
		if not file_name:
			raise AgentToolError("NOT_FOUND", "PDF-Datei des Serienbrief-Dokuments nicht gefunden.")
		content = frappe.get_doc("File", file_name).get_content()
		if isinstance(content, str):
			content = content.encode("latin-1")
		return _pdf_payload(content, f"{doc.name}", "document")
	payload = _prepared(preparation_token)
	_recheck(payload)
	output = next((o for o in payload["outputs"] if o["recipient"] == recipient), None)
	if not output:
		raise AgentToolError("NOT_FOUND", "Empfänger ist nicht Teil dieser Vorschau.")
	return _pdf_payload(base64.b64decode(output["pdf"]), f"Vorschau_{recipient}", "preview")


def _status(run):
	doc = _read(RUN, run)
	names = frappe.get_all(DOCUMENT, filters={"durchlauf": run}, pluck="name", order_by="creation asc")
	documents = [_read(DOCUMENT, name) for name in names]
	return {
		"run": doc.name,
		"url": f"/app/serienbrief-durchlauf/{doc.name}",
		"docstatus": doc.docstatus,
		"status": doc.status,
		"documents": [
			{
				"name": d.name,
				"recipient": d.objekt,
				"status": d.status,
				"pdf_url": d.generated_pdf_file,
				"pages": d.pages,
				"error": d.get("error_msg") or "",
			}
			for d in documents
		],
	}


@frappe.whitelist()
@_endpoint
def get_status(run):
	return _status(run)


@frappe.whitelist(methods=["POST"])
@_endpoint
def execute(preparation_token):
	_access(write=True)
	key = _cache_key(preparation_token)
	# Hold through commit. A retry after response loss finds the deterministic
	# run name, even if writing the cache receipt failed after the DB commit.
	with frappe.cache.lock(key + ":execute", timeout=120, blocking_timeout=5):
		payload = _prepared(preparation_token)
		run_name = payload["run"]["name"]
		if payload.get("executed") or frappe.db.exists(RUN, run_name):
			run = _read(RUN, run_name)
			if run.owner != frappe.session.user:
				raise AgentToolError("PERMISSION_DENIED", "Durchlauf gehört einem anderen Benutzer.")
			return {**_status(run_name), "reused": True}
		_recheck(payload)
		try:
			# Läuft suppresses the core's on_update auto-render. Persist precisely
			# the already inspected PDFs, without regenerating, submitting or sending.
			run = frappe.get_doc(payload["run"])
			run.insert(set_name=run_name)
			for output in payload["outputs"]:
				document = frappe.get_doc(
					{
						"doctype": DOCUMENT,
						"durchlauf": run.name,
						"vorlage": run.vorlage,
						"kategorie": run.kategorie,
						"date": run.date,
						"iteration_doctype": run.iteration_doctype,
						"objekt": output["recipient"],
						"title": run.title,
						"recipient_email": output["recipient_email"],
						"variablen_werte": output["values"],
						"html": output["html"],
						"status": "Generiert",
						"pages": output["pages"],
					}
				)
				document.insert()
				file_doc = frappe.get_doc(
					{
						"doctype": "File",
						"file_name": f"{document.name}.pdf",
						"is_private": 1,
						"attached_to_doctype": DOCUMENT,
						"attached_to_name": document.name,
						"content": base64.b64decode(output["pdf"]),
					}
				)
				# The attachment inherits the checked document's permissions.
				file_doc.insert(ignore_permissions=True)
				document.db_set("generated_pdf_file", file_doc.file_url, update_modified=False)
			run.db_set(
				{
					"status": "Generiert",
					"last_run_on": now_datetime(),
					"progress": f"{len(payload['outputs'])}/{len(payload['outputs'])}",
					"run_summary": json.dumps(
						{
							"generated": len(payload["outputs"]),
							"error": 0,
							"agent": {
								"revision": payload["revision"],
								"prepared_by": payload["owner"],
								"pdf_sha256": {o["recipient"]: o["pdf_sha256"] for o in payload["outputs"]},
							},
						}
					),
				}
			)
			result = _status(run.name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			raise
		payload["executed"] = True
		frappe.cache.set_value(key, payload, expires_in_sec=max(1, int(payload["expires_at"] - time.time())))
		return {**result, "reused": False}
