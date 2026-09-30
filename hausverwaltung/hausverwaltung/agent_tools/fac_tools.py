"""Expose existing permission-checked tools through FAC's registry and MCP endpoint."""

from copy import deepcopy
from typing import ClassVar

import frappe
from frappe.utils import get_url
from frappe_assistant_core.core.base_tool import BaseTool
from jsonschema import validate

from hausverwaltung.hausverwaltung.agent_tools import fac_output
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_MAIL_MERGE_TOOL_NAMES, FAC_TOOL_NAMES

EXPORT_VIEW_MAX_LIMIT = 1000
EXPORT_VIEW_CANDIDATE_LIMIT = 20_000
EXPORT_REPORT_MAX_LIMIT = 1000

# Direct results land in the model context, so every list-like tool gets a small default and a hard
# cap, both visible in its schema: (default, maximum). Larger values are clamped, not rejected.
DIRECT_LIMITS = {
	"search_mieter": (5, 10),
	"search_open_items": (10, 10),
	"search_late_payments": (20, 50),
	"rank_mieter_by_rent": (10, 10),
	"analyze_revenue_over_time": (24, 100),
	"hv_query_docs": (20, 50),
	"hv_query_view": (20, 100),
	"agent_list_doctypes": (20, 100),
	"agent_list_docs": (20, 100),
	"agent_search_docs": (10, 50),
	"agent_mail_merge_list_templates": (20, 100),
	"hv_report_list": (20, 50),
	"hv_run_report": (20, 100),
}

# Parameters FAC clients may send in addition to the built-in assistant's tool schema.
_EXTRA_PARAMETERS = {
	"hv_query_view": {
		"offset": {
			"type": "integer",
			"minimum": 0,
			"description": "Optional: Anzahl zu überspringender Zeilen (Blättern, siehe next_offset).",
		},
	},
}


def _apply_limit_schema(tool_name, schema):
	bounds = DIRECT_LIMITS.get(tool_name)
	properties = schema.get("properties") or {}
	if not bounds or "limit" not in properties:
		return
	default, maximum = bounds
	description = f"Maximale Anzahl Einträge. Standard {default}, höchstens {maximum}."
	if "offset" in properties:
		description += " Weitere Seiten mit offset = next_offset."
	properties["limit"] = {
		"type": "integer",
		"minimum": 1,
		"maximum": maximum,
		"default": default,
		"description": description,
	}


def _apply_limit(tool_name, arguments):
	bounds = DIRECT_LIMITS.get(tool_name)
	if not bounds:
		return arguments
	default, maximum = bounds
	try:
		limit = int(arguments["limit"]) if arguments.get("limit") is not None else default
	except (TypeError, ValueError):
		limit = default
	return {**arguments, "limit": max(1, min(limit, maximum))}


def _raise_on_tool_error(result):
	if isinstance(result, dict) and (result.get("ok") is False or result.get("error")):
		error = result.get("error") or {}
		message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
		# Raise so FAC records a failed call instead of a successful audit entry.
		frappe.throw(message)


class HausverwaltungReadTool(BaseTool):
	tool_name = ""

	def __init__(self):
		super().__init__()
		from hausverwaltung.hausverwaltung.services import assistant

		definition = next(
			item["function"]
			for item in assistant.ASSISTANT_TOOLS
			if item.get("function", {}).get("name") == self.tool_name
		)
		self.name = self.tool_name
		self.description = definition["description"]
		self.inputSchema = deepcopy(definition["parameters"])
		self.inputSchema.setdefault("properties", {}).update(
			deepcopy(_EXTRA_PARAMETERS.get(self.tool_name, {}))
		)
		_apply_limit_schema(self.tool_name, self.inputSchema)
		self.inputSchema["additionalProperties"] = False
		self.source_app = "hausverwaltung"
		self.category = "read_only"
		self.requires_permission = "Mietvertrag"

	def check_permission(self):
		from hausverwaltung.hausverwaltung.agent_tools.read_api import _ensure_agent_api_access

		_ensure_agent_api_access()
		super().check_permission()

	def validate_arguments(self, arguments):
		# FAC's base validator only checks top-level types. Validate the full schema.
		validate(instance=arguments, schema=self.inputSchema)

	def execute(self, arguments):
		from hausverwaltung.hausverwaltung.services import assistant

		self.check_permission()
		arguments = _apply_limit(self.name, arguments)
		self.validate_arguments(arguments)
		result = assistant.TOOL_FUNCTIONS[self.name](**arguments)
		_raise_on_tool_error(result)
		result = fac_output.compact_direct_result(self.name, arguments, result)
		return fac_output.enforce_output_budget(result)


