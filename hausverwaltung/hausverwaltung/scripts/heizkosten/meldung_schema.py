"""Versionierte, deklarative Zusatzfelder. Kein ausführbarer Vorlagencode."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

SCOPES = ("Meldung", "Nutzer", "Kosten", "Brennstoff")
TYPES = ("Data", "Small Text", "Date", "Int", "Float", "Currency", "Select")
FIELD_KEYS = (
	"schluessel",
	"bezeichnung",
	"bereich",
	"feldtyp",
	"pflichtfeld",
	"einheit",
	"abschnitt",
	"optionen",
	"standardwert",
	"folgejahr_uebernehmen",
	"hinweis",
)


def json_object(value):
	if not value:
		return {}
	try:
		result = json.loads(value) if isinstance(value, str) else value
	except (ValueError, TypeError) as exc:
		raise ValueError("Zusatzwerte müssen ein gültiges JSON-Objekt sein.") from exc
	if not isinstance(result, dict):
		raise ValueError("Zusatzwerte müssen ein JSON-Objekt sein.")
	return result


def dumps(value):
	return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def typed_value(definition, value):
	"""Leere Eingaben bleiben leer; eine echte 0 wird nicht als fehlend behandelt."""
	if value is None or value == "":
		return None
	typ = definition["feldtyp"]
	label = definition["bezeichnung"]
	if isinstance(value, (dict, list, bool)):
		raise ValueError(f"{label}: ungültiger Wert.")
	if typ in ("Float", "Currency", "Int"):
		try:
			number = Decimal(str(value))
		except InvalidOperation as exc:
			raise ValueError(f"{label}: Zahl erwartet (Dezimaltrennzeichen Punkt).") from exc
		if not number.is_finite() or abs(number) > Decimal("1000000000000"):
			raise ValueError(f"{label}: Zahl außerhalb des zulässigen Bereichs.")
		if typ == "Int":
			if number != number.to_integral_value():
				raise ValueError(f"{label}: ganze Zahl erwartet.")
			return int(number)
		if typ == "Currency":
			number = number.quantize(Decimal("0.01"))
		return float(number)
	value = str(value).strip()
	if not value:
		return None
	if len(value) > (4000 if typ == "Small Text" else 140):
		raise ValueError(f"{label}: Eingabe ist zu lang.")
	if typ == "Date":
		try:
			if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
				raise ValueError
			return date.fromisoformat(value).isoformat()
		except ValueError as exc:
			raise ValueError(f"{label}: gültiges Datum im Format JJJJ-MM-TT erwartet.") from exc
	if typ == "Select" and value not in definition["optionen"].splitlines():
		raise ValueError(f"{label}: Wert ist nicht in der Auswahlliste dieser Vorlagenversion.")
	return value


def normalize_definitions(rows):
	if len(rows) > 100:
		raise ValueError("Eine Vorlagenversion darf höchstens 100 Zusatzfelder enthalten.")
	result, keys, labels = [], set(), set()
	for row in rows:
		d = {key: row.get(key) if row.get(key) is not None else "" for key in FIELD_KEYS}
		for key in ("schluessel", "bezeichnung", "bereich", "feldtyp", "optionen"):
			d[key] = str(d[key]).strip()
		if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", d["schluessel"]):
			raise ValueError(
				"Feldschlüssel: Kleinbuchstaben, Ziffern und Unterstriche; Beginn mit Buchstabe."
			)
		if d["bereich"] not in SCOPES or d["feldtyp"] not in TYPES or not d["bezeichnung"]:
			raise ValueError("Zusatzfeld benötigt Bezeichnung, gültigen Bereich und Datentyp.")
		key, label = (d["bereich"], d["schluessel"]), (d["bereich"], d["bezeichnung"])
		if key in keys or label in labels:
			raise ValueError("Feldschlüssel und Bezeichnung müssen innerhalb eines Bereichs eindeutig sein.")
		keys.add(key)
		labels.add(label)
		options = [line.strip() for line in d["optionen"].splitlines() if line.strip()]
		if d["feldtyp"] == "Select" and (not options or len(options) != len(set(options))):
			raise ValueError(f"{d['bezeichnung']}: eindeutige Auswahlwerte erforderlich.")
		d["optionen"] = "\n".join(options)
		for key in ("pflichtfeld", "folgejahr_uebernehmen"):
			d[key] = int(bool(int(d[key] or 0)))
		d["standardwert"] = typed_value(d, d["standardwert"])
		result.append(d)
	return result


def normalize_values(definitions, scope, raw, *, required=False):
	values = json_object(raw)
	fields = {d["schluessel"]: d for d in definitions if d["bereich"] == scope}
	unknown = set(values) - fields.keys()
	if unknown:
		raise ValueError(f"{scope}: unbekannte Zusatzfelder: {', '.join(sorted(unknown))}")
	result, missing = {}, []
	for key, d in fields.items():
		value = typed_value(d, values.get(key))
		if value is not None:
			result[key] = value
		elif required and d["pflichtfeld"]:
			missing.append(d["bezeichnung"])
	return result, missing


def initial_values(definitions, scope, previous=None):
	old = json_object(previous)
	return {
		d["schluessel"]: old[d["schluessel"]]
		if d["folgejahr_uebernehmen"] and d["schluessel"] in old
		else d["standardwert"]
		for d in definitions
		if d["bereich"] == scope
		and (d["standardwert"] is not None or (d["folgejahr_uebernehmen"] and d["schluessel"] in old))
	}


def carry_values(old_definitions, new_definitions, scope, previous):
	"""Übernahme über Versionen nur bei kompatiblem Schlüssel und Datentyp."""
	old = {d["schluessel"]: d for d in old_definitions if d["bereich"] == scope}
	values = json_object(previous)
	result = initial_values(new_definitions, scope)
	for d in new_definitions:
		key = d["schluessel"]
		if d["bereich"] != scope or not d["folgejahr_uebernehmen"]:
			continue
		if key not in old or old[key]["feldtyp"] != d["feldtyp"]:
			continue
		try:
			value = typed_value(d, values.get(key))
		except ValueError:
			continue
		if value is not None:
			result[key] = value
	return result
