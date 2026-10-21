"""Current invoice reads and duplicate protection shared by the dunning APIs."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def validate_dunning_invoice(invoice, posting_date=None) -> None:
	if int(invoice.docstatus) != 1 or flt(invoice.outstanding_amount) <= 0:
		frappe.throw(_("{0} ist nicht offen oder nicht gebucht.").format(invoice.name))
	if not invoice.due_date or getdate(invoice.due_date) >= getdate(posting_date or nowdate()):
		frappe.throw(
			_("Rechnung {0} ist zum Mahndatum noch nicht überfällig.").format(invoice.name)
		)


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
	names = [row.sales_invoice for row in doc.get("overdue_payments") or [] if row.sales_invoice]
	if not names:
		frappe.throw(_("Die Mahnung enthält keine verknüpfte Sales Invoice."))
	invoices = lock_dunning_invoices(names, doc.posting_date)
	if any(invoice.customer != doc.customer or invoice.company != doc.company for invoice in invoices):
		frappe.throw(_("Mahnung und Rechnungen müssen zu derselben Firma und demselben Mieter gehören."))
	for invoice in invoices:
		rows = [row for row in doc.get("overdue_payments") or [] if row.sales_invoice == invoice.name]
		stored_outstanding = sum(flt(row.get("outstanding")) for row in rows)
		if abs(stored_outstanding - flt(invoice.outstanding_amount)) >= 0.005 or any(
			not row.get("due_date") or getdate(row.due_date) != getdate(invoice.due_date) for row in rows
		):
			frappe.throw(
				_("Rechnung {0} hat sich seit Anlage des Mahnentwurfs geändert. Bitte den Entwurf aktualisieren.")
				.format(invoice.name)
			)
	reject_duplicate_dunning(names, doc.posting_date, exclude_dunning=doc.name)
