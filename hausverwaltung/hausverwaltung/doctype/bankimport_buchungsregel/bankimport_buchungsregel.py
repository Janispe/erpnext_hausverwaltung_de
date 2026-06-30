import json

import frappe
from frappe.model.document import Document


class BankimportBuchungsregel(Document):
	def validate(self):
		if self.get("parameters_json"):
			try:
				json.loads(self.parameters_json)
			except Exception:
				frappe.throw("Parameter JSON ist ungueltig.")

