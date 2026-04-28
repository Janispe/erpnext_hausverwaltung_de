from __future__ import annotations

import hashlib
import imaplib
import json
import mimetypes
import os
import re
import subprocess
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from html import escape
from typing import Iterable
from urllib.parse import urljoin

import frappe
import requests
from frappe import _
from frappe.utils import get_datetime, now_datetime, strip_html
from frappe.utils.file_manager import get_file, save_file
from frappe.utils.password import get_decrypted_password

LOGGER_TITLE = "Paperless NGX Export"
LOG_DOCTYPE = "Paperless Export Log"
PAPERLESS_TAG_EMAIL_SLUG = "email"
PAPERLESS_TAG_ATTACHMENT_SLUG = "anhang"
PAPERLESS_CUSTOM_FIELD_LINK_NAME = "Email oder Anhang"
PAPERLESS_CUSTOM_FIELD_LINK_SLUG = "email_oder_anhang"


@dataclass
class PaperlessConfig:
	"""Configuration container for Paperless NGX exports."""

	url: str
	token: str
	correspondent_id: int | None
	document_type_id: int | None
	tag_ids: list[int]
	tag_email_id: int | None
	tag_attachment_id: int | None
	custom_field_link_id: int | None
	timeout: int
	verify_ssl: bool

	@classmethod
	def from_conf(cls) -> "PaperlessConfig | None":
		conf = getattr(frappe, "conf", {}) or {}
		url = (conf.get("paperless_ngx_url") or "").rstrip("/")
		token = conf.get("paperless_ngx_token")
		if not url or not token:
			return None

		return cls(
			url=url,
			token=token,
			correspondent_id=_to_int(conf.get("paperless_ngx_correspondent_id")),
			document_type_id=_to_int(conf.get("paperless_ngx_document_type_id")),
			tag_ids=_to_int_list(conf.get("paperless_ngx_tag_ids")),
			tag_email_id=_to_int(conf.get("paperless_ngx_tag_email_id")),
			tag_attachment_id=_to_int(conf.get("paperless_ngx_tag_attachment_id")),
			custom_field_link_id=_to_int(conf.get("paperless_ngx_custom_field_link_id")),
			timeout=_to_int(conf.get("paperless_ngx_timeout")) or 20,
			verify_ssl=_to_bool(conf.get("paperless_ngx_verify_ssl", True)),
		)


@dataclass
class PaperlessUpload:
	"""Track a single file destined for Paperless while we resolve its document ID."""

	file_name: str
	content: bytes
	checksum: str
	is_email: bool = False
	paperless_id: int | None = None
	task_id: str | None = None


def enqueue_paperless_export(doc, method: str | None = None) -> None:
	"""Hook: enqueue export of new incoming Communications to Paperless NGX."""
	if not _is_incoming_email(doc):
		return

	if not PaperlessConfig.from_conf():
		# Paperless NGX not configured on this site
		return

	# Attach a .eml once on insert so we keep the original-ish mail around for later exports.
	_attach_eml_if_missing(doc)

	_ensure_log_entry(doc.name, status="Pending")

	frappe.enqueue(
		"hausverwaltung.hausverwaltung.integrations.paperless.export_communication",
		queue="long",
		communication_name=doc.name,
		enqueue_after_commit=True,
	)


@frappe.whitelist()
def trigger_manual_paperless_export(communication: str) -> str:
	"""Manual trigger to export a Communication to Paperless via a UI button."""
	config = PaperlessConfig.from_conf()
	if not config:
		frappe.throw(_("Paperless NGX ist nicht konfiguriert."))

	try:
		doc = frappe.get_doc("Communication", communication)
	except Exception:
		frappe.throw(_("Kommunikation konnte nicht geladen werden."))

	if not _is_incoming_email(doc):
		frappe.throw(_("Nur eingehende E-Mails können exportiert werden."))

	_ensure_log_entry(doc.name, status="Pending")
	frappe.enqueue(
		"hausverwaltung.hausverwaltung.integrations.paperless.export_communication",
		queue="long",
		communication_name=doc.name,
		enqueue_after_commit=False,
	)
	return _("Export nach Paperless wurde gestartet.")


@frappe.whitelist()
def get_paperless_link(communication: str) -> dict:
	"""Return the most recent Paperless link for a Communication together with export status."""
	result: dict[str, str | None] = {"link": None, "status": None, "last_error": None}
	if not communication:
		return result

	# Prefer the dedicated link file that is attached during export.
	file_rows = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Communication",
			"attached_to_name": communication,
			# be tolerant if the filename differs or multiple link files exist
			"file_name": ("like", "%Paperless%"),
		},
		fields=["file_url"],
		order_by="creation desc",
		limit=1,
	)
	if file_rows and file_rows[0].file_url:
		result["link"] = file_rows[0].file_url
		return result

	# Fallback: parse the timeline comment created by _add_paperless_link.
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Communication",
			"reference_name": communication,
			"comment_type": "Info",
			"content": ("like", "%Paperless%"),
		},
		fields=["content"],
		order_by="creation desc",
		limit=5,
	)
	for row in comments:
		href = _extract_first_href(row.content)
		if href:
			result["link"] = href
			return result

	# Last resort: surface the current export status so the UI can tell the user what's happening.
	log = frappe.db.get_value(
		LOG_DOCTYPE,
		communication,
		["status", "last_error"],
		as_dict=True,
	)
	if log:
		result["status"] = log.get("status")
		result["last_error"] = log.get("last_error")

	return result


