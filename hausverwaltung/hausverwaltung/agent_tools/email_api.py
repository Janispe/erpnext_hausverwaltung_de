"""Permission-checked ERPNext gateway to Stalwart tenant mail; draft creation only."""

from __future__ import annotations

import html
import json
import uuid
from datetime import timedelta
from functools import wraps

import frappe
from frappe.utils import get_datetime, getdate, now_datetime

from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError
from hausverwaltung.hausverwaltung.agent_tools.email_budget import fit_context, fit_preview, fits_data
from hausverwaltung.hausverwaltung.agent_tools.fac_overview import (
	OverviewError,
	_exact_identity,
	_invoice_identity,
)
from hausverwaltung.hausverwaltung.agent_tools.fac_overview_backend import OverviewBackend
from hausverwaltung.hausverwaltung.services.email_attachments import (
	MAX_ATTACHMENT_BYTES,
	attachment_manifest,
	prepare_attachments,
)
from hausverwaltung.hausverwaltung.services.email_draft_contract import (
	DraftCreationRejected,
	EmailDraftError,
	addresses,
	classify_remote,
	configured_addresses,
	create_remote_draft,
	exact_name,
	prepare_payload,
)

DRAFT = "Email Entwurf"
ACCOUNT = "Mail Archive Account"
SOURCE = "Mail Archive Message"
FOLDER = "Mail Archive Folder"
MISSING_PAUSE_THRESHOLD = 6


def _reload_locked(doc):
	# A locking read sees the latest row even under MariaDB REPEATABLE READ.
	# Merely locking name followed by a normal reload can read an old snapshot.
	doc.flags.for_update = True
	doc.reload()
	return doc


def _access(write=False):
	roles = set(frappe.get_roles())
	allowed = {"System Manager", "Hausverwalter", "Agent Email Drafts"}
	if not write:
		allowed.add("Agent Readonly API")
	if frappe.session.user == "Guest" or not roles.intersection(allowed):
		raise EmailDraftError("PERMISSION_DENIED", "Keine Berechtigung für diese E-Mail-Aktion.")
	if "thunderbird_hausverwaltung" not in frappe.get_installed_apps():
		raise EmailDraftError("NOT_CONFIGURED", "Die Thunderbird-/Stalwart-Anbindung ist nicht installiert.")
	if not frappe.has_permission(DRAFT, "read"):
		raise EmailDraftError("PERMISSION_DENIED", "Leseberechtigung für Email Entwurf fehlt.")


def _endpoint(*, write=False):
	def decorate(function):
		@wraps(function)
		def wrapped(*args, **kwargs):
			try:
				_access(write)
				data = function(*args, **kwargs)
				if not fits_data(data):
					raise EmailDraftError(
						"LIMIT_EXCEEDED", "Mailantwort zu groß; limit oder body_limit verkleinern."
					)
				return {"ok": True, "data": data}
			except (EmailDraftError, AgentToolError, OverviewError) as error:
				return {"ok": False, "error": {"code": error.code, "message": str(error)}}
			except frappe.PermissionError:
				return {"ok": False, "error": {"code": "PERMISSION_DENIED", "message": "Berechtigung fehlt."}}
			except frappe.DoesNotExistError:
				return {"ok": False, "error": {"code": "NOT_FOUND", "message": "Datensatz nicht verfügbar."}}
			except Exception:
				frappe.log_error(title="Agent E-Mail", message=frappe.get_traceback())
				return {
					"ok": False,
					"error": {
						"code": "MAIL_OPERATION_FAILED",
						"message": "Mailserver-Aktion fehlgeschlagen. Bei Entwurfserstellung dieselbe request_id wiederverwenden.",
					},
				}

		return wrapped

	return decorate


def _read(doctype, name):
	doc = frappe.get_doc(doctype, exact_name(name, doctype))
	doc.check_permission("read")
	return doc


class _EmailIdentityBackend(OverviewBackend):
	def _fields(self, doctype, fields, parenttype=None):
		# Use the same field/document permissions as overviews, but the narrow
		# mail role must not need the general Agent Readonly API capability.
		from frappe.model import get_permitted_fields

		from hausverwaltung.hausverwaltung.agent_tools.contracts import is_sensitive_field
		from hausverwaltung.hausverwaltung.agent_tools.read_api import (
			_ensure_doctype_readable,
			_sanitize_fieldnames,
		)

		if not parenttype:
			_ensure_doctype_readable(doctype)
		meta = frappe.get_meta(doctype)
		present = [
			field for field in fields if field in {"name", "docstatus", "modified"} or meta.has_field(field)
		]
		if parenttype:
			permitted = set(
				get_permitted_fields(
					doctype, parenttype=parenttype, user=frappe.session.user, permission_type="read"
				)
			)
			safe = [
				field
				for field in present
				if field in permitted
				and not is_sensitive_field(field)
				and not (meta.get_field(field) and meta.get_field(field).hidden)
			]
		else:
			safe, _ = _sanitize_fieldnames(doctype, present)
		if set(safe) != set(present):
			raise EmailDraftError(
				"FIELD_PERMISSION_DENIED", "Benötigte Mail-Kontextfelder sind nicht lesbar."
			)
		return safe


