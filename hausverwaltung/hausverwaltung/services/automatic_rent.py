from __future__ import annotations

import frappe
from frappe.utils import cint, getdate, nowdate

from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import generate_mietrechnungen


def _enabled() -> bool:
	return bool(
		cint(frappe.db.get_single_value("Hausverwaltung Einstellungen", "automatische_mietsollstellung"))
	)


def schedule_monthly_rent() -> None:
	"""Queue the current month's rent on the first, using the site's local date.

	Each company gets its own transaction: a failed company must not roll back
	other companies' invoices. Frappe also executes overdue monthly jobs after
	a scheduler outage; deliberately keep the month fixed when queuing workers.
	"""
	if not _enabled():
		return

	today = getdate(nowdate())
	for company in frappe.get_all("Company", filters={"is_group": 0}, pluck="name", order_by="name asc"):
		frappe.enqueue(
			"hausverwaltung.hausverwaltung.services.automatic_rent.generate_company_rent",
			queue="long",
			enqueue_after_commit=True,
			company=company,
			monat=today.month,
			jahr=today.year,
		)


def generate_company_rent(company: str, monat: int, jahr: int) -> dict | None:
	# Respect disabling the setting even if a job is already waiting in the queue.
	if not _enabled():
		return None

	# Reuse the manual run's contract/customer identity checks, row locks and
	# duplicate guard, including drafts. Errors propagate to Frappe for rollback.
	return generate_mietrechnungen(
		company=company,
		monat=monat,
		jahr=jahr,
		include_drafts_in_guard=1,
	)
