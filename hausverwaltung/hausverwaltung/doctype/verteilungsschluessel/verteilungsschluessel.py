import frappe
from frappe.model.document import Document


class Verteilungsschluessel(Document):
	@property
	def verteilt_ueber(self) -> str | None:


		"""Verteilungsschlüssel der zugrunde liegenden Kostenart."""
		if not self.betriebskostenart:
			return None
		return frappe.get_cached_value(
			"Betriebskostenart",
			self.betriebskostenart,
			"verteilungsschluessel",
		)

	def _context(self) -> tuple[str, str, list[str]]:
		"""Stichtag, Wohnung und alle Wohnungen des Hauses."""
		parent = frappe.get_doc("Betriebskostenverteilung", self.parent)
		stichtag = str(parent.gilt_ab)
		wohnung = parent.wohnung

		immobilie = frappe.db.get_value("Wohnung", wohnung, "immobilie")
		haus = frappe.db.get_value("Wohnung", wohnung, "haus")
		filters = {"immobilie": immobilie} if immobilie else {"haus": haus}
		wohnungen = frappe.get_all("Wohnung", filters=filters, pluck="name")

		return stichtag, wohnung, wohnungen

	@property
	def gesamt_haus(self) -> float | None:
		print("Berechne Gesamtsumme der Verteilungsgröße im Haus")
		frappe.msgprint("Berechne Gesamtsumme der Verteilungsgröße im Haus")

		"""Gesamtsumme der Verteilungsgröße im Haus."""
		try:
			stichtag, _, wohnungen = self._context()
		except Exception:
			frappe.msgprint("Fehler beim Ermitteln des Stichtags oder der Wohnungen.")
			return None

		key = self.verteilt_ueber
		if key == "Fläche":
			from hausverwaltung.scripts.betriebskosten import betriebskoste_service_meins as svc

			total = sum(svc._flaeche_wohnung_am(w, stichtag) or 0 for w in wohnungen)
		elif key == "Personen":
			total = frappe.db.sql(
				"""
				SELECT COALESCE(SUM(mvp.personen), 0)
				FROM `tabMietvertrag` mv
				LEFT JOIN `tabMietvertragPersonen` mvp
				  ON mvp.parent = mv.name
				 AND mvp.parenttype = 'Mietvertrag'
				 AND mvp.parentfield = 'personen'
				 AND mvp.von = (
				   SELECT MAX(mvp2.von)
				   FROM `tabMietvertragPersonen` mvp2
				   WHERE mvp2.parent = mv.name
					 AND mvp2.parenttype = 'Mietvertrag'
					 AND mvp2.parentfield = 'personen'
					 AND mvp2.von <= %(stag)s
				 )
				WHERE mv.wohnung IN %(whg)s
				  AND mv.von <= %(stag)s
				  AND (mv.bis IS NULL OR mv.bis >= %(stag)s)
				""",
				{"whg": tuple(wohnungen), "stag": stichtag},
			)[0][0]
		elif key == "Faktor":
			verteil_ids = frappe.get_all(
				"Betriebskostenverteilung",
				filters={"wohnung": ("in", wohnungen), "gilt_ab": ("<=", stichtag)},
				pluck="name",
			)
			total = 0
			if verteil_ids:
				rows = frappe.get_all(
					"Verteilungsschluessel",
					filters={
						"parent": ("in", verteil_ids),
						"betriebskostenart": self.betriebskostenart,
						"verteilt_ueber": "Faktor",
					},
					pluck="ueberschreiben",
				)
			total = sum(float(v or 1) for v in rows)
			if not total:
				total = 1
		else:
			total = 1

		return float(total)

	@property
	def anteil_dieser_wohnung(self) -> float | None:
		"""Berechneter Anteil dieser Wohnung."""
		total = self.gesamt_haus
		if not total:
			return None

		try:
			stichtag, wohnung, _ = self._context()
		except Exception:
			return None

		key = self.verteilt_ueber
		if self.ueberschreiben_pruefen:
			wert = self.ueberschreiben or 0
		elif key == "Fläche":
			from hausverwaltung.scripts.betriebskosten import betriebskoste_service_meins as svc

			wert = svc._flaeche_wohnung_am(wohnung, stichtag)
		elif key == "Personen":
			wert = frappe.db.sql(
				"""
				SELECT COALESCE(SUM(mvp.personen), 0)
				FROM `tabMietvertrag` mv
				LEFT JOIN `tabMietvertragPersonen` mvp
				  ON mvp.parent = mv.name
				 AND mvp.parenttype = 'Mietvertrag'
				 AND mvp.parentfield = 'personen'
				 AND mvp.von = (
				   SELECT MAX(mvp2.von)
				   FROM `tabMietvertragPersonen` mvp2
				   WHERE mvp2.parent = mv.name
					 AND mvp2.parenttype = 'Mietvertrag'
					 AND mvp2.parentfield = 'personen'
					 AND mvp2.von <= %(stag)s
				 )
				WHERE mv.wohnung = %(whg)s
				  AND mv.von <= %(stag)s
				  AND (mv.bis IS NULL OR mv.bis >= %(stag)s)
				""",
				{"whg": wohnung, "stag": stichtag},
			)[0][0]
		elif key == "Faktor":
			wert = self.ueberschreiben or 1
		else:
			wert = 1

		return round(float(wert) / float(total), 4)
