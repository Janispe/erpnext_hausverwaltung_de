from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class HausverwaltungEinstellungen(Document):
	def validate(self):
		self.validate_abschreibungskonto_forderungen()

	def validate_abschreibungskonto_forderungen(self):
		if not self.abschreibungskonto_forderungen:
			return

		account = frappe.db.get_value(
			"Account",
			self.abschreibungskonto_forderungen,
			["root_type", "is_group", "disabled"],
			as_dict=True,
		)
		if not account:
			frappe.throw(
				_("Abschreibungskonto Forderungen {0} wurde nicht gefunden.").format(
					self.abschreibungskonto_forderungen
				)
			)
		if int(account.get("is_group") or 0):
			frappe.throw(_("Abschreibungskonto Forderungen muss ein Blattkonto sein."))
		if int(account.get("disabled") or 0):
			frappe.throw(_("Abschreibungskonto Forderungen darf nicht deaktiviert sein."))
		if account.get("root_type") != "Expense":
			frappe.throw(_("Abschreibungskonto Forderungen muss ein Aufwandskonto sein."))