@frappe.whitelist()
def export_attachment_to_paperless_whitelisted(
	doctype: str, docname: str, file_url: str, title: str | None = None, tag_names_json: str | None = None
) -> dict:
	"""Whitelisted wrapper for generic attachment export."""
	tag_names: list[str] = []
	if tag_names_json:
		try:
			raw = json.loads(tag_names_json)
			if isinstance(raw, list):
				tag_names = [str(v).strip() for v in raw if str(v or "").strip()]
		except Exception:
			tag_names = []

	return export_attachment_to_paperless(
		doctype=doctype,
		docname=docname,
		file_url=file_url,
		title=title,
		tag_names=tag_names,
	)


def export_attachment_to_paperless(
	*,
	doctype: str,
	docname: str,
	file_url: str,
	title: str | None = None,
	tag_names: list[str] | None = None,
) -> dict:
	"""Export a file attachment to Paperless and return IDs/links."""
	config = PaperlessConfig.from_conf()
	if not config:
		frappe.throw(_("Paperless NGX ist nicht konfiguriert."))

	if not doctype or not docname:
		frappe.throw(_("Doctype und Docname sind erforderlich."))
	if not file_url:
		frappe.throw(_("Datei-URL fehlt."))

	doc = frappe.get_doc(doctype, docname)
	file_name, content = get_file(file_url)
	file_name = _sanitize_filename(file_name or os.path.basename(file_url) or f"{docname}.bin")
	content_bytes = _ensure_bytes(content)
	checksum = _checksum(content_bytes)

	extra_tag_ids = _ensure_tag_ids(config, tag_names or [])
	placeholder_doc = frappe._dict(
		{
			"name": doc.name,
			"subject": title or f"{doctype} {docname}",
			"creation": getattr(doc, "creation", None) or now_datetime(),
			"communication_date": getattr(doc, "modified", None) or now_datetime(),
		}
	)

	ok, paperless_id, task_id = _post_to_paperless(
		config,
		placeholder_doc,
		file_name=file_name,
		file_content=content_bytes,
		extra_tag_ids=extra_tag_ids or None,
		title=title or file_name,
	)
	if not ok:
		frappe.throw(_("Export nach Paperless fehlgeschlagen."))

	if not paperless_id:
		upload = PaperlessUpload(file_name=file_name, content=content_bytes, checksum=checksum)
		upload.task_id = task_id
		resolved = _resolve_paperless_ids(config, [upload], now_datetime())
		if not resolved or not upload.paperless_id:
			frappe.throw(_("Paperless-Dokument-ID konnte nicht aufgeloest werden."))
		paperless_id = upload.paperless_id

	conf = getattr(frappe, "conf", {}) or {}
	base_url = conf.get("paperless_ngx_public_url") or conf.get("paperless_ngx_url") or config.url
	link = _paperless_doc_link(base_url, paperless_id)
	return {
		"ok": True,
		"paperless_id": paperless_id,
		"task_id": task_id,
		"link": link,
		"file_name": file_name,
	}


