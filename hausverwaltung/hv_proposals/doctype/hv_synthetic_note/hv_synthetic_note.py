import frappe
from frappe.model.document import Document
from hausverwaltung.proposals.frappe_service import enabled


class HVSyntheticNote(Document):
	def validate(self):
		enabled()
		if not isinstance(self.synthetic_id, str) or not self.synthetic_id.startswith("SYN-"):
			frappe.throw("Synthetic identifier required")
		if not isinstance(self.label, str) or not 1 <= len(self.label) <= 120 or self.label != self.label.strip():
			frappe.throw("Label must contain 1..120 characters without outer whitespace")
		before = self.get_doc_before_save()
		self.generation = int(before.generation) + 1 if before else 0
