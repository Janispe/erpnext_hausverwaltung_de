"""Protocol-independent rules for tenant mail drafts; never submits mail."""

from __future__ import annotations

import hashlib
import json
import re
from email.utils import parseaddr


class EmailDraftError(Exception):
	def __init__(self, code: str, message: str):
		super().__init__(message)
		self.code = code
		self.message = message


def exact_name(value, label):
	if not isinstance(value, str) or not value.strip() or len(value) > 240:
		raise EmailDraftError("INVALID_ARGUMENT", f"{label}: exakte ID erforderlich.")
	return value.strip()


def addresses(values, *, required=False):
	if values is None:
		values = []
	if not isinstance(values, (list, tuple)) or len(values) > 20:
		raise EmailDraftError(
			"INVALID_ARGUMENT", "Empfänger müssen eine Liste mit höchstens 20 Adressen sein."
		)
	result = []
	for value in values:
		if not isinstance(value, str):
			raise EmailDraftError("INVALID_ARGUMENT", "Ungültige E-Mail-Adresse.")
		value = value.strip().casefold()
		if (
			not value
			or len(value) > 254
			or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
			or parseaddr(value)[1] != value
			or not re.fullmatch(r"[^@<>(),;:\s]+@[^@<>(),;:\s]+\.[^@<>(),;:\s]+", value)
		):
			raise EmailDraftError("INVALID_ARGUMENT", "Ungültige E-Mail-Adresse.")
		if value not in result:
			result.append(value)
	if required and not result:
		raise EmailDraftError(
			"MISSING_RECIPIENT", "Mindestens ein Vertragspartner mit E-Mail-Adresse ist erforderlich."
		)
	return result


def configured_addresses(value):
	return addresses([item.strip() for item in re.split(r"[\n,;]", value or "") if item.strip()])


def message_ids(values):
	if not isinstance(values, (list, tuple)) or len(values) > 100:
		raise EmailDraftError("INVALID_REPLY_HEADERS", "Ungültige oder zu viele Antwort-Header.")
	result = []
	for value in values or ():
		if not isinstance(value, str):
			raise EmailDraftError("INVALID_REPLY_HEADERS", "Ungültige Antwort-Header.")
		value = value.strip()
		if value.startswith("<") and value.endswith(">"):
			value = value[1:-1]
		if (
			not value
			or len(value) > 998
			or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
			or "<" in value
			or ">" in value
		):
			raise EmailDraftError(
				"INVALID_REPLY_HEADERS", "Die Ausgangsmail enthält ungültige Antwort-Header."
			)
		if value not in result:
			result.append(value)
	return result


def prepare_payload(
	*,
	identity,
	archive_account,
	own_addresses,
	partner_addresses,
	default_recipients,
	subject,
	message,
	recipients=None,
	cc=None,
	sender=None,
	reply=None,
	reply_to_message=None,
):
	if (
		not isinstance(subject, str)
		or not subject.strip()
		or len(subject) > 500
		or any(ord(char) < 32 or ord(char) == 127 for char in subject)
	):
		raise EmailDraftError("INVALID_ARGUMENT", "Betreff erforderlich (höchstens 500 Zeichen, eine Zeile).")
	try:
		body_bytes = len(message.encode()) if isinstance(message, str) else 0
	except UnicodeError:
		raise EmailDraftError("INVALID_ARGUMENT", "Nachricht enthält ungültige Unicode-Zeichen.")
	if (
		not isinstance(message, str)
		or not message.strip()
		or len(message) > 20_000
		or body_bytes > 50_000
		or "\x00" in message
	):
		raise EmailDraftError(
			"INVALID_ARGUMENT", "Nachricht erforderlich (höchstens 20.000 Zeichen / 50.000 UTF-8-Bytes)."
		)
	own = addresses(own_addresses, required=True)
	if sender is None:
		if len(own) != 1:
			raise EmailDraftError(
				"AMBIGUOUS_SENDER", "Mehrere eigene Adressen: Absender ausdrücklich auswählen."
			)
		sender = own[0]
	else:
		sender = addresses([sender], required=True)[0]
	if sender not in own:
		raise EmailDraftError("INVALID_SENDER", "Absender gehört nicht zum ausgewählten Postfach.")
	partners = set(addresses(partner_addresses))
	if recipients is None:
		if reply is not None:
			reply_to = reply.raw.get("replyTo") or reply.sender
			recipients = [item.get("email", "") for item in reply_to]
		else:
			recipients = default_recipients
	to = addresses(recipients, required=True)
	copy = [item for item in addresses(cc) if item not in to]
	if len(to) + len(copy) > 20:
		raise EmailDraftError(
			"INVALID_ARGUMENT", "To und CC dürfen zusammen höchstens 20 Empfänger enthalten."
		)
	if any(item not in partners for item in to) or any(item not in partners | set(own) for item in copy):
		raise EmailDraftError(
			"RECIPIENT_MISMATCH", "Empfänger gehört nicht zu den Vertragspartnern dieses Mietvertrags."
		)
	in_reply_to = message_ids(reply.rfc_message_ids) if reply else []
	if reply and not in_reply_to:
		raise EmailDraftError(
			"MISSING_REPLY_ID",
			"Die Ausgangsmail hat keine RFC Message-ID; kein verlässlicher Antwortentwurf möglich.",
		)
	references = message_ids(reply.references or reply.in_reply_to) if reply else []
	for item in in_reply_to:
		if item not in references:
			references.append(item)
	return {
		"identity": identity,
		"archive_account": archive_account,
		"sender": sender,
		"recipients": to,
		"cc": copy,
		"subject": subject.strip(),
		"message": message,
		"reply_to_message": reply_to_message or "",
		"in_reply_to": in_reply_to,
		"references": references,
	}


