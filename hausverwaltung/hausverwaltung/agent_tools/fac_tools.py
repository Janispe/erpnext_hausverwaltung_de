"""Expose existing permission-checked tools through FAC's registry and MCP endpoint."""

from copy import deepcopy

import frappe
from frappe.utils import get_url
from frappe_assistant_core.core.base_tool import BaseTool
from jsonschema import validate

from hausverwaltung.hausverwaltung.agent_tools import fac_output
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_MAIL_MERGE_TOOL_NAMES, FAC_TOOL_NAMES

EXPORT_VIEW_MAX_LIMIT = 1000
EXPORT_VIEW_CANDIDATE_LIMIT = 20_000

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
		return fac_output.enforce_output_budget(payload, fac_output.EXPORT_OUTPUT_MAX_CHARS)


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
		self.inputSchema["additionalProperties"] = False
		self.source_app = "hausverwaltung"
		self.category = "write" if self.tool_name == "agent_mail_merge_execute" else "read_only"
		self.requires_permission = "Serienbrief Vorlage"

	def execute(self, arguments):
		from hausverwaltung.hausverwaltung.agent_tools.mail_merge_tools import MAIL_MERGE_FUNCTIONS

		self.check_permission()
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
