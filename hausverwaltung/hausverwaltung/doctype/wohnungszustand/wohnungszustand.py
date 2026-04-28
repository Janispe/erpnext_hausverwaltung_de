import frappe
from frappe.model.document import Document
from frappe.utils import add_days, nowdate


class Wohnungszustand(Document):
	@property
	def vorheriger_zustand(self):
		if not self.wohnung or not self.ab:
			return None
		z = frappe.get_all(
			"Wohnungszustand",
			filters={
				"wohnung": self.wohnung,
				"ab": ("<", self.ab),
				#    "docstatus": 1,
			},
			fields=["name"],
			order_by="ab desc",
			limit=1,
		)
		return z[0].name if z else None

	@property
	def folgender_zustand(self):
		if not self.wohnung or not self.ab:
			return None
		z = frappe.get_all(
			"Wohnungszustand",
			filters={
				"wohnung": self.wohnung,
				"ab": (">", self.ab),
				#   "docstatus": 1,
			},
			fields=["name"],
			order_by="ab asc",
			limit=1,
		)
		return z[0].name if z else None


@frappe.whitelist()
def create_follow_up_state(docname: str, ab_datum) -> str:
	"""Create a draft copy of the given document one day later."""
	source = frappe.get_doc("Wohnungszustand", docname)
	new_doc = frappe.copy_doc(source)

	new_doc.ab = ab_datum
	new_doc.docstatus = 0
	#new_doc.amended_from = source.name

	new_doc.insert()
	frappe.db.commit()
	return new_doc.name
