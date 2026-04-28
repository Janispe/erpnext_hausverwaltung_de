"""Eindeutigkeit von `konto` über die beiden Kostenart-Doctypes hinweg.

Ein Konto darf entweder in `Betriebskostenart` ODER in `Kostenart nicht umlagefaehig`
referenziert sein, niemals in beiden gleichzeitig oder mehrfach in einer der Listen.
Diese Invariante ermöglicht den Reverse-Lookup vom Konto zur Kostenart im Buchungs-
Cockpit.
"""

from __future__ import annotations

import frappe


BK_DOCTYPE = "Betriebskostenart"
KOSTENART_NICHT_UL_DOCTYPE = "Kostenart nicht umlagefaehig"


def assert_konto_unique(*, konto: str | None, doctype: str, name: str | None) -> None:
	"""Wirft, wenn `konto` schon in BK oder Kostenart-nicht-UL belegt ist.

	`doctype`/`name` identifizieren den aktuell gespeicherten Datensatz, der vom
	Vergleich ausgenommen wird.
	"""
	if not konto:
		return

	other_doctype = (
		KOSTENART_NICHT_UL_DOCTYPE if doctype == BK_DOCTYPE else BK_DOCTYPE
	)

	# Konflikt im selben Doctype (anderer Datensatz, gleiches Konto)?
	same_filters: dict = {"konto": konto}
	if name:
		same_filters["name"] = ["!=", name]
	conflict = frappe.db.get_value(doctype, same_filters, "name")
	if conflict:
		frappe.throw(
			f"Konto „{konto}“ ist bereits in {doctype} „{conflict}“ hinterlegt. "
			f"Ein Konto darf nur einmal als Kostenart referenziert werden."
		)

	# Konflikt im anderen Doctype?
	conflict = frappe.db.get_value(other_doctype, {"konto": konto}, "name")
	if conflict:
		frappe.throw(
			f"Konto „{konto}“ ist bereits in {other_doctype} „{conflict}“ hinterlegt. "
			f"Ein Konto kann entweder umlagefähig (Betriebskostenart) oder nicht "
			f"umlagefähig sein, nicht beides."
		)
