from __future__ import annotations

from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, nowdate


class TechnischeAnlage(Document):
	def validate(self) -> None:
		self._apply_assignment_default()
		self._validate_wohnung()
		self._validate_dates()
		self._validate_baujahr()
		self._validate_replacement_chain()
		self._update_status_date()

	def after_insert(self) -> None:
		if not self.get("inventarnummer"):
			self.inventarnummer = self.name
			self.db_set("inventarnummer", self.name, update_modified=False)
		self.wartungsplaene_aus_vorlagen_anlegen(nur_automatische=1)

	def on_update(self) -> None:
		self._sync_replacement()
		self._pause_plans_when_inactive()

	def on_trash(self) -> None:
		for doctype in ("Wartungsplan", "Anlagenwartung", "Anlagenmangel"):
			if frappe.db.exists(doctype, {"technische_anlage": self.name}):
				frappe.throw(
					_("Die Anlage besitzt verknüpfte {0} und darf nur stillgelegt werden.").format(
						frappe.bold(_(doctype))
					)
				)

	def _apply_assignment_default(self) -> None:
		if self.get("zuordnungstyp"):
			return
		standard = frappe.db.get_value("Anlagenart", self.get("anlagenart"), "standard_zuordnung")
		self.zuordnungstyp = "Wohnung" if standard == "Wohnung" else "Immobilie"

	def _validate_wohnung(self) -> None:
		if self.get("zuordnungstyp") == "Wohnung" and not self.get("wohnung"):
			frappe.throw(_("Für eine wohnungsbezogene Anlage ist eine Wohnung erforderlich."))
		if self.get("zuordnungstyp") != "Wohnung" and self.get("wohnung"):
			frappe.throw(_("Eine Wohnung darf nur beim Zuordnungstyp Wohnung angegeben werden."))
		if not self.get("wohnung"):
			return

		wohnung_immobilie = frappe.db.get_value("Wohnung", self.wohnung, "immobilie")
		if not wohnung_immobilie:
			frappe.throw(_("Die ausgewählte Wohnung besitzt keine Immobilienzuordnung."))
		if wohnung_immobilie != self.get("immobilie"):
			frappe.throw(
				_("Die Wohnung {0} gehört nicht zur Immobilie {1}.").format(self.wohnung, self.immobilie)
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

	def _validate_replacement_chain(self) -> None:
		for feld in ("vorgaengeranlage", "nachfolgeanlage"):
			if self.get(feld) and self.get(feld) == self.name:
				frappe.throw(
					_("Eine technische Anlage kann nicht ihre eigene Vorgänger- oder Nachfolgeanlage sein.")
				)

		aktuell = self.get("vorgaengeranlage")
		gesehen = {self.name}
		while aktuell:
			if aktuell in gesehen:
				frappe.throw(_("Die Vorgängerbeziehung enthält einen Kreis."))
			gesehen.add(aktuell)
			werte = (
				frappe.db.get_value(
					"Technische Anlage", aktuell, ["vorgaengeranlage", "immobilie"], as_dict=True
				)
				or {}
			)
			if werte.get("immobilie") and werte.get("immobilie") != self.get("immobilie"):
				frappe.throw(_("Vorgänger- und Nachfolgeanlage müssen zur selben Immobilie gehören."))
			aktuell = werte.get("vorgaengeranlage")

	def _update_status_date(self) -> None:
		if self.is_new() or self.has_value_changed("status"):
			self.status_seit = nowdate()

	def _sync_replacement(self) -> None:
		if not self.get("vorgaengeranlage"):
			return
		frappe.db.set_value(
			"Technische Anlage",
			self.vorgaengeranlage,
			{
				"nachfolgeanlage": self.name,
				"status": "Ersetzt",
				"status_seit": self.get("inbetriebnahme") or nowdate(),
				"stilllegungsgrund": _("Durch {0} ersetzt").format(self.name),
			},
		)
		self._pause_plans_for(self.vorgaengeranlage)

	def _pause_plans_when_inactive(self) -> None:
		if self.get("status") == "Aktiv":
			return
		self._pause_plans_for(self.name)

	@staticmethod
	def _pause_plans_for(anlage: str) -> None:
		plaene = frappe.get_all(
			"Wartungsplan", filters={"technische_anlage": anlage, "status": "Aktiv"}, pluck="name"
		)
		for plan in plaene:
			frappe.db.set_value(
				"Wartungsplan",
				plan,
				{"status": "Pausiert", "faelligkeitsstatus": "Inaktiv"},
			)
			from hausverwaltung.hausverwaltung.doctype.wartungstermin.wartungstermin import (
				synchronisiere_offenen_termin,
			)

			synchronisiere_offenen_termin(plan)

	@frappe.whitelist()
	def wartungsplaene_aus_vorlagen_anlegen(self, nur_automatische: int | bool = 0) -> dict:
		self.check_permission("write")
		if self.is_new():
			frappe.throw(_("Bitte die technische Anlage zuerst speichern."))

		filterwerte: dict = {"anlagenart": self.anlagenart, "aktiv": 1}
		if cint(nur_automatische):
			filterwerte["wartungsplan_automatisch_anlegen"] = 1
		vorlagen = frappe.get_all(
			"Wartungsmassnahme Vorlage",
			filters=filterwerte,
			fields=[
				"name",
				"bezeichnung",
				"massnahmenart",
				"intervall_anzahl",
				"intervall_einheit",
				"terminberechnung",
				"erstfaelligkeit_anzahl",
				"erstfaelligkeit_einheit",
				"erinnerung_vorlauf_tage",
				"eskalation_nach_tagen",
			],
		)
		erstellt = []
		for vorlage in vorlagen:
			if frappe.db.exists(
				"Wartungsplan",
				{
					"technische_anlage": self.name,
					"massnahmenvorlage": vorlage.name,
					"status": ("in", ("Aktiv", "Pausiert")),
				},
			):
				continue
			from hausverwaltung.hausverwaltung.doctype.wartungsplan.wartungsplan import (
				add_wartungsintervall,
			)

			basis = self.get("inbetriebnahme") or nowdate()
			erst_anzahl = vorlage.erstfaelligkeit_anzahl or vorlage.intervall_anzahl
			erst_einheit = vorlage.erstfaelligkeit_einheit or vorlage.intervall_einheit
			erste_faelligkeit = add_wartungsintervall(basis, erst_anzahl, erst_einheit)
			plan = frappe.get_doc(
				{
					"doctype": "Wartungsplan",
					"bezeichnung": vorlage.bezeichnung,
					"technische_anlage": self.name,
					"massnahmenvorlage": vorlage.name,
					"massnahmenart": vorlage.massnahmenart,
					"status": "Aktiv" if self.get("status") == "Aktiv" else "Pausiert",
					"intervall_anzahl": vorlage.intervall_anzahl,
					"intervall_einheit": vorlage.intervall_einheit,
					"terminberechnung": vorlage.terminberechnung,
					"erste_faelligkeit": erste_faelligkeit,
					"gueltig_von": self.get("inbetriebnahme") or nowdate(),
					"erinnerung_vorlauf_tage": vorlage.erinnerung_vorlauf_tage,
					"eskalation_nach_tagen": vorlage.eskalation_nach_tagen,
					"wartungsfirma": self.get("wartungsfirma"),
				}
			).insert()
			erstellt.append(plan.name)
		return {"erstellt": erstellt}
