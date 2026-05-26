"""Post-Processing: Seitenzahlen-Overlay 'Seite X von Y' bei mehrseitigen PDFs.

Wird nach der Frappe-PDF-Generierung aufgerufen (über den Print-Format-Pfad), weil
Chrome's @page-margin-Boxes vom Frappe-Footer-Stamp-Mechanismus überdeckt werden
und Chrome's native footerTemplate-Magic-Klassen (.pageNumber/.totalPages) nicht
in Frappes Footer-Pipeline gemerged werden. Stattdessen legen wir hier per
reportlab/pypdf ein Overlay über jede Seite — nur wenn das PDF mehr als eine
Seite hat (Single-Page-Briefe bleiben sauber, ohne 'Seite 1 von 1').
"""

from __future__ import annotations

import io


_MM_TO_PT = 2.8346


def add_page_numbers_if_multipage(
	pdf_bytes: bytes,
	*,
	text_template: str = "Seite {page} von {total}",
	font_size: int = 9,
	y_from_bottom_mm: float = 20.0,
) -> bytes:
	"""Fügt 'Seite X von Y' mittig in den unteren Seitenrand jeder Seite ein.

	Voraussetzung für die Sichtbarkeit: das Print Format hat einen Bottom-Margin
	von mind. ~22mm — sonst landet die Seitenzahl entweder im Body-Bereich (über
	Text) oder im Frappe-Footer-Bereich (überdeckt).

	Bei genau einer Seite wird das PDF unverändert zurückgegeben. Bei fehlenden
	Dependencies (reportlab/pypdf) ebenfalls — defensive Degradation statt
	Render-Crash.
	"""
	try:
		from pypdf import PdfReader, PdfWriter
		from reportlab.pdfgen import canvas
	except Exception:
		return pdf_bytes

	try:
		reader = PdfReader(io.BytesIO(pdf_bytes))
	except Exception:
		return pdf_bytes

	total = len(reader.pages)
	if total <= 1:
		return pdf_bytes

	writer = PdfWriter()
	y_pt = y_from_bottom_mm * _MM_TO_PT

	for i, page in enumerate(reader.pages):
		page_num = i + 1
		text = text_template.format(page=page_num, total=total)
		width_pt = float(page.mediabox.width)
		height_pt = float(page.mediabox.height)

		buf = io.BytesIO()
		c = canvas.Canvas(buf, pagesize=(width_pt, height_pt))
		c.setFont("Helvetica", font_size)
		c.setFillColorRGB(0, 0, 0)
		c.drawCentredString(width_pt / 2, y_pt, text)
		c.save()

		overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
		page.merge_page(overlay)
		writer.add_page(page)

	out = io.BytesIO()
	writer.write(out)
	return out.getvalue()
