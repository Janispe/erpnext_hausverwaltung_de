from __future__ import annotations

import frappe
from frappe.utils import cint, flt


ALLOCATION_DOCTYPE = "Zahlungsplan Zahlung Zuordnung"
ACTIVE = "Aktiv"
REVIEW = "Prüfen"
CANCELLED = "Storniert"


def execute() -> None:
	"""Migrate legacy one-to-one plan-row links into the allocation child table.

	The legacy columns do not prove that a Payment Entry still has an available
	advance. Therefore only the Payment Entry's *current* unallocated amount may
	become an active allocation. Ambiguous rows are retained as review records
	instead of making an accounting assumption.
	"""
	if not frappe.db.table_exists(ALLOCATION_DOCTYPE):
		return

	rows = frappe.db.sql(
		"""
		SELECT
			z.name AS plan_name,
			zz.name AS row_name,
			zz.idx AS row_idx,
			zz.betrag,
			zz.faelligkeitsdatum,
			zz.payment_entry,
			zz.bank_transaction,
			zz.gebucht_am
		FROM `tabZahlungsplan` z
		INNER JOIN `tabZahlungsplan Zeile` zz ON zz.parent = z.name
		WHERE z.modus = 'Abschlagsplan'
		  AND zz.payment_entry IS NOT NULL
		  AND zz.payment_entry != ''
		ORDER BY z.name, zz.idx
		""",
		as_dict=True,
	) or []

	by_plan: dict[str, list[frappe._dict]] = {}
	for row in rows:
		by_plan.setdefault(row.plan_name, []).append(row)

	active_totals = {
		row.payment_entry: _money(row.allocated_amount)
		for row in (
			frappe.db.sql(
				f"""
				SELECT payment_entry, SUM(allocated_amount) AS allocated_amount
				FROM `tab{ALLOCATION_DOCTYPE}`
				WHERE status = %s
				GROUP BY payment_entry
				""",
				(ACTIVE,),
				as_dict=True,
			)
			or []
		)
	}

	for sequence, (plan_name, plan_rows) in enumerate(by_plan.items(), start=1):
		savepoint = f"zp_payment_alloc_{sequence}"
		working_totals = dict(active_totals)
		frappe.db.savepoint(savepoint)
		try:
			_migrate_plan(plan_name, plan_rows, working_totals)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			_log_plan_failure(plan_name, "Aktive Migration fehlgeschlagen")
			# Preserve the legacy links as explicitly inactive audit rows. This
			# second, isolated attempt must never block later plans.
			_write_fail_closed_audit(
				plan_name,
				plan_rows,
				savepoint=f"{savepoint}_audit",
			)
		else:
			# Do not consume an amount in memory until the complete plan has
			# succeeded. A savepoint rollback would otherwise corrupt the
			# remaining amount calculated for later plans.
			active_totals = working_totals


def _migrate_plan(
	plan_name: str,
	plan_rows: list[frappe._dict],
	active_totals: dict[str, float],
) -> None:
	_lock_plan(plan_name)
	plan = frappe.db.get_value(
		"Zahlungsplan",
		plan_name,
		["company", "lieferant"],
		as_dict=True,
	)
	if not plan:
		raise frappe.DoesNotExistError(f"Zahlungsplan {plan_name} wurde nicht gefunden.")

	existing_pairs, next_idx = _existing_pairs_and_next_idx(plan_name)
	for row in plan_rows:
		pair = (row.row_name, row.payment_entry)
		if pair in existing_pairs:
			continue

		amount, status = _allocation_decision(plan, row, active_totals)
		next_idx += 1
		_insert_allocation(
			plan_name,
			row,
			idx=next_idx,
			amount=amount,
			status=status,
		)
		if status != ACTIVE or not _same_amount(amount, row.betrag):
			_clear_legacy_link(row.row_name)
		existing_pairs.add(pair)


