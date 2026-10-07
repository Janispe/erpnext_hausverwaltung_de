"""Immutable document numbers; human-readable context belongs in title fields.

The Frappe series counter is locked in the same transaction as the insert.
Existing names (including imports and amendments) are never renamed here.
"""

from __future__ import annotations

import re

import frappe
from frappe.model.naming import make_autoname
from frappe.utils import getdate, nowdate

# Prefix, annual counter. Accounting vouchers keep ERPNext's own naming rules.
DOCUMENT_SERIES = {
	"Immobilie": ("IMM", False),
	"Wohnung": ("WHG", False),
	"Mietvertrag": ("MV", False),
	"Customer": ("DEB", False),
	"Zaehler": ("ZAE", False),
	"Zaehler Zuordnung": ("ZAZ", False),
	"Wohnungszustand": ("WZS", False),
	"Mietvertragsbuilder": ("MVB", False),
	"Betriebskosten rechnung": ("BKR", False),
	"Bankauszug Import": ("BAI", False),
	"Kreditvertrag": ("KV", False),
	"Hausverwaltung Problem": ("PROB", True),
	"Einnahmen Ueberschuss Rechnung": ("EUER", True),
	"Betriebskostenabrechnung Immobilie": ("BKAI", True),
	"Betriebskostenabrechnung Mieter": ("BKAM", True),
	"Heizkostenabrechnung Immobilie": ("HKAI", True),
	"Heizkostenabrechnung Mieter": ("HKAM", True),
}


def series_prefix(doctype: str, year: int | None = None) -> str:
	prefix, annual = DOCUMENT_SERIES[doctype]
	if annual:
		prefix = f"{prefix}-{year or getdate(nowdate()).year}"
	return f"{prefix}-"


def make_document_name(doctype: str) -> str:
	"""Allocate a fresh number, tolerating legacy imports with an unseeded counter."""
	prefix = series_prefix(doctype)
	# A prefix for a future calendar year might not exist yet. The upsert locks
	# its row before Frappe's getseries SELECT/INSERT, including concurrent first use.
	frappe.db.sql(
		"INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, 0) "
		"ON DUPLICATE KEY UPDATE `name` = VALUES(`name`)",
		(prefix,),
	)
	while True:
		candidate = make_autoname(f"{prefix}.#####")
		if not frappe.db.exists(doctype, candidate, cache=False):
			return candidate


def set_document_name(doc, method: str | None = None) -> None:
	"""Autoname hook for simple controllers without their own naming behavior."""
	if not doc.get("amended_from"):
		doc.name = make_document_name(doc.doctype)


def existing_series_numbers(doctype: str, names: list[str]) -> dict[str, int]:
	"""Find counter floors, including amendment names, without parsing human labels."""
	prefix, annual = DOCUMENT_SERIES[doctype]
	year_part = r"(?P<year>\d{4})-" if annual else ""
	# New numbers have at least five digits. Frappe amendments are unpadded
	# positive integers; legacy KV/BAI names end in a padded four-digit counter.
	# Treating that old external contract number as our counter can overflow Series.
	pattern = re.compile(rf"^{re.escape(prefix)}-{year_part}(?P<number>\d{{5,}})(?:-[1-9]\d*)?$")
	floors: dict[str, int] = {}
	for name in names:
		match = pattern.fullmatch(name)
		if match:
			year = int(match.group("year")) if annual else None
			key = series_prefix(doctype, year)
			floors[key] = max(floors.get(key, 0), int(match.group("number")))
	return floors


def seed_document_series() -> dict[str, int]:
	"""Advance counters to existing numbers; never lower an already used counter."""
	seeded = {}
	for doctype in DOCUMENT_SERIES:
		if not frappe.db.exists("DocType", doctype):
			continue
		names = frappe.get_all(doctype, pluck="name", limit_page_length=0)
		floors = existing_series_numbers(doctype, names)
		floors.setdefault(series_prefix(doctype), 0)
		for key, floor in floors.items():
			# Atomic upsert also creates an empty series before concurrent first inserts.
			frappe.db.sql(
				"INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, %s) "
				"ON DUPLICATE KEY UPDATE `current` = GREATEST(COALESCE(`current`, 0), VALUES(`current`))",
				(key, floor),
			)
			seeded[key] = floor
	return seeded