def _contract(name):
	name = exact_name(name, "Mietvertrag")
	contract = _read("Mietvertrag", name)
	if contract.docstatus == 2:
		raise EmailDraftError("INVALID_CONTRACT", "Stornierter Mietvertrag.")
	identity = _exact_identity(_EmailIdentityBackend(), name)
	if identity["mietvertrag"] != name:
		raise EmailDraftError("IDENTITY_CONFLICT", "Exakte Mietvertrag-ID erforderlich.")
	_read("Wohnung", identity["wohnung"])
	return contract, {key: identity[key] for key in ("mietvertrag", "customer", "wohnung")}


def _account(name):
	account = _read(ACCOUNT, name)
	if not account.enabled or account.provider != "JMAP":
		raise EmailDraftError("NOT_CONFIGURED", "Ein aktives JMAP-Mailkonto ist erforderlich.")
	return account


def _provider(account):
	from thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.providers import get_provider

	return get_provider(account)


def _attachment_scope(doctype, name, identity):
	"""Accept exact lease/debtor identities; an apartment is never sufficient."""
	if doctype not in {"Mietvertrag", "Customer", "Sales Invoice", "Serienbrief Dokument"}:
		raise EmailDraftError("ATTACHMENT_SCOPE_MISMATCH", "Anhang hat keinen erlaubten Mietvertragsbezug.")
	doc = _read(doctype, name)
	if doctype == "Mietvertrag":
		valid = name == identity["mietvertrag"]
	elif doctype == "Customer":
		valid = name == identity["customer"]
	elif doctype == "Sales Invoice":
		backend = _EmailIdentityBackend()
		invoice = backend.read_doc(
			"Sales Invoice",
			name,
			["name", "customer", "wohnung", "immobilie", "mietvertrag", "mietabrechnung_id", "remarks"],
			children={"items": ["idx", "wohnung", "immobilie", "mietvertrag"]},
		)
		matched = _invoice_identity(backend, invoice, invoice.get("items", []))
		valid = all(matched.get(key) == value for key, value in identity.items())
	else:
		if doc.iteration_doctype not in {"Mietvertrag", "Customer", "Sales Invoice"} or not doc.objekt:
			raise EmailDraftError(
				"ATTACHMENT_SCOPE_MISMATCH", "Serienbrief hat keinen eindeutigen Mietvertragsbezug."
			)
		_attachment_scope(doc.iteration_doctype, doc.objekt, identity)
		return
	if not valid:
		raise EmailDraftError(
			"ATTACHMENT_SCOPE_MISMATCH", "Anhang gehört nicht zum ausgewählten Mietvertrag."
		)


def _attachment_file(name, identity):
	file = _read("File", name)
	if (
		file.is_folder
		or not isinstance(file.file_url, str)
		or not file.file_url.startswith(("/files/", "/private/files/"))
	):
		raise EmailDraftError("INVALID_ATTACHMENT", "Nur lokal gespeicherte ERPNext-Dateien sind erlaubt.")
	if not file.attached_to_doctype or not file.attached_to_name:
		raise EmailDraftError(
			"ATTACHMENT_SCOPE_MISMATCH", "Anhang benötigt einen eindeutigen Mietvertragsbezug."
		)
	_attachment_scope(file.attached_to_doctype, file.attached_to_name, identity)
	# Bounded binary read: File.get_content() can decode text and alter BOM/encoding.
	file.validate_file_url()
	try:
		with open(file.get_full_path(), "rb") as stream:
			content = stream.read(MAX_ATTACHMENT_BYTES + 1)
	except OSError:
		raise EmailDraftError("INVALID_ATTACHMENT", "Die Anhangsdatei ist nicht verfügbar.") from None
	return file.file_name, content


def _partner_addresses(contract):
	backend = _EmailIdentityBackend()
	projected = backend.read_doc(
		"Mietvertrag",
		contract.name,
		["name"],
		children={"mieter": ["mieter", "rolle", "eingezogen", "ausgezogen"]},
	)
	all_addresses, defaults = [], []
	for partner in projected.get("mieter", []):
		contact = backend.read_doc(
			"Contact",
			partner["mieter"],
			["name", "email_id"],
			children={"email_ids": ["email_id", "is_primary"]},
		)
		emails = [item["email_id"] for item in contact.get("email_ids", []) if item.get("email_id")]
		if contact.get("email_id"):
			emails.append(contact["email_id"])
		emails = addresses(emails)
		all_addresses.extend(emails)
		active = (
			partner.get("rolle") != "Ausgezogen"
			and (not partner.get("eingezogen") or getdate(partner["eingezogen"]) <= getdate())
			and (not partner.get("ausgezogen") or getdate(partner["ausgezogen"]) > getdate())
		)
		if active and emails:
			preferred = next(
				(
					item["email_id"]
					for item in contact.get("email_ids", [])
					if item.get("is_primary") and item.get("email_id")
				),
				contact.get("email_id") or emails[0],
			)
			defaults.append(preferred)
	return addresses(all_addresses), addresses(defaults)