class Fac_hv_export_view(HausverwaltungReadTool):
	"""Paged bulk rows of a semantic view, intended for code callers only."""

	tool_name = "hv_export_view"

	def __init__(self):
		BaseTool.__init__(self)
		from hausverwaltung.hausverwaltung.services import assistant

		view_schema = next(
			item["function"]["parameters"]
			for item in assistant.ASSISTANT_TOOLS
			if item.get("function", {}).get("name") == "hv_query_view"
		)
		properties = {
			key: deepcopy(value)
			for key, value in view_schema["properties"].items()
			if key in ("view", "fields", "filters", "order_by")
		}
		properties["offset"] = {
			"type": "integer",
			"minimum": 0,
			"description": "Startzeile; mit next_offset der vorigen Seite weiterblättern, bis has_more false ist.",
		}
		properties["limit"] = {
			"type": "integer",
			"minimum": 1,
			"description": f"Zeilen pro Seite, höchstens {EXPORT_VIEW_MAX_LIMIT} (größere Werte werden gekappt).",
		}
		self.name = self.tool_name
		self.description = (
			"NUR AUS CODE AUFRUFEN (z. B. run_tools_with_bash), nie direkt: liefert eine Seite mit bis zu "
			f"{EXPORT_VIEW_MAX_LIMIT} Zeilen einer Hausverwaltungs-View (apartments, tenant_contracts, invoices, "
			"open_items, payments) mit denselben Rechten und Filtern wie hv_query_view. Antwort: rows, total_count, "
			"has_more, next_offset. Für Exporte und Auswertungen großer Datenmengen; Ergebnis im Skript verarbeiten "
			"und nur eine Zusammenfassung ausgeben."
		)
		self.inputSchema = {
			"type": "object",
			"properties": properties,
			"required": ["view"],
			"additionalProperties": False,
		}
		self.source_app = "hausverwaltung"
		self.category = "read_only"
		self.requires_permission = "Mietvertrag"

	def execute(self, arguments):
		from hausverwaltung.hausverwaltung.services import assistant

		self.check_permission()
		self.validate_arguments(arguments)
		limit = min(int(arguments.get("limit") or EXPORT_VIEW_MAX_LIMIT), EXPORT_VIEW_MAX_LIMIT)
		result = assistant.hv_query_view(
			view=arguments["view"],
			fields=arguments.get("fields"),
			filters=arguments.get("filters"),
			order_by=arguments.get("order_by"),
			limit=limit,
			offset=arguments.get("offset"),
			max_limit=EXPORT_VIEW_MAX_LIMIT,
			candidate_limit=EXPORT_VIEW_CANDIDATE_LIMIT,
		)
		_raise_on_tool_error(result)
		payload = fac_output.export_view_payload(result, limit)
		if fac_output.output_size(payload) > fac_output.EXPORT_OUTPUT_MAX_CHARS:
			return {"ok": False, "error": {"code": "LIMIT_EXCEEDED", "message": "Exportseite zu gross; limit oder Felder verkleinern."}}
		return payload


