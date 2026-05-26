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
	y_from_bottom_mm: float = 14.0,
) -> bytes:
	"""Fügt 'Seite X von Y' mittig in den unteren Seitenrand jeder Seite ein.

	Position: y_from_bottom_mm=14 platziert die Zeile in den Spalt zwischen
	Body-Ende (~29mm vom unteren Rand) und dem Frappe-Page-Footer (~9mm) — ~5mm
	Abstand nach unten zum Footer, ~15mm nach oben zum Body. Bei kleinerem
	Bottom-Margin im Print Format ggf. anpassen.

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

		# Canvas-Groesse auf mediabox: Overlay muss exakt ueber Originalseite
		# liegen, sonst rutscht es beim merge_page. Text-Position dagegen
		# relativ zur cropbox (sichtbare Druckflaeche), damit "Seite X von Y"
		# bei Bleed-PDFs nicht aus dem Sichtbaren rutscht. Bei Standard-PDFs
		# (cropbox.left=0, cropbox.bottom=0) ist das Verhalten identisch zum
		# alten Code.
		media = page.mediabox
		box = getattr(page, "cropbox", None) or media
		width_pt = float(media.width)
		height_pt = float(media.height)
		x_text = float(box.left) + float(box.width) / 2
		y_text = float(box.bottom) + y_pt

		buf = io.BytesIO()
		c = canvas.Canvas(buf, pagesize=(width_pt, height_pt))
		c.setFont("Helvetica", font_size)
		c.setFillColorRGB(0, 0, 0)
		c.drawCentredString(x_text, y_text, text)
		c.save()

		overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
		page.merge_page(overlay)
		writer.add_page(page)

	out = io.BytesIO()
	writer.write(out)
	return out.getvalue()
