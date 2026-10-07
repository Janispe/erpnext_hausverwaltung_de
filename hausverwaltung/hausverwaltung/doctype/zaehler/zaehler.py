from frappe.model.document import Document

from hausverwaltung.hausverwaltung.utils.document_naming import make_document_name


class Zaehler(Document):
	def autoname(self):
		self.name = make_document_name("Zaehler")
