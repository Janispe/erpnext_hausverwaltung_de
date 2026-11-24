"""Keep approved heating settlement source files attached and private."""

import json

import frappe

HEAD = "Heizkostenabrechnung Immobilie"


def _is_approved_source(name, protocol):
	if not protocol:
		return False
	approved = json.loads(protocol)
	return any(audit["datei"] == name for audit in (approved, *approved.get("historie", [])))


class HeizkostenRuecklaufFileMixin:
	def on_trash(self):
		# Run before File.on_trash schedules deletion of the physical file.
		if self.attached_to_doctype == HEAD and self.attached_to_name:
			protocol = frappe.db.get_value(HEAD, self.attached_to_name, "ruecklauf_import", for_update=True)
			if _is_approved_source(self.name, protocol):
				frappe.throw("Die freigegebene D-Datei gehört zum Prüfprotokoll und kann nicht entfernt werden.")
		return super().on_trash()

	def validate(self):
		previous = self.get_doc_before_save()
		if previous and (previous.file_url or "").lower().endswith(".dat") and any(
			self.get(field) != previous.get(field)
			for field in ("is_private", "file_url", "attached_to_doctype", "attached_to_name", "content_hash")
		):
			# Frappe can share the physical upload between several File records.
			# Changing visibility on an alias also moves the content of the approved import.
			attached = frappe.db.sql(
				"""SELECT attachment.name, head.ruecklauf_import FROM `tabFile` AS attachment
				JOIN `tabHeizkostenabrechnung Immobilie` AS head ON head.name = attachment.attached_to_name
				WHERE attachment.file_url = %s AND attachment.attached_to_doctype = %s FOR UPDATE""",
				(previous.file_url, HEAD),
			)
			if any(_is_approved_source(name, protocol) for name, protocol in attached):
				frappe.throw("Die freigegebene D-Datei gehört zum Prüfprotokoll und kann nicht geändert werden.")
		return super().validate()
