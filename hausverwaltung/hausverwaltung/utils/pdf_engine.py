"""Wrapper, der HTML zu PDF rendert und dabei die in Print Settings
hinterlegte Engine respektiert (``wkhtmltopdf`` oder ``chrome``).

Hintergrund: Frappes ``frappe.utils.pdf.get_pdf`` ist hardcoded auf
wkhtmltopdf (via pdfkit). Für CSS-Paged-Media-Features wie
``position: fixed; bottom: 0`` brauchen wir Chromium-Headless.
Frappe hat dafür eine eigene API (``get_chrome_pdf``), die aber einen
Print-Format-Namen erwartet.

Diese Funktion kapselt die Engine-Auswahl. Bei Fehlern in der
Chrome-Pipeline fällt sie still auf wkhtmltopdf zurück, damit der
Druck nie komplett blockiert.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils.pdf import get_pdf as _wk_get_pdf


_FALLBACK_PRINT_FORMAT = "Standard"


def _resolve_pdf_generator() -> str:
	"""Liest Print Settings → pdf_generator. Default ``wkhtmltopdf``."""
	try:
		value = frappe.db.get_single_value("Print Settings", "pdf_generator") or ""
	except Exception:
		value = ""
	return (value or "wkhtmltopdf").strip().lower()


def render_pdf(html: str, options: dict[str, Any] | None = None) -> bytes:
	"""Rendert HTML zu PDF. Nutzt Chrome wenn Print Settings das verlangen,
	sonst wkhtmltopdf.

	Bei Chrome-Fehlern: stiller Fallback auf wkhtmltopdf, damit Drucke
	nie hart fehlschlagen.
	"""
	if _resolve_pdf_generator() == "chrome":
		try:
			from frappe.utils.pdf import get_chrome_pdf

			return get_chrome_pdf(
				_FALLBACK_PRINT_FORMAT,
				html,
				options or {},
				None,
				pdf_generator="chrome",
			)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"render_pdf: Chrome fehlgeschlagen, Fallback wkhtmltopdf",
			)

	return _wk_get_pdf(html, options=options or {})
