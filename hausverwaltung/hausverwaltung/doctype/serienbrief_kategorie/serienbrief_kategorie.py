from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.nestedset import get_descendants_of


class SerienbriefKategorie(Document):
	pass


def _unique_title(doctype: str, base_title: str) -> str:
	title = (base_title or "").strip() or "Kopie"
	if not frappe.db.exists(doctype, title):
		return title
	for idx in range(2, 200):
		candidate = f"{title} ({idx})"
		if not frappe.db.exists(doctype, candidate):
			return candidate
	raise frappe.ValidationError(_("Kein eindeutiger Titel verfügbar."))


def _copy_templates_for_kategorie(source_name: str, target_name: str) -> int:
	count = 0
	templates = frappe.get_all(
		"Serienbrief Vorlage",
		filters={"kategorie": source_name, "docstatus": ["<", 2]},
		pluck="name",
	)
	for template_name in templates:
		source_doc = frappe.get_doc("Serienbrief Vorlage", template_name)
		new_doc = frappe.copy_doc(source_doc)
		new_title = _unique_title("Serienbrief Vorlage", source_doc.title or source_doc.name)
		new_doc.title = new_title
		new_doc.name = None
		new_doc.kategorie = target_name
		new_doc.insert(ignore_permissions=True)
		count += 1
	return count


def _copy_kategorie_recursive(source_name: str, new_title: str | None, new_parent: str | None) -> str:
	source_doc = frappe.get_doc("Serienbrief Kategorie", source_name)
	target_title = _unique_title("Serienbrief Kategorie", new_title or source_doc.title or source_doc.name)

	target_doc = frappe.get_doc(
		{
			"doctype": "Serienbrief Kategorie",
			"title": target_title,
			"parent_serienbrief_kategorie": new_parent or None,
			"is_group": 1,
		}
	)
	target_doc.insert(ignore_permissions=True)

	_copy_templates_for_kategorie(source_name, target_doc.name)

	children = frappe.get_all(
		"Serienbrief Kategorie",
		filters={"parent_serienbrief_kategorie": source_name},
		pluck="name",
	)
	for child in children:
		_copy_kategorie_recursive(child, None, target_doc.name)
	return target_doc.name


@frappe.whitelist()
def get_kategorie_und_unterkategorien(kategorie: str | None = None) -> list[str]:
	"""Gibt Kategorie + alle Unterkategorien zurück (für 'Ordner'-Filter in der Vorlagenliste)."""

	name = (kategorie or "").strip()
	if not name:
		return []

	if not frappe.has_permission("Serienbrief Kategorie", "read", doc=name):
		frappe.throw(_("Keine Berechtigung, Serienbrief Kategorien zu lesen."), frappe.PermissionError)

	descendants = get_descendants_of("Serienbrief Kategorie", name) or []
	return [name, *descendants]


@frappe.whitelist()
def move_serienbrief_kategorie(name: str | None = None, new_parent: str | None = None) -> str:
	source_name = (name or "").strip()
	if not source_name:
		frappe.throw(_("Bitte einen Ordner auswählen."))

	if not frappe.has_permission("Serienbrief Kategorie", "write", doc=source_name):
		frappe.throw(_("Keine Berechtigung, Ordner zu verschieben."), frappe.PermissionError)

	if new_parent:
		if not frappe.db.exists("Serienbrief Kategorie", new_parent):
			frappe.throw(_("Zielordner existiert nicht."))
		if not frappe.has_permission("Serienbrief Kategorie", "read", doc=new_parent):
			frappe.throw(_("Keine Berechtigung für den Zielordner."), frappe.PermissionError)

	doc = frappe.get_doc("Serienbrief Kategorie", source_name)
	doc.parent_serienbrief_kategorie = new_parent or None
	doc.save(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def copy_serienbrief_kategorie(
	name: str | None = None,
	new_title: str | None = None,
	new_parent: str | None = None,
	copy_children: int | bool = 1,
) -> str:
	source_name = (name or "").strip()
	target_title = (new_title or "").strip()
	if not source_name:
		frappe.throw(_("Bitte einen Ordner auswählen."))
	if not target_title:
		frappe.throw(_("Bitte einen neuen Ordnernamen angeben."))

	if not frappe.has_permission("Serienbrief Kategorie", "read", doc=source_name):
		frappe.throw(_("Keine Berechtigung, Ordner zu lesen."), frappe.PermissionError)
	if not frappe.has_permission("Serienbrief Kategorie", "create"):
		frappe.throw(_("Keine Berechtigung, Ordner zu erstellen."), frappe.PermissionError)

	if new_parent:
		if not frappe.db.exists("Serienbrief Kategorie", new_parent):
			frappe.throw(_("Zielordner existiert nicht."))
		if not frappe.has_permission("Serienbrief Kategorie", "read", doc=new_parent):
			frappe.throw(_("Keine Berechtigung für den Zielordner."), frappe.PermissionError)

	copy_children = bool(copy_children)

	if not copy_children:
		target_title = _unique_title("Serienbrief Kategorie", target_title)
		doc = frappe.get_doc(
			{
				"doctype": "Serienbrief Kategorie",
				"title": target_title,
				"parent_serienbrief_kategorie": new_parent or None,
				"is_group": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		_copy_templates_for_kategorie(source_name, doc.name)
		return doc.name

	return _copy_kategorie_recursive(source_name, target_title, new_parent)
