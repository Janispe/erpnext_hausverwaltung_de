from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class Wartungsvertrag(Document):
	def validate(self) -> None:
		if self.get("gueltig_von") and self.get("gueltig_bis"):
			if getdate(self.gueltig_bis) < getdate(self.gueltig_von):
				frappe.throw(_("Das Vertragsende darf nicht vor dem Vertragsbeginn liegen."))
		if flt(self.get("jahrespauschale")) < 0:
			frappe.throw(_("Die Jahrespauschale darf nicht negativ sein."))
		if cint(self.get("kuendigungsfrist_monate")) < 0:
			frappe.throw(_("Die Kündigungsfrist darf nicht negativ sein."))

		gesehen = set()
		frappe.db.sql(
			"SELECT name FROM `tabWartungsplan` WHERE name IN %(wartungsplaene)s ORDER BY name FOR UPDATE",
			{
				"wartungsplaene": tuple(sorted({p.wartungsplan for p in self.get("positionen") or []}))
				or ("",)
			},
		)
		for position in self.get("positionen") or []:
			if position.wartungsplan in gesehen:
				frappe.throw(_("Jeder Wartungsplan darf nur einmal im Vertrag enthalten sein."))
			gesehen.add(position.wartungsplan)
			plan_anlage = frappe.db.get_value("Wartungsplan", position.wartungsplan, "technische_anlage")
			if position.technische_anlage and position.technische_anlage != plan_anlage:
				frappe.throw(
					_("Wartungsplan und technische Anlage der Vertragsposition passen nicht zusammen.")
				)
			position.technische_anlage = plan_anlage
			if flt(position.get("jahresanteil")) < 0:
				frappe.throw(_("Der Jahresanteil einer Vertragsposition darf nicht negativ sein."))
			andere_aktive_vertraege = frappe.db.sql(
				"""
				SELECT wv.name
				FROM `tabWartungsvertrag Position` wvp
				INNER JOIN `tabWartungsvertrag` wv ON wv.name = wvp.parent
				WHERE wvp.parenttype = 'Wartungsvertrag'
					AND wvp.wartungsplan = %(wartungsplan)s
					AND wv.status = 'Aktiv'
					AND wv.name != %(name)s
				LIMIT 1
				""",
				{"wartungsplan": position.wartungsplan, "name": self.name or ""},
			)
			if self.get("status") == "Aktiv" and andere_aktive_vertraege:
				frappe.throw(_("Der Wartungsplan ist bereits einem anderen Wartungsvertrag zugeordnet."))

	def on_trash(self) -> None:
		if frappe.db.exists("Sammelwartung", {"wartungsvertrag": self.name}):
			frappe.throw(_("Der Wartungsvertrag wird bereits in Wartungsaufträgen verwendet."))