def export_communication(communication_name: str) -> None:
	"""Load a Communication and push its attachments (or body) to Paperless NGX."""
	config = PaperlessConfig.from_conf()
	if not config:
		_mark_log(communication_name, status="Failed", error="Paperless NGX nicht konfiguriert")
		return

	try:
		doc = frappe.get_doc("Communication", communication_name)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Kommunikation {communication_name} konnte nicht geladen werden.",
		)
		_mark_log(communication_name, status="Failed", error="Kommunikation konnte nicht geladen werden")
		return

	if not _is_incoming_email(doc):
		_mark_log(communication_name, status="Failed", error="Keine eingehende E-Mail")
		return

	_mark_log(doc.name, status="Pending")

	attachments = list(_collect_attachments(doc.name))
	eml, attachments = _pop_original_eml(attachments)
	if not eml:
		eml = _build_eml(doc, attachments)
	if not eml:
		_mark_log(doc.name, status="Failed", error="EML konnte nicht erzeugt werden")
		return

	# Resolve custom field IDs (either from config or by querying Paperless).
	try:
		custom_fields_cache = _fetch_custom_fields(config)
		custom_field_link_id = _ensure_custom_field(
			config,
			name=PAPERLESS_CUSTOM_FIELD_LINK_NAME,
			slug=PAPERLESS_CUSTOM_FIELD_LINK_SLUG,
			desired_type="documentlink",
			fields_cache=custom_fields_cache,
			existing_id=config.custom_field_link_id,
		)
	except Exception:
		_mark_log(doc.name, status="Failed", error="Paperless Custom Fields konnten nicht geladen werden")
		raise

	if not custom_field_link_id:
		_mark_log(doc.name, status="Failed", error="Paperless Custom Field ID fehlt (Email oder Anhang)")
		return

	# Resolve / create tag IDs if missing.
	try:
		tag_email_id = config.tag_email_id
		tag_attachment_id = config.tag_attachment_id
		if not (tag_email_id and tag_attachment_id):
			tags_cache = _fetch_tags(config)
			tag_email_id = tag_email_id or _resolve_tag_id(tags_cache, PAPERLESS_TAG_EMAIL_SLUG)
			tag_attachment_id = tag_attachment_id or _resolve_tag_id(tags_cache, PAPERLESS_TAG_ATTACHMENT_SLUG)
		if not tag_email_id:
			tag_email_id = _create_tag(config, "Email", PAPERLESS_TAG_EMAIL_SLUG)
		if not tag_attachment_id:
			tag_attachment_id = _create_tag(config, "Anhang", PAPERLESS_TAG_ATTACHMENT_SLUG)
	except Exception:
		_mark_log(doc.name, status="Failed", error="Paperless Tags konnten nicht geladen oder erstellt werden")
		raise

	started_at = now_datetime()

	success = True
	failure_reason: str | None = None
	paperless_refs: list[tuple[str, int]] = []
	eml_link: str | None = None
	uploads: list[PaperlessUpload] = []

	# Upload EML first (Paperless returns a task ID; we resolve document IDs via checksum afterwards).
	eml_file_name, eml_content = eml
	eml_content_bytes = _ensure_bytes(eml_content)
	eml_upload = PaperlessUpload(
		file_name=eml_file_name,
		content=eml_content_bytes,
		checksum=_checksum(eml_content_bytes),
		is_email=True,
	)
	uploads.append(eml_upload)
	ok, eml_id, _eml_task = _post_to_paperless(
		config,
		doc,
		eml_file_name,
		eml_content_bytes,
		extra_tag_ids=_maybe_single_tag(tag_email_id),
		title=doc.subject or eml_file_name,
	)
	if ok and eml_id:
		eml_upload.paperless_id = eml_id
	success = success and ok

	# Upload attachments individually; linking happens after IDs are resolved.
	for file_name, file_content in attachments:
		file_content_bytes = _ensure_bytes(file_content)
		upload = PaperlessUpload(
			file_name=file_name,
			content=file_content_bytes,
			checksum=_checksum(file_content_bytes),
			is_email=False,
		)
		uploads.append(upload)
		ok, paperless_id, _task_id = _post_to_paperless(
			config,
			doc,
			file_name,
			file_content_bytes,
			extra_tag_ids=_maybe_single_tag(tag_attachment_id),
			title=file_name,
		)
		if ok and paperless_id:
			upload.paperless_id = paperless_id
		success = success and ok

	# Paperless post_document returns a Celery task ID; poll for real document IDs via checksum.
	if not _resolve_paperless_ids(config, uploads, added_after=started_at):
		success = False
		failure_reason = "Paperless-Dokumente konnten nicht gefunden werden (Checksum)"

	eml_id = next((u.paperless_id for u in uploads if u.is_email), None)
	attachment_ids = [u.paperless_id for u in uploads if not u.is_email and u.paperless_id]

	if eml_id:
		eml_link = _paperless_doc_link(config.url, eml_id)
		paperless_refs.append((eml_file_name, eml_id))

	for upload in uploads:
		if upload.paperless_id and not upload.is_email:
			paperless_refs.append((upload.file_name, upload.paperless_id))

	# Add bidirectional custom field links once IDs are known.
	if eml_id and attachment_ids and custom_field_link_id:
		try:
			for attachment_id in attachment_ids:
				set_ok = _set_custom_fields_by_id(
					config,
					attachment_id,
					{custom_field_link_id: [eml_id]},
				)
				success = success and set_ok

			set_ok = _set_custom_fields_by_id(
				config,
				eml_id,
				# Custom field is a document link, so we store the first attachment ID.
				{custom_field_link_id: [attachment_ids[0]]},
			)
			success = success and set_ok
		except Exception:
			_mark_log(doc.name, status="Failed", error="Paperless Custom Field (Link) konnte nicht gesetzt werden")
			raise

	if paperless_refs:
		_add_paperless_link(doc.name, config.url, paperless_refs)
		if eml_link:
			_attach_paperless_link_file(doc.name, eml_link)

	if success:
		_mark_log(doc.name, status="Success")
	else:
		_mark_log(doc.name, status="Failed", error=failure_reason or "Mindestens ein Dokument konnte nicht exportiert werden")


def retry_failed_exports(limit: int = 200) -> None:
	"""Scheduled job: re-enqueue Communications whose export failed or is pending."""
	config = PaperlessConfig.from_conf()
	if not config:
		return

	rows = frappe.get_all(
		LOG_DOCTYPE,
		filters={"status": ["in", ["Pending", "Failed"]]},
		fields=["communication"],
		limit=limit,
	)
	for row in rows:
		frappe.enqueue(
			"hausverwaltung.hausverwaltung.integrations.paperless.export_communication",
			queue="long",
			communication_name=row.communication,
			enqueue_after_commit=False,
		)


