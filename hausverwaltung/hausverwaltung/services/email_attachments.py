"""Bounded binary attachments; never fetch URLs or interpret file contents."""

import base64
import binascii
import hashlib
import mimetypes
import re

from .email_draft_contract import EmailDraftError, exact_name

MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_BASE64_CHARS = 4 * ((MAX_ATTACHMENT_BYTES + 2) // 3)


def attachment_metadata(filename, content_type=None):
	if (
		not isinstance(filename, str)
		or not filename.strip()
		or len(filename) > 200
		or filename.strip() in {".", ".."}
		or any(ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in filename)
	):
		raise EmailDraftError(
			"INVALID_ATTACHMENT", "Anhang benötigt einen Dateinamen ohne Pfad (maximal 200 Zeichen)."
		)
	filename = filename.strip()
	if content_type is None:
		content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
	if not isinstance(content_type, str) or not re.fullmatch(
		r"[A-Za-z0-9!#$&^_.+-]{1,80}/[A-Za-z0-9!#$&^_.+-]{1,80}", content_type
	):
		raise EmailDraftError("INVALID_ATTACHMENT", "Ungültiger MIME-Typ für den Anhang.")
	return filename, content_type.lower()


def prepare_attachments(values, load_file):
	"""load_file must enforce File/parent permissions and return filename, raw bytes."""
	if values is None:
		return []
	if not isinstance(values, list) or len(values) > MAX_ATTACHMENTS:
		raise EmailDraftError("INVALID_ATTACHMENT", "Höchstens 10 Anhänge als Liste erlaubt.")
	result, total = [], 0
	for value in values:
		if not isinstance(value, dict):
			raise EmailDraftError("INVALID_ATTACHMENT", "Anhang muss eine Datei-ID oder Base64-Datei sein.")
		if "file" in value:
			if set(value) != {"file"}:
				raise EmailDraftError(
					"INVALID_ATTACHMENT", "Dateireferenz darf keinen zusätzlichen Inhalt enthalten."
				)
			file_id = exact_name(value["file"], "File")
			filename, content = load_file(file_id)
			filename, content_type = attachment_metadata(filename)
		else:
			if not {"filename", "content_base64"} <= set(value) or set(value) - {
				"filename",
				"content_base64",
				"content_type",
			}:
				raise EmailDraftError(
					"INVALID_ATTACHMENT",
					"Dateiname und Base64-Inhalt erforderlich; keine URLs oder Dateipfade.",
				)
			filename, content_type = attachment_metadata(value["filename"], value.get("content_type"))
			encoded = value["content_base64"]
			if not isinstance(encoded, str) or len(encoded) > MAX_BASE64_CHARS:
				raise EmailDraftError(
					"ATTACHMENT_TOO_LARGE", "Anhang überschreitet 10 MiB oder enthält kein Base64."
				)
			try:
				content = base64.b64decode(encoded, validate=True)
				if base64.b64encode(content).decode("ascii") != encoded:
					raise ValueError("Non-canonical Base64")
			except (ValueError, binascii.Error):
				raise EmailDraftError("INVALID_ATTACHMENT", "Anhang enthält ungültiges Base64.") from None
		if not isinstance(content, bytes):
			raise EmailDraftError("INVALID_ATTACHMENT", "Anhang muss unveränderte Binärdaten enthalten.")
		total += len(content)
		if len(content) > MAX_ATTACHMENT_BYTES or total > MAX_TOTAL_ATTACHMENT_BYTES:
			raise EmailDraftError(
				"ATTACHMENT_TOO_LARGE", "Maximal 10 MiB je Anhang und 20 MiB insgesamt erlaubt."
			)
		result.append({"filename": filename, "content_type": content_type, "content": content})
	return result


def attachment_manifest(attachments):
	return [
		{
			"filename": item["filename"],
			"content_type": item["content_type"],
			"size": len(item["content"]),
			"sha256": hashlib.sha256(item["content"]).hexdigest(),
		}
		for item in attachments
	]


def audit_attachments(values):
	"""Bounded audit metadata, including rejected calls; never retain binary input."""
	if not isinstance(values, list):
		return {"redacted": True, "invalid_structure": True}
	result = []
	for value in values[:MAX_ATTACHMENTS]:
		if not isinstance(value, dict):
			result.append({"redacted": True, "invalid_structure": True})
			continue
		item = {
			key: value[key][:limit]
			for key, limit in (("file", 140), ("filename", 200), ("content_type", 161))
			if isinstance(value.get(key), str)
		}
		# Use an allowlist so malformed/unknown nested fields cannot carry file data.
		if "content_base64" in value:
			encoded = value["content_base64"]
			item["content_redacted"] = True
			item["encoded_chars"] = len(encoded) if isinstance(encoded, str) else None
			if isinstance(encoded, str) and len(encoded) <= MAX_BASE64_CHARS:
				try:
					content = base64.b64decode(encoded, validate=True)
					if base64.b64encode(content).decode("ascii") != encoded:
						raise ValueError("Non-canonical Base64")
					item["size"] = len(content)
					item["sha256"] = hashlib.sha256(content).hexdigest()
				except (ValueError, binascii.Error):
					item["invalid_content"] = True
			else:
				item["invalid_or_oversized_content"] = True
		result.append(item)
	if len(values) > MAX_ATTACHMENTS:
		result.append({"omitted_attachments": len(values) - MAX_ATTACHMENTS})
	return result
