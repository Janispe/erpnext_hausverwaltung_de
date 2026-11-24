"""Keep the source file of an approved heating settlement attached and private."""

import frappe


class HeizkostenRuecklaufFileMixin:
	def on_trash(self):
		# Run before File.on_trash schedules deletion of the physical file.
		if self.attached_to_doctype == "Heizkostenabrechnung Immobilie" and self.attached_to_name:
			if frappe.db.get_value(self.attached_to_doctype, self.attached_to_name, "ruecklauf_datei", for_update=True) == self.name:
				frappe.throw("Die freigegebene D-Datei gehört zum Prüfprotokoll und kann nicht entfernt werden.")
		return super().on_trash()

	def validate(self):
		previous = self.get_doc_before_save()
		if previous and (previous.file_url or "").lower().endswith(".dat") and any(
			self.get(field) != previous.get(field)
			for field in ("is_private", "file_url", "attached_to_doctype", "attached_to_name", "content_hash")
		):
			# Frappe can share the same physical upload between several File records.
			# Changing visibility on an alias also moves the source of the approved import.
			approved = frappe.db.sql(
				"""SELECT head.name FROM `tabFile` AS source
				JOIN `tabHeizkostenabrechnung Immobilie` AS head ON head.ruecklauf_datei = source.name
				WHERE source.file_url = %s FOR UPDATE""",
				(previous.file_url,),
			)
			if approved:
				frappe.throw("Die freigegebene D-Datei gehört zum Prüfprotokoll und kann nicht geändert werden.")
		return super().validate()
