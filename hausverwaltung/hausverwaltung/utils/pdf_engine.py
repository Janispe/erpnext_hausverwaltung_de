"""Wrapper, der HTML zu PDF rendert und dabei die in Print Settings
hinterlegte Engine respektiert (``wkhtmltopdf`` oder ``chrome``).

Hintergrund: Frappes ``frappe.utils.pdf.get_pdf`` ist hardcoded auf
wkhtmltopdf (via pdfkit). Für CSS-Paged-Media-Features wie
``position: fixed; bottom: 0`` brauchen wir Chromium-Headless.
Frappe hat dafür eine eigene API (``get_chrome_pdf``), die aber einen
Print-Format-Namen erwartet.

Diese Funktion kapselt die Engine-Auswahl. Bei Chrome-Fehlern faellt
sie auf wkhtmltopdf zurueck **wenn** das HTML keine Paged-Media-Features
braucht (kein Footer, keine @page-Rules, keine page-break-*-Regeln).
Wenn das HTML diese Features braucht, wird die Chrome-Exception
propagiert, damit Briefe nicht sichtbar kaputt rausgehen.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils.pdf import get_pdf as _wk_get_pdf


_FALLBACK_PRINT_FORMAT = "Standard"

# Indikatoren fuer CSS-Paged-Media-Features, die wkhtmltopdf nicht zuverlaessig
# rendert. Bei Chrome-Crash + diesen Features im HTML kein stiller Fallback,
# weil das Ergebnis sichtbar falsch waere (Footer fehlt, Raender falsch,
# Page-Breaks an falscher Stelle).
_PAGED_MEDIA_INDICATORS = (
	"footer-html",
	"@page",
	"page-break-before",
	"page-break-after",
	"page-break-inside",
	"break-before",
	"break-after",
	"break-inside",
)


def _needs_paged_media(html: str | None) -> bool:
	haystack = (html or "").lower()
	return any(token in haystack for token in _PAGED_MEDIA_INDICATORS)


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

	Bei Chrome-Fehlern: Fallback auf wkhtmltopdf nur wenn das HTML keine
	Paged-Media-Features braucht. Sonst Exception propagieren.
	"""
	if _resolve_pdf_generator() == "chrome":
		try:
			# Workaround für Frappe-Bug, der Chrome-Footer-Pages crashen lässt
			# (s. frappe_chrome_footer_patch). Patch ist idempotent.
			from hausverwaltung.hausverwaltung.utils.frappe_chrome_footer_patch import (
				apply as apply_chrome_footer_patch,
			)
			apply_chrome_footer_patch()

			from frappe.utils.pdf import get_chrome_pdf

			return get_chrome_pdf(
				_FALLBACK_PRINT_FORMAT,
				html,
				options or {},
				None,
				pdf_generator="chrome",
			)
		except Exception:
			needs_paged = _needs_paged_media(html)
			frappe.log_error(
				frappe.get_traceback(),
				f"render_pdf: Chrome fehlgeschlagen "
				f"(paged-media={'ja' if needs_paged else 'nein'})",
			)
			if needs_paged:
				# Wkhtmltopdf kann diese CSS-Features nicht — kein stiller
				# Fallback. Brief wuerde sonst sichtbar kaputt
				# (kein Footer, falsche Raender, falsche Page-Breaks).
				raise

	return _wk_get_pdf(html, options=options or {})
