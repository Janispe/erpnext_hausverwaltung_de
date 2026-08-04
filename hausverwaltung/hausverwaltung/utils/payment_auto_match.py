"""Auto-Matching von Bank Transactions gegen offene Rechnungen.

Versucht für eine Bank Transaction (mit gesetzter Party) eine exakte
Zuordnung zu offenen Sales/Purchase Invoices zu finden und legt — bei
Erfolg — ein passendes Payment Entry an, das gegen die Bank Transaction
reconciled wird.

Strategien für Mieter-Zahlungen (in dieser Reihenfolge, jeweils mit Toleranz ≤ 0,01 €):

1. **Single match** — eine offene Rechnung mit ``outstanding_amount`` =
   Bank-Betrag, deren Rechnungsmonat zur Bankbuchung passt.
2. **Monats-Summe** — alle offenen Rechnungen der Party im selben
   Kalendermonat (posting_date) summieren sich auf den Bank-Betrag, und die
   Bankbuchung liegt im Monatsfenster. Deckt den Mieten-Standardfall ab
   (Miete + NK + HK = 1 Überweisung).

Kein Auto-Match bei Teilzahlungen, ungleichen Beträgen, Subset-Sum-
Kombinationen oder Gesamtsummen über mehrere Mietmonate. Die Bank Transaction
bleibt dann unreconciled und der User kann manuell zuordnen.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import add_months, cint, flt, getdate

_TOLERANCE = 0.01
_DEFAULT_EXACT_MATCH_WINDOW_DAYS = 7
_DEFAULT_RENT_MATCH_DAYS_BEFORE_MONTH = 10
_DEFAULT_RENT_MATCH_DAYS_IN_MONTH = 10
_AMOUNT_EPSILON = 0.005

_RENT_ITEM_LABELS = {
	"Miete": "Miete",
	"Betriebskosten": "BK VZ",
	"Heizkosten": "HK VZ",
	"BK Nachzahlung": "BK Nachzahlung",
	"BK Guthaben": "BK Guthaben",
}

_RENT_TYPE_LABELS = {
	"Miete": "Miete",
	"Betriebskosten": "BK VZ",
	"Heizkosten": "HK VZ",
}


def _bank_transaction_shape(bt) -> frappe._dict:
	"""Return the only valid direction/amount shape of a Bank Transaction.

	ERPNext reconciliation compares absolute amounts.  Every custom booking path
	must therefore establish the signed bank movement itself before it creates or
	reconciles a voucher.
	"""
	deposit = flt(bt.get("deposit") if hasattr(bt, "get") else getattr(bt, "deposit", 0))
	withdrawal = flt(
		bt.get("withdrawal") if hasattr(bt, "get") else getattr(bt, "withdrawal", 0)
	)

	has_deposit = deposit > 0
	has_withdrawal = withdrawal > 0
	if has_deposit == has_withdrawal or deposit < 0 or withdrawal < 0:
		frappe.throw(
			"Bank Transaction hat keinen eindeutigen Betrag "
			"(genau eines von deposit/withdrawal muss positiv sein)."
		)

	if has_deposit:
		return frappe._dict(
			direction="in",
			amount=deposit,
			signed_amount=deposit,
			payment_type="Receive",
		)
	return frappe._dict(
		direction="out",
		amount=withdrawal,
		signed_amount=-withdrawal,
		payment_type="Pay",
	)


def _amounts_equal(left, right) -> bool:
	"""Currency-safe equality at cent precision."""
	return abs(flt(left) - flt(right)) < _AMOUNT_EPSILON


def _get_company_currency(company: str) -> str:
	currency = frappe.get_cached_value("Company", company, "default_currency")
	currency = str(currency or "").strip()
	if not currency:
		frappe.throw(f"Company {company} hat keine Standardwährung.")
	return currency


def _require_company_currency_account(
	account: str,
	*,
	company: str,
	company_currency: str | None = None,
	label: str = "Konto",
) -> str:
	"""Reject accounts whose currency is not exactly the company currency."""
	values = frappe.db.get_value(
		"Account",
		account,
		["company", "account_currency"],
		as_dict=True,
	)
	if not values:
		frappe.throw(f"{label} '{account}' existiert nicht.")
	if values.get("company") != company:
		frappe.throw(f"{label} '{account}' gehört nicht zur Company {company}.")
	expected = company_currency or _get_company_currency(company)
	actual = str(values.get("account_currency") or "").strip()
	if actual != expected:
		frappe.throw(
			f"{label} '{account}' hat Währung '{actual or 'nicht gesetzt'}', "
			f"erwartet ist die Company-Währung '{expected}'. "
			"Bankimport unterstützt keine 1:1-Fremdwährungsbuchung."
		)
	return expected


def _invoice_party_field(invoice_doctype: str) -> tuple[str, str]:
	if invoice_doctype == "Sales Invoice":
		return "customer", "debit_to"
	if invoice_doctype == "Purchase Invoice":
		return "supplier", "credit_to"
	frappe.throw(f"Rechnungstyp '{invoice_doctype}' wird nicht unterstützt.")


def _lock_and_validate_invoices(
	*,
	invoices,
	invoice_doctype: str,
	company: str,
	party: str,
	company_currency: str,
	expected_cost_center: str | None = None,
	credit_notes: bool = False,
) -> list:
	"""Lock selected invoices and return their current outstanding amounts.

	For supplier payments, ``expected_cost_center`` is the authoritative,
	property-specific Cost Center resolved from the locked bank account.  The
	invoice items are locked and checked here as well, so neither a stale
	candidate list nor the split endpoint can cross-pay another property.
	``credit_notes`` switches the expected sign to a negative outstanding amount.
	"""
	party_field, party_account_field = _invoice_party_field(invoice_doctype)
	requested = {}
	for invoice in invoices:
		name = _get_value(invoice, "name")
		if not name or name in requested:
			frappe.throw("Rechnungsauswahl enthält keinen eindeutigen Rechnungsnamen.")
		requested[name] = invoice

	current_by_name = {}
	for name in sorted(requested):
		try:
			invoice = frappe.get_doc(invoice_doctype, name, for_update=True)
		except frappe.DoesNotExistError:
			frappe.throw(f"Rechnung {name} wurde nicht gefunden.")
		outstanding = flt(invoice.outstanding_amount)
		is_open = outstanding < -0.001 if credit_notes else outstanding > 0.001
		if int(invoice.docstatus or 0) != 1 or not is_open:
			label = (
				"kein aktuelles auszahlbares Guthaben"
				if credit_notes
				else "keinen aktuellen offenen Betrag"
			)
			frappe.throw(f"Rechnung {name} hat {label} mehr.")
		if invoice.company != company:
			frappe.throw(f"Rechnung {name} gehört nicht zur Company {company}.")
		if invoice.get(party_field) != party:
			frappe.throw(f"Rechnung {name} gehört nicht zur ausgewählten Partei {party}.")
		if str(invoice.currency or "").strip() != company_currency:
			frappe.throw(
				f"Rechnung {name} hat Währung '{invoice.currency or 'nicht gesetzt'}', "
				f"erwartet ist '{company_currency}'. Fremdwährungsrechnungen werden "
				"im Bankimport nicht 1:1 gebucht."
			)
		if not _amounts_equal(invoice.get("conversion_rate") or 1, 1):
			frappe.throw(
				f"Rechnung {name} hat einen Umrechnungskurs ungleich 1. "
				"Bankimport unterstützt hier keine Fremdwährungsumrechnung."
			)
		party_account = invoice.get(party_account_field)
		_require_company_currency_account(
			party_account,
			company=company,
			company_currency=company_currency,
			label=f"Party-Konto von Rechnung {name}",
		)
		if invoice_doctype == "Purchase Invoice" and expected_cost_center:
			invoice_cost_center = _get_cost_center_of_invoice(
				name,
				invoice_doctype,
				for_update=True,
			)
			if invoice_cost_center != expected_cost_center:
				frappe.throw(
					f"Rechnung {name} gehört zur Kostenstelle "
					f"'{invoice_cost_center or 'ohne eindeutige Kostenstelle'}', "
					f"erwartet ist '{expected_cost_center}' für dieses Bankkonto."
				)

		original = requested[name]
		current_by_name[name] = frappe._dict(
			name=name,
			outstanding_amount=outstanding,
			posting_date=invoice.posting_date,
			allocated_amount=_get_value(original, "allocated_amount"),
			wohnung=invoice.get("wohnung"),
			mietabrechnung_id=invoice.get("mietabrechnung_id"),
		)

	return [current_by_name[name] for name in requested]


def _customer_invoice_identity(
	invoice,
	customer: str,
	*,
	for_update: bool = False,
) -> tuple[str, str | None] | None:
	"""Resolve one invoice to exactly one Mietvertrag/Wohnung identity.

	Structured IDs are validated against the authoritative contract. Legacy
	invoices resolve through the Customer's one-to-one Mietvertrag and are then
	validated against posting date and optional Wohnung.
	"""
	posting_date = _get_value(invoice, "posting_date")
	wohnung = str(_get_value(invoice, "wohnung") or "").strip() or None
	structured = str(_get_value(invoice, "mietabrechnung_id") or "").strip()
	contract_name = None
	if structured and "|" in structured:
		contract_name = structured.rsplit("|", 1)[0].strip()
		if not contract_name:
			return None

	if contract_name:
		try:
			contract = frappe.get_doc(
				"Mietvertrag",
				contract_name,
				for_update=for_update,
			)
		except frappe.DoesNotExistError:
			return None
		if not contract or int(contract.get("docstatus") or 0) == 2:
			return None
		if contract.get("kunde") != customer:
			return None
		if wohnung and contract.get("wohnung") != wohnung:
			return None
		if posting_date:
			d = getdate(posting_date)
			if contract.get("von") and getdate(contract.get("von")) > d:
				return None
			if contract.get("bis") and getdate(contract.get("bis")) < d:
				return None
		return contract.name, contract.get("wohnung") or wohnung

	if not posting_date:
		return None
	d = getdate(posting_date)
	values: dict[str, Any] = {"customer": customer}
	matches = frappe.db.sql(
		f"""
		SELECT name, wohnung, von, bis
		FROM `tabMietvertrag`
		WHERE kunde = %(customer)s
		  AND docstatus != 2
		ORDER BY name
		LIMIT 2
		{"FOR UPDATE" if for_update else ""}
		""",
		values,
		as_dict=True,
	)
	if len(matches) != 1:
		return None
	contract = matches[0]
	if wohnung and contract.get("wohnung") != wohnung:
		return None
	if contract.get("von") and getdate(contract.get("von")) > d:
		return None
	if contract.get("bis") and getdate(contract.get("bis")) < d:
		return None
	return contract.name, contract.get("wohnung") or wohnung


def _match_failure(reason: str, message: str) -> dict[str, Any]:
	return {"ok": False, "reason": reason, "message": message}


def _resolve_invoice_match_context(bt) -> dict[str, Any]:
	if bt.get("payment_entries"):
		return _match_failure("already_reconciled", "Bereits zugeordnet")
	if not bt.party_type or not bt.party:
		return _match_failure("no_party", "Keine Party an Bank Transaction")
	if bt.party_type not in ("Customer", "Supplier"):
		return _match_failure(
			"unsupported_party_type",
			f"Party-Typ '{bt.party_type}' nicht unterstützt",
		)
	try:
		shape = _bank_transaction_shape(bt)
	except frappe.ValidationError as exc:
		return _match_failure("invalid_bank_transaction_amount", str(exc))
	try:
		company, _bank_account_doc = _resolve_company_and_bank_account(bt)
		company_currency = _get_company_currency(company)
	except frappe.ValidationError as exc:
		return _match_failure("foreign_currency_or_company_context", str(exc))

	is_customer = bt.party_type == "Customer"
	expected_direction = "in" if is_customer else "out"
	if shape.direction != expected_direction:
		return _match_failure(
			"wrong_direction_for_customer" if is_customer else "wrong_direction_for_supplier",
			("Customer aber kein Eingang" if is_customer else "Supplier aber kein Ausgang")
			+ " — übersprungen",
		)
	return {
		"ok": True,
		"company": company,
		"company_currency": company_currency,
		"target_amount": shape.amount,
		"invoice_doctype": "Sales Invoice" if is_customer else "Purchase Invoice",
		"party_field": "customer" if is_customer else "supplier",
		"party_account_field": "debit_to" if is_customer else "credit_to",
	}


def _open_invoice_fields(invoice_doctype: str, party_account_field: str) -> list[str]:
	fields = [
		"name",
		"outstanding_amount",
		"posting_date",
		"company",
		"currency",
		"conversion_rate",
		party_account_field,
	]
	meta = frappe.get_meta(invoice_doctype)
	fields.extend(
		fieldname
		for fieldname in ("wohnung", "mietabrechnung_id")
		if meta.has_field(fieldname)
	)
	return fields


def _load_open_invoice_candidates(
	bt,
	*,
	company: str,
	invoice_doctype: str,
	party_field: str,
	party_account_field: str,
	lock_invoices: bool,
) -> list[Any]:
	fields = _open_invoice_fields(invoice_doctype, party_account_field)
	if not lock_invoices:
		return frappe.get_all(
			invoice_doctype,
			filters={
				party_field: bt.party,
				"company": company,
				"docstatus": 1,
				"outstanding_amount": [">", 0.001],
			},
			fields=fields,
			order_by="posting_date asc, name asc",
		)
	optional_selects = [
		f"`{fieldname}`"
		for fieldname in ("wohnung", "mietabrechnung_id")
		if fieldname in fields
	]
	return frappe.db.sql(
		f"""
		SELECT name, outstanding_amount, posting_date, company, currency,
			conversion_rate, `{party_account_field}`,
			{", ".join(optional_selects) if optional_selects else "NULL AS invoice_identity"}
		FROM `tab{invoice_doctype}`
		WHERE `{party_field}` = %(party)s
		  AND company = %(company)s
		  AND docstatus = 1
		  AND outstanding_amount > 0.001
		ORDER BY posting_date ASC, name ASC
		FOR UPDATE
		""",
		{"party": bt.party, "company": company},
		as_dict=True,
	)


def _company_currency_candidates(
	candidates: list[Any],
	*,
	company: str,
	company_currency: str,
	party_account_field: str,
) -> list[Any]:
	safe = []
	for invoice in candidates:
		if str(invoice.get("currency") or "").strip() != company_currency:
			continue
		if not _amounts_equal(invoice.get("conversion_rate") or 1, 1):
			continue
		try:
			_require_company_currency_account(
				invoice.get(party_account_field),
				company=company,
				company_currency=company_currency,
				label=f"Party-Konto von Rechnung {invoice.get('name')}",
			)
		except frappe.ValidationError:
			continue
		safe.append(invoice)
	return safe


def _validate_customer_match_identities(
	candidates: list[Any],
	*,
	customer: str,
	lock_invoices: bool,
) -> dict[str, Any] | None:
	for invoice in candidates:
		identity = _customer_invoice_identity(
			invoice,
			customer,
			for_update=lock_invoices,
		)
		if identity is None:
			return _match_failure(
				"ambiguous_customer_contract_identity",
				f"Rechnung {invoice.get('name')} lässt sich nicht eindeutig einem "
				"Mietvertrag und einer Wohnung dieses Kunden zuordnen. Automatische "
				"Zuordnung gesperrt; bitte manuell prüfen.",
			)
		invoice["_hv_customer_identity"] = identity
	return None


def _filter_candidates_by_cost_center(
	candidates: list[Any],
	*,
	invoice_doctype: str,
	expected_cost_center: str | None,
) -> list[Any]:
	if not expected_cost_center:
		return candidates
	return [
		invoice
		for invoice in candidates
		if _get_cost_center_of_invoice(invoice["name"], invoice_doctype)
		== expected_cost_center
	]


def prepare_invoice_match(
	bt,
	*,
	lock_invoices: bool = False,
	excluded_invoice_names: set[str] | None = None,
) -> dict[str, Any]:
	"""Prepare the shared, read-only candidate state for automatic matching."""
	context = _resolve_invoice_match_context(bt)
	if not context.get("ok"):
		return context

	expected_cc = None
	if bt.party_type == "Supplier":
		try:
			expected_cc = _resolve_expected_cost_center_for_bt(
				bt,
				require_property=True,
				for_update=lock_invoices,
			)
		except frappe.ValidationError as exc:
			return _match_failure(
				"ambiguous_property_context",
				"Bankkonto lässt sich keiner eindeutigen Immobilie mit "
				f"Kostenstelle zuordnen: {exc}",
			)

	candidates = _load_open_invoice_candidates(
		bt,
		company=context["company"],
		invoice_doctype=context["invoice_doctype"],
		party_field=context["party_field"],
		party_account_field=context["party_account_field"],
		lock_invoices=lock_invoices,
	)
	if excluded_invoice_names:
		candidates = [
			invoice
			for invoice in candidates
			if invoice.get("name") not in excluded_invoice_names
		]
	if not candidates:
		return _match_failure(
			"no_open_invoices",
			f"Keine offenen {context['invoice_doctype']}s für {bt.party}",
		)

	safe_candidates = _company_currency_candidates(
		candidates,
		company=context["company"],
		company_currency=context["company_currency"],
		party_account_field=context["party_account_field"],
	)
	if not safe_candidates:
		return _match_failure(
			"foreign_currency_invoice",
			f"{len(candidates)} offene Rechnung(en) gefunden, aber keine ist "
			f"vollständig in Company-Währung {context['company_currency']}. "
			"Fremdwährungen müssen manuell mit Kurs gebucht werden.",
		)
	if bt.party_type == "Customer":
		identity_failure = _validate_customer_match_identities(
			safe_candidates,
			customer=bt.party,
			lock_invoices=lock_invoices,
		)
		if identity_failure:
			return identity_failure

	filtered = _filter_candidates_by_cost_center(
		safe_candidates,
		invoice_doctype=context["invoice_doctype"],
		expected_cost_center=expected_cc,
	)
	if expected_cc and not filtered:
		return _match_failure(
			"no_matching_cost_center",
			f"{len(safe_candidates)} offene Rechnung(en) für {bt.party}, aber "
			f"keine mit Kostenstelle '{expected_cc}' — manuell prüfen.",
		)
	return {
		"ok": True,
		"candidates": filtered,
		"invoice_doctype": context["invoice_doctype"],
		"target_amount": context["target_amount"],
		"company": context["company"],
		"company_currency": context["company_currency"],
	}


def _get_exact_match_window_days(default: int = _DEFAULT_EXACT_MATCH_WINDOW_DAYS) -> int:
	try:
		value = frappe.db.get_single_value(
			"Hausverwaltung Einstellungen", "bankimport_exact_match_toleranz_tage"
		)
		if value is not None and int(value) >= 0:
			return int(value)
	except Exception:
		pass
	return default


def _bank_transaction_date(bt):
	for fieldname in ("date", "posting_date", "transaction_date"):
		value = getattr(bt, fieldname, None)
		if value:
			return getdate(value)
	return None


def _filter_exact_matches_by_date_window(exact_matches, bt, window_days: int):
	bt_date = _bank_transaction_date(bt)
	if not bt_date:
		return []
	start = bt_date - timedelta(days=window_days)
	end = bt_date + timedelta(days=window_days)
	return [
		inv
		for inv in exact_matches
		if getattr(inv, "posting_date", None)
		and start <= getdate(inv.posting_date) <= end
	]


def _rent_month_payment_window(
	posting_date,
	*,
	days_before: int = _DEFAULT_RENT_MATCH_DAYS_BEFORE_MONTH,
	days_in_month: int = _DEFAULT_RENT_MATCH_DAYS_IN_MONTH,
):
	if not posting_date:
		return None
	d = getdate(posting_date)
	month_start = d.replace(day=1)
	start = month_start - timedelta(days=max(int(days_before or 0), 0))
	end = month_start + timedelta(days=max(int(days_in_month or 1), 1) - 1)
	return start, end


def _invoice_in_rent_month_window(inv, bt) -> bool:
	bt_date = _bank_transaction_date(bt)
	if not bt_date:
		return False
	window = _rent_month_payment_window(getattr(inv, "posting_date", None))
	if not window:
		return False
	start, end = window
	return start <= bt_date <= end


def _filter_matches_by_rent_month_window(matches, bt):
	return [inv for inv in matches if _invoice_in_rent_month_window(inv, bt)]


_CUSTOMER_SETTLEMENT_DOCTYPES = (
	("Betriebskostenabrechnung Mieter", "BK-Abrechnung"),
	("Heizkostenabrechnung Mieter", "HK-Abrechnung"),
)


def _settlement_match_failure(
	reason: str,
	message: str,
	*,
	excluded_invoice_names=(),
) -> dict[str, Any]:
	return {
		"matched": False,
		"reason": reason,
		"message": message,
		"excluded_invoice_names": sorted(set(excluded_invoice_names)),
	}


def auto_match_customer_settlement(bt_name: str) -> dict[str, Any]:
	"""Match one exact BK/HK charge or credit within one calendar month.

	Eligibility comes exclusively from the submitted settlement's explicit
	``sales_invoice`` / ``credit_note`` backlink. Free text and item labels are
	intentionally ignored. Linked settlement invoices are returned as exclusions
	so the following generic invoice rule cannot bypass this stricter window.
	"""
	bt = frappe.get_doc("Bank Transaction", bt_name, for_update=True)
	if bt.get("payment_entries"):
		return _settlement_match_failure("already_reconciled", "Bereits zugeordnet")
	if bt.party_type != "Customer" or not bt.party:
		return _settlement_match_failure(
			"not_customer",
			"Keine Customer-Bankbuchung — BK/HK-Abrechnungsregel übersprungen.",
		)

	try:
		shape = _bank_transaction_shape(bt)
		company, _bank_account_doc = _resolve_company_and_bank_account(bt)
		company_currency = _get_company_currency(company)
	except frappe.ValidationError as exc:
		return _settlement_match_failure("invalid_bank_context", str(exc))

	voucher_field = "credit_note" if shape.direction == "out" else "sales_invoice"
	settlement_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for doctype, label in _CUSTOMER_SETTLEMENT_DOCTYPES:
		rows = frappe.get_all(
			doctype,
			filters={
				"docstatus": 1,
				"customer": bt.party,
				voucher_field: ["is", "set"],
			},
			fields=["name", "datum", voucher_field],
			limit_page_length=0,
		)
		for row in rows:
			invoice_name = str(row.get(voucher_field) or "").strip()
			if invoice_name:
				settlement_links[invoice_name].append(
					{
						"doctype": doctype,
						"label": label,
						"name": row.get("name"),
						"date": row.get("datum"),
					}
				)

	if not settlement_links:
		return _settlement_match_failure(
			"no_customer_settlement_vouchers",
			"Keine offene BK-/HK-Abrechnung für diese Buchungsrichtung gefunden.",
		)

	fields = _open_invoice_fields("Sales Invoice", "debit_to")
	outstanding_filter = ["<", -0.001] if shape.direction == "out" else [">", 0.001]
	open_invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": bt.party,
			"company": company,
			"docstatus": 1,
			"outstanding_amount": outstanding_filter,
		},
		fields=fields,
		order_by="posting_date asc, name asc",
		limit_page_length=0,
	)
	safe_invoices = _company_currency_candidates(
		open_invoices,
		company=company,
		company_currency=company_currency,
		party_account_field="debit_to",
	)
	linked_open_names = {
		invoice.get("name")
		for invoice in safe_invoices
		if invoice.get("name") in settlement_links
	}
	exact = [
		invoice
		for invoice in safe_invoices
		if _amounts_equal(abs(flt(invoice.get("outstanding_amount"))), shape.amount)
	]
	exact_settlements = [
		invoice for invoice in exact if invoice.get("name") in settlement_links
	]
	if not exact_settlements:
		return _settlement_match_failure(
			"no_exact_customer_settlement",
			f"Keine BK-/HK-Abrechnung mit exakt {shape.amount:.2f} € gefunden.",
			excluded_invoice_names=linked_open_names,
		)
	if len(exact) != 1 or len(exact_settlements) != 1:
		return _settlement_match_failure(
			"ambiguous_customer_settlement",
			f"{len(exact)} offene Belege mit exakt {shape.amount:.2f} € gefunden; "
			"Abrechnungsbeleg nicht eindeutig — bitte manuell zuordnen.",
			excluded_invoice_names=linked_open_names,
		)

	invoice = exact_settlements[0]
	links = settlement_links[invoice.get("name")]
	if len(links) != 1:
		return _settlement_match_failure(
			"ambiguous_customer_settlement_link",
			f"Beleg {invoice.get('name')} ist mit mehreren Abrechnungen verknüpft — "
			"bitte manuell prüfen.",
			excluded_invoice_names=linked_open_names,
		)

	link = links[0]
	bt_date = _bank_transaction_date(bt)
	settlement_date = getdate(link.get("date")) if link.get("date") else None
	if (
		not bt_date
		or not settlement_date
		or not (settlement_date <= bt_date <= add_months(settlement_date, 1))
	):
		return _settlement_match_failure(
			"customer_settlement_outside_one_month",
			f"{link['label']} {link['name']} passt betragsmäßig, die Bankbuchung "
			"liegt aber nicht zwischen Abrechnungsdatum und dem gleichen Tag des "
			"Folgemonats — bitte manuell zuordnen.",
			excluded_invoice_names=linked_open_names,
		)

	locked_settlement = frappe.get_doc(link["doctype"], link["name"], for_update=True)
	if (
		int(locked_settlement.docstatus or 0) != 1
		or locked_settlement.get("customer") != bt.party
		or str(locked_settlement.get(voucher_field) or "").strip() != invoice.get("name")
		or getdate(locked_settlement.get("datum")) != settlement_date
	):
		return _settlement_match_failure(
			"customer_settlement_changed",
			"Die verknüpfte Abrechnung wurde zwischenzeitlich geändert — bitte erneut prüfen.",
			excluded_invoice_names=linked_open_names,
		)

	identity_failure = _validate_customer_match_identities(
		[invoice],
		customer=bt.party,
		lock_invoices=True,
	)
	if identity_failure:
		return _settlement_match_failure(
			identity_failure["reason"],
			identity_failure["message"],
			excluded_invoice_names=linked_open_names,
		)
	return _do_match(
		bt,
		[invoice],
		"Sales Invoice",
		"bk_hk_credit_one_month" if shape.direction == "out" else "bk_hk_charge_one_month",
		shape.amount,
	)


def auto_match_bank_transaction(
	bt_name: str,
	*,
	excluded_invoice_names: set[str] | None = None,
) -> dict[str, Any]:
	"""Hauptentry-Point: versucht eine Bank Transaction automatisch zuzuordnen.

	Idempotent — wenn die BT bereits ``payment_entries`` hat (status =
	Reconciled / Partially Reconciled), wird nichts gemacht.

	Returns ein Dict mit:
	    matched: bool
	    payment_entry: Name des erstellten PE (oder None)
	    invoices: Liste der zugeordneten Rechnungen
	    strategy: 'single' | 'month_<key>'
	    reason: maschinen-lesbarer Grund bei kein Match
	    message: kurze deutsche Zusammenfassung für UI
	"""
	bt = frappe.get_doc("Bank Transaction", bt_name, for_update=True)
	prep = prepare_invoice_match(
		bt,
		lock_invoices=True,
		excluded_invoice_names=excluded_invoice_names,
	)
	if not prep["ok"]:
		return {"matched": False, "reason": prep["reason"], "message": prep["message"]}

	candidates = prep["candidates"]
	invoice_doctype = prep["invoice_doctype"]
	target_amount = prep["target_amount"]

	is_sales_invoice = invoice_doctype == "Sales Invoice"

	# Strategy 1: Single invoice exact. Bei Mieter-Rechnungen nur, wenn der
	# Rechnungsmonat zur Bankbuchung passt. Bei mehreren exakten Treffern muss
	# genau einer im erlaubten Zeitfenster liegen.
	exact = [
		inv
		for inv in candidates
		if abs(flt(inv.outstanding_amount) - target_amount) < _TOLERANCE
	]
	if is_sales_invoice and exact:
		window_matches = _filter_matches_by_rent_month_window(exact, bt)
		if len(window_matches) == 1:
			return _do_match(
				bt,
				window_matches,
				invoice_doctype,
				"single_month_window_10_10d",
				target_amount,
			)
		return {
			"matched": False,
			"reason": "exact_match_outside_month_window"
			if len(exact) == 1
			else "ambiguous_exact_match",
			"message": (
				f"{len(exact)} offene Rechnung(en) mit exakt {target_amount:.2f} € gefunden; "
				f"{len(window_matches)} davon im Mietfenster "
				f"(-{_DEFAULT_RENT_MATCH_DAYS_BEFORE_MONTH}/+{_DEFAULT_RENT_MATCH_DAYS_IN_MONTH - 1} Tage ab Monatsbeginn) — "
				"bitte manuell zuordnen."
			),
		}
	if len(exact) == 1:
		return _do_match(bt, exact, invoice_doctype, "single", target_amount)
	elif len(exact) > 1:
		window_days = _get_exact_match_window_days()
		window_matches = _filter_exact_matches_by_date_window(exact, bt, window_days)
		if len(window_matches) == 1:
			return _do_match(
				bt,
				window_matches,
				invoice_doctype,
				f"single_window_{window_days}d",
				target_amount,
			)
		return {
			"matched": False,
			"reason": "ambiguous_exact_match",
			"message": (
				f"{len(exact)} offene Rechnung(en) mit exakt {target_amount:.2f} € gefunden; "
				f"{len(window_matches)} davon im Datumsfenster ±{window_days} Tage — "
				"bitte manuell zuordnen."
			),
		}

	# Strategy 2: Same posting month sum. Bei Mieter-Rechnungen darf nur der
	# Monat automatisch gebucht werden, in dessen Zahlungsfenster die Bankbuchung
	# liegt. Dadurch kann eine einzelne Zahlung nicht mehrere offene Mietmonate
	# automatisch ausgleichen.
	by_month: dict[tuple, list] = defaultdict(list)
	has_customer_identities = is_sales_invoice and any(
		inv.get("_hv_customer_identity") for inv in candidates
	)
	for inv in candidates:
		if inv.posting_date:
			d = getdate(inv.posting_date)
			identity = inv.get("_hv_customer_identity") if has_customer_identities else None
			by_month[(d.year, d.month, identity)].append(inv)

	matching_month_groups = []
	for month_key, invs in by_month.items():
		if len(invs) < 2:
			continue  # bereits durch Strategy 1 abgedeckt
		if is_sales_invoice and not any(_invoice_in_rent_month_window(inv, bt) for inv in invs):
			continue
		total = sum(flt(i.outstanding_amount) for i in invs)
		if abs(total - target_amount) < _TOLERANCE:
			matching_month_groups.append((month_key, invs))

	if len(matching_month_groups) == 1:
		month_key, invs = matching_month_groups[0]
		label = f"month_{month_key[0]}-{month_key[1]:02d}"
		return _do_match(bt, invs, invoice_doctype, label, target_amount)
	if len(matching_month_groups) > 1:
		months = ", ".join(
			f"{month_key[0]}-{month_key[1]:02d}"
			for month_key, _invs in matching_month_groups
		)
		return {
			"matched": False,
			"reason": "ambiguous_month_sum",
			"message": (
				f"Mehrere Monatsgruppen ({months}) summieren sich jeweils auf "
				f"{target_amount:.2f} € — bitte manuell zuordnen."
			),
		}

	# Strategy 3: All open invoices sum. Für Mieter bewusst deaktiviert:
	# mehrere offene Monate dürfen nicht durch eine einzige Zahlung automatisch
	# geschlossen werden.
	if (not is_sales_invoice) and len(candidates) >= 2:
		total = sum(flt(i.outstanding_amount) for i in candidates)
		if abs(total - target_amount) < _TOLERANCE:
			return _do_match(bt, candidates, invoice_doctype, "all", target_amount)

	# Sum-Diagnose für die Message (hilft beim manuellen Zuordnen)
	candidates_sum = sum(flt(i.outstanding_amount) for i in candidates)
	if is_sales_invoice and len(candidates) >= 2 and abs(candidates_sum - target_amount) < _TOLERANCE:
		months = {
			(getdate(inv.posting_date).year, getdate(inv.posting_date).month)
			for inv in candidates
			if inv.posting_date
		}
		if len(months) <= 1:
			return {
				"matched": False,
				"reason": "month_total_outside_payment_window",
				"message": (
					f"{len(candidates)} offene Rechnung(en), Monatssumme {candidates_sum:.2f} € "
					"passt zur Zahlung, liegt aber außerhalb des Miet-Zahlungsfensters — "
					"bitte manuell zuordnen."
				),
			}
		return {
			"matched": False,
			"reason": "multi_month_total_not_auto_matched",
			"message": (
				f"{len(candidates)} offene Rechnung(en), Gesamtsumme {candidates_sum:.2f} € "
				"passt zur Zahlung, wird aber nicht automatisch über mehrere Mietmonate gebucht — "
				"bitte manuell zuordnen."
			),
		}
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
	reconcile_created_voucher_or_rollback(bt, "Payment Entry", pe.name, target_amount)

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
	"""Attach a voucher only if its signed GL bank movement matches the BT."""
	from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
		reconcile_vouchers,
	)

	shape = _bank_transaction_shape(bt)
	if not _amounts_equal(abs(flt(amount)), shape.amount):
		frappe.throw(
			f"Reconcile-Betrag {abs(flt(amount)):.2f} € stimmt nicht mit der "
			f"Bank Transaction ({shape.amount:.2f} €) überein."
		)

	company, bank_account_doc = _resolve_company_and_bank_account(bt)
	gl_totals = frappe.db.sql(
		"""
		SELECT
			COALESCE(SUM(debit_in_account_currency), 0) AS debit,
			COALESCE(SUM(credit_in_account_currency), 0) AS credit
		FROM `tabGL Entry`
		WHERE voucher_type = %(voucher_type)s
		  AND voucher_no = %(voucher_no)s
		  AND account = %(account)s
		  AND company = %(company)s
		  AND is_cancelled = 0
		""",
		{
			"voucher_type": voucher_doctype,
			"voucher_no": voucher_name,
			"account": bank_account_doc.account,
			"company": company,
		},
		as_dict=True,
	)
	row = gl_totals[0] if gl_totals else frappe._dict()
	actual_signed_amount = flt(row.get("debit")) - flt(row.get("credit"))
	if not _amounts_equal(actual_signed_amount, shape.signed_amount):
		frappe.throw(
			f"{voucher_doctype} {voucher_name} bewegt das Bankkonto mit "
			f"{actual_signed_amount:.2f} € statt erwartet {shape.signed_amount:.2f} €. "
			"Abstimmung abgebrochen."
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


def reconcile_created_voucher_or_rollback(
	bt,
	voucher_doctype: str,
	voucher_name: str,
	amount,
	savepoint_name: str = "bankimport_reconcile_voucher",
	*,
	voucher_created_here: bool = True,
) -> None:
	"""Reconcile a freshly submitted voucher, rolling it back on failure.

	Bankimport first creates/submits the voucher and then reconciles it with the
	Bank Transaction. If reconcile fails, the submitted voucher must not remain
	as an orphan that can be booked a second time from the import row.

	``voucher_created_here=False`` protects a pre-existing voucher that is reused
	by a second Bank Transaction (notably the other side of an internal
	transfer). A failed reconcile may roll back the attempted link, but must
	never cancel accounting documents owned by an earlier operation/import.
	"""
	frappe.db.savepoint(savepoint_name)
	try:
		reconcile_voucher_with_bt(bt, voucher_doctype, voucher_name, amount)
	except Exception:
		frappe.db.rollback(save_point=savepoint_name)
		if voucher_created_here:
			try:
				if frappe.db.exists(voucher_doctype, voucher_name):
					voucher = frappe.get_doc(voucher_doctype, voucher_name)
					if int(getattr(voucher, "docstatus", 0) or 0) == 1:
						if not getattr(voucher, "flags", None):
							voucher.flags = frappe._dict()
						voucher.flags.ignore_permissions = True
						voucher.cancel()
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"Bankimport: konnte verwaisten {voucher_doctype} {voucher_name} nicht stornieren",
				)
		raise


def _resolve_company_and_bank_account(bt):
	bank_account_doc = frappe.get_doc("Bank Account", bt.bank_account, for_update=True)
	company = bank_account_doc.company or bt.company
	if not company:
		frappe.throw(
			f"Bank Account {bt.bank_account} hat keine Company hinterlegt."
		)
	if not bank_account_doc.account:
		frappe.throw(
			f"Bank Account {bt.bank_account} hat kein GL-Konto hinterlegt."
		)
	company_currency = _get_company_currency(company)
	_require_company_currency_account(
		bank_account_doc.account,
		company=company,
		company_currency=company_currency,
		label=f"Bankkonto von {bt.bank_account}",
	)
	return company, bank_account_doc


def _get_cost_center_of_invoice(
	invoice_name: str,
	invoice_doctype: str,
	*,
	for_update: bool = False,
) -> str | None:
	"""Return one unambiguous cost center shared by every invoice item.

	A missing item cost center, mixed cost centers, or an invoice without items is
	unsafe for property-specific matching and therefore returns ``None``.
	Database/metadata failures deliberately propagate: treating a failed lookup
	as merely "no Cost Center" could let a fallback create a wrong posting.
	"""
	item_dt = invoice_doctype + " Item"
	if for_update:
		items = frappe.db.sql(
			f"""
			SELECT cost_center
			FROM `tab{item_dt}`
			WHERE parent = %(parent)s
			  AND parenttype = %(parenttype)s
			ORDER BY idx ASC
			FOR UPDATE
			""",
			{"parent": invoice_name, "parenttype": invoice_doctype},
			as_dict=True,
		)
	else:
		items = frappe.get_all(
			item_dt,
			filters={"parent": invoice_name, "parenttype": invoice_doctype},
			fields=["cost_center"],
			order_by="idx asc",
		)

	if not items:
		return None

	cost_centers = set()
	for item in items:
		cost_center = (
			item.get("cost_center")
			if hasattr(item, "get")
			else getattr(item, "cost_center", None)
		)
		cost_center = str(cost_center).strip() if cost_center else ""
		if not cost_center:
			return None
		cost_centers.add(cost_center)
		if len(cost_centers) > 1:
			return None

	return next(iter(cost_centers))


def _resolve_expected_cost_center_for_bt(
	bt,
	*,
	require_property: bool = False,
	allow_company_default: bool = False,
	for_update: bool = False,
) -> str | None:
	"""Bestimmt die 'Soll'-Kostenstelle für jede Buchung über diese Bank Transaction.

	Auflösungs-Kette:
	1. Bank Account → GL-Konto → Immobilie (über Immobilie Bankkonto Child-Table)
	   → ``Immobilie.kostenstelle``
	2. Optional Company-Default ``cost_center`` ausschließlich für ausdrücklich
	   nicht-property-spezifische manuelle Buchungspfade.

	Null, ein oder mehrere Immobilien-Mappings werden bewusst unterschieden.
	Mehrere Mappings, eine gelöschte Immobilie oder eine gemappte Immobilie ohne
	aktive Kostenstelle sind immer ein Fehler. Datenbank-/Metadatenfehler werden
	niemals als "kein Mapping" oder Company-Default kaschiert.
	"""
	bank_account_name = str(_get_value(bt, "bank_account") or "").strip()
	if not bank_account_name:
		frappe.throw("Bank Transaction hat kein Bankkonto.")

	bank_account_doc = frappe.get_doc(
		"Bank Account",
		bank_account_name,
		for_update=for_update,
	)
	gl_account = str(bank_account_doc.get("account") or "").strip()
	company = str(
		bank_account_doc.get("company") or _get_value(bt, "company") or ""
	).strip()
	if not gl_account:
		frappe.throw(f"Bank Account {bank_account_name} hat kein GL-Konto hinterlegt.")
	if not company:
		frappe.throw(f"Bank Account {bank_account_name} hat keine Company hinterlegt.")

	bt_company = str(_get_value(bt, "company") or "").strip()
	if bt_company and bank_account_doc.get("company") and bt_company != company:
		frappe.throw(
			f"Bank Transaction gehört zur Company '{bt_company}', das Bankkonto "
			f"aber zu '{company}'."
		)

	if for_update:
		mappings = frappe.db.sql(
			"""
			SELECT name, parent
			FROM `tabImmobilie Bankkonto`
			WHERE konto = %(konto)s
			  AND parenttype = 'Immobilie'
			ORDER BY parent ASC, name ASC
			LIMIT 2
			FOR UPDATE
			""",
			{"konto": gl_account},
			as_dict=True,
		)
	else:
		mappings = frappe.get_all(
			"Immobilie Bankkonto",
			filters={"konto": gl_account, "parenttype": "Immobilie"},
			fields=["name", "parent"],
			order_by="parent asc, name asc",
			limit=2,
		)

	if len(mappings) > 1:
		properties = ", ".join(
			str(row.get("parent") or "?") for row in mappings
		)
		frappe.throw(
			f"GL-Konto '{gl_account}' des Bankkontos '{bank_account_name}' ist "
			f"mehrfach Immobilien zugeordnet ({properties}). Buchung abgebrochen."
		)

	if mappings:
		immobilie = str(mappings[0].get("parent") or "").strip()
		property_values = frappe.db.get_value(
			"Immobilie",
			immobilie,
			["name", "kostenstelle"],
			as_dict=True,
			for_update=for_update,
		) or {}
		if not property_values.get("name"):
			frappe.throw(
				f"Die zum Bankkonto '{bank_account_name}' gemappte Immobilie "
				f"'{immobilie}' wurde nicht gefunden."
			)
		cost_center = str(property_values.get("kostenstelle") or "").strip()
		if not cost_center:
			frappe.throw(
				f"An der zum Bankkonto '{bank_account_name}' gemappten Immobilie "
				f"'{immobilie}' fehlt die Kostenstelle. Buchung abgebrochen."
			)
		cost_center_values = frappe.db.get_value(
			"Cost Center",
			cost_center,
			["name", "company", "is_group", "disabled"],
			as_dict=True,
			for_update=for_update,
		) or {}
		if not cost_center_values.get("name"):
			frappe.throw(
				f"Kostenstelle '{cost_center}' der Immobilie '{immobilie}' "
				"wurde nicht gefunden."
			)
		if cint(cost_center_values.get("is_group")) or cint(
			cost_center_values.get("disabled")
		):
			frappe.throw(
				f"Kostenstelle '{cost_center}' der Immobilie '{immobilie}' "
				"ist nicht aktiv bebuchbar."
			)
		if str(cost_center_values.get("company") or "").strip() != company:
			frappe.throw(
				f"Kostenstelle '{cost_center}' der Immobilie '{immobilie}' gehört "
				f"nicht zur Bankkonto-Company '{company}'."
			)
		return cost_center

	if require_property:
		frappe.throw(
			f"GL-Konto '{gl_account}' des Bankkontos '{bank_account_name}' ist "
			"keiner Immobilie mit eindeutiger Kostenstelle zugeordnet. "
			"Automatische Lieferantenbuchung abgebrochen."
		)

	if not allow_company_default:
		return None

	default_cost_center = frappe.db.get_value("Company", company, "cost_center")
	if not default_cost_center:
		return None
	default_values = frappe.db.get_value(
		"Cost Center",
		default_cost_center,
		["name", "company", "is_group", "disabled"],
		as_dict=True,
		for_update=for_update,
	) or {}
	if (
		not default_values.get("name")
		or str(default_values.get("company") or "").strip() != company
		or cint(default_values.get("is_group"))
		or cint(default_values.get("disabled"))
	):
		frappe.throw(
			f"Company-Standardkostenstelle '{default_cost_center}' ist nicht "
			f"aktiv für Company '{company}' bebuchbar."
		)
	return default_cost_center


def _get_value(row, key):
	return row.get(key) if hasattr(row, "get") else getattr(row, key, None)


def _month_label(value) -> str | None:
	if not value:
		return None
	try:
		d = getdate(value)
		return f"{d.month:02d}/{d.year}"
	except Exception:
		return None


def _label_from_invoice_remarks(remarks: str | None) -> tuple[str | None, str | None]:
	text = str(remarks or "")
	type_match = re.search(r"\[TYPE:([^\]]+)\]", text)
	month_match = re.search(r"(\d{2}/\d{4})", text)
	if not type_match:
		return None, month_match.group(1) if month_match else None
	return _RENT_TYPE_LABELS.get(type_match.group(1).strip()), month_match.group(1) if month_match else None


def _build_customer_payment_remarks(*, invoices, invoice_doctype: str) -> str | None:
	if invoice_doctype != "Sales Invoice":
		return None

	invoice_names = [str(_get_value(inv, "name") or "").strip() for inv in invoices]
	invoice_names = [name for name in invoice_names if name]
	if not invoice_names:
		return None

	invoice_rows = {
		row.name: row
		for row in frappe.get_all(
			"Sales Invoice",
			filters={"name": ["in", invoice_names]},
			fields=["name", "posting_date", "remarks"],
		)
	}
	item_rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": ["in", invoice_names], "parenttype": "Sales Invoice"},
		fields=["parent", "item_code", "description", "idx"],
		order_by="parent asc, idx asc",
	)
	items_by_invoice: dict[str, list] = defaultdict(list)
	for item in item_rows:
		items_by_invoice[item.parent].append(item)

	parts: list[str] = []
	seen: set[str] = set()
	for inv in invoices:
		invoice_name = str(_get_value(inv, "name") or "").strip()
		if not invoice_name:
			continue
		invoice_row = invoice_rows.get(invoice_name)
		posting_date = _get_value(inv, "posting_date") or _get_value(invoice_row, "posting_date")
		month = _month_label(posting_date)
		remark_label, remark_month = _label_from_invoice_remarks(_get_value(invoice_row, "remarks"))
		month = remark_month or month

		labels = []
		for item in items_by_invoice.get(invoice_name, []):
			label = _RENT_ITEM_LABELS.get(str(item.item_code or "").strip())
			if label:
				labels.append(label)
		if not labels and remark_label:
			labels.append(remark_label)
		if not labels:
			continue

		for label in labels:
			part = f"{label} {month}" if month else label
			if part not in seen:
				parts.append(part)
				seen.add(part)

	if not parts:
		return None
	return "Zahlung: " + "; ".join(parts)


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
	        Negative Sales-Invoice-Outstandings werden bei einem Customer-Ausgang
	        als Guthabenauszahlung mit negativer Allocation verarbeitet.
	    invoice_doctype: ``Sales Invoice`` oder ``Purchase Invoice``.
	    target_amount: Komplett-Betrag der Bank Transaction (>= sum(allocations)).
	    leftover_as_advance: Wenn True und ``target_amount`` > Allocation-Summe,
	        bleibt der Rest als ``unallocated_amount`` am PE stehen (Vorauszahlung).
	        Wenn False und Differenz > 0,01 €: Fehler — Aufrufer muss balancieren.

	Raises wenn party_type/party fehlt oder GL-Konto unvollständig.
	"""
	from erpnext.accounts.party import get_party_account

	invoices = list(invoices or [])
	if not invoices:
		frappe.throw("Bitte mindestens eine Rechnung auswählen.")
	if not bt.party_type or not bt.party:
		frappe.throw(
			"Payment Entry braucht eine Party — bitte zuerst Mieter/Lieferant "
			"an der Zeile zuweisen."
		)
	if bt.party_type not in ("Customer", "Supplier"):
		frappe.throw(f"Party-Typ '{bt.party_type}' nicht unterstützt für Payment Entry.")

	company, bank_account_doc = _resolve_company_and_bank_account(bt)
	company_currency = _get_company_currency(company)
	shape = _bank_transaction_shape(bt)

	is_customer_refund = (
		bt.party_type == "Customer"
		and invoice_doctype == "Sales Invoice"
		and shape.direction == "out"
	)
	if bt.party_type == "Customer" and invoice_doctype == "Sales Invoice":
		party_account = get_party_account("Customer", bt.party, company)
		if is_customer_refund:
			payment_type = "Pay"
			paid_from = bank_account_doc.account
			paid_to = party_account
		else:
			payment_type = "Receive"
			paid_from = party_account
			paid_to = bank_account_doc.account
	elif bt.party_type == "Supplier" and invoice_doctype == "Purchase Invoice":
		if shape.direction != "out":
			frappe.throw(
				"Eine positive Lieferantenrechnung kann nur mit einem Zahlungsausgang "
				"ausgeglichen werden. Für eine Lieferantenerstattung bitte einen "
				"eigenständigen Zahlungseingang verwenden."
			)
		payment_type = "Pay"
		party_account = get_party_account("Supplier", bt.party, company)
		paid_from = bank_account_doc.account
		paid_to = party_account
	else:
		frappe.throw(
			f"Party-Typ '{bt.party_type}' passt nicht zu {invoice_doctype}."
		)
	_require_company_currency_account(
		party_account,
		company=company,
		company_currency=company_currency,
		label=f"Party-Konto von {bt.party}",
	)
	expected_cost_center = None
	if invoice_doctype == "Purchase Invoice":
		expected_cost_center = _resolve_expected_cost_center_for_bt(
			bt,
			require_property=True,
			for_update=True,
		)
	invoices = _lock_and_validate_invoices(
		invoices=invoices,
		invoice_doctype=invoice_doctype,
		company=company,
		party=bt.party,
		company_currency=company_currency,
		expected_cost_center=expected_cost_center,
		credit_notes=is_customer_refund,
	)
	if not _amounts_equal(target_amount, shape.amount):
		frappe.throw(
			f"Payment-Entry-Betrag {flt(target_amount):.2f} € stimmt nicht mit der "
			f"Bank Transaction ({shape.amount:.2f} €) überein."
		)

	cost_center = (
		expected_cost_center
		if invoice_doctype == "Purchase Invoice"
		else _resolve_expected_cost_center_for_bt(bt, for_update=True)
	)

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
	custom_remarks = (
		"Auszahlung Guthaben: " + ", ".join(inv.name for inv in invoices)
		if is_customer_refund
		else _build_customer_payment_remarks(
			invoices=invoices,
			invoice_doctype=invoice_doctype,
		)
	)
	if custom_remarks:
		if pe.meta.get_field("custom_remarks"):
			pe.custom_remarks = 1
		pe.remarks = custom_remarks
	if cost_center and pe.meta.get_field("cost_center"):
		pe.cost_center = cost_center

	# Allocations in Reihenfolge der Eingangs-Liste:
	#   - Wenn die Rechnung ein explizites ``allocated_amount`` mitbringt
	#     (z.B. vom manuellen Zuordnen-Dialog), wird genau das genutzt.
	#   - Sonst: voller offener Betrag. Nicht still auf den verbleibenden
	#     Bankbetrag kuerzen, sonst entstehen unbeabsichtigte Teilzahlungen.
	remaining = target_amount
	allocated_total = 0.0
	for inv in invoices:
		def _g(key):
			return inv.get(key) if hasattr(inv, "get") else getattr(inv, key, None)

		outstanding = flt(_g("outstanding_amount"))
		available = abs(outstanding) if is_customer_refund else outstanding
		inv_name = _g("name")
		explicit = _g("allocated_amount")
		if explicit is not None:
			explicit = flt(explicit)
			if explicit <= 0:
				frappe.throw(f"Zuweisung für {inv_name} muss größer als 0 € sein.")
			if explicit > available + _TOLERANCE:
				frappe.throw(
					f"Zuweisung für {inv_name} ({explicit:.2f} €) übersteigt "
					f"offenen Betrag ({available:.2f} €)."
				)
			if explicit > remaining + _TOLERANCE:
				frappe.throw(
					f"Zuweisung für {inv_name} ({explicit:.2f} €) übersteigt "
					f"verbleibenden Bank-Betrag ({remaining:.2f} €)."
				)
			alloc = explicit
		else:
			alloc = available
		if alloc <= 0:
			continue
		pe.append(
			"references",
			{
				"reference_doctype": invoice_doctype,
				"reference_name": inv_name,
				"allocated_amount": -alloc if is_customer_refund else alloc,
			},
		)
		remaining -= alloc
		allocated_total += alloc

	# Sanity-Check: Differenz Bank-Betrag vs. zuteilbare Summe
	over_allocated = flt(allocated_total) - flt(target_amount)
	if over_allocated > _TOLERANCE:
		frappe.throw(
			f"Auswahl summiert auf {allocated_total:.2f} €, Bank-Betrag ist "
			f"{target_amount:.2f} €. Bitte Teilbeträge explizit reduzieren."
		)

	leftover = flt(target_amount) - flt(allocated_total)
	if is_customer_refund and leftover > _TOLERANCE:
		frappe.throw(
			f"Ausgewählte Guthaben summieren auf {allocated_total:.2f} €, "
			f"Bank-Betrag ist {target_amount:.2f} €. Die Auszahlung muss "
			"vollständig einem oder mehreren Guthaben zugeordnet werden."
		)
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

	company, bank_account_doc = _resolve_company_and_bank_account(bt)
	shape = _bank_transaction_shape(bt)
	target_amount = shape.amount
	payment_type = shape.payment_type
	party_account = get_party_account(party_type, party, company)
	_require_company_currency_account(
		party_account,
		company=company,
		company_currency=_get_company_currency(company),
		label=f"Party-Konto von {party}",
	)

	if shape.direction == "in":
		paid_from = party_account
		paid_to = bank_account_doc.account
	else:
		paid_from = bank_account_doc.account
		paid_to = party_account

	cost_center = _resolve_expected_cost_center_for_bt(
		bt,
		allow_company_default=True,
		for_update=True,
	)

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
			# Sonst überschreibt Payment Entry.set_remarks() unseren Verwendungs-
			# zweck nach dem Insert mit "Betrag EUR X bezahlt an Y …".
			"custom_remarks": 1,
		}
	)
	if cost_center and pe.meta.get_field("cost_center"):
		pe.cost_center = cost_center
	# bewusst keine references — alles bleibt unallocated_amount
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def create_internal_transfer_payment_entry(*, bt, other_bank_account: str, remarks=None):
	"""Payment Entry / Internal Transfer between the BT bank account and another bank account.

	The Bank Transaction side determines direction:
	- withdrawal: current bank account -> other bank account
	- deposit: other bank account -> current bank account
	"""
	other_bank_account = (other_bank_account or "").strip()
	if not other_bank_account:
		frappe.throw("Bitte Ziel-/Gegen-Bankkonto auswählen.")

	shape = _bank_transaction_shape(bt)
	direction = shape.direction
	target_amount = shape.amount

	company, bank_account_doc = _resolve_company_and_bank_account(bt)
	if other_bank_account == bt.bank_account:
		frappe.throw("Das Gegen-Bankkonto muss ein anderes Bankkonto sein.")
	if not frappe.db.exists("Bank Account", other_bank_account):
		frappe.throw(f"Bankkonto '{other_bank_account}' existiert nicht.")

	other_bank_account_doc = frappe.get_doc(
		"Bank Account",
		other_bank_account,
		for_update=True,
	)
	if getattr(other_bank_account_doc, "disabled", 0):
		frappe.throw(f"Bankkonto '{other_bank_account}' ist deaktiviert.")
	if getattr(other_bank_account_doc, "company", None) and other_bank_account_doc.company != company:
		frappe.throw("Das Gegen-Bankkonto gehört zu einer anderen Company.")
	if not getattr(other_bank_account_doc, "account", None):
		frappe.throw(f"Bank Account {other_bank_account} hat kein GL-Konto hinterlegt.")
	if other_bank_account_doc.account == bank_account_doc.account:
		frappe.throw("Das Gegen-Bankkonto verwendet dasselbe GL-Konto.")
	company_currency = _get_company_currency(company)
	_require_company_currency_account(
		other_bank_account_doc.account,
		company=company,
		company_currency=company_currency,
		label=f"Gegen-Bankkonto {other_bank_account}",
	)

	if direction == "out":
		paid_from = bank_account_doc.account
		paid_to = other_bank_account_doc.account
	else:
		paid_from = other_bank_account_doc.account
		paid_to = bank_account_doc.account

	pe = frappe.new_doc("Payment Entry")
	pe.update(
		{
			"payment_type": "Internal Transfer",
			"company": company,
			"posting_date": bt.date,
			"bank_account": bt.bank_account,
			"paid_from": paid_from,
			"paid_to": paid_to,
			"paid_amount": target_amount,
			"received_amount": target_amount,
			"reference_no": bt.reference_number or bt.name,
			"reference_date": bt.date,
			"remarks": remarks or bt.description or None,
			"custom_remarks": 1,
		}
	)
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def _validate_journal_counter_account(
	account: str,
	*,
	company: str,
	current_bank_gl: str,
	company_currency: str,
) -> str:
	"""Validate one free-JE counter account before any voucher is created.

	The unrestricted Journal-Entry path is only for non-cash/non-bank
	counter-accounts of the same company. Bank and cash movements must use the
	explicit internal-transfer/payment flows so direction and reconciliation
	stay verifiable.
	"""
	values = frappe.db.get_value(
		"Account",
		account,
		["company", "account_type", "is_group", "disabled", "account_currency"],
		as_dict=True,
	)
	if not values:
		frappe.throw(f"Konto '{account}' existiert nicht.")
	if values.get("company") != company:
		frappe.throw(
			f"Konto '{account}' gehört nicht zur Company {company}."
		)
	if cint(values.get("is_group")) or cint(values.get("disabled")):
		frappe.throw(f"Konto '{account}' ist kein aktives Buchungskonto.")
	if account == current_bank_gl or values.get("account_type") in {"Bank", "Cash"}:
		frappe.throw(
			f"Bank-/Kassenkonto '{account}' darf im freien Buchungssatz nicht als "
			"Gegenkonto verwendet werden. Bitte den Zahlungs- oder Umbuchungspfad nutzen."
		)
	if str(values.get("account_currency") or "").strip() != company_currency:
		frappe.throw(
			f"Gegenkonto '{account}' hat Währung "
			f"'{values.get('account_currency') or 'nicht gesetzt'}', erwartet ist "
			f"'{company_currency}'. Bankimport unterstützt keine "
			"1:1-Fremdwährungsbuchung."
		)
	return account