class MailMergeTool(HausverwaltungReadTool):
	"""Controlled mail merge steps; errors stay structured so the model can explain `issues`."""

	def __init__(self):
		BaseTool.__init__(self)
		from hausverwaltung.hausverwaltung.agent_tools.mail_merge_tools import MAIL_MERGE_TOOLS

		definition = next(
			item["function"] for item in MAIL_MERGE_TOOLS if item["function"]["name"] == self.tool_name
		)
		self.name = self.tool_name
		self.description = definition["description"]
		self.inputSchema = deepcopy(definition["parameters"])
		_apply_limit_schema(self.tool_name, self.inputSchema)
		self.inputSchema["additionalProperties"] = False
		self.source_app = "hausverwaltung"
		self.category = "write" if self.tool_name == "agent_mail_merge_execute" else "read_only"
		self.requires_permission = "Serienbrief Vorlage"

	def execute(self, arguments):
		from hausverwaltung.hausverwaltung.agent_tools.mail_merge_tools import MAIL_MERGE_FUNCTIONS

		self.check_permission()
		arguments = _apply_limit(self.name, arguments)
		self.validate_arguments(arguments)
		result = MAIL_MERGE_FUNCTIONS[self.name](**arguments)
		result = fac_output.absolutize_urls(result, _link_base_url())
		return fac_output.enforce_output_budget(result, fac_output.MAIL_MERGE_OUTPUT_MAX_CHARS)


class Fac_agent_mail_merge_get_pdf(MailMergeTool):
	"""PDF bytes of a preview or stored draft, for code callers that save them as chat files."""

	tool_name = "agent_mail_merge_get_pdf"

	def __init__(self):
		BaseTool.__init__(self)
		self.name = self.tool_name
		self.description = (
			"NUR AUS CODE AUFRUFEN (z. B. run_tools_with_bash), nie direkt: liefert ein Serienbrief-PDF als "
			"content_base64 mit filename. Entweder preparation_token + recipient (Vorschau aus "
			"agent_mail_merge_prepare) oder document (gespeichertes Serienbrief Dokument aus "
			"agent_mail_merge_get_status). Im Skript base64-dekodieren und als /mnt/data/<filename> speichern; "
			"nur Dateiname und Größe ausgeben."
		)
		self.inputSchema = {
			"type": "object",
			"properties": {
				"preparation_token": {"type": "string"},
				"recipient": {"type": "string", "description": "Exakter Empfänger aus previews[].recipient."},
				"document": {"type": "string", "description": "Name des Serienbrief Dokuments."},
			},
			"additionalProperties": False,
		}
		self.source_app = "hausverwaltung"
		self.category = "read_only"
		self.requires_permission = "Serienbrief Vorlage"

	def execute(self, arguments):
		from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api

		self.check_permission()
		self.validate_arguments(arguments)
		result = mail_merge_api.get_pdf(**arguments)
		data = result.get("data") or {}
		if len(data.get("content_base64") or "") > fac_output.PDF_OUTPUT_MAX_CHARS:
			return {"ok": False, "error": {"code": "LIMIT_EXCEEDED", "message": "PDF zu groß für den Chat."}}
		return result


class ReportTool(HausverwaltungReadTool):
	"""ERPNext reports through FAC's report engine, with paging and output limits."""

	description = ""
	properties: ClassVar[dict] = {}
	required: tuple = ()

	def __init__(self):
		BaseTool.__init__(self)
		self.name = self.tool_name
		self.description = type(self).description
		self.inputSchema = {
			"type": "object",
			"properties": deepcopy(type(self).properties),
			"required": list(type(self).required),
			"additionalProperties": False,
		}
		_apply_limit_schema(self.tool_name, self.inputSchema)
		self.source_app = "hausverwaltung"
		self.category = "read_only"
		# Checked per report (roles) in `_permitted_report`.
		self.requires_permission = "Report"