def _post_to_paperless(
	config: PaperlessConfig,
	doc,
	file_name: str,
	file_content: bytes | str | bytearray | memoryview,
	extra_tag_ids: list[int] | None = None,
	title: str | None = None,
	custom_fields: dict[int | str, str | int | list | None] | None = None,
) -> tuple[bool, int | None, str | None]:
	"""Send a single file to Paperless NGX. Returns success, the Paperless document ID (if available) and the task ID."""
	url = urljoin(config.url + "/", "api/documents/post_document/")
	file_content_bytes = _ensure_bytes(file_content)
	files = {"document": (file_name, file_content_bytes, _guess_mime(file_name))}
	data = _build_payload(config, doc, file_name, extra_tag_ids=extra_tag_ids, title_override=title)
	if custom_fields:
		try:
			data["custom_fields"] = json.dumps(custom_fields)
		except Exception:
			data["custom_fields"] = json.dumps({})

	try:
		resp = requests.post(
			url,
			headers={"Authorization": f"Token {config.token}"},
			data=data,
			files=files,
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		paperless_id = None
		task_id = None
		try:
			json_resp = resp.json()
			if isinstance(json_resp, dict):
				paperless_id = _to_int(json_resp.get("id"))
				task_id = json_resp.get("task_id") or json_resp.get("task")
			elif isinstance(json_resp, str):
				task_id = json_resp
		except Exception:
			paperless_id = None
			task_id = None
		return True, paperless_id, task_id
	except Exception as exc:
		extra = ""
		if isinstance(exc, requests.HTTPError) and exc.response is not None:
			try:
				extra = f" ({exc.response.status_code} {exc.response.text})"
			except Exception:
				extra = ""
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Upload fehlgeschlagen ({doc.name}, {file_name}){extra}",
		)
		return False, None, None


def _paperless_doc_link(base_url: str, document_id: int | None) -> str:
	if not base_url or not document_id:
		return ""
	return urljoin(base_url.rstrip("/") + "/", f"documents/{document_id}")


def _resolve_paperless_ids(config: PaperlessConfig, uploads: list[PaperlessUpload], added_after) -> bool:
	"""Poll Paperless for uploaded documents and fill in their IDs based on checksum."""
	if not uploads:
		return True

	deadline = time.time() + max(config.timeout * 6, 120)
	interval = 2.0
	added_after_filter = None
	try:
		added_after_filter = get_datetime(added_after).isoformat() if added_after else None
	except Exception:
		added_after_filter = None

	while time.time() < deadline:
		unresolved = [u for u in uploads if not u.paperless_id]
		if not unresolved:
			return True

		found_any = False
		for upload in unresolved:
			try:
				doc_id = _find_document_by_checksum(
					config,
					upload.checksum,
					file_name=upload.file_name,
					added_after=added_after_filter,
				)
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"{LOGGER_TITLE}: Dokument-ID konnte nicht ermittelt werden ({upload.file_name})",
				)
				return False

			if doc_id:
				upload.paperless_id = doc_id
				found_any = True

		if not found_any:
			time.sleep(interval)

	return all(u.paperless_id for u in uploads)


def _find_document_by_checksum(
	config: PaperlessConfig, checksum: str, file_name: str | None, added_after: str | None = None
) -> int | None:
	"""Return the Paperless document ID that matches the checksum (and optional filename/time filter)."""
	if not checksum:
		return None

	def _query(include_filename: bool) -> list[dict] | None:
		params = {
			"checksum__iexact": checksum,
			"ordering": "-added",
			"page_size": 2,
		}
		if include_filename and file_name:
			params["original_filename__iexact"] = file_name
		if added_after:
			params["added__gte"] = added_after

		url = urljoin(config.url.rstrip("/") + "/", "api/documents/")
		resp = requests.get(
			url,
			headers={"Authorization": f"Token {config.token}"},
			params=params,
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		data = resp.json() or {}
		results = data.get("results")
		if results is None and isinstance(data, list):
			results = data
		return results

	results = _query(include_filename=True)
	if (not results) and file_name:
		results = _query(include_filename=False)
	if not results:
		return None

	try:
		return int(results[0].get("id"))
	except Exception:
		return None


def _set_custom_fields_by_id(config: PaperlessConfig, document_id: int, fields: dict[int | None, str | int | list[int]]) -> bool:
	"""Patch custom fields on an existing Paperless document (expects IDs)."""
	entries = [{"field": field_id, "value": value} for field_id, value in (fields or {}).items() if field_id and value]
	if not entries:
		return True

	url = urljoin(config.url.rstrip("/") + "/", f"api/documents/{document_id}/")
	try:
		resp = requests.patch(
			url,
			headers={"Authorization": f"Token {config.token}"},
			json={"custom_fields": entries},
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		# Verify that values are applied.
		actual = _fetch_document_custom_field_values(config, document_id)
		for entry in entries:
			if str(actual.get(entry["field"], "")) != str(entry["value"]):
				raise ValueError(
					f"Custom Field mismatch for {document_id}: expected {entry['field']}={entry['value']}, "
					f"got {actual.get(entry['field'])}"
				)
		return True
	except Exception as exc:
		extra = ""
		if isinstance(exc, requests.HTTPError) and exc.response is not None:
			try:
				extra = f" ({exc.response.status_code} {exc.response.text})"
			except Exception:
				extra = ""
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Custom Fields konnten nicht gesetzt werden ({document_id}){extra}",
		)
		# Raise so the caller can mark the export as failed and surface an error.
		raise


def _maybe_single_tag(tag_id: int | None) -> list[int] | None:
	return [tag_id] if tag_id else None


def _attach_paperless_link_file(communication_name: str, link: str) -> None:
	"""Attach a link file to the Communication pointing to the Paperless document."""
	if not (communication_name and link):
		return

	try:
		existing = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Communication",
				"attached_to_name": communication_name,
				"file_url": link,
			},
			limit=1,
		)
		if existing:
			return

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "Paperless-EML-Link.url",
				"file_url": link,
				"attached_to_doctype": "Communication",
				"attached_to_name": communication_name,
				"is_private": 0,
			}
		)
		doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Paperless-Link konnte nicht als Anhang hinzugefügt werden ({communication_name})",
		)


