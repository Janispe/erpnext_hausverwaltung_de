from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

OFFENE_TERMINSTATUS = {"Offen", "Beauftragt"}
GESCHLOSSENE_TERMINSTATUS = {"Abgeschlossen", "Entfallen"}


class Wartungstermin(Document):
	def validate(self) -> None:
		self._apply_plan_defaults()
		self._validate_links()
		self._validate_dates()
		self._validate_unique_open_due()
		self._validate_immutable_schedule()
		self._set_title()

	def on_trash(self) -> None:
		if frappe.db.exists("Anlagenwartung", {"wartungstermin": self.name, "docstatus": ("<", 2)}):
			frappe.throw(
				_("Der Wartungstermin besitzt eine aktive Durchführung und kann nicht gelöscht werden.")
			)

	def _apply_plan_defaults(self) -> None:
		if not self.get("wartungsplan"):
			return
		plan = (
			frappe.db.get_value(
				"Wartungsplan",
				self.wartungsplan,
				["technische_anlage", "massnahmenart", "naechste_faelligkeit"],
				as_dict=True,
			)
			or {}
		)
		if not plan:
			frappe.throw(_("Der Wartungsplan wurde nicht gefunden."))
		if not self.get("technische_anlage"):
			self.technische_anlage = plan.get("technische_anlage")
		if not self.get("massnahmenart"):
			self.massnahmenart = plan.get("massnahmenart")
		if not self.get("soll_termin"):
			self.soll_termin = plan.get("naechste_faelligkeit")

	def _validate_links(self) -> None:
		if not self.get("wartungsplan") or not self.get("technische_anlage"):
			return
		plan_anlage = frappe.db.get_value("Wartungsplan", self.wartungsplan, "technische_anlage")
		if plan_anlage != self.technische_anlage:
			frappe.throw(_("Wartungsplan und technische Anlage passen nicht zusammen."))

	def _validate_dates(self) -> None:
		if self.get("faellig_ab") and self.get("faellig_bis"):
			if getdate(self.faellig_bis) < getdate(self.faellig_ab):
				frappe.throw(_("Das Ende des Fälligkeitsfensters darf nicht vor dessen Beginn liegen."))
		if self.get("soll_termin") and self.get("faellig_ab"):
			if getdate(self.soll_termin) < getdate(self.faellig_ab):
				frappe.throw(_("Der Soll-Termin liegt vor dem Fälligkeitsfenster."))
		if self.get("soll_termin") and self.get("faellig_bis"):
			if getdate(self.soll_termin) > getdate(self.faellig_bis):
				frappe.throw(_("Der Soll-Termin liegt nach dem Fälligkeitsfenster."))
		if self.get("status") in GESCHLOSSENE_TERMINSTATUS and not self.get("abgeschlossen_am"):
			self.abgeschlossen_am = nowdate()
		if self.get("status") in OFFENE_TERMINSTATUS and self.get("ergebnis"):
			frappe.throw(_("Ein offener Wartungstermin darf noch kein Ergebnis besitzen."))
		if self.get("status") == "Abgeschlossen" and not self.get("ergebnis"):
			frappe.throw(_("Ein abgeschlossener Wartungstermin benötigt ein Ergebnis."))

	def _validate_unique_open_due(self) -> None:
		if self.get("status") not in OFFENE_TERMINSTATUS:
			return
		duplikat = frappe.db.exists(
			"Wartungstermin",
			{
				"wartungsplan": self.wartungsplan,
				"soll_termin": self.soll_termin,
				"status": ("in", tuple(OFFENE_TERMINSTATUS)),
				"name": ("!=", self.name or ""),
			},
		)
		if duplikat:
			frappe.throw(_("Für diesen Wartungsplan und Soll-Termin existiert bereits ein offener Termin."))

	def _validate_immutable_schedule(self) -> None:
		if self.is_new():
			return
		if any(
			self.has_value_changed(feld) for feld in ("wartungsplan", "technische_anlage", "soll_termin")
		) and frappe.db.exists("Anlagenwartung", {"wartungstermin": self.name}):
			frappe.throw(
				_("Plan, Anlage und Soll-Termin können nach Anlage einer Durchführung nicht geändert werden.")
			)

	def _set_title(self) -> None:
		teile = [self.get("massnahmenart"), self.get("technische_anlage")]
		if self.get("soll_termin"):
			teile.append(str(getdate(self.soll_termin)))
		self.bezeichnung = " · ".join(str(teil) for teil in teile if teil)


@frappe.whitelist()
def get_or_create_offener_termin(wartungsplan: str, soll_termin=None) -> Document | None:
	"""Return the open occurrence for a due date, creating it when necessary."""
	if not wartungsplan:
		return None
	plan = (
		frappe.db.get_value(
			"Wartungsplan",
			wartungsplan,
			["technische_anlage", "massnahmenart", "naechste_faelligkeit", "status", "gueltig_bis"],
			as_dict=True,
		)
		or {}
	)
	if not plan or plan.get("status") != "Aktiv":
		return None
	faelligkeit = (
		getdate(soll_termin or plan.get("naechste_faelligkeit"))
		if (soll_termin or plan.get("naechste_faelligkeit"))
		else None
	)
	if not faelligkeit:
		return None
	if plan.get("gueltig_bis") and faelligkeit > getdate(plan.get("gueltig_bis")):
		return None

	frappe.db.sql("SELECT name FROM `tabWartungsplan` WHERE name = %s FOR UPDATE", (wartungsplan,))

	name = frappe.db.get_value(
		"Wartungstermin",
		{
			"wartungsplan": wartungsplan,
			"soll_termin": faelligkeit,
			"status": ("in", tuple(OFFENE_TERMINSTATUS)),
		},
		"name",
	)
	if name:
		return frappe.get_doc("Wartungstermin", name)

	return frappe.get_doc(
		{
			"doctype": "Wartungstermin",
			"wartungsplan": wartungsplan,
			"technische_anlage": plan.get("technische_anlage"),
			"massnahmenart": plan.get("massnahmenart"),
			"soll_termin": faelligkeit,
			"status": "Offen",
		}
	).insert()


def synchronisiere_offenen_termin(wartungsplan: str) -> None:
	"""Ensure the plan's cached next due date has one corresponding open occurrence."""
	plan = (
		frappe.db.get_value("Wartungsplan", wartungsplan, ["status", "naechste_faelligkeit"], as_dict=True)
		or {}
	)
	if not plan:
		return
	if plan.get("status") != "Aktiv":
		frappe.db.set_value(
			"Wartungstermin",
			{"wartungsplan": wartungsplan, "status": ("in", tuple(OFFENE_TERMINSTATUS))},
			"status",
			"Entfallen",
			update_modified=False,
		)
		return
	get_or_create_offener_termin(wartungsplan, plan.get("naechste_faelligkeit"))
