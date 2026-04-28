from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class ZaehlerZuordnung(Document):
	def validate(self):
		self._validate_dates()
		self._validate_no_overlap_for_zaehler()

	def _validate_dates(self):
		if self.von and self.bis and getdate(self.bis) < getdate(self.von):
			frappe.throw(_("Bis darf nicht vor Von liegen."))

	def _validate_no_overlap_for_zaehler(self):
		if not self.zaehler or not self.von:
			return

		start = getdate(self.von)
		end = getdate(self.bis) if self.bis else None

		existing = frappe.get_all(
			"Zaehler Zuordnung",
			filters={
				"zaehler": self.zaehler,
				"name": ("!=", self.name),
				"docstatus": ("<", 2),
			},
			fields=["name", "von", "bis"],
		)

		for row in existing or []:
			row_start = getdate(row.get("von")) if row.get("von") else None
			if not row_start:
				continue
			row_end = getdate(row.get("bis")) if row.get("bis") else None

			if _ranges_overlap_exclusive_end(start, end, row_start, row_end):
				frappe.throw(
					_(
						"Z\u00e4hler {0} ist im Zeitraum bereits zugeordnet ({1})."
					).format(self.zaehler, row.get("name"))
				)


def _ranges_overlap_exclusive_end(
	start_a, end_a, start_b, end_b
) -> bool:
	"""Return whether [start_a, end_a) and [start_b, end_b) overlap.

	end_* can be None (= open ended).
	"""
	# Overlap if: start_a < end_b (or end_b open) AND start_b < end_a (or end_a open)
	if end_b is not None and not (start_a < end_b):
		return False
	if end_a is not None and not (start_b < end_a):
		return False
	return True


@frappe.whitelist()
def assign_zaehler_to_wohnung(wohnung: str, zaehler: str, notiz: str | None = None) -> str:
	"""Create a new `Zaehler Zuordnung` for a Wohnung and close any current assignment.

	- sets `von` = today
	- closes overlapping existing assignment(s) by setting `bis` = today
	"""
	if not wohnung:
		frappe.throw(_("Parameter 'wohnung' fehlt."))
	if not zaehler:
		frappe.throw(_("Parameter 'zaehler' fehlt."))

	frappe.get_doc("Wohnung", wohnung).check_permission("read")
	frappe.get_doc("Zaehler", zaehler).check_permission("read")

	von = nowdate()

	# Close any assignment that overlaps the new open-ended range starting today,
	# but only if it started before today (avoid silently rewriting future assignments).
	frappe.db.sql(
		"""
		UPDATE `tabZaehler Zuordnung`
		SET bis = %(von)s
		WHERE
			zaehler = %(zaehler)s
			AND docstatus < 2
			AND von < %(von)s
			AND (bis IS NULL OR bis > %(von)s)
		""",
		{"von": von, "zaehler": zaehler},
	)

	doc = frappe.get_doc(
		{
			"doctype": "Zaehler Zuordnung",
			"zaehler": zaehler,
			"bezugsobjekt_typ": "Wohnung",
			"bezugsobjekt": wohnung,
			"von": von,
			"notiz": (notiz or "").strip() or None,
		}
	)
	doc.insert()
	return doc.name


@frappe.whitelist()
def get_aktive_zaehler_fuer_wohnung(wohnung: str):
	"""Return active meter assignments for a Wohnung as of today.

	Includes Zuordnung + Zaehler master data for rendering in the Wohnung UI.
	"""
	if not wohnung:
		return []
	frappe.get_doc("Wohnung", wohnung).check_permission("read")

	heute = nowdate()
	rows = frappe.db.sql(
		"""
		SELECT
			zz.name AS zuordnung,
			zz.von AS von,
			zz.bis AS bis,
			zz.notiz AS notiz,
			z.name AS zaehler,
			z.zaehlerart AS zaehlerart,
			z.zaehlernummer AS zaehlernummer,
			z.status AS status,
			z.standort_beschreibung AS standort_beschreibung
		FROM `tabZaehler Zuordnung` zz
		INNER JOIN `tabZaehler` z ON z.name = zz.zaehler
		WHERE
			zz.docstatus < 2
			AND zz.bezugsobjekt_typ = 'Wohnung'
			AND zz.bezugsobjekt = %(wohnung)s
			AND zz.von <= %(heute)s
			AND (zz.bis IS NULL OR zz.bis >= %(heute)s)
		ORDER BY zz.von DESC, zz.modified DESC
		""",
		{"wohnung": wohnung, "heute": heute},
		as_dict=True,
	)
	return rows or []