def _fetch_custom_fields(config: PaperlessConfig) -> list[dict]:
	"""Return all custom fields from Paperless."""
	fields: list[dict] = []
	next_url: str | None = urljoin(config.url.rstrip("/") + "/", "api/custom_fields/")
	params = {"page_size": 250}

	while next_url:
		resp = requests.get(
			next_url,
			headers={"Authorization": f"Token {config.token}"},
			params=params,
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		data = resp.json() or {}
		results = data.get("results")
		if results is None and isinstance(data, list):
			results = data
		fields.extend(results or [])
		next_url = data.get("next")
		params = None  # pagination URLs already contain params

	return fields


def _resolve_custom_field_id(fields: list[dict], slug: str) -> int | None:
	target = _normalize_key(slug)
	if not target:
		return None

	for field in fields or []:
		slug_val = _normalize_key(field.get("slug"))
		name_val = _normalize_key(field.get("name"))
		if target in {slug_val, name_val}:
			try:
				return int(field.get("id"))
			except Exception:
				continue
	return None


def _create_custom_field(config: PaperlessConfig, name: str, slug: str, data_type: str) -> int:
	"""Create a custom field and return its ID."""
	url = urljoin(config.url.rstrip("/") + "/", "api/custom_fields/")
	payload = {"name": name, "slug": slug, "data_type": data_type}
	try:
		resp = requests.post(
			url,
			headers={"Authorization": f"Token {config.token}"},
			json=payload,
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		data = resp.json() or {}
		return int(data.get("id"))
	except requests.HTTPError as err:
		# If the field already exists (e.g., same name/slug), try to resolve it.
		if err.response is not None and err.response.status_code == 400:
			fields = _fetch_custom_fields(config)
			field_id = _resolve_custom_field_id(fields, slug) or _resolve_custom_field_id(fields, name)
			if field_id:
				return field_id
		raise


def _fetch_tags(config: PaperlessConfig) -> list[dict]:
	"""Return all tags from Paperless."""
	tags: list[dict] = []
	next_url: str | None = urljoin(config.url.rstrip("/") + "/", "api/tags/")
	params = {"page_size": 250}

	while next_url:
		resp = requests.get(
			next_url,
			headers={"Authorization": f"Token {config.token}"},
			params=params,
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		data = resp.json() or {}
		results = data.get("results")
		if results is None and isinstance(data, list):
			results = data
		tags.extend(results or [])
		next_url = data.get("next")
		params = None

	return tags


def _ensure_tag_ids(config: PaperlessConfig, tag_names: list[str]) -> list[int]:
	"""Ensure all tag names exist in Paperless and return their IDs."""
	if not tag_names:
		return []

	tags_cache = _fetch_tags(config)
	resolved: list[int] = []
	for name in tag_names:
		tag_name = (name or "").strip()
		if not tag_name:
			continue

		tag_id = _resolve_tag_id(tags_cache, tag_name)
		if not tag_id:
			slug = re.sub(r"[^a-z0-9]+", "-", _normalize_key(tag_name)).strip("-") or "tag"
			tag_id = _create_tag(config, tag_name, slug)
			tags_cache = _fetch_tags(config)

		if tag_id:
			resolved.append(int(tag_id))

	return sorted(set(resolved))


def _resolve_tag_id(tags: list[dict], slug: str, parent_id: int | None = None) -> int | None:
	target = _normalize_key(slug)
	if not target:
		return None

	for tag in tags or []:
		slug_val = _normalize_key(tag.get("slug"))
		name_val = _normalize_key(tag.get("name"))
		tag_parent = tag.get("parent")
		if target in {slug_val, name_val} and (parent_id is None or tag_parent == parent_id):
			try:
				return int(tag.get("id"))
			except Exception:
				continue
	return None


def _create_tag(config: PaperlessConfig, name: str, slug: str, parent_id: int | None = None) -> int:
	"""Create a tag and return its ID."""
	url = urljoin(config.url.rstrip("/") + "/", "api/tags/")
	payload = {"name": name, "slug": slug}
	if parent_id:
		payload["parent"] = parent_id
	try:
		resp = requests.post(
			url,
			headers={"Authorization": f"Token {config.token}"},
			json=payload,
			timeout=config.timeout,
			verify=config.verify_ssl,
		)
		resp.raise_for_status()
		data = resp.json() or {}
		return int(data.get("id"))
	except requests.HTTPError as err:
		# If the tag already exists, fetch its ID.
		if err.response is not None and err.response.status_code == 400:
			tags = _fetch_tags(config)
			tag_id = _resolve_tag_id(tags, slug, parent_id=parent_id) or _resolve_tag_id(
				tags, name, parent_id=parent_id
			)
			if tag_id:
				return tag_id
		raise


def _normalize_key(value) -> str:
	text = str(value or "").strip().lower()
	# Basic German umlaut normalization for matching slugs/names.
	for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
		text = text.replace(src, dst)
	return text


def _extract_first_href(html: str | None) -> str | None:
	if not html:
		return None
	match = re.search(r"href=['\"]([^'\"]+)['\"]", str(html))
	if match:
		return match.group(1)
	return None


def _ensure_custom_field(
	config: PaperlessConfig, name: str, slug: str, desired_type: str, fields_cache: list[dict], existing_id: int | None
) -> int:
	"""Ensure a custom field exists with the desired type, returning its ID."""
	field = None
	if existing_id:
		field = _get_custom_field_by_id(fields_cache, existing_id)
	if not field:
		field = _get_custom_field_by_slug_or_name(fields_cache, slug) or _get_custom_field_by_slug_or_name(
			fields_cache, name
		)

	if field:
		field_id = int(field.get("id"))
		if field.get("data_type") != desired_type:
			field = _update_custom_field_type(config, field_id, desired_type)
		return field_id

	return _create_custom_field(config, name, slug, desired_type)


def _get_custom_field_by_id(fields: list[dict], field_id: int | None) -> dict | None:
	if not field_id:
		return None
	for field in fields or []:
		try:
			if int(field.get("id")) == int(field_id):
				return field
		except Exception:
			continue
	return None


def _get_custom_field_by_slug_or_name(fields: list[dict], value: str) -> dict | None:
	target = _normalize_key(value)
	if not target:
		return None
	for field in fields or []:
		if target in {_normalize_key(field.get("slug")), _normalize_key(field.get("name"))}:
			return field
	return None


def _update_custom_field_type(config: PaperlessConfig, field_id: int, desired_type: str) -> dict:
	"""Update a custom field's data_type if it differs."""
	url = urljoin(config.url.rstrip("/") + "/", f"api/custom_fields/{field_id}/")
	resp = requests.patch(
		url,
		headers={"Authorization": f"Token {config.token}"},
		json={"data_type": desired_type},
		timeout=config.timeout,
		verify=config.verify_ssl,
	)
	resp.raise_for_status()
	return resp.json() or {"id": field_id, "data_type": desired_type}


def _fetch_document_custom_field_values(config: PaperlessConfig, document_id: int) -> dict[int, str]:
	"""Return custom field values for a Paperless document."""
	url = urljoin(config.url.rstrip("/") + "/", f"api/documents/{document_id}/")
	resp = requests.get(
		url,
		headers={"Authorization": f"Token {config.token}"},
		timeout=config.timeout,
		verify=config.verify_ssl,
	)
	resp.raise_for_status()
	data = resp.json() or {}
	values: dict[int, str] = {}
	for entry in data.get("custom_fields") or []:
		try:
			values[int(entry.get("field"))] = entry.get("value")
		except Exception:
			continue
	return values


def _collect_attachments(communication_name: str) -> Iterable[tuple[str, bytes]]:
	"""Return all files attached to the Communication."""
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Communication", "attached_to_name": communication_name},
		fields=["name", "file_url", "file_name"],
	)

	for file in files:
		try:
			stored_name, content = get_file(file.file_url or file.file_name)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"{LOGGER_TITLE}: Anhang {file.name} konnte nicht gelesen werden.",
			)
			continue

		yield (
			file.file_name
			or stored_name
			or os.path.basename(file.file_url or file.file_name or f"{communication_name}.bin"),
			_ensure_bytes(content),
		)


def _pop_original_eml(
	attachments: list[tuple[str, bytes]]
) -> tuple[tuple[str, bytes] | None, list[tuple[str, bytes]]]:
	"""If a .eml attachment exists, return it and the remaining attachments."""
	if not attachments:
		return None, attachments

	for idx, (filename, content) in enumerate(list(attachments)):
		if _looks_like_eml_file(filename, content):
			remaining = attachments[:idx] + attachments[idx + 1 :]
			return (filename, content), remaining
	return None, attachments


def _looks_like_eml_file(filename: str | None, content: bytes | None) -> bool:
	name = (filename or "").lower()
	if name.endswith(".eml"):
		return True
	if not content:
		return False
	# crude sniff: EMLs often start with "From:" or "Return-Path" etc.
	head = (content[:200] or b"").decode("utf-8", errors="ignore").lower()
	return head.startswith("from:") or "return-path:" in head


def _attach_eml_if_missing(doc) -> None:
	"""Persist a .eml file on the Communication so future exports have the original message."""
	try:
		existing = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Communication",
				"attached_to_name": doc.name,
				"file_name": ("like", "%.eml%"),
			},
			limit=1,
		)
		if existing:
			return

		content = _fetch_imap_raw_email(doc)
		file_name = None
		if content:
			file_name = _sanitize_filename(f"{(doc.subject or 'Email').strip() or 'Email'}_{doc.name}.eml")
		else:
			attachments = list(_collect_attachments(doc.name))
			eml = _build_eml(doc, attachments)
			if not eml:
				return
			file_name, content = eml

		if not (file_name and content):
			return

		save_file(
			file_name,
			content,
			"Communication",
			doc.name,
			is_private=0,
			df=None,
		)
	except Exception:
		# Don't block mail ingestion if file creation fails.
		frappe.log_error(frappe.get_traceback(), f"{LOGGER_TITLE}: EML konnte nicht gespeichert werden ({doc.name})")


