"""Transaction-scoped entry lock for bank imports and the rent invoice run."""

import frappe


def lock_accounting_scope(companies=None, *, wait=True):
	"""Acquire Company rows before any bank, contract or invoice row locks.

	The rent run visits contracts from multiple companies, including contracts
	that it subsequently skips. It therefore acquires all Company rows in one
	stable order before visiting the first contract. Bank actions acquire only
	the companies of their source/counterpart accounts. Locks survive until
	commit/rollback; no advisory lock or process-local mutex is involved.
	"""
	requested = sorted(set(companies)) if companies is not None else None
	if requested == []:
		frappe.throw("Bankkonto hat keine Company; Buchung abgebrochen.")
	where = "WHERE name IN %(companies)s" if requested is not None else ""
	# Frappe delete_doc locks the document before on_trash. Such callers
	# must fail immediately instead of waiting in reverse lock order.
	lock_clause = "FOR UPDATE" if wait else "FOR UPDATE NOWAIT"
	rows = frappe.db.sql(
		f"SELECT name FROM `tabCompany` {where} ORDER BY name {lock_clause}",
		{"companies": tuple(requested)} if requested is not None else {},
	)
	if not rows or (requested is not None and {row[0] for row in rows} != set(requested)):
		frappe.throw("Company für die Buchungssperre wurde nicht gefunden.")
