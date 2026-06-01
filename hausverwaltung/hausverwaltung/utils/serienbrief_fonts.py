from __future__ import annotations

import base64
from pathlib import Path

import frappe


_FONT_FACE_CACHE: str | None = None


def get_serienbrief_font_face_css() -> str:
	"""Embed the same Liberation Sans font files used by the React editor.

	Chrome's PDF renderer otherwise falls back to system-installed fonts. That
	makes line wrapping depend on the host/container image. Data-URI font faces
	keep the editor/PDF metrics stable across machines.
	"""
	global _FONT_FACE_CACHE
	if _FONT_FACE_CACHE is not None:
		return _FONT_FACE_CACHE

	app_root = Path(frappe.get_app_path("hausverwaltung")).parent
	font_dirs = (
		app_root / "public" / "serienbrief_editor" / "assets",
		app_root / "HV_Serienbrief" / "src_react" / "src" / "assets" / "fonts",
	)
	fonts = (
		("Regular", 400, "normal"),
		("Bold", 700, "normal"),
		("Italic", 400, "italic"),
		("BoldItalic", 700, "italic"),
	)
	blocks: list[str] = []
	for suffix, weight, style in fonts:
		matches = []
		for font_dir in font_dirs:
			matches = sorted(font_dir.glob(f"LiberationSans-{suffix}*.ttf"))
			if matches:
				break
		if not matches:
			continue
		encoded = base64.b64encode(matches[0].read_bytes()).decode("ascii")
		blocks.append(
			"@font-face {\n"
			'  font-family: "HV Liberation Sans";\n'
			f'  src: url("data:font/ttf;base64,{encoded}") format("truetype");\n'
			f"  font-weight: {weight};\n"
			f"  font-style: {style};\n"
			"  font-display: swap;\n"
			"}"
		)

	_FONT_FACE_CACHE = "\n".join(blocks)
	return _FONT_FACE_CACHE


def serienbrief_font_family() -> str:
	return '"HV Liberation Sans", "Liberation Sans", "Arial", "Helvetica", sans-serif'
