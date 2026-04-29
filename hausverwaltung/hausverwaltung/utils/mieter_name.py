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

	# 3) First row at all
	first = rows_list[0]
	mieter = _get(first, "mieter")
	return mieter or None


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
		row = None

	if row:
		parts = [(row.get("last_name") or "").strip(), (row.get("first_name") or "").strip()]
		display = " ".join(part for part in parts if part)
		if display:
			return display

	return contact


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
