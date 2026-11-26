"""Canonical source pages for receipt workers and submission validation."""

import io
from contextlib import closing

from PIL import Image, ImageOps


def _encoded(image, image_format):
	with io.BytesIO() as output:
		image.save(output, format=image_format)
		return output.getvalue()


def _pdf_page_count(pdf, page_limit):
	count = len(pdf)
	if not 0 < count <= page_limit:
		raise ValueError("Invalid receipt PDF page count.")
	return count


def pdf_page_count(content, page_limit):
	import pypdfium2 as pdfium

	with closing(pdfium.PdfDocument(content)) as pdf:
		return _pdf_page_count(pdf, page_limit)


def render_pages(content, extension, page_limit, *, page_numbers=None, preview=False):
	if extension == "pdf":
		import pypdfium2 as pdfium

		with closing(pdfium.PdfDocument(content)) as pdf:
			count = _pdf_page_count(pdf, page_limit)
			page_numbers = range(1, count + 1) if page_numbers is None else page_numbers
			max_side, image_format = (1600, "JPEG") if preview else (3000, "PNG")
			pages = []
			for number in page_numbers:
				if not 1 <= number <= count:
					raise ValueError("Invalid receipt page number.")
				with closing(pdf[number - 1]) as page:
					scale = min(200 / 72, max_side / max(page.get_size()))
					with closing(page.render(scale=scale)) as bitmap:
						pages.append(_encoded(bitmap.to_pil(), image_format))
			return pages
	if page_numbers is not None and list(page_numbers) != [1]:
		raise ValueError("Invalid receipt page number.")
	with Image.open(io.BytesIO(content), formats=["JPEG", "PNG"]) as original:
		image = ImageOps.exif_transpose(original).convert("RGB")
		image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
		return [_encoded(image, "PNG")]
