from __future__ import annotations

import frappe
from frappe.permissions import reset_perms

TARGET_DOCTYPES = (
	"Wohnung",
	"Mieterwechsel",
	"Prozess Version",
	"Prozess Aufgabe",
	"Prozess Aufgabe Datei",
	"Prozess Aufgabe Druck",
)


def execute() -> None:
	for dt in TARGET_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		reset_perms(dt)

	for dt in TARGET_DOCTYPES:
		if frappe.db.exists("DocType", dt):
			frappe.clear_cache(doctype=dt)
