from __future__ import annotations

import json
from pathlib import Path

import frappe


CATEGORY = "Mahnungen Mietzahlungen"

ARCHIVE_DIR = Path("archive") / "serienbrief_vorlagen_2026-05-26"

TEMPLATE_FILES = (
	"-_Miete_-_Mahnung_1-2-3_-_allgemeine_Vorlage_mit_allen_Sätzen.json",
	"Miete_-_Zahlungserinnerung.json",
	"Miete_-_Mahnung_1.json",
	"Miete_-_Mahnung_1_-_Untermietzuschlag_fehlt.json",
	"Miete_-_Mahnung_1_-_zu_wenig_gezahlt.json",
	"Miete_-_Mahnung_2.json",
	"Miete_-_Mahnung_3_-.json",
	"Staffelmiete-0-Zahlungserinnerung.json",
	"Staffelmiete_1_Mahnung.json",
	"Staffelmiete_2_Mahnung.json",
	"Staffelmiete_3_Mahnung.json",
	"Staffelmiete_3_Mahnung_teilweise_Zahlung.json",
)

SYSTEM_FIELDS = {
	"doctype",
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"idx",
	"parent",
	"parentfield",
	"parenttype",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
}


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Vorlage"):
		return

	archive_path = _get_archive_path()
	if not archive_path:
		frappe.log_error(
			"Archiv fuer Mahnungen-Mietzahlungen-Vorlagen nicht gefunden.",
			"restore_mahnungen_mietzahlungen_archive_templates",
		)
		return

	_ensure_category()

	for filename in TEMPLATE_FILES:
		file_path = archive_path / filename
		if not file_path.exists():
			frappe.log_error(
				f"Archiv-Vorlage fehlt: {file_path}",
				"restore_mahnungen_mietzahlungen_archive_templates",
			)
			continue
		_upsert_template(json.loads(file_path.read_text(encoding="utf-8")))

	frappe.db.commit()
	frappe.clear_cache(doctype="Serienbrief Vorlage")


def _get_archive_path() -> Path | None:
	try:
		app_root = Path(frappe.get_app_path("hausverwaltung_peters")).parent
	except Exception:
		return None

	archive_path = app_root / ARCHIVE_DIR
	return archive_path if archive_path.exists() else None


def _ensure_category() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Kategorie"):
		return
	if frappe.db.exists("Serienbrief Kategorie", CATEGORY):
		return

	payload = {
		"doctype": "Serienbrief Kategorie",
		"title": CATEGORY,
		"is_group": 0,
	}
	parent = "Unsere Briefe" if frappe.db.exists("Serienbrief Kategorie", "Unsere Briefe") else None
	if parent:
		payload["parent_serienbrief_kategorie"] = parent
	frappe.get_doc(payload).insert(ignore_permissions=True)


def _upsert_template(source: dict) -> None:
	name = (source.get("name") or "").strip()
	if not name:
		return

	doc = _get_existing_template(source)
	if not doc:
		doc = frappe.new_doc("Serienbrief Vorlage")

	_copy_main_fields(doc, source)
	_copy_child_table(doc, source, "variables")
	_copy_child_table(doc, source, "textbausteine")

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


def _get_existing_template(source: dict):
	"""Resolve existing templates before copying fields.

	``Serienbrief Vorlage`` is named from ``title``. Older restored data can have a
	name/title mismatch, so resolving only by archived ``name`` can make save()
	try to reload a non-existing document name.
	"""
	names = [
		(source.get("name") or "").strip(),
		(source.get("title") or "").strip(),
	]
	for candidate in dict.fromkeys(filter(None, names)):
		if frappe.db.exists("Serienbrief Vorlage", candidate):
			return frappe.get_doc("Serienbrief Vorlage", candidate)

	title = (source.get("title") or source.get("name") or "").strip()
	if title:
		existing_name = frappe.db.get_value("Serienbrief Vorlage", {"title": title}, "name")
		if existing_name:
			return frappe.get_doc("Serienbrief Vorlage", existing_name)

	return None


def _copy_main_fields(doc, source: dict) -> None:
	meta = frappe.get_meta("Serienbrief Vorlage")
	table_fields = {
		field.fieldname for field in meta.fields if field.fieldtype == "Table" and field.fieldname
	}
	for field in meta.fields:
		fieldname = field.fieldname
		if not fieldname or fieldname in table_fields:
			continue
		if fieldname in source:
			doc.set(fieldname, source.get(fieldname))

	doc.set("title", source.get("title") or source.get("name"))
	doc.set("kategorie", CATEGORY)


def _copy_child_table(doc, source: dict, table_field: str) -> None:
	rows = source.get(table_field) or []
	meta_field = frappe.get_meta("Serienbrief Vorlage").get_field(table_field)
	if not meta_field or not meta_field.options:
		return

	child_meta = frappe.get_meta(meta_field.options)
	allowed_fields = {
		field.fieldname
		for field in child_meta.fields
		if field.fieldname and field.fieldtype != "Table" and field.fieldname not in SYSTEM_FIELDS
	}

	doc.set(table_field, [])
	for source_row in rows:
		row = {
			fieldname: source_row.get(fieldname)
			for fieldname in allowed_fields
			if fieldname in source_row
		}
		doc.append(table_field, row)
