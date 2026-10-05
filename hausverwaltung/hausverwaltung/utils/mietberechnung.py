"""Shared, exact rent calculation for invoices, checks and the contract preview.

Monthly rates cover calendar days. An explicit fixed amount replaces the rent
for its inclusive interval; it is never added on top of the monthly rate.
Legacy fixed staffels remain readable until they have been migrated.
"""

from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from itertools import pairwise

import frappe
from frappe import _
from frappe.utils import getdate

AUTOMATIC = "Automatisch anteilig"
FIXED = "Festbetrag"
MONTHLY = "Monatlich"
LEGACY_FIXED = "Gesamter Zeitraum"
CENT = Decimal("0.01")


def _money(value, label: str, *, required: bool = False) -> Decimal:
	if value is None or value == "":
		if required:
			frappe.throw(_("Bitte {0} angeben; auch 0 € ist zulässig.").format(label))
		return Decimal(0)
	try:
		amount = Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError):
		frappe.throw(_("{0} muss ein gültiger Geldbetrag sein.").format(label))
	if not amount.is_finite() or amount < 0 or amount != amount.quantize(CENT):
		frappe.throw(
			_("{0} muss ein nicht negativer Betrag mit höchstens zwei Nachkommastellen sein.").format(label)
		)
	return amount


def _required_date(value, label: str) -> date:
	if not value:
		frappe.throw(_("Bitte {0} angeben.").format(label))
	try:
		parsed = getdate(value)
		if not isinstance(parsed, date):
			raise ValueError("invalid date")
		return parsed
	except (ValueError, TypeError):
		frappe.throw(_("{0} muss ein gültiges Datum sein.").format(label))


def validate_part_month_rows(von, bis, rows=None) -> list[dict]:
	"""Return normalized part-month rules; reject ambiguous or invalid intervals."""
	if rows and not von:
		frappe.throw(_("Für Teilmonatsregeln wird ein Vertragsbeginn benötigt."))
	contract_start = _required_date(von, _("Vertragsbeginn")) if von else None
	contract_end = _required_date(bis, _("Vertragsende")) if bis else None
	normalized = []
	for index, row in enumerate(rows or [], 1):
		start = _required_date(row.get("von"), _("Teilmonat {0}: Von").format(index))
		end = _required_date(row.get("bis"), _("Teilmonat {0}: Bis").format(index))
		if end < start:
			frappe.throw(_("Teilmonat {0}: Bis darf nicht vor Von liegen.").format(index))
		if (start.year, start.month) != (end.year, end.month):
			frappe.throw(_("Teilmonat {0} muss innerhalb eines Kalendermonats liegen.").format(index))
		if (contract_start and start < contract_start) or (contract_end and end > contract_end):
			frappe.throw(_("Teilmonat {0} liegt außerhalb des Mietvertrags.").format(index))
		mode = (row.get("berechnung") or AUTOMATIC).strip()
		if mode not in (AUTOMATIC, FIXED):
			frappe.throw(_("Teilmonat {0}: Unbekannte Berechnungsart.").format(index))
		amount = (
			_money(row.get("betrag"), _("Teilmonat {0}: Festbetrag").format(index), required=True)
			if mode == FIXED
			else Decimal(0)
		)
		normalized.append({"von": start, "bis": end, "berechnung": mode, "betrag": amount})
	normalized.sort(key=lambda row: (row["von"], row["bis"]))
	for previous, current in pairwise(normalized):
		if current["von"] <= previous["bis"]:
			frappe.throw(
				_("Teilmonatsregeln dürfen sich nicht überschneiden ({0} bis {1}).").format(
					current["von"], previous["bis"]
				)
			)
	return normalized