def _folder_scope(account, identity):
	from thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.classifier import (
		_effective_folder_reference,
	)

	rows = frappe.get_all(
		FOLDER,
		filters={"archive_account": account.name},
		fields=[
			"name",
			"provider_mailbox_id",
			"parent_mailbox_id",
			"reference_doctype",
			"reference_name",
			"provider_exists",
		],
		limit_page_length=2001,
	)
	if len(rows) > 2000:
		raise EmailDraftError(
			"LIMIT_EXCEEDED", "Zu viele Archivordner für eine vollständige Zuordnungsprüfung."
		)
	by_id = {row.provider_mailbox_id: row for row in rows}
	scope = set()
	for row in rows:
		if not row.provider_exists:
			continue
		reference = _effective_folder_reference(row, by_id)
		if reference not in {("Mietvertrag", identity["mietvertrag"]), ("Customer", identity["customer"])}:
			continue
		# A inherited reference is usable only if its whole ancestry can be read.
		current, visited = row, set()
		while current and current.provider_mailbox_id not in visited:
			visited.add(current.provider_mailbox_id)
			_read(FOLDER, current.name)
			if current.reference_doctype and current.reference_name:
				break
			current = by_id.get(current.parent_mailbox_id)
		scope.add(row.provider_mailbox_id)
	return scope, by_id


def _source(name, account, identity, provider, scope=None):
	source = _read(SOURCE, name)
	if source.archive_account != account.name or source.status == "Gelöscht":
		raise EmailDraftError(
			"MESSAGE_MISMATCH", "Ausgangsmail gehört nicht zum ausgewählten Postfach oder wurde gelöscht."
		)
	scope, folders = _folder_scope(account, identity) if scope is None else scope
	remote, _state = provider.get_messages([source.provider_message_id])
	if len(remote) != 1 or remote[0].id != source.provider_message_id:
		raise EmailDraftError(
			"MESSAGE_NOT_FOUND", "Ausgangsmail auf dem Mailserver nicht eindeutig gefunden."
		)
	mail = remote[0]
	if not set(mail.mailbox_ids).intersection(scope):
		raise EmailDraftError(
			"MESSAGE_MISMATCH",
			"Ausgangsmail liegt nicht in einem Ordner des angegebenen Mietvertrags. Zuerst eindeutig zuordnen.",
		)
	from thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.classifier import (
		_effective_folder_reference,
	)

	for mailbox_id in mail.mailbox_ids:
		folder = folders.get(mailbox_id)
		if folder:
			reference = _effective_folder_reference(folder, folders)
			if reference[0] in {"Mietvertrag", "Customer"} and mailbox_id not in scope:
				raise EmailDraftError(
					"MESSAGE_MISMATCH", "Mail ist zugleich einem anderen Mietverhältnis zugeordnet."
				)
	if "$draft" in mail.keywords:
		raise EmailDraftError("INVALID_SOURCE", "Ein Mailentwurf ist keine Ausgangsmail für eine Antwort.")
	return source, mail


def _integer(value, default, minimum, maximum):
	if value is None:
		return default
	if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
		raise EmailDraftError("INVALID_ARGUMENT", f"Ganzzahl zwischen {minimum} und {maximum} erforderlich.")
	return value


def _summary(mail, name=None):
	return {
		"message": name,
		"provider_message_id": mail.id,
		"thread_id": mail.thread_id,
		"subject": mail.subject,
		"from": list(mail.sender),
		"to": list(mail.to),
		"cc": list(mail.cc),
		"received_at": mail.received_at,
		"has_attachment": mail.has_attachment,
	}


def _body_quality(mail):
	values = mail.raw.get("bodyValues") or {}
	source = mail.raw.get("body_text_source", "plain")
	parts = mail.raw.get("textBody") or []
	if source == "html":
		parts = [
			part
			for part in [*(mail.raw.get("htmlBody") or []), *parts]
			if str(part.get("type") or "").casefold() == "text/html"
		]
	else:
		parts = [part for part in parts if str(part.get("type") or "text/plain").casefold() == "text/plain"]
	part_ids = dict.fromkeys(str(part.get("partId") or "") for part in parts)
	selected = [values.get(part_id, {}) for part_id in part_ids] if parts else values.values()
	selected = list(selected)
	return {
		"truncated": any(value.get("isTruncated") for value in selected),
		"encoding_problem": any(value.get("isEncodingProblem") for value in selected),
	}


