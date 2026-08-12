from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


def _sperre_wartungstermine(wartungstermine) -> None:
	"""Serialize bulk creation for each due occurrence until the transaction ends."""
	for wartungstermin in sorted({name for name in wartungstermine if name}):
		frappe.db.sql(
			"""
			SELECT name
			FROM `tabWartungstermin`
			WHERE name = %s
			FOR UPDATE
			""",
			(wartungstermin,),
		)


def _finde_offene_anlagenwartung(wartungstermin: str):
	"""Find an unfinished maintenance record with a current, locking read."""
	treffer = frappe.db.sql(
		"""
		SELECT name, status, sammelwartung
		FROM `tabAnlagenwartung`
		WHERE wartungstermin = %(wartungstermin)s
			AND (
				docstatus = 0
				OR (docstatus = 1 AND status IN ('Geplant', 'Beauftragt'))
			)
		ORDER BY creation, name
		LIMIT 1
		FOR UPDATE
		""",
		{"wartungstermin": wartungstermin},
		as_dict=True,
	)
	return treffer[0] if treffer else None


def berechne_fortschritt(statuswerte: list[str]) -> dict:
	gesamt = len(statuswerte)
	gewartet = sum(status == "Durchgeführt" for status in statuswerte)
	abgeschlossen = sum(status in {"Durchgeführt", "Ausgefallen", "Abgebrochen"} for status in statuswerte)
	offen = gesamt - abgeschlossen
	ausgefallen = sum(status in {"Ausgefallen", "Abgebrochen"} for status in statuswerte)
	fortschritt = round((abgeschlossen / gesamt) * 100, 1) if gesamt else 0

	if not gesamt:
		status = "Entwurf"
	elif abgeschlossen == gesamt:
		status = "Abgeschlossen"
	elif any(wert not in {"Offen", "Geplant"} for wert in statuswerte) or gewartet:
		status = "In Arbeit"
	else:
		status = "Geplant"

	return {
		"anzahl_gesamt": gesamt,
		"anzahl_gewartet": gewartet,
		"anzahl_offen": offen,
		"anzahl_ausgefallen": ausgefallen,
		"fortschritt": fortschritt,
		"status": status,
	}


