"""Refresh dependent display fields without saving or renaming business records."""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.utils.document_titles import build_document_title

_SOURCE_FIELDS = {
	"Address": ("address_title", "address_line1"),
	"Immobilie": ("adresse", "adresse_titel", "bezeichnung", "objekt"),
	"Wohnung": ("immobilie", "gebaeudeteil", "name__lage_in_der_immobilie", "bezeichnung"),
	"Zaehler": ("zaehlerart", "zaehlernummer", "standort_beschreibung", "bezeichnung"),
	"Customer": ("customer_name",),
	"Contact": ("first_name", "middle_name", "last_name", "company_name", "full_name"),
	"Mietvertrag": ("wohnung", "kunde", "bezeichnung"),
}
_PROPERTY_SETTLEMENTS = ("Betriebskostenabrechnung Immobilie", "Heizkostenabrechnung Immobilie")
_TENANT_SETTLEMENTS = ("Betriebskostenabrechnung Mieter", "Heizkostenabrechnung Mieter")


def _write_title(doctype: str, name: str, field: str, title: str) -> None:
	if (frappe.db.get_value(doctype, name, field) or "") != title:
		frappe.db.set_value(doctype, name, field, title, update_modified=False)


def _refresh_records(doctype: str, filters: dict) -> None:
	for name in frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0):
		doc = frappe.get_doc(doctype, name)
		_write_title(doctype, name, "bezeichnung", build_document_title(doc) or name)


def _refresh_contracts(filters: dict) -> set[str]:
	from hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag import (
		_build_mietvertrag_display_title,
	)

	customers = set()
	for name in frappe.get_all("Mietvertrag", filters=filters, pluck="name", limit_page_length=0):
		doc = frappe.get_doc("Mietvertrag", name)
		customer = doc.get("kunde")
		owners = (
			frappe.get_all("Mietvertrag", filters={"kunde": customer}, pluck="name", limit=2)
			if customer
			else []
		)
		if owners != [name] or not frappe.db.exists("Customer", customer):
			frappe.throw(
				f"Anzeigetitel kann nicht aktualisiert werden: Mietvertrag {name} hat keinen eindeutigen eigenen Customer."
			)
		title = _build_mietvertrag_display_title(doc) or name
		_write_title("Mietvertrag", name, "bezeichnung", title)
		_write_title("Customer", customer, "hv_display_title", title)
		customers.add(customer)
	return customers


def _refresh_customer_settlements(customers: set[str]) -> None:
	if customers:
		for doctype in _TENANT_SETTLEMENTS:
			_refresh_records(doctype, {"customer": ["in", sorted(customers)]})


def _refresh_apartments(apartments: list[str]) -> None:
	if not apartments:
		return
	filters = {"wohnung": ["in", apartments]}
	_refresh_records("Wohnung", {"name": ["in", apartments]})
	customers = _refresh_contracts(filters)
	_refresh_records("Wohnungszustand", filters)
	_refresh_records("Zaehler Zuordnung", {"bezugsobjekt_typ": "Wohnung", "bezugsobjekt": ["in", apartments]})
	for doctype in _TENANT_SETTLEMENTS:
		_refresh_records(doctype, filters)
	_refresh_customer_settlements(customers)


def _refresh_properties(properties: list[str], *, include_apartments: bool = True) -> None:
	if not properties:
		return
	for name in properties:
		doc = frappe.get_doc("Immobilie", name)
		address_title = frappe.db.get_value("Address", doc.adresse, "address_title") if doc.adresse else ""
		_write_title(
			"Immobilie", name, "adresse_titel", address_title or doc.bezeichnung or doc.objekt or name
		)
	if include_apartments:
		_refresh_apartments(
			frappe.get_all(
				"Wohnung", filters={"immobilie": ["in", properties]}, pluck="name", limit_page_length=0
			)
		)
	_refresh_records(
		"Zaehler Zuordnung", {"bezugsobjekt_typ": "Immobilie", "bezugsobjekt": ["in", properties]}
	)
	for doctype in _PROPERTY_SETTLEMENTS:
		_refresh_records(doctype, {"immobilie": ["in", properties]})


def _partners(doc) -> tuple:
	return tuple(
		tuple(str(row.get(field) or "") for field in ("mieter", "rolle", "eingezogen", "ausgezogen"))
		for row in (doc.get("mieter") or [])
	)


def refresh_dependent_titles(doc, method: str | None = None) -> None:
	"""Follow explicit source links after a relevant source field changes."""
	fields = _SOURCE_FIELDS.get(doc.doctype, ())
	previous = doc.get_doc_before_save()
	partners_changed = doc.doctype == "Mietvertrag" and (
		not previous or _partners(previous) != _partners(doc)
	)
	if (
		previous
		and not partners_changed
		and not any(previous.get(field) != doc.get(field) for field in fields)
	):
		return
	if doc.doctype == "Address":
		_refresh_properties(
			frappe.get_all("Immobilie", filters={"adresse": doc.name}, pluck="name", limit_page_length=0)
		)
	elif doc.doctype == "Immobilie":
		_refresh_properties([doc.name])
	elif doc.doctype == "Wohnung":
		_refresh_apartments([doc.name])
	elif doc.doctype == "Zaehler":
		_refresh_records("Zaehler Zuordnung", {"zaehler": doc.name})
	elif doc.doctype == "Customer":
		_refresh_customer_settlements({doc.name})
	elif doc.doctype == "Contact":
		contracts = frappe.get_all(
			"Vertragspartner",
			filters={"parenttype": "Mietvertrag", "mieter": doc.name},
			pluck="parent",
			limit_page_length=0,
		)
		if contracts:
			_refresh_customer_settlements(_refresh_contracts({"name": ["in", sorted(set(contracts))]}))
	elif doc.doctype == "Mietvertrag" and doc.get("kunde"):
		# Frappe skips validate/on_update for changes to submitted partner rows.
		# Check ownership first; do not create a replacement Customer as a fallback.
		_refresh_contracts({"name": doc.name})
		doc._sync_display_title()
		if partners_changed:
			doc._sync_customer_name()
		_refresh_customer_settlements({doc.kunde})


def refresh_all_titles() -> None:
	"""Backfill the same dependencies for sites upgraded before this hook existed."""
	from hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_document_naming import preflight

	result = preflight()
	if not result["ready"]:
		frappe.throw("Titel-Aktualisierung benötigt eine Datenbereinigung:\n" + "\n".join(result["blockers"]))
	_refresh_properties(
		frappe.get_all("Immobilie", pluck="name", limit_page_length=0), include_apartments=False
	)
	# An apartment's property link is optional; cover those apartments as well.
	_refresh_apartments(frappe.get_all("Wohnung", pluck="name", limit_page_length=0))
	_refresh_records("Zaehler", {})
	_refresh_records("Zaehler Zuordnung", {})
