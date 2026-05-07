import frappe
from frappe.model.document import Document


class Vertragspartner(Document):
	@property
	def kontakt(self):
		"""Contact-Doc des Vertragspartners. Liefert das Frappe-Contact-Doc oder
		None — Vorlagen können damit ``{{ vp.kontakt.first_name }}`` schreiben,
		ohne ``mieter`` (Link-String) inline auflösen zu müssen.
		"""
		raw = (self.mieter or "").strip() if isinstance(self.mieter, str) else None
		if not raw:
			return None
		try:
			return frappe.get_cached_doc("Contact", raw)
		except frappe.DoesNotExistError:
			return None
