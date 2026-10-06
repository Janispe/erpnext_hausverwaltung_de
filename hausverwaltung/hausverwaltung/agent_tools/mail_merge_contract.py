"""Compact template descriptions and actionable errors, without model calls."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

RECORD_TYPES = {"Doctype", "Doctype Liste"}
# Fest gewählte Datensätze darf der Assistent nur für Adressaten-Stammdaten setzen,
# nicht für Buchungs-, Vertrags- oder Systemdaten.
AI_RECORD_DOCTYPES = ("Contact", "Address", "Customer", "Supplier")
JSON_TYPES = {
	"Text": "string",
	"String": "string",
	"Zahl": "number",
	"Bool": "boolean",
	"Datum": "string",
	"Doctype": "string",
	"Doctype Liste": "array",
}
EXAMPLES = {
	"Text": "BEISPIELTEXT",
	"String": "BEISPIELTEXT",
	"Zahl": 125.5,
	"Bool": False,
	"Datum": "2030-01-15",
	"Doctype": "EXAKTER-DATENSATZNAME",
	"Doctype Liste": ["EXAKTER-DATENSATZNAME"],
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
		out["json_type"] = ["string", "number", "boolean"] if field.get("direct_path") else JSON_TYPES[kind]
		if field.get("path_overridable"):
			out["path_example"] = {"path": "objekt.FELDNAME"}
		out["example"] = EXAMPLES[kind]
		if kind == "Datum":
			out["format"] = "YYYY-MM-DD"
		elif kind in RECORD_TYPES:
			out["format"] = f"exakter Name eines vorhandenen {field['reference_doctype']}-Datensatzes"
		elif kind in {"Text", "String"}:
			out["max_length"] = 4000
			out["plain_text_only"] = True
	return out


_PARAGRAPH_RE = re.compile(r"<p[\s>]", re.IGNORECASE)
_BLANK_PARAGRAPH_RE = re.compile(r"<p[^>]*>(?:\s|&nbsp;|&#160;|\u00a0|<br\s*/?>)*</p>", re.IGNORECASE)


def layout_warnings(source):
	"""Absätze haben im Druck keinen Abstand; Vorlagen setzen Leerzeilen als eigene leere Absätze."""
	if len(_PARAGRAPH_RE.findall(source or "")) >= 4 and not _BLANK_PARAGRAPH_RE.search(source or ""):
		return [
			{
				"code": "NO_BLANK_LINES",
				"message": "Absätze haben im Druck keinen Abstand und die Vorlage enthält keine Leerzeile. "
				"Leerzeilen wie in den bestehenden Vorlagen als <p>&nbsp;</p> setzen.",
			}
		]
	return []


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


def render_error(exc, *, recipient, recipient_doctype, phase="render", template=None, vorlagenversion=None):
	"""Expose the original cause and verified location, without tracebacks or data dumps."""
	from mail_merge.mail_merge.utils.render_diagnostics import exception_chain, render_diagnostic

	chain = exception_chain(exc)
	result = _classify_render_error(exc, recipient=recipient, recipient_doctype=recipient_doctype)
	if isinstance(exc, AgentToolError):
		return result
	# A Frappe wrapper may HTML-escape the original diagnostic. Classify the
	# original exceptions directly, rather than guessing a field from that text.
	if result["code"] == "RENDER_FAILED":
		for cause in chain[1:]:
			classified = _classify_render_error(
				cause, recipient=recipient, recipient_doctype=recipient_doctype
			)
			if classified["code"] != "RENDER_FAILED":
				result = classified
				break
	diagnostic = render_diagnostic(exc, phase=phase)
	block = diagnostic.get("baustein")
	result["diagnostic"] = diagnostic
	if template is not None:
		result["template"] = template
	if vorlagenversion is not None:
		result["vorlagenversion"] = vorlagenversion
	if result["code"] == "RENDER_FAILED":
		location = (
			f"Textbaustein {block}"
			if block
			else "PDF-Erzeugung"
			if diagnostic["phase"] in {"pdf", "pdf_validation"}
			else "Vorlage"
		)
		if diagnostic.get("line"):
			location += f", Jinja-Zeile {diagnostic['line']}"
		result["message"] = f"{location}: {diagnostic['exception_type']}: {diagnostic['message']}"
		if diagnostic["phase"] in {"pdf", "pdf_validation"}:
			result["action"] = "check_pdf_renderer"
	# Location does not imply a missing field. Preserve known field/path issues
	# and enrich them with verified line/block coordinates only.
	coordinates = {
		key: diagnostic[key] for key in ("baustein", "line", "line_reference") if key in diagnostic
	}
	if coordinates:
		if not result["issues"]:
			result["issues"] = [{"source": "template", **coordinates}]
		else:
			result["issues"] = [{**issue, **coordinates} for issue in result["issues"]]
	return result


def _classify_render_error(exc, *, recipient, recipient_doctype):
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
	override_match = re.search(r"Überschriebener Serienbrief-Pfad ([\w.\[\]]+) konnte nicht aufgelöst werden", text)
	if override_match:
		path = override_match[1]
		result.update(code="INVALID_INPUT", message=f"Der gewählte Feldpfad {path} konnte für {recipient} nicht aufgelöst werden.",
			issues=[{"field": path.rsplit(".", 1)[-1], "path": path, "source": "input"}], action="correct_inputs")
		return result
	if "Zirkuläre Serienbrief-Pfadzuordnung:" in text:
		result.update(code="INVALID_INPUT", message="Die gewählten Feldpfade verweisen zirkulär aufeinander.", action="correct_inputs")
		return result
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
