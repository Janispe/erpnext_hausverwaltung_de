from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class Anlagenart(Document):
	def validate(self) -> None:
		anzahl = cint(self.get("standard_intervall_anzahl"))
		einheit = self.get("standard_intervall_einheit")

		if anzahl < 0:
			frappe.throw(_("Das Standardintervall darf nicht negativ sein."))
		if bool(anzahl) != bool(einheit):
			frappe.throw(
				_("Für das Standardintervall müssen Anzahl und Einheit gemeinsam angegeben werden.")
			)
		if cint(self.get("erinnerung_vorlauf_tage")) < 0:
			frappe.throw(_("Der Erinnerungsvorlauf darf nicht negativ sein."))
