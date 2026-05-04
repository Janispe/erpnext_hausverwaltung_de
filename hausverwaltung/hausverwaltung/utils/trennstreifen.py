from __future__ import annotations

import base64
import io
from typing import Optional

import frappe

from hausverwaltung.hausverwaltung.utils.mieter_name import get_hauptmieter_display_name


def get_vormieter_display_name(
	wohnung: str | None,
	von: object,
	exclude: str | None = None,
) -> str:
	"""Display name of the Hauptmieter of the most recent prior Mietvertrag for the same Wohnung.

	Picks the contract with the largest `bis < von` (excluding `exclude` if given).
	Returns empty string when no prior contract exists.
	"""
	wohnung_name = (wohnung or "").strip()
	if not wohnung_name or not von:
		return ""

	# Explicit SQL — Frappe's `["<", date]` filter wraps `bis` in COALESCE(bis, '0001-01-01'),
	# which would let NULL-bis rows match `bis < <future-date>`. We need a strict bis < von.
	conditions = ["wohnung = %(wohnung)s", "bis IS NOT NULL", "bis < %(von)s", "docstatus != 2"]
	params: dict = {"wohnung": wohnung_name, "von": von}
	if exclude:
		conditions.append("name != %(exclude)s")
		params["exclude"] = exclude

	rows = frappe.db.sql(
		f"SELECT name FROM `tabMietvertrag` WHERE {' AND '.join(conditions)} ORDER BY bis DESC LIMIT 1",
		params,
		as_dict=True,
	)
	if not rows:
		return ""

	return _hauptmieter_for_mietvertrag(rows[0].get("name"))


def get_nachmieter_display_name(
	wohnung: str | None,
	von: object,
	exclude: str | None = None,
) -> str:
	"""Display name of the Hauptmieter of the next Mietvertrag for the same Wohnung.

	Picks the contract with the smallest `von > von` (excluding `exclude` if given).
	Returns empty string when no successor contract exists.
	"""
	wohnung_name = (wohnung or "").strip()
	if not wohnung_name or not von:
		return ""

	conditions = ["wohnung = %(wohnung)s", "von IS NOT NULL", "von > %(von)s", "docstatus != 2"]
	params: dict = {"wohnung": wohnung_name, "von": von}
	if exclude:
		conditions.append("name != %(exclude)s")
		params["exclude"] = exclude

	rows = frappe.db.sql(
		f"SELECT name FROM `tabMietvertrag` WHERE {' AND '.join(conditions)} ORDER BY von ASC LIMIT 1",
		params,
		as_dict=True,
	)
	if not rows:
		return ""

	return _hauptmieter_for_mietvertrag(rows[0].get("name"))


def _hauptmieter_for_mietvertrag(mietvertrag_name: str | None) -> str:
	if not mietvertrag_name:
		return ""
	mieter_rows = frappe.get_all(
		"Vertragspartner",
		filters={"parenttype": "Mietvertrag", "parent": mietvertrag_name},
		fields=["mieter", "rolle"],
		order_by="idx asc",
	)
	return get_hauptmieter_display_name(mieter_rows)


def get_contact_kontakte(contact_name: str | None) -> dict:
	"""Return primary phone, mobile and email for a Contact.

	Picks `is_primary_phone` for telefon, `is_primary_mobile_no` for mobil
	and `is_primary` for email. Falls back to first row when no primary is set.
	"""
	contact = (contact_name or "").strip()
	if not contact:
		return {"telefon": "", "mobil": "", "email": ""}

	try:
		doc = frappe.get_cached_doc("Contact", contact)
	except Exception:
		return {"telefon": "", "mobil": "", "email": ""}

	telefon = ""
	mobil = ""
	first_phone = ""
	for row in getattr(doc, "phone_nos", None) or []:
		number = (getattr(row, "phone", "") or "").strip()
		if not number:
			continue
		if not first_phone:
			first_phone = number
		if getattr(row, "is_primary_mobile_no", 0) and not mobil:
			mobil = number
		if getattr(row, "is_primary_phone", 0) and not telefon:
			telefon = number

	if not telefon and not mobil:
		telefon = first_phone

	email = ""
	first_email = ""
	for row in getattr(doc, "email_ids", None) or []:
		addr = (getattr(row, "email_id", "") or "").strip()
		if not addr:
			continue
		if not first_email:
			first_email = addr
		if getattr(row, "is_primary", 0) and not email:
			email = addr
	if not email:
		email = first_email

	return {"telefon": telefon, "mobil": mobil, "email": email}


def make_qr_data_url(url: str, *, scale: int = 3, quiet_zone: int = 0) -> str:
	"""Return a `data:image/png;base64,…` URL containing a QR code for `url`.

	Uses PyQRCode (pure Python, ships with the bench env). Returns empty string
	on any error so the print format can fall back to no-QR layout.
	"""
	target = (url or "").strip()
	if not target:
		return ""

	try:
		import pyqrcode

		qr = pyqrcode.create(target, error="M")
		buf = io.BytesIO()
		qr.png(buf, scale=scale, quiet_zone=quiet_zone)
		b64 = base64.b64encode(buf.getvalue()).decode("ascii")
		return f"data:image/png;base64,{b64}"
	except Exception:
		return ""


def get_wohnung_adresse(wohnung_name: str | None) -> dict:
	"""Return display strings for a Wohnung's address, gebäudeteil and lage.

	Wohnung itself has no address field — the address lives on the linked Immobilie.
	Falls back gracefully when fields are missing.
	"""
	name = (wohnung_name or "").strip()
	if not name:
		return {"adresse": "", "gebaeudeteil": "", "lage": ""}

	wohnung = frappe.db.get_value(
		"Wohnung",
		name,
		["immobilie", "gebaeudeteil", "name__lage_in_der_immobilie", "id"],
		as_dict=True,
	) or {}

	immobilie_name = (wohnung.get("immobilie") or "").strip()
	adresse = ""
	if immobilie_name:
		imm = frappe.db.get_value(
			"Immobilie",
			immobilie_name,
			["adresse_titel", "bezeichnung"],
			as_dict=True,
		) or {}
		adresse = (imm.get("adresse_titel") or imm.get("bezeichnung") or "").strip()

	return {
		"adresse": adresse,
		"gebaeudeteil": (wohnung.get("gebaeudeteil") or "").strip(),
		"lage": (wohnung.get("name__lage_in_der_immobilie") or "").strip(),
		"id": wohnung.get("id"),
	}
