from __future__ import annotations

import frappe


def execute():
	"""Bereinigt operative Links auf stornierte oder gelöschte Zahlungsbelege."""
	from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
		sync_cancelled_journal_entry_links,
		sync_cancelled_payment_entry_links as sync_bankimport_payment_entries,
	)
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import (
		sync_cancelled_payment_entry_links as sync_zahlungsplan_payment_entries,
		sync_cancelled_purchase_invoice_links,
	)

	try:
		sync_bankimport_payment_entries()
		sync_cancelled_journal_entry_links()
		sync_zahlungsplan_payment_entries()
		sync_cancelled_purchase_invoice_links()
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"Patch cleanup_cancelled_storno_references fehlgeschlagen",
		)
		raise
