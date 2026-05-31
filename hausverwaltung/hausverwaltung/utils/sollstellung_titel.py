from __future__ import annotations

import re
from typing import Any

import frappe
from frappe.utils import getdate


TYPE_LABELS = {
	"Miete": "Miete",
	"Betriebskosten": "Betriebskosten",
	"Heizkosten": "Heizkosten",
	"Untermietzuschlag": "Untermietzuschlag",
	"Guthaben/Nachzahlungen": "Guthaben/Nachzahlung",
	"BK Nachzahlung": "Betriebskosten Nachzahlung",
	"BK Guthaben": "Betriebskosten Guthaben",
	"HK Nachzahlung": "Heizkosten Nachzahlung",
	"HK Guthaben": "Heizkosten Guthaben",
	"Garage/Stellplatz": "Garage/Stellplatz",
	"VHB-SERVICE": "Service",
	"Mahngebuehr": "Mahngebuehr",
}


def build_sollstellung_titel(doc: Any) -> str:
	"""Build the human-facing title for rent-related Sales Invoices."""
	parts = [
		_get_wohnung_label(doc),
		_get_customer_label(doc),
		" ".join(filter(None, [_get_invoice_type(doc), _get_period_label(doc)])),
	]
	return " · ".join(part for part in parts if part)


def _get_wohnung_label(doc: Any) -> str:
	wohnung = _get(doc, "wohnung")
	if not wohnung:
		return ""

	try:
		name_lage = frappe.get_cached_value("Wohnung", wohnung, "name__lage_in_der_immobilie")
		if name_lage:
			return str(name_lage)
	except Exception:
		pass

	return str(wohnung)


def _get_customer_label(doc: Any) -> str:
	return str(_get(doc, "customer_name") or _get(doc, "customer") or "").strip()


def _get_invoice_type(doc: Any) -> str:
	remarks = str(_get(doc, "remarks") or "")
	match = re.search(r"\[TYPE:([^\]]+)\]", remarks)
	if match:
		raw_type = match.group(1).strip()
		return TYPE_LABELS.get(raw_type, raw_type)

	for item in _get_items(doc):
		item_code = str(_get(item, "item_code") or "").strip()
		if item_code in TYPE_LABELS:
			return TYPE_LABELS[item_code]
		item_name = str(_get(item, "item_name") or "").strip()
		if item_name:
			return item_name

	return "Sollstellung"


def _get_period_label(doc: Any) -> str:
	mietabrechnung_id = str(_get(doc, "mietabrechnung_id") or "").strip()
	if mietabrechnung_id:
		period = mietabrechnung_id.split("|")[-1].strip()
		if period:
			return period

	posting_date = _get(doc, "posting_date")
	if posting_date:
		date = getdate(posting_date)
		return date.strftime("%m/%Y")

	return ""


def _get_items(doc: Any) -> list[Any]:
	if isinstance(doc, dict):
		return doc.get("items") or []
	return getattr(doc, "items", None) or []


def _get(doc: Any, fieldname: str) -> Any:
	if isinstance(doc, dict):
		return doc.get(fieldname)
	if hasattr(doc, "get"):
		return doc.get(fieldname)
	return getattr(doc, fieldname, None)