@_endpoint()
def list_mieter_emails(mietvertrag, archive_account, limit=10, offset=0):
	_contract_doc, identity = _contract(mietvertrag)
	account = _account(archive_account)
	limit, offset = _integer(limit, 10, 1, 20), _integer(offset, 0, 0, 1000)
	scope, _folders = _folder_scope(account, identity)
	rows = []
	if scope:
		rows = frappe.get_list(
			SOURCE,
			filters={
				"archive_account": account.name,
				"actual_mailbox_id": ["in", sorted(scope)],
				"status": ["!=", "Gelöscht"],
			},
			fields=["name", "subject", "sender_email", "received_at", "thread_id", "has_attachment"],
			order_by="received_at desc, name asc",
			limit_page_length=1021,
		)
	if len(rows) > 1000:
		raise EmailDraftError("LIMIT_EXCEEDED", "Mehr als 1.000 Archivnachrichten; Scope eingrenzen.")
	rows = [row for row in rows if frappe.has_permission(SOURCE, "read", doc=row.name)]
	candidates = rows[offset : offset + limit]
	page, next_offset = [], offset

	def result(budget_limited=False):
		return {
			"identity": identity,
			"archive_account": account.name,
			"messages": page,
			"indexed_total_count": len(rows),
			"returned": len(page),
			"has_more": next_offset < len(rows),
			"next_offset": next_offset if next_offset < len(rows) else None,
			"output_budget_limited": budget_limited,
			"coverage": {
				"source": "permission_checked_archive_index",
				"scope": "explicit_contract_folders",
				"mailbox_complete": False,
				"returned_messages_verified_live": True,
				"initial_sync_completed": bool(account.initial_sync_completed),
				"last_sync_on": account.last_sync_on,
			},
		}

	provider = _provider(account) if candidates else None
	for candidate in candidates:
		try:
			_source_doc, mail = _source(candidate.name, account, identity, provider, (scope, _folders))
		except EmailDraftError as error:
			if error.code in {"MESSAGE_MISMATCH", "MESSAGE_NOT_FOUND", "INVALID_SOURCE"}:
				next_offset += 1
				continue
			raise
		page.append(_summary(mail, candidate.name))
		next_offset += 1
		if not fits_data(result(True)):
			page.pop()
			next_offset -= 1
			if not page:
				raise EmailDraftError(
					"LIMIT_EXCEEDED", "Metadaten einer Mail überschreiten das Ausgabebudget."
				)
			return result(True)
	return result()


@_endpoint()
def get_email_context(mietvertrag, message, limit=5, body_offset=0, body_limit=4000):
	_contract_doc, identity = _contract(mietvertrag)
	source = _read(SOURCE, message)
	account = _account(source.archive_account)
	provider = _provider(account)
	scope = _folder_scope(account, identity)
	source, mail = _source(message, account, identity, provider, scope)
	limit = _integer(limit, 5, 1, 10)
	body_offset = _integer(body_offset, 0, 0, 50000)
	body_limit = _integer(body_limit, 4000, 1, 6000)
	text = mail.text_body
	if not text and (mail.raw.get("htmlBody") or mail.raw.get("textBody")):
		raise EmailDraftError("BODY_UNAVAILABLE", "Nachrichtentext nicht verfügbar; in Thunderbird prüfen.")
	if body_offset > len(text):
		raise EmailDraftError("INVALID_ARGUMENT", "body_offset liegt hinter dem Nachrichtentext.")
	thread = []
	rows = (
		frappe.get_list(
			SOURCE,
			filters={
				"archive_account": account.name,
				"thread_id": mail.thread_id,
				"actual_mailbox_id": ["in", sorted(scope[0])],
				"status": ["!=", "Gelöscht"],
				"name": ["!=", source.name],
			},
			fields=["name", "subject", "sender_email", "received_at", "preview", "has_attachment"],
			order_by="received_at desc, name asc",
			limit_page_length=limit + 1,
		)
		if mail.thread_id
		else []
	)
	for row in rows[:limit]:
		# Index metadata can lag behind a mailbox move. Verify each neighbour live
		# before returning any content under the requested contract identity.
		try:
			_neighbour, neighbour = _source(row.name, account, identity, provider, scope)
		except EmailDraftError as error:
			if error.code in {"MESSAGE_MISMATCH", "MESSAGE_NOT_FOUND"}:
				continue
			raise
		thread.append(
			{**_summary(neighbour, row.name), "preview": neighbour.text_body[:100], "body_complete": False}
		)
	body_quality = _body_quality(mail)
	next_offset = min(body_offset + body_limit, len(text))
	return fit_context(
		{
			"identity": identity,
			"archive_account": account.name,
			"source": {
				**_summary(mail, source.name),
				"body": text[body_offset:next_offset],
				"body_offset": body_offset,
				"body_characters_available": len(text),
				"body_complete": body_offset == 0
				and next_offset == len(text)
				and not any(body_quality.values()),
				"next_body_offset": next_offset if next_offset < len(text) else None,
				"provider_body_truncated": body_quality["truncated"],
				"provider_body_encoding_problem": body_quality["encoding_problem"],
				"body_text_source": mail.raw.get("body_text_source", "plain"),
			},
			"thread": thread,
			"coverage": {
				"thread_complete": False,
				"thread_has_more": len(rows) > limit,
				"scope": "indexed_contract_folder_messages",
				"attachments_loaded": False,
				"content_is_external": True,
			},
		}
	)


