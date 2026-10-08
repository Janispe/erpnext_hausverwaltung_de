"""Readable titles for document IDs shown to people.

Document IDs such as ``MV-00012``, ``DEB-00034`` or ``WHG-00007`` are stable
identities, not labels. Wherever a page, report or message shows such an ID,
it resolves the document's title here and shows that instead; the ID remains
the link target and the value used by the business logic.

Voucher numbers (Sales Invoice, Payment Entry, ...) are their own readable
identifier and are therefore returned unchanged.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

import frappe

# The ID is the meaningful identifier for these doctypes; their title field is
# usually just a copy of the party name and would hide the voucher number.
ID_IS_TITLE_DOCTYPES = frozenset(
	{
		"Sales Invoice",
		"Purchase Invoice",
		"Payment Entry",
		"Journal Entry",
		"Delivery Note",
		"Sales Order",
		"Purchase Order",
		"Purchase Receipt",
		"Stock Entry",
		"Quotation",
		"Material Request",
		"Dunning",
	}
)


def title_field_for(doctype: str | None) -> str | None:
	"""Return the field holding a readable title, or None if the ID is the label."""
	if not doctype or doctype in ID_IS_TITLE_DOCTYPES:
		return None
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return None
	field = (meta.title_field or "").strip()
	if not field or field == "name" or not meta.get_field(field):
		return None
	return field


def get_titles(doctype: str | None, names: Iterable[str | None]) -> dict[str, str]:
	"""Titles of the given documents in one query; documents without a title are omitted."""
	field = title_field_for(doctype)
	ids = sorted({name for name in names if name})
	if not field or not ids:
		return {}
	rows = frappe.get_all(
		doctype,
		filters={"name": ["in", ids]},
		fields=["name", field],
		limit_page_length=0,
	)
	titles = {}
	for row in rows:
		title = " ".join(str(row.get(field) or "").split())
		if title:
			titles[row.name] = title
	return titles


def title_of(doctype: str | None, name: str | None) -> str:
	"""Readable title of one document, falling back to its ID."""
	if not name:
		return ""
	return get_titles(doctype, [name]).get(name) or name


def label_with_id(doctype: str | None, name: Any) -> str:
	"""``Title (ID)`` for messages where the exact record must stay traceable.

	Safe in error paths: non-text values are returned as text, lookups that
	fail fall back to the plain ID.
	"""
	if name is None or name == "":
		return ""
	if not isinstance(name, str):
		return str(name)
	try:
		title = title_of(doctype, name)
	except Exception:
		return name
	return f"{title} ({name})" if title != name else name


def wohnung_position(values: Mapping[str, Any]) -> tuple[str, str]:
	"""``("VH", "EG links")`` from an apartment's building part and position.

	Imported positions often repeat the building part ("Vorderhaus, EG links");
	it is shown once, as standard abbreviation.
	"""
	from hausverwaltung.hausverwaltung.utils.gebaeudeteil import (
		normalize_gebaeudeteil_to_standard,
		split_lage_gebaeudeteil,
	)

	raw_teil = (values.get("gebaeudeteil") or "").strip()
	lage = " ".join(str(values.get("name__lage_in_der_immobilie") or "").split())
	lage_teil, rest = split_lage_gebaeudeteil(lage)
	teil = normalize_gebaeudeteil_to_standard(raw_teil) or raw_teil or lage_teil or ""
	if lage_teil and rest and (not raw_teil or lage_teil == teil):
		lage = rest
	return teil, lage


def wohnung_position_label(values: Mapping[str, Any]) -> str:
	"""``VH · EG links``."""
	return " · ".join(part for part in wohnung_position(values) if part)


def property_label(immobilie: str | None) -> str:
	"""Street and house number of a property, falling back to its title."""
	if not immobilie:
		return ""
	values = (
		frappe.db.get_value(
			"Immobilie", immobilie, ["adresse", "adresse_titel", "bezeichnung", "objekt"], as_dict=True
		)
		or {}
	)
	street = frappe.db.get_value("Address", values.get("adresse"), "address_line1") if values.get("adresse") else ""
	# Imported streets sometimes lack the space before the house number.
	street = re.sub(r"(?<=[A-Za-zÄÖÜäöüß.])(?=\d)", " ", " ".join(str(street or "").split()))
	return street or values.get("adresse_titel") or values.get("bezeichnung") or values.get("objekt") or immobilie


def apartment_location(wohnung: str | None) -> dict[str, str]:
	"""``{"objekt": "Musterstr. 1", "einheit": "VH · EG links"}`` of an apartment."""
	values = (
		frappe.db.get_value(
			"Wohnung", wohnung, ["immobilie", "gebaeudeteil", "name__lage_in_der_immobilie"], as_dict=True
		)
		if wohnung
		else None
	) or {}
	return {
		"objekt": property_label(values.get("immobilie")),
		"einheit": wohnung_position_label(values) or title_of("Wohnung", wohnung),
	}


def add_titles(
	rows: Iterable[dict[str, Any]] | None,
	fields: Mapping[str, str],
	*,
	suffix: str = "_title",
) -> None:
	"""Write ``<field><suffix>`` into each row for the given ``{field: doctype}`` map.

	A doctype starting with ``@`` names the row field holding the doctype
	(Dynamic Link), e.g. ``{"party": "@party_type"}``. Existing values win.
	"""
	rows = [row for row in (rows or []) if row is not None]
	if not rows:
		return
	for fieldname, target in fields.items():
		names_by_doctype: dict[str, set[str]] = {}
		for row in rows:
			doctype = row.get(target[1:]) if target.startswith("@") else target
			if doctype and row.get(fieldname):
				names_by_doctype.setdefault(doctype, set()).add(row.get(fieldname))
		titles = {doctype: get_titles(doctype, names) for doctype, names in names_by_doctype.items()}
		key = f"{fieldname}{suffix}"
		for row in rows:
			if row.get(key):
				continue
			name = row.get(fieldname)
			doctype = row.get(target[1:]) if target.startswith("@") else target
			if name:
				row[key] = titles.get(doctype, {}).get(name) or name


def send_titles(pairs: Iterable[tuple[str | None, str | None]]) -> None:
	"""Hand titles to Frappe's client cache so standard link formatting shows them."""
	names_by_doctype: dict[str, set[str]] = {}
	for doctype, name in pairs:
		if doctype and name:
			names_by_doctype.setdefault(doctype, set()).add(name)
	link_titles = {
		f"{doctype}::{name}": title
		for doctype, names in names_by_doctype.items()
		for name, title in get_titles(doctype, names).items()
	}
	response = getattr(frappe.local, "response", None)
	if link_titles and response is not None:
		response.setdefault("_link_titles", {}).update(link_titles)


