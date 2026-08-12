from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from hausverwaltung.hausverwaltung.doctype.wartungsplan.wartungsplan import INTERVALL_EINHEITEN


class WartungsmassnahmeVorlage(Document):
	def validate(self) -> None:
		self._validate_intervall(
			self.get("intervall_anzahl"),
			self.get("intervall_einheit"),
			_("Wartungsintervall"),
		)
		if self.get("erstfaelligkeit_anzahl") or self.get("erstfaelligkeit_einheit"):
			self._validate_intervall(
				self.get("erstfaelligkeit_anzahl"),
				self.get("erstfaelligkeit_einheit"),
				_("Erstfälligkeit"),
			)
		if cint(self.get("erinnerung_vorlauf_tage")) < 0:
			frappe.throw(_("Der Erinnerungsvorlauf darf nicht negativ sein."))
		if cint(self.get("eskalation_nach_tagen")) < 0:
			frappe.throw(_("Die Eskalationsfrist darf nicht negativ sein."))

		frappe.db.sql("SELECT name FROM `tabAnlagenart` WHERE name = %s FOR UPDATE", (self.anlagenart,))
		duplikat = frappe.db.exists(
			"Wartungsmassnahme Vorlage",
			{
				"anlagenart": self.anlagenart,
				"bezeichnung": self.bezeichnung,
				"name": ("!=", self.name or ""),
			},
		)
		if duplikat:
			frappe.throw(
				_(
					"Für die Anlagenart {0} existiert bereits eine Maßnahmevorlage mit dieser Bezeichnung."
				).format(self.anlagenart)
			)

	@staticmethod
	def _validate_intervall(anzahl, einheit, label: str) -> None:
		if cint(anzahl) <= 0:
			frappe.throw(_("{0}: Die Anzahl muss größer als null sein.").format(label))
		if einheit not in INTERVALL_EINHEITEN:
			frappe.throw(_("{0}: Bitte eine gültige Intervalleinheit auswählen.").format(label))
