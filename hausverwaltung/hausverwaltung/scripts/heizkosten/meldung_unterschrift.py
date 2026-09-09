"""Lokale PNG-Unterschriften des Frappe-Signature-Feldes validieren."""

import base64
from io import BytesIO

from PIL import Image


def signature_bytes(value):
	if not value:
		return None
	try:
		prefix = "data:image/png;base64,"
		if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 2_000_000:
			raise ValueError
		content = base64.b64decode(value[len(prefix) :], validate=True)
		with Image.open(BytesIO(content)) as image:
			if image.format != "PNG" or image.width > 4096 or image.height > 2048:
				raise ValueError
			image.verify()
		return content
	except Exception as exc:
		raise ValueError(
			"Unterschrift muss eine gültige PNG-Zeichnung aus dem Unterschriftsfeld sein."
		) from exc
