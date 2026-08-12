from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class Anlagenkategorie(Document):
	def validate(self) -> None:
		self.bezeichnung = (self.get("bezeichnung") or "").strip()
		if cint(self.get("sortierung")) < 0:
			frappe.throw(_("Die Sortierung darf nicht negativ sein."))