class _DraftBackend:
	def __init__(self, account, *, connect=True):
		self.account = account
		self.provider = _provider(account) if connect else None
		self.site, self.user = frappe.local.site, frappe.session.user

	def lock(self, key):
		return frappe.cache().lock(
			f"hv-email-draft:{key}",
			timeout=max(
				300, int(self.account.request_timeout or 30) * (8 + 2 * getattr(self, "attachment_count", 0))
			),
			blocking_timeout=5,
		)

	def reserve(self, key, digest, payload):
		name = frappe.db.get_value(DRAFT, {"draft_request_key": key}, "name")
		if name:
			doc = _read(DRAFT, name)
			if (
				doc.owner != self.user
				or doc.mail_archive_account != self.account.name
				or doc.reference_name != payload["identity"]["mietvertrag"]
			):
				raise EmailDraftError("REQUEST_CONFLICT", "request_id ist bereits anders gebunden.")
			if doc.status == "Cancelled":
				raise EmailDraftError(
					"REQUEST_CLOSED", "Dieser Auftrag wurde manuell verworfen; kein neuer Entwurf erstellt."
				)
			if doc.mailbox_sync_paused and doc.mailbox_pause_reason != "Rejected":
				raise EmailDraftError(
					"TRACKING_PAUSED", "Abgleich pausiert. In ERPNext prüfen und bei Bedarf fortsetzen."
				)
			return self._record(doc), True
		token = uuid.uuid4().hex
		doc = frappe.get_doc(
			{
				"doctype": DRAFT,
				"status": "Draft",
				"delivery_backend": "Stalwart",
				"orchestrator_backend": "local",
				"sender": payload["sender"],
				"recipients": ", ".join(payload["recipients"]),
				"cc": ", ".join(payload["cc"]),
				"subject": payload["subject"],
				"message": html.escape(payload["message"]).replace("\n", "<br>"),
				"reference_doctype": "Mietvertrag",
				"reference_name": payload["identity"]["mietvertrag"],
				"mail_archive_account": self.account.name,
				"source_mail_message": payload["reply_to_message"],
				"draft_request_key": key,
				"draft_fingerprint": digest,
				"draft_attachment_manifest": json.dumps(payload.get("attachments", []), ensure_ascii=False),
				"draft_token": token,
				"draft_rfc_message_id": f"{token}@{payload['sender'].split('@', 1)[1]}",
				"mailbox_sync_status": "Pending",
				"mailbox_sync_paused": 1,
				"mailbox_pause_reason": "Rejected",
			}
		).insert(ignore_permissions=True)
		# A remote create may succeed even if the HTTP reply or later DB write fails.
		frappe.db.commit()
		return self._record(doc), False

	def _record(self, doc):
		return {
			"name": doc.name,
			"fingerprint": doc.draft_fingerprint,
			"draft_token": doc.draft_token,
			"rfc_message_id": doc.draft_rfc_message_id,
			"creation_started": bool(doc.remote_creation_started),
			"provider_message_id": doc.provider_draft_id,
			"doc": doc,
		}

	def mark_creation_started(self, record):
		# Redis leases can expire during slow mailbox queries. This row lock
		# is the final, transactional guard against a second remote create.
		self._lock_record(record["name"])
		doc = record["doc"]
		_reload_locked(doc)
		if doc.remote_creation_started or doc.provider_draft_id or doc.sent_provider_message_id:
			raise EmailDraftError(
				"REMOTE_STATE_UNCERTAIN",
				"Entwurfserstellung bereits beansprucht; dieselbe request_id später prüfen.",
			)
		if (
			doc.status != "Draft"
			or doc.delivery_backend != "Stalwart"
			or doc.mail_archive_account != self.account.name
			or doc.draft_fingerprint != record["fingerprint"]
			or (doc.mailbox_sync_paused and doc.mailbox_pause_reason != "Rejected")
		):
			raise EmailDraftError(
				"TRACKING_PAUSED", "Auftrag ist geschlossen, pausiert oder wurde verändert."
			)
		attempt = uuid.uuid4().hex
		doc.db_set(
			{
				"remote_creation_started": 1,
				"remote_creation_attempt": attempt,
				"mailbox_sync_paused": 0,
				"mailbox_pause_reason": "",
				"mailbox_missing_count": 0,
				"mailbox_next_check_on": None,
			},
			update_modified=False,
		)
		record["creation_started"] = True
		record["creation_attempt"] = attempt
		frappe.db.commit()

	def _lock_record(self, name):
		rows = frappe.db.sql("SELECT name FROM `tabEmail Entwurf` WHERE name=%s FOR UPDATE", (name,))
		if not rows:
			raise EmailDraftError("NOT_FOUND", "Entwurfsauftrag nicht verfügbar.")

	def create_draft(self, **arguments):
		from thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.providers.base import (
			DraftNotCreatedError,
		)

		try:
			return self.provider.create_draft(**arguments)
		except DraftNotCreatedError as error:
			raise DraftCreationRejected(str(error)) from error

	def release_creation_claim(self, record):
		self._lock_record(record["name"])
		doc = record["doc"]
		_reload_locked(doc)
		if (
			not record.get("creation_attempt")
			or doc.remote_creation_attempt != record["creation_attempt"]
			or not doc.remote_creation_started
			or doc.status != "Draft"
			or doc.delivery_backend != "Stalwart"
			or doc.mail_archive_account != self.account.name
			or doc.draft_fingerprint != record["fingerprint"]
			or doc.provider_draft_id
			or doc.sent_provider_message_id
			or doc.communication
		):
			raise EmailDraftError(
				"REMOTE_STATE_UNCERTAIN",
				"Erstellungsversuch nicht eindeutig zugeordnet; Claim bleibt erhalten.",
			)
		pause_reason = (
			"Manual" if doc.mailbox_sync_paused and doc.mailbox_pause_reason == "Manual" else "Rejected"
		)
		doc.db_set(
			{
				"remote_creation_started": 0,
				"remote_creation_attempt": "",
				"mailbox_sync_status": "Rejected",
				"mailbox_sync_paused": 1,
				"mailbox_pause_reason": pause_reason,
				"mailbox_next_check_on": None,
				"mailbox_checked_on": now_datetime(),
				"last_send_error": "Kein Entwurf angelegt. Ursache beheben und dieselbe request_id erneut verwenden.",
			},
			update_modified=False,
		)
		frappe.db.commit()
		record["creation_started"] = False
		record["creation_attempt"] = ""

	def record_created(self, record, remote_id):
		self._lock_record(record["name"])
		doc = _reload_locked(record["doc"])
		if (
			doc.remote_creation_attempt != record.get("creation_attempt")
			or not doc.remote_creation_started
			or doc.delivery_backend != "Stalwart"
			or doc.mail_archive_account != self.account.name
			or doc.draft_fingerprint != record["fingerprint"]
		):
			raise EmailDraftError(
				"REMOTE_STATE_UNCERTAIN",
				"Erfolgreicher Mailserver-Aufruf gehört nicht zum aktuellen Erstellungsversuch.",
			)
		if doc.status == "Sent":
			record["mailbox_state"] = "Sent"
		elif doc.status == "Draft" and not doc.mailbox_sync_paused:
			doc.db_set(
				{
					"provider_draft_id": remote_id,
					"mailbox_sync_status": "Draft",
					"mailbox_checked_on": now_datetime(),
				},
				update_modified=False,
			)
		elif not doc.provider_draft_id:
			# Keep a late successful create identifiable even after human discard/pause.
			# Do not reopen or change the user's tracking decision.
			doc.db_set("provider_draft_id", remote_id, update_modified=False)
		record["provider_message_id"] = doc.provider_draft_id or remote_id
		frappe.db.commit()

	def record_remote(self, record, state, remote):
		_persist_remote(record["doc"], state, remote, self.account)
		record["provider_message_id"] = remote.id
		frappe.db.commit()

	def result(self, record, state, remote, reused):
		if remote is None:
			state = record.get("mailbox_state", state)
		return {
			"draft": record["name"],
			"archive_account": self.account.name,
			"provider_message_id": remote.id if remote else record["provider_message_id"],
			"mailbox_state": state,
			"reused": reused,
			"review_in": "Thunderbird",
			"url": f"/app/email-entwurf/{record['name']}",
		}


