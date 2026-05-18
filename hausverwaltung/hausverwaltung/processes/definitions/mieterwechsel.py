from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag import _build_mietvertrag_tag_name
from hausverwaltung.hausverwaltung.doctype.wohnung.wohnung import _build_paperless_tag_name
from hausverwaltung.hausverwaltung.processes.engine import (
	ProcessPluginRegistry,
	ProcessRuntimeConfig,
	ProcessTrigger,
	register_process_runtime,
)
from hausverwaltung.hausverwaltung.processes.task_registry import (
	BaseTaskHandler,
	TASK_TYPE_MANUAL_CHECK,
	TASK_TYPE_PAPERLESS_EXPORT,
	TASK_TYPE_PYTHON_ACTION,
	TaskCheckResult,
	TaskHandlerContext,
	extract_task_config,
)

PROZESS_TYP_MIETERWECHSEL = "Mieterwechsel"
PROZESS_TYP_ERSTVERMIETUNG = "Erstvermietung"
PROZESS_TYP_BEIDE = "Beide"


class MieterwechselFlagTaskHandler(BaseTaskHandler):
	task_type = TASK_TYPE_PYTHON_ACTION

	def validate_config(self, step_or_task) -> None:
		config = extract_task_config(step_or_task)
		if not config and hasattr(step_or_task, "get"):
			try:
				config = dict(step_or_task)
			except Exception:
				config = {}
		target_field = (config.get("target_field") or getattr(step_or_task, "mapping_flag", None) or "").strip()
		if not target_field:
			frappe.throw(_("python_action fuer Mieterwechsel erfordert target_field oder mapping_flag."))
		if target_field not in {
			"neue_adresse_altmieter_erfasst",
			"zaehler_geprueft",
			"zaehlerstaende_eingetragen",
		}:
			frappe.throw(_("Unbekanntes target_field fuer Mieterwechsel python_action: {0}").format(target_field))

	def _read_flag(self, doc: Document, target_field: str):
		"""Liest target_field aus payload_json (Prozess Instanz) ODER nativem
		Feld (Backward-Compat fuer alte Mieterwechsel-Doctypes — heute nur noch
		theoretisch, nach Phase 4c-Cutover ausschliesslich payload)."""
		if hasattr(doc, "payload") and callable(doc.payload):
			return doc.payload(target_field)
		return doc.get(target_field)

	def _write_flag(self, doc: Document, target_field: str, value) -> None:
		if hasattr(doc, "payload_set") and callable(doc.payload_set):
			doc.payload_set(target_field, value)
			return
		doc.set(target_field, value)

	def is_fulfilled(self, context: TaskHandlerContext, doc: Document, task_row) -> TaskCheckResult:
		config = extract_task_config(task_row)
		target_field = (config.get("target_field") or getattr(task_row, "mapping_flag", None) or "").strip()
		return TaskCheckResult(
			fulfilled=bool(self._read_flag(doc, target_field)),
			meta={"target_field": target_field},
		)

	def run_action(self, context: TaskHandlerContext, doc: Document, task_row, payload: dict | None = None) -> dict:
		config = extract_task_config(task_row)
		target_field = (config.get("target_field") or getattr(task_row, "mapping_flag", None) or "").strip()
		self._write_flag(doc, target_field, 1)
		task_row.result_json = frappe.as_json({"target_field": target_field, "executed": True})
		task_row.status = "Erledigt"
		doc.save(ignore_permissions=True)
		return {"target_field": target_field, "executed": True}


def _is_erstvermietung(doc: Document) -> bool:
	"""Phase 4c: variant lebt jetzt in payload_json. Trigger setzt 'variant'
	auf 'mieterwechsel' (default) oder 'erstvermietung'."""
	if hasattr(doc, "payload") and callable(doc.payload):
		return (doc.payload("variant") or "").strip() == "erstvermietung"
	# Backward-Compat falls jemand die Funktion mit altem Mieterwechsel-Doc aufruft
	return (doc.get("prozess_typ") or "").strip() == PROZESS_TYP_ERSTVERMIETUNG


