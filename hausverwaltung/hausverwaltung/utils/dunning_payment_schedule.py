"""Build dunning installments from the invoice's actual ERPNext payment schedule."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def _payment_schedule_outstanding(invoice, schedules):
	from erpnext.accounts.doctype.dunning import dunning as erpnext_dunning

	helper = getattr(erpnext_dunning, "get_payment_schedule_outstanding", None)
	if helper is not None:
		return helper(invoice, schedules)

	# ERPNext 16.50 predates this helper. Match the 16.53 rule: payments with
	# no term allocation consume the oldest installments first. Outstanding on
	# a foreign-currency party account cannot be compared to invoice currency.
	outstanding = {row.name: flt(row.outstanding) for row in schedules}
	if invoice.party_account_currency != invoice.currency:
		return outstanding
	unallocated = max(sum(outstanding.values()) - flt(invoice.outstanding_amount), 0)
	for row in sorted(schedules, key=lambda row: (getdate(row.due_date), row.idx)):
		paid = min(outstanding[row.name], unallocated)
		unallocated -= paid
		outstanding[row.name] -= paid
	return outstanding


def overdue_payment_rows(invoice, posting_date=None) -> list[dict]:
	"""Return only unpaid installments overdue on the requested letter date.

	A Sales Invoice's header due date can be the last installment's due date.
	It cannot identify which earlier installment is already overdue. Never
	invent a schedule or assign the full invoice balance to an arbitrary term.
	"""
	if flt(invoice.outstanding_amount) <= 0:
		return []
	schedules = invoice.get("payment_schedule") or []
	if not schedules:
		frappe.throw(
			_("Rechnung {0} hat keinen Zahlungsplan. Bitte den Zahlungsplan der Rechnung prüfen; es wurde keine Mahnung erstellt.")
			.format(invoice.name)
		)
	seen = set()
	for schedule in schedules:
		if (
			not schedule.name or schedule.name in seen or not schedule.due_date
			or schedule.parent != invoice.name
			or schedule.parenttype != "Sales Invoice"
			or schedule.parentfield != "payment_schedule"
		):
			frappe.throw(_("Der Zahlungsplan der Rechnung {0} ist nicht eindeutig oder unvollständig.").format(invoice.name))
		seen.add(schedule.name)

	outstanding = _payment_schedule_outstanding(invoice, schedules)
	letter_date = getdate(posting_date or nowdate())
	rows = []
	for schedule in sorted(schedules, key=lambda row: (getdate(row.due_date), row.idx)):
		amount = flt(outstanding[schedule.name])
		if amount <= 0 or getdate(schedule.due_date) >= letter_date:
			continue
		rows.append({
			"sales_invoice": invoice.name,
			"payment_schedule": schedule.name,
			"outstanding": amount,
			**{
				field: schedule.get(field)
				for field in (
					"payment_term", "mode_of_payment", "payment_amount", "invoice_portion",
					"due_date", "description", "paid_amount", "discounted_amount",
				)
			},
		})
	return rows


def require_overdue_payment_rows(invoice, posting_date=None) -> list[dict]:
	rows = overdue_payment_rows(invoice, posting_date)
	if not rows:
		frappe.throw(_("Rechnung {0} ist zum Mahndatum noch nicht überfällig oder ihre fälligen Raten sind bereits bezahlt.").format(invoice.name))
	return rows
