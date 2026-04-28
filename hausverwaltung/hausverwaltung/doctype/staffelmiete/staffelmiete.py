# import frappe
from frappe.model.document import Document
import frappe
from frappe.utils import getdate


class Staffelmiete(Document):
	def validate(self):
		# Auf Dokumentebene erfolgt nur eine Minimalprüfung.
		# Die Prüfung, ob "Gesamter Zeitraum" innerhalb eines Monats liegt,
		# erfolgt im Mietvertrag (dort sind Geschwisterzeilen und Vertragsende bekannt).
		art = (self.art or "Monatlich").strip()
		if not self.von:
			frappe.throw("'Von' muss gesetzt sein.")
