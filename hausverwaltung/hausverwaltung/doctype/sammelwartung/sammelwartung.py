from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate


def _sperre_wartungsplaene(wartungsplaene) -> None:
	"""Serialize bulk creation for each plan until the current transaction ends."""
	for wartungsplan in sorted({name for name in wartungsplaene if name}):
		frappe.db.sql(
			"""
			SELECT name
			FROM `tabWartungsplan`
			WHERE name = %s
			FOR UPDATE
			""",
			(wartungsplan,),
		)


def _finde_offene_anlagenwartung(wartungsplan: str):
	"""Find an unfinished maintenance record with a current, locking read."""
	treffer = frappe.db.sql(
		"""
		SELECT name, status, sammelwartung
		FROM `tabAnlagenwartung`
		WHERE wartungsplan = %(wartungsplan)s
			AND (
				docstatus = 0
				OR (docstatus = 1 AND status IN ('Geplant', 'Beauftragt'))
			)
		ORDER BY creation, name
		LIMIT 1
		FOR UPDATE
		""",
		{"wartungsplan": wartungsplan},
		as_dict=True,
	)
	return treffer[0] if treffer else None


def berechne_fortschritt(statuswerte: list[str]) -> dict:
	gesamt = len(statuswerte)
	gewartet = sum(status == "Durchgeführt" for status in statuswerte)
	offen = gesamt - gewartet
	ausgefallen = sum(status in {"Ausgefallen", "Abgebrochen"} for status in statuswerte)
	fortschritt = round((gewartet / gesamt) * 100, 1) if gesamt else 0

	if not gesamt:
		status = "Entwurf"
	elif gewartet == gesamt:
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
		if not self.get("faellig_bis"):
			self.faellig_bis = self.get("termin_bis") or self.get("termin_von")
		if not self.get("bezeichnung"):
			teile = ["Sammelwartung", self.get("immobilie"), self.get("anlagenart")]
			if self.get("termin_von"):
				teile.append(str(getdate(self.termin_von)))
			self.bezeichnung = " · ".join(str(teil) for teil in teile if teil)
		self._set_progress_from_rows()

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

	@frappe.whitelist()
	def positionen_uebernehmen(self, faellig_bis: str | None = None, nur_faellige: int | bool = 1):
		self.check_permission("write")
		if self.is_new():
			frappe.throw(_("Bitte die Sammelwartung zuerst speichern."))
		if not self.get("immobilie"):
			frappe.throw(_("Bitte eine Immobilie auswählen."))

		stichtag = getdate(faellig_bis or self.get("faellig_bis") or self.get("termin_von"))
		bedingungen = [
			"wp.status = 'Aktiv'",
			"ta.status = 'Aktiv'",
			"ta.immobilie = %(immobilie)s",
		]
		parameter = {"immobilie": self.immobilie, "faellig_bis": stichtag}
		if self.get("anlagenart"):
			bedingungen.append("ta.anlagenart = %(anlagenart)s")
			parameter["anlagenart"] = self.anlagenart
		if cint(nur_faellige):
			bedingungen.extend(
				["wp.naechste_faelligkeit IS NOT NULL", "wp.naechste_faelligkeit <= %(faellig_bis)s"]
			)

		plaene = frappe.db.sql(
			f"""
			SELECT
				wp.name AS wartungsplan,
				wp.technische_anlage,
				wp.naechste_faelligkeit AS faellig_am,
				ta.wohnung
			FROM `tabWartungsplan` wp
			INNER JOIN `tabTechnische Anlage` ta ON ta.name = wp.technische_anlage
			WHERE {" AND ".join(bedingungen)}
			ORDER BY ta.wohnung, ta.bezeichnung, wp.naechste_faelligkeit, wp.name
			""",
			parameter,
			as_dict=True,
		)

		vorhanden = {row.wartungsplan for row in self.get("positionen") or [] if row.wartungsplan}
		hinzugefuegt = 0
		for plan in plaene:
			if plan.wartungsplan in vorhanden:
				continue
			self.append(
				"positionen",
				{
					"technische_anlage": plan.technische_anlage,
					"wohnung": plan.wohnung,
					"wartungsplan": plan.wartungsplan,
					"faellig_am": plan.faellig_am,
					"status": "Offen",
				},
			)
			vorhanden.add(plan.wartungsplan)
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
		_sperre_wartungsplaene(position.wartungsplan for position in positionen)

		erstellt = []
		uebersprungen = 0
		for position in positionen:
			if position.anlagenwartung:
				docstatus = frappe.db.get_value("Anlagenwartung", position.anlagenwartung, "docstatus")
				if docstatus is not None and cint(docstatus) < 2:
					uebersprungen += 1
					continue

			vorhandene_wartung = _finde_offene_anlagenwartung(position.wartungsplan)
			if vorhandene_wartung:
				# Repair an unlinked row in this bulk document, but never link
				# another bulk document's work order into this one.
				if vorhandene_wartung.sammelwartung == self.name:
					position.anlagenwartung = vorhandene_wartung.name
					position.status = vorhandene_wartung.status
				uebersprungen += 1
				continue

			plan = frappe.db.get_value(
				"Wartungsplan",
				position.wartungsplan,
				["massnahmenart", "wartungsfirma"],
				as_dict=True,
			) or {}
			wartung = frappe.get_doc(
				{
					"doctype": "Anlagenwartung",
					"sammelwartung": self.name,
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
		fields=["name", "anlagenwartung", "status"],
		order_by="idx asc",
	)
	statuswerte = []
	for position in positionen:
		status = "Offen"
		if position.anlagenwartung:
			wartung = frappe.db.get_value(
				"Anlagenwartung", position.anlagenwartung, ["status", "docstatus"], as_dict=True
			)
			if wartung and cint(wartung.docstatus) < 2:
				status = wartung.status or "Offen"
		if status != position.status:
			frappe.db.set_value(
				"Sammelwartung Position", position.name, "status", status, update_modified=False
			)
		statuswerte.append(status)

	werte = berechne_fortschritt(statuswerte)
	frappe.db.set_value("Sammelwartung", sammelwartung, werte, update_modified=False)
	return werte
