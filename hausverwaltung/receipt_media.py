"""Canonical source pages for receipt workers and submission validation."""

import io
from contextlib import closing

from PIL import Image, ImageOps


def _png(image):
	with io.BytesIO() as output:
		image.save(output, format="PNG")
		return output.getvalue()


def render_pages(content, extension, page_limit):
	if extension == "pdf":
		import pypdfium2 as pdfium

		with closing(pdfium.PdfDocument(content)) as pdf:
			if not 0 < len(pdf) <= page_limit:
				raise ValueError("Invalid receipt PDF page count.")
			pages = []
			for index in range(len(pdf)):
				with closing(pdf[index]) as page:
					scale = min(200 / 72, 3000 / max(page.get_size()))
					with closing(page.render(scale=scale)) as bitmap:
						pages.append(_png(bitmap.to_pil()))
			return pages
	with Image.open(io.BytesIO(content), formats=["JPEG", "PNG"]) as original:
		image = ImageOps.exif_transpose(original).convert("RGB")
		image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
		return [_png(image)]
