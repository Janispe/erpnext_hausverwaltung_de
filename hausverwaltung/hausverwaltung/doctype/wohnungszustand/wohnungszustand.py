import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class Wohnungszustand(Document):
	def validate(self):
		self.validate_merkmalpunkte()

	def validate_merkmalpunkte(self):
		value = self.get("merkmalpunkte")
		if value is None:
			return
		value = int(value or 0)
		if value < -5 or value > 5:
			frappe.throw(_("Merkmalpunkte müssen zwischen -5 und 5 liegen."))

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
	source_ab = getdate(source.ab) if source.ab else None
	target_ab = getdate(ab_datum) if ab_datum else None

	if not source.wohnung:
		frappe.throw(_("Der Ausgangszustand ist keiner Wohnung zugeordnet."))
	if not source_ab:
		frappe.throw(_("Der Ausgangszustand hat kein gültiges Ab-Datum."))
	if not target_ab:
		frappe.throw(_("Bitte ein gültiges Ab-Datum für den Folgezustand angeben."))
	if target_ab <= source_ab:
		frappe.throw(_("Das Ab-Datum des Folgezustands muss nach dem Ausgangszustand liegen."))

	duplicate = frappe.get_all(
		"Wohnungszustand",
		filters={
			"wohnung": source.wohnung,
			"ab": target_ab,
			"name": ("!=", source.name),
		},
		pluck="name",
		limit=1,
	)
	if duplicate:
		frappe.throw(_("Für diese Wohnung existiert bereits ein Wohnungszustand mit diesem Ab-Datum."))

	following = frappe.get_all(
		"Wohnungszustand",
		filters={
			"wohnung": source.wohnung,
			"ab": (">", source_ab),
			"name": ("!=", source.name),
		},
		fields=["name", "ab"],
		order_by="ab asc",
		limit=1,
	)
	if following and getdate(following[0].get("ab")) <= target_ab:
		frappe.throw(_("Zwischen Ausgangszustand und neuem Folgezustand existiert bereits ein weiterer Zustand."))

	new_doc = frappe.copy_doc(source)

	new_doc.ab = target_ab
	new_doc.docstatus = 0
	#new_doc.amended_from = source.name

	new_doc.insert()
	return new_doc.name
