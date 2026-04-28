from frappe.model.document import Document

from hausverwaltung.hausverwaltung.utils.kostenart_konto import (
	BK_DOCTYPE,
	assert_konto_unique,
)


class Betriebskostenart(Document):
	def validate(self):
		assert_konto_unique(konto=self.konto, doctype=BK_DOCTYPE, name=self.name)