def create_journal_entry_for_bt(
	*,
	bt,
	account=None,
	cost_center=None,
	splits=None,
	remarks=None,
	wertstellungsdatum=None,
	allow_company_default_cost_center: bool = False,
):
	"""Buchungssatz: Bank-Konto vs. ein oder mehrere Gegenkonten.

	Eingang (deposit > 0): Bank Soll, Gegenkonten Haben.
	Ausgang (withdrawal > 0): Bank Haben, Gegenkonten Soll.

	``splits``: Liste von ``{account, cost_center?, amount}``. Summe muss dem
	Bank-Betrag entsprechen. Wenn ``splits`` None ist, fällt der Aufruf auf den
	Single-Account-Modus zurück (``account`` + ``cost_center`` mit Vollbetrag).
	"""
	shape = _bank_transaction_shape(bt)
	direction = shape.direction
	amount = shape.amount

	company, bank_account_doc = _resolve_company_and_bank_account(bt)
	company_currency = _get_company_currency(company)
	default_cc = _resolve_expected_cost_center_for_bt(bt, for_update=True)
	if not default_cc:
		# In an explicit manual JE, the user's concrete Cost Center is a safer
		# default for the bank leg than a possibly generic Company default.
		explicit_cost_centers = {
			str(value).strip()
			for value in (
				[cost_center]
				if cost_center
				else [
					s.get("cost_center")
					for s in (splits or [])
					if s.get("cost_center")
				]
			)
			if value and str(value).strip()
		}
		if len(explicit_cost_centers) == 1:
			default_cc = next(iter(explicit_cost_centers))
		elif allow_company_default_cost_center:
			default_cc = _resolve_expected_cost_center_for_bt(
				bt,
				allow_company_default=True,
				for_update=True,
			)

	if splits:
		normalized = []
		for s in splits:
			acc = (s.get("account") or "").strip()
			if not acc:
				frappe.throw("Split-Zeile ohne Konto.")
			_validate_journal_counter_account(
				acc,
				company=company,
				current_bank_gl=bank_account_doc.account,
				company_currency=company_currency,
			)
			amt = flt(s.get("amount"))
			if amt <= 0:
				frappe.throw(f"Split für {acc}: Betrag muss > 0 sein.")
			cc = (s.get("cost_center") or "").strip() or default_cc
			normalized.append({"account": acc, "cost_center": cc, "amount": amt})
		total_split = sum(s["amount"] for s in normalized)
		if abs(total_split - amount) > 0.01:
			frappe.throw(
				f"Split-Summe ({total_split:.2f} €) stimmt nicht mit Bank-Betrag "
				f"({amount:.2f} €) überein."
			)
	else:
		if not account:
			frappe.throw("Bitte ein Gegenkonto angeben.")
		_validate_journal_counter_account(
			account,
			company=company,
			current_bank_gl=bank_account_doc.account,
			company_currency=company_currency,
		)
		normalized = [{
			"account": account,
			"cost_center": cost_center or default_cc,
			"amount": amount,
		}]

	je = frappe.new_doc("Journal Entry")
	# ``remark`` (= GL-Entry-Remarks-Quelle) explizit setzen und ``custom_remark``
	# aktivieren — sonst überschreibt Journal Entry.create_remarks() unseren
	# Verwendungszweck mit "Reference #<cheque_no> dated <date>".
	bt_remark = remarks or bt.description or ""
	je.update(
		{
			"voucher_type": "Bank Entry",
			"company": company,
			"posting_date": bt.date,
			"cheque_no": bt.reference_number or bt.name,
			"cheque_date": bt.date,
			"user_remark": bt_remark,
			"remark": bt_remark,
			"custom_remark": 1,
		}
	)
	if wertstellungsdatum and je.meta.has_field("custom_wertstellungsdatum"):
		je.custom_wertstellungsdatum = getdate(wertstellungsdatum)

	# Bank-Seite (Gesamtbetrag in einer Zeile)
	bank_row = {
		"account": bank_account_doc.account,
		"cost_center": default_cc,
	}
	if direction == "in":
		bank_row["debit_in_account_currency"] = amount
	else:
		bank_row["credit_in_account_currency"] = amount
	je.append("accounts", bank_row)

	# Gegen-Seite (eine Zeile pro Split)
	for s in normalized:
		other_row = {
			"account": s["account"],
			"cost_center": s["cost_center"],
		}
		if direction == "in":
			other_row["credit_in_account_currency"] = s["amount"]
		else:
			other_row["debit_in_account_currency"] = s["amount"]
		je.append("accounts", other_row)

	je.insert(ignore_permissions=True)
	je.submit()
	return je
