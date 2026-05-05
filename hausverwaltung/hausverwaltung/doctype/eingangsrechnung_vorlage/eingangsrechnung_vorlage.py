from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class EingangsrechnungVorlage(Document):
	def validate(self):
		if not self.get("positionen"):
			frappe.throw(_("Mindestens eine Position ist erforderlich."))

		for idx, row in enumerate(self.positionen, start=1):
			typ = (row.get("typ") or "").strip()
			bk = row.get("betriebskostenart")
			nul = row.get("kostenart_nicht_ul")

			if typ == "umlegbar":
				if not bk:
					frappe.throw(
						_("Position {0}: Betriebskostenart ist Pflicht für 'umlegbar'.").format(idx)
					)
				if nul:
					frappe.throw(
						_(
							"Position {0}: 'Kostenart (nicht umlegbar)' darf nicht gesetzt sein, wenn Typ = umlegbar."
						).format(idx)
					)
			elif typ == "nicht umlegbar":
				if not nul:
					frappe.throw(
						_(
							"Position {0}: Kostenart (nicht umlegbar) ist Pflicht für 'nicht umlegbar'."
						).format(idx)
					)
				if bk:
					frappe.throw(
						_(
							"Position {0}: 'Betriebskostenart' darf nicht gesetzt sein, wenn Typ = nicht umlegbar."
						).format(idx)
					)
			else:
				frappe.throw(_("Position {0}: Typ muss gesetzt sein.").format(idx))
