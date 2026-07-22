from __future__ import annotations

from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate


class TechnischeAnlage(Document):
	def validate(self) -> None:
		self._validate_wohnung()
		self._validate_dates()
		self._validate_baujahr()

		if self.get("vorgaengeranlage") and self.vorgaengeranlage == self.name:
			frappe.throw(_("Eine technische Anlage kann nicht ihre eigene Vorgängeranlage sein."))

	def _validate_wohnung(self) -> None:
		if not self.get("wohnung"):
			return

		wohnung_immobilie = frappe.db.get_value("Wohnung", self.wohnung, "immobilie")
		if not wohnung_immobilie:
			frappe.throw(_("Die ausgewählte Wohnung besitzt keine Immobilienzuordnung."))
		if wohnung_immobilie != self.get("immobilie"):
			frappe.throw(
				_("Die Wohnung {0} gehört nicht zur Immobilie {1}.").format(
					self.wohnung, self.immobilie
				)
			)

	def _validate_dates(self) -> None:
		if (
			self.get("inbetriebnahme")
			and self.get("ausserbetriebnahme")
			and getdate(self.ausserbetriebnahme) < getdate(self.inbetriebnahme)
		):
			frappe.throw(_("Die Außerbetriebnahme darf nicht vor der Inbetriebnahme liegen."))

	def _validate_baujahr(self) -> None:
		if not self.get("baujahr"):
			return
		baujahr = cint(self.baujahr)
		if baujahr < 1800 or baujahr > date.today().year + 1:
			frappe.throw(_("Bitte ein plausibles Baujahr angeben."))