_REPORT_NAME = {"type": "string", "description": "Exakter Berichtsname aus hv_report_list."}
_REPORT_FILTERS = {
	"type": "object",
	"description": (
		"Filter laut hv_report_requirements. Datum als YYYY-MM-DD, Links mit exaktem Namen "
		"(z. B. company). Nicht angegebene Pflichtfilter werden automatisch vorbelegt."
	),
}
_REPORT_COLUMNS = {
	"type": "array",
	"items": {"type": "string"},
	"description": "Optional: nur diese Spalten (fieldname) zurückgeben.",
}
_OFFSET = {"type": "integer", "minimum": 0, "description": "Startzeile; mit next_offset weiterblättern."}


def _permitted_report(report_name):
	if not report_name or not frappe.db.exists("Report", report_name):
		frappe.throw(f"Bericht nicht gefunden: {report_name}")
	report = frappe.get_cached_doc("Report", report_name)
	if report.disabled or not report.is_permitted():
		frappe.throw(f"Keine Berechtigung für den Bericht {report_name}.", frappe.PermissionError)
	if report.report_type == "Report Builder":
		frappe.throw("Report-Builder-Berichte werden nicht unterstützt; agent_list_docs verwenden.")
	return report


def _run_report(arguments):
	from frappe_assistant_core.plugins.core.tools.report_tools import ReportTools

	_permitted_report(arguments["report_name"])
	# Always JSON: the csv/excel formats of FAC would create files.
	return ReportTools.execute_report(
		report_name=arguments["report_name"], filters=arguments.get("filters") or {}, format="json"
	)


class Fac_hv_report_list(ReportTool):
	tool_name = "hv_report_list"
	description = (
		"Sucht ERPNext-Berichte (Script/Query Reports), z. B. Hauptbuch (General Ledger), Offene Posten "
		"(Accounts Receivable), Summen- und Saldenliste (Trial Balance) oder eigene Hausverwaltungsberichte. "
		"Liefert Name, Typ und Modul; danach hv_report_requirements und hv_run_report."
	)
	properties: ClassVar[dict] = {
		"query": {"type": "string", "description": "Suchbegriff im Namen oder Modul, deutsch oder englisch."},
		"module": {"type": "string", "description": "Optional: nur Berichte dieses Moduls, z. B. Accounts."},
		"limit": {"type": "integer"},
		"offset": _OFFSET,
	}

	def execute(self, arguments):
		self.check_permission()
		arguments = _apply_limit(self.name, arguments)
		self.validate_arguments(arguments)
		query = str(arguments.get("query") or "").strip().casefold()
		filters = {"disabled": 0, "report_type": ["in", ["Script Report", "Query Report"]]}
		if arguments.get("module"):
			filters["module"] = arguments["module"]
		matches = []
		for row in frappe.get_all(
			"Report", filters=filters, fields=["name", "report_type", "module"], order_by="name asc"
		):
			label = frappe._(row.name, lang="de")
			if query and not any(query in str(value).casefold() for value in (row.name, label, row.module)):
				continue
			if not frappe.get_cached_doc("Report", row.name).is_permitted():
				continue
			item = {"name": row.name, "report_type": row.report_type, "module": row.module}
			if label != row.name:
				item["label"] = label
			matches.append(item)
		offset = int(arguments.get("offset") or 0)
		page = matches[offset : offset + arguments["limit"]]
		next_offset = offset + len(page)
		return fac_output.enforce_output_budget(
			{
				"reports": page,
				"offset": offset,
				"returned": len(page),
				"total_count": len(matches),
				"has_more": next_offset < len(matches),
				"next_offset": next_offset if next_offset < len(matches) else None,
			}
		)


