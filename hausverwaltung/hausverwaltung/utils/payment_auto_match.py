"""Auto-Matching von Bank Transactions gegen offene Rechnungen.

Versucht für eine Bank Transaction (mit gesetzter Party) eine exakte
Zuordnung zu offenen Sales/Purchase Invoices zu finden und legt — bei
Erfolg — ein passendes Payment Entry an, das gegen die Bank Transaction
reconciled wird.

Strategien (in dieser Reihenfolge, jeweils mit Toleranz ≤ 0,01 €):

1. **Single match** — eine offene Rechnung mit ``outstanding_amount`` =
   Bank-Betrag.
2. **Monats-Summe** — alle offenen Rechnungen der Party im selben
   Kalendermonat (posting_date) summieren sich auf den Bank-Betrag.
   Deckt den Mieten-Standardfall ab (Miete + NK + HK = 1 Überweisung).
3. **Gesamt-Summe** — alle offenen Rechnungen der Party summiert sind
   exakt der Bank-Betrag (z.B. zwei aufgelaufene Monatsmieten in einer
   Überweisung).

Kein Auto-Match bei Teilzahlungen, ungleichen Beträgen oder Subset-Sum-
Kombinationen. Die Bank Transaction bleibt dann unreconciled und der
User kann manuell zuordnen.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import frappe
from frappe.utils import flt, getdate


_TOLERANCE = 0.01


def auto_match_bank_transaction(bt_name: str) -> dict[str, Any]:
	"""Hauptentry-Point: versucht eine Bank Transaction automatisch zuzuordnen.

	Idempotent — wenn die BT bereits ``payment_entries`` hat (status =
	Reconciled / Partially Reconciled), wird nichts gemacht.

	Returns ein Dict mit:
	    matched: bool
	    payment_entry: Name des erstellten PE (oder None)
	    invoices: Liste der zugeordneten Rechnungen
	    strategy: 'single' | 'month_<key>' | 'all'
	    reason: maschinen-lesbarer Grund bei kein Match
	    message: kurze deutsche Zusammenfassung für UI
	"""
	bt = frappe.get_doc("Bank Transaction", bt_name)

	# Idempotenz: bereits zugeordnet?
	if bt.get("payment_entries"):
		return {
			"matched": False,
			"reason": "already_reconciled",
			"message": "Bereits zugeordnet",
		}

	if not bt.party_type or not bt.party:
		return {
			"matched": False,
			"reason": "no_party",
			"message": "Keine Party an Bank Transaction",
		}

	if bt.party_type not in ("Customer", "Supplier"):
		return {
			"matched": False,
			"reason": "unsupported_party_type",
			"message": f"Party-Typ '{bt.party_type}' nicht unterstützt",
		}

	deposit = flt(bt.deposit)
	withdrawal = flt(bt.withdrawal)

	if bt.party_type == "Customer":
		if deposit <= 0:
			return {
				"matched": False,
				"reason": "wrong_direction_for_customer",
				"message": "Customer aber kein Eingang — übersprungen",
			}
		target_amount = deposit
		invoice_doctype = "Sales Invoice"
		party_field = "customer"
	else:  # Supplier
		if withdrawal <= 0:
			return {
				"matched": False,
				"reason": "wrong_direction_for_supplier",
				"message": "Supplier aber kein Ausgang — übersprungen",
			}
		target_amount = withdrawal
		invoice_doctype = "Purchase Invoice"
		party_field = "supplier"

	# Offene Rechnungen abfragen
	candidates = frappe.get_all(
		invoice_doctype,
		filters={
			party_field: bt.party,
			"docstatus": 1,
			"outstanding_amount": [">", 0.001],
		},
		fields=["name", "outstanding_amount", "posting_date"],
		order_by="posting_date asc",
	)

	if not candidates:
		return {
			"matched": False,
			"reason": "no_open_invoices",
			"message": f"Keine offenen {invoice_doctype}s für {bt.party}",
		}

	# Bei Lieferanten-Auto-Match: Kostenstelle muss zur Bank-Transaction-Immobilie
	# passen, sonst würde Bank von Immobilie A eine Rechnung für Immobilie B
	# bezahlen. Bei Customers (Mieter) ist die IBAN-Zuordnung schon eindeutig
	# genug — kein Filter dort.
	expected_cc = _resolve_expected_cost_center_for_bt(bt) if bt.party_type == "Supplier" else None
	if expected_cc:
		filtered = []
		for inv in candidates:
			inv_cc = _get_cost_center_of_invoice(inv["name"], invoice_doctype)
			if inv_cc and inv_cc == expected_cc:
				filtered.append(inv)
		if not filtered:
			return {
				"matched": False,
				"reason": "no_matching_cost_center",
				"message": (
					f"{len(candidates)} offene Rechnung(en) für {bt.party}, "
					f"aber keine mit Kostenstelle '{expected_cc}' — manuell prüfen."
				),
			}
		candidates = filtered

	# Strategy 1: Single invoice exact
	for inv in candidates:
		if abs(flt(inv.outstanding_amount) - target_amount) < _TOLERANCE:
			return _do_match(bt, [inv], invoice_doctype, "single", target_amount)

	# Strategy 2: Same posting month sum
	by_month: dict[tuple[int, int], list] = defaultdict(list)
	for inv in candidates:
		if inv.posting_date:
			d = getdate(inv.posting_date)
			by_month[(d.year, d.month)].append(inv)

	for month_key, invs in by_month.items():
		if len(invs) < 2:
			continue  # bereits durch Strategy 1 abgedeckt
		total = sum(flt(i.outstanding_amount) for i in invs)
		if abs(total - target_amount) < _TOLERANCE:
			label = f"month_{month_key[0]}-{month_key[1]:02d}"
			return _do_match(bt, invs, invoice_doctype, label, target_amount)

	# Strategy 3: All open invoices sum
	if len(candidates) >= 2:
		total = sum(flt(i.outstanding_amount) for i in candidates)
		if abs(total - target_amount) < _TOLERANCE:
			return _do_match(bt, candidates, invoice_doctype, "all", target_amount)

	# Sum-Diagnose für die Message (hilft beim manuellen Zuordnen)
	candidates_sum = sum(flt(i.outstanding_amount) for i in candidates)
	return {
		"matched": False,
		"reason": "no_exact_match",
		"message": (
			f"{len(candidates)} offene Rechnung(en), "
			f"Summe {candidates_sum:.2f} € ≠ {target_amount:.2f} €"
		),
	}


def _do_match(bt, invoices, invoice_doctype, strategy_label, target_amount):
	"""Erstelle PE mit Allocations und reconcile gegen die Bank Transaction."""
	pe = create_payment_entry_for_invoices(
		bt=bt,
		invoices=invoices,
		invoice_doctype=invoice_doctype,
		target_amount=target_amount,
	)
	reconcile_voucher_with_bt(bt, "Payment Entry", pe.name, target_amount)

	return {
		"matched": True,
		"payment_entry": pe.name,
		"invoices": [i.name for i in invoices],
		"strategy": strategy_label,
		"message": (
			f"{len(invoices)} Rechnung(en) zugeordnet [{strategy_label}]: "
			f"{target_amount:.2f} €"
		),
	}


def reconcile_voucher_with_bt(bt, voucher_doctype, voucher_name, amount):
	"""Wrapper um ERPNext ``reconcile_vouchers``: hängt einen Beleg an eine BT."""
	from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
		reconcile_vouchers,
	)

	reconcile_vouchers(
		bank_transaction_name=bt.name,
		vouchers=json.dumps(
			[
				{
					"payment_doctype": voucher_doctype,
					"payment_name": voucher_name,
					"amount": amount,
				}
			]
		),
	)


def _resolve_company_and_bank_account(bt):
	bank_account_doc = frappe.get_cached_doc("Bank Account", bt.bank_account)
	company = bank_account_doc.company or bt.company
	if not company:
		frappe.throw(
			f"Bank Account {bt.bank_account} hat keine Company hinterlegt."
		)
	if not bank_account_doc.account:
		frappe.throw(
			f"Bank Account {bt.bank_account} hat kein GL-Konto hinterlegt."
		)
	return company, bank_account_doc


def _get_cost_center_of_invoice(invoice_name: str, invoice_doctype: str) -> str | None:
	"""Liest die Kostenstelle aus der ersten Item-Zeile einer Rechnung.

	Bei Hausverwaltung haben i.d.R. alle Items einer Rechnung dieselbe Kostenstelle
	(eine Rechnung gehört zu einer Immobilie). Erste Item-Zeile reicht daher.
	"""
	try:
		item_dt = invoice_doctype + " Item"
		return frappe.db.get_value(
			item_dt,
			{"parent": invoice_name, "parenttype": invoice_doctype},
			"cost_center",
		) or None
	except Exception:
		return None


def _resolve_expected_cost_center_for_bt(bt) -> str | None:
	"""Bestimmt die 'Soll'-Kostenstelle für jede Buchung über diese Bank Transaction.

	Auflösungs-Kette:
	1. Bank Account → GL-Konto → Immobilie (über Immobilie Bankkonto Child-Table)
	   → ``Immobilie.kostenstelle``
	2. Company-Default ``cost_center`` (Fallback)

	Wird genutzt für:
	- Cost Center auf erzeugte Payment Entries / Journal Entries
	- Cost-Center-Filter beim Lieferanten-Auto-Match (nur Rechnungen der gleichen
	  Kostenstelle gelten als Match-Kandidat)
	"""
	try:
		bank_account_doc = frappe.get_cached_doc("Bank Account", bt.bank_account)
	except Exception:
		return None
	gl_account = getattr(bank_account_doc, "account", None)
	company = getattr(bank_account_doc, "company", None) or getattr(bt, "company", None)

	# 1. Über GL-Konto → Immobilie → Kostenstelle
	if gl_account:
		try:
			immo = frappe.db.get_value(
				"Immobilie Bankkonto",
				{"konto": gl_account, "parenttype": "Immobilie"},
				"parent",
			)
			if immo:
				cc = frappe.db.get_value("Immobilie", immo, "kostenstelle")
				if cc:
					return cc
		except Exception:
			pass

	# 2. Company-Default
	if company:
		try:
			cc = frappe.get_cached_value("Company", company, "cost_center")
			if cc:
				return cc
		except Exception:
			pass
	return None


def create_payment_entry_for_invoices(
	*,
	bt,
	invoices,
	invoice_doctype,
	target_amount,
	leftover_as_advance: bool = False,
):
	"""Baut, inseriert und submitted ein Payment Entry mit Allocation pro Rechnung.

	Args:
	    bt: Bank Transaction Document.
	    invoices: Iterable von Dicts/Records mit ``name`` und ``outstanding_amount``.
	    invoice_doctype: ``Sales Invoice`` oder ``Purchase Invoice``.
	    target_amount: Komplett-Betrag der Bank Transaction (>= sum(allocations)).
	    leftover_as_advance: Wenn True und ``target_amount`` > Allocation-Summe,
	        bleibt der Rest als ``unallocated_amount`` am PE stehen (Vorauszahlung).
	        Wenn False und Differenz > 0,01 €: Fehler — Aufrufer muss balancieren.

	Raises wenn party_type/party fehlt oder GL-Konto unvollständig.
	"""
	from erpnext.accounts.party import get_party_account

	if not bt.party_type or not bt.party:
		frappe.throw(
			"Payment Entry braucht eine Party — bitte zuerst Mieter/Lieferant "
			"an der Zeile zuweisen."
		)
	if bt.party_type not in ("Customer", "Supplier"):
		frappe.throw(f"Party-Typ '{bt.party_type}' nicht unterstützt für Payment Entry.")

	company, bank_account_doc = _resolve_company_and_bank_account(bt)

	if bt.party_type == "Customer":
		payment_type = "Receive"
		party_account = get_party_account("Customer", bt.party, company)
		paid_from = party_account
		paid_to = bank_account_doc.account
	else:
		payment_type = "Pay"
		party_account = get_party_account("Supplier", bt.party, company)
		paid_from = bank_account_doc.account
		paid_to = party_account

	cost_center = _resolve_expected_cost_center_for_bt(bt)

	pe = frappe.new_doc("Payment Entry")
	pe.update(
		{
			"payment_type": payment_type,
			"company": company,
			"posting_date": bt.date,
			"party_type": bt.party_type,
			"party": bt.party,
			"bank_account": bt.bank_account,
			"paid_from": paid_from,
			"paid_to": paid_to,
			"paid_amount": target_amount,
			"received_amount": target_amount,
			"reference_no": bt.reference_number or bt.name,
			"reference_date": bt.date,
		}
	)
	if cost_center and pe.meta.get_field("cost_center"):
		pe.cost_center = cost_center

	# Allocations in Reihenfolge der Eingangs-Liste:
	#   - Wenn die Rechnung ein explizites ``allocated_amount`` mitbringt
	#     (z.B. vom manuellen Zuordnen-Dialog), wird genau das genutzt.
	#   - Sonst: Voll-Allokation bis remaining (älteste zuerst, max outstanding).
	remaining = target_amount
	allocated_total = 0.0
	for inv in invoices:
		def _g(key):
			return inv.get(key) if hasattr(inv, "get") else getattr(inv, key, None)

		outstanding = flt(_g("outstanding_amount"))
		inv_name = _g("name")
		explicit = _g("allocated_amount")
		if explicit is not None and flt(explicit) > 0:
			alloc = min(flt(explicit), outstanding, remaining if remaining > 0 else flt(explicit))
		else:
			alloc = min(outstanding, remaining)
		if alloc <= 0:
			continue
		pe.append(
			"references",
			{
				"reference_doctype": invoice_doctype,
				"reference_name": inv_name,
				"allocated_amount": alloc,
			},
		)
		remaining -= alloc
		allocated_total += alloc

	# Sanity-Check: Differenz Bank-Betrag vs. zuteilbare Summe
	leftover = flt(target_amount) - flt(allocated_total)
	if leftover > _TOLERANCE and not leftover_as_advance:
		frappe.throw(
			f"Auswahl summiert auf {allocated_total:.2f} €, Bank-Betrag ist "
			f"{target_amount:.2f} €. Differenz {leftover:.2f} € — bitte mehr "
			f"Rechnungen wählen oder 'Restbetrag als Vorauszahlung' aktivieren."
		)

	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def create_standalone_payment_entry(*, bt, party_type=None, party=None, remarks=None):
	"""Komplett unallocated Payment Entry: kompletter BT-Betrag wandert ins
	Receivable/Payable des angegebenen Mieters/Lieferanten als offenes
	Guthaben/Verbindlichkeit.

	Wenn party_type/party None: vom BT übernehmen.
	"""
	from erpnext.accounts.party import get_party_account

	party_type = party_type or bt.party_type
	party = party or bt.party
	if not party_type or not party:
		frappe.throw(
			"Standalone Payment Entry braucht Party Type und Party — entweder "
			"in der Zeile zuweisen oder im Dialog angeben."
		)
	if party_type not in ("Customer", "Supplier"):
		frappe.throw(f"Party-Typ '{party_type}' nicht unterstützt.")

	deposit = flt(bt.deposit)
	withdrawal = flt(bt.withdrawal)
	target_amount = deposit if deposit > 0 else withdrawal
	if target_amount <= 0:
		frappe.throw("Bank Transaction hat keinen Betrag (deposit/withdrawal beide 0).")

	company, bank_account_doc = _resolve_company_and_bank_account(bt)

	if party_type == "Customer":
		payment_type = "Receive"
		party_account = get_party_account("Customer", party, company)
		paid_from = party_account
		paid_to = bank_account_doc.account
	else:
		payment_type = "Pay"
		party_account = get_party_account("Supplier", party, company)
		paid_from = bank_account_doc.account
		paid_to = party_account

	cost_center = _resolve_expected_cost_center_for_bt(bt)

	pe = frappe.new_doc("Payment Entry")
	pe.update(
		{
			"payment_type": payment_type,
			"company": company,
			"posting_date": bt.date,
			"party_type": party_type,
			"party": party,
			"bank_account": bt.bank_account,
			"paid_from": paid_from,
			"paid_to": paid_to,
			"paid_amount": target_amount,
			"received_amount": target_amount,
			"reference_no": bt.reference_number or bt.name,
			"reference_date": bt.date,
			"remarks": remarks or bt.description or None,
		}
	)
	if cost_center and pe.meta.get_field("cost_center"):
		pe.cost_center = cost_center
	# bewusst keine references — alles bleibt unallocated_amount
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def create_journal_entry_for_bt(*, bt, account, cost_center=None, remarks=None):
	"""Buchungssatz: Bank-Konto vs. übergebenes GL-Konto.

	Eingang (deposit > 0): Bank Soll, account Haben.
	Ausgang (withdrawal > 0): Bank Haben, account Soll.
	"""
	deposit = flt(bt.deposit)
	withdrawal = flt(bt.withdrawal)
	if deposit > 0 and withdrawal == 0:
		direction = "in"
		amount = deposit
	elif withdrawal > 0 and deposit == 0:
		direction = "out"
		amount = withdrawal
	else:
		frappe.throw(
			"Bank Transaction hat keinen eindeutigen Betrag (deposit + withdrawal nicht klar)."
		)

	if not account:
		frappe.throw("Bitte ein Gegenkonto angeben.")
	if not frappe.db.exists("Account", account):
		frappe.throw(f"Konto '{account}' existiert nicht.")

	company, bank_account_doc = _resolve_company_and_bank_account(bt)

	# Cost Center — wenn der Aufrufer keine angegeben hat, automatisch aus der
	# Immobilie der Bank-Transaction ableiten.
	resolved_cc = cost_center or _resolve_expected_cost_center_for_bt(bt)

	je = frappe.new_doc("Journal Entry")
	je.update(
		{
			"voucher_type": "Bank Entry",
			"company": company,
			"posting_date": bt.date,
			"cheque_no": bt.reference_number or bt.name,
			"cheque_date": bt.date,
			"user_remark": remarks or bt.description or "",
		}
	)

	# Bank-Seite
	bank_row = {
		"account": bank_account_doc.account,
		"cost_center": resolved_cc,
	}
	# Gegen-Seite
	other_row = {
		"account": account,
		"cost_center": resolved_cc,
	}
	if direction == "in":
		bank_row["debit_in_account_currency"] = amount
		other_row["credit_in_account_currency"] = amount
	else:
		bank_row["credit_in_account_currency"] = amount
		other_row["debit_in_account_currency"] = amount

	je.append("accounts", bank_row)
	je.append("accounts", other_row)

	je.insert(ignore_permissions=True)
	je.submit()
	return je