def _doc_field(doc: Document, key: str, default=None):
	"""Liest aus payload_json (Prozess Instanz) oder nativer Doc-Property."""
	if hasattr(doc, "payload") and callable(doc.payload):
		return doc.payload(key, default)
	return doc.get(key) or default


def _get_contract_data(contract_name: str | None) -> dict:
	if not contract_name:
		return {}
	return frappe.db.get_value("Mietvertrag", contract_name, ["name", "wohnung", "von", "bis"], as_dict=True) or {}


def validate_contract_consistency(doc: Document) -> None:
	"""Validator: nur konsistenz-checken was gesetzt ist.

	Beim ersten Save (frisch via 'Mieterwechsel starten'-Trigger) hat der User
	in der Regel nur alter_mietvertrag/wohnung, weil der neue Vertrag erst im
	Lauf des Prozesses entsteht. Strenge Pflichten ('Neuer Mietvertrag muss
	existieren', 'Auszugsdatum muss gesetzt sein') wandern in den
	Completion-Blocker — die feuern erst beim 'Abschluss'-Versuch."""
	wohnung = _doc_field(doc, "wohnung")
	if not wohnung:
		return
	alter = _doc_field(doc, "alter_mietvertrag")
	neuer = _doc_field(doc, "neuer_mietvertrag")
	auszug = _doc_field(doc, "auszugsdatum")
	einzug = _doc_field(doc, "einzugsdatum")

	# Nur pruefen wenn Felder GESETZT sind — leere Felder sind beim Save erlaubt.
	if alter:
		old_data = _get_contract_data(alter)
		if not old_data:
			frappe.throw(_("Alter Mietvertrag '{0}' wurde nicht gefunden.").format(alter))
		if old_data.get("wohnung") != wohnung:
			frappe.throw(_("Alter Mietvertrag gehoert nicht zur ausgewaehlten Wohnung."))
	if neuer:
		new_data = _get_contract_data(neuer)
		if not new_data:
			frappe.throw(_("Neuer Mietvertrag '{0}' wurde nicht gefunden.").format(neuer))
		if new_data.get("wohnung") != wohnung:
			frappe.throw(_("Neuer Mietvertrag gehoert nicht zur ausgewaehlten Wohnung."))
	if auszug and einzug and getdate(auszug) > getdate(einzug):
		frappe.throw(_("Auszugsdatum darf nicht nach Einzugsdatum liegen."))


def apply_contract_end_to_old_contract(doc: Document) -> None:
	if _is_erstvermietung(doc):
		return
	alter = _doc_field(doc, "alter_mietvertrag")
	auszug = _doc_field(doc, "auszugsdatum")
	if not alter or not auszug:
		return
	contract_end = frappe.db.get_value("Mietvertrag", alter, "bis")
	target = getdate(auszug)
	if contract_end and getdate(contract_end) == target:
		return
	frappe.db.set_value("Mietvertrag", alter, "bis", target, update_modified=False)


def get_completion_blockers(doc: Document) -> list[str]:
	blockers: list[str] = []
	alter = _doc_field(doc, "alter_mietvertrag")
	einzug = _doc_field(doc, "einzugsdatum")
	if not _is_erstvermietung(doc) and alter and einzug:
		old_end = frappe.db.get_value("Mietvertrag", alter, "bis")
		if not old_end:
			blockers.append(_("Beim alten Mietvertrag fehlt das Enddatum."))
		elif getdate(old_end) > getdate(einzug):
			blockers.append(_("Enddatum des alten Mietvertrags darf nicht nach Einzugsdatum liegen."))
	return blockers


