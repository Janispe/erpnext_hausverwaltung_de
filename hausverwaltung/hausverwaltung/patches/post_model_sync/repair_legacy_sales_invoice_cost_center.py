"""Prepare a narrow, manual repair of missing Sales Invoice header cost centers.

This module is deliberately absent from patches.txt. The default is a read-only
report; inspect its planned/skipped rows before applying an explicit selection:

    bench --site <site> execute \
      hausverwaltung.hausverwaltung.patches.post_model_sync.repair_legacy_sales_invoice_cost_center.execute \
      --kwargs '{"invoice_names": ["ACC-SINV-..."], "dry_run": True}'

For the reviewed selection, pass ``dry_run=False``. The caller owns the
transaction: this module never commits. Only the blank Sales Invoice header
``cost_center`` is changed, without modifying timestamps, items, GL Entries,
amounts or accounts. This repairs missing header metadata; it is not a ledger
dimension migration. Existing values and ambiguous identities are reported
without being overwritten.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, cstr

from hausverwaltung.hausverwaltung.overrides.sales_invoice import _contract_reference
from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import _company_via_wohnung
from hausverwaltung.hausverwaltung.utils.booking_locks import lock_accounting_scope
from hausverwaltung.hausverwaltung.utils.customer_booking_identity import lock_customer_booking_identity


class _SkipCandidate(Exception):
	pass


def _dry_run_value(value) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, (str, int)) and str(value).strip().lower() in {"true", "false", "1", "0"}:
		return str(value).strip().lower() in {"true", "1"}
	raise ValueError("dry_run must explicitly be true or false")


def _invoice_names(value) -> list[str]:
	if value is None:
		return [row.name for row in frappe.db.sql(
			"""SELECT name FROM `tabSales Invoice`
			WHERE docstatus = 1 AND COALESCE(TRIM(cost_center), '') = ''
			ORDER BY name""", as_dict=True,
		)]
	if isinstance(value, str):
		value = json.loads(value)
	if not isinstance(value, (list, tuple)) or any(not isinstance(name, str) or not name.strip() for name in value):
		raise ValueError("invoice_names must be a list of nonempty invoice names")
	return sorted({name.strip() for name in value})


def _read_identity(customer: str):
	contracts = frappe.get_all(
		"Mietvertrag", filters={"kunde": customer},
		fields=["name", "kunde", "wohnung", "immobilie", "docstatus"], limit_page_length=2,
	)
	if len(contracts) != 1:
		raise _SkipCandidate("customer_contract_not_unique")
	contract = contracts[0]
	if cint(contract.docstatus) == 2 or not contract.wohnung:
		raise _SkipCandidate("contract_cancelled_or_without_apartment")
	property_name = frappe.db.get_value("Wohnung", contract.wohnung, "immobilie")
	if not property_name or (contract.immobilie and contract.immobilie != property_name):
		raise _SkipCandidate("contract_property_conflict")
	cost_center = frappe.db.get_value("Immobilie", property_name, "kostenstelle")
	company = _company_via_wohnung(contract.wohnung)
	return frappe._dict(
		name=contract.name, kunde=customer, wohnung=contract.wohnung,
		immobilie=property_name, cost_center=cost_center, company=company,
	)


def _decision(invoice, identity) -> dict:
	if cint(invoice.docstatus) != 1:
		raise _SkipCandidate("invoice_not_submitted")
	if cstr(invoice.get("cost_center")).strip():
		raise _SkipCandidate("header_cost_center_already_set")
	if not invoice.customer or invoice.customer != identity.kunde:
		raise _SkipCandidate("invoice_customer_conflict")
	if not identity.company or invoice.company != identity.company:
		raise _SkipCandidate("invoice_company_conflict")
	if invoice.get("wohnung") and invoice.wohnung != identity.wohnung:
		raise _SkipCandidate("invoice_apartment_conflict")
	try:
		reference = _contract_reference(
			mietabrechnung_id=invoice.get("mietabrechnung_id"), remarks=invoice.get("remarks"),
			document_label=invoice.name,
		)
	except ValueError as exc:
		# A malformed historic period is a candidate error, not invalid repair
		# input. Continue reporting the remaining invoices without guessing it.
		raise _SkipCandidate(f"contract_reference_invalid: {exc}") from exc
	if reference.mietvertrag and reference.mietvertrag != identity.name:
		raise _SkipCandidate("invoice_contract_reference_conflict")
	items = invoice.get("items") or []
	if not items or any(not cstr(row.get("cost_center")).strip() for row in items):
		raise _SkipCandidate("item_cost_center_missing")
	centers = {cstr(row.get("cost_center")).strip() for row in items}
	if len(centers) != 1:
		raise _SkipCandidate("multiple_item_cost_centers")
	cost_center = next(iter(centers))
	if not identity.cost_center or cost_center != identity.cost_center:
		raise _SkipCandidate("item_property_cost_center_conflict")
	if any(row.get("wohnung") and row.wohnung != identity.wohnung for row in items):
		raise _SkipCandidate("item_apartment_conflict")
	return {
		"invoice": invoice.name, "customer": invoice.customer, "mietvertrag": identity.name,
		"company": invoice.company, "old_value": invoice.get("cost_center"), "new_value": cost_center,
	}


def execute(invoice_names=None, dry_run=True) -> dict:
	"""Return planned/applied/skipped rows, applying only with dry_run=False."""
	frappe.only_for("System Manager")
	is_dry_run = _dry_run_value(dry_run)
	names = _invoice_names(invoice_names)
	report = {"dry_run": is_dry_run, "planned": [], "applied": [], "skipped": []}
	if not is_dry_run and names:
		# Same first lock as direct accounting writes, before contract/invoice
		# locks. A global scope keeps a multi-company selection in stable order.
		lock_accounting_scope()
	for name in names:
		try:
			invoice = frappe.get_doc("Sales Invoice", name)
			if not invoice.customer:
				raise _SkipCandidate("invoice_customer_missing")
			identity = lock_customer_booking_identity(invoice.customer) if not is_dry_run else _read_identity(invoice.customer)
			if not is_dry_run:
				# A candidate list or an earlier nonlocking read is not authoritative.
				invoice = frappe.get_doc("Sales Invoice", name, for_update=True)
			cost_center = frappe.db.get_value(
				"Cost Center", identity.cost_center, ["name", "company", "is_group", "disabled"],
				as_dict=True, for_update=not is_dry_run,
			) if identity.cost_center else None
			if (
				not cost_center or cost_center.company != identity.company
				or cint(cost_center.is_group) or cint(cost_center.disabled)
			):
				raise _SkipCandidate("property_cost_center_invalid")
			plan = _decision(invoice, identity)
			report["planned"].append(plan)
			if not is_dry_run:
				frappe.db.set_value("Sales Invoice", name, "cost_center", plan["new_value"], update_modified=False)
				report["applied"].append(dict(plan))
		except (frappe.DoesNotExistError, frappe.ValidationError, _SkipCandidate) as exc:
			report["skipped"].append({"invoice": name, "reason": str(exc)})
	return report
