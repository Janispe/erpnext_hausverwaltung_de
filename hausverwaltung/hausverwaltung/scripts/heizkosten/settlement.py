"""Settlement-Logik für ``Heizkostenabrechnung Mieter``.

Erzeugt beim Submit der HK-Abrechnung automatisch eine Sales Invoice
(Nachzahlung) bzw. Credit Note (Guthaben) für die Differenz zwischen den
tatsächlich abgerechneten Wärmedienst-Kosten und der Vorauszahlung des Mieters.

Diese Variante ist bewusst **deutlich einfacher** als das BK-Pendant
([`abrechnung_erstellen.create_bk_settlement_documents`](../betriebskosten/abrechnung_erstellen.py)):

- Keine Konsolidierung offener Alt-Rechnungen via Journal Entry — HK hat
  keine vergleichbare Outstanding-Anteile-Logik. Wenn der Mieter HK-Vorauszahlungen
  schuldet, läuft das über das normale Mahnwesen, nicht über die Abrechnung.
- Keine ``before_insert``-Sperre: Anlage erfolgt direkt vom Hausverwalter,
  nicht über einen Immobilien-Parent.

Wir nutzen die existierenden, gut getesteten Helper aus dem BK-Modul direkt
(``_make_sales_invoice``, ``_run_settlement_selfcheck``, ``_ensure_item_with_income``,
``_get_default_company``, ``_get_customer_for_mietvertrag``) — kein
Code-Duplikat.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

import frappe
from frappe.utils import cstr

from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	MONEY_QUANT,
	_ensure_item_with_income,
	_get_customer_for_mietvertrag,
	_get_default_company,
	_make_sales_invoice,
	_quantize_money,
	_run_settlement_selfcheck,
	_to_decimal,
)


@frappe.whitelist()
def create_hk_settlement_documents(abrechnung: str) -> dict:
	"""Erzeugt Nachzahlung (SI) oder Guthaben (Credit Note) für eine HK-Abrechnung.

	Args:
		abrechnung: Name der ``Heizkostenabrechnung Mieter``.

	Returns:
		Dict ``{"created": {sales_invoice, credit_note, note}, "differenz": float}``.
	"""
	doc = frappe.get_doc("Heizkostenabrechnung Mieter", abrechnung)
	customer = doc.customer or _get_customer_for_mietvertrag(doc.mietvertrag)
	if not customer:
		frappe.throw("Kein Mieter (Customer) auf dem Mietvertrag gefunden.")

	posting_date = cstr(doc.bis or doc.datum or frappe.utils.today())

	# Differenz: Kosten Wärmedienst − Vorauszahlung des Mieters
	try:
		kosten = _to_decimal(doc.kosten_gesamt)
		vor = _to_decimal(doc.vorauszahlungen)
		diff = _quantize_money(kosten - vor)
	except Exception:
		diff = Decimal("0")

	# Selfcheck wirft bei fehlendem Setup einen aussagekräftigen Fehler
	# (Customer, Receivable Account, Items mit Income Defaults).
	_run_settlement_selfcheck(doc)
	company = _get_default_company()

	# Items idempotent anlegen (HK Nachzahlung / HK Guthaben)
	code_nach = _ensure_item_with_income("HK Nachzahlung", "Heizkosten Nachzahlung", company)
	code_guth = _ensure_item_with_income("HK Guthaben", "Heizkosten Guthaben", company)

	created: Dict[str, Optional[str]] = {"sales_invoice": None, "credit_note": None}

	if diff > MONEY_QUANT:
		try:
			si_name = _make_sales_invoice(
				customer,
				posting_date,
				code_nach,
				diff,
				is_return=0,
				do_submit=True,
				company=company,
			)
		except Exception as e:
			frappe.throw(f"HK-Nachzahlung konnte nicht erstellt werden: {e}")
		created["sales_invoice"] = si_name
	elif diff < -MONEY_QUANT:
		diff_abs = diff.copy_abs()
		try:
			cn_name = _make_sales_invoice(
				customer,
				posting_date,
				code_guth,
				diff_abs,
				is_return=1,
				do_submit=True,
				company=company,
			)
		except Exception as e:
			frappe.throw(f"HK-Guthaben konnte nicht erstellt werden: {e}")
		created["credit_note"] = cn_name
	else:
		# differenz ≈ 0 → nur Comment, kein Beleg
		doc.add_comment("Comment", text="HK-Abrechnung ist ausgeglichen — kein Ausgleichsbeleg nötig.")
		created["note"] = "ausgeglichen"

	# Verknüpfungen am Doc speichern (read-only Felder via db_set, da das Doc
	# zu diesem Zeitpunkt schon submittet ist).
	updates: Dict[str, Any] = {}
	if created.get("sales_invoice"):
		updates["sales_invoice"] = created["sales_invoice"]
	if created.get("credit_note"):
		updates["credit_note"] = created["credit_note"]
	if updates:
		try:
			doc.db_set(updates)
		except Exception:
			# Verknüpfung optional — bei Fehler nicht blockieren
			pass

	return {"created": created, "differenz": float(diff)}