def build_default_tags(doc: Document, variant: str) -> list[str]:
	# Phase 4c: doc ist jetzt Prozess Instanz mit domain-Daten in payload_json.
	# _doc_field unterstuetzt beide Pfade.
	alter = _doc_field(doc, "alter_mietvertrag")
	neuer = _doc_field(doc, "neuer_mietvertrag")
	w_name = _doc_field(doc, "wohnung")
	mv_old = _get_contract_data(alter)
	mv_new = _get_contract_data(neuer)
	wohnung = frappe.db.get_value(
		"Wohnung",
		w_name,
		["immobilie", "name__lage_in_der_immobilie", "name", "paperless_tag"],
		as_dict=True,
	) or {}
	wohnung_tag = (wohnung.get("paperless_tag") or "").strip() or _build_paperless_tag_name(
		wohnung.get("immobilie"),
		wohnung.get("name__lage_in_der_immobilie"),
		wohnung.get("name"),
	)
	tags = ["Mieterwechsel", f"Mieterwechsel {doc.name}", wohnung_tag, f"Mieterwechsel Dokument {variant}"]
	if mv_old:
		tags.append(
			_build_mietvertrag_tag_name(
				wohnung.get("immobilie"),
				wohnung.get("name__lage_in_der_immobilie"),
				wohnung.get("name"),
				mv_old.get("von"),
				mv_old.get("name"),
			)
		)
	if mv_new:
		tags.append(
			_build_mietvertrag_tag_name(
				wohnung.get("immobilie"),
				wohnung.get("name__lage_in_der_immobilie"),
				wohnung.get("name"),
				mv_new.get("von"),
				mv_new.get("name"),
			)
		)
	return [tag for tag in tags if (tag or "").strip()]
def trigger_payload_from_mietvertrag(src: Document) -> dict:
	return {
		"prozess_typ": PROZESS_TYP_MIETERWECHSEL,
		"wohnung": src.get("wohnung"),
		"alter_mietvertrag": src.name,
		"auszugsdatum": src.get("bis"),
		"einzugsdatum": src.get("bis"),
		"quelle_doctype": "Mietvertrag",
		"quelle_name": src.name,
	}


def trigger_payload_mieterwechsel_from_wohnung(src: Document) -> dict:
	return {
		"prozess_typ": PROZESS_TYP_MIETERWECHSEL,
		"wohnung": src.name,
		"quelle_doctype": "Wohnung",
		"quelle_name": src.name,
	}


def trigger_payload_erstvermietung_from_wohnung(src: Document) -> dict:
	return {
		"prozess_typ": PROZESS_TYP_ERSTVERMIETUNG,
		"wohnung": src.name,
		"neue_adresse_altmieter_erfasst": 1,
		"quelle_doctype": "Wohnung",
		"quelle_name": src.name,
	}


# === Phase 4b: Plugin-Registrierung ===
# Domain-Funktionen werden hier unter stabilen plugin_key in der globalen
# ProcessPluginRegistry verfuegbar gemacht. Ein Prozess Typ-Doc kann diese
# via Prozess Plugin Reference im UI selektieren. Die selben Funktionen bleiben
# fuer den Code-defined Mieterwechsel-Doctype direkt im _PROCESS_RUNTIMES-Eintrag
# (siehe get_mieterwechsel_runtime unten), damit Phase 1/2/3/3.5 unveraendert
# weiterlaufen.

ProcessPluginRegistry.register_validator(
	"mieterwechsel.contract_consistency", validate_contract_consistency
)
ProcessPluginRegistry.register_update_hook(
	"mieterwechsel.apply_contract_end", apply_contract_end_to_old_contract
)
ProcessPluginRegistry.register_completion_blocker(
	"mieterwechsel.completion_blockers", get_completion_blockers
)
ProcessPluginRegistry.register_custom_handler(
	"mieterwechsel.set_flag", MieterwechselFlagTaskHandler()
)
# Payload-Builder fuer DB-defined Trigger (Phase 4c-Vorbereitung)
ProcessPluginRegistry.register_payload_builder(
	"mieterwechsel.payload_from_mietvertrag", trigger_payload_from_mietvertrag
)
ProcessPluginRegistry.register_payload_builder(
	"mieterwechsel.payload_mieterwechsel_from_wohnung", trigger_payload_mieterwechsel_from_wohnung
)
ProcessPluginRegistry.register_payload_builder(
	"mieterwechsel.payload_erstvermietung_from_wohnung", trigger_payload_erstvermietung_from_wohnung
)
# Tag-Builder fuer Paperless-Export-Tasks (Phase 4c — payload-aware refactored)
ProcessPluginRegistry.register_tag_builder(
	"mieterwechsel.build_tags", build_default_tags
)


