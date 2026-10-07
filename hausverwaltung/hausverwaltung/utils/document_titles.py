"""Display titles that can change independently of document identity."""

from __future__ import annotations

import re

import frappe
from frappe.utils import getdate

TITLE_DOCTYPES = {
	"Wohnung", "Wohnungszustand", "Zaehler", "Zaehler Zuordnung",
	"Betriebskostenabrechnung Immobilie", "Betriebskostenabrechnung Mieter",
	"Heizkostenabrechnung Immobilie", "Heizkostenabrechnung Mieter",
}


def _clean(value) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()


def _join(*parts) -> str:
	return " · ".join(dict.fromkeys(_clean(part) for part in parts if _clean(part)))[:240]


def _date(value) -> str:
	if not value:
		return ""
	return getdate(value).strftime("%d.%m.%Y")


def _label(doctype: str, name: str | None) -> str:
	if not name:
		return ""
	meta = frappe.get_meta(doctype)
	field = meta.title_field
	if field:
		return _clean(frappe.db.get_value(doctype, name, field)) or name
	return name


def build_document_title(doc) -> str:
	"""Describe a document using its explicit links and fields, never its ID syntax."""
	doctype = doc.doctype
	if doctype == "Wohnung":
		return _join(
			_label("Immobilie", doc.get("immobilie")),
			doc.get("gebaeudeteil"), doc.get("name__lage_in_der_immobilie"),
		)
	if doctype == "Zaehler":
		return _join(doc.get("zaehlerart"), doc.get("zaehlernummer"), doc.get("standort_beschreibung"))
	if doctype == "Wohnungszustand":
		return _join(_label("Wohnung", doc.get("wohnung")), f"ab {_date(doc.get('ab'))}" if doc.get("ab") else "")
	if doctype == "Zaehler Zuordnung":
		target = doc.get("bezugsobjekt_typ")
		return _join(
			_label("Zaehler", doc.get("zaehler")),
			_label(target, doc.get("bezugsobjekt")) if target in ("Wohnung", "Immobilie") else "",
			f"ab {_date(doc.get('von'))}" if doc.get("von") else "",
		)
	if doctype in TITLE_DOCTYPES:
		kind = "Betriebskosten" if doctype.startswith("Betriebskosten") else "Heizkosten"
		context = _label("Wohnung", doc.get("wohnung")) or _label("Immobilie", doc.get("immobilie"))
		# Person text stays separate from the customer ID and contract title.
		customer = doc.get("customer")
		person = frappe.db.get_value("Customer", customer, "customer_name") if customer else ""
		period = "–".join(part for part in (_date(doc.get("von")), _date(doc.get("bis"))) if part)  # noqa: RUF001
		return _join(kind, context, person, period)
	return _clean(doc.get("name"))


def set_document_title(doc, method: str | None = None) -> None:
	if doc.doctype in TITLE_DOCTYPES:
		doc.bezeichnung = build_document_title(doc) or doc.get("name") or doc.doctype