@_endpoint(write=True)
def create_email_draft(
	mietvertrag,
	archive_account,
	subject,
	message,
	request_id,
	recipients=None,
	cc=None,
	reply_to_message=None,
	sender=None,
	attachments=None,
):
	contract, identity = _contract(mietvertrag)
	account = _account(archive_account)
	partners, defaults = _partner_addresses(contract)
	files = prepare_attachments(attachments, lambda name: _attachment_file(name, identity))
	backend = _DraftBackend(account)
	backend.attachment_count = len(files)
	reply = None
	if reply_to_message:
		_source_doc, reply = _source(reply_to_message, account, identity, backend.provider)
	payload = prepare_payload(
		identity=identity,
		archive_account=account.name,
		own_addresses=configured_addresses(account.email_addresses),
		partner_addresses=partners,
		default_recipients=defaults,
		subject=subject,
		message=message,
		recipients=recipients,
		cc=cc,
		sender=sender,
		reply=reply,
		reply_to_message=reply_to_message,
	)
	if files:
		payload["attachments"] = attachment_manifest(files)
	result = create_remote_draft(backend, payload, request_id, **({"attachments": files} if files else {}))
	return {**result, "attachment_count": len(files)}


def _live_state(doc, account):
	provider = _provider(account)
	matches = provider.find_draft_messages(doc.draft_token)
	return classify_remote(
		matches, draft_token=doc.draft_token, sender=doc.sender, mailboxes=provider.list_mailboxes()
	)


