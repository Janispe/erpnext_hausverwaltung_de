"""Local Mistral/FAC bridge; keeps credentials and execution inside Frappe.

FAC is optional. This module must remain importable without FAC installed.
External MCP clients use FAC's authenticated HTTP endpoint instead.
"""

import frappe
from frappe import _

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_TOOL_NAMES


def get_registry():
	if "frappe_assistant_core" not in frappe.get_installed_apps():
		frappe.throw(_("FAC ist nicht installiert. Bitte zuerst die FAC-Testumgebung einrichten."))
	if not frappe.db.get_single_value("Assistant Core Settings", "server_enabled"):
		frappe.throw(_("FAC ist in Assistant Core Settings deaktiviert."), frappe.PermissionError)
	if not frappe.db.get_value("User", frappe.session.user, "assistant_enabled"):
		frappe.throw(_("FAC-Zugriff ist fuer diesen Benutzer nicht aktiviert."), frappe.PermissionError)
	from frappe_assistant_core.core.tool_registry import get_tool_registry

	return get_tool_registry()


def available_tools():
	registry = get_registry()
	tools = [
		{
			"type": "function",
			"function": {
				"name": tool["name"],
				"description": tool["description"],
				"parameters": tool["inputSchema"],
			},
		}
		for tool in registry.get_available_tools(user=frappe.session.user)
		if tool["name"] in FAC_TOOL_NAMES
	]
	if not tools:
		frappe.throw(
			_(
				"Keine Hausverwaltungswerkzeuge in FAC freigegeben. Bitte custom_tools und Benutzerrechte pruefen."
			)
		)
	return tools


def execute_tool(name, arguments):
	if name not in FAC_TOOL_NAMES:
		return {"error": {"code": "UNKNOWN_TOOL", "message": f"Im FAC-Test nicht erlaubt: {name}"}}
	try:
		# Re-check settings, user access and FAC role/tool permissions on every call.
		return get_registry().execute_tool(name, arguments)
	except Exception as exc:
		return {"error": {"code": "FAC_TOOL_ERROR", "message": str(exc)}}


def system_prompt():
	from hausverwaltung.hausverwaltung.services import assistant

	# The base prompt ends before MAIL_MERGE_PROMPT is appended. The pilot has no writes.
	base = assistant.ASSISTANT_SYSTEM_PROMPT.removesuffix(assistant.MAIL_MERGE_PROMPT)
	base = base.replace(
		"Du liest Daten. Nur die unten beschriebenen Serienbrief-Werkzeuge duerfen auf Nutzerauftrag Dokumententwuerfe anlegen.",
		"Alle Werkzeuge lesen ausschliesslich Daten.",
	)
	return (
		base
		+ "\nFAC-Testmodus: Alle verfuegbaren Werkzeuge lesen nur Daten. Es gibt keine Serienbrief- oder Schreibwerkzeuge."
	)


def fallback_answer(tool_calls):
	"""An absent model answer is not evidence that no documents exist."""
	if any(call.get("error") for call in tool_calls):
		return (
			"Die Abfrage konnte nicht verlaesslich abgeschlossen werden: "
			"Werkzeugaufrufe sind fehlgeschlagen und das Modell hat keine Textantwort geliefert. "
			"Daraus laesst sich nicht ableiten, dass keine passenden Daten vorhanden sind."
		)
	return (
		"Das Modell hat keine auswertbare Textantwort geliefert. "
		"Bitte pruefe die Werkzeugergebnisse; dies bedeutet nicht, dass keine passenden Daten vorhanden sind."
	)
