from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class HausverwaltungEinstellungen(Document):
	def validate(self):
		self.validate_abschreibungskonto_forderungen()
		self.validate_assistant_models()

	def validate_assistant_models(self):
		seen_models: set[str] = set()
		default_models: list[str] = []
		for row in self.get("assistant_models") or []:
			model = str(row.modell or "").strip()
			label = str(row.bezeichnung or "").strip()
			if not model:
				frappe.throw(_("In Zeile {0} der Assistenten-Modelle fehlt der Modellname.").format(row.idx))
			if model == "default":
				frappe.throw(_("Der Modellname 'default' ist reserviert."))
			if model in seen_models:
				frappe.throw(_("Das Assistenten-Modell {0} ist doppelt eingetragen.").format(model))
			seen_models.add(model)
			row.modell = model
			row.bezeichnung = label or model
			if cint(row.standard) and not cint(row.aktiv):
				frappe.throw(_("Das Standardmodell {0} muss aktiv sein.").format(row.bezeichnung))
			if cint(row.standard):
				default_models.append(row.bezeichnung)
		if len(default_models) > 1:
			frappe.throw(_("Es darf nur ein Assistenten-Modell als Standard markiert sein."))

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
