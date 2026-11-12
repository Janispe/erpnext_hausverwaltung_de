"""Aggregate-only, SELECT-only upgrade audit for an explicitly isolated copy.

Run after restoring a production backup into the disposable test stack, before
and after migration. This audits historical data; it never repairs records or
returns document names, customers, remarks, addresses or monetary amounts.

    bench --site fac.localhost execute \\
      hausverwaltung.hausverwaltung.utils.upgrade_preflight.execute \\
      --kwargs '{"expected_site": "fac.localhost"}'

Both allow_tests and hv_isolated_integration_test must already be enabled on
the copy. The module does not change site settings, jobs or email delivery.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date


_FIELDS = {
	"Customer": ("name",),
	"Mietvertrag": ("name", "kunde", "wohnung", "immobilie", "docstatus"),
	"Wohnung": ("name", "immobilie"),
	"Immobilie": ("name", "kostenstelle", "parent_immobilie", "old_parent", "haupt_bank_account", "konto", "kassenkonto"),
	"Cost Center": ("name", "company", "disabled", "is_group"),
	"Company": ("name",),
	"Account": ("name", "company"),
	"Bank Account": ("name", "company"),
	"Immobilie Bankkonto": ("parent", "konto"),
	"Immobilie Kassenkonto": ("parent", "konto"),
	"Sales Invoice": ("name", "customer", "company", "wohnung", "cost_center", "mietabrechnung_id", "remarks", "docstatus"),
	"Sales Invoice Item": ("parent", "wohnung", "cost_center"),
	"Payment Entry": ("name", "party_type", "party", "company", "wohnung", "cost_center", "docstatus"),
	"Journal Entry": ("name", "company", "docstatus"),
	"Journal Entry Account": ("parent", "party_type", "party", "wohnung", "cost_center"),
}
_OPTIONAL_FIELDS = {
	"Immobilie": {"parent_immobilie", "old_parent", "haupt_bank_account", "konto", "kassenkonto"},
	"Immobilie Bankkonto": {"parent", "konto"},
	"Immobilie Kassenkonto": {"parent", "konto"},
	"Sales Invoice": {"mietabrechnung_id"},
}
_MARKER = re.compile(r"\[MV:([^\]\r\n]+)\]")
_PERIOD = re.compile(r"(?:0[1-9]|1[0-2])/\d{4}")


def _text(value):
	return str(value or "").strip()


def _reference(row):
	"""Read the invoice reference without emitting messages containing data."""
	structured = _text(row.get("mietabrechnung_id"))
	names = set()
	if structured:
		contract, separator, period = structured.rpartition("|")
		if not separator or not contract.strip() or not _PERIOD.fullmatch(period.strip()):
			return None, "malformed_structured_reference"
		month, year = period.strip().split("/")
		try:
			date(int(year), int(month), 1)
		except ValueError:
			return None, "malformed_structured_reference"
		names.add(contract.strip())
	remarks = str(row.get("remarks") or "")
	markers = [_text(value) for value in _MARKER.findall(remarks)]
	if remarks.count("[MV:") != len(markers) or any(not value for value in markers):
		return None, "malformed_contract_marker"
	names.update(markers)
	if len(names) > 1:
		return None, "conflicting_contract_references"
	return next(iter(names), None), None


def audit_tables(tables):
	"""Summarize an in-memory SELECT snapshot; return counts, never row data.

	Findings count documents per reason and may overlap. Cancelled contracts
	still count toward Customer 1:1. Missing dimensions are separate from
	nonempty contradictions because historical PE/JE may legitimately be blank.
	"""
	indexes = {
		doctype: {_text(row.get("name")): row for row in rows if row.get("name")}
		for doctype, rows in tables.items()
	}
	blocking, review = Counter(), Counter()
	contracts = defaultdict(list)
	for row in tables.get("Mietvertrag", []):
		customer = _text(row.get("kunde"))
		if customer:
			contracts[customer].append(row)
		else:
			blocking["contracts_without_customer"] += 1
	for customer in indexes.get("Customer", {}):
		if not contracts[customer]:
			review["customers_without_contract"] += 1
	for customer, rows in contracts.items():
		if len(rows) > 1:
			blocking["customers_with_multiple_contracts_including_cancelled"] += 1
		if customer not in indexes.get("Customer", {}):
			blocking["contract_customer_missing"] += len(rows)

	financial_children = defaultdict(list)
	for table in ("Immobilie Bankkonto", "Immobilie Kassenkonto"):
		for row in tables.get(table, []):
			if row.get("konto"):
				financial_children[_text(row.get("parent"))].append(("Account", _text(row.get("konto"))))

	def identity(contract):
		flat = indexes.get("Wohnung", {}).get(_text(contract.get("wohnung")))
		if not flat:
			return None, "contract_apartment_missing"
		property_name = _text(flat.get("immobilie"))
		if contract.get("immobilie") and _text(contract["immobilie"]) != property_name:
			return None, "contract_property_conflict"
		prop = indexes.get("Immobilie", {}).get(property_name)
		if not prop:
			return None, "apartment_property_missing"
		cc_name = _text(prop.get("kostenstelle"))
		cc = indexes.get("Cost Center", {}).get(cc_name)
		if not cc or cc.get("disabled") or cc.get("is_group"):
			return None, "property_cost_center_missing_or_inactive_or_group"
		companies, visited = set(), set()
		while property_name:
			if property_name in visited:
				return None, "property_hierarchy_cycle"
			visited.add(property_name)
			prop = indexes.get("Immobilie", {}).get(property_name)
			if not prop:
				return None, "property_parent_missing"
			sources = list(financial_children[property_name])
			for field, doctype in (("kostenstelle", "Cost Center"), ("haupt_bank_account", "Bank Account"), ("konto", "Account"), ("kassenkonto", "Account")):
				if prop.get(field):
					sources.append((doctype, _text(prop[field])))
			for doctype, name in sources:
				company = _text(indexes.get(doctype, {}).get(name, {}).get("company"))
				if not company or company not in indexes.get("Company", {}):
					return None, "property_financial_source_missing_or_without_company"
				companies.add(company)
			property_name = _text(prop.get("parent_immobilie") or prop.get("old_parent"))
		if len(companies) != 1:
			return None, "property_financial_companies_conflict"
		return {"contract": _text(contract.get("name")), "wohnung": _text(flat.get("name")), "cost_center": cc_name, "company": next(iter(companies))}, None

	identities = {}
	for customer, rows in contracts.items():
		for contract in rows:
			context, reason = identity(contract)
			if reason:
				blocking[reason] += 1
			elif len(rows) == 1:
				identities[customer] = context

	items = defaultdict(list)
	for row in tables.get("Sales Invoice Item", []):
		items[_text(row.get("parent"))].append(row)
	for invoice in tables.get("Sales Invoice", []):
		if int(invoice.get("docstatus") or 0) != 1:
			continue
		context = identities.get(_text(invoice.get("customer")))
		if not context:
			blocking["submitted_invoices_without_unique_valid_customer_identity"] += 1
			continue
		name, reason = _reference(invoice)
		if reason:
			blocking["invoice_" + reason] += 1
		elif name and name != context["contract"]:
			blocking["invoice_contract_reference_conflict"] += 1
		for field in ("company", "wohnung", "cost_center"):
			actual = _text(invoice.get(field))
			if not actual:
				review["submitted_invoice_missing_" + field] += 1
			elif actual != context[field]:
				blocking["submitted_invoice_conflicting_" + field] += 1
		invoice_items = items[_text(invoice.get("name"))]
		if not invoice_items:
			blocking["submitted_invoice_without_items"] += 1
		for field in ("wohnung", "cost_center"):
			if any(not _text(row.get(field)) for row in invoice_items):
				review["submitted_invoice_item_missing_" + field] += 1
			if any(_text(row.get(field)) and _text(row.get(field)) != context[field] for row in invoice_items):
				blocking["submitted_invoice_item_conflicting_" + field] += 1

	def audit_tenant_row(row, company, prefix):
		context = identities.get(_text(row.get("party")))
		if not context:
			blocking[prefix + "_without_unique_valid_customer_identity"] += 1
			return
		if _text(company) != context["company"]:
			blocking[prefix + "_conflicting_company"] += 1
		for field in ("wohnung", "cost_center"):
			actual = _text(row.get(field))
			if not actual:
				review[prefix + "_missing_" + field] += 1
			elif actual != context[field]:
				blocking[prefix + "_conflicting_" + field] += 1

	for row in tables.get("Payment Entry", []):
		if int(row.get("docstatus") or 0) == 1 and row.get("party_type") == "Customer":
			audit_tenant_row(row, row.get("company"), "submitted_payment")
	for row in tables.get("Journal Entry Account", []):
		head = indexes.get("Journal Entry", {}).get(_text(row.get("parent")), {})
		if int(head.get("docstatus") or 0) == 1 and row.get("party_type") == "Customer":
			audit_tenant_row(row, head.get("company"), "submitted_journal_customer_row")
	return {
		"audit_version": 1,
		"counts_may_overlap": True,
		"totals": {doctype: len(rows) for doctype, rows in sorted(tables.items())},
		"blocking_findings": dict(sorted(blocking.items())),
		"historical_review_findings": dict(sorted(review.items())),
		"status": "review_required" if blocking or review else "no_findings_in_audited_fields",
	}


def execute(expected_site):
	"""Read only the explicit disposable copy and return aggregate counts."""
	import frappe

	if (
		not expected_site
		or expected_site != frappe.local.site
		or frappe.conf.get("allow_tests") not in (1, "1", True)
		or frappe.conf.get("hv_isolated_integration_test") not in (1, "1", True)
	):
		raise ValueError("Requires matching expected_site and both isolated test flags")
	frappe.only_for("System Manager")
	tables, missing, optional_missing = {}, {}, {}
	for doctype, fields in _FIELDS.items():
		table = "tab" + doctype
		columns = {row[0] for row in frappe.db.sql(
			"SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
			(table,),
		)}
		absent = set(fields) - columns
		optional = absent & _OPTIONAL_FIELDS.get(doctype, set())
		required = absent - optional
		if optional:
			optional_missing[doctype] = sorted(optional)
		if required:
			missing[doctype] = sorted(required)
		selected = [field for field in fields if field in columns]
		if not selected:
			tables[doctype] = []
			continue
		# All identifiers come from the fixed module allowlist above.
		projection = ", ".join("`" + field + "`" for field in selected)
		tables[doctype] = frappe.db.sql(f"SELECT {projection} FROM `{table}`", as_dict=True)
	report = audit_tables(tables)
	report["schema_missing_fields"] = missing
	report["schema_optional_missing_fields"] = optional_missing
	if missing:
		report["status"] = "incomplete_schema_requires_review"
	return report
