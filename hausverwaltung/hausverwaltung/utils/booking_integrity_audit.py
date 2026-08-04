"""Read-only integrity checks for the application's financial booking links."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import frappe
from frappe.utils import cint, cstr, flt, getdate

_MV_MARKER = re.compile(r"\[MV:([^\]]+)\]")
_MONTH_MARKER = re.compile(r"(\d{2}/\d{4})")
_PAYMENT_PLAN_MARKER = re.compile(r"\[Zahlungsplan:([^\]]+)\]")
_RENT_ITEM_CODES = (
	"Miete",
	"Betriebskosten",
	"Heizkosten",
	"Untermietzuschlag",
)


def _source_coverage(total: int, checked: int) -> dict[str, Any]:
	"""Describe a bounded scan without pretending that an unseen tail is clean."""
	total = max(cint(total), 0)
	checked = max(min(cint(checked), total), 0)
	truncated = checked < total
	return {
		"total": total,
		"checked": checked,
		"remaining": total - checked,
		"complete": not truncated,
		"truncated": truncated,
	}


def _combined_coverage(**sources: dict[str, Any]) -> dict[str, Any]:
	complete = all(source.get("complete", False) for source in sources.values())
	return {
		"complete": complete,
		"truncated": not complete,
		"sources": sources,
	}


def _normalize_contract_name(value: Any) -> str | None:
	"""Normalize whitespace introduced by legacy HTML/text invoice markers.

	Older rent invoices contain tab characters around the pipe separators even
	though the linked Mietvertrag name contains regular spaces.  Treating those
	formatting characters as part of the document name creates false
	``contract_missing`` findings.
	"""
	text = str(value or "").replace("\xa0", " ").strip()
	if not text:
		return None
	text = re.sub(r"[ \t\r\n]*\|[ \t\r\n]*", " | ", text)
	text = re.sub(r"[\t\r\n]+", " ", text)
	return text.strip() or None


def _rent_identity(row: dict[str, Any]) -> tuple[str | None, str | None, bool]:
	"""Return (contract, month, contradictory) from structured and legacy markers."""
	structured_contract = None
	structured_month = None
	structured = str(row.get("mietabrechnung_id") or "").strip()
	if "|" in structured:
		contract_part, _separator, month_part = structured.rpartition("|")
		structured_contract = _normalize_contract_name(contract_part)
		match = _MONTH_MARKER.search(month_part)
		structured_month = match.group(1) if match else None

	remarks = str(row.get("remarks") or "")
	contract_match = _MV_MARKER.search(remarks)
	month_match = _MONTH_MARKER.search(remarks)
	remark_contract = (
		_normalize_contract_name(contract_match.group(1))
		if contract_match
		else None
	)
	remark_month = month_match.group(1) if month_match else None

	contradictory = bool(
		(structured_contract and remark_contract and structured_contract != remark_contract)
		or (structured_month and remark_month and structured_month != remark_month)
	)
	return (
		structured_contract or remark_contract,
		structured_month or remark_month,
		contradictory,
	)


def _issue(
	issues: list[dict[str, Any]],
	*,
	severity: str,
	code: str,
	doctype: str,
	name: str,
	message: str,
	**details: Any,
) -> None:
	issues.append(
		{
			"severity": severity,
			"code": code,
			"doctype": doctype,
			"name": name,
			"message": message,
			"details": details,
		}
	)


def _load_referenced_contracts(normalized_names: set[str]) -> list[Any]:
	"""Load only contracts named by the bounded invoice window.

	The SQL normalization mirrors ``_normalize_contract_name`` closely enough
	to retain support for historical names containing tabs or irregular spaces
	around pipe separators without loading every contract into Python.
	"""
	if not normalized_names:
		return []
	placeholders = ", ".join(["%s"] * len(normalized_names))
	return frappe.db.sql(
		f"""
		SELECT name, kunde, wohnung, von, bis
		FROM `tabMietvertrag`
		WHERE docstatus < 2
		  AND REGEXP_REPLACE(
			REGEXP_REPLACE(TRIM(name), '[[:space:]]+', ' '),
			'[[:space:]]*\\\\|[[:space:]]*',
			' | '
		  ) IN ({placeholders})
		""",
		tuple(sorted(normalized_names)),
		as_dict=True,
	) or []


def _companies_by_wohnung(
	wohnungen: set[str],
) -> dict[str, tuple[str | None, str | None]]:
	"""Resolve property companies in batches instead of one query per contract."""
	if not wohnungen:
		return {}

	wohnung_rows = frappe.get_all(
		"Wohnung",
		filters={"name": ("in", sorted(wohnungen))},
		fields=["name", "immobilie"],
		limit_page_length=0,
	)
	immobilie_by_wohnung = {
		cstr(row.get("name") or "").strip(): cstr(row.get("immobilie") or "").strip()
		for row in wohnung_rows
	}

	properties: dict[str, Any] = {}
	pending = {
		name for name in immobilie_by_wohnung.values() if name
	}
	while pending:
		rows = frappe.get_all(
			"Immobilie",
			filters={"name": ("in", sorted(pending))},
			fields=[
				"name",
				"kostenstelle",
				"haupt_bank_account",
				"konto",
				"kassenkonto",
				"parent_immobilie",
				"old_parent",
			],
			limit_page_length=0,
		)
		for row in rows:
			properties[cstr(row.get("name") or "").strip()] = row
		loaded = set(properties)
		pending = {
			cstr(row.get("parent_immobilie") or row.get("old_parent") or "").strip()
			for row in rows
			if cstr(row.get("parent_immobilie") or row.get("old_parent") or "").strip()
		} - loaded

	all_property_names = sorted(properties)
	child_accounts: dict[str, set[str]] = {
		name: set() for name in all_property_names
	}
	for child_doctype in ("Immobilie Bankkonto", "Immobilie Kassenkonto"):
		if not all_property_names:
			break
		for row in frappe.get_all(
			child_doctype,
			filters={"parent": ("in", all_property_names)},
			fields=["parent", "konto"],
			limit_page_length=0,
		):
			if row.get("konto"):
				child_accounts.setdefault(row.get("parent"), set()).add(row.get("konto"))

	sources_by_wohnung: dict[str, set[tuple[str, str]]] = {}
	errors: dict[str, str] = {}
	for wohnung in wohnungen:
		sources: set[tuple[str, str]] = set()
		immobilie = immobilie_by_wohnung.get(wohnung, "")
		visited: set[str] = set()
		while immobilie:
			if immobilie in visited:
				errors[wohnung] = f"Die Immobilien-Hierarchie enthält einen Kreis bei {immobilie}."
				break
			visited.add(immobilie)
			row = properties.get(immobilie)
			if not row:
				errors[wohnung] = f"Immobilie {immobilie} wurde nicht gefunden."
				break
			if row.get("kostenstelle"):
				sources.add(("Cost Center", row.get("kostenstelle")))
			if row.get("haupt_bank_account"):
				sources.add(("Bank Account", row.get("haupt_bank_account")))
			for account in (row.get("konto"), row.get("kassenkonto")):
				if account:
					sources.add(("Account", account))
			for account in child_accounts.get(immobilie, set()):
				sources.add(("Account", account))
			immobilie = cstr(
				row.get("parent_immobilie") or row.get("old_parent") or ""
			).strip()
		sources_by_wohnung[wohnung] = sources

	company_by_source: dict[tuple[str, str], str | None] = {}
	for doctype in ("Cost Center", "Bank Account", "Account"):
		names = sorted({
			name
			for sources in sources_by_wohnung.values()
			for kind, name in sources
			if kind == doctype
		})
		if not names:
			continue
		rows = frappe.get_all(
			doctype,
			filters={"name": ("in", names)},
			fields=["name", "company"],
			limit_page_length=0,
		)
		for row in rows:
			company_by_source[(doctype, row.get("name"))] = row.get("company")

	active_companies: list[str] | None = None
	result: dict[str, tuple[str | None, str | None]] = {}
	for wohnung in sorted(wohnungen):
		if wohnung in errors:
			result[wohnung] = (None, errors[wohnung])
			continue
		companies: set[str] = set()
		for source in sorted(sources_by_wohnung.get(wohnung, set())):
			company = cstr(company_by_source.get(source) or "").strip()
			if not company:
				errors[wohnung] = f"Finanzzuordnung {source[0]} {source[1]} hat keine Company."
				break
			companies.add(company)
		if wohnung in errors:
			result[wohnung] = (None, errors[wohnung])
		elif len(companies) > 1:
			result[wohnung] = (
				None,
				"Finanzzuordnungen gehören zu mehreren Companies: "
				+ ", ".join(sorted(companies)),
			)
		elif companies:
			result[wohnung] = (next(iter(companies)), None)
		else:
			if active_companies is None:
				active_companies = frappe.get_all(
					"Company",
					filters={"disabled": 0},
					pluck="name",
					limit_page_length=0,
				)
			result[wohnung] = (
				(active_companies[0] if len(active_companies) == 1 else None),
				(None if len(active_companies) == 1 else "Keine eindeutige aktive Company."),
			)
	return result


def _check_contract_and_rent_invoice_identity(
	issues: list[dict[str, Any]],
	limit: int,
) -> dict[str, Any]:
	meta = frappe.get_meta("Sales Invoice")
	wohnung_select = (
		"si.wohnung AS wohnung"
		if meta.has_field("wohnung")
		else "NULL AS wohnung"
	)
	structured_select = (
		"si.mietabrechnung_id AS mietabrechnung_id"
		if meta.has_field("mietabrechnung_id")
		else "NULL AS mietabrechnung_id"
	)
	rent_invoice_where = """
		WHERE si.docstatus = 1
		  AND EXISTS (
			SELECT 1
			FROM `tabSales Invoice Item` sii
			WHERE sii.parent = si.name
			  AND sii.item_code IN %(rent_item_codes)s
		  )
	"""
	total_row = frappe.db.sql(
		f"""
		SELECT COUNT(*) AS total
		FROM `tabSales Invoice` si
		{rent_invoice_where}
		""",
		{"rent_item_codes": _RENT_ITEM_CODES},
		as_dict=True,
	)
	total_invoices = cint(total_row[0].get("total")) if total_row else 0
	invoices = frappe.db.sql(
		f"""
		SELECT
			si.name,
			si.customer,
			si.company,
			si.posting_date,
			si.remarks,
			{wohnung_select},
			{structured_select}
		FROM `tabSales Invoice` si
		{rent_invoice_where}
		ORDER BY si.modified DESC, si.name
		LIMIT %(limit)s
		""",
		{
			"rent_item_codes": _RENT_ITEM_CODES,
			"limit": limit,
		},
		as_dict=True,
	)
	total_contracts = frappe.db.count(
		"Mietvertrag",
		filters={"docstatus": ("<", 2)},
	)
	sampled_contracts = frappe.get_all(
		"Mietvertrag",
		filters={"docstatus": ("<", 2)},
		fields=["name", "kunde", "wohnung", "von", "bis"],
		order_by="modified desc, name",
		limit_page_length=limit,
	)
	referenced_names = {
		contract_name
		for invoice in invoices
		if (contract_name := _rent_identity(invoice)[0])
	}
	referenced_contracts = _load_referenced_contracts(referenced_names)
	contracts_by_actual_name = {
		cstr(contract.get("name") or "").strip(): contract
		for contract in [*sampled_contracts, *referenced_contracts]
	}
	contracts = list(contracts_by_actual_name.values())
	contract_by_name = {
		_normalize_contract_name(row.name): row
		for row in contracts
		if _normalize_contract_name(row.name)
	}

	customer_names = {
		cstr(contract.get("kunde") or "").strip()
		for contract in contracts
		if cstr(contract.get("kunde") or "").strip()
	}
	existing_customers = set(
		frappe.get_all(
			"Customer",
			filters={"name": ("in", sorted(customer_names))},
			pluck="name",
			limit_page_length=0,
		)
		if customer_names
		else []
	)
	wohnungen = {
		cstr(contract.get("wohnung") or "").strip()
		for contract in contracts
		if cstr(contract.get("wohnung") or "").strip()
	}
	company_by_wohnung = _companies_by_wohnung(wohnungen)
	for contract in contracts:
		customer = cstr(contract.get("kunde") or "").strip()
		if not customer:
			_issue(
				issues,
				severity="critical",
				code="contract_without_customer",
				doctype="Mietvertrag",
				name=contract.name,
				message="Der Mietvertrag hat keinen verknüpften Kunden.",
				wohnung=contract.get("wohnung"),
			)
		elif customer not in existing_customers:
			_issue(
				issues,
				severity="critical",
				code="contract_customer_missing",
				doctype="Mietvertrag",
				name=contract.name,
				message=f"Der verknüpfte Kunde {customer} existiert nicht.",
				customer=customer,
			)
		wohnung = cstr(contract.get("wohnung") or "").strip()
		if wohnung:
			company, error = company_by_wohnung.get(
				wohnung,
				(None, "Wohnung konnte nicht aufgelöst werden."),
			)
			if not company:
				_issue(
					issues,
					severity="critical",
					code="contract_company_ambiguous",
					doctype="Mietvertrag",
					name=contract.name,
					message=(
						"Für die Wohnung des Mietvertrags ist keine eindeutige "
						"Buchungs-Company ableitbar."
					),
					wohnung=wohnung,
					error=error,
				)
	for invoice in invoices:
		contract_name, month, contradictory = _rent_identity(invoice)
		if not contract_name:
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_identity_unresolved",
				doctype="Sales Invoice",
				name=invoice.name,
				message=(
					"Die gebuchte Mietrechnung enthält keinen eindeutig "
					"auflösbaren Mietvertragsmarker."
				),
				mietabrechnung_id=invoice.get("mietabrechnung_id"),
			)
			continue
		if contradictory:
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_identity_conflict",
				doctype="Sales Invoice",
				name=invoice.name,
				message="Strukturierte ID und Rechnungsmarker widersprechen sich.",
			)
			continue
		contract = contract_by_name.get(contract_name)
		if not contract:
			_issue(
				issues,
				severity="high",
				code="rent_invoice_contract_missing",
				doctype="Sales Invoice",
				name=invoice.name,
				message=f"Der referenzierte Mietvertrag {contract_name} fehlt oder ist storniert.",
				mietvertrag=contract_name,
				month=month,
			)
			continue
		customer_mismatch = (
			(invoice.get("customer") or "").strip()
			!= (contract.get("kunde") or "").strip()
		)
		invoice_wohnung = (invoice.get("wohnung") or "").strip()
		contract_wohnung = (contract.get("wohnung") or "").strip()
		wohnung_mismatch = bool(
			invoice_wohnung and invoice_wohnung != contract_wohnung
		)
		expected_company = company_by_wohnung.get(
			contract_wohnung,
			(None, None),
		)[0]
		company_mismatch = bool(
			expected_company
			and (invoice.get("company") or "").strip() != expected_company
		)
		if customer_mismatch or wohnung_mismatch or company_mismatch:
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_header_mismatch",
				doctype="Sales Invoice",
				name=invoice.name,
				message=(
					"Company, Kunde oder Wohnung passen nicht exakt zum "
					"referenzierten Mietvertrag."
				),
				mietvertrag=contract_name,
				invoice_company=invoice.get("company"),
				expected_company=expected_company,
				invoice_customer=invoice.get("customer"),
				contract_customer=contract.get("kunde"),
				invoice_wohnung=invoice.get("wohnung"),
				contract_wohnung=contract.get("wohnung"),
			)
		elif meta.has_field("wohnung") and not invoice_wohnung:
			_issue(
				issues,
				severity="high",
				code="rent_invoice_legacy_wohnung_missing",
				doctype="Sales Invoice",
				name=invoice.name,
				message="Die ältere Mietrechnung hat noch keine strukturierte Wohnungszuordnung.",
				mietvertrag=contract_name,
				contract_wohnung=contract_wohnung,
			)

		if not month:
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_period_unresolved",
				doctype="Sales Invoice",
				name=invoice.name,
				message=(
					"Der Abrechnungsmonat der gebuchten Mietrechnung ist "
					"nicht eindeutig markiert."
				),
				mietvertrag=contract_name,
			)
			continue
		try:
			month_start = datetime.strptime(month, "%m/%Y").date()
		except ValueError:
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_period_unresolved",
				doctype="Sales Invoice",
				name=invoice.name,
				message="Der markierte Abrechnungsmonat ist ungültig.",
				mietvertrag=contract_name,
				month=month,
			)
			continue
		if month_start.month == 12:
			next_month_start = month_start.replace(
				year=month_start.year + 1,
				month=1,
			)
		else:
			next_month_start = month_start.replace(month=month_start.month + 1)
		contract_start = (
			getdate(contract.get("von"))
			if contract.get("von")
			else None
		)
		contract_end = (
			getdate(contract.get("bis"))
			if contract.get("bis")
			else None
		)
		contract_covers_month = bool(
			contract_start
			and contract_start < next_month_start
			and (not contract_end or contract_end >= month_start)
		)
		if not contract_covers_month:
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_contract_period_mismatch",
				doctype="Sales Invoice",
				name=invoice.name,
				message=(
					"Der markierte Abrechnungsmonat liegt nicht im "
					"Vertragszeitraum."
				),
				mietvertrag=contract_name,
				month=month,
				contract_from=contract.get("von"),
				contract_until=contract.get("bis"),
			)
		posting_date = (
			getdate(invoice.get("posting_date"))
			if invoice.get("posting_date")
			else None
		)
		if (
			not posting_date
			or posting_date.year != month_start.year
			or posting_date.month != month_start.month
		):
			_issue(
				issues,
				severity="critical",
				code="rent_invoice_posting_month_mismatch",
				doctype="Sales Invoice",
				name=invoice.name,
				message=(
					"Buchungsdatum und markierter Abrechnungsmonat der "
					"Mietrechnung stimmen nicht überein."
				),
				posting_date=invoice.get("posting_date"),
				month=month,
			)

	return _combined_coverage(
		contracts=_source_coverage(
			total_contracts,
			min(total_contracts, len(contracts)),
		),
		rent_invoices=_source_coverage(total_invoices, len(invoices)),
	)


def _check_rent_invoice_ledger_dimensions(
	issues: list[dict[str, Any]],
	limit: int,
) -> dict[str, Any]:
	"""Compare Wohnung on rent invoice header, items and active GL entries.

	Changing only the header of a submitted invoice is not an accounting
	repair.  The posting dimension on its items and ledger entries must carry
	the same value; otherwise reports can allocate the money to a different
	property (or to none at all).
	"""
	required_columns = (
		("Sales Invoice", "wohnung"),
		("Sales Invoice Item", "wohnung"),
		("GL Entry", "wohnung"),
	)
	missing_columns = [
		f"{doctype}.{fieldname}"
		for doctype, fieldname in required_columns
		if not frappe.db.has_column(doctype, fieldname)
	]
	if missing_columns:
		_issue(
			issues,
			severity="critical",
			code="rent_ledger_wohnung_dimension_missing",
			doctype="Accounting Dimension",
			name="Wohnung",
			message=(
				"Die Wohnungsdimension fehlt auf mindestens einer "
				"Buchungstabelle; Mietbuchungen sind nicht vollständig "
				"auswertbar."
			),
			missing_columns=missing_columns,
		)
		return _combined_coverage(
			dimension_schema=_source_coverage(1, 1),
		)

	broken_rows_sql = """
		SELECT
			si.name,
			si.modified,
			si.wohnung AS header_wohnung,
			MAX(
				CASE
					WHEN COALESCE(sii.wohnung, '') = '' THEN 1
					ELSE 0
				END
			) AS item_missing,
			MAX(
				CASE
					WHEN COALESCE(sii.wohnung, '') != ''
					 AND sii.wohnung != si.wohnung THEN 1
					ELSE 0
				END
			) AS item_mismatch,
			MAX(
				CASE
					WHEN gle.name IS NULL OR COALESCE(gle.wohnung, '') = '' THEN 1
					ELSE 0
				END
			) AS gl_missing,
			MAX(
				CASE
					WHEN COALESCE(gle.wohnung, '') != ''
					 AND gle.wohnung != si.wohnung THEN 1
					ELSE 0
				END
			) AS gl_mismatch
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii
		  ON sii.parent = si.name
		 AND sii.item_code IN (
			'Miete',
			'Betriebskosten',
			'Heizkosten',
			'Untermietzuschlag'
		 )
		LEFT JOIN `tabGL Entry` gle
		  ON gle.voucher_type = 'Sales Invoice'
		 AND gle.voucher_no = si.name
		 AND gle.is_cancelled = 0
		WHERE si.docstatus = 1
		GROUP BY si.name, si.wohnung, si.modified
		HAVING
			COALESCE(si.wohnung, '') = ''
			OR item_missing = 1
			OR item_mismatch = 1
			OR gl_missing = 1
			OR gl_mismatch = 1
	"""
	total_row = frappe.db.sql(
		f"""
		SELECT COUNT(*) AS total
		FROM ({broken_rows_sql}) broken
		""",
		as_dict=True,
	)
	total = cint(total_row[0].get("total")) if total_row else 0
	rows = frappe.db.sql(
		f"""
		{broken_rows_sql}
		ORDER BY si.modified DESC, si.name
		LIMIT %(limit)s
		""",
		{"limit": limit},
		as_dict=True,
	)
	for row in rows:
		has_mismatch = bool(cint(row.item_mismatch) or cint(row.gl_mismatch))
		_issue(
			issues,
			severity="critical" if has_mismatch else "high",
			code="rent_invoice_ledger_wohnung_mismatch",
			doctype="Sales Invoice",
			name=row.name,
			message=(
				"Die Wohnung ist auf Rechnung, Positionen und aktiven "
				"GL Entries nicht vollständig identisch. Eine Header-Änderung "
				"allein wäre keine sichere Korrektur; kontrollierter Repost "
				"erforderlich."
			),
			header_wohnung=row.header_wohnung,
			item_missing=bool(cint(row.item_missing)),
			item_mismatch=bool(cint(row.item_mismatch)),
			gl_missing=bool(cint(row.gl_missing)),
			gl_mismatch=bool(cint(row.gl_mismatch)),
		)
	return _combined_coverage(
		inconsistent_rent_invoices=_source_coverage(total, len(rows)),
	)


def _active_docstatus(doctype: str, name: str | None) -> int | None:
	if not name:
		return None
	value = frappe.db.get_value(doctype, name, "docstatus")
	return cint(value) if value is not None else None


def _check_bank_links(
	issues: list[dict[str, Any]],
	limit: int,
) -> dict[str, Any]:
	total = cint(frappe.db.count("Bankauszug Import Row"))
	rows = frappe.get_all(
		"Bankauszug Import Row",
		fields=[
			"name",
			"parent",
			"bank_transaction",
			"payment_entry",
			"journal_entry",
			"payment_document_type",
			"payment_document",
		],
		limit_page_length=limit,
		order_by="modified desc",
	)
	checked_pairs: set[tuple[str, str, str]] = set()
	for row in rows:
		legacy_links = [
			("Payment Entry", row.get("payment_entry")),
			("Journal Entry", row.get("journal_entry")),
		]
		active_legacy = [(doctype, name) for doctype, name in legacy_links if name]
		if len(active_legacy) > 1:
			_issue(
				issues,
				severity="critical",
				code="bank_row_multiple_vouchers",
				doctype="Bankauszug Import Row",
				name=row.name,
				message="Die Importzeile verweist gleichzeitig auf Payment Entry und Journal Entry.",
			)

		voucher_type = row.get("payment_document_type")
		voucher_name = row.get("payment_document")
		if not voucher_name and active_legacy:
			voucher_type, voucher_name = active_legacy[0]
		elif voucher_name and (voucher_type, voucher_name) not in active_legacy and active_legacy:
			_issue(
				issues,
				severity="critical",
				code="bank_row_voucher_fields_disagree",
				doctype="Bankauszug Import Row",
				name=row.name,
				message="Generische und alte Beleglinks der Importzeile widersprechen sich.",
			)
		if voucher_name and voucher_type not in {"Payment Entry", "Journal Entry"}:
			_issue(
				issues,
				severity="critical",
				code="bank_row_invalid_voucher_type",
				doctype="Bankauszug Import Row",
				name=row.name,
				message="Die Importzeile enthält einen Beleg ohne gültigen Belegtyp.",
				voucher_type=voucher_type,
				voucher=voucher_name,
			)
			continue

		bt_name = row.get("bank_transaction")
		if bt_name and _active_docstatus("Bank Transaction", bt_name) not in {0, 1}:
			_issue(
				issues,
				severity="critical",
				code="bank_transaction_missing_or_cancelled",
				doctype="Bankauszug Import Row",
				name=row.name,
				message=f"Bank Transaction {bt_name} fehlt oder ist storniert.",
				bank_transaction=bt_name,
			)
		if voucher_name and _active_docstatus(voucher_type, voucher_name) != 1:
			_issue(
				issues,
				severity="critical",
				code="bank_voucher_not_submitted",
				doctype="Bankauszug Import Row",
				name=row.name,
				message=f"{voucher_type} {voucher_name} fehlt oder ist nicht gebucht.",
			)
			continue
		if not (bt_name and voucher_type and voucher_name):
			continue

		pair = (bt_name, voucher_type, voucher_name)
		if pair in checked_pairs:
			continue
		checked_pairs.add(pair)
		bt = frappe.db.get_value(
			"Bank Transaction",
			bt_name,
			["bank_account", "deposit", "withdrawal"],
			as_dict=True,
		)
		if not bt:
			continue
		bank = frappe.db.get_value(
			"Bank Account",
			bt.bank_account,
			["account", "company"],
			as_dict=True,
		)
		if not bank or not bank.account:
			continue
		expected = flt(bt.deposit) - flt(bt.withdrawal)
		gl_rows = frappe.db.sql(
			"""
			SELECT
				COALESCE(SUM(debit_in_account_currency), 0) AS debit,
				COALESCE(SUM(credit_in_account_currency), 0) AS credit
			FROM `tabGL Entry`
			WHERE voucher_type = %(voucher_type)s
			  AND voucher_no = %(voucher_name)s
			  AND account = %(account)s
			  AND company = %(company)s
			  AND is_cancelled = 0
			""",
			{
				"voucher_type": voucher_type,
				"voucher_name": voucher_name,
				"account": bank.account,
				"company": bank.company,
			},
			as_dict=True,
		)
		actual = (
			flt(gl_rows[0].get("debit")) - flt(gl_rows[0].get("credit"))
			if gl_rows
			else 0.0
		)
		if abs(actual - expected) >= 0.005:
			_issue(
				issues,
				severity="critical",
				code="bank_voucher_signed_amount_mismatch",
				doctype=voucher_type,
				name=voucher_name,
				message="Der gebuchte Banksaldo stimmt in Betrag oder Richtung nicht mit der Bankzeile überein.",
				bank_transaction=bt_name,
				expected_signed=expected,
				actual_signed=actual,
			)
	return _combined_coverage(
		bank_import_rows=_source_coverage(total, len(rows)),
	)


def _supplier_payable_account(company: str, supplier: str) -> str | None:
	from erpnext.accounts.party import get_party_account

	return get_party_account("Supplier", supplier, company)


def _historical_prepayment_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
	"""Validate one historical supplier advance without acquiring locks or writing."""
	reasons: list[str] = []
	amount = flt(plan.get("vor_systemstart_bezahlt"))
	journal_entry = (plan.get("vor_systemstart_journal_entry") or "").strip()
	company = (plan.get("company") or "").strip()
	supplier = (plan.get("lieferant") or "").strip()
	counter_account = (plan.get("vor_systemstart_gegenkonto") or "").strip()
	expected_date = plan.get("vor_systemstart_buchungsdatum")
	open_balance = 0.0
	payable_account = None

	def add_reason(reason: str) -> None:
		if reason not in reasons:
			reasons.append(reason)

	if not company:
		add_reason("Company fehlt im Zahlungsplan.")
	if not supplier:
		add_reason("Lieferant fehlt im Zahlungsplan.")
	if not expected_date:
		add_reason("Buchungsdatum der historischen Zahlung fehlt.")
	if not counter_account:
		add_reason("Gegenkonto der historischen Zahlung fehlt.")
	if not journal_entry:
		add_reason("Verknüpfter Journal Entry fehlt.")
		return {
			"reasons": reasons,
			"payable_account": None,
			"open_balance": open_balance,
		}

	journal = frappe.db.get_value(
		"Journal Entry",
		journal_entry,
		[
			"name",
			"docstatus",
			"company",
			"posting_date",
			"user_remark",
			"is_opening",
		],
		as_dict=True,
	)
	if not journal:
		add_reason("Verknüpfter Journal Entry existiert nicht.")
		return {
			"reasons": reasons,
			"payable_account": None,
			"open_balance": open_balance,
		}
	if cint(journal.get("docstatus")) != 1:
		add_reason("Journal Entry ist nicht gebucht.")
	if journal.get("company") != company:
		add_reason("Company von Journal Entry und Zahlungsplan stimmt nicht überein.")
	if (
		expected_date
		and getdate(journal.get("posting_date")) != getdate(expected_date)
	):
		add_reason("Buchungsdatum von Journal Entry und Zahlungsplan stimmt nicht überein.")
	if journal.get("is_opening") != "Yes":
		add_reason("Journal Entry ist keine Eröffnungsbuchung.")
	markers = _PAYMENT_PLAN_MARKER.findall(journal.get("user_remark") or "")
	if markers != [plan.get("name")]:
		add_reason("Journal Entry enthält keinen eindeutigen Marker dieses Zahlungsplans.")

	if company and supplier:
		try:
			payable_account = _supplier_payable_account(company, supplier)
		except Exception as exc:
			add_reason(f"Lieferantenkonto konnte nicht aufgelöst werden: {exc}")
	if not payable_account:
		add_reason("Eindeutiges Verbindlichkeitskonto des Lieferanten fehlt.")

	account_rows = frappe.db.sql(
		"""
		SELECT
			name,
			account,
			party_type,
			party,
			is_advance,
			debit_in_account_currency,
			credit_in_account_currency,
			exchange_rate,
			reference_type,
			reference_name
		FROM `tabJournal Entry Account`
		WHERE parent = %(journal_entry)s
		  AND parenttype = 'Journal Entry'
		ORDER BY idx ASC, name ASC
		""",
		{"journal_entry": journal_entry},
		as_dict=True,
	) or []
	if not account_rows:
		add_reason("Journal Entry enthält keine Kontenzeilen.")

	exact_party_rows = [
		row
		for row in account_rows
		if row.get("account") == payable_account
		and row.get("party_type") == "Supplier"
		and row.get("party") == supplier
	]
	party_rows = [
		row
		for row in account_rows
		if row.get("party_type") or row.get("party")
	]
	if not exact_party_rows:
		add_reason("Journal Entry enthält keinen Vorschuss für den exakten Lieferanten.")
	if len(party_rows) != len(exact_party_rows):
		add_reason("Journal Entry enthält eine fremde oder unvollständige Partei-Kontenzeile.")
	if any(row.get("is_advance") != "Yes" for row in exact_party_rows):
		add_reason("Lieferantenzeile ist nicht vollständig als Vorschuss markiert.")
	if any(
		row.get("exchange_rate")
		and abs(flt(row.get("exchange_rate")) - 1.0) > 0.000001
		for row in exact_party_rows
	):
		add_reason("Lieferantenvorschuss verwendet einen Fremdwährungskurs.")

	booked_amount = sum(
		flt(row.get("debit_in_account_currency"))
		- flt(row.get("credit_in_account_currency"))
		for row in exact_party_rows
	)
	if abs(booked_amount - amount) > 0.01:
		add_reason("Gebuchter Lieferantenvorschuss entspricht nicht dem Sollbetrag.")

	counter_rows = [row for row in account_rows if row not in exact_party_rows]
	if (
		len(counter_rows) != 1
		or counter_rows[0].get("account") != counter_account
		or abs(flt(counter_rows[0].get("credit_in_account_currency")) - amount)
		> 0.01
		or flt(counter_rows[0].get("debit_in_account_currency")) > 0.005
		or counter_rows[0].get("party_type")
		or counter_rows[0].get("party")
	):
		add_reason("Gegenkonto oder Sollbetrag der Gegenbuchung ist nicht exakt.")

	if payable_account:
		payable_meta = frappe.db.get_value(
			"Account",
			payable_account,
			["name", "company", "is_group", "account_type"],
			as_dict=True,
		)
		if (
			not payable_meta
			or payable_meta.get("company") != company
			or cint(payable_meta.get("is_group"))
			or payable_meta.get("account_type") != "Payable"
		):
			add_reason("Verbindlichkeitskonto ist für die Company nicht exakt bebuchbar.")
	if counter_account:
		counter_meta = frappe.db.get_value(
			"Account",
			counter_account,
			["name", "company", "is_group"],
			as_dict=True,
		)
		if (
			not counter_meta
			or counter_meta.get("company") != company
			or cint(counter_meta.get("is_group"))
			or counter_account == payable_account
		):
			add_reason("Gegenkonto ist für die Company nicht exakt bebuchbar.")

	ledger_rows = frappe.db.sql(
		"""
		SELECT
			name,
			company,
			account_type,
			account,
			party_type,
			party,
			voucher_detail_no,
			against_voucher_type,
			against_voucher_no,
			amount_in_account_currency
		FROM `tabPayment Ledger Entry`
		WHERE delinked = 0
		  AND voucher_type = 'Journal Entry'
		  AND voucher_no = %(journal_entry)s
		ORDER BY name ASC
		""",
		{"journal_entry": journal_entry},
		as_dict=True,
	) or []
	exact_ledger_rows = [
		row
		for row in ledger_rows
		if row.get("account_type") == "Payable"
		and row.get("company") == company
		and row.get("account") == payable_account
		and row.get("party_type") == "Supplier"
		and row.get("party") == supplier
	]
	if len(exact_ledger_rows) != len(ledger_rows):
		add_reason("Aktiver Payment Ledger enthält eine fremde Company-/Supplier-/Kontenzuordnung.")

	open_by_detail: dict[str, float] = defaultdict(float)
	for ledger_row in exact_ledger_rows:
		if (
			ledger_row.get("against_voucher_type") != "Journal Entry"
			or ledger_row.get("against_voucher_no") != journal_entry
		):
			continue
		detail_name = (ledger_row.get("voucher_detail_no") or "").strip()
		if not detail_name:
			add_reason("Offener Payment-Ledger-Saldo hat keine Journal-Entry-Zeile.")
			continue
		# Payable advances are debit balances and therefore negative in PLE.
		open_by_detail[detail_name] += -flt(
			ledger_row.get("amount_in_account_currency")
		)

	for row in exact_party_rows:
		if row.get("reference_type") not in (None, ""):
			continue
		row_amount = flt(row.get("debit_in_account_currency")) - flt(
			row.get("credit_in_account_currency")
		)
		ledger_available = open_by_detail.pop(row.get("name"), 0.0)
		if row_amount <= 0.005 and abs(ledger_available) <= 0.005:
			continue
		if (
			ledger_available <= 0.005
			or abs(row_amount - ledger_available) > 0.01
		):
			add_reason(
				"Offener Lieferantenvorschuss stimmt zwischen Journal Entry "
				"und Payment Ledger nicht überein."
			)
		open_balance += max(ledger_available, 0.0)
	if any(abs(value) > 0.005 for value in open_by_detail.values()):
		add_reason("Offener Payment-Ledger-Saldo ist keiner unverrechneten Vorschusszeile zugeordnet.")
		open_balance += sum(
			max(value, 0.0)
			for value in open_by_detail.values()
		)
	if open_balance < -0.005 or open_balance > amount + 0.01:
		add_reason("Offener Payment-Ledger-Saldo liegt außerhalb des Sollbetrags.")

	return {
		"reasons": reasons,
		"payable_account": payable_account,
		"open_balance": open_balance,
		"booked_amount": booked_amount,
	}


def _check_payment_plan_allocations(
	issues: list[dict[str, Any]],
	limit: int,
) -> dict[str, Any]:
	allocations = []
	if frappe.db.table_exists("Zahlungsplan Zahlung Zuordnung"):
		allocations = frappe.db.sql(
			"""
			SELECT
				a.name,
				a.parent,
				a.plan_zeile,
				a.payment_entry,
				a.allocated_amount,
				a.consumed_amount,
				a.released_amount,
				a.settlement_invoice,
				z.company,
				z.lieferant,
				p.parent AS row_parent,
				p.betrag AS row_amount,
				pe.docstatus AS pe_docstatus,
				pe.company AS pe_company,
				pe.party_type,
				pe.party,
				pe.payment_type,
				pe.paid_amount,
				pe.unallocated_amount,
				pe.paid_to,
				pe.paid_to_account_currency,
				company.default_currency AS company_currency,
				payable.account_currency AS payable_currency,
				settlement.docstatus AS settlement_docstatus,
				settlement.company AS settlement_company,
				settlement.supplier AS settlement_supplier,
				settlement.currency AS settlement_currency
			FROM `tabZahlungsplan Zahlung Zuordnung` a
			LEFT JOIN `tabZahlungsplan` z ON z.name = a.parent
			LEFT JOIN `tabZahlungsplan Zeile` p ON p.name = a.plan_zeile
			LEFT JOIN `tabPayment Entry` pe ON pe.name = a.payment_entry
			LEFT JOIN `tabCompany` company ON company.name = z.company
			LEFT JOIN `tabAccount` payable ON payable.name = pe.paid_to
			LEFT JOIN `tabPurchase Invoice` settlement
			  ON settlement.name = a.settlement_invoice
			WHERE a.status = 'Aktiv'
			ORDER BY a.modified DESC
			""",
			as_dict=True,
		)
	by_plan_row: dict[tuple[str, str], float] = defaultdict(float)
	reserved_by_payment: dict[str, float] = defaultdict(float)
	payment_unallocated: dict[str, float] = {}
	for row in allocations:
		allocated = flt(row.allocated_amount)
		consumed = flt(row.consumed_amount)
		released = flt(row.released_amount)
		claim = max(allocated - released, 0.0)
		by_plan_row[(row.parent, row.plan_zeile)] += claim
		if not row.settlement_invoice:
			reserved_by_payment[row.payment_entry] += claim
		payment_unallocated[row.payment_entry] = flt(row.unallocated_amount)
		amount_state_invalid = (
			allocated <= 0
			or consumed < -0.005
			or released < -0.005
			or consumed + released > allocated + 0.005
			or (consumed > 0.005 and not row.settlement_invoice)
			or (
				row.settlement_invoice
				and abs(consumed + released - allocated) > 0.005
			)
		)
		settlement_invalid = bool(
			row.settlement_invoice
			and (
				cint(row.settlement_docstatus) != 1
				or row.settlement_company != row.company
				or row.settlement_supplier != row.lieferant
				or row.settlement_currency != row.company_currency
			)
		)
		currency_invalid = bool(
			not row.company_currency
			or (
				row.paid_to_account_currency
				or row.payable_currency
			) != row.company_currency
			or row.payable_currency != row.company_currency
		)
		if (
			not row.row_parent
			or row.row_parent != row.parent
			or cint(row.pe_docstatus) != 1
			or row.pe_company != row.company
			or row.party_type != "Supplier"
			or row.party != row.lieferant
			or row.payment_type != "Pay"
			or amount_state_invalid
			or settlement_invalid
			or currency_invalid
		):
			_issue(
				issues,
				severity="critical",
				code="payment_plan_allocation_invalid",
				doctype="Zahlungsplan Zahlung Zuordnung",
				name=row.name,
				message="Aktive Zahlungszuordnung passt nicht zu Planzeile, Firma oder Lieferant.",
				plan=row.parent,
				payment_entry=row.payment_entry,
				allocated_amount=allocated,
				consumed_amount=consumed,
				released_amount=released,
				settlement_invoice=row.settlement_invoice,
			)
	for row in allocations:
		total = by_plan_row[(row.parent, row.plan_zeile)]
		if total > flt(row.row_amount) + 0.005:
			_issue(
				issues,
				severity="critical",
				code="payment_plan_row_overallocated",
				doctype="Zahlungsplan",
				name=row.parent,
				message=f"Planzeile {row.plan_zeile} ist mit {total:.2f} EUR überbezahlt.",
				plan_row=row.plan_zeile,
				allocated=total,
				planned=flt(row.row_amount),
			)
			by_plan_row[(row.parent, row.plan_zeile)] = float("-inf")
	for payment_entry, total in reserved_by_payment.items():
		if total > payment_unallocated.get(payment_entry, 0.0) + 0.005:
			_issue(
				issues,
				severity="critical",
				code="payment_entry_reserved_above_paid_amount",
				doctype="Payment Entry",
				name=payment_entry,
				message="Zahlungspläne reservieren mehr als das unverrechnete Lieferantenguthaben.",
				reserved=total,
				unallocated_amount=payment_unallocated.get(payment_entry),
			)

	historical_filters = {"vor_systemstart_bezahlt": (">", 0)}
	historical_total = cint(
		frappe.db.count("Zahlungsplan", filters=historical_filters)
	)
	historical_plans = frappe.get_all(
		"Zahlungsplan",
		filters=historical_filters,
		fields=[
			"name",
			"company",
			"lieferant",
			"vor_systemstart_bezahlt",
			"vor_systemstart_buchungsdatum",
			"vor_systemstart_gegenkonto",
			"vor_systemstart_journal_entry",
			"ja_purchase_invoice",
		],
		limit_page_length=limit,
	)
	plans_by_journal: dict[str, list[str]] = defaultdict(list)
	for plan in historical_plans:
		if plan.get("vor_systemstart_journal_entry"):
			plans_by_journal[plan.vor_systemstart_journal_entry].append(plan.name)
	for plan in historical_plans:
		active_invoice = _active_docstatus("Purchase Invoice", plan.ja_purchase_invoice) == 1
		snapshot = _historical_prepayment_snapshot(plan)
		journal_entry = plan.get("vor_systemstart_journal_entry")
		if (
			journal_entry
			and len(plans_by_journal.get(journal_entry, [])) > 1
		):
			snapshot["reasons"].append(
				"Journal Entry ist mehreren Zahlungsplänen zugeordnet."
			)
		if snapshot["reasons"]:
			_issue(
				issues,
				severity="critical" if active_invoice else "high",
				code="historical_prepayment_not_in_ledger",
				doctype="Zahlungsplan",
				name=plan.name,
				message=(
					"Historische Vorzahlung ist nicht exakt als aktiver, "
					"offener Lieferantenvorschuss belegt."
				),
				amount=flt(plan.vor_systemstart_bezahlt),
				journal_entry=journal_entry,
				company=plan.get("company"),
				supplier=plan.get("lieferant"),
				payable_account=snapshot.get("payable_account"),
				open_balance=snapshot.get("open_balance"),
				reasons=snapshot["reasons"],
				active_annual_invoice=active_invoice,
			)
	return _combined_coverage(
		active_payment_allocations=_source_coverage(
			len(allocations),
			len(allocations),
		),
		historical_prepayments=_source_coverage(
			historical_total,
			len(historical_plans),
		),
	)


def _check_proposals_and_credit_rates(
	issues: list[dict[str, Any]],
	limit: int,
) -> dict[str, Any]:
	proposal_total = 0
	if frappe.db.exists("DocType", "Buchungs Vorschlag"):
		proposal_filters = {"status": ("in", ("Ready", "Booked"))}
		proposal_total = cint(
			frappe.db.count(
				"Buchungs Vorschlag",
				filters=proposal_filters,
			)
		)
		proposals = frappe.get_all(
			"Buchungs Vorschlag",
			filters=proposal_filters,
			fields=["name", "status", "linked_purchase_invoice"],
			limit_page_length=limit,
		)
		for proposal in proposals:
			pi_status = _active_docstatus(
				"Purchase Invoice",
				proposal.linked_purchase_invoice,
			)
			if (
				(proposal.status == "Booked" and pi_status != 1)
				or (proposal.status == "Ready" and pi_status == 1)
			):
				_issue(
					issues,
					severity="critical",
					code="booking_proposal_state_mismatch",
					doctype="Buchungs Vorschlag",
					name=proposal.name,
					message="Status und verknüpfte Eingangsrechnung des Buchungsvorschlags sind inkonsistent.",
					status=proposal.status,
					purchase_invoice=proposal.linked_purchase_invoice,
					purchase_invoice_docstatus=pi_status,
				)
	else:
		proposals = []

	rate_filters = {"journal_entry": ("is", "set")}
	rate_total = cint(frappe.db.count("Kreditrate", filters=rate_filters))
	rates = frappe.get_all(
		"Kreditrate",
		filters=rate_filters,
		fields=["name", "parent", "journal_entry", "restschuld_nach"],
		limit_page_length=limit,
	)
	je_to_rates: dict[str, list[str]] = defaultdict(list)
	for rate in rates:
		je_to_rates[rate.journal_entry].append(rate.name)
		if _active_docstatus("Journal Entry", rate.journal_entry) != 1:
			_issue(
				issues,
				severity="critical",
				code="credit_rate_voucher_missing_or_cancelled",
				doctype="Kreditrate",
				name=rate.name,
				message=f"Der verknüpfte Journal Entry {rate.journal_entry} ist nicht aktiv.",
				kreditvertrag=rate.parent,
			)
		if flt(rate.restschuld_nach) < -0.005:
			_issue(
				issues,
				severity="critical",
				code="credit_negative_remaining_principal",
				doctype="Kreditrate",
				name=rate.name,
				message="Die berechnete Restschuld ist negativ.",
				restschuld=flt(rate.restschuld_nach),
			)
	for journal_entry, rate_names in je_to_rates.items():
		if len(rate_names) > 1:
			_issue(
				issues,
				severity="critical",
				code="credit_voucher_linked_multiple_times",
				doctype="Journal Entry",
				name=journal_entry,
				message="Ein Journal Entry ist mehreren Kreditraten zugeordnet.",
				rates=rate_names,
			)
	return _combined_coverage(
		booking_proposals=_source_coverage(proposal_total, len(proposals)),
		credit_rates=_source_coverage(rate_total, len(rates)),
	)


@frappe.whitelist()
def run_booking_integrity_audit(limit: int = 1000) -> dict[str, Any]:
	"""Run read-only checks. This function never repairs or books anything."""
	frappe.only_for("System Manager")
	safe_limit = max(1, min(cint(limit) or 1000, 5000))
	issues: list[dict[str, Any]] = []
	failed_checks: list[dict[str, str]] = []
	coverage: dict[str, dict[str, Any]] = {}
	checks = (
		("contracts_and_rent_invoices", _check_contract_and_rent_invoice_identity),
		("rent_invoice_ledger_dimensions", _check_rent_invoice_ledger_dimensions),
		("bank_links", _check_bank_links),
		("payment_plans", _check_payment_plan_allocations),
		("proposals_and_credit_rates", _check_proposals_and_credit_rates),
	)
	for name, check in checks:
		issues_before = len(issues)
		try:
			check_coverage = check(issues, safe_limit) or {
				"complete": False,
				"truncated": True,
				"error": "Check lieferte keine Coverage-Metadaten.",
			}
			check_coverage["reported_issue_count"] = (
				len(issues) - issues_before
			)
			coverage[name] = check_coverage
		except Exception as exc:
			failed_checks.append({"check": name, "error": str(exc)})
			coverage[name] = {
				"complete": False,
				"truncated": False,
				"reported_issue_count": len(issues) - issues_before,
				"error": str(exc),
			}

	severity_order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
	issues.sort(
		key=lambda row: (
			severity_order.get(row["severity"], 99),
			row["code"],
			row["doctype"],
			row["name"],
		)
	)
	truncated = any(
		check_coverage.get("truncated", False)
		for check_coverage in coverage.values()
	)
	complete = bool(
		not failed_checks
		and coverage
		and all(
			check_coverage.get("complete", False)
			for check_coverage in coverage.values()
		)
	)
	return {
		# A bounded scan must never be presented as clean. Coverage exposes the
		# exact total and remaining tail so operational callers can explicitly
		# distinguish "clean" from "not fully checked".
		"ok": complete and not issues,
		"read_only": True,
		"complete": complete,
		"truncated": truncated,
		"limit": safe_limit,
		"coverage": coverage,
		"issue_count": len(issues),
		"issue_count_is_complete": complete,
		"critical_count": sum(1 for row in issues if row["severity"] == "critical"),
		"high_count": sum(1 for row in issues if row["severity"] == "high"),
		"failed_checks": failed_checks,
		"issues": issues,
	}


@frappe.whitelist()
def run_booking_integrity_audit_summary(limit: int = 1000) -> dict[str, Any]:
	"""Return compact counts and samples for operational/CLI checks."""
	result = run_booking_integrity_audit(limit=limit)
	issues = result.pop("issues")
	result["counts_by_code"] = dict(
		sorted(Counter(row["code"] for row in issues).items())
	)
	result["samples"] = issues[:20]
	return result