def _fetch_imap_raw_email(doc) -> bytes | None:
	"""Fetch the raw email via IMAP using UID and Email Account settings."""
	uid = getattr(doc, "uid", None)
	account_name = getattr(doc, "email_account", None)
	if not (uid and account_name):
		return None

	try:
		account = frappe.get_doc("Email Account", account_name)
	except Exception:
		return None

	if not _to_bool(getattr(account, "enable_incoming", False)) or not _to_bool(
		getattr(account, "use_imap", False)
	):
		return None

	host = (getattr(account, "email_server", "") or "").strip()
	if not host:
		return None

	port = _to_int(getattr(account, "incoming_port", None))
	if not port:
		port = 993 if _to_bool(getattr(account, "use_ssl", False)) else 143

	username = getattr(account, "login_id", None) if _to_bool(getattr(account, "login_id_is_different", False)) else None
	username = username or getattr(account, "email_id", None)
	if not username:
		return None

	password = None
	try:
		password = get_decrypted_password("Email Account", account.name, "password", raise_exception=False)
	except Exception:
		password = None
	if not password:
		return None

	use_ssl = _to_bool(getattr(account, "use_ssl", False))
	use_starttls = _to_bool(getattr(account, "use_starttls", False))
	folder = (getattr(doc, "imap_folder", "") or "INBOX").strip() or "INBOX"

	conn = None
	try:
		conn = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
		if use_starttls and not use_ssl:
			conn.starttls()
		conn.login(username, password)
		conn.select(folder, readonly=True)
		typ, data = conn.uid("fetch", str(uid), "(RFC822)")
		if typ != "OK" or not data:
			return None
		for part in data:
			if isinstance(part, tuple) and len(part) > 1 and part[1]:
				return part[1]
		return None
	except Exception:
		return None
	finally:
		try:
			if conn:
				conn.logout()
		except Exception:
			pass


