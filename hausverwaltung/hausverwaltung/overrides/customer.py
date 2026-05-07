import frappe
from erpnext.selling.doctype.customer.customer import Customer as ERPNextCustomer
from frappe.contacts.doctype.address.address import get_default_address


class Customer(ERPNextCustomer):
	"""Erweitert Customer um eine ``briefanschrift``-Property mit Wohnung-
	Fallback. In der Hausverwaltung haben Mieter (= Customer) typischerweise
	keine eigene Default-Address — die Postanschrift ist die Wohnungs-/
	Immobilien-Adresse, in der sie wohnen.

	Pfad in Vorlagen: ``{{ objekt.kunde.briefanschrift.adresse }}``.

	Im Gegensatz zu ``objekt.kunde.address`` (= strict Customer-Default-Address,
	wirft im Strict-Mode wenn nicht gepflegt) liefert ``briefanschrift`` eine
	konstruierte Adresse mit Fallback-Logik.
	"""

	@property
	def briefanschrift(self):
		# 1. Eigene Default-Adresse am Customer
		addr_name = get_default_address("Customer", self.name)
		if addr_name:
			return frappe.get_cached_doc("Address", addr_name)

		# 2. Mietvertrag → Wohnung → Immobilien-Adresse.
		# Erst aktive Verträge (zum heutigen Datum), als Fallback der zuletzt
		# bewohnte (für ausgezogene Mieter, bei denen Briefe an ihre letzte
		# bekannte Wohn-Adresse gehen sollen).
		try:
			rows = frappe.db.sql(
				"""
				SELECT
					wohnung,
					CASE
						WHEN (von IS NULL OR von <= CURDATE())
						 AND (bis IS NULL OR bis >= CURDATE())
						THEN 0
						ELSE 1
					END AS is_inactive
				FROM `tabMietvertrag`
				WHERE kunde = %(kunde)s
				ORDER BY is_inactive ASC, COALESCE(von, '1900-01-01') DESC
				LIMIT 1
				""",
				{"kunde": self.name},
				as_dict=True,
			)
		except Exception:
			rows = []

		wohnung = rows[0].get("wohnung") if rows else None
		if not wohnung:
			return None

		immobilie = frappe.db.get_value("Wohnung", wohnung, "immobilie")
		if not immobilie:
			return None

		addr_name = get_default_address("Immobilie", immobilie)
		if not addr_name:
			return None

		return frappe.get_cached_doc("Address", addr_name)
