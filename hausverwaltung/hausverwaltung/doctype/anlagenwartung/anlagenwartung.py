from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from hausverwaltung.hausverwaltung.doctype.wartungsplan.wartungsplan import (
	add_wartungsintervall,
	berechne_faelligkeitsstatus,
)

ABSCHLUSS_STATUS = {"Durchgeführt", "Ausgefallen", "Abgebrochen"}


class Anlagenwartung(Document):
	def validate(self) -> None:
		self._apply_term_defaults_and_validate_link()
		self._apply_plan_defaults_and_validate_link()
		self._validate_sammelwartung_scope()
		self._validate_completion()
		self._validate_unique_execution()
		self._validate_immutable_links()
		self._set_bezeichnung()

	def on_update(self) -> None:
		self._sync_wartungstermin()
		self._sync_sammelwartung()

	def before_submit(self) -> None:
		if self.get("status") not in ABSCHLUSS_STATUS:
			frappe.throw(
				_("Nur durchgeführte, ausgefallene oder abgebrochene Maßnahmen können eingereicht werden.")
			)
		if self.get("status") == "Durchgeführt" and not self.get("ergebnis"):
			frappe.throw(_("Für eine durchgeführte Maßnahme ist ein Ergebnis erforderlich."))
		vorlage = frappe.db.get_value("Wartungsplan", self.wartungsplan, "massnahmenvorlage")
		nachweis_erforderlich = frappe.db.get_value(
			"Wartungsmassnahme Vorlage", vorlage, "nachweis_erforderlich"
		)
		if (
			self.get("status") == "Durchgeführt"
			and nachweis_erforderlich
			and not self.get("wartungsprotokoll")
		):
			frappe.throw(_("Für diese Maßnahme ist ein Wartungs- oder Prüfprotokoll erforderlich."))

	def on_submit(self) -> None:
		self._sync_wartungstermin()
		if self.get("wartungsplan"):
			synchronisiere_wartungsplan(self.wartungsplan, aktuelle_wartung=self)
		self._create_structured_protocol_document()
		self._create_mangel_from_legacy_text()
		self._sync_sammelwartung()

	def on_cancel(self) -> None:
		self._sync_wartungstermin(storniert=True)
		if self.get("wartungsplan"):
			synchronisiere_wartungsplan(self.wartungsplan, auszuschliessen=self.name)
		self._sync_sammelwartung()

	def on_trash(self) -> None:
		if frappe.db.exists("Anlagenmangel", {"anlagenwartung": self.name}):
			frappe.throw(_("Die Durchführung besitzt dokumentierte Mängel und kann nicht gelöscht werden."))

	def _apply_term_defaults_and_validate_link(self) -> None:
		if not self.get("wartungstermin"):
			return
		termin = (
			frappe.db.get_value(
				"Wartungstermin",
				self.wartungstermin,
				["wartungsplan", "technische_anlage", "massnahmenart", "soll_termin", "sammelwartung"],
				as_dict=True,
			)
			or {}
		)
		if not termin:
			frappe.throw(_("Der Wartungstermin wurde nicht gefunden."))
		for feld in ("wartungsplan", "technische_anlage"):
			if self.get(feld) and self.get(feld) != termin.get(feld):
				frappe.throw(_("Wartungstermin und Durchführung passen nicht zusammen."))
			self.set(feld, termin.get(feld))
		if not self.get("massnahmenart"):
			self.massnahmenart = termin.get("massnahmenart")
		if not self.get("soll_termin"):
			self.soll_termin = termin.get("soll_termin")
		if not self.get("sammelwartung"):
			self.sammelwartung = termin.get("sammelwartung")

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

		plan = (
			frappe.db.get_value(
				"Wartungsplan",
				self.wartungsplan,
				["technische_anlage", "massnahmenart", "wartungsfirma", "naechste_faelligkeit"],
				as_dict=True,
			)
			or {}
		)
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

	def _validate_unique_execution(self) -> None:
		if not self.get("wartungstermin"):
			return
		frappe.db.sql(
			"SELECT name FROM `tabWartungstermin` WHERE name = %s FOR UPDATE",
			(self.wartungstermin,),
		)
		duplikat = frappe.db.exists(
			"Anlagenwartung",
			{
				"wartungstermin": self.wartungstermin,
				"docstatus": ("<", 2),
				"name": ("!=", self.name or ""),
			},
		)
		if duplikat:
			frappe.throw(_("Für diesen Wartungstermin existiert bereits eine aktive Durchführung."))

	def _validate_immutable_links(self) -> None:
		if self.is_new() or not self.has_value_changed("wartungstermin"):
			return
		frappe.throw(_("Der Wartungstermin einer gespeicherten Durchführung kann nicht geändert werden."))

	def _validate_sammelwartung_scope(self) -> None:
		if not self.get("sammelwartung") or not self.get("technische_anlage"):
			return
		sammel_immobilie = frappe.db.get_value("Sammelwartung", self.sammelwartung, "immobilie")
		anlagen_immobilie = frappe.db.get_value("Technische Anlage", self.technische_anlage, "immobilie")
		if sammel_immobilie and anlagen_immobilie != sammel_immobilie:
			frappe.throw(_("Die technische Anlage gehört nicht zum Haus der ausgewählten Sammelwartung."))

	def _set_bezeichnung(self) -> None:
		teile = [self.get("massnahmenart"), self.get("technische_anlage")]
		termin = self.get("durchgefuehrt_am") or self.get("soll_termin")
		if termin:
			teile.append(str(getdate(termin)))
		self.bezeichnung = " · ".join(str(teil) for teil in teile if teil)

	def _sync_wartungstermin(self, *, storniert: bool = False) -> None:
		if not self.get("wartungstermin"):
			return
		if storniert:
			werte = {
				"status": "Offen",
				"ergebnis": None,
				"anlagenwartung": None,
				"abgeschlossen_am": None,
			}
		elif self.get("status") == "Beauftragt":
			werte = {"status": "Beauftragt", "anlagenwartung": self.name}
		elif self.get("status") == "Durchgeführt":
			ergebnis_map = {
				"Ohne Mängel": "Bestanden",
				"Mängel festgestellt": "Mit Mängeln",
				"Nicht bestanden": "Nicht bestanden",
				"Nicht durchgeführt": "Nicht durchgeführt",
			}
			werte = {
				"status": "Abgeschlossen",
				"ergebnis": ergebnis_map.get(self.get("ergebnis")),
				"anlagenwartung": self.name,
				"abgeschlossen_am": self.get("durchgefuehrt_am") or nowdate(),
			}
		elif self.get("status") in {"Ausgefallen", "Abgebrochen"}:
			werte = {
				"status": "Entfallen",
				"ergebnis": "Nicht durchgeführt",
				"anlagenwartung": self.name,
				"abgeschlossen_am": nowdate(),
			}
		else:
			werte = {"status": "Offen", "anlagenwartung": self.name}
		frappe.db.set_value("Wartungstermin", self.wartungstermin, werte, update_modified=False)

	def _create_mangel_from_legacy_text(self) -> None:
		if self.get("ergebnis") not in {"Mängel festgestellt", "Nicht bestanden"}:
			return
		if frappe.db.exists("Anlagenmangel", {"anlagenwartung": self.name}):
			return
		frappe.get_doc(
			{
				"doctype": "Anlagenmangel",
				"technische_anlage": self.technische_anlage,
				"wartungstermin": self.wartungstermin,
				"anlagenwartung": self.name,
				"festgestellt_am": self.get("durchgefuehrt_am") or nowdate(),
				"schweregrad": "Erheblich" if self.get("ergebnis") == "Nicht bestanden" else "Gering",
				"status": "Offen",
				"beschreibung": self.get("maengel"),
			}
		).insert()

	def _create_structured_protocol_document(self) -> None:
		if not self.get("wartungsprotokoll") or frappe.db.exists(
			"Anlagendokument",
			{
				"bezugsdoctype": "Anlagenwartung",
				"bezug": self.name,
				"datei": self.wartungsprotokoll,
			},
		):
			return
		dokumentart = (
			frappe.db.get_value(
				"Wartungsmassnahmenart", self.get("massnahmenart"), "standard_dokumentart"
			)
			or "Wartungsprotokoll"
		)
		frappe.get_doc(
			{
				"doctype": "Anlagendokument",
				"bezeichnung": _("{0} zu {1}").format(dokumentart, self.name),
				"dokumentart": dokumentart,
				"datei": self.wartungsprotokoll,
				"bezugsdoctype": "Anlagenwartung",
				"bezug": self.name,
				"ausgestellt_am": self.get("durchgefuehrt_am"),
			}
		).insert()


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
		)
		or []
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
			naechste_faelligkeit = add_wartungsintervall(basis, plan.intervall_anzahl, plan.intervall_einheit)
	else:
		letzte_durchfuehrung = None
		naechste_faelligkeit = getdate(plan.erste_faelligkeit) if plan.get("erste_faelligkeit") else None

	plan_status = plan.status
	if (
		plan.get("gueltig_bis")
		and naechste_faelligkeit
		and getdate(naechste_faelligkeit) > getdate(plan.gueltig_bis)
	):
		plan_status = "Beendet"

	faelligkeitsstatus = berechne_faelligkeitsstatus(
		plan_status,
		naechste_faelligkeit,
		plan.get("erinnerung_vorlauf_tage"),
	)
	frappe.db.set_value(
		"Wartungsplan",
		wartungsplan,
		{
			"status": plan_status,
			"letzte_durchfuehrung": letzte_durchfuehrung,
			"naechste_faelligkeit": naechste_faelligkeit,
			"faelligkeitsstatus": faelligkeitsstatus,
		},
	)
	from hausverwaltung.hausverwaltung.doctype.wartungstermin.wartungstermin import (
		synchronisiere_offenen_termin,
	)

	synchronisiere_offenen_termin(wartungsplan)
