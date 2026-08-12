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
		self._apply_template_defaults()
		self._validate_links()
		self._validate_intervall()
		self._validate_dates()
		self._validate_unique_active_plan()
		self._validate_immutable_links()

		if self.get("letzte_durchfuehrung"):
			self._set_naechste_faelligkeit_from_latest_maintenance()
		else:
			self.naechste_faelligkeit = self.get("erste_faelligkeit")
		if (
			self.get("gueltig_bis")
			and self.get("naechste_faelligkeit")
			and getdate(self.naechste_faelligkeit) > getdate(self.gueltig_bis)
		):
			self.status = "Beendet"

		self.faelligkeitsstatus = berechne_faelligkeitsstatus(
			self.get("status"),
			self.get("naechste_faelligkeit"),
			self.get("erinnerung_vorlauf_tage"),
		)

	def on_update(self) -> None:
		from hausverwaltung.hausverwaltung.doctype.wartungstermin.wartungstermin import (
			synchronisiere_offenen_termin,
		)

		synchronisiere_offenen_termin(self.name)

	def on_trash(self) -> None:
		for doctype in ("Wartungstermin", "Anlagenwartung"):
			if frappe.db.exists(doctype, {"wartungsplan": self.name}):
				frappe.throw(
					_("Der Wartungsplan besitzt verknüpfte {0} und darf nur beendet werden.").format(
						frappe.bold(_(doctype))
					)
				)

	def _set_naechste_faelligkeit_from_latest_maintenance(self) -> None:
		"""Recalculate derived dates with the plan's currently configured interval."""
		eintraege = frappe.get_all(
			"Anlagenwartung",
			filters={
				"wartungsplan": self.name,
				"docstatus": 1,
				"status": "Durchgeführt",
			},
			fields=["name", "durchgefuehrt_am", "soll_termin", "naechster_termin"],
			order_by="durchgefuehrt_am desc, name desc",
			limit_page_length=1,
		)
		if not eintraege:
			return

		letzte = eintraege[0]
		self.letzte_durchfuehrung = getdate(letzte.durchgefuehrt_am)
		if letzte.get("naechster_termin"):
			self.naechste_faelligkeit = getdate(letzte.naechster_termin)
			return

		basis = self.letzte_durchfuehrung
		if self.get("terminberechnung") == "Ab bisheriger Fälligkeit":
			basis = getdate(letzte.get("soll_termin") or self.get("erste_faelligkeit"))
		self.naechste_faelligkeit = add_wartungsintervall(
			basis,
			self.get("intervall_anzahl"),
			self.get("intervall_einheit"),
		)

	def _apply_template_defaults(self) -> None:
		if not self.get("massnahmenvorlage"):
			return
		defaults = (
			frappe.db.get_value(
				"Wartungsmassnahme Vorlage",
				self.massnahmenvorlage,
				[
					"massnahmenart",
					"intervall_anzahl",
					"intervall_einheit",
					"terminberechnung",
					"erinnerung_vorlauf_tage",
					"eskalation_nach_tagen",
				],
				as_dict=True,
			)
			or {}
		)
		if not self.get("massnahmenart") and defaults.get("massnahmenart"):
			self.massnahmenart = defaults.get("massnahmenart")
		if not self.get("intervall_anzahl") and defaults.get("intervall_anzahl"):
			self.intervall_anzahl = defaults.get("intervall_anzahl")
		if not self.get("intervall_einheit") and defaults.get("intervall_einheit"):
			self.intervall_einheit = defaults.get("intervall_einheit")
		if not self.get("terminberechnung") and defaults.get("terminberechnung"):
			self.terminberechnung = defaults.get("terminberechnung")
		if self.get("erinnerung_vorlauf_tage") in (None, ""):
			self.erinnerung_vorlauf_tage = defaults.get("erinnerung_vorlauf_tage") or 0
		if self.get("eskalation_nach_tagen") in (None, ""):
			self.eskalation_nach_tagen = defaults.get("eskalation_nach_tagen") or 0

	def _validate_links(self) -> None:
		anlage_art = frappe.db.get_value("Technische Anlage", self.technische_anlage, "anlagenart")
		vorlage_art = frappe.db.get_value("Wartungsmassnahme Vorlage", self.massnahmenvorlage, "anlagenart")
		if anlage_art != vorlage_art:
			frappe.throw(_("Maßnahmevorlage und technische Anlage gehören nicht zur selben Anlagenart."))
		anlage_status = frappe.db.get_value("Technische Anlage", self.technische_anlage, "status")
		if self.get("status") == "Aktiv" and anlage_status != "Aktiv":
			frappe.throw(_("Für eine nicht aktive Anlage kann kein aktiver Wartungsplan geführt werden."))

	def _validate_dates(self) -> None:
		if self.get("gueltig_von") and self.get("gueltig_bis"):
			if getdate(self.gueltig_bis) < getdate(self.gueltig_von):
				frappe.throw(_("Das Ende des Wartungsplans darf nicht vor seinem Beginn liegen."))
		if self.get("gueltig_bis") and self.get("erste_faelligkeit"):
			if getdate(self.erste_faelligkeit) > getdate(self.gueltig_bis):
				frappe.throw(_("Die erste Fälligkeit liegt nach dem Ende des Wartungsplans."))
		if self.get("gueltig_von") and self.get("erste_faelligkeit"):
			if getdate(self.erste_faelligkeit) < getdate(self.gueltig_von):
				frappe.throw(_("Die erste Fälligkeit liegt vor dem Beginn des Wartungsplans."))

	def _validate_unique_active_plan(self) -> None:
		if self.get("status") == "Beendet":
			return
		frappe.db.sql(
			"SELECT name FROM `tabTechnische Anlage` WHERE name = %s FOR UPDATE",
			(self.technische_anlage,),
		)
		duplikat = frappe.db.exists(
			"Wartungsplan",
			{
				"technische_anlage": self.technische_anlage,
				"massnahmenvorlage": self.massnahmenvorlage,
				"status": ("in", ("Aktiv", "Pausiert")),
				"name": ("!=", self.name or ""),
			},
		)
		if duplikat:
			frappe.throw(
				_("Für diese Anlage und Maßnahmevorlage existiert bereits ein laufender Wartungsplan.")
			)

	def _validate_immutable_links(self) -> None:
		if self.is_new():
			return
		geschuetzte_felder = (
			"technische_anlage",
			"massnahmenvorlage",
			"intervall_anzahl",
			"intervall_einheit",
			"terminberechnung",
			"erste_faelligkeit",
		)
		if any(self.has_value_changed(feld) for feld in geschuetzte_felder) and frappe.db.exists(
			"Wartungstermin", {"wartungsplan": self.name}
		):
			frappe.throw(
				_(
					"Anlage, Vorlage und Terminregel können nach Erzeugung von Wartungsterminen nicht geändert werden. Beenden Sie den Plan und legen Sie einen neuen an."
				)
			)

	def _validate_intervall(self) -> None:
		if cint(self.get("intervall_anzahl")) <= 0:
			frappe.throw(_("Das Wartungsintervall muss größer als null sein."))
		if self.get("intervall_einheit") not in INTERVALL_EINHEITEN:
			frappe.throw(_("Bitte eine gültige Intervalleinheit auswählen."))
		if cint(self.get("erinnerung_vorlauf_tage")) < 0:
			frappe.throw(_("Der Erinnerungsvorlauf darf nicht negativ sein."))
		if cint(self.get("eskalation_nach_tagen")) < 0:
			frappe.throw(_("Die Eskalationsfrist darf nicht negativ sein."))


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
			frappe.db.set_value("Wartungsplan", row.name, "faelligkeitsstatus", neu, update_modified=False)
		from hausverwaltung.hausverwaltung.doctype.wartungstermin.wartungstermin import (
			synchronisiere_offenen_termin,
		)

		synchronisiere_offenen_termin(row.name)