class Sammelwartung(Document):
	def validate(self) -> None:
		self._validate_dates()
		self._apply_contract_defaults()
		self._validate_positions()
		self._collect_and_validate_removed_positions()
		if not self.get("faellig_bis"):
			self.faellig_bis = self.get("termin_bis") or self.get("termin_von")
		if not self.get("bezeichnung"):
			teile = ["Sammelwartung", self.get("immobilie"), self.get("anlagenart")]
			if self.get("termin_von"):
				teile.append(str(getdate(self.termin_von)))
			self.bezeichnung = " · ".join(str(teil) for teil in teile if teil)
		self._set_progress_from_rows()

	def on_update(self) -> None:
		for wartungstermin in getattr(self, "_removed_wartungstermine", set()):
			frappe.db.set_value(
				"Wartungstermin",
				{"name": wartungstermin, "sammelwartung": self.name, "status": "Offen"},
				"sammelwartung",
				None,
				update_modified=False,
			)
		for position in self.get("positionen") or []:
			frappe.db.set_value(
				"Wartungstermin",
				position.wartungstermin,
				"sammelwartung",
				self.name,
				update_modified=False,
			)

	def on_trash(self) -> None:
		if frappe.db.exists("Anlagenwartung", {"sammelwartung": self.name, "docstatus": ("<", 2)}):
			frappe.throw(
				_("Der Wartungsauftrag besitzt aktive Durchführungen und kann nicht gelöscht werden.")
			)
		frappe.db.set_value(
			"Wartungstermin",
			{"sammelwartung": self.name, "status": "Offen"},
			"sammelwartung",
			None,
			update_modified=False,
		)

	def _apply_contract_defaults(self) -> None:
		if not self.get("wartungsvertrag"):
			return
		vertrag = (
			frappe.db.get_value(
				"Wartungsvertrag", self.wartungsvertrag, ["wartungsfirma", "status"], as_dict=True
			)
			or {}
		)
		if vertrag.get("status") != "Aktiv":
			frappe.throw(_("Für einen Wartungsauftrag muss der Wartungsvertrag aktiv sein."))
		if self.get("wartungsfirma") and self.wartungsfirma != vertrag.get("wartungsfirma"):
			frappe.throw(_("Wartungsvertrag und Wartungsfirma passen nicht zusammen."))
		self.wartungsfirma = vertrag.get("wartungsfirma")

	def _validate_positions(self) -> None:
		gesehen = set()
		for position in self.get("positionen") or []:
			if position.wartungstermin in gesehen:
				frappe.throw(_("Jeder Wartungstermin darf nur einmal im Wartungsauftrag enthalten sein."))
			gesehen.add(position.wartungstermin)
			werte = (
				frappe.db.get_value(
					"Wartungstermin",
					position.wartungstermin,
					["wartungsplan", "technische_anlage", "soll_termin"],
					as_dict=True,
				)
				or {}
			)
			if not werte:
				frappe.throw(_("Ein Wartungstermin der Position wurde nicht gefunden."))
			if position.wartungsplan != werte.get("wartungsplan") or position.technische_anlage != werte.get(
				"technische_anlage"
			):
				frappe.throw(
					_("Wartungstermin, Wartungsplan und Anlage einer Position passen nicht zusammen.")
				)
			position.faellig_am = werte.get("soll_termin")
			anlage_immobilie = frappe.db.get_value(
				"Technische Anlage", position.technische_anlage, "immobilie"
			)
			if anlage_immobilie != self.get("immobilie"):
				frappe.throw(_("Alle Positionen müssen zur Immobilie des Wartungsauftrags gehören."))
			if self.get("wartungsvertrag") and not frappe.db.exists(
				"Wartungsvertrag Position",
				{
					"parent": self.wartungsvertrag,
					"parenttype": "Wartungsvertrag",
					"wartungsplan": position.wartungsplan,
				},
			):
				frappe.throw(
					_("Der Wartungsplan ist nicht durch den ausgewählten Wartungsvertrag abgedeckt.")
				)

	def _collect_and_validate_removed_positions(self) -> None:
		self._removed_wartungstermine = set()
		alt = self.get_doc_before_save()
		if not alt:
			return
		neu = {row.wartungstermin for row in self.get("positionen") or []}
		for position in alt.get("positionen") or []:
			if position.wartungstermin in neu:
				continue
			if position.anlagenwartung and frappe.db.exists(
				"Anlagenwartung", {"name": position.anlagenwartung, "docstatus": ("<", 2)}
			):
				frappe.throw(_("Eine Position mit aktiver Durchführung kann nicht entfernt werden."))
			self._removed_wartungstermine.add(position.wartungstermin)

	def _validate_dates(self) -> None:
		if (
			self.get("termin_von")
			and self.get("termin_bis")
			and getdate(self.termin_bis) < getdate(self.termin_von)
		):
			frappe.throw(_("Das Terminende darf nicht vor dem Terminbeginn liegen."))

	def _set_progress_from_rows(self) -> None:
		werte = berechne_fortschritt([row.status or "Offen" for row in self.get("positionen") or []])
		for feld, wert in werte.items():
			self.set(feld, wert)
		self.gesamtbetrag = sum(flt(row.get("kostenanteil")) for row in self.get("positionen") or [])

	@frappe.whitelist()
	def positionen_uebernehmen(self, faellig_bis: str | None = None, nur_faellige: int | bool = 1):
		self.check_permission("write")
		if self.is_new():
			frappe.throw(_("Bitte die Sammelwartung zuerst speichern."))
		if not self.get("immobilie"):
			frappe.throw(_("Bitte eine Immobilie auswählen."))

		stichtag = getdate(faellig_bis or self.get("faellig_bis") or self.get("termin_von"))
		bedingungen = [
			"wt.status = 'Offen'",
			"wp.status = 'Aktiv'",
			"ta.status = 'Aktiv'",
			"ta.immobilie = %(immobilie)s",
			"(wt.sammelwartung IS NULL OR wt.sammelwartung = '' OR wt.sammelwartung = %(sammelwartung)s)",
		]
		parameter = {
			"immobilie": self.immobilie,
			"faellig_bis": stichtag,
			"sammelwartung": self.name,
		}
		if self.get("anlagenart"):
			bedingungen.append("ta.anlagenart = %(anlagenart)s")
			parameter["anlagenart"] = self.anlagenart
		if self.get("wartungsvertrag"):
			bedingungen.append(
				"EXISTS (SELECT 1 FROM `tabWartungsvertrag Position` wvp "
				"WHERE wvp.parent = %(wartungsvertrag)s AND wvp.parenttype = 'Wartungsvertrag' "
				"AND wvp.wartungsplan = wp.name)"
			)
			parameter["wartungsvertrag"] = self.wartungsvertrag
		if cint(nur_faellige):
			bedingungen.extend(["wt.soll_termin IS NOT NULL", "wt.soll_termin <= %(faellig_bis)s"])

		plaene = frappe.db.sql(
			f"""
			SELECT
				wt.name AS wartungstermin,
				wp.name AS wartungsplan,
				wp.technische_anlage,
				wt.soll_termin AS faellig_am,
				ta.wohnung
			FROM `tabWartungstermin` wt
			INNER JOIN `tabWartungsplan` wp ON wp.name = wt.wartungsplan
			INNER JOIN `tabTechnische Anlage` ta ON ta.name = wp.technische_anlage
			WHERE {" AND ".join(bedingungen)}
			ORDER BY ta.wohnung, ta.bezeichnung, wt.soll_termin, wt.name
			""",
			parameter,
			as_dict=True,
		)

		vorhanden = {row.wartungstermin for row in self.get("positionen") or [] if row.wartungstermin}
		hinzugefuegt = 0
		for plan in plaene:
			if plan.wartungstermin in vorhanden:
				continue
			self.append(
				"positionen",
				{
					"technische_anlage": plan.technische_anlage,
					"wohnung": plan.wohnung,
					"wartungsplan": plan.wartungsplan,
					"wartungstermin": plan.wartungstermin,
					"faellig_am": plan.faellig_am,
					"status": "Offen",
				},
			)
			frappe.db.set_value(
				"Wartungstermin", plan.wartungstermin, "sammelwartung", self.name, update_modified=False
			)
			vorhanden.add(plan.wartungstermin)
			hinzugefuegt += 1

		self.faellig_bis = stichtag
		self.save()
		return {"hinzugefuegt": hinzugefuegt, "gesamt": len(self.positionen)}

	@frappe.whitelist()
	def anlagenwartungen_anlegen(self):
		self.check_permission("write")
		if self.is_new():
			frappe.throw(_("Bitte die Sammelwartung zuerst speichern."))

		positionen = list(self.get("positionen") or [])
		# The locks are acquired in a stable order to avoid two overlapping
		# bulk documents deadlocking each other. They also make the persisted
		# duplicate check below safe against concurrent bulk creation.
		_sperre_wartungstermine(position.wartungstermin for position in positionen)

		erstellt = []
		uebersprungen = 0
		for position in positionen:
			if position.anlagenwartung:
				docstatus = frappe.db.get_value("Anlagenwartung", position.anlagenwartung, "docstatus")
				if docstatus is not None and cint(docstatus) < 2:
					uebersprungen += 1
					continue

			vorhandene_wartung = _finde_offene_anlagenwartung(position.wartungstermin)
			if vorhandene_wartung:
				# Repair an unlinked row in this bulk document, but never link
				# another bulk document's work order into this one.
				if vorhandene_wartung.sammelwartung == self.name:
					position.anlagenwartung = vorhandene_wartung.name
					position.status = vorhandene_wartung.status
				uebersprungen += 1
				continue

			plan = (
				frappe.db.get_value(
					"Wartungsplan",
					position.wartungsplan,
					["massnahmenart", "wartungsfirma"],
					as_dict=True,
				)
				or {}
			)
			wartung = frappe.get_doc(
				{
					"doctype": "Anlagenwartung",
					"sammelwartung": self.name,
					"wartungstermin": position.wartungstermin,
					"wartungsplan": position.wartungsplan,
					"technische_anlage": position.technische_anlage,
					"massnahmenart": plan.get("massnahmenart"),
					"status": "Geplant",
					"soll_termin": position.faellig_am or self.termin_von,
					"wartungsfirma": self.get("wartungsfirma") or plan.get("wartungsfirma"),
				}
			).insert()
			position.anlagenwartung = wartung.name
			position.status = wartung.status
			erstellt.append(wartung.name)

		self.save()
		return {"erstellt": erstellt, "uebersprungen": uebersprungen}

	@frappe.whitelist()
	def fortschritt_aktualisieren(self):
		self.check_permission("read")
		return synchronisiere_sammelwartung(self.name)


