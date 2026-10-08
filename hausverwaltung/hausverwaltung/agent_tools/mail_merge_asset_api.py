"""Upload local letter assets from code; binary data never belongs in model context."""

import base64
import binascii
import hashlib
import re
from io import BytesIO

import frappe
from PIL import Image

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as api
from hausverwaltung.hausverwaltung.agent_tools import template_authoring_api as author
from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BASE64_CHARS = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
TARGETS = ("Serienbrief Vorlage", "Serienbrief Textbaustein")


def _decode(content_base64):
	if not isinstance(content_base64, str) or not 0 < len(content_base64) <= MAX_BASE64_CHARS:
		raise AgentToolError("INVALID_ASSET", "Datei benötigt Base64-Inhalt mit maximal 10 MiB.")
	try:
		content = base64.b64decode(content_base64, validate=True)
	except (ValueError, binascii.Error):
		raise AgentToolError("INVALID_ASSET", "Ungültiger Base64-Dateiinhalt.") from None
	if not content or len(content) > MAX_FILE_BYTES:
		raise AgentToolError("INVALID_ASSET", "Datei ist leer oder größer als 10 MiB.")
	return content


def asset_info(content):
	from mail_merge.mail_merge.utils.assistant_assets import pdf_info

	if content.startswith(b"%PDF-"):
		try:
			return {"extension": "pdf", "mime_type": "application/pdf", **pdf_info(content)}
		except frappe.ValidationError as exc:
			raise AgentToolError("INVALID_ASSET", str(exc)) from None
	if len(content) > MAX_IMAGE_BYTES:
		raise AgentToolError("INVALID_ASSET", "Bilder dürfen maximal 5 MiB groß sein.")
	try:
		with Image.open(BytesIO(content)) as img:
			formats = {
				"PNG": ("png", "image/png"),
				"JPEG": ("jpg", "image/jpeg"),
				"GIF": ("gif", "image/gif"),
				"WEBP": ("webp", "image/webp"),
			}
			if img.format not in formats or img.width * img.height > 40_000_000:
				raise ValueError
			ext, mime = formats[img.format]
			width, height = img.size
			img.verify()
	except Exception:
		raise AgentToolError(
			"INVALID_ASSET", "Erlaubt sind PDF, PNG, JPG, GIF und WebP; Bild maximal 40 Megapixel."
		) from None
	return {"extension": ext, "mime_type": mime, "width": width, "height": height}


@frappe.whitelist(methods=["POST"])
@api._endpoint
def upload_asset(filename, content_base64, attached_to_doctype, attached_to_name):
	if attached_to_doctype not in TARGETS:
		raise AgentToolError(
			"INVALID_ARGUMENT",
			"Dateien dürfen nur an Serienbrief Vorlagen oder Textbausteine angehängt werden.",
		)
	if not set(frappe.get_roles()).intersection({"System Manager", "Hausverwalter"}):
		raise AgentToolError("PERMISSION_DENIED", "Keine Berechtigung für Serienbrief-Uploads.")
	target = api._read(attached_to_doctype, attached_to_name)
	target.check_permission("write")
	if not frappe.has_permission("File", "create"):
		raise frappe.PermissionError
	if (
		not isinstance(filename, str)
		or not filename.strip()
		or len(filename) > 200
		or any(ord(c) < 32 or c in "/\\" for c in filename)
	):
		raise AgentToolError(
			"INVALID_ARGUMENT", "Dateiname ohne Pfad mit höchstens 200 Zeichen erforderlich."
		)
	content = _decode(content_base64)
	info = asset_info(content)
	stem = re.sub(r"[^\w.\-]+", "_", filename.rsplit(".", 1)[0]).strip(".")[:80] or "datei"
	with author._atomic():
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{stem}.{info['extension']}",
				"content": content,
				"is_private": 1,
				"attached_to_doctype": attached_to_doctype,
				"attached_to_name": target.name,
			}
		).insert()
		return {
			"file": file_doc.name,
			"file_url": file_doc.file_url,
			"filename": file_doc.file_name,
			"is_private": True,
			"size_bytes": len(content),
			"sha256": hashlib.sha256(content).hexdigest(),
			**info,
		}
