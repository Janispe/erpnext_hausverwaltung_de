from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class Anlagenmangel(Document):
	def validate(self) -> None:
		self._apply_source_defaults()
		self._validate_dates()
		self._set_title()

	def on_update(self) -> None:
		if self.get("anlage_sperren") and self.get("status") not in {"Behoben", "Akzeptiert"}:
			anlage = frappe.get_doc("Technische Anlage", self.technische_anlage)
			if anlage.status == "Aktiv":
				anlage.status = "Außer Betrieb"
				anlage.status_seit = nowdate()
				anlage.stilllegungsgrund = _("Kritischer/offener Mangel {0}").format(self.name)
				anlage.save(ignore_permissions=True)

	def _apply_source_defaults(self) -> None:
		if self.get("anlagenwartung"):
			werte = (
				frappe.db.get_value(
					"Anlagenwartung",
					self.anlagenwartung,
					["technische_anlage", "wartungstermin", "durchgefuehrt_am"],
					as_dict=True,
				)
				or {}
			)
			if self.get("technische_anlage") and self.technische_anlage != werte.get("technische_anlage"):
				frappe.throw(_("Mangel und Anlagenwartung beziehen sich nicht auf dieselbe Anlage."))
			self.technische_anlage = self.get("technische_anlage") or werte.get("technische_anlage")
			self.wartungstermin = self.get("wartungstermin") or werte.get("wartungstermin")
			self.festgestellt_am = self.get("festgestellt_am") or werte.get("durchgefuehrt_am")

	def _validate_dates(self) -> None:
		if self.get("festgestellt_am") and self.get("behebungsfrist"):
			if getdate(self.behebungsfrist) < getdate(self.festgestellt_am):
				frappe.throw(_("Die Behebungsfrist darf nicht vor der Feststellung liegen."))
		if self.get("status") == "Behoben" and not self.get("behoben_am"):
			self.behoben_am = nowdate()
		if self.get("behoben_am") and self.get("festgestellt_am"):
			if getdate(self.behoben_am) < getdate(self.festgestellt_am):
				frappe.throw(_("Das Behebungsdatum darf nicht vor der Feststellung liegen."))

	def _set_title(self) -> None:
		if self.get("bezeichnung"):
			return
		teile = [self.get("schweregrad"), self.get("technische_anlage")]
		if self.get("festgestellt_am"):
			teile.append(str(getdate(self.festgestellt_am)))
		self.bezeichnung = " · ".join(str(teil) for teil in teile if teil)