# Row keys that hold IDs of the doctypes with short document numbers.
PAYLOAD_LINK_KEYS = {
	"mietvertrag": "Mietvertrag",
	"wohnung": "Wohnung",
	"immobilie": "Immobilie",
	"customer": "Customer",
	"kunde": "Customer",
	"zaehler": "Zaehler",
	"kreditvertrag": "Kreditvertrag",
}


def send_payload_titles(payload: Any, keys: Mapping[str, str] = PAYLOAD_LINK_KEYS) -> Any:
	"""Send titles for all known ID keys found in a nested API payload; returns it unchanged."""
	pairs: list[tuple[str, str]] = []
	stack = [payload]
	while stack and len(pairs) < 20000:
		value = stack.pop()
		if isinstance(value, Mapping):
			for key, item in value.items():
				if key in keys and isinstance(item, str):
					pairs.append((keys[key], item))
				elif isinstance(item, (Mapping, list, tuple)):
					stack.append(item)
		elif isinstance(value, (list, tuple)):
			stack.extend(item for item in value if isinstance(item, (Mapping, list, tuple)))
	send_titles(pairs)
	return payload


def with_display_titles(fn):
	"""Decorator for whitelisted endpoints: send titles for IDs in the returned payload."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		return send_payload_titles(fn(*args, **kwargs))

	return wrapper


def send_report_titles(columns: Iterable[dict[str, Any]] | None, rows: Iterable[Any] | None) -> None:
	"""Send titles for all Link and Dynamic Link columns of a report result."""
	rows = [row for row in (rows or []) if isinstance(row, dict)]
	pairs = []
	for column in columns or []:
		if not isinstance(column, dict) or not column.get("fieldname") or not column.get("options"):
			continue
		fieldname = column["fieldname"]
		if column.get("fieldtype") == "Link":
			pairs.extend((column["options"], row.get(fieldname)) for row in rows)
		elif column.get("fieldtype") == "Dynamic Link":
			pairs.extend((row.get(column["options"]), row.get(fieldname)) for row in rows)
	send_titles(pairs)


@frappe.whitelist()
def get_display_titles(items: str | dict | None = None) -> dict[str, dict[str, str]]:
	"""``{doctype: [names]}`` → ``{doctype: {name: title}}`` for desk pages."""
	if isinstance(items, str):
		items = json.loads(items or "{}")
	result = {}
	for doctype, names in (items or {}).items():
		if not isinstance(names, list) or not frappe.has_permission(doctype, "read"):
			continue
		result[doctype] = get_titles(doctype, names[:5000])
	return result
