"""Keep locking period checks restricted to one property and period."""

import frappe


def execute():
	frappe.db.add_index(
		"Heizkostenabrechnung Immobilie",
		["immobilie", "von", "bis", "docstatus"],
		index_name="hk_property_period_status",
	)
