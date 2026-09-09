import re

import frappe
from frappe.model.document import Document

from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_schema import normalize_definitions


class HeizkostenmeldungVorlage(Document):
	def validate(self):
		if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.vorlagenkennung or ""):
			frappe.throw("Vorlagenkennung: nur Buchstaben, Ziffern, Bindestrich und Unterstrich.")
		if int(self.version or 0) < 1:
			frappe.throw("Die Versionsnummer muss mindestens 1 sein.")
		before = self.get_doc_before_save()
		if before and (self.vorlagenkennung, self.version) != (before.vorlagenkennung, before.version):
			frappe.throw(
				"Kennung und Versionsnummer sind nach dem Anlegen fest. Bitte neue Version erstellen."
			)
		try:
			normalize_definitions(self.felder or [])
		except ValueError as exc:
			frappe.throw(str(exc))

	def before_update_after_submit(self):
		frappe.throw("Freigegebene Vorlagenversionen sind unveränderlich. Bitte neue Version erstellen.")

	def on_cancel(self):
		if frappe.db.exists("Heizkostenmeldung", {"vorlage": self.name}):
			frappe.throw("Diese Vorlagenversion wird bereits in einer Heizkostenmeldung verwendet.")


@frappe.whitelist(methods=["POST"])
def neue_version(name):
	source = frappe.get_doc("Heizkostenmeldung Vorlage", name, for_update=True)
	source.check_permission("read")
	frappe.has_permission("Heizkostenmeldung Vorlage", "create", throw=True)
	versions = frappe.db.sql(
		"SELECT version FROM `tabHeizkostenmeldung Vorlage` WHERE vorlagenkennung=%s FOR UPDATE",
		source.vorlagenkennung,
	)
	doc = frappe.copy_doc(source)
	doc.version = max(row[0] for row in versions) + 1
	doc.vorgaenger = source.name
	doc.amended_from = None
	doc.insert()
	return doc.name
