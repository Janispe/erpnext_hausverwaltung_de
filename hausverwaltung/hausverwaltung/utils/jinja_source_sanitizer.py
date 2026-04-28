from __future__ import annotations

import re
from html import unescape


_JINJA_TAG_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})", re.DOTALL)
_HV_QUILL_BADGE_SPAN_RE = re.compile(
	r"<span\b[^>]*(?:hv-placeholder-badge|hv-jinja-badge|data-hv-placeholder=|data-hv-jinja-token=)[^>]*>(.*?)</span>",
	re.DOTALL | re.IGNORECASE,
)
_QUILL_CONTENTEDITABLE_JINJA_SPAN_RE = re.compile(
	r"<span\b[^>]*\bcontenteditable=(?:\"|')false(?:\"|')[^>]*>[\s\ufeff\u200b]*(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})[\s\ufeff\u200b]*</span>",
	re.DOTALL | re.IGNORECASE,
)

# Common invisible characters inserted by rich-text editors around placeholders.
_RICH_TEXT_INVISIBLE_CHARS_RE = re.compile(r"[\ufeff\u200b]")
_PLACEHOLDER_ONLY_PARAGRAPH_RE = re.compile(
	r"<p\b[^>]*>[\s\ufeff\u200b]*"
	r"(\{\{\s*(?:baustein|textbaustein)\(\s*(['\"])(.*?)\2\s*\)\s*\}\})"
	r"[\s\ufeff\u200b]*(?:<br\s*/?>[\s\ufeff\u200b]*)*</p>",
	re.DOTALL | re.IGNORECASE,
)
_QUILL_EDITOR_WRAPPER_RE = re.compile(
	r"^\s*<div\b[^>]*\bclass=(['\"])(?:(?!\1).)*\bql-editor\b(?:(?!\1).)*\1[^>]*>(.*)</div>\s*$",
	re.DOTALL | re.IGNORECASE,
)


def strip_hv_quill_placeholder_badges(source: str) -> str:
	"""Strip Hausverwaltung Quill placeholder badge spans from HTML source.

	The rich-text editor renders placeholders as spans with metadata attributes like
	`data-hv-jinja-token="..."` and `contenteditable="false"`. These are editor artifacts
	and should not leak into rendered output; additionally they may contain HTML-encoded
	quotes inside Jinja tokens (e.g. `&quot;`) which would break HTML if unescaped.

	This function replaces the badge `<span>` nodes with their inner HTML (typically the
	Jinja token text), leaving the template itself intact.
	"""

	if not source or "<span" not in source:
		return source or ""

	# Iteratively unwrap badges to handle multiple/nested occurrences.
	last = None
	current = source
	for _ in range(25):
		if current == last:
			break
		last = current
		current = _HV_QUILL_BADGE_SPAN_RE.sub(lambda m: m.group(1), current)
	return current


def strip_richtext_placeholder_wrappers(source: str) -> str:
	"""Strip remaining rich-text placeholder wrapper spans.

	Some editor flows store placeholders as nested spans, e.g.
	`<span class="hv-placeholder-badge">...<span contenteditable="false">{{ ... }}</span>...</span>`.
	The outer badge is already unwrapped by `strip_hv_quill_placeholder_badges`, but the inner
	`contenteditable="false"` span remains and can:
	- wrap block-level HTML (invalid markup) when the placeholder renders to `<div>...`
	- inherit styles (e.g. `color`, `text-decoration`) that then leak into the letterhead

	This function unwraps those inner spans only when they contain a single Jinja tag.
	"""

	if not source or "<span" not in source:
		return source or ""

	last = None
	current = source
	for _ in range(25):
		if current == last:
			break
		last = current
		current = _QUILL_CONTENTEDITABLE_JINJA_SPAN_RE.sub(lambda m: m.group(1), current)
	return current


def normalize_jinja_html_entities(source: str) -> str:
	"""Normalize HTML-encoded entities inside Jinja tags.

	Rich-text editors sometimes HTML-encode quotes/spaces inside `{{ ... }}` / `{% ... %}`,
	which makes Jinja parsing fail (e.g. `&quot;`, `&nbsp;`).

	Only entities inside Jinja tags are unescaped; normal HTML text stays untouched.
	"""

	if not source:
		return ""

	if "&" not in source and "\xa0" not in source:
		return source

	def _fix_tag(match: re.Match[str]) -> str:
		tag = match.group(0)
		if "&" not in tag and "\xa0" not in tag:
			return tag

		unescaped = unescape(tag)
		return unescaped.replace("\xa0", " ")

	return _JINJA_TAG_RE.sub(_fix_tag, source)


def unwrap_placeholder_only_paragraphs(source: str) -> str:
	"""Unwrap <p> that contain only a placeholder token.

	Rich-text editors tend to wrap every line in <p>. When a placeholder expands to
	block-level HTML (e.g. letterhead uses <div>), having `{{ baustein(...) }}` inside
	a <p> yields invalid HTML and can lead to broken layout in PDFs.
	"""

	if not source or "<p" not in source:
		return source or ""

	return _PLACEHOLDER_ONLY_PARAGRAPH_RE.sub(lambda m: m.group(1), source)


def strip_quill_editor_wrapper(source: str) -> str:
	"""Strip a top-level Quill `ql-editor` wrapper div.

	Templates stored from the rich-text editor often wrap the actual content in a div like:
	`<div class="ql-editor read-mode"> ... </div>`.
	This wrapper is editor/UI specific and can cause styling/layout differences in print/PDF views.
	"""

	if not source or "ql-editor" not in source:
		return source or ""

	match = _QUILL_EDITOR_WRAPPER_RE.match(source)
	if not match:
		return source

	return match.group(2) or ""


def sanitize_richtext_jinja_source(source: str) -> str:
	"""Sanitize rich-text HTML that may contain Jinja and Quill placeholder badges."""

	clean = strip_hv_quill_placeholder_badges(source)
	clean = strip_richtext_placeholder_wrappers(clean)
	clean = unwrap_placeholder_only_paragraphs(clean)
	# Remove invisible chars that commonly surround placeholders; they can affect rendering in PDFs.
	clean = _RICH_TEXT_INVISIBLE_CHARS_RE.sub("", clean)
	clean = strip_quill_editor_wrapper(clean)
	return normalize_jinja_html_entities(clean)
