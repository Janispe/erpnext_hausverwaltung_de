from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


FIELD_REPLACEMENTS = {
	"doc": "objekt",
	"iteration_doc": "objekt",
	"iteration_objekt": "objekt",
	"serienbrief_titel": "serienbrief.titel",
	"empfaenger_index": "serienbrief.index",
	"empfaenger_count": "serienbrief.count",
	"empfaenger_anzeigename": "empfaenger.anzeigename",
	"mieter_name": "empfaenger.mieter_name",
	"mieter_strasse": "empfaenger.strasse",
	"mieter_plz": "empfaenger.plz",
	"mieter_ort": "empfaenger.ort",
	"mieter_plz_ort": "empfaenger.plz_ort",
	"mieter_adresse": "empfaenger.adresse",
}

LEGACY_ROOTS = {
	"mieter",
	"mieter_doc",
	"wohnung",
	"wohnung_doc",
	"immobilie",
	"immobilie_doc",
	"eigentuemer",
	"eigentuemer_doc",
	"mietvertrag",
	"mietvertrag_doc",
	"bank_name",
	"bank_iban",
	"bank_bic",
	"bank_blz",
	"bank_konto",
	"bank_kto_inhaber",
	"vorauszahlung_1",
	"vorauszahlung_2",
	"vorauszahlung_3",
	"vorauszahlung_4",
}


def execute():
	_backfill_baustein_keys()
	_migrate_template_sources()
	_migrate_block_sources()
	_drop_legacy_reference_doctype()


def _replace_known_roots(source: str | None) -> tuple[str | None, bool]:
	if not source:
		return source, False
	updated = source
	for old, new in FIELD_REPLACEMENTS.items():
		updated = re.sub(rf"\b{re.escape(old)}\b", new, updated)
	return updated, updated != source


def _log_legacy_roots(owner: str, fieldname: str, source: str | None) -> None:
	if not source:
		return
	found = sorted(root for root in LEGACY_ROOTS if re.search(rf"\b{re.escape(root)}\b", source))
	if not found:
		return
	frappe.log_error(
		title="Serienbrief Legacy-Kontext Migration",
		message=(
			f"{owner}.{fieldname} enthält nach der Best-effort-Migration noch "
			f"Legacy-Root-Variablen: {', '.join(found)}"
		),
	)


def _backfill_baustein_keys() -> None:
	rows = frappe.get_all(
		"Serienbrief Vorlagenbaustein",
		fields=["name", "parent", "baustein", "baustein_key", "idx"],
		order_by="parent asc, idx asc",
	)
	seen_by_parent: dict[str, dict[str, int]] = {}
	for row in rows:
		if cstr(row.baustein_key).strip() or not cstr(row.baustein).strip():
			continue
		seen = seen_by_parent.setdefault(row.parent, {})
		base = frappe.scrub(row.baustein) or "baustein"
		seen[base] = seen.get(base, 0) + 1
		key = base if seen[base] == 1 else f"{base}_{seen[base]}"
		frappe.db.set_value("Serienbrief Vorlagenbaustein", row.name, "baustein_key", key, update_modified=False)


def _migrate_template_sources() -> None:
	for row in frappe.get_all(
		"Serienbrief Vorlage",
		fields=["name", "content", "html_content", "jinja_content"],
	):
		updates = {}
		for fieldname in ("content", "html_content", "jinja_content"):
			updated, changed = _replace_known_roots(row.get(fieldname))
			if changed:
				updates[fieldname] = updated
			_log_legacy_roots(f"Serienbrief Vorlage {row.name}", fieldname, updated)
		if updates:
			frappe.db.set_value("Serienbrief Vorlage", row.name, updates, update_modified=False)


def _migrate_block_sources() -> None:
	for row in frappe.get_all(
		"Serienbrief Textbaustein",
		fields=["name", "text_content", "html_content", "jinja_content"],
	):
		updates = {}
		for fieldname in ("text_content", "html_content", "jinja_content"):
			updated, changed = _replace_known_roots(row.get(fieldname))
			if changed:
				updates[fieldname] = updated
			_log_legacy_roots(f"Serienbrief Textbaustein {row.name}", fieldname, updated)
		if updates:
			frappe.db.set_value("Serienbrief Textbaustein", row.name, updates, update_modified=False)


def _drop_legacy_reference_doctype() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein Referenz"):
		return
	try:
		frappe.delete_doc(
			"DocType",
			"Serienbrief Textbaustein Referenz",
			force=True,
			ignore_permissions=True,
		)
	except Exception:
		frappe.log_error(
			title="Serienbrief Legacy-Referenz Doctype entfernen",
			message=frappe.get_traceback(),
		)
