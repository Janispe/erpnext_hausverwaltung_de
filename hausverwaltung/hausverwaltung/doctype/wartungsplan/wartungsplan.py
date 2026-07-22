from __future__ import annotations

from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, getdate, nowdate

INTERVALL_EINHEITEN = {"Tage", "Wochen", "Monate", "Jahre"}


def add_wartungsintervall(ausgangsdatum, anzahl: int, einheit: str) -> date:
	"""Add a maintenance interval while preserving Frappe's month-end semantics."""
	datum = getdate(ausgangsdatum)
	anzahl = cint(anzahl)
	if anzahl <= 0:
		raise ValueError("Intervallanzahl muss positiv sein")
	if einheit == "Tage":
		return getdate(add_days(datum, anzahl))
	if einheit == "Wochen":
		return getdate(add_days(datum, anzahl * 7))
	if einheit == "Monate":
		return getdate(add_months(datum, anzahl))
	if einheit == "Jahre":
		return getdate(add_months(datum, anzahl * 12))
	raise ValueError(f"Unbekannte Intervalleinheit: {einheit}")


def berechne_faelligkeitsstatus(
	status: str | None,
	naechste_faelligkeit,
	erinnerung_vorlauf_tage: int | None = 0,
	*,
	heute=None,
) -> str:
	if status != "Aktiv":
		return "Inaktiv"
	if not naechste_faelligkeit:
		return "Nicht terminiert"

	heute_d = getdate(heute or nowdate())
	faellig_d = getdate(naechste_faelligkeit)
	if faellig_d < heute_d:
		return "Überfällig"
	if faellig_d <= getdate(add_days(heute_d, max(cint(erinnerung_vorlauf_tage), 0))):
		return "Bald fällig"
	return "Geplant"


class Wartungsplan(Document):
	def validate(self) -> None:
		self._apply_anlagenart_defaults()
		self._validate_intervall()

		if not self.get("letzte_durchfuehrung"):
			self.naechste_faelligkeit = self.get("erste_faelligkeit")

		self.faelligkeitsstatus = berechne_faelligkeitsstatus(
			self.get("status"),
			self.get("naechste_faelligkeit"),
			self.get("erinnerung_vorlauf_tage"),
		)

	def _apply_anlagenart_defaults(self) -> None:
		if not self.get("technische_anlage"):
			return

		anlagenart = frappe.db.get_value("Technische Anlage", self.technische_anlage, "anlagenart")
		if not anlagenart:
			return

		defaults = frappe.db.get_value(
			"Anlagenart",
			anlagenart,
			[
				"standard_massnahmenart",
				"standard_intervall_anzahl",
				"standard_intervall_einheit",
				"erinnerung_vorlauf_tage",
			],
			as_dict=True,
		) or {}
		if not self.get("massnahmenart") and defaults.get("standard_massnahmenart"):
			self.massnahmenart = defaults.get("standard_massnahmenart")
		if not self.get("intervall_anzahl") and defaults.get("standard_intervall_anzahl"):
			self.intervall_anzahl = defaults.get("standard_intervall_anzahl")
		if not self.get("intervall_einheit") and defaults.get("standard_intervall_einheit"):
			self.intervall_einheit = defaults.get("standard_intervall_einheit")
		if self.get("erinnerung_vorlauf_tage") in (None, ""):
			self.erinnerung_vorlauf_tage = defaults.get("erinnerung_vorlauf_tage") or 0

	def _validate_intervall(self) -> None:
		if cint(self.get("intervall_anzahl")) <= 0:
			frappe.throw(_("Das Wartungsintervall muss größer als null sein."))
		if self.get("intervall_einheit") not in INTERVALL_EINHEITEN:
			frappe.throw(_("Bitte eine gültige Intervalleinheit auswählen."))
		if cint(self.get("erinnerung_vorlauf_tage")) < 0:
			frappe.throw(_("Der Erinnerungsvorlauf darf nicht negativ sein."))


def update_faelligkeitsstatus() -> None:
	"""Refresh stored due states so list filters stay correct without opening documents."""
	for row in frappe.get_all(
		"Wartungsplan",
		fields=["name", "status", "naechste_faelligkeit", "erinnerung_vorlauf_tage", "faelligkeitsstatus"],
	):
		neu = berechne_faelligkeitsstatus(
			row.status,
			row.naechste_faelligkeit,
			row.erinnerung_vorlauf_tage,
		)
		if neu != row.faelligkeitsstatus:
			frappe.db.set_value(
				"Wartungsplan", row.name, "faelligkeitsstatus", neu, update_modified=False
			)
