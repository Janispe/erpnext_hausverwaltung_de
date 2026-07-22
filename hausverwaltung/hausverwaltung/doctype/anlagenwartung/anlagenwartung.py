from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from hausverwaltung.hausverwaltung.doctype.wartungsplan.wartungsplan import (
	add_wartungsintervall,
	berechne_faelligkeitsstatus,
)

ABSCHLUSS_STATUS = {"Durchgeführt", "Ausgefallen", "Abgebrochen"}


class Anlagenwartung(Document):
	def validate(self) -> None:
		self._apply_plan_defaults_and_validate_link()
		self._validate_sammelwartung_scope()
		self._validate_completion()
		self._set_bezeichnung()

	def on_update(self) -> None:
		self._sync_sammelwartung()

	def before_submit(self) -> None:
		if self.get("status") not in ABSCHLUSS_STATUS:
			frappe.throw(
				_("Nur durchgeführte, ausgefallene oder abgebrochene Maßnahmen können eingereicht werden.")
			)

	def on_submit(self) -> None:
		if self.get("wartungsplan"):
			synchronisiere_wartungsplan(self.wartungsplan, aktuelle_wartung=self)
		self._sync_sammelwartung()

	def on_cancel(self) -> None:
		if self.get("wartungsplan"):
			synchronisiere_wartungsplan(self.wartungsplan, auszuschliessen=self.name)
		self._sync_sammelwartung()

	def _sync_sammelwartung(self) -> None:
		if not self.get("sammelwartung"):
			return
		from hausverwaltung.hausverwaltung.doctype.sammelwartung.sammelwartung import (
			synchronisiere_sammelwartung,
		)

		synchronisiere_sammelwartung(self.sammelwartung)

	def _apply_plan_defaults_and_validate_link(self) -> None:
		if not self.get("wartungsplan"):
			return

		plan = frappe.db.get_value(
			"Wartungsplan",
			self.wartungsplan,
			["technische_anlage", "massnahmenart", "wartungsfirma", "naechste_faelligkeit"],
			as_dict=True,
		) or {}
		if not plan:
			frappe.throw(_("Der ausgewählte Wartungsplan wurde nicht gefunden."))

		plan_anlage = plan.get("technische_anlage")
		if self.get("technische_anlage") and plan_anlage != self.technische_anlage:
			frappe.throw(_("Wartungsplan und technische Anlage passen nicht zusammen."))
		if not self.get("technische_anlage"):
			self.technische_anlage = plan_anlage
		if not self.get("massnahmenart"):
			self.massnahmenart = plan.get("massnahmenart")
		if not self.get("wartungsfirma"):
			self.wartungsfirma = plan.get("wartungsfirma")
		if not self.get("soll_termin"):
			self.soll_termin = plan.get("naechste_faelligkeit")

	def _validate_completion(self) -> None:
		if self.get("status") == "Durchgeführt" and not self.get("durchgefuehrt_am"):
			frappe.throw(_("Für eine durchgeführte Maßnahme ist das Durchführungsdatum erforderlich."))
		if (
			self.get("durchgefuehrt_am")
			and self.get("naechster_termin")
			and getdate(self.naechster_termin) <= getdate(self.durchgefuehrt_am)
		):
			frappe.throw(_("Der nächste Termin muss nach dem Durchführungsdatum liegen."))
		if self.get("ergebnis") in {"Mängel festgestellt", "Nicht bestanden"} and not self.get("maengel"):
			frappe.throw(_("Bitte die festgestellten Mängel dokumentieren."))
		if flt(self.get("kosten")) < 0:
			frappe.throw(_("Die Kosten dürfen nicht negativ sein."))

	def _validate_sammelwartung_scope(self) -> None:
		if not self.get("sammelwartung") or not self.get("technische_anlage"):
			return
		sammel_immobilie = frappe.db.get_value("Sammelwartung", self.sammelwartung, "immobilie")
		anlagen_immobilie = frappe.db.get_value(
			"Technische Anlage", self.technische_anlage, "immobilie"
		)
		if sammel_immobilie and anlagen_immobilie != sammel_immobilie:
			frappe.throw(
				_("Die technische Anlage gehört nicht zum Haus der ausgewählten Sammelwartung.")
			)

	def _set_bezeichnung(self) -> None:
		teile = [self.get("massnahmenart"), self.get("technische_anlage")]
		termin = self.get("durchgefuehrt_am") or self.get("soll_termin")
		if termin:
			teile.append(str(getdate(termin)))
		self.bezeichnung = " · ".join(str(teil) for teil in teile if teil)


def synchronisiere_wartungsplan(
	wartungsplan: str,
	*,
	aktuelle_wartung: Document | None = None,
	auszuschliessen: str | None = None,
) -> None:
	"""Rebuild a plan's latest/next dates from submitted completed maintenance records."""
	plan = frappe.get_doc("Wartungsplan", wartungsplan)
	filters: dict = {
		"wartungsplan": wartungsplan,
		"docstatus": 1,
		"status": "Durchgeführt",
	}
	if auszuschliessen:
		filters["name"] = ("!=", auszuschliessen)

	eintraege = list(
		frappe.get_all(
			"Anlagenwartung",
			filters=filters,
			fields=["name", "durchgefuehrt_am", "soll_termin", "naechster_termin"],
		) or []
	)
	if aktuelle_wartung and aktuelle_wartung.get("status") == "Durchgeführt":
		eintraege = [row for row in eintraege if row.get("name") != aktuelle_wartung.name]
		eintraege.append(
			frappe._dict(
				name=aktuelle_wartung.name,
				durchgefuehrt_am=aktuelle_wartung.get("durchgefuehrt_am"),
				soll_termin=aktuelle_wartung.get("soll_termin"),
				naechster_termin=aktuelle_wartung.get("naechster_termin"),
			)
		)

	eintraege = [row for row in eintraege if row.get("durchgefuehrt_am")]
	letzte = max(eintraege, key=lambda row: (getdate(row.durchgefuehrt_am), row.name)) if eintraege else None

	if letzte:
		letzte_durchfuehrung = getdate(letzte.durchgefuehrt_am)
		if letzte.get("naechster_termin"):
			naechste_faelligkeit = getdate(letzte.naechster_termin)
		else:
			basis = letzte_durchfuehrung
			if plan.get("terminberechnung") == "Ab bisheriger Fälligkeit":
				basis = getdate(letzte.get("soll_termin") or plan.get("erste_faelligkeit"))
			naechste_faelligkeit = add_wartungsintervall(
				basis, plan.intervall_anzahl, plan.intervall_einheit
			)
	else:
		letzte_durchfuehrung = None
		naechste_faelligkeit = getdate(plan.erste_faelligkeit) if plan.get("erste_faelligkeit") else None

	faelligkeitsstatus = berechne_faelligkeitsstatus(
		plan.status,
		naechste_faelligkeit,
		plan.get("erinnerung_vorlauf_tage"),
	)
	frappe.db.set_value(
		"Wartungsplan",
		wartungsplan,
		{
			"letzte_durchfuehrung": letzte_durchfuehrung,
			"naechste_faelligkeit": naechste_faelligkeit,
			"faelligkeitsstatus": faelligkeitsstatus,
		},
	)
