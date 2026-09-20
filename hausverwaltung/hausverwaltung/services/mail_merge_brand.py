from __future__ import annotations

import re


_PETERS_LOCKUP_RE = re.compile(
	r"(?P<prefix><img\b[^>]*\bsrc=(?P<quote>['\"])/files/"
	r"(?:peters-lockup|peters-lockup-sw)\.svg(?P=quote)[^>]*>)",
	re.IGNORECASE,
)
_PETERS_LOGO_IMG_RE = re.compile(
	r"<img\b(?=[^>]*\bsrc=['\"]/files/"
	r"(?:peters-lockup|peters-lockup-sw|peters-siegel|peters-siegel-sw)\.svg['\"])[^>]*>",
	re.IGNORECASE,
)
_HEIGHT_RE = re.compile(r"height\s*:\s*[^;\"']+;?", re.IGNORECASE)


def _hide_peters_logo_enabled() -> bool:
	try:
		import frappe

		value = frappe.db.get_single_value("Serienbrief Einstellungen", "hide_peters_logo")
	except Exception:
		return False
	if value in (None, ""):
		return True
	try:
		return bool(int(value))
	except (TypeError, ValueError):
		return bool(value)


def apply_print_saving_brand_assets(
	html: str,
	enabled: bool,
	hide_peters_logo: bool | None = None,
) -> str:
	"""Apply Peters logo visibility and toner-saving brand image handling."""
	if not html:
		return html
	if hide_peters_logo is None:
		hide_peters_logo = _hide_peters_logo_enabled()
	if hide_peters_logo:
		html = _PETERS_LOGO_IMG_RE.sub("", html)
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
