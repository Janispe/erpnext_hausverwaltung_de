from frappe.contacts.doctype.address.address import Address as FrappeAddress
from frappe.utils import cstr


class Address(FrappeAddress):
	"""Address-Subclass mit composite Properties für Serienbrief-Pfade.

	``plz_ort`` und ``adresse`` werden im Resolver via ``getattr`` gefunden
	und liefern vor-formatierte Strings, ohne dass die Vorlage Jinja-
	Concat-Logik schreiben muss. Beispiel-Pfad:
	``{{ objekt.wohnung.immobilie.address.adresse }}``.
	"""

	@property
	def plz_ort(self) -> str:
		parts = [cstr(self.pincode).strip(), cstr(self.city).strip()]
		return " ".join(p for p in parts if p)

	@property
	def adresse(self) -> str:
		line = cstr(self.address_line1).strip()
		plz_ort = self.plz_ort
		return ", ".join(p for p in (line, plz_ort) if p)
