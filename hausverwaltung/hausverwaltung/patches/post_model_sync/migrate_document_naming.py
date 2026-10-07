"""Introduce document numbers and titles without renaming any existing record.

Only counters, display fields, and their metadata are written. No document is
saved/submitted, so accounting and external archive hooks are not triggered.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from hausverwaltung.hausverwaltung.utils.document_naming import DOCUMENT_SERIES, seed_document_series
from hausverwaltung.hausverwaltung.utils.document_titles import TITLE_DOCTYPES, build_document_title


def preflight() -> dict:
	"""Read-only checks, also callable with bench execute before a production update."""
	blockers = []
	rules = frappe.get_all(
		"Document Naming Rule",
		filters={"document_type": ["in", list(DOCUMENT_SERIES)], "disabled": 0},
		fields=["name", "document_type"],
		limit_page_length=0,
	)
	for rule in rules:
		blockers.append(f"Aktive Document Naming Rule für {rule.document_type}: {rule.name}")
	for setter in frappe.get_all(
		"Property Setter",
		filters={"doc_type": ["in", list(DOCUMENT_SERIES)], "property": ["in", ["autoname", "naming_rule"]]},
		fields=["doc_type", "property", "value"],
		limit_page_length=0,
	):
		if setter.doc_type != "Customer" and setter.value not in (None, "", "By script"):
			blockers.append(f"Abweichende Namenskonfiguration: {setter.doc_type}.{setter.property}={setter.value}")
	# The contract is the identity authority; do not manufacture a title from ambiguous ownership.
	contracts = frappe.get_all("Mietvertrag", fields=["name", "kunde", "wohnung"], limit_page_length=0)
	owners = {}
	for contract in contracts:
		if not contract.kunde or not contract.wohnung:
			blockers.append(f"Mietvertrag ohne Customer oder Wohnung: {contract.name}")
		elif contract.kunde in owners:
			blockers.append(f"Customer mehreren Mietverträgen zugeordnet: {contract.kunde}")
		else:
			owners[contract.kunde] = contract.name
	customers = set(frappe.get_all("Customer", pluck="name", limit_page_length=0))
	apartments = set(frappe.get_all("Wohnung", pluck="name", limit_page_length=0))
	for customer in owners.keys() - customers:
		blockers.append(f"Verknüpfter Customer fehlt: {customer}")
	for contract in contracts:
		if contract.wohnung and contract.wohnung not in apartments:
			blockers.append(f"Verknüpfte Wohnung fehlt: {contract.name} -> {contract.wohnung}")
	counts = {}
	digest = hashlib.sha256()
	for doctype in DOCUMENT_SERIES:
		if not frappe.db.exists("DocType", doctype):
			continue
		names = sorted(frappe.get_all(doctype, pluck="name", limit_page_length=0))
		counts[doctype] = len(names)
		digest.update(json.dumps([doctype, names], ensure_ascii=False).encode())
	link_digest = hashlib.sha256(json.dumps(sorted(
		(contract.name, contract.kunde or "", contract.wohnung or "") for contract in contracts
	), ensure_ascii=False).encode()).hexdigest()
	return {"ready": not blockers, "blockers": blockers, "counts": counts,
		"document_ids_sha256": digest.hexdigest(), "contract_links_sha256": link_digest}


def _ensure_customer_title_schema() -> None:
	# Customizations sync after post_model_sync patches in Frappe. Create this field
	# now as well, so the backfill works on upgrades and on fresh installations.
	path = Path(frappe.get_app_path("hausverwaltung", "hausverwaltung", "custom", "customer.json"))
	customization = json.loads(path.read_text())
	field = next(field for field in customization["custom_fields"] if field["fieldname"] == "hv_display_title")
	create_custom_fields({"Customer": [field]}, update=True)
	for property_name, value, fieldtype in (
		("title_field", "hv_display_title", "Data"),
		("show_title_field_in_link", "1", "Check"),
		("allow_rename", "0", "Check"),
	):
		make_property_setter("Customer", None, property_name, value, fieldtype, for_doctype=True)
	frappe.clear_cache(doctype="Customer")


def _write_title(doctype: str, name: str, fieldname: str, title: str) -> None:
	if (frappe.db.get_value(doctype, name, fieldname) or "") != title:
		frappe.db.set_value(doctype, name, fieldname, title, update_modified=False)


def execute() -> None:
	result = preflight()
	if not result["ready"]:
		frappe.throw("Dokumentnamens-Migration benötigt eine Datenbereinigung:\n" + "\n".join(result["blockers"]))
	_ensure_customer_title_schema()
	seed_document_series()
	# Ordered dependencies: building -> apartment -> records referring to apartment.
	for name in frappe.get_all("Immobilie", pluck="name", limit_page_length=0):
		doc = frappe.get_doc("Immobilie", name)
		title = frappe.db.get_value("Address", doc.adresse, "address_title") if doc.adresse else ""
		_write_title("Immobilie", name, "adresse_titel", title or doc.bezeichnung or doc.objekt or name)
	for doctype in ["Wohnung", *sorted(TITLE_DOCTYPES - {"Wohnung"})]:
		for name in frappe.get_all(doctype, pluck="name", limit_page_length=0):
			doc = frappe.get_doc(doctype, name)
			_write_title(doctype, name, "bezeichnung", build_document_title(doc) or name)
	from hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag import (
		_build_customer_display_title,
		_build_mietvertrag_display_title,
	)
	for name in frappe.get_all("Mietvertrag", pluck="name", limit_page_length=0):
		doc = frappe.get_doc("Mietvertrag", name)
		_write_title("Mietvertrag", name, "bezeichnung", _build_mietvertrag_display_title(doc) or name)
		_write_title("Customer", doc.kunde, "hv_display_title", _build_customer_display_title(doc))
	# Non-contract legacy customers are kept; they get their existing display name.
	for customer in frappe.get_all("Customer", fields=["name", "customer_name", "hv_display_title"], limit_page_length=0):
		if not customer.hv_display_title:
			_write_title("Customer", customer.name, "hv_display_title", customer.customer_name or customer.name)
	# An explicit guard against accidental identity or relation changes in future edits.
	after = preflight()
	for key in ("document_ids_sha256", "contract_links_sha256"):
		if result[key] != after[key]:
			frappe.throw("Dokumentnamens-Migration hat unerwartet Identitäten oder Vertragslinks verändert.")