def _build_email_body_attachment(doc) -> tuple[str, bytes]:
	"""Render the email body as a plain-text attachment when no files exist."""
	subject = (doc.subject or "").strip() or "Email"
	body_html = doc.content or getattr(doc, "text_content", "")
	body_text = strip_html(body_html) if body_html else ""
	recipients = (doc.recipients or "").strip()
	lines = [
		f"Subject: {subject}",
		f"From: {doc.sender or ''}",
		f"To: {recipients}",
	]
	if doc.cc:
		lines.append(f"Cc: {doc.cc}")
	if doc.communication_date:
		lines.append(f"Date: {doc.communication_date}")

	lines.extend(["", body_text or "(kein Inhalt)"])
	text = "\n".join(lines)

	filename = _sanitize_filename(f"{subject}_{doc.name}.txt")
	return filename, text.encode("utf-8")


def _build_email_body_pdf(doc, timeout: int) -> tuple[str, bytes] | None:
	"""Render email body (with metadata) into a PDF for nicer display in Paperless."""
	html_body = doc.content or getattr(doc, "text_content", "")
	body_text = strip_html(html_body) if html_body else ""
	if not (html_body or body_text):
		return None

	subject = (doc.subject or "").strip() or "Email"
	recipients = (doc.recipients or "").strip()
	header_rows = [
		("Subject", subject),
		("From", doc.sender or ""),
		("To", recipients),
	]
	if doc.cc:
		header_rows.append(("Cc", doc.cc))
	if doc.communication_date:
		header_rows.append(("Date", str(doc.communication_date)))

	header_html = "".join(
		f"<tr><th>{escape(label)}:</th><td>{escape(value)}</td></tr>"
		for label, value in header_rows
	)
	body_html = html_body or f"<pre>{escape(body_text)}</pre>"

	html = f"""<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<style>
		body {{ font-family: Arial, sans-serif; margin: 24px; }}
		table.meta {{ width: 100%; border-collapse: collapse; margin-bottom: 18px; }}
		table.meta th {{ text-align: left; width: 120px; padding: 4px 8px; vertical-align: top; background: #f3f4f6; }}
		table.meta td {{ padding: 4px 8px; }}
		.body {{ border: 1px solid #e5e7eb; padding: 16px; }}
	</style>
</head>
<body>
	<table class="meta">{header_html}</table>
	<div class="body">{body_html}</div>
</body>
</html>"""

	try:
		result = subprocess.run(
			[
				"wkhtmltopdf",
				"--disable-javascript",
				"--disable-local-file-access",
				"--quiet",
				"-",
				"-",
			],
			input=html.encode("utf-8"),
			check=True,
			capture_output=True,
			timeout=timeout or 20,
		)
		filename = _sanitize_filename(f"{subject}_{doc.name}.pdf")
		return filename, result.stdout
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: PDF-Rendern fehlgeschlagen ({doc.name})",
		)
		return None


def _build_eml(doc, attachments: list[tuple[str, bytes]]) -> tuple[str, bytes] | None:
	"""Create an .eml with headers, body and original attachments."""
	subject = (doc.subject or "").strip() or "Email"
	recipients = (doc.recipients or "").strip()
	body_html = doc.content or getattr(doc, "text_content", "")
	body_text = strip_html(body_html) if body_html else ""
	if not (body_html or body_text):
		return None

	msg = EmailMessage()
	msg["Subject"] = subject
	if doc.sender:
		msg["From"] = doc.sender
	if recipients:
		msg["To"] = recipients
	if doc.cc:
		msg["Cc"] = doc.cc
	if getattr(doc, "message_id", None):
		msg["Message-ID"] = doc.message_id
	else:
		msg["Message-ID"] = make_msgid(domain=None)
	if doc.communication_date:
		try:
			msg["Date"] = format_datetime(get_datetime(doc.communication_date))
		except Exception:
			pass

	msg.set_content(body_text or "(kein Inhalt)")
	if body_html:
		msg.add_alternative(body_html, subtype="html")

	for filename, content in attachments:
		maintype, subtype = (_guess_mime(filename) or "application/octet-stream").split("/", 1)
		msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

	filename = _sanitize_filename(f"{subject}_{doc.name}.eml")
	return filename, msg.as_bytes()


