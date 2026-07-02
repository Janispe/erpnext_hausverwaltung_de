from __future__ import annotations

from typing import Iterable, Optional

import frappe


def pick_preferred_mieter_contact(rows: Iterable[object] | None) -> Optional[str]:
	"""Pick a tenant contact name from Vertragspartner rows.

	Priority:
	1) Rolle == "Hauptmieter" and not "Ausgezogen"
	2) First row with Rolle != "Ausgezogen"
	3) First row at all
	"""
	if not rows:
		return None

	rows_list = list(rows)
	if not rows_list:
		return None

	def _get(row, field: str) -> str:
		try:
			val = getattr(row, field, None)
		except Exception:
			val = None
		if val is None and isinstance(row, dict):
			val = row.get(field)
		return (val or "").strip()

	# 1) Hauptmieter, not Ausgezogen
	for row in rows_list:
		rolle = _get(row, "rolle")
		if rolle == "Ausgezogen":
			continue
		if rolle == "Hauptmieter":
			mieter = _get(row, "mieter")
			if mieter:
				return mieter

	# 2) First not Ausgezogen
	for row in rows_list:
		rolle = _get(row, "rolle")
		if rolle == "Ausgezogen":
			continue
		mieter = _get(row, "mieter")
		if mieter:
			return mieter

	# 3) Any row with a mieter set (auch Ausgezogen, als letzte Notbremse).
	# Vorher: starr rows_list[0] — wenn dort mieter leer ist, kommt None,
	# auch wenn spätere Rows einen Wert haetten.
	for row in rows_list:
		mieter = _get(row, "mieter")
		if mieter:
			return mieter
	return None


def get_hauptmieter_contacts(rows: Iterable[object] | None) -> list[str]:
	"""Return all contacts marked as Hauptmieter, preserving row order.

	If no Hauptmieter is set, fall back to the preferred tenant contact so existing
	contracts without explicit roles still get a useful name suffix.
	"""
	if not rows:
		return []

	rows_list = list(rows)
	if not rows_list:
		return []

	def _get(row, field: str) -> str:
		try:
			val = getattr(row, field, None)
		except Exception:
			val = None
		if val is None and isinstance(row, dict):
			val = row.get(field)
		return (val or "").strip()

	contacts: list[str] = []
	seen: set[str] = set()
	for row in rows_list:
		if _get(row, "rolle") != "Hauptmieter":
			continue
		mieter = _get(row, "mieter")
		if mieter and mieter not in seen:
			contacts.append(mieter)
			seen.add(mieter)

	if contacts:
		return contacts

	fallback = pick_preferred_mieter_contact(rows_list)
	return [fallback] if fallback else []


def get_contact_last_name(contact_name: str | None) -> str:
	"""Return last_name with fallbacks for a Contact."""
	contact = (contact_name or "").strip()
	if not contact:
		return ""

	try:
		row = frappe.db.get_value("Contact", contact, ["last_name", "first_name"], as_dict=True)
	except Exception:
		# frappe.db.get_value returnt bei nicht-existenter Row None (kein Throw).
		# Wenn wir hier landen, ist etwas Unerwartetes passiert (Lock, Permission,
		# DB-Connection). Vorher silent → falscher Anzeigename. Jetzt sichtbar.
		frappe.log_error(
			frappe.get_traceback(),
			f"get_contact_last_name: Lookup von Contact {contact!r} fehlgeschlagen.",
		)
		row = None

	last_name = (row.get("last_name") if row else "") or ""
	if last_name and isinstance(last_name, str):
		return last_name.strip()

	first_name = (row.get("first_name") if row else "") or ""
	if first_name and isinstance(first_name, str):
		return first_name.strip()

	return contact


def get_contact_display_name(contact_name: str | None) -> str:
	"""Return a readable Contact name as 'last first' when available."""
	contact = (contact_name or "").strip()
	if not contact:
		return ""

	try:
		row = frappe.db.get_value("Contact", contact, ["last_name", "first_name"], as_dict=True)
	except Exception:
		# Siehe Hinweis in get_contact_last_name: get_value wirft nicht bei
		# nicht-existenter Row, daher ist eine Exception hier unerwartet.
		frappe.log_error(
			frappe.get_traceback(),
			f"get_contact_display_name: Lookup von Contact {contact!r} fehlgeschlagen.",
		)
		row = None

	if row:
		parts = [(row.get("last_name") or "").strip(), (row.get("first_name") or "").strip()]
		display = " ".join(part for part in parts if part)
		if display:
			return display

	return contact


def get_contact_salutation_full_name(contact_name: str | None) -> str:
	"""Return a readable Contact name as 'salutation first last' when available."""
	contact = (contact_name or "").strip()
	if not contact:
		return ""

	try:
		row = frappe.db.get_value(
			"Contact",
			contact,
			["salutation", "first_name", "last_name", "company_name"],
			as_dict=True,
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"get_contact_salutation_full_name: Lookup von Contact {contact!r} fehlgeschlagen.",
		)
		row = None

	if row:
		salutation = (row.get("salutation") or "").strip()
		name = " ".join(
			part
			for part in (
				(row.get("first_name") or "").strip(),
				(row.get("last_name") or "").strip(),
			)
			if part
		).strip()
		if not name:
			name = (row.get("company_name") or "").strip()
		display = " ".join(part for part in (salutation, name) if part).strip()
		if display:
			return display

	return contact


def get_hauptmieter_salutation_full_names(rows: Iterable[object] | None) -> list[str]:
	"""Return 'salutation first last' for all Hauptmieter contacts."""
	names: list[str] = []
	seen: set[str] = set()
	for contact in get_hauptmieter_contacts(rows):
		name = sanitize_name_part(get_contact_salutation_full_name(contact))
		if name and name not in seen:
			names.append(name)
			seen.add(name)
	return names


def get_hauptmieter_salutation_full_display(rows: Iterable[object] | None) -> str:
	"""Return all Hauptmieter as a German natural-language list."""
	return join_german_name_list(get_hauptmieter_salutation_full_names(rows))


def get_hauptmieter_last_names(rows: Iterable[object] | None) -> list[str]:
	"""Return sanitized last names for all Hauptmieter contacts."""
	names: list[str] = []
	seen: set[str] = set()
	for contact in get_hauptmieter_contacts(rows):
		name = sanitize_name_part(get_contact_last_name(contact))
		if name and name not in seen:
			names.append(name)
			seen.add(name)
	return names


def get_hauptmieter_display_name(rows: Iterable[object] | None) -> str:
	"""Return a readable combined name for all Hauptmieter contacts."""
	parts: list[str] = []
	seen: set[str] = set()
	for contact in get_hauptmieter_contacts(rows):
		display = sanitize_name_part(get_contact_display_name(contact))
		if display and display not in seen:
			parts.append(display)
			seen.add(display)
	return ", ".join(parts)


def join_german_name_list(names: Iterable[str] | None) -> str:
	"""Join names as 'A', 'A und B' or 'A, B und C'."""
	parts = [name.strip() for name in (names or []) if name and name.strip()]
	if len(parts) <= 1:
		return parts[0] if parts else ""
	if len(parts) == 2:
		return " und ".join(parts)
	return f"{', '.join(parts[:-1])} und {parts[-1]}"


def sanitize_name_part(value: str | None) -> str:
	"""Prevent separators from leaking into DocName parts."""
	s = (value or "").strip()
	if not s:
		return ""
	s = s.replace("\t", " ").replace("|", "/")
	# Collapse spaces (but don't introduce tabs here).
	while "  " in s:
		s = s.replace("  ", " ")
	return s.strip()
