from __future__ import annotations

import frappe
from frappe.utils import cstr


PROFILE_DOCTYPE = "Serienbrief Beispielobjekt"


def _doctype_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _append_values(doc, values: dict[str, str | int | float | bool | tuple[str, object]]) -> None:
	doc.set("werte", [])
	for path, value in sorted(values.items()):
		value_type = "Text"
		raw_value = value
		if isinstance(value, tuple):
			value_type, raw_value = value
		doc.append(
			"werte",
			{
				"pfad": path,
				"wert_typ": value_type,
				"wert": cstr(raw_value if raw_value is not None else ""),
			},
		)


def _upsert_profile(title: str, target_doctype: str, values: dict[str, object], *, priority: int = 0) -> bool:
	if not _doctype_exists(PROFILE_DOCTYPE) or not _doctype_exists(target_doctype):
		return False

	name = frappe.db.exists(PROFILE_DOCTYPE, title)
	if name:
		doc = frappe.get_doc(PROFILE_DOCTYPE, name)
	else:
		doc = frappe.new_doc(PROFILE_DOCTYPE)
		doc.title = title

	doc.enabled = 1
	doc.target_doctype = target_doctype
	doc.template = None
	doc.priority = priority
	doc.description = "Von hausverwaltung gepflegtes Beispielobjekt fuer die Serienbrief-Vorschau."
	_append_values(doc, values)

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	return True


def _base_mietvertrag_values(prefix: str = "") -> dict[str, object]:
	p = f"{prefix}." if prefix else ""
	return {
		f"{p}doctype": "Mietvertrag",
		f"{p}name": "PREVIEW-MIETVERTRAG-001",
		f"{p}title": "Beispiel-Mietvertrag",
		f"{p}mietbeginn": "01.04.2015",
		f"{p}bruttomiete": "1.234,56 EUR",
		f"{p}kaltmiete": "995,00 EUR",
		f"{p}vorauszahlung_betriebskosten": "145,00 EUR",
		f"{p}vorauszahlung_heizkosten": "94,56 EUR",
		f"{p}mieter[0].rolle": "Hauptmieter",
		f"{p}mieter[0].kontakt.doctype": "Contact",
		f"{p}mieter[0].kontakt.name": "PREVIEW-CONTACT-001",
		f"{p}mieter[0].kontakt.salutation": "Frau",
		f"{p}mieter[0].kontakt.first_name": "Maria",
		f"{p}mieter[0].kontakt.last_name": "Musterfrau",
		f"{p}mieter[1].rolle": "Hauptmieter",
		f"{p}mieter[1].kontakt.doctype": "Contact",
		f"{p}mieter[1].kontakt.name": "PREVIEW-CONTACT-002",
		f"{p}mieter[1].kontakt.salutation": "Herr",
		f"{p}mieter[1].kontakt.first_name": "Max",
		f"{p}mieter[1].kontakt.last_name": "Mustermann",
		f"{p}kunde.doctype": "Customer",
		f"{p}kunde.name": "PREVIEW-CUSTOMER-001",
		f"{p}kunde.customer_name": "Musterfrau und Mustermann",
		f"{p}kunde.briefanschrift.doctype": "Address",
		f"{p}kunde.briefanschrift.name": "PREVIEW-ADDRESS-001",
		f"{p}kunde.briefanschrift.address_line1": "Musterstrasse 12",
		f"{p}kunde.briefanschrift.pincode": "12345",
		f"{p}kunde.briefanschrift.city": "Berlin",
		f"{p}kunde.briefanschrift.plz_ort": "12345 Berlin",
		f"{p}kunde.briefanschrift.adresse": "Maria Musterfrau und Max Mustermann<br/>Musterstrasse 12<br/>12345 Berlin",
		f"{p}wohnung.doctype": "Wohnung",
		f"{p}wohnung.name": "PREVIEW-WOHNUNG-001",
		f"{p}wohnung.titel": "4.OG links",
		f"{p}wohnung.immobilie.doctype": "Immobilie",
		f"{p}wohnung.immobilie.name": "PREVIEW-IMMOBILIE-001",
		f"{p}wohnung.immobilie.titel": "Musterhaus Berlin",
		f"{p}wohnung.immobilie.adresse": "Musterstrasse 12, 12345 Berlin",
		f"{p}wohnung.immobilie.bank_name": "Musterbank",
		f"{p}wohnung.immobilie.iban": "DE02120300000000202051",
		f"{p}wohnung.immobilie.bic": "BYLADEM1001",
	}


def _invalidate_cached_previews(target_doctypes: set[str]) -> None:
	if not target_doctypes or not frappe.db.has_column("Serienbrief Vorlage", "preview_pdf_file"):
		return
	for template in frappe.get_all(
		"Serienbrief Vorlage",
		filters={"haupt_verteil_objekt": ["in", sorted(target_doctypes)]},
		fields=["name"],
	):
		frappe.db.set_value(
			"Serienbrief Vorlage",
			template["name"],
			"preview_pdf_file",
			"",
			update_modified=False,
		)


def execute() -> None:
	changed_targets: set[str] = set()

	if _upsert_profile(
		"Hausverwaltung Beispiel: Mietvertrag",
		"Mietvertrag",
		{
			**_base_mietvertrag_values(),
			"datum": "31.12.2024",
			"datum_iso": "2024-12-31",
		},
		priority=100,
	):
		changed_targets.add("Mietvertrag")

	if _upsert_profile(
		"Hausverwaltung Beispiel: Betriebskostenabrechnung Mieter",
		"Betriebskostenabrechnung Mieter",
		{
			"doctype": "Betriebskostenabrechnung Mieter",
			"name": "PREVIEW-BK-MIETER-001",
			"abrechnungsjahr": "2024",
			"nachzahlung": "60,00 EUR",
			"guthaben": "0,00 EUR",
			**_base_mietvertrag_values("mietvertrag"),
		},
		priority=100,
	):
		changed_targets.add("Betriebskostenabrechnung Mieter")

	if _upsert_profile(
		"Hausverwaltung Beispiel: Dunning",
		"Dunning",
		{
			"doctype": "Dunning",
			"name": "PREVIEW-DUNNING-001",
			"customer.doctype": "Customer",
			"customer.name": "PREVIEW-CUSTOMER-001",
			"customer.customer_name": "Musterfrau und Mustermann",
			"customer.briefanschrift.doctype": "Address",
			"customer.briefanschrift.name": "PREVIEW-ADDRESS-001",
			"customer.briefanschrift.address_line1": "Musterstrasse 12",
			"customer.briefanschrift.pincode": "12345",
			"customer.briefanschrift.city": "Berlin",
			"customer.briefanschrift.plz_ort": "12345 Berlin",
			"customer.briefanschrift.adresse": "Maria Musterfrau und Max Mustermann<br/>Musterstrasse 12<br/>12345 Berlin",
			**_base_mietvertrag_values("mietvertrag"),
			"overdue_payments.sales_invoice.mietvertrag.doctype": "Mietvertrag",
			**_base_mietvertrag_values("overdue_payments.sales_invoice.mietvertrag"),
		},
		priority=100,
	):
		changed_targets.add("Dunning")

	_invalidate_cached_previews(changed_targets)
