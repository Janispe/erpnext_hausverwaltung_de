"""Workaround für einen Frappe-Bug in ``frappe.utils.pdf_generator.browser.Browser``.

Beim PDF-Render mit Chromium und einem ``<div id="footer-html">`` setzt Frappe
für die Footer-Page fälschlich den Body-``marginBottom`` (z.B. 30mm), während
``paperHeight`` der Footer-Page nur die Footer-Höhe (z.B. 9mm) ist. Das
Resultat: Chrome wirft ``invalid print parameters: content area is empty``,
weil ``paperHeight - marginBottom`` negativ wird.

Diese Patch-Funktion erweitert ``prepare_options_for_pdf`` und setzt
``marginTop`` und ``marginBottom`` der Footer-Page auf 0 — die Footer-Page
ist nur eine Mini-Page mit Footer-Inhalt, sie braucht keine eigenen Margins.
"""

from __future__ import annotations


_PATCHED_FLAG = "_hv_chrome_footer_patched"


def apply() -> None:
	"""Patch idempotent applizieren. Mehrfacher Aufruf hat keinen Effekt."""
	from frappe.utils.pdf_generator.browser import Browser
	from frappe.utils.print_utils import convert_uom

	if getattr(Browser, _PATCHED_FLAG, False):
		return

	original = Browser.prepare_options_for_pdf

	def patched(self) -> None:
		original(self)

		# Bug 1: Body-margin_bottom wird auf footer_page.options["marginBottom"]
		# kopiert, was bei kleiner footer_height zu negativer content-area führt.
		# Footer-Page hat eigene paperHeight = footer_height; Margins müssen 0 sein.
		footer_page = getattr(self, "footer_page", None)
		footer_options = getattr(footer_page, "options", None) if footer_page else None
		if isinstance(footer_options, dict):
			footer_options["marginBottom"] = 0
			footer_options["marginTop"] = 0

			# Bug 3: Frappe misst die ``.wrapper``-Höhe der Footer-Page über
			# ``getBoxModel`` und nutzt sie als ``paperHeight`` der Footer-
			# Page. Bei Multi-Line-Footer-Inhalt (z.B. Bankverbindung +
			# Pfad-Zeile) misst Chrome die Höhe zu klein zurück, sodass die
			# zweite Zeile abgeschnitten wird. Mindesthöhe von 60px (~16mm)
			# erzwingen, damit zweizeilige Footer komplett sichtbar bleiben.
			min_footer_height_px = 60
			if getattr(self, "footer_height", 0) < min_footer_height_px:
				self.footer_height = min_footer_height_px
				try:
					footer_height_in = convert_uom(
						float(min_footer_height_px), "px", "in", only_number=True
					)
					footer_options["paperHeight"] = footer_height_in
				except Exception:
					import frappe as _f
					_f.log_error(_f.get_traceback(), "frappe_chrome_footer_patch min height")
		header_page = getattr(self, "header_page", None)
		header_options = getattr(header_page, "options", None) if header_page else None
		if isinstance(header_options, dict):
			header_options["marginBottom"] = 0
			header_options["marginTop"] = 0

		# Bug 2: Body-Page paperHeight wird auf ``page_height - footer_height -
		# margin_bottom`` reduziert. Da ``_transform`` im pdf_merge die Page-
		# mediabox nur erweitert wenn ein Header existiert, bleibt die finale
		# PDF-Page bei der reduzierten Höhe (z.B. 249mm statt A4 297mm).
		# Fix: Body-Page kriegt full page_height; marginBottom reserviert Platz
		# für Footer-Render via Merge.
		body_page = getattr(self, "body_page", None)
		body_options = getattr(body_page, "options", None) if body_page else None
		if (
			footer_page is not None
			and not header_page
			and isinstance(body_options, dict)
		):
			try:
				page_h_px = self.options.get("page-height", 0)
				# page-height kann nach prepare schon int/float sein (px) oder string.
				# Frappe-API-Drift: wenn _get_converted_num entfernt/umbenannt ist,
				# nicht raten — Block ueberspringen (Sentinel 0 → if page_h_px False).
				if isinstance(page_h_px, str):
					if hasattr(self, "_get_converted_num"):
						page_h_px = self._get_converted_num(page_h_px)
					else:
						import frappe as _f
						_f.log_error(
							"_get_converted_num fehlt — Bug-2-Fix uebersprungen (page-height)",
							"frappe_chrome_footer_patch hasattr",
						)
						page_h_px = 0
				if page_h_px:
					full_height_in = convert_uom(
						float(page_h_px), "px", "in", only_number=True
					)
					body_options["paperHeight"] = full_height_in

					# Body-marginBottom muss Platz für den Footer + Abstand
					# reservieren. Wert kommt aus den Original-Options.
					mb = self.options.get("margin-bottom", 0)
					if isinstance(mb, str):
						if hasattr(self, "_get_converted_num"):
							mb = self._get_converted_num(mb)
						else:
							import frappe as _f
							_f.log_error(
								"_get_converted_num fehlt — Bug-2-Fix uebersprungen (margin-bottom)",
								"frappe_chrome_footer_patch hasattr",
							)
							mb = 0
					if mb:
						margin_bottom_in = convert_uom(
							float(mb), "px", "in", only_number=True
						)
						body_options["marginBottom"] = margin_bottom_in
			except Exception:
				import frappe as _f
				_f.log_error(_f.get_traceback(), "frappe_chrome_footer_patch height fix")

	Browser.prepare_options_for_pdf = patched
	setattr(Browser, _PATCHED_FLAG, True)