@_endpoint()
def get_email_draft(draft):
	doc = _read(DRAFT, draft)
	if doc.delivery_backend != "Stalwart" or doc.reference_doctype != "Mietvertrag":
		raise EmailDraftError("INVALID_DRAFT", "Kein Stalwart-Mieterentwurf.")
	_contract_doc, identity = _contract(doc.reference_name)
	account = _account(doc.mail_archive_account)
	state, remote = _live_state(doc, account)
	body_quality = _body_quality(remote) if remote else {"truncated": False, "encoding_problem": False}
	body_available = bool(
		remote and (remote.text_body or not (remote.raw.get("textBody") or remote.raw.get("htmlBody")))
	)
	return fit_preview(
		{
			"draft": doc.name,
			"identity": identity,
			"archive_account": account.name,
			"mailbox_state": state,
			"provider_message_id": remote.id if remote else None,
			"message": {
				**_summary(remote),
				"body_preview": remote.text_body[:2000],
				"body_available": body_available,
				"body_complete": body_available
				and len(remote.text_body) <= 2000
				and not any(body_quality.values()),
				"provider_body_truncated": body_quality["truncated"],
				"provider_body_encoding_problem": body_quality["encoding_problem"],
			}
			if remote
			else None,
			"stored_status": doc.status,
			"sync_paused": bool(doc.mailbox_sync_paused),
			"pause_reason": doc.mailbox_pause_reason,
			"next_check_on": doc.mailbox_next_check_on,
			"communication": doc.communication,
			"review_in": "Thunderbird",
			"coverage": {
				"live_mailbox_read": True,
				"database_updated": False,
				"send_evidence": "sent_folder_copy",
				"delivery_confirmed": False,
			},
		}
	)


def _persist_remote(doc, state, remote, account):
	frappe.db.sql("SELECT name FROM `tabEmail Entwurf` WHERE name=%s FOR UPDATE", (doc.name,))
	_reload_locked(doc)
	if doc.delivery_backend != "Stalwart" or doc.mail_archive_account != account.name:
		raise EmailDraftError("REMOTE_CONFLICT", "Postfachzuordnung wurde während des Abgleichs geändert.")
	if doc.status != "Draft" or doc.mailbox_sync_paused:
		return
	now = now_datetime()
	updates = {"mailbox_sync_status": state, "mailbox_checked_on": now, "last_send_error": ""}
	if state == "Missing":
		missing_count = int(doc.mailbox_missing_count or 0) + 1
		updates.update(
			{
				"mailbox_missing_count": missing_count,
				"mailbox_next_check_on": now
				+ timedelta(minutes=min(5 * 2 ** min(missing_count - 1, 8), 1440)),
			}
		)
		if missing_count >= MISSING_PAUSE_THRESHOLD:
			updates.update(
				{
					"mailbox_sync_paused": 1,
					"mailbox_pause_reason": "Missing",
					"mailbox_next_check_on": None,
					"last_send_error": "Entwurfskennung mehrfach nicht gefunden. Abgleich pausiert; bitte manuell prüfen.",
				}
			)
	else:
		updates.update({"mailbox_missing_count": 0, "mailbox_next_check_on": None})
	if remote:
		updates["provider_draft_id"] = remote.id
	if state == "Sent" and remote:
		_contract(doc.reference_name)
		if not remote.text_body and (remote.raw.get("htmlBody") or remote.raw.get("textBody")):
			raise EmailDraftError(
				"BODY_UNAVAILABLE",
				"Gesendeter Nachrichtentext nicht verfügbar; keine leere Communication gespeichert.",
			)
		if any(_body_quality(remote).values()):
			raise EmailDraftError(
				"BODY_INCOMPLETE",
				"Gesendeter Nachrichtentext ist gekürzt oder enthält Dekodierungsfehler; keine unvollständige Communication gespeichert.",
			)
		from thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.sync import _message_date

		sent_on = _message_date(remote.raw.get("sentAt")) or now_datetime()
		communication = (
			frappe.get_doc("Communication", doc.communication)
			if doc.communication
			else frappe.new_doc("Communication")
		)
		if doc.communication and (
			communication.reference_doctype != doc.reference_doctype
			or communication.reference_name != doc.reference_name
			or communication.communication_medium != "Email"
			or communication.sent_or_received != "Sent"
		):
			raise EmailDraftError(
				"COMMUNICATION_CONFLICT",
				"Vorhandene Communication gehört nicht zu diesem gesendeten Vertragsentwurf.",
			)
		communication.update(
			{
				"communication_medium": "Email",
				"communication_type": "Communication",
				"sent_or_received": "Sent",
				"subject": remote.subject,
				"sender": doc.sender,
				"recipients": ", ".join(item["email"] for item in remote.to),
				"cc": ", ".join(item["email"] for item in remote.cc),
				"content": html.escape(remote.text_body).replace("\n", "<br>"),
				"content_type": "text/html",
				"reference_doctype": doc.reference_doctype,
				"reference_name": doc.reference_name,
				"communication_date": sent_on,
			}
		)
		if communication.is_new():
			communication.insert(ignore_permissions=True)
		else:
			communication.save(ignore_permissions=True)
		updates.update(
			{
				"status": "Sent",
				"sent_on": doc.sent_on or sent_on,
				"communication": communication.name,
				"sent_provider_message_id": remote.id,
			}
		)
	doc.db_set(updates, update_modified=False)


