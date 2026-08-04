"""Buchung der Heizkostenabrechnung eines Mietvertrags.

Vor dem Ausgleich werden Abrechnung, Mietvertrag, HK-Vorauszahlungsrechnungen
und deren Zahlungs-/Journalreferenzen gesperrt und als aktueller Datenstand
neu gelesen. Der gespeicherte Vorauszahlungsstand muss weiterhin zum Live-
Buchungsstand passen. Bereits offene HK-Vorauszahlungen (einschließlich
Gutschriften) werden vorzeichenbehaftet in den neuen Ausgleich eingerechnet.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe.utils import cint, cstr, getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	MONEY_QUANT,
	_cost_center_for_abrechnung_doc,
	_ensure_item_with_income,
	_find_income_account,
	_get_default_company,
	_make_sales_invoice,
	_quantize_money,
	_require_settlement_permissions,
	_to_decimal,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
	HK_ITEM_CODE,
)

HK_SETTLEMENT_MARKER_PREFIX = "[HK-SETTLEMENT:"


def _row_value(row: object, fieldname: str) -> Any:
	getter = getattr(row, "get", None)
	return getter(fieldname) if callable(getter) else getattr(row, fieldname, None)


def _strict_money(value: Any, label: str) -> Decimal:
	"""Parse a booking input without silently turning malformed data into zero."""
	if value in (None, ""):
		frappe.throw(f"{label} fehlt; es wurde nichts gebucht.")
	try:
		amount = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(f"{label} ist keine gültige Zahl; es wurde nichts gebucht.")
	if not amount.is_finite():
		frappe.throw(f"{label} ist keine endliche Zahl; es wurde nichts gebucht.")
	return _quantize_money(amount)


def _hk_settlement_marker(abrechnung: str) -> str:
	name = cstr(abrechnung or "").strip()
	if not name:
		frappe.throw(
			"Die HK-Abrechnung hat keinen eindeutigen Namen; es wurde nichts gebucht."
		)
	if any(character in name for character in ("[", "]", "\r", "\n")):
		frappe.throw(
			"Der Name der HK-Abrechnung kann nicht sicher als Ownership-Marker "
			"gespeichert werden; es wurde nichts gebucht."
		)
	return f"{HK_SETTLEMENT_MARKER_PREFIX}{name}]"


def _build_hk_settlement_remark(
	von: Any = None,
	bis: Any = None,
	*,
	abrechnung: str | None = None,
) -> str:
	"""Build the visible remark for HK invoices and credit notes."""
	von_date = getdate(von) if von else None
	bis_date = getdate(bis) if bis else None
	if von_date and bis_date:
		visible = f"Heizkostenabrechnung {von_date:%d.%m.%Y} bis {bis_date:%d.%m.%Y}"
	elif bis_date:
		visible = f"Heizkostenabrechnung {bis_date.year}"
	elif von_date:
		visible = f"Heizkostenabrechnung ab {von_date:%d.%m.%Y}"
	else:
		visible = "Heizkostenabrechnung"

	settlement_name = cstr(abrechnung or "").strip()
	if settlement_name:
		return f"{_hk_settlement_marker(settlement_name)} {visible}"
	return visible


def _get_locked_settlement_document(abrechnung: str):
	"""Lock and reload the HK settlement and its authoritative contract."""
	rows = frappe.db.sql(
		"""
		SELECT name
		FROM `tabHeizkostenabrechnung Mieter`
		WHERE name = %s
		FOR UPDATE
		""",
		(abrechnung,),
	)
	if not rows:
		frappe.throw(f"Heizkostenabrechnung Mieter {abrechnung} wurde nicht gefunden.")
	doc = frappe.get_doc(
		"Heizkostenabrechnung Mieter",
		abrechnung,
		for_update=True,
	)
	if int(getattr(doc, "docstatus", 0) or 0) != 1:
		frappe.throw(
			"HK-Ausgleichsbelege dürfen nur für eine eingereichte "
			"HK-Mieterabrechnung erzeugt werden."
		)

	parent_name = cstr(
		getattr(doc, "heizkostenabrechnung_immobilie", None) or ""
	).strip()
	if not parent_name:
		frappe.throw(
			"Die HK-Mieterabrechnung ist keiner Heizkostenabrechnung Immobilie "
			"zugeordnet; es wurde nichts gebucht."
		)
	parent_rows = frappe.db.sql(
		"""
		SELECT name, docstatus
		FROM `tabHeizkostenabrechnung Immobilie`
		WHERE name = %s
		FOR UPDATE
		""",
		(parent_name,),
		as_dict=True,
	)
	if (
		len(parent_rows or []) != 1
		or int(_row_value(parent_rows[0], "docstatus") or 0) == 2
	):
		frappe.throw(
			f"Die zugehörige Heizkostenabrechnung Immobilie {parent_name} "
			"fehlt oder ist storniert; es wurde nichts gebucht."
		)

	mietvertrag = cstr(getattr(doc, "mietvertrag", None) or "").strip()
	if not mietvertrag:
		frappe.throw("Die HK-Abrechnung hat keinen Mietvertrag; es wurde nichts gebucht.")
	contract_rows = frappe.db.sql(
		"""
		SELECT name, kunde, wohnung
		FROM `tabMietvertrag`
		WHERE name = %s
		FOR UPDATE
		""",
		(mietvertrag,),
		as_dict=True,
	)
	if not contract_rows:
		frappe.throw(
			f"Mietvertrag {mietvertrag} wurde nicht gefunden; es wurde nichts gebucht."
		)
	contract = contract_rows[0]
	contract_customer = cstr(_row_value(contract, "kunde") or "").strip()
	contract_wohnung = cstr(_row_value(contract, "wohnung") or "").strip()
	doc_customer = cstr(getattr(doc, "customer", None) or "").strip()
	doc_wohnung = cstr(getattr(doc, "wohnung", None) or "").strip()
	if not contract_customer:
		frappe.throw(
			f"Mietvertrag {mietvertrag} hat keinen Customer; es wurde nichts gebucht."
		)
	if not contract_wohnung:
		frappe.throw(
			f"Mietvertrag {mietvertrag} hat keine Wohnung; es wurde nichts gebucht."
		)
	if doc_customer != contract_customer:
		frappe.throw(
			f"Customer {doc_customer or '—'} der HK-Abrechnung passt nicht zum "
			f"Mietvertrag {mietvertrag} ({contract_customer}); es wurde nichts gebucht."
		)
	if doc_wohnung != contract_wohnung:
		frappe.throw(
			f"Wohnung {doc_wohnung or '—'} der HK-Abrechnung passt nicht zum "
			f"Mietvertrag {mietvertrag} ({contract_wohnung}); es wurde nichts gebucht."
		)
	return doc


def _structured_contract_and_month(value: Any) -> tuple[str, date | None]:
	structured_id = cstr(value or "").strip()
	if "|" not in structured_id:
		return "", None
	contract, month_text = structured_id.rsplit("|", 1)
	try:
		month = datetime.strptime(month_text.strip(), "%m/%Y").date().replace(day=1)
	except ValueError:
		month = None
	return contract.strip(), month


def _marker_contracts_and_months(remarks: Any) -> tuple[set[str], set[date]]:
	text = cstr(remarks or "")
	contracts = {
		match.strip()
		for match in re.findall(r"\[MV:([^\]]+)\]", text)
		if match.strip()
	}
	months: set[date] = set()
	for month, year in re.findall(r"(?<!\d)(0[1-9]|1[0-2])/(20\d{2})(?!\d)", text):
		months.add(date(int(year), int(month), 1))
	return contracts, months


def _month_in_period(month: date, von: Any, bis: Any) -> bool:
	start = getdate(von)
	end = getdate(bis)
	return date(start.year, start.month, 1) <= month <= date(end.year, end.month, 1)


def _invoice_belongs_to_period(row: object, mietvertrag: str, von: Any, bis: Any) -> bool:
	"""Validate exact contract identity and decide whether the invoice is in-period."""
	structured_contract, structured_month = _structured_contract_and_month(
		_row_value(row, "mietabrechnung_id")
	)
	marker_contracts, marker_months = _marker_contracts_and_months(
		_row_value(row, "remarks")
	)
	if len(marker_contracts) > 1:
		frappe.throw(
			f"HK-Vorauszahlungsbeleg {_row_value(row, 'name')} enthält mehrere "
			"Mietvertragsmarker; es wurde nichts gebucht."
		)
	marker_contract = next(iter(marker_contracts), "")
	if structured_contract and marker_contract and structured_contract != marker_contract:
		frappe.throw(
			f"HK-Vorauszahlungsbeleg {_row_value(row, 'name')} enthält "
			"widersprüchliche Mietvertragskennzeichen; es wurde nichts gebucht."
		)
	invoice_contract = structured_contract or marker_contract
	if invoice_contract and invoice_contract != mietvertrag:
		return False
	if not invoice_contract:
		frappe.throw(
			f"HK-Vorauszahlungsbeleg {_row_value(row, 'name')} ist dem "
			f"Mietvertrag {mietvertrag} nicht eindeutig zugeordnet; es wurde nichts gebucht."
		)

	identity_months = set(marker_months)
	if structured_month:
		identity_months.add(structured_month)
	if len(identity_months) > 1:
		frappe.throw(
			f"HK-Vorauszahlungsbeleg {_row_value(row, 'name')} enthält "
			"widersprüchliche Abrechnungsmonate; es wurde nichts gebucht."
		)
	if identity_months:
		return _month_in_period(next(iter(identity_months)), von, bis)

	effective_date = _row_value(row, "effective_date")
	if not effective_date:
		frappe.throw(
			f"Der Zeitraum von HK-Vorauszahlungsbeleg {_row_value(row, 'name')} "
			"kann nicht eindeutig bestimmt werden; es wurde nichts gebucht."
		)
	return getdate(von) <= getdate(effective_date) <= getdate(bis)


def _validate_invoice_identity(
	row: object,
	*,
	company: str,
	customer: str,
	wohnung: str,
) -> None:
	name = _row_value(row, "name")
	actual_company = cstr(_row_value(row, "company") or "").strip()
	actual_customer = cstr(_row_value(row, "customer") or "").strip()
	actual_wohnung = cstr(_row_value(row, "wohnung") or "").strip()
	if actual_company != company:
		frappe.throw(
			f"Company von HK-Vorauszahlungsbeleg {name} ({actual_company or '—'}) "
			f"passt nicht zur Abrechnung ({company}); es wurde nichts gebucht."
		)
	if actual_customer != customer:
		frappe.throw(
			f"Customer von HK-Vorauszahlungsbeleg {name} ({actual_customer or '—'}) "
			f"passt nicht zum Mietvertrag ({customer}); es wurde nichts gebucht."
		)
	if actual_wohnung != wohnung:
		frappe.throw(
			f"Wohnung von HK-Vorauszahlungsbeleg {name} ({actual_wohnung or '—'}) "
			f"passt nicht zum Mietvertrag ({wohnung}); es wurde nichts gebucht."
		)


def _locked_hk_prepayment_invoice_rows(
	doc: object,
	*,
	company: str,
) -> list[dict[str, Any]]:
	"""Select exact monthly HK invoices and linked returns under row locks."""
	mietvertrag = cstr(getattr(doc, "mietvertrag", None) or "").strip()
	customer = cstr(getattr(doc, "customer", None) or "").strip()
	wohnung = cstr(getattr(doc, "wohnung", None) or "").strip()
	von = getattr(doc, "von", None)
	bis = getattr(doc, "bis", None)
	if not (mietvertrag and customer and wohnung and von and bis):
		frappe.throw(
			"HK-Abrechnung unvollständig: Mietvertrag, Customer, Wohnung, Von und Bis "
			"müssen gesetzt sein; es wurde nichts gebucht."
		)

	# Der Header-/Datumszweig findet unmarkierte, potentiell relevante Altbelege.
	# Diese werden anschließend bewusst fail-closed abgelehnt. Die beiden
	# Identitätszweige finden auch spätere Korrekturbelege mit Periodenmarker.
	candidates = frappe.db.sql(
		"""
		SELECT
			si.name,
			si.company,
			si.customer,
			si.wohnung,
			si.mietabrechnung_id,
			si.remarks,
			si.is_return,
			si.return_against,
			si.outstanding_amount,
			COALESCE(si.custom_wertstellungsdatum, si.posting_date) AS effective_date
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1
		  AND EXISTS (
				SELECT 1
				FROM `tabSales Invoice Item` sii
				WHERE sii.parent = si.name
				  AND sii.item_code = %(item_code)s
		  )
		  AND (
				CASE
					WHEN INSTR(COALESCE(si.mietabrechnung_id, ''), '|') > 0
					THEN LEFT(
						si.mietabrechnung_id,
						CHAR_LENGTH(si.mietabrechnung_id)
						- CHAR_LENGTH(SUBSTRING_INDEX(si.mietabrechnung_id, '|', -1))
						- 1
					)
					ELSE NULL
				END = %(mietvertrag)s
				OR LOCATE(%(marker)s, COALESCE(si.remarks, '')) > 0
				OR (
					si.customer = %(customer)s
					AND si.wohnung = %(wohnung)s
					AND COALESCE(si.custom_wertstellungsdatum, si.posting_date)
						BETWEEN %(von)s AND %(bis)s
				)
		  )
		ORDER BY si.name
		FOR UPDATE
		""",
		{
			"item_code": HK_ITEM_CODE,
			"mietvertrag": mietvertrag,
			"marker": f"[MV:{mietvertrag}]",
			"customer": customer,
			"wohnung": wohnung,
			"von": getdate(von),
			"bis": getdate(bis),
		},
		as_dict=True,
	)

	selected: dict[str, dict[str, Any]] = {}
	for row in candidates or []:
		if not _invoice_belongs_to_period(row, mietvertrag, von, bis):
			continue
		_validate_invoice_identity(
			row,
			company=company,
			customer=customer,
			wohnung=wohnung,
		)
		selected[cstr(_row_value(row, "name"))] = row

	# Unmarkierte Korrektur-Gutschriften erben Vertrag und Zeitraum ausschließlich
	# von ihrem gesperrten Originalbeleg.
	if selected:
		linked_returns = frappe.db.sql(
			"""
			SELECT
				si.name,
				si.company,
				si.customer,
				si.wohnung,
				si.mietabrechnung_id,
				si.remarks,
				si.is_return,
				si.return_against,
				si.outstanding_amount,
				COALESCE(si.custom_wertstellungsdatum, si.posting_date) AS effective_date
			FROM `tabSales Invoice` si
			WHERE si.docstatus = 1
			  AND si.is_return = 1
			  AND si.return_against IN %(parents)s
			  AND EXISTS (
					SELECT 1
					FROM `tabSales Invoice Item` sii
					WHERE sii.parent = si.name
					  AND sii.item_code = %(item_code)s
			  )
			ORDER BY si.name
			FOR UPDATE
			""",
			{"parents": tuple(sorted(selected)), "item_code": HK_ITEM_CODE},
			as_dict=True,
		)
		for row in linked_returns or []:
			name = cstr(_row_value(row, "name"))
			_validate_invoice_identity(
				row,
				company=company,
				customer=customer,
				wohnung=wohnung,
			)
			structured_contract, structured_month = _structured_contract_and_month(
				_row_value(row, "mietabrechnung_id")
			)
			marker_contracts, marker_months = _marker_contracts_and_months(
				_row_value(row, "remarks")
			)
			explicit_contracts = ({structured_contract} if structured_contract else set()) | marker_contracts
			if explicit_contracts and explicit_contracts != {mietvertrag}:
				frappe.throw(
					f"HK-Gutschrift {name} widerspricht dem Mietvertrag ihres "
					"Originalbelegs; es wurde nichts gebucht."
				)
			explicit_months = set(marker_months)
			if structured_month:
				explicit_months.add(structured_month)
			if len(explicit_months) > 1:
				frappe.throw(
					f"HK-Gutschrift {name} enthält widersprüchliche "
					"Abrechnungsmonate; es wurde nichts gebucht."
				)
			if explicit_months and not _month_in_period(
				next(iter(explicit_months)),
				von,
				bis,
			):
				frappe.throw(
					f"HK-Gutschrift {name} nennt einen Zeitraum außerhalb der "
					"zugehörigen HK-Abrechnung; es wurde nichts gebucht."
				)
			selected[name] = row

	for row in selected.values():
		if int(_row_value(row, "is_return") or 0) != 1:
			continue
		return_against = cstr(_row_value(row, "return_against") or "").strip()
		if return_against and return_against not in selected:
			frappe.throw(
				f"HK-Gutschrift {_row_value(row, 'name')} verweist auf einen "
				"nicht zur Abrechnung gehörenden Originalbeleg; es wurde nichts gebucht."
			)
	return [selected[name] for name in sorted(selected)]


def _locked_hk_reference_rows(
	invoice_names: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	"""Lock all PE/JE references, including references on draft vouchers."""
	if not invoice_names:
		return [], []
	params = {"names": tuple(invoice_names)}
	payment_rows = frappe.db.sql(
		"""
		SELECT
			per.name,
			per.reference_name AS invoice,
			per.allocated_amount,
			pe.name AS voucher,
			pe.docstatus,
			pe.payment_type
		FROM `tabPayment Entry Reference` per
		INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Sales Invoice'
		  AND per.reference_name IN %(names)s
		ORDER BY per.reference_name, per.parent, per.name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)
	journal_rows = frappe.db.sql(
		"""
		SELECT
			jea.name,
			jea.reference_name AS invoice,
			jea.debit_in_account_currency,
			jea.credit_in_account_currency,
			je.name AS voucher,
			je.docstatus
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE jea.reference_type = 'Sales Invoice'
		  AND jea.reference_name IN %(names)s
		ORDER BY jea.reference_name, jea.parent, jea.name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)
	return payment_rows or [], journal_rows or []


def _get_locked_hk_prepayment_state(doc: object, *, company: str) -> dict[str, Any]:
	"""Return signed HK expected/paid/open amounts from one locked snapshot."""
	invoice_rows = _locked_hk_prepayment_invoice_rows(doc, company=company)
	names = [cstr(_row_value(row, "name")) for row in invoice_rows]
	if not names:
		stored = _strict_money(getattr(doc, "vorauszahlungen", None), "Vorauszahlungen")
		if stored != Decimal("0.00"):
			frappe.throw(
				"Für den gespeicherten HK-Vorauszahlungsstand wurden keine eindeutig "
				"zugehörigen Belege gefunden; es wurde nichts gebucht."
			)
		return {
			"invoice_names": [],
			"expected": Decimal("0.00"),
			"live_paid": Decimal("0.00"),
			"signed_open": Decimal("0.00"),
		}

	item_rows = frappe.db.sql(
		"""
		SELECT parent, item_code, net_amount
		FROM `tabSales Invoice Item`
		WHERE parent IN %(parents)s
		ORDER BY parent, idx
		FOR UPDATE
		""",
		{"parents": tuple(names)},
		as_dict=True,
	)
	hk_by_invoice: dict[str, Decimal] = {name: Decimal("0") for name in names}
	total_by_invoice: dict[str, Decimal] = {name: Decimal("0") for name in names}
	for row in item_rows or []:
		name = cstr(_row_value(row, "parent"))
		amount = _to_decimal(_row_value(row, "net_amount"))
		total_by_invoice[name] = total_by_invoice.get(name, Decimal("0")) + amount
		if _row_value(row, "item_code") == HK_ITEM_CODE:
			hk_by_invoice[name] = hk_by_invoice.get(name, Decimal("0")) + amount

	row_by_name = {cstr(_row_value(row, "name")): row for row in invoice_rows}
	ratio_by_invoice: dict[str, Decimal] = {}
	expected = Decimal("0")
	signed_open = Decimal("0")
	for name in names:
		row = row_by_name[name]
		hk_net = hk_by_invoice.get(name, Decimal("0"))
		total_net = total_by_invoice.get(name, Decimal("0"))
		if hk_net == 0 or total_net == 0:
			frappe.throw(
				f"HK-Vorauszahlungsbeleg {name} hat keinen eindeutig berechenbaren "
				"HK-Anteil; es wurde nichts gebucht."
			)
		is_return = int(_row_value(row, "is_return") or 0) == 1
		signed_hk = -abs(hk_net) if is_return else hk_net
		if not is_return and signed_hk < 0:
			frappe.throw(
				f"HK-Vorauszahlungsbeleg {name} hat einen negativen HK-Anteil ohne "
				"Gutschrift-Kennzeichen; es wurde nichts gebucht."
			)
		ratio = abs(hk_net / total_net)
		if ratio > Decimal("1.000000001"):
			frappe.throw(
				f"HK-Anteil von Vorauszahlungsbeleg {name} ist nicht eindeutig; "
				"es wurde nichts gebucht."
			)
		ratio_by_invoice[name] = ratio
		expected += signed_hk
		signed_open += _to_decimal(_row_value(row, "outstanding_amount")) * ratio

	payment_rows, journal_rows = _locked_hk_reference_rows(names)
	live_paid = Decimal("0")
	for row in payment_rows:
		if int(_row_value(row, "docstatus") or 0) != 1:
			continue
		name = cstr(_row_value(row, "invoice"))
		invoice = row_by_name.get(name)
		if not invoice:
			continue
		sign = Decimal("-1") if int(_row_value(invoice, "is_return") or 0) else Decimal("1")
		live_paid += (
			sign
			* abs(_to_decimal(_row_value(row, "allocated_amount")))
			* ratio_by_invoice[name]
		)
	for row in journal_rows:
		if int(_row_value(row, "docstatus") or 0) != 1:
			continue
		name = cstr(_row_value(row, "invoice"))
		if name not in ratio_by_invoice:
			continue
		live_paid += (
			_to_decimal(_row_value(row, "credit_in_account_currency"))
			- _to_decimal(_row_value(row, "debit_in_account_currency"))
		) * ratio_by_invoice[name]

	expected = _quantize_money(expected)
	signed_open = _quantize_money(signed_open)
	live_paid = _quantize_money(live_paid)
	stored_paid = _strict_money(getattr(doc, "vorauszahlungen", None), "Vorauszahlungen")
	if live_paid != stored_paid:
		frappe.throw(
			"Der Zahlungsstand der HK-Vorauszahlungen hat sich seit Erstellung "
			f"der Abrechnung geändert (Entwurf {stored_paid:.2f}, aktuell "
			f"{live_paid:.2f}). Bitte Abrechnung neu erzeugen; es wurde nichts gebucht."
		)
	if expected != _quantize_money(live_paid + signed_open):
		frappe.throw(
			"HK-Vorauszahlungen sind nicht eindeutig auflösbar: "
			f"Soll {expected:.2f} != bezahlt {live_paid:.2f} + offen "
			f"{signed_open:.2f}. Bitte Gutschriften, Write-offs und "
			"Zahlungs-/Journalzuordnungen prüfen; es wurde nichts gebucht."
		)
	return {
		"invoice_names": names,
		"expected": expected,
		"live_paid": live_paid,
		"signed_open": signed_open,
	}


def _run_hk_settlement_selfcheck(doc: object, company: str) -> None:
	"""Check only HK prerequisites; do not create/check BK master data."""
	issues: list[str] = []
	if not company:
		issues.append("Keine eindeutige Company für die Wohnung gefunden.")
	if not all(
		getattr(doc, fieldname, None)
		for fieldname in ("mietvertrag", "customer", "wohnung", "von", "bis")
	):
		issues.append(
			"Abrechnung unvollständig: Mietvertrag, Customer, Wohnung, Von und Bis "
			"müssen gesetzt sein."
		)
	if company:
		receivables = frappe.get_all(
			"Account",
			filters={"company": company, "account_type": "Receivable", "is_group": 0},
			pluck="name",
			limit=1,
		)
		if not receivables:
			issues.append(f"Kein Debitorenkonto für Company {company} vorhanden.")
		if not _find_income_account(company):
			issues.append(f"Kein Ertragskonto für Company {company} vorhanden.")
	if issues:
		raise frappe.ValidationError(
			"Voraussetzungen für HK-Buchung nicht erfüllt:\n- " + "\n- ".join(issues)
		)


def _validated_existing_hk_settlement_document(
	doc: object,
	*,
	fieldname: str,
	expected_is_return: int,
):
	"""Lock and validate one existing HK settlement link fail-closed."""
	voucher_name = cstr(getattr(doc, fieldname, None) or "").strip()
	if not voucher_name:
		return None

	voucher = frappe.get_doc("Sales Invoice", voucher_name, for_update=True)
	label = "HK-Gutschrift" if expected_is_return else "HK-Nachzahlung"
	if cint(getattr(voucher, "docstatus", 0) or 0) != 1:
		frappe.throw(
			f"Settlement-Retry abgebrochen: {label} {voucher_name} ist nicht "
			"mehr eingereicht.",
			frappe.ValidationError,
		)
	if cint(getattr(voucher, "is_return", 0) or 0) != expected_is_return:
		frappe.throw(
			f"Settlement-Retry abgebrochen: Belegart von {voucher_name} passt "
			f"nicht zum Feld {fieldname}.",
			frappe.ValidationError,
		)

	expected_marker = _hk_settlement_marker(
		cstr(getattr(doc, "name", None) or "").strip()
	)
	expected_remark = _build_hk_settlement_remark(
		getattr(doc, "von", None),
		getattr(doc, "bis", None),
		abrechnung=cstr(getattr(doc, "name", None) or "").strip(),
	)
	voucher_remarks = cstr(getattr(voucher, "remarks", None) or "").strip()
	is_legacy_link = not voucher_remarks
	if voucher_remarks not in (expected_marker, expected_remark):
		if voucher_remarks:
			frappe.throw(
				f"Settlement-Retry abgebrochen: {voucher_name} gehört laut "
				"Ownership-Marker nicht zu dieser HK-Abrechnung.",
				frappe.ValidationError,
			)
		linked_settlements = frappe.db.sql(
			"""
			SELECT name
			FROM `tabHeizkostenabrechnung Mieter`
			WHERE sales_invoice = %s OR credit_note = %s
			ORDER BY name
			FOR UPDATE
			""",
			(voucher_name, voucher_name),
		)
		expected_settlement = cstr(getattr(doc, "name", None) or "").strip()
		if [row[0] for row in linked_settlements] != [expected_settlement]:
			frappe.throw(
				f"Settlement-Retry abgebrochen: Legacy-Beleg {voucher_name} ist "
				"nicht eindeutig ausschließlich dieser HK-Abrechnung zugeordnet.",
				frappe.ValidationError,
			)

	expected_customer = cstr(getattr(doc, "customer", None) or "").strip()
	expected_wohnung = cstr(getattr(doc, "wohnung", None) or "").strip()
	if cstr(getattr(voucher, "customer", None) or "").strip() != expected_customer:
		frappe.throw(
			f"Settlement-Retry abgebrochen: Customer von {voucher_name} passt "
			"nicht zur HK-Abrechnung.",
			frappe.ValidationError,
		)
	voucher_wohnung = cstr(getattr(voucher, "wohnung", None) or "").strip()
	if voucher_wohnung != expected_wohnung and not (is_legacy_link and not voucher_wohnung):
		frappe.throw(
			f"Settlement-Retry abgebrochen: Wohnung von {voucher_name} passt "
			"nicht zur HK-Abrechnung.",
			frappe.ValidationError,
		)
	return voucher


def _validate_existing_hk_settlement_links(doc: object) -> None:
	"""Validate retry links instead of trusting mutable Link fields."""
	existing_si = cstr(getattr(doc, "sales_invoice", None) or "").strip()
	existing_cn = cstr(getattr(doc, "credit_note", None) or "").strip()
	if existing_si and existing_cn:
		frappe.throw(
			"Settlement-Retry abgebrochen: Die HK-Abrechnung verweist zugleich "
			"auf eine Nachzahlung und eine Gutschrift.",
			frappe.ValidationError,
		)
	voucher = _validated_existing_hk_settlement_document(
		doc,
		fieldname="sales_invoice" if existing_si else "credit_note",
		expected_is_return=0 if existing_si else 1,
	)
	company = _get_default_company(doc)
	if cstr(getattr(voucher, "company", None) or "").strip() != cstr(company or "").strip():
		frappe.throw(
			f"Settlement-Retry abgebrochen: Company von {voucher.name} passt "
			"nicht zur HK-Abrechnung.",
			frappe.ValidationError,
		)


@frappe.whitelist()
def create_hk_settlement_documents(abrechnung: str) -> dict:
	"""Create exactly one live-state-adjusted HK invoice or credit note."""
	doc = _get_locked_settlement_document(abrechnung)
	_require_settlement_permissions(doc, "Heizkostenabrechnung Mieter")

	# The locked link fields are the authoritative idempotency guard.
	existing_si = cstr(getattr(doc, "sales_invoice", None) or "").strip()
	existing_cn = cstr(getattr(doc, "credit_note", None) or "").strip()
	if existing_si or existing_cn:
		_validate_existing_hk_settlement_links(doc)
		return {
			"created": {
				"sales_invoice": existing_si or None,
				"credit_note": existing_cn or None,
				"note": "Settlement bereits erzeugt.",
			},
			"differenz": float(
				_strict_money(getattr(doc, "kosten_gesamt", None), "Heizkosten")
				- _strict_money(getattr(doc, "vorauszahlungen", None), "Vorauszahlungen")
			),
		}

	customer = cstr(getattr(doc, "customer", None) or "").strip()
	company = _get_default_company(doc)
	_run_hk_settlement_selfcheck(doc, company)
	prepayments = _get_locked_hk_prepayment_state(doc, company=company)

	posting_date = cstr(getattr(doc, "datum", None) or frappe.utils.today())
	wertstellungsdatum = cstr(getattr(doc, "bis", None) or posting_date)
	kosten = _strict_money(getattr(doc, "kosten_gesamt", None), "Heizkosten")
	vorauszahlungen = _strict_money(
		getattr(doc, "vorauszahlungen", None),
		"Vorauszahlungen",
	)
	diff = _quantize_money(kosten - vorauszahlungen)
	signed_open_hk = _quantize_money(prepayments["signed_open"])
	adjustment = _quantize_money(diff - signed_open_hk)

	cost_center = _cost_center_for_abrechnung_doc(doc)
	code_nach = _ensure_item_with_income(
		"HK Nachzahlung",
		"Heizkosten Nachzahlung",
		company,
	)
	code_guth = _ensure_item_with_income(
		"HK Guthaben",
		"Heizkosten Guthaben",
		company,
	)
	created: dict[str, str | None] = {
		"sales_invoice": None,
		"credit_note": None,
	}
	settlement_name = cstr(getattr(doc, "name", None) or abrechnung).strip()
	settlement_remark = _build_hk_settlement_remark(
		doc.von,
		doc.bis,
		abrechnung=settlement_name,
	)

	if adjustment >= MONEY_QUANT:
		try:
			created["sales_invoice"] = _make_sales_invoice(
				customer,
				posting_date,
				code_nach,
				adjustment,
				is_return=0,
				do_submit=True,
				company=company,
				wertstellungsdatum=wertstellungsdatum,
				cost_center=cost_center,
				wohnung=doc.wohnung,
				remarks=settlement_remark,
			)
		except Exception as exc:
			frappe.throw(f"HK-Nachzahlung konnte nicht erstellt werden: {exc}")
	elif adjustment <= -MONEY_QUANT:
		try:
			created["credit_note"] = _make_sales_invoice(
				customer,
				posting_date,
				code_guth,
				adjustment.copy_abs(),
				is_return=1,
				do_submit=True,
				company=company,
				wertstellungsdatum=wertstellungsdatum,
				cost_center=cost_center,
				wohnung=doc.wohnung,
				remarks=settlement_remark,
			)
		except Exception as exc:
			frappe.throw(f"HK-Guthaben konnte nicht erstellt werden: {exc}")
	else:
		doc.add_comment(
			"Comment",
			text=(
				"HK-Abrechnung ist unter Berücksichtigung der offenen "
				"HK-Vorauszahlungen ausgeglichen — kein Ausgleichsbeleg nötig."
			),
		)
		created["note"] = "ausgeglichen"

	updates: dict[str, Any] = {}
	if created.get("sales_invoice"):
		updates["sales_invoice"] = created["sales_invoice"]
	if created.get("credit_note"):
		updates["credit_note"] = created["credit_note"]
	if updates:
		# A link failure must roll back the invoice so a retry cannot duplicate it.
		doc.db_set(updates)

	return {
		"created": created,
		"differenz": float(diff),
		"signed_open_hk": float(signed_open_hk),
		"ausgleich": float(adjustment),
	}
