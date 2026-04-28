from __future__ import annotations

import re


def _normalize_token(value: str) -> str:
	t = (value or "").strip().lower()
	t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
	t = re.sub(r"[.\-_/\\\s]+", "", t)
	return t


def normalize_gebaeudeteil_to_standard(value: str | None) -> str | None:
	"""Return standardized building part abbr (VH/HH/SF) or None if not recognized."""
	raw = (value or "").strip()
	if not raw:
		return None

	t = _normalize_token(raw)
	mapping = {
		"vorderhaus": "VH",
		"vh": "VH",
		"hinterhaus": "HH",
		"hh": "HH",
		"seitenfluegel": "SF",
		"sf": "SF",
	}
	if t in mapping:
		return mapping[t]

	for prefix, abbr in (("vorderhaus", "VH"), ("hinterhaus", "HH"), ("seitenfluegel", "SF")):
		if t.startswith(prefix):
			return abbr

	return None


def split_lage_gebaeudeteil(lage: str | None) -> tuple[str | None, str]:
	"""Split a Lage string into (gebaeudeteil, rest).

	Supports both:
	- "Vorderhaus, EG links" (comma-separated)
	- "VH EG li" / "HH 2.OG mi re" (prefix token)
	"""
	text = (lage or "").strip()
	if not text:
		return None, ""

	if "," in text:
		head, rest = text.split(",", 1)
		teil = normalize_gebaeudeteil_to_standard(head)
		rest = rest.strip()
		if teil and rest:
			return teil, rest
		return None, text

	# Prefix form: "VH EG li" / "Vorderhaus EG links" etc.
	m = re.match(r"^([A-Za-zÄÖÜäöüß]+[A-Za-zÄÖÜäöüß.]*)\b", text)
	if not m:
		return None, text

	head = m.group(1)
	teil = normalize_gebaeudeteil_to_standard(head)
	if not teil:
		return None, text

	rest = text[m.end() :].strip(" \t-–—:;")
	if not rest:
		return None, text
	return teil, rest.strip()
