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
		if getattr(self, "footer_page", None) is not None:
			self.footer_page.options["marginBottom"] = 0
			self.footer_page.options["marginTop"] = 0
		if getattr(self, "header_page", None) is not None:
			self.header_page.options["marginBottom"] = 0
			self.header_page.options["marginTop"] = 0

		# Bug 2: Body-Page paperHeight wird auf ``page_height - footer_height -
		# margin_bottom`` reduziert. Da ``_transform`` im pdf_merge die Page-
		# mediabox nur erweitert wenn ein Header existiert, bleibt die finale
		# PDF-Page bei der reduzierten Höhe (z.B. 249mm statt A4 297mm).
		# Fix: Body-Page kriegt full page_height; marginBottom reserviert Platz
		# für Footer-Render via Merge.
		if getattr(self, "footer_page", None) is not None and not getattr(
			self, "header_page", None
		):
			try:
				page_h_px = self.options.get("page-height", 0)
				# page-height kann nach prepare schon int/float sein (px) oder string
				if isinstance(page_h_px, str):
					page_h_px = self._get_converted_num(page_h_px)
				if page_h_px:
					full_height_in = convert_uom(
						float(page_h_px), "px", "in", only_number=True
					)
					self.body_page.options["paperHeight"] = full_height_in

					# Body-marginBottom muss Platz für den Footer + Abstand
					# reservieren. Wert kommt aus den Original-Options.
					mb = self.options.get("margin-bottom", 0)
					if isinstance(mb, str):
						mb = self._get_converted_num(mb)
					if mb:
						margin_bottom_in = convert_uom(
							float(mb), "px", "in", only_number=True
						)
						self.body_page.options["marginBottom"] = margin_bottom_in
			except Exception:
				import frappe as _f
				_f.log_error(_f.get_traceback(), "frappe_chrome_footer_patch height fix")

	Browser.prepare_options_for_pdf = patched
	setattr(Browser, _PATCHED_FLAG, True)