class Fac_hv_report_requirements(ReportTool):
	tool_name = "hv_report_requirements"
	description = (
		"Liest Pflicht- und optionale Filter (mit gültigen Werten) und Spalten eines ERPNext-Berichts. "
		"Vor hv_run_report aufrufen."
	)
	properties: ClassVar[dict] = {"report_name": _REPORT_NAME}
	required = ("report_name",)

	def execute(self, arguments):
		from frappe_assistant_core.plugins.core.tools.report_requirements import ReportRequirements

		self.check_permission()
		self.validate_arguments(arguments)
		_permitted_report(arguments["report_name"])
		result = ReportRequirements().execute(
			{
				"report_name": arguments["report_name"],
				"include_metadata": False,
				"include_columns": True,
				"include_filters": True,
			}
		)
		return fac_output.enforce_output_budget(result)


class Fac_hv_run_report(ReportTool):
	tool_name = "hv_run_report"
	description = (
		"Führt einen ERPNext-Bericht aus und liefert eine Seite Zeilen (Standard 20, höchstens 100) mit "
		"Spalten, total_count und next_offset. Filter vorher mit hv_report_requirements klären. Für "
		"Auswertungen über viele Zeilen hv_export_report aus Code verwenden."
	)
	properties: ClassVar[dict] = {
		"report_name": _REPORT_NAME,
		"filters": _REPORT_FILTERS,
		"columns": _REPORT_COLUMNS,
		"limit": {"type": "integer"},
		"offset": _OFFSET,
	}
	required = ("report_name",)

	def execute(self, arguments):
		self.check_permission()
		arguments = _apply_limit(self.name, arguments)
		self.validate_arguments(arguments)
		result = _run_report(arguments)
		if not result.get("success"):
			return result
		page = fac_output.report_page(
			result, int(arguments.get("offset") or 0), arguments["limit"], arguments.get("columns")
		)
		return fac_output.enforce_output_budget(page, hint=fac_output.REPORT_TRUNCATION_HINT)


class Fac_hv_export_report(ReportTool):
	"""Paged report rows for code callers only."""

	tool_name = "hv_export_report"
	description = (
		"NUR AUS CODE AUFRUFEN (z. B. run_tools_with_bash), nie direkt: wie hv_run_report, aber bis zu "
		f"{EXPORT_REPORT_MAX_LIMIT} Zeilen pro Seite. Antwort: columns, rows, total_count, has_more, "
		"next_offset. Ergebnis im Skript verarbeiten und nur eine Zusammenfassung ausgeben."
	)
	properties: ClassVar[dict] = {
		"report_name": _REPORT_NAME,
		"filters": _REPORT_FILTERS,
		"columns": _REPORT_COLUMNS,
		"limit": {
			"type": "integer",
			"minimum": 1,
			"description": f"Zeilen pro Seite, höchstens {EXPORT_REPORT_MAX_LIMIT} (größere Werte werden gekappt).",
		},
		"offset": _OFFSET,
	}
	required = ("report_name",)

	def execute(self, arguments):
		self.check_permission()
		self.validate_arguments(arguments)
		limit = min(int(arguments.get("limit") or EXPORT_REPORT_MAX_LIMIT), EXPORT_REPORT_MAX_LIMIT)
		result = _run_report(arguments)
		if not result.get("success"):
			return result
		page = fac_output.report_page(result, int(arguments.get("offset") or 0), limit, arguments.get("columns"))
		if fac_output.output_size(page) > fac_output.EXPORT_OUTPUT_MAX_CHARS:
			return {"ok": False, "error": {"code": "LIMIT_EXCEEDED", "message": "Berichtsseite zu gross; limit oder Spalten verkleinern."}}
		return page


def _link_base_url():
	# Site config key; external chat clients cannot resolve desk-relative links.
	return frappe.conf.get("hv_agent_link_base_url") or get_url()


for _name in FAC_MAIL_MERGE_TOOL_NAMES:
	globals()[f"Fac_{_name}"] = type(
		f"Fac_{_name}", (MailMergeTool,), {"tool_name": _name, "__module__": __name__}
	)


for _name in FAC_TOOL_NAMES:
	globals()[f"Fac_{_name}"] = type(
		f"Fac_{_name}", (HausverwaltungReadTool,), {"tool_name": _name, "__module__": __name__}
	)
