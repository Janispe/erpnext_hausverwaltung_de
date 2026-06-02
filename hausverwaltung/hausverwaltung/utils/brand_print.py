from __future__ import annotations

import re


_PETERS_LOCKUP_RE = re.compile(
	r"(?P<prefix><img\b[^>]*\bsrc=(?P<quote>['\"])/files/"
	r"(?:peters-lockup|peters-lockup-sw)\.svg(?P=quote)[^>]*>)",
	re.IGNORECASE,
)
_HEIGHT_RE = re.compile(r"height\s*:\s*[^;\"']+;?", re.IGNORECASE)


def apply_print_saving_brand_assets(html: str, enabled: bool) -> str:
	"""Switch static Peters lockup images to the toner-saving seal variant."""
	if not enabled or not html or "peters-lockup" not in html:
		return html

	def replace_img(match: re.Match) -> str:
		img = match.group("prefix")
		img = re.sub(
			r"(/files/)(?:peters-lockup|peters-lockup-sw)\.svg",
			r"\1peters-siegel-sw.svg",
			img,
			flags=re.IGNORECASE,
		)
		if "style=" in img.lower():
			img = _HEIGHT_RE.sub("height:1.15cm;", img)
		return img

	return _PETERS_LOCKUP_RE.sub(replace_img, html)