def _allocation_decision(
	plan: frappe._dict,
	row: frappe._dict,
	active_totals: dict[str, float],
) -> tuple[float, str]:
	"""Return the auditable amount and status for one legacy link."""
	legacy_amount = _money(row.betrag)
	pe = frappe.db.get_value(
		"Payment Entry",
		row.payment_entry,
		[
			"docstatus",
			"company",
			"party_type",
			"party",
			"payment_type",
			"paid_to",
			"paid_to_account_currency",
			"unallocated_amount",
		],
		as_dict=True,
	)
	if not pe or cint(pe.docstatus) != 1:
		return legacy_amount, CANCELLED

	if (
		not plan.company
		or not plan.lieferant
		or pe.company != plan.company
		or pe.party_type != "Supplier"
		or pe.party != plan.lieferant
		or pe.payment_type != "Pay"
	):
		return legacy_amount, REVIEW

	company_currency = frappe.db.get_value("Company", plan.company, "default_currency")
	party_account = (
		frappe.db.get_value(
			"Account",
			pe.paid_to,
			["company", "account_currency"],
			as_dict=True,
		)
		if pe.paid_to
		else None
	)
	if (
		not company_currency
		or not party_account
		or party_account.company != plan.company
		or not party_account.account_currency
		or party_account.account_currency != company_currency
		or not pe.paid_to_account_currency
		or pe.paid_to_account_currency != company_currency
		or pe.paid_to_account_currency != party_account.account_currency
	):
		# Plan amounts use the company's currency while unallocated_amount uses
		# the party-account currency. Without a 1:1 currency basis, silently
		# copying the number would create a false allocation.
		return legacy_amount, REVIEW

	already_allocated = _money(active_totals.get(row.payment_entry))
	available = max(_money(pe.unallocated_amount) - already_allocated, 0.0)
	if legacy_amount <= 0 or available <= 0:
		return legacy_amount, REVIEW

	active_amount = min(legacy_amount, available)
	active_totals[row.payment_entry] = _money(already_allocated + active_amount)
	return _money(active_amount), ACTIVE


def _lock_plan(plan_name: str) -> None:
	frappe.db.sql(
		"SELECT name FROM `tabZahlungsplan` WHERE name = %s FOR UPDATE",
		(plan_name,),
	)


def _existing_pairs_and_next_idx(plan_name: str) -> tuple[set[tuple[str, str]], int]:
	rows = frappe.db.sql(
		f"""
		SELECT plan_zeile, payment_entry, idx
		FROM `tab{ALLOCATION_DOCTYPE}`
		WHERE parent = %s
		  AND parenttype = 'Zahlungsplan'
		  AND parentfield = 'zahlungen'
		""",
		(plan_name,),
		as_dict=True,
	) or []
	pairs = {
		(row.plan_zeile, row.payment_entry)
		for row in rows
		if row.plan_zeile and row.payment_entry
	}
	return pairs, max((cint(row.idx) for row in rows), default=0)


def _insert_allocation(
	plan_name: str,
	row: frappe._dict,
	*,
	idx: int,
	amount: float,
	status: str,
) -> None:
	# db_insert deliberately avoids validating/saving the legacy parent. A
	# malformed unrelated field on one old plan must not stop this deployment
	# migration or any plan following it.
	allocation = frappe.get_doc({
		"doctype": ALLOCATION_DOCTYPE,
		"parent": plan_name,
		"parenttype": "Zahlungsplan",
		"parentfield": "zahlungen",
		"idx": idx,
		"plan_zeile": row.row_name,
		"plan_zeile_idx": cint(row.row_idx),
		"payment_entry": row.payment_entry,
		"bank_transaction": row.bank_transaction,
		"allocated_amount": amount,
		"posting_date": row.gebucht_am or row.faelligkeitsdatum,
		"status": status,
	})
	allocation.db_insert()


def _clear_legacy_link(row_name: str) -> None:
	frappe.db.set_value(
		"Zahlungsplan Zeile",
		row_name,
		{
			"payment_entry": None,
			"bank_transaction": None,
			"gebucht_am": None,
		},
		update_modified=False,
	)


def _write_fail_closed_audit(
	plan_name: str,
	plan_rows: list[frappe._dict],
	*,
	savepoint: str,
) -> None:
	frappe.db.savepoint(savepoint)
	try:
		_lock_plan(plan_name)
		existing_pairs, next_idx = _existing_pairs_and_next_idx(plan_name)
		for row in plan_rows:
			pair = (row.row_name, row.payment_entry)
			if pair in existing_pairs:
				continue
			next_idx += 1
			_insert_allocation(
				plan_name,
				row,
				idx=next_idx,
				amount=_money(row.betrag),
				status=REVIEW,
			)
			_clear_legacy_link(row.row_name)
			existing_pairs.add(pair)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		_log_plan_failure(plan_name, "Fail-closed-Prüfdatensatz konnte nicht angelegt werden")


def _same_amount(left: float, right: float) -> bool:
	return abs(_money(left) - _money(right)) < 0.005


def _money(value) -> float:
	# Legacy Currency columns are stored at two decimal places. Avoid consulting
	# System Settings while a schema/data patch may still be establishing them.
	return round(flt(value), 2)


def _log_plan_failure(plan_name: str, title: str) -> None:
	try:
		frappe.log_error(
			title=f"Zahlungsplan-Backfill: {title} ({plan_name})",
			message=frappe.get_traceback(),
		)
	except Exception:
		# Error logging itself must not turn a recoverable legacy inconsistency
		# into a deployment blocker.
		pass
