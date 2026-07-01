"""Monkey-Patch für ``frappe.utils.print_format.report_to_pdf``.

Frappes Standard-Endpoint ruft ``frappe.utils.pdf.get_pdf`` auf — das ist
hardcoded auf wkhtmltopdf via pdfkit. Im Docker-Setup kann wkhtmltopdf den
Asset-Server (CSS-URLs in der gerenderten Report-HTML) nicht erreichen, weil
``http://localhost:8080/...`` aus Container-Sicht nicht existiert (Caddy
hängt am Host, nicht im Backend-Container) → ``ConnectionRefusedError`` →
PDF-Download crasht mit 500.

Workaround: wir leiten den Endpoint auf unseren ``pdf_engine.render_pdf``-
Wrapper um, der Print Settings respektiert und Chrome nutzt. Chrome lädt
externe Assets nicht über Netzwerk (Frappe injected die CSS direkt) —
funktioniert also out-of-the-box.

Patch ist idempotent (Flag-Attribut auf dem Modul).
"""

from __future__ import annotations

import frappe

_PATCHED_FLAG = "_hv_report_to_pdf_patched"


_FOOTER_DIV_RE = None


def apply() -> None:
	from frappe.utils import print_format as core_pf

	if getattr(core_pf, _PATCHED_FLAG, False):
		return

	import re

	from frappe.core.doctype.access_log.access_log import make_access_log

	from mail_merge.mail_merge.utils.pdf_engine import render_pdf

	# Frappe injectet `<div id="footer-html">` mit `Seite <span class="page">`
	# — funktioniert nur in wkhtmltopdf's Custom-CSS-Page-Replacement, nicht
	# in Chrome. Chrome erstellt daraus eine separate footer_page mit
	# paperHeight=0 und kippt mit "content area is empty". Header analog.
	# Reports brauchen diesen Frappe-Footer nicht (eigene Header schon im Body).
	footer_re = re.compile(
		r'<div\s+id="(?:footer-html|header-html)"[^>]*>.*?</div>\s*',
		flags=re.DOTALL | re.IGNORECASE,
	)

	@frappe.whitelist()
	def report_to_pdf(html: str, orientation: str = "Landscape") -> None:
		make_access_log(file_type="PDF", method="PDF", page=html)
		clean_html = footer_re.sub("", html or "")
		frappe.local.response.filename = "report.pdf"
		frappe.local.response.filecontent = render_pdf(
			clean_html,
			options={"orientation": orientation},
		)
		frappe.local.response.type = "pdf"

	core_pf.report_to_pdf = report_to_pdf
	setattr(core_pf, _PATCHED_FLAG, True)
