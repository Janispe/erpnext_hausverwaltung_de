"""Build dunning installments from the invoice's actual ERPNext payment schedule."""

from __future__ import annotations

import math

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


def overdue_payment_rows(invoice, posting_date=None, *, allow_legacy=False) -> list[dict]:
	"""Return only unpaid installments overdue on the requested letter date.

	A Sales Invoice's header due date can be the last installment's due date.
	It cannot identify which earlier installment is already overdue. Never
	invent a schedule or assign the full invoice balance to an arbitrary term.
	"""
	if flt(invoice.outstanding_amount) <= 0:
		return []
	schedules = invoice.get("payment_schedule") or []
	if not schedules:
		if allow_legacy and invoice.due_date and getdate(invoice.due_date) < getdate(posting_date or nowdate()):
			return [{"sales_invoice": invoice.name, "payment_schedule": None,
				"outstanding": flt(invoice.outstanding_amount), "due_date": invoice.due_date}]
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


def require_overdue_payment_rows(invoice, posting_date=None, *, allow_legacy=False) -> list[dict]:
	rows = overdue_payment_rows(invoice, posting_date, allow_legacy=allow_legacy)
	if not rows:
		frappe.throw(_("Rechnung {0} ist zum Mahndatum noch nicht überfällig oder ihre fälligen Raten sind bereits bezahlt.").format(invoice.name))
	return rows


def match_dunning_rows(invoice, payments, posting_date=None, *, allow_legacy=False):
	"""Match old fee-free drafts uniquely while retaining current row safeguards."""
	legacy = allow_legacy and any(not row.get("payment_schedule") for row in payments)
	if legacy:
		schedules = invoice.get("payment_schedule") or []
		invalid_amount = any(
			not math.isfinite(flt(row.outstanding)) or flt(row.outstanding) < 0
			or flt(row.outstanding) > flt(row.payment_amount) + 0.005
			for row in schedules
		)
		insufficient_balance = (
			schedules
			and sum(flt(row.outstanding) for row in schedules) + 0.005 < flt(invoice.outstanding_amount)
		)
		if invalid_amount or insufficient_balance:
			frappe.throw(
				_("Zahlungsplan und offener Rechnungssaldo von {0} passen nicht zusammen.").format(invoice.name)
			)
		if (invoice.get("party_account_currency") or invoice.currency) != invoice.currency:
			frappe.throw(_("Die alten Mahnraten müssen eindeutig in Rechnungswährung vorliegen."))

	current = require_overdue_payment_rows(invoice, posting_date, allow_legacy=allow_legacy)
	seen = set()
	resolved = []
	for payment in payments:
		legacy_row = allow_legacy and not payment.get("payment_schedule")
		candidates = [row for row in current if _matches_dunning_row(payment, row, legacy=legacy_row)]
		if len(candidates) != 1 or candidates[0]["payment_schedule"] in seen:
			frappe.throw(
				_(
					"Rechnung {0} oder ihr Zahlungsplan hat sich seit Anlage des Mahnentwurfs geändert "
					"oder die Rate ist nicht eindeutig. Bitte den Entwurf aktualisieren."
				).format(invoice.name)
			)
		row = candidates[0]
		seen.add(row["payment_schedule"])
		resolved.append((payment, row))
	return resolved


def _matches_dunning_row(payment, current, *, legacy):
	if not payment.get("due_date") or getdate(payment.due_date) != getdate(current["due_date"]):
		return False
	amount = flt(payment.get("outstanding"))
	current_amount = flt(current["outstanding"])
	if not (math.isfinite(amount) and math.isfinite(current_amount)
		and amount > 0 and abs(amount - current_amount) < 0.005):
		return False
	if not legacy and payment.get("payment_schedule") != current["payment_schedule"]:
		return False
	for field in ("payment_term", "mode_of_payment"):
		value = payment.get(field)
		if legacy and not value:
			continue
		if (value or "") != (current.get(field) or ""):
			return False
	for field in ("payment_amount", "invoice_portion"):
		value = payment.get(field)
		if legacy and not value:
			continue
		if not math.isfinite(flt(value)) or abs(flt(value) - flt(current.get(field))) >= 0.005:
			return False
	return True
