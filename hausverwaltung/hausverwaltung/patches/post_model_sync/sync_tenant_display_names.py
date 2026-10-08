"""Show tenant names and uniform titles instead of legacy ID strings.

Imported Customers often carry their old document ID ("Müller - W | VH | EG")
as ``customer_name``. Saving the contract already replaces it with the
Hauptmieter name; this applies the same rule to all contracts at once and then
rebuilds the dependent display titles. No document is renamed, saved or
submitted, and historical invoices keep the name they were issued with.
"""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.utils.document_title_sync import refresh_all_titles
from hausverwaltung.hausverwaltung.utils.mieter_name import get_hauptmieter_display_name


def execute() -> None:
	for name in frappe.get_all("Mietvertrag", filters={"kunde": ["is", "set"]}, pluck="name", limit_page_length=0):
		contract = frappe.get_doc("Mietvertrag", name)
		display_name = get_hauptmieter_display_name(contract.get("mieter"))
		if not display_name or not frappe.db.exists("Customer", contract.kunde):
			continue
		if frappe.db.get_value("Customer", contract.kunde, "customer_name") != display_name:
			frappe.db.set_value(
				"Customer", contract.kunde, "customer_name", display_name, update_modified=False
			)
	refresh_all_titles()
