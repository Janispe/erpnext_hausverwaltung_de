r"""Prepare/apply an explicitly reviewed contract rename on invoice references.

This manual repair is deliberately absent from patches.txt. It does not infer
renames from a person, dates, apartment history or similar contract names.

    bench --site SITE execute \
      hausverwaltung.hausverwaltung.patches.post_model_sync.repair_renamed_mietvertrag_invoice_markers.execute \
      --kwargs '{"renames": {"EXACT OLD NAME": "EXACT CURRENT NAME"}}'

The default is a read-only dry run. Inspect its planned/skipped rows first;
only an explicit dry_run=False writes remarks/mietabrechnung_id. No invoice
save, GL repost, accounting-date update or internal commit is performed.
The caller owns the transaction and should retain the returned change report.
"""

from __future__ import annotations

import json
import re
from datetime import date

import frappe
from frappe.utils import cint, cstr

from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import _company_via_wohnung
from hausverwaltung.hausverwaltung.utils.booking_locks import lock_accounting_scope
from hausverwaltung.hausverwaltung.utils.customer_booking_identity import lock_customer_booking_identity

_MARKER = re.compile(r"\[MV:([^\]\r\n]+)\]")
_PERIOD = re.compile(r"(?:0[1-9]|1[0-2])/\d{4}")


def _text(value) -> str:
	return cstr(value).strip()


def _changes(invoice, old: str, new: str, identity) -> tuple[dict, str | None]:
	"""Validate one invoice without mutation and replace complete references."""
	if cint(invoice.get("docstatus")) != 1:
		return {}, "invoice_not_submitted"
	for field, expected in (
		("customer", identity.get("kunde")),
		("wohnung", identity.get("wohnung")),
		("company", identity.get("company")),
	):
		if not _text(expected) or _text(invoice.get(field)) != _text(expected):
			return {}, f"invoice_{field}_conflict_or_missing"
	if invoice.get("cost_center") and _text(invoice.get("cost_center")) != _text(identity.get("cost_center")):
		return {}, "invoice_cost_center_conflict"
	items = invoice.get("items") or []
	if not items:
		return {}, "invoice_items_missing"
	for item in items:
		for field in ("wohnung", "cost_center"):
			if item.get(field) and _text(item.get(field)) != _text(identity.get(field)):
				return {}, f"item_{field}_conflict"

	remarks = cstr(invoice.get("remarks"))
	markers = list(_MARKER.finditer(remarks))
	if remarks.count("[MV:") != len(markers):
		return {}, "malformed_contract_marker"
	marker_names = {_text(match.group(1)) for match in markers}
	if any(not name or name not in {old, new} for name in marker_names):
		return {}, "foreign_contract_marker"

	structured = cstr(invoice.get("mietabrechnung_id"))
	structured_name = None
	period = None
	if structured:
		structured_name, separator, period = structured.rpartition("|")
		if not separator or not _PERIOD.fullmatch(period):
			return {}, "malformed_structured_reference"
		month, year = period.split("/")
		try:
			date(int(year), int(month), 1)
		except ValueError:
			return {}, "malformed_structured_reference"
		if structured_name not in {old, new}:
			return {}, "foreign_structured_reference"

	# Some installations carry an additional Link field. Never leave a stale
	# Link behind or silently broaden this two-field repair to another field.
	linked_contract = _text(invoice.get("mietvertrag"))
	if linked_contract and linked_contract != new:
		return {}, "additional_contract_field_requires_review"

	changes = {}
	if old in marker_names:
		changes["remarks"] = _MARKER.sub(
			lambda match: f"[MV:{new}]" if _text(match.group(1)) == old else match.group(0), remarks
		)
	if structured_name == old:
		changes["mietabrechnung_id"] = f"{new}|{period}"
	return changes, None if changes else "no_old_reference"