def _rent_rows(rows) -> list[dict]:
	normalized = []
	for index, row in enumerate(rows or [], 1):
		start = _required_date(row.get("von"), _("Mietstaffel {0}: Gültig ab").format(index))
		mode = (row.get("art") or MONTHLY).strip()
		if mode not in (MONTHLY, LEGACY_FIXED):
			frappe.throw(_("Mietstaffel {0}: Unbekannte Berechnungsart.").format(index))
		normalized.append(
			{
				"von": start,
				"art": mode,
				"miete": _money(row.get("miete"), _("Mietstaffel {0}: Betrag").format(index)),
			}
		)
	normalized.sort(key=lambda row: row["von"])
	for previous, current in pairwise(normalized):
		if previous["von"] == current["von"]:
			frappe.throw(
				_("Mietstaffeln benötigen unterschiedliche Startdaten ({0}).").format(current["von"])
			)
	return normalized


def validate_rent_rows(von, bis, miete_rows, teilmonat_rows=None) -> dict:
	"""Validate both tables, including legacy fixed intervals and their boundaries."""
	staffels = _rent_rows(miete_rows)
	rules = validate_part_month_rows(von, bis, teilmonat_rows)
	for rule in rules:
		active_rate = next((row for row in reversed(staffels) if row["von"] <= rule["von"]), None)
		if active_rate is None or active_rate["art"] != MONTHLY:
			frappe.throw(
				_(
					"Bitte zuerst eine reguläre Monatsmiete hinterlegen, die am Beginn der Teilmonatsregel ({0}) gilt. Auch 0 € ist zulässig."
				).format(rule["von"])
			)
	contract_end = getdate(bis) if bis else date.max
	for index, row in enumerate(staffels):
		if row["art"] != LEGACY_FIXED:
			continue
		next_start = staffels[index + 1]["von"] if index + 1 < len(staffels) else None
		row_end = next_start - timedelta(days=1) if next_start else contract_end
		if not next_start and not bis:
			row_end = _end_of_month(row["von"])
		if row_end < row["von"] or (row["von"].year, row["von"].month) != (row_end.year, row_end.month):
			frappe.throw(
				_(
					"Der bisherige Festbetrag ab {0} muss innerhalb eines Monats liegen (ermitteltes Ende: {1})."
				).format(row["von"], row_end)
			)
		if any(rule["von"] <= row_end and rule["bis"] >= row["von"] for rule in rules):
			frappe.throw(
				_(
					"Ein bisheriger Festbetrag und eine Teilmonatsregel dürfen denselben Zeitraum nicht abdecken."
				)
			)
	return {"miete": staffels, "miete_teilmonate": rules}


def _round_fraction(amount: Fraction, rounding_method: str) -> Decimal:
	"""Round an exact rational amount, including exact half-cent ties."""
	cents = amount * 100
	whole, remainder = divmod(cents.numerator, cents.denominator)
	comparison = remainder * 2 - cents.denominator
	if comparison > 0 or (comparison == 0 and (rounding_method == ROUND_HALF_UP or whole % 2)):
		whole += 1
	return Decimal(whole) / 100


def _rounding_mode(method: str | None) -> str:
	method = method or frappe.get_system_settings("rounding_method") or "Banker's Rounding (legacy)"
	if method in ("Commercial Rounding", "Banker's Rounding (legacy)", ROUND_HALF_UP):
		return ROUND_HALF_UP
	if method in ("Banker's Rounding", ROUND_HALF_EVEN):
		return ROUND_HALF_EVEN
	frappe.throw(_("Unbekannte Rundungsmethode: {0}.").format(method))


def _end_of_month(value: date) -> date:
	return value.replace(day=monthrange(value.year, value.month)[1])


