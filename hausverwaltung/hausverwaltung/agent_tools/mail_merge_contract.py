"""Compact template descriptions and actionable errors, without model calls."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

JSON_TYPES = {"Text": "string", "String": "string", "Zahl": "number", "Bool": "boolean", "Datum": "string"}
EXAMPLES = {
	"Text": "BEISPIELTEXT",
	"String": "BEISPIELTEXT",
	"Zahl": 125.5,
	"Bool": False,
	"Datum": "2030-01-15",
}


class _PlainText(HTMLParser):
	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.parts = []
		self.hidden = 0

	def handle_starttag(self, tag, attrs):
		if tag in {"script", "style"}:
			self.hidden += 1
		if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
			self.parts.append(" ")

	def handle_endtag(self, tag):
		if tag in {"script", "style"}:
			self.hidden = max(0, self.hidden - 1)
		self.parts.append(" ")

	def handle_data(self, data):
		if not self.hidden:
			self.parts.append(data)


def plain_text(value, limit):
	parser = _PlainText()
	# Keep dynamic values visibly unresolved; do not execute or summarize Jinja.
	value = re.sub(r"\{\{.*?\}\}", " [Platzhalter] ", value or "", flags=re.DOTALL)
	value = re.sub(r"\{%.*?%\}|\{#.*?#\}", " ", value, flags=re.DOTALL)
	parser.feed(value)
	text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
	return text[:limit], len(text) > limit


def input_description(field):
	"""Examples describe syntax; only the saved default is a real default."""
	out = {**field, "required": not field["optional"]}
	if field["fillable"]:
		kind = field["type"]
		out["json_type"] = JSON_TYPES[kind]
		out["example"] = EXAMPLES[kind]
		if kind == "Datum":
			out["format"] = "YYYY-MM-DD"
		elif kind in {"Text", "String"}:
			out["max_length"] = 4000
			out["plain_text_only"] = True
	return out


class MailMergeError(AgentToolError):
	def __init__(self, code, message, *, issues=(), action="review_template", recipient=None):
		super().__init__(code, message)
		self.details = {"issues": list(issues), "action": action}
		if recipient is not None:
			self.details["recipient"] = recipient


def input_issue(field, *, expected_type=None, format=None):
	issue = {"field": field, "source": "input"}
	if expected_type:
		issue["expected_type"] = expected_type
	if format:
		issue["format"] = format
	return issue


def missing_inputs(fields):
	return MailMergeError(
		"MISSING_INPUT",
		"Pflichtangaben fehlen: " + ", ".join(f["key"] for f in fields),
		issues=[
			input_issue(
				f["key"],
				expected_type=JSON_TYPES[f["type"]],
				format="YYYY-MM-DD" if f["type"] == "Datum" else None,
			)
			for f in fields
		],
		action="provide_inputs",
	)


def render_error(exc, *, recipient, recipient_doctype):
	"""Adapt only explicit renderer diagnostics; never infer a field from snippets.

	The core embeds examples, whole template lines and even tracebacks in some
	messages. These are deliberately excluded from the model-facing response.
	"""
	result = {
		"recipient": recipient,
		"recipient_doctype": recipient_doctype,
		"code": "RENDER_FAILED",
		"message": "Vorlage konnte nicht gerendert werden; bitte im Vorlageneditor prüfen.",
		"issues": [],
		"action": "review_template",
	}
	if isinstance(exc, AgentToolError):
		result.update(code=exc.code, message=exc.message)
		result.update(getattr(exc, "details", {}))
		return result

	# Remove source before unescaping it, so encoded template HTML stays data.
	raw = re.sub(r"<pre\b[^>]*>.*?</pre>", "", str(exc), flags=re.DOTALL | re.IGNORECASE)
	raw = re.split(r"Vorlagen-Zeile|Kandidaten in dieser Zeile|Traceback", raw, maxsplit=1)[0]
	text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
	path_match = re.search(
		r"Platzhalter\s+\{\{?\s*\$\s*([^{}$]+?)\s*\$\s*\}\}?\s+konnte nicht aufgelöst werden", text
	)
	if path_match:
		path = path_match[1].strip()
		if re.fullmatch(r"[\w.\[\]]+", path):
			is_data = path.startswith("objekt.")
			result.update(
				code="MISSING_DATA" if is_data else "UNRESOLVED_PATH",
				message=f"Für {recipient} konnte der Pfad {path} nicht aufgelöst werden.",
				issues=[
					{
						"field": path.rsplit(".", 1)[-1],
						"path": path,
						"source": "recipient_data" if is_data else "template",
					}
				],
				action="check_recipient_data" if is_data else "review_template",
			)
			return result

	mapped = re.search(r"Pfad\s+([\w.\[\]]+)\s+für Variable\s+(\w+)\s+.*?konnte nicht aufgelöst werden", text)
	if mapped:
		path, variable = mapped.groups()
		is_data = path.startswith("objekt.")
		result.update(
			code="MISSING_DATA" if is_data else "UNRESOLVED_PATH",
			message=f"Datenpfad für Variable {variable} konnte nicht aufgelöst werden.",
			issues=[
				{
					"field": path.rsplit(".", 1)[-1],
					"variable": variable,
					"path": path,
					"source": "recipient_data" if is_data else "template",
				}
			],
			action="check_recipient_data" if is_data else "review_template",
		)
		return result

	variable = re.search(r"Variable\s+([\w]+)\s+ist nicht definiert", text)
	if not variable:
		variable = re.fullmatch(r"'?(\w+)'? is undefined", text)
	if variable:
		result.update(
			code="UNDEFINED_VARIABLE",
			message=f"Vorlagenvariable {variable[1]} ist nicht definiert.",
			issues=[{"field": variable[1], "source": "template"}],
		)
		return result

	field = re.search(r"Feld\s+(\w+)\s+(existiert nicht im DocType|kann nicht gelesen werden)", text)
	if field:
		missing_link = field[2] == "kann nicht gelesen werden"
		result.update(
			code="MISSING_DATA" if missing_link else "INVALID_TEMPLATE_FIELD",
			message=f"Feld {field[1]} ist über die Vorlage nicht lesbar.",
			issues=[{"field": field[1], "source": "recipient_data" if missing_link else "template"}],
			action="check_recipient_data" if missing_link else "review_template",
		)
	return result
