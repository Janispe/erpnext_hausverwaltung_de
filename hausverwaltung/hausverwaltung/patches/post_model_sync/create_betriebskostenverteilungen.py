import frappe
from frappe.utils import nowdate


def execute():
	"""Erstellt für alle Wohnungen eine Betriebskostenverteilung, sofern noch
	keine existiert."""
	wohnungen = frappe.get_all("Wohnung", pluck="name")
	for whg in wohnungen:
		if not frappe.db.exists("Betriebskostenverteilung", {"wohnung": whg}):
			doc = frappe.get_doc(
				{
					"doctype": "Betriebskostenverteilung",
					"wohnung": whg,
					"gilt_ab": nowdate(),
				}
			)
			doc.insert(ignore_permissions=True)