# Phase 4c: Mieterwechsel-Doctype geloescht. get_mieterwechsel_runtime existiert
# noch fuer Backward-Compat (alte Patches/Tests koennten es importieren), aber
# registriert KEINEN ProcessRuntimeConfig mehr. Die Mieterwechsel-Domain-Logik
# lebt jetzt ausschliesslich als Plugin-Registry-Eintraege + dem
# Prozess Typ "mieterwechsel"-Doc, das via Migration-Patch angelegt wird.

_RUNTIME: ProcessRuntimeConfig | None = None


def get_mieterwechsel_runtime() -> ProcessRuntimeConfig | None:
	"""DEPRECATED nach Phase 4c. Returnt None — die Mieterwechsel-Logik lebt jetzt
	als Plugin-Eintraege + UI-Doc 'Prozess Typ:mieterwechsel'. Bleibt als
	Funktion erhalten, damit ensure_process_runtimes_registered() weiterhin
	importieren kann ohne ImportError."""
	return None


def _legacy_register_unused():
	"""Ungenutzt — bleibt als Doku-Referenz, was hier vor Phase 4c stand.
	Tagbuilder, Trigger-Functions und Plugin-Registrierungen oben sind weiter
	aktiv ueber den Prozess Typ 'mieterwechsel' (siehe Migration-Patch)."""
	global _RUNTIME
	if _RUNTIME:
		return _RUNTIME
	_RUNTIME = register_process_runtime(
		ProcessRuntimeConfig(
			doctype="Mieterwechsel",
			process_version_doctype="Prozess Version",
			process_step_doctype="Prozess Schritt",
			default_process_type=PROZESS_TYP_MIETERWECHSEL,
			process_version_type_fieldname=None,
			both_process_type=PROZESS_TYP_BEIDE,
			task_handler_context=TaskHandlerContext(
				runtime_doctype="Mieterwechsel",
				file_detail_doctype="Prozess Aufgabe Datei",
				file_detail_doctype_field="prozess_doctype",
				file_detail_name_field="prozess_name",
				print_detail_doctype="Prozess Aufgabe Druck",
				print_detail_doctype_field="prozess_doctype",
				print_detail_name_field="prozess_name",
				tag_builder=build_default_tags,
				custom_handlers={"mieterwechsel.set_flag": MieterwechselFlagTaskHandler()},
			),
			validators=(validate_contract_consistency,),
			update_hooks=(apply_contract_end_to_old_contract,),
			completion_blockers=(get_completion_blockers,),
			triggers=(
				ProcessTrigger(
					key="mieterwechsel_from_mietvertrag",
					source_doctype="Mietvertrag",
					button_label="Mieterwechsel starten",
					payload_builder=trigger_payload_from_mietvertrag,
				),
				ProcessTrigger(
					key="mieterwechsel_from_wohnung",
					source_doctype="Wohnung",
					button_label="Mieterwechsel starten",
					payload_builder=trigger_payload_mieterwechsel_from_wohnung,
				),
				ProcessTrigger(
					key="erstvermietung_from_wohnung",
					source_doctype="Wohnung",
					button_label="Erstvermietung starten",
					payload_builder=trigger_payload_erstvermietung_from_wohnung,
				),
			),
		)
	)
	return _RUNTIME
