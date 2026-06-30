import json

import frappe
from frappe.model.document import Document


class BankimportPartyRegel(Document):
	def validate(self):
		if self.get("parameters_json"):
			try:
				json.loads(self.parameters_json)
			except Exception:
				frappe.throw("Parameter JSON ist ungueltig.")

