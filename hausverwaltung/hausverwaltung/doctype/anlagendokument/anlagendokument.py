from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, getdate, nowdate

ERLAUBTE_BEZUEGE = {
	"Technische Anlage",
	"Wartungstermin",
	"Anlagenwartung",
	"Anlagenmangel",
	"Wartungsvertrag",
}


class Anlagendokument(Document):
	def validate(self) -> None:
		if self.get("bezugsdoctype") not in ERLAUBTE_BEZUEGE:
			frappe.throw(_("Dieser Bezugstyp ist für Anlagendokumente nicht zulässig."))
		if self.get("ausgestellt_am") and self.get("gueltig_bis"):
			if getdate(self.gueltig_bis) < getdate(self.ausgestellt_am):
				frappe.throw(_("Das Gültigkeitsende darf nicht vor dem Ausstellungsdatum liegen."))
		if cint(self.get("erinnerung_vorlauf_tage")) < 0:
			frappe.throw(_("Der Erinnerungsvorlauf darf nicht negativ sein."))
		self._validate_replacement_chain()
		self.gueltigkeitsstatus = berechne_gueltigkeitsstatus(
			self.get("gueltig_bis"), self.get("erinnerung_vorlauf_tage")
		)

	def _validate_replacement_chain(self) -> None:
		aktuell = self.get("ersetzt_dokument")
		gesehen = {self.name}
		while aktuell:
			if aktuell in gesehen:
				frappe.throw(_("Die Dokumentversionen enthalten einen Kreis."))
			gesehen.add(aktuell)
			werte = (
				frappe.db.get_value(
					"Anlagendokument",
					aktuell,
					["ersetzt_dokument", "bezugsdoctype", "bezug", "dokumentart"],
					as_dict=True,
				)
				or {}
			)
			if werte and (
				werte.get("bezugsdoctype") != self.get("bezugsdoctype")
				or werte.get("bezug") != self.get("bezug")
				or werte.get("dokumentart") != self.get("dokumentart")
			):
				frappe.throw(
					_("Eine Dokumentversion muss denselben Bezug und dieselbe Dokumentart besitzen.")
				)
			aktuell = werte.get("ersetzt_dokument")


def berechne_gueltigkeitsstatus(gueltig_bis, erinnerung_vorlauf_tage=30, *, heute=None) -> str:
	if not gueltig_bis:
		return "Unbefristet"
	heute_d = getdate(heute or nowdate())
	gueltig_d = getdate(gueltig_bis)
	if gueltig_d < heute_d:
		return "Abgelaufen"
	if gueltig_d <= getdate(add_days(heute_d, max(cint(erinnerung_vorlauf_tage), 0))):
		return "Läuft bald ab"
	return "Gültig"


def update_gueltigkeitsstatus() -> None:
	for row in frappe.get_all(
		"Anlagendokument",
		fields=["name", "gueltig_bis", "erinnerung_vorlauf_tage", "gueltigkeitsstatus"],
	):
		status = berechne_gueltigkeitsstatus(row.gueltig_bis, row.erinnerung_vorlauf_tage)
		if status != row.gueltigkeitsstatus:
			frappe.db.set_value(
				"Anlagendokument", row.name, "gueltigkeitsstatus", status, update_modified=False
			)
