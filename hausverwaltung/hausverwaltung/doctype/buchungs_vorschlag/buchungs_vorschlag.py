import frappe
from frappe.model.document import Document


class BuchungsVorschlag(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		if not previous:
			return
		if self.receipt_upload != previous.receipt_upload or (
			self.receipt_upload and any(
				self.get(field) != previous.get(field)
				for field in ("receipt_analysis", "extracted_data", "status", "receipt_context")
			)
		):
			frappe.throw("Bon-Analysen können nur über die Buchungs-Inbox geändert werden.")
		if self.receipt_digest != previous.receipt_digest:
			frappe.throw("Die Prüfsumme eines Bon-Originals ist unveränderlich.")
		if self.receipt_digest and (
			self.file_url != previous.file_url
			or self.linked_purchase_invoice != previous.linked_purchase_invoice
			or (self.status != previous.status and (
				{self.status, previous.status} & {"Booked", "Cancelled"} or previous.linked_purchase_invoice
			))
		):
			frappe.throw("Das Original und die Buchungsverknüpfung eines Bons sind unveränderlich.")

	def on_trash(self):
		if self.receipt_upload:
			frappe.throw("Bons mit Analysehistorie können nicht gelöscht werden.")
		if self.receipt_digest:
			from hausverwaltung.proposals import receipt_action

			if receipt_action._final(self) or receipt_action._proposal(self, lock=True)[0]:
				frappe.throw("Ein Bon mit Freigabehistorie kann nicht gelöscht werden.")
