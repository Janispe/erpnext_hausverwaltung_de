from __future__ import annotations

import frappe


def _child_value(row, fieldname: str):
	return row.get(fieldname) if hasattr(row, "get") else getattr(row, fieldname, None)


def remove_bank_transaction_payment_links(payment_document_type: str, payment_document: str) -> list[str]:
	"""Remove reconciliation rows for a voucher from Bank Transactions.

	Uses ERPNext's ``BankTransaction.remove_payment_entry`` so related allocation
	and clearance side effects stay consistent.
	"""
	if not payment_document_type or not payment_document:
		return []

	bt_names = frappe.get_all(
		"Bank Transaction Payments",
		filters={
			"payment_document": payment_document_type,
			"payment_entry": payment_document,
		},
		fields=["parent"],
		distinct=True,
	)
	updated: list[str] = []
	for r in bt_names:
		parent = r.get("parent")
		if not parent:
			continue
		try:
			bt = frappe.get_doc("Bank Transaction", parent)
			targets = [
				pe
				for pe in bt.get("payment_entries") or []
				if _child_value(pe, "payment_document") == payment_document_type
				and _child_value(pe, "payment_entry") == payment_document
			]
			if not targets:
				continue
			for pe in targets:
				bt.remove_payment_entry(pe)
			bt.save(ignore_permissions=True)
			updated.append(parent)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Bank Transaction {parent} delink fehlgeschlagen ({payment_document_type} {payment_document})",
			)
	return updated
