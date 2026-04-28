import frappe


def execute():
	"""Legt die Accounting Dimension 'Wohnung' an (fieldname=wohnung) und erzeugt Custom Fields.

	Benötigt ERPNext (DocType 'Accounting Dimension').
	"""
	# ERPNext ggf. nicht installiert / Doctype fehlt
	if not frappe.db.exists("DocType", "Accounting Dimension"):
		return

	# Unsere Referenz muss existieren
	if not frappe.db.exists("DocType", "Wohnung"):
		frappe.throw("DocType 'Wohnung' existiert nicht – Accounting Dimension kann nicht angelegt werden.")

	# Dimension existiert bereits?
	existing = frappe.db.get_value("Accounting Dimension", {"document_type": "Wohnung"}, "name")
	if existing:
		dim = frappe.get_doc("Accounting Dimension", existing)
	else:
		dim = frappe.get_doc(
			{
				"doctype": "Accounting Dimension",
				"document_type": "Wohnung",
				"label": "Wohnung",
				"fieldname": "wohnung",
				"disabled": 0,
			}
		)
		dim.insert(ignore_permissions=True)

	# Sicherstellen, dass die Custom Fields direkt angelegt werden (nicht nur per enqueue)
	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			make_dimension_in_accounting_doctypes,
		)

		make_dimension_in_accounting_doctypes(doc=dim)
	except Exception:
		# Fallback: ERPNext legt die Felder ggf. asynchron über after_insert an
		pass
