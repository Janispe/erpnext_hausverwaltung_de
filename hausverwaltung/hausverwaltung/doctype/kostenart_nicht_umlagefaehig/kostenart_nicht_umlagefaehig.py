from frappe.model.document import Document

from hausverwaltung.hausverwaltung.utils.kostenart_konto import (
	KOSTENART_NICHT_UL_DOCTYPE,
	assert_konto_unique,
)


class Kostenartnichtumlagefaehig(Document):
	def validate(self):
		assert_konto_unique(
			konto=self.konto,
			doctype=KOSTENART_NICHT_UL_DOCTYPE,
			name=self.name,
		)