def synchronisiere_sammelwartung(sammelwartung: str) -> dict:
	positionen = frappe.get_all(
		"Sammelwartung Position",
		filters={"parent": sammelwartung, "parenttype": "Sammelwartung"},
		fields=["name", "anlagenwartung", "status", "kostenanteil"],
		order_by="idx asc",
	)
	statuswerte = []
	gesamtbetrag = 0.0
	for position in positionen:
		status = "Offen"
		kostenanteil = flt(position.kostenanteil) if position.get("kostenanteil") not in (None, "") else None
		if position.anlagenwartung:
			wartung = frappe.db.get_value(
				"Anlagenwartung", position.anlagenwartung, ["status", "docstatus", "kosten"], as_dict=True
			)
			if wartung and cint(wartung.docstatus) < 2:
				status = wartung.status or "Offen"
				if kostenanteil is None:
					kostenanteil = flt(wartung.get("kosten"))
		gesamtbetrag += kostenanteil or 0
		if status != position.status:
			frappe.db.set_value(
				"Sammelwartung Position", position.name, "status", status, update_modified=False
			)
		statuswerte.append(status)

	werte = berechne_fortschritt(statuswerte)
	werte["gesamtbetrag"] = gesamtbetrag
	frappe.db.set_value("Sammelwartung", sammelwartung, werte, update_modified=False)
	return werte