def manage_mailbox_tracking(draft, action):
	"""Human Desk action; changes ERP tracking only, never mail or the creation claim."""
	frappe.only_for(("System Manager", "Hausverwalter"))
	if not isinstance(action, str) or action not in {"pause", "resume", "discard"}:
		raise EmailDraftError("INVALID_ARGUMENT", "Unbekannte Abgleichsaktion.")
	doc = _read(DRAFT, draft)
	if doc.delivery_backend != "Stalwart" or doc.reference_doctype != "Mietvertrag":
		raise EmailDraftError("INVALID_DRAFT", "Kein Stalwart-Mieterauftrag.")
	account = _read(ACCOUNT, doc.mail_archive_account)
	_read("Mietvertrag", doc.reference_name)
	backend = _DraftBackend(account, connect=False)
	with backend.lock(doc.draft_request_key):
		backend._lock_record(doc.name)
		_reload_locked(doc)
		if (
			doc.delivery_backend != "Stalwart"
			or doc.mail_archive_account != account.name
			or doc.status != "Draft"
		):
			raise EmailDraftError("INVALID_DRAFT", "Nur offene Stalwart-Aufträge können verwaltet werden.")
		if (
			action == "resume"
			and not doc.remote_creation_started
			and not doc.provider_draft_id
			and doc.mailbox_pause_reason != "Manual"
		):
			raise EmailDraftError(
				"DRAFT_NOT_CREATED",
				"Noch kein Entwurf angelegt. Erstellung mit derselben request_id erneut versuchen.",
			)
		updates = {
			"mailbox_sync_paused": int(action != "resume"),
			"mailbox_pause_reason": "Manual" if action != "resume" else "",
			"mailbox_next_check_on": None,
			"mailbox_missing_count": 0,
		}
		if action == "discard":
			updates["status"] = "Cancelled"
		doc.db_set(updates, update_modified=False)
		frappe.db.commit()
	return {"draft": doc.name, "action": action, "mailbox_changed": False}


def sync_stalwart_email_drafts():
	"""Scheduler: reconcile actual sent copies; no enqueue/send actions."""
	if "thunderbird_hausverwaltung" not in frappe.get_installed_apps():
		return
	for row in frappe.get_all(
		DRAFT,
		filters={"delivery_backend": "Stalwart", "status": "Draft", "mailbox_sync_paused": 0},
		or_filters=[
			["mailbox_next_check_on", "is", "not set"],
			["mailbox_next_check_on", "<=", now_datetime()],
		],
		fields=["name"],
		order_by="mailbox_checked_on asc, creation asc",
		limit_page_length=50,
	):
		doc = frappe.get_doc(DRAFT, row.name)
		try:
			account = frappe.get_doc(ACCOUNT, doc.mail_archive_account)
			if not account.enabled:
				continue
			with _DraftBackend(account).lock(doc.draft_request_key):
				_reload_locked(doc)
				if doc.status != "Draft" or doc.mailbox_sync_paused:
					continue
				if doc.mailbox_next_check_on and get_datetime(doc.mailbox_next_check_on) > now_datetime():
					continue
				if not doc.remote_creation_started and not doc.provider_draft_id:
					doc.db_set(
						{
							"mailbox_sync_paused": 1,
							"mailbox_pause_reason": "Rejected",
							"mailbox_next_check_on": None,
							"last_send_error": "Erstellung noch nicht gestartet. Dieselbe request_id erneut verwenden.",
						},
						update_modified=False,
					)
					frappe.db.commit()
					continue
				frappe.db.commit()
				state, remote = _live_state(doc, account)
				_persist_remote(doc, state, remote, account)
				frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			error_traceback = frappe.get_traceback()
			frappe.db.sql("SELECT name FROM `tabEmail Entwurf` WHERE name=%s FOR UPDATE", (row.name,))
			_reload_locked(doc)
			if doc.delivery_backend == "Stalwart" and doc.status == "Draft" and not doc.mailbox_sync_paused:
				doc.db_set(
					{
						"mailbox_sync_status": "Error",
						"mailbox_checked_on": now_datetime(),
						"mailbox_next_check_on": now_datetime() + timedelta(hours=1),
						"last_send_error": "Postfachstatus konnte nicht eindeutig abgeglichen werden.",
					},
					update_modified=False,
				)
			frappe.db.commit()
			frappe.log_error(title="Stalwart Entwurfsabgleich", message=error_traceback)
