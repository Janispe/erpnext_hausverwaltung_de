"""Current invoice reads and duplicate protection shared by the dunning APIs."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from hausverwaltung.hausverwaltung.utils.dunning_payment_schedule import match_dunning_rows, require_overdue_payment_rows


def validate_dunning_invoice(invoice, posting_date=None) -> None:
	if int(invoice.docstatus) != 1 or invoice.get("is_return") or flt(invoice.outstanding_amount) <= 0:
		frappe.throw(_("{0} ist nicht offen oder nicht gebucht.").format(invoice.name))
	if invoice.get("payment_schedule"):
		require_overdue_payment_rows(invoice, posting_date)
	elif not invoice.due_date or getdate(invoice.due_date) >= getdate(posting_date or nowdate()):
		frappe.throw(_("Rechnung {0} ist zum Mahndatum noch nicht überfällig.").format(invoice.name))
	# Legacy invoices without a schedule can still be inspected/locked. The
	# row builder rejects them before creating a draft or submitting a letter.


def lock_dunning_invoices(invoice_names, posting_date=None):
	"""Keep source invoice locks until commit, including PDF/email finalization."""
	invoices = []
	for name in sorted(set(invoice_names)):
		invoice = frappe.get_doc("Sales Invoice", name, for_update=True)
		invoice.check_permission("read")
		validate_dunning_invoice(invoice, posting_date)
		invoices.append(invoice)
	return invoices


def reject_duplicate_dunning(invoice_names, posting_date=None, *, exclude_dunning="") -> None:
	"""Call under the source invoice locks; cancelled letters permit a correction.

	An invoice must not be included in two active letters on the same letter
	date, even with a different stage or a partially overlapping invoice set.
	The locking read also sees a competing request that committed while we waited.
	"""
	if not invoice_names:
		return
	existing = frappe.db.sql(
		"""
		SELECT d.name
		FROM `tabDunning` d
		INNER JOIN `tabOverdue Payment` payment
			ON payment.parent = d.name AND payment.parenttype = 'Dunning'
		WHERE d.docstatus < 2
			AND d.posting_date = %(posting_date)s
			AND d.name != %(exclude_dunning)s
			AND payment.sales_invoice IN %(invoices)s
		ORDER BY d.name
		LIMIT 1
		FOR UPDATE
		""",
		{
			"posting_date": getdate(posting_date or nowdate()),
			"exclude_dunning": exclude_dunning or "",
			"invoices": tuple(sorted(set(invoice_names))),
		},
		as_dict=True,
	)
	if existing:
		frappe.throw(
			_(
				"Für mindestens eine ausgewählte Rechnung existiert zum Mahndatum bereits "
				"Mahnung {0}. Bitte den vorhandenen Entwurf bearbeiten/löschen oder "
				"die gebuchte Mahnung vor einer Korrektur stornieren."
			).format(existing[0].name)
		)


def validate_dunning_before_submit(doc, method=None) -> None:
	"""Recheck drafts at submit, including letters edited in the standard form."""
	payments = doc.get("overdue_payments") or []
	names = [row.sales_invoice for row in payments if row.sales_invoice]
	if not names or len(names) != len(payments):
		frappe.throw(_("Die Mahnung enthält keine verknüpfte Sales Invoice."))
	invoices = lock_dunning_invoices(names, doc.posting_date)
	if any(
		invoice.customer != doc.customer or invoice.company != doc.company
		or invoice.currency != doc.currency for invoice in invoices
	):
		frappe.throw(_("Mahnung und Rechnungen müssen zu derselben Firma und demselben Mieter gehören."))
	free = not any(flt(doc.get(field)) for field in ("dunning_amount", "dunning_fee", "rate_of_interest"))
	resolved = []
	for invoice in invoices:
		rows = [row for row in payments if row.sales_invoice == invoice.name]
		resolved.extend(match_dunning_rows(invoice, rows, doc.posting_date, allow_legacy=free))
	reject_duplicate_dunning(names, doc.posting_date, exclude_dunning=doc.name)
	# Mutate only after all source rows and the duplicate check have passed.
	references_changed = False
	for payment, current in resolved:
		if not payment.get("payment_schedule") and current["payment_schedule"]:
			for field in ("payment_schedule", "payment_amount", "invoice_portion", "payment_term", "mode_of_payment"):
				payment[field] = current.get(field)
			references_changed = True
	if references_changed:
		# Older ERPNext versions compute levels before this before_submit hook.
		doc.set_dunning_level()