def _add_paperless_link(communication_name: str, base_url: str, refs: list[tuple[str, int]]) -> None:
	"""Add a timeline comment with links to all Paperless documents created from this mail."""
	if not refs or not base_url:
		return

	parts = []
	for filename, paperless_id in refs:
		link = urljoin(base_url.rstrip("/") + "/", f"documents/{paperless_id}")
		title = os.path.splitext(filename)[1].lstrip(".").upper() or "DOC"
		parts.append(f"<a href='{escape(link)}' target='_blank'>{escape(title)}</a>")

	content = "📄 Paperless: " + " | ".join(parts)

	try:
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Communication",
				"reference_name": communication_name,
				"content": content,
			}
		)
		comment.insert(ignore_permissions=True, ignore_if_duplicate=True)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Link zu Paperless konnte nicht angelegt werden ({communication_name})",
		)


def _build_payload(
	config: PaperlessConfig, doc, file_name: str, extra_tag_ids: list[int] | None = None, title_override: str | None = None
) -> dict:
	"""Build metadata payload for Paperless NGX upload."""
	payload = {
		"title": title_override or doc.subject or file_name,
		"created": _get_comm_datetime(doc),
	}

	if config.correspondent_id:
		payload["correspondent"] = config.correspondent_id
	if config.document_type_id:
		payload["document_type"] = config.document_type_id
	tags = list(config.tag_ids or [])
	if extra_tag_ids:
		tags.extend(extra_tag_ids)
	if tags:
		# Paperless expects unique tag IDs.
		payload["tags"] = sorted(set(tags))

	return {k: v for k, v in payload.items() if v not in (None, "", [])}


def _get_comm_datetime(doc) -> str | None:
	"""Return the email timestamp as ISO string."""
	for fieldname in ("communication_date", "creation", "modified"):
		value = getattr(doc, fieldname, None)
		if value:
			try:
				return get_datetime(value).isoformat()
			except Exception:
				continue
	return None


def _ensure_bytes(content: bytes | str | bytearray | memoryview | None) -> bytes:
	"""Return bytes for hashing/uploading regardless of the original input type."""
	if content is None:
		return b""
	if isinstance(content, bytes):
		return content
	if isinstance(content, str):
		return content.encode("utf-8", errors="replace")
	if isinstance(content, memoryview):
		return content.tobytes()
	if isinstance(content, bytearray):
		return bytes(content)
	try:
		return bytes(content)
	except Exception:
		return b""


def _checksum(content: bytes | str | bytearray | memoryview | None) -> str:
	"""Return an md5 checksum for matching Paperless documents."""
	return hashlib.md5(_ensure_bytes(content)).hexdigest()


def _guess_mime(file_name: str) -> str:
	if (file_name or "").lower().endswith(".eml"):
		return "message/rfc822"
	mime, _ = mimetypes.guess_type(file_name or "")
	return mime or "application/octet-stream"


def _sanitize_filename(file_name: str) -> str:
	"""Replace filesystem-unfriendly characters."""
	safe_chars = "-_.() "
	return "".join(ch if ch.isalnum() or ch in safe_chars else "_" for ch in file_name)


def _ensure_log_entry(communication_name: str, status: str = "Pending") -> None:
	"""Create a log row if missing."""
	try:
		if frappe.db.exists(LOG_DOCTYPE, communication_name):
			return
		doc = frappe.get_doc(
			{
				"doctype": LOG_DOCTYPE,
				"communication": communication_name,
				"status": status,
			}
		)
		doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Log-Eintrag konnte nicht angelegt werden ({communication_name})",
		)


def _mark_log(communication_name: str, status: str | None = None, error: str | None = None) -> None:
	"""Update or create the log row with latest status and error."""
	try:
		_ensure_log_entry(communication_name, status=status or "Pending")
		updates: dict[str, str | None] = {"last_attempt": now_datetime()}
		if status:
			updates["status"] = status
		if error:
			updates["last_error"] = (error or "")[:1000]
		elif status == "Success":
			updates["last_error"] = ""
		frappe.db.set_value(LOG_DOCTYPE, communication_name, updates, update_modified=False)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"{LOGGER_TITLE}: Log-Eintrag konnte nicht aktualisiert werden ({communication_name})",
		)


def _is_incoming_email(doc) -> bool:
	"""Check whether the Communication represents an incoming email."""
	if (getattr(doc, "communication_medium", "") or "").lower() != "email":
		return False

	sent_received = (getattr(doc, "sent_or_received", "") or "").lower()
	if sent_received not in {"received", "incoming"}:
		return False

	comm_type = (getattr(doc, "communication_type", "") or "").lower()
	if comm_type and comm_type not in {"communication", "email"}:
		return False

	return True


def _to_int(value) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _to_int_list(raw) -> list[int]:
	if not raw:
		return []

	if isinstance(raw, str):
		items = [part.strip() for part in raw.split(",") if part.strip()]
	elif isinstance(raw, (list, tuple, set)):
		items = raw
	else:
		return []

	ids = []
	for item in items:
		try:
			ids.append(int(item))
		except Exception:
			continue
	return ids


def _to_bool(value, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() not in {"0", "false", "no", "off"}
	return bool(value)
