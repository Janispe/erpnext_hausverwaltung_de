from __future__ import annotations

from collections.abc import Hashable, Iterable
from decimal import ROUND_HALF_UP, Decimal

import frappe

ROUNDING_METHOD_LARGEST_REMAINDER = "Größte-Rest-Methode"
ROUNDING_METHOD_ONLY = "Nur kaufmännisch runden"
ROUNDING_METHOD_TENANT_ONLY = "Kaufmännisch erst beim Mieter runden"
ROUNDING_METHOD_LEGACY = "Bisherige Restverteilung"
ROUNDING_METHODS = (
	ROUNDING_METHOD_LARGEST_REMAINDER,
	ROUNDING_METHOD_ONLY,
	ROUNDING_METHOD_TENANT_ONLY,
	ROUNDING_METHOD_LEGACY,
)
MONEY_QUANT = Decimal("0.01")


def get_bk_rounding_method() -> str:
	"""Liefert das konfigurierte Rundungsverfahren mit Legacy-Fallback."""
	try:
		value = frappe.db.get_single_value(
			"Hausverwaltung Einstellungen",
			"bk_rundungsverfahren",
		)
	except Exception:
		value = None
	return value if value in ROUNDING_METHODS else ROUNDING_METHOD_LEGACY


def round_money_allocations(
	entries: Iterable[tuple[Hashable, Decimal]],
	method: str,
	target_total: Decimal | None = None,
) -> dict[Hashable, Decimal]:
	"""Rundet Geldanteile und verteilt optional die Differenz zum Zielbetrag."""
	items = [(key, Decimal(str(raw))) for key, raw in entries]
	if not items:
		return {}
	if method == ROUNDING_METHOD_TENANT_ONLY:
		# Die Wohnungsanteile bleiben exakt, damit erst die endgültigen
		# Kostenpositionen des Mieters auf Cent gerundet werden.
		return dict(items)

	rounded = {key: _round_money(raw) for key, raw in items}
	if method == ROUNDING_METHOD_ONLY:
		return rounded

	target = _round_money(
		target_total if target_total is not None else sum((raw for _key, raw in items), Decimal("0"))
	)
	diff = target - sum(rounded.values(), Decimal("0"))
	if diff == 0:
		return rounded

	if method == ROUNDING_METHOD_LARGEST_REMAINDER:
		return _distribute_by_largest_remainder(items, rounded, diff)

	# Prefer the historically largest share, but never turn positive costs
	# into a credit (or a credit into costs) just to reconcile rounded cents.
	priority = sorted(items, key=lambda item: (item[1].copy_abs(), str(item[0])), reverse=True)
	return reconcile_rounding_difference(priority, rounded, diff)


def reconcile_rounding_difference(
	items: Iterable[tuple[Hashable, Decimal]],
	rounded: dict[Hashable, Decimal],
	diff: Decimal,
) -> dict[Hashable, Decimal]:
	"""Reconcile cents in priority order without crossing an original sign."""
	for key, raw in items:
		if not diff:
			break
		if not raw:
			continue
		adjustment = diff
		if (rounded[key] + adjustment) * raw < 0:
			adjustment = -rounded[key]
		rounded[key] += adjustment
		diff -= adjustment
	if diff:
		frappe.throw("Die Rundungsdifferenz kann ohne Vorzeichenwechsel nicht verteilt werden.")
	return rounded


def _distribute_by_largest_remainder(
	items: list[tuple[Hashable, Decimal]],
	rounded: dict[Hashable, Decimal],
	diff: Decimal,
) -> dict[Hashable, Decimal]:
	step = MONEY_QUANT if diff > 0 else -MONEY_QUANT
	# Bei positivem Diff zuerst die am stärksten abgerundeten Werte, bei
	# negativem Diff zuerst die am stärksten aufgerundeten Werte korrigieren.
	ranked = sorted(
		items,
		key=lambda item: (
			-(item[1] - rounded[item[0]]) if diff > 0 else item[1] - rounded[item[0]],
			str(item[0]),
		),
	)
	cent_count = int((diff.copy_abs() / MONEY_QUANT).to_integral_value())
	for index in range(cent_count):
		key = ranked[index % len(ranked)][0]
		rounded[key] += step
	return rounded


def _round_money(value: Decimal) -> Decimal:
	return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