def fingerprint(payload):
	return hashlib.sha256(
		json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
	).hexdigest()


def request_key(site, user, request_id):
	if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
		raise EmailDraftError(
			"INVALID_ARGUMENT",
			"request_id erforderlich (höchstens 128 Zeichen); bei Wiederholung beibehalten.",
		)
	return hashlib.sha256(f"{site}\0{user}\0{request_id.strip()}".encode()).hexdigest()


def classify_remote(messages, *, draft_token, sender, mailboxes):
	"""Absence and removal of $draft do not prove that mail was sent."""
	roles = {mailbox.id: mailbox.role for mailbox in mailboxes}
	drafts, sent, other = [], [], []
	for item in messages:
		if item.raw.get("header:X-Hausverwaltung-Draft-ID:asText") != draft_token:
			raise EmailDraftError(
				"REMOTE_CONFLICT", "Entwurfskennung auf dem Mailserver stimmt nicht überein."
			)
		if {entry.get("email", "").casefold() for entry in item.sender} != {sender.casefold()}:
			raise EmailDraftError("REMOTE_CONFLICT", "Absender des verknüpften Mailentwurfs wurde geändert.")
		item_roles = {roles.get(mailbox_id) for mailbox_id in item.mailbox_ids}
		if "$draft" in item.keywords and "drafts" in item_roles:
			drafts.append(item)
		elif "$draft" not in item.keywords and "sent" in item_roles:
			sent.append(item)
		else:
			other.append(item)
	if len(sent) > 1 or len(drafts) > 1 or other:
		raise EmailDraftError(
			"REMOTE_CONFLICT", "Mehrdeutige oder verschobene Entwurfsreferenz; manuell prüfen."
		)
	if sent:
		return "Sent", sent[0]
	if drafts:
		return "Draft", drafts[0]
	return "Missing", None


def create_remote_draft(backend, payload, request_id):
	"""Reserve before the remote side effect, reconcile retries, never blindly repeat a create."""
	key = request_key(backend.site, backend.user, request_id)
	digest = fingerprint(payload)
	with backend.lock(key):
		record, reused = backend.reserve(key, digest, payload)
		if record["fingerprint"] != digest:
			raise EmailDraftError(
				"REQUEST_CONFLICT", "request_id wurde bereits für einen anderen Entwurf verwendet."
			)
		matches = backend.provider.find_draft_messages(record["draft_token"])
		mailboxes = backend.provider.list_mailboxes()
		state, remote = classify_remote(
			matches,
			draft_token=record["draft_token"],
			sender=payload["sender"],
			mailboxes=mailboxes,
		)
		if remote is not None:
			backend.record_remote(record, state, remote)
			return backend.result(record, state, remote, reused=True)
		if record.get("creation_started"):
			raise EmailDraftError(
				"REMOTE_STATE_UNCERTAIN",
				"Der frühere Mailserver-Aufruf ist nicht eindeutig auflösbar. Kein weiterer Entwurf angelegt; mit derselben request_id später prüfen.",
			)
		mailboxes = [item for item in mailboxes if item.role == "drafts"]
		if len(mailboxes) != 1:
			raise EmailDraftError(
				"DRAFT_MAILBOX_CONFLICT", "Genau ein Entwürfe-Ordner im Postfach erforderlich."
			)
		backend.mark_creation_started(record)
		remote_id = backend.provider.create_draft(
			mailbox_id=mailboxes[0].id,
			sender=payload["sender"],
			recipients=payload["recipients"],
			cc=payload["cc"],
			subject=payload["subject"],
			text_body=payload["message"],
			draft_token=record["draft_token"],
			rfc_message_id=record["rfc_message_id"],
			in_reply_to=tuple(payload["in_reply_to"]),
			references=tuple(payload["references"]),
		)
		# Persist the provider ID even if the subsequent read fails or is temporarily stale.
		backend.record_created(record, remote_id)
		return backend.result(record, "Draft", None, reused=reused)
