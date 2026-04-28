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
