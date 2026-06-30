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
		if self.get("rule_code"):
			try:
				compile(self.rule_code, f"<{self.doctype} {self.name or self.rule_key}>", "exec")
			except Exception as exc:
				frappe.throw(f"Regel-Code ist ungueltig: {exc}")