def _mapping_identity(old: str, new: str, *, for_update: bool):
	if frappe.db.exists("Mietvertrag", old):
		raise ValueError("old_contract_still_exists")
	contract = frappe.db.get_value(
		"Mietvertrag",
		new,
		["name", "kunde", "wohnung", "immobilie", "docstatus"],
		as_dict=True,
		for_update=for_update,
	)
	if (
		not contract
		or not contract.get("kunde")
		or not contract.get("wohnung")
		or cint(contract.docstatus) == 2
	):
		raise ValueError("target_contract_missing_or_incomplete")
	if for_update:
		identity = lock_customer_booking_identity(contract.kunde)
		if identity.name != new:
			raise ValueError("customer_contract_not_unique")
		# Recheck the old name as a current read after locking the target identity.
		if frappe.db.get_value("Mietvertrag", old, "name", for_update=True):
			raise ValueError("old_contract_still_exists")
		return identity
	if frappe.get_all("Mietvertrag", filters={"kunde": contract.kunde}, pluck="name", limit=2) != [new]:
		raise ValueError("customer_contract_not_unique")
	property_name = frappe.db.get_value("Wohnung", contract.wohnung, "immobilie")
	if not property_name or (contract.get("immobilie") and contract.immobilie != property_name):
		raise ValueError("contract_property_conflict_or_missing")
	cost_center = frappe.db.get_value("Immobilie", property_name, "kostenstelle")
	if not cost_center:
		raise ValueError("property_cost_center_missing")
	company = _company_via_wohnung(contract.wohnung)
	cc = frappe.db.get_value("Cost Center", cost_center, ["company", "disabled", "is_group"], as_dict=True)
	if not company or not cc or cc.company != company or cc.get("disabled") or cc.get("is_group"):
		raise ValueError("property_company_or_cost_center_invalid")
	return frappe._dict(
		name=new, kunde=contract.kunde, wohnung=contract.wohnung, company=company, cost_center=cost_center
	)


def execute(renames=None, dry_run=True, invoice_names=None) -> dict:
	"""Return an inspectable report; applying requires explicit dry_run=false."""
	frappe.only_for("System Manager")
	if isinstance(renames, str):
		renames = json.loads(renames)
	if not isinstance(renames, dict) or not renames:
		raise ValueError("An explicit nonempty old-to-new contract mapping is required")
	if any(
		not isinstance(old, str)
		or not isinstance(new, str)
		or not old.strip()
		or not new.strip()
		or old != old.strip()
		or new != new.strip()
		or old == new
		or any(character in old + new for character in "]\r\n")
		for old, new in renames.items()
	):
		raise ValueError("Each mapping must contain two different exact contract names")
	if isinstance(invoice_names, str):
		invoice_names = json.loads(invoice_names)
	if invoice_names is not None and (
		not isinstance(invoice_names, list)
		or any(not isinstance(name, str) or not name for name in invoice_names)
	):
		raise ValueError("invoice_names must be a list of exact invoice names")
	if type(dry_run) not in (bool, int) or dry_run not in (0, 1):
		raise ValueError("dry_run must be an explicit boolean or 0/1")
	dry_run = bool(dry_run)
	report = {
		"dry_run": dry_run,
		"renames": dict(sorted(renames.items())),
		"planned": [],
		"applied": [],
		"skipped": [],
	}
	if not dry_run:
		lock_accounting_scope()  # Before any contract, property or invoice locks.
	for old, new in sorted(renames.items()):
		try:
			identity = _mapping_identity(old, new, for_update=not dry_run)
		except (ValueError, frappe.ValidationError) as exc:
			report["skipped"].append({"old": old, "new": new, "reason": str(exc)})
			continue
		filters = {"customer": identity.kunde, "docstatus": 1}
		if invoice_names is not None:
			filters["name"] = ["in", invoice_names]
		names = frappe.get_all(
			"Sales Invoice", filters=filters, pluck="name", order_by="name", limit_page_length=0
		)
		for name in names:
			invoice = frappe.get_doc("Sales Invoice", name, for_update=not dry_run)
			changes, reason = _changes(invoice, old, new, identity)
			entry = {"invoice": name, "old": old, "new": new}
			if reason:
				report["skipped"].append({**entry, "reason": reason})
				continue
			entry.update(before={field: invoice.get(field) for field in changes}, after=changes)
			if not dry_run:
				frappe.db.set_value("Sales Invoice", name, changes, update_modified=False)
			report["planned" if dry_run else "applied"].append(entry)
	report["counts"] = {key: len(report[key]) for key in ("planned", "applied", "skipped")}
	return report
