from __future__ import annotations

from typing import Optional, Set

import frappe
from frappe import _
from frappe.model.document import Document


ART_BOOLEAN = "Boolean"
ART_FLOAT = "Gleitkommazahl"
ART_INT = "Natürliche Zahl"
NUMERIC_ARTS = {ART_FLOAT, ART_INT}

REFERENZQUELLE_NONE = "Keine"
REFERENZQUELLE_WOHNUNGSZUSTAND = "Wohnungszustand-Feld"
REFERENZQUELLE_SCHLUESSEL = "Zustandsschluessel"

SUPPORTED_WOHNUNGSZUSTAND_FIELDS = {"größe": ART_FLOAT}


def _zustand_am(wohnung: str, stichtag: str) -> Optional[str]:
	rows = frappe.get_all(
		"Wohnungszustand",
		filters={"wohnung": wohnung, "ab": ("<=", stichtag), "docstatus": ("!=", 2)},
		fields=["name"],
		order_by="ab desc",
		limit=1,
	)
	return rows[0].name if rows else None


def _get_override_value(zustand: str, schluessel: str, art: str):
	if art == ART_BOOLEAN:
		rows = frappe.get_all(
			"ZustandsschluesselBooleanRow",
			filters={"parent": zustand, "zustandsschluessel": schluessel},
			fields=["wert_bool"],
			limit=1,
		)
		if not rows:
			return None
		return 1.0 if rows[0].get("wert_bool") else 0.0

	if art == ART_FLOAT:
		rows = frappe.get_all(
			"ZustandsschluesselFloatRow",
			filters={"parent": zustand, "zustandsschluessel": schluessel},
			fields=["wert_float"],
			limit=1,
		)
		if not rows:
			return None
		value = rows[0].get("wert_float")
		return None if value in (None, "") else float(value)

	if art == ART_INT:
		rows = frappe.get_all(
			"ZustandsschluesselIntRow",
			filters={"parent": zustand, "zustandsschluessel": schluessel},
			fields=["wert_int"],
			limit=1,
		)
		if not rows:
			return None
		value = rows[0].get("wert_int")
		return None if value in (None, "") else float(value)

	return None


def _resolve_field_default(zustand: str, feldname: str) -> float:
	if feldname not in SUPPORTED_WOHNUNGSZUSTAND_FIELDS:
		return 0.0
	value = frappe.db.get_value("Wohnungszustand", zustand, feldname)
	if value in (None, ""):
		return 0.0
	return float(value)


def get_effective_zustandsschluessel_value(
	wohnung: str,
	stichtag: str,
	schluessel: str,
	visited: Optional[Set[str]] = None,
) -> float:
	meta = frappe.db.get_value(
		"Zustandsschluessel",
		schluessel,
		["art", "referenzquelle", "wohnungszustand_feld", "referenz_zustandsschluessel"],
		as_dict=True,
	)
	if not meta:
		return 0.0

	art = meta.get("art")
	zustand = _zustand_am(wohnung, stichtag)
	if zustand:
		override = _get_override_value(zustand, schluessel, art)
		if override is not None:
			return float(override)

	referenzquelle = meta.get("referenzquelle") or REFERENZQUELLE_NONE
	if referenzquelle == REFERENZQUELLE_NONE or art not in NUMERIC_ARTS or not zustand:
		return 0.0

	if referenzquelle == REFERENZQUELLE_WOHNUNGSZUSTAND:
		return _resolve_field_default(zustand, meta.get("wohnungszustand_feld"))

	if referenzquelle == REFERENZQUELLE_SCHLUESSEL:
		referenz = meta.get("referenz_zustandsschluessel")
		if not referenz:
			return 0.0
		seen = set(visited or set())
		if schluessel in seen:
			return 0.0
		seen.add(schluessel)
		return get_effective_zustandsschluessel_value(wohnung, stichtag, referenz, seen)

	return 0.0


def _validate_reference_chain(name: str, visited: Optional[Set[str]] = None) -> None:
	seen = set(visited or set())
	if name in seen:
		raise frappe.ValidationError(_("Zyklische Referenz zwischen Zustandsschlüsseln ist nicht erlaubt."))
	seen.add(name)

	meta = frappe.db.get_value(
		"Zustandsschluessel",
		name,
		["referenzquelle", "referenz_zustandsschluessel"],
		as_dict=True,
	)
	if not meta:
		return
	if meta.get("referenzquelle") != REFERENZQUELLE_SCHLUESSEL:
		return
	next_name = meta.get("referenz_zustandsschluessel")
	if not next_name:
		return
	_validate_reference_chain(next_name, seen)


class Zustandsschluessel(Document):
	def validate(self):
		self._validate_reference_settings()
		self._validate_reference_cycle()

	def _validate_reference_settings(self) -> None:
		source = self.referenzquelle or REFERENZQUELLE_NONE
		self.referenzquelle = source

		if self.art != ART_FLOAT and source != REFERENZQUELLE_NONE:
			frappe.throw(_("Referenzquellen sind in v1 nur für Zustandsschlüssel vom Typ 'Gleitkommazahl' erlaubt."))

		if source == REFERENZQUELLE_NONE:
			self.wohnungszustand_feld = None
			self.referenz_zustandsschluessel = None
			return

		if source == REFERENZQUELLE_WOHNUNGSZUSTAND:
			if not self.wohnungszustand_feld:
				frappe.throw(_("Bitte ein Wohnungszustand-Feld als Referenz auswählen."))
			if self.wohnungszustand_feld not in SUPPORTED_WOHNUNGSZUSTAND_FIELDS:
				frappe.throw(_("Das ausgewählte Wohnungszustand-Feld wird als Referenzquelle noch nicht unterstützt."))
			required_art = SUPPORTED_WOHNUNGSZUSTAND_FIELDS[self.wohnungszustand_feld]
			if self.art != required_art:
				frappe.throw(_("Das ausgewählte Wohnungszustand-Feld ist nicht kompatibel mit der Art dieses Zustandsschlüssels."))
			self.referenz_zustandsschluessel = None
			return

		if source == REFERENZQUELLE_SCHLUESSEL:
			if not self.referenz_zustandsschluessel:
				frappe.throw(_("Bitte einen Referenz-Zustandsschlüssel auswählen."))
			if self.referenz_zustandsschluessel == self.name:
				frappe.throw(_("Ein Zustandsschlüssel darf nicht auf sich selbst verweisen."))
			ref_art = frappe.db.get_value("Zustandsschluessel", self.referenz_zustandsschluessel, "art")
			if ref_art not in NUMERIC_ARTS:
				frappe.throw(_("Es dürfen nur numerische Zustandsschlüssel referenziert werden."))
			self.wohnungszustand_feld = None
			return

		frappe.throw(_("Unbekannte Referenzquelle für Zustandsschlüssel."))

	def _validate_reference_cycle(self) -> None:
		if (self.referenzquelle or REFERENZQUELLE_NONE) != REFERENZQUELLE_SCHLUESSEL:
			return
		if not self.referenz_zustandsschluessel:
			return
		_validate_reference_chain(self.referenz_zustandsschluessel, {self.name})
