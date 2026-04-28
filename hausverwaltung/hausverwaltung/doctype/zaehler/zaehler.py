import frappe
from frappe.model.document import Document


class Zaehler(Document):
	def autoname(self):
		zaehlerart = (self.zaehlerart or "").strip()
		zaehlernummer = (self.zaehlernummer or "").strip()

		base_name = " ".join(part for part in (zaehlerart, zaehlernummer) if part).strip()
		if not base_name:
			return

		candidate = base_name
		suffix = 1
		while frappe.db.exists("Zaehler", candidate):
			suffix += 1
			candidate = f"{base_name}-{suffix}"

		self.name = candidate