def calculate_monthly_rent(
	von, bis, anchor, miete_rows, teilmonat_rows=None, *, rounding_method=None
) -> dict:
	"""Calculate rent once and return the same cent-safe breakdown for the UI.

	``von`` and ``bis`` are inclusive contract dates. Row inputs may be ordinary
	dicts or Frappe child documents. Legacy rows delimit one another regardless
	of their type, preventing a monthly rate from continuing through a fixed
	period. All intermediate amounts are rational; rounding happens only once
	for the total. Breakdown cents are reconciled to that total.
	"""
	month_start = getdate(anchor).replace(day=1)
	month_end = _end_of_month(month_start)
	days_in_month = month_end.day
	contract_start = getdate(von) if von else date(1900, 1, 1)
	contract_end = getdate(bis) if bis else date.max
	if contract_end < contract_start:
		frappe.throw(_("Das Vertragsende darf nicht vor dem Vertragsbeginn liegen."))
	validated = validate_rent_rows(von, bis, miete_rows, teilmonat_rows)
	staffels = validated["miete"]
	rules = validated["miete_teilmonate"]
	rounding = _rounding_mode(rounding_method)
	start, end = max(month_start, contract_start), min(month_end, contract_end)
	if start > end:
		return {"month": str(month_start), "amount": 0.0, "segments": []}

	segments = []
	for index, row in enumerate(staffels):
		next_start = staffels[index + 1]["von"] if index + 1 < len(staffels) else None
		row_end = next_start - timedelta(days=1) if next_start else contract_end
		if row["art"] == LEGACY_FIXED:
			# This is the historical meaning of an open-ended final fixed row.
			if not next_start and not bis:
				row_end = _end_of_month(row["von"])
		seg_start, seg_end = max(start, row["von"]), min(end, row_end)
		if seg_start > seg_end:
			continue
		if row["art"] == LEGACY_FIXED:
			segments.append(_segment(seg_start, seg_end, "Bisheriger Festbetrag", Fraction(row["miete"])))
			continue

		points = {seg_start, seg_end + timedelta(days=1)}
		for rule in rules:
			if rule["von"] <= seg_end and rule["bis"] >= seg_start:
				points.add(max(seg_start, rule["von"]))
				points.add(min(seg_end, rule["bis"]) + timedelta(days=1))
		points = sorted(points)
		for cut_start, cut_end_excl in pairwise(points):
			covering_rule = next((rule for rule in rules if rule["von"] <= cut_start <= rule["bis"]), None)
			if covering_rule and covering_rule["berechnung"] == FIXED:
				continue
			days = (cut_end_excl - cut_start).days
			amount = Fraction(row["miete"]) * days / days_in_month
			segments.append(
				_segment(cut_start, cut_end_excl - timedelta(days=1), AUTOMATIC, amount, row["miete"])
			)

	for rule in rules:
		if rule["berechnung"] == FIXED and start <= rule["von"] <= end:
			segments.append(_segment(rule["von"], rule["bis"], FIXED, Fraction(rule["betrag"])))

	segments.sort(key=lambda segment: (segment["von"], segment["bis"]))
	total = _round_fraction(sum((segment.pop("_exact") for segment in segments), Fraction(0)), rounding)
	# Preserve every agreed fixed amount exactly. Distribute rounded monthly
	# cents by fractional remainder, so the displayed sections add to the total
	# even when a half-even tie changes after adding an odd fixed cent.
	fixed_cents = 0
	monthly = []
	for index, segment in enumerate(segments):
		exact = segment.pop("_display_exact")
		if segment["monatsmiete"] is None:
			segment["betrag"] = float(exact)
			fixed_cents += int(exact * 100)
		else:
			cents = exact * 100
			whole, remainder = divmod(cents.numerator, cents.denominator)
			segment["betrag"] = whole
			monthly.append((index, Fraction(remainder, cents.denominator)))
	remaining = int(total * 100) - fixed_cents - sum(segments[index]["betrag"] for index, _ in monthly)
	for index, _remainder in sorted(monthly, key=lambda entry: (-entry[1], entry[0]))[:remaining]:
		segments[index]["betrag"] += 1
	for index, _remainder in monthly:
		segments[index]["betrag"] = float(Decimal(segments[index]["betrag"]) / 100)
	return {"month": str(month_start), "amount": float(total), "segments": segments}


def _segment(
	start: date, end: date, mode: str, amount: Fraction, monthly_rate: Decimal | None = None
) -> dict:
	return {
		"von": str(start),
		"bis": str(end),
		"berechnung": mode,
		"monatsmiete": float(monthly_rate) if monthly_rate is not None else None,
		"tage": (end - start).days + 1,
		"_exact": amount,
		"_display_exact": amount,
	}
