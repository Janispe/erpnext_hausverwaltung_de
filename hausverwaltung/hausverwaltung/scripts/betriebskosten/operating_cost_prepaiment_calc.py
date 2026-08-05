from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import getdate


BK_ITEM_CODE = "Betriebskosten"
HK_ITEM_CODE = "Heizkosten"

MONEY_QUANT = Decimal("0.01")


def _to_decimal(value: Any) -> Decimal:
	if isinstance(value, Decimal):
		return value
	if value in (None, ""):
		return Decimal("0")
	try:
		return Decimal(str(value))
	except Exception:
		return Decimal("0")


def _quantize_money(value: Decimal) -> Decimal:
	return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _as_money(value: Decimal) -> float:
	return float(_quantize_money(value))


def _date_range(from_date: Optional[str | date], to_date: Optional[str | date]) -> Tuple[Optional[str], Optional[str]]:
	"""Normalisiere from/to in YYYY-MM-DD Strings (oder None)."""
	fd = getdate(from_date).strftime("%Y-%m-%d") if from_date else None
	td = getdate(to_date).strftime("%Y-%m-%d") if to_date else None
	return fd, td


def _invoice_effective_date_expr(alias: str = "si") -> str:
	"""SQL-Expression für das effektive Belegdatum (Wertstellung oder Posting)."""
	return f"COALESCE({alias}.custom_wertstellungsdatum, {alias}.posting_date)"


def _payment_effective_date_expr(alias: str = "pe") -> str:
	"""SQL-Expression für das effektive Zahlungsdatum (Wertstellung oder Posting)."""
	return f"COALESCE({alias}.custom_wertstellungsdatum, {alias}.posting_date)"


def _customer_segments_for_wohnung(wohnung: str, from_date: Optional[str | date], to_date: Optional[str | date]) -> List[Dict[str, Any]]:
	"""Hole Mieter aus Mietverträgen der Wohnung, zugeschnitten auf den Zeitraum.

	Rückgabe: Liste von Segmenten [{customer, start, end}]. start/end sind Strings YYYY-MM-DD oder None.
	Nur überlappende Verträge werden berücksichtigt und auf [from_date, to_date] geclippt.
	"""
	# Fachliche Annahme: Customer ist die Abrechnungseinheit pro Mietvertrag/Wohnung.
	# Wenn dieselbe Person mehrere Wohnungen mietet, bekommt sie mehrere Customer.
	# Deshalb reicht customer + Zeitraum + Item-Code fuer BK/HK-Vorauszahlungen.
	# Ohne Zeitraum: wir nehmen volle Vertragszeiträume
	fd = getdate(from_date) if from_date else None
	td = getdate(to_date) if to_date else None

	# Verträge mit Überlappung holen (ähnlich Report)
	where = ["wohnung = %(whg)s"]
	params: Dict[str, Any] = {"whg": wohnung}
	if td:
		where.append("von <= %(td)s")
		params["td"] = td
	if fd:
		where.append("(bis IS NULL OR bis >= %(fd)s)")
		params["fd"] = fd

	rows = frappe.db.sql(
		f"""
		SELECT kunde, von, bis
		FROM `tabMietvertrag`
		WHERE {' AND '.join(where)}
		ORDER BY von ASC
		""",
		params,
		as_dict=True,
	)

	segments: List[Dict[str, Any]] = []
	for r in rows or []:
		cust = r.get("kunde")
		if not cust:
			continue
		v_start = getdate(r.get("von")) if r.get("von") else None
		v_end = getdate(r.get("bis")) if r.get("bis") else None

		# clip an Anfragefenster
		start = v_start
		end = v_end
		if fd and (not start or fd > start):
			start = fd
		if td:
			if end:
				end = td if td < end else end
			else:
				end = td
		if start and end and start > end:
			continue
		segments.append(
			{
				"customer": cust,
				"start": start.strftime("%Y-%m-%d") if start else None,
				"end": end.strftime("%Y-%m-%d") if end else None,
			}
		)
	return segments


def _invoice_segments_for_wohnung(
	wohnung: str,
	from_date: Optional[str | date],
	to_date: Optional[str | date],
	customer: Optional[str] = None,
) -> List[Dict[str, Any]]:
	"""Rechnungsfilter für Vorauszahlungen.

	Bei einer konkreten Mieterabrechnung gilt der gesamte Abrechnungszeitraum;
	der Customer trennt die Vorauszahlungen der aufeinanderfolgenden Mieter.
	Ohne Customer bleibt die bisherige wohnungsweite Vertragssegment-Logik.
	"""
	if not customer:
		return _customer_segments_for_wohnung(wohnung, from_date, to_date)

	contract_segments = _customer_segments_for_wohnung(wohnung, from_date, to_date)
	if customer not in {segment.get("customer") for segment in contract_segments}:
		return []

	fd, td = _date_range(from_date, to_date)
	return [{"customer": customer, "start": fd, "end": td}]


_MONTH_TOKEN_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{4})$")
_MV_MARKER_RE = re.compile(r"\[MV:([^\]]+)\]")
_MV_PERIOD_MARKER_RE = re.compile(r"\[MV:([^\]]+)\]\s+(\d{2}/\d{4})")


def _structured_contract_sql(alias: str) -> str:
	"""Extract the contract part before the last ``|`` from a billing id."""
	return f"""
		CASE
			WHEN INSTR(COALESCE({alias}.mietabrechnung_id, ''), '|') > 0
			THEN LEFT(
				{alias}.mietabrechnung_id,
				CHAR_LENGTH({alias}.mietabrechnung_id)
				- CHAR_LENGTH(SUBSTRING_INDEX({alias}.mietabrechnung_id, '|', -1))
				- 1
			)
			ELSE NULL
		END
	"""


def _segment_invoice_predicates(alias: str, segments: List[Dict[str, Any]]) -> List[str]:
	effective_date = _invoice_effective_date_expr(alias)
	predicates: List[str] = []
	for i, segment in enumerate(segments):
		start = segment.get("start")
		end = segment.get("end")
		if start and end:
			predicates.append(
				f"({alias}.customer = %(c{i})s AND "
				f"{effective_date} BETWEEN %(f{i})s AND %(t{i})s)"
			)
		elif start:
			predicates.append(
				f"({alias}.customer = %(c{i})s AND {effective_date} >= %(f{i})s)"
			)
		elif end:
			predicates.append(
				f"({alias}.customer = %(c{i})s AND {effective_date} <= %(t{i})s)"
			)
		else:
			predicates.append(f"({alias}.customer = %(c{i})s)")
	return predicates


def _parse_month_token(token: str, *, invoice_name: str, source: str) -> Optional[date]:
	token = (token or "").strip()
	if not token:
		return None
	match = _MONTH_TOKEN_RE.fullmatch(token)
	if not match:
		frappe.throw(
			f"Sales Invoice {invoice_name} enthält einen ungültigen "
			f"Abrechnungsmonat in {source}: {token}. Buchung abgebrochen."
		)
	return date(int(match.group(2)), int(match.group(1)), 1)


def _period_overlaps(
	month_start: Optional[date],
	effective_date: Any,
	from_date: Optional[str | date],
	to_date: Optional[str | date],
) -> bool:
	start = getdate(from_date) if from_date else None
	end = getdate(to_date) if to_date else None
	if month_start:
		if month_start.month == 12:
			month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
		else:
			month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
		return (not start or month_end >= start) and (not end or month_start <= end)
	if not effective_date:
		return False
	value = getdate(effective_date)
	return (not start or value >= start) and (not end or value <= end)


def _invoice_identity_evidence(
	row: Dict[str, Any],
	*,
	prefix: str,
	invoice_name: str,
	contract_cache: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
	"""Resolve one invoice's exact contract, apartment, customer and period.

	``prefix`` is empty for the selected document and ``return_source_`` for
	the document referenced through ``return_against``.
	"""
	def field(name: str) -> Any:
		if prefix:
			return row.get(f"{prefix}{name}")
		if name == "customer":
			return row.get("invoice_customer")
		return row.get(name)

	structured_id = str(field("mietabrechnung_id") or "").strip()
	structured_contract = ""
	structured_month: Optional[date] = None
	if structured_id:
		if "|" not in structured_id:
			frappe.throw(
				f"Sales Invoice {invoice_name} enthält eine nicht auflösbare "
				"mietabrechnung_id. Buchung abgebrochen."
			)
		structured_contract, _separator, month_token = structured_id.rpartition("|")
		structured_contract = structured_contract.strip()
		if not structured_contract:
			frappe.throw(
				f"Sales Invoice {invoice_name} enthält keinen Mietvertrag in "
				"mietabrechnung_id. Buchung abgebrochen."
			)
		structured_month = _parse_month_token(
			month_token,
			invoice_name=invoice_name,
			source="mietabrechnung_id",
		)

	remarks = str(field("remarks") or "")
	marker_names = {
		value.strip()
		for value in _MV_MARKER_RE.findall(remarks)
		if value.strip()
	}
	if len(marker_names) > 1:
		frappe.throw(
			f"Sales Invoice {invoice_name} enthält mehrere Mietvertragsmarker. "
			"Buchung abgebrochen."
		)
	marker_contract = next(iter(marker_names), "")
	marker_periods = {
		_parse_month_token(
			month_token,
			invoice_name=invoice_name,
			source="Mietvertragsmarker",
		)
		for _marker_contract, month_token in _MV_PERIOD_MARKER_RE.findall(remarks)
	}
	marker_periods.discard(None)
	if len(marker_periods) > 1:
		frappe.throw(
			f"Sales Invoice {invoice_name} enthält mehrere Abrechnungsmonate. "
			"Buchung abgebrochen."
		)
	marker_month = next(iter(marker_periods), None)

	contract_names = {
		value
		for value in (structured_contract, marker_contract)
		if value
	}
	if len(contract_names) > 1:
		frappe.throw(
			f"Sales Invoice {invoice_name} enthält widersprüchliche "
			"Mietvertragskennzeichen. Buchung abgebrochen."
		)
	if structured_month and marker_month and structured_month != marker_month:
		frappe.throw(
			f"Sales Invoice {invoice_name} enthält widersprüchliche "
			"Abrechnungsmonate. Buchung abgebrochen."
		)
	contract_name = next(iter(contract_names), "")

	joined_contract = str(field("identity_mietvertrag") or "").strip()
	if joined_contract and contract_name and joined_contract != contract_name:
		frappe.throw(
			f"Sales Invoice {invoice_name} enthält eine widersprüchliche "
			"strukturierte Mietvertragskennung. Buchung abgebrochen."
		)

	contract_identity: Dict[str, Any] = {}
	if contract_name:
		if contract_name not in contract_cache:
			joined_identity = {}
			if joined_contract == contract_name:
				joined_identity = {
					"wohnung": field("identity_wohnung"),
					"kunde": field("identity_customer"),
				}
			if not (joined_identity.get("wohnung") and joined_identity.get("kunde")):
				joined_identity = (
					frappe.db.get_value(
						"Mietvertrag",
						contract_name,
						["wohnung", "kunde"],
						as_dict=True,
					)
					or {}
				)
			contract_cache[contract_name] = joined_identity
		contract_identity = contract_cache[contract_name]
		if not contract_identity.get("wohnung") or not contract_identity.get("kunde"):
			frappe.throw(
				f"Sales Invoice {invoice_name} verweist auf einen nicht eindeutig "
				f"auflösbaren Mietvertrag {contract_name}. Buchung abgebrochen."
			)

	customer_values = {
		str(value).strip()
		for value in (field("customer"), contract_identity.get("kunde"))
		if str(value or "").strip()
	}
	wohnung_values = {
		str(value).strip()
		for value in (field("wohnung"), contract_identity.get("wohnung"))
		if str(value or "").strip()
	}
	if len(customer_values) > 1 or len(wohnung_values) > 1:
		frappe.throw(
			f"Sales Invoice {invoice_name} widerspricht ihrem Mietvertrag "
			"(Customer/Wohnung). Buchung abgebrochen."
		)

	return {
		"contract": contract_name,
		"customer": next(iter(customer_values), ""),
		"wohnung": next(iter(wohnung_values), ""),
		"explicit_month": structured_month or marker_month,
		"effective_date": field("effective_date"),
	}


def _bk_invoice_names_for_wohnung(
	wohnung: str,
	from_date: Optional[str | date],
	to_date: Optional[str | date],
	item_code: str = BK_ITEM_CODE,
	customer: Optional[str] = None,
	mietvertrag: Optional[str] = None,
	company: Optional[str] = None,
	contract_identity: Optional[Dict[str, Any]] = None,
	*,
	lock: bool = False,
) -> List[str]:
	"""Liefert alle Sales Invoice Namen (docstatus=1) für die Wohnung über Mieter/Verträge.

	Eingereichte Returns werden vorzeichenbehaftet Teil derselben Belegmenge.
	Ihre Identität und Periode dürfen über ``return_against`` geerbt werden,
	sofern Quelle und Return nicht widersprüchlich sind. Später gebuchte
	Korrekturen werden über den expliziten Monat in ``mietabrechnung_id`` oder
	``[MV:...] MM/YYYY`` der ursprünglichen Periode zugeordnet.

	Bei einer konkreten Mietvertragsabrechnung reicht für unmarkierte Belege
	die eindeutige Kombination aus Customer und Wohnung. Explizite
	Mietvertragskennzeichen werden weiterhin auf Widersprüche geprüft.
	"""
	locked_contract_identity: Dict[str, Any] = {}
	if contract_identity:
		identity_name = str(contract_identity.get("name") or mietvertrag or "").strip()
		identity_customer = str(contract_identity.get("kunde") or "").strip()
		identity_wohnung = str(contract_identity.get("wohnung") or "").strip()
		if not mietvertrag or identity_name != mietvertrag:
			frappe.throw(
				"Die gesperrte Mietvertragsidentität passt nicht zur "
				"Vorauszahlungsabfrage. Buchung abgebrochen."
			)
		if not identity_customer or not identity_wohnung:
			frappe.throw(
				f"Mietvertrag {mietvertrag} hat keinen eindeutigen Customer "
				"oder keine Wohnung. Buchung abgebrochen."
			)
		if identity_wohnung != wohnung:
			frappe.throw(
				f"Mietvertrag {mietvertrag} gehört zu Wohnung "
				f"{identity_wohnung} statt {wohnung}. Buchung abgebrochen."
			)
		if customer and customer != identity_customer:
			frappe.throw(
				f"Customer {customer} passt nicht zum gesperrten Mietvertrag "
				f"{mietvertrag} ({identity_customer}). Buchung abgebrochen."
			)
		customer = identity_customer
		fd, td = _date_range(from_date, to_date)
		segments = [{"customer": identity_customer, "start": fd, "end": td}]
		locked_contract_identity = {
			"wohnung": identity_wohnung,
			"kunde": identity_customer,
		}
	else:
		segments = _invoice_segments_for_wohnung(
			wohnung,
			from_date,
			to_date,
			customer,
		)
	if not segments:
		return []

	params: Dict[str, Any] = {"bk": item_code, "wohnung": wohnung}
	for i, seg in enumerate(segments):
		params[f"c{i}"] = seg["customer"]
		if seg.get("start"):
			params[f"f{i}"] = seg["start"]
		if seg.get("end"):
			params[f"t{i}"] = seg["end"]

	own_period_candidates = _segment_invoice_predicates("si", segments)
	return_period_candidates = _segment_invoice_predicates("return_source", segments)
	customers = tuple(sorted({str(segment["customer"]) for segment in segments}))
	params["candidate_customers"] = customers

	structured_contract = _structured_contract_sql("si")
	return_structured_contract = _structured_contract_sql("return_source")
	if mietvertrag:
		params["mietvertrag"] = mietvertrag
		params["mietvertrag_marker"] = f"[MV:{mietvertrag}]"
		own_identity_candidate = f"""
			(
				{structured_contract} = %(mietvertrag)s
				OR LOCATE(%(mietvertrag_marker)s, COALESCE(si.remarks, '')) > 0
			)
		"""
		return_identity_candidate = f"""
			(
				{return_structured_contract} = %(mietvertrag)s
				OR LOCATE(%(mietvertrag_marker)s, COALESCE(return_source.remarks, '')) > 0
			)
		"""
	else:
		own_identity_candidate = """
			(
				si.customer IN %(candidate_customers)s
				AND (
					INSTR(COALESCE(si.mietabrechnung_id, ''), '|') > 0
					OR INSTR(COALESCE(si.remarks, ''), '[MV:') > 0
				)
			)
		"""
		return_identity_candidate = """
			(
				return_source.customer IN %(candidate_customers)s
				AND (
					INSTR(COALESCE(return_source.mietabrechnung_id, ''), '|') > 0
					OR INSTR(COALESCE(return_source.remarks, ''), '[MV:') > 0
				)
			)
		"""

	sql = f"""
		SELECT
			si.name,
			si.customer AS invoice_customer,
			si.company,
			si.wohnung,
			si.mietabrechnung_id,
			si.remarks,
			si.is_return,
			si.return_against,
			{_invoice_effective_date_expr("si")} AS effective_date,
			identity_mv.name AS identity_mietvertrag,
			identity_mv.wohnung AS identity_wohnung,
			identity_mv.kunde AS identity_customer,
			return_source.name AS return_source_name,
			return_source.docstatus AS return_source_docstatus,
			return_source.is_return AS return_source_is_return,
			return_source.customer AS return_source_customer,
			return_source.company AS return_source_company,
			return_source.wohnung AS return_source_wohnung,
			return_source.mietabrechnung_id AS return_source_mietabrechnung_id,
			return_source.remarks AS return_source_remarks,
			{_invoice_effective_date_expr("return_source")} AS return_source_effective_date,
			return_identity_mv.name AS return_source_identity_mietvertrag,
			return_identity_mv.wohnung AS return_source_identity_wohnung,
			return_identity_mv.kunde AS return_source_identity_customer,
			CASE WHEN EXISTS (
				SELECT 1
				FROM `tabSales Invoice Item` return_item
				WHERE return_item.parent = return_source.name
				  AND return_item.item_code = %(bk)s
			) THEN 1 ELSE 0 END AS return_source_has_item
		FROM `tabSales Invoice` si
		LEFT JOIN `tabMietvertrag` identity_mv
		  ON identity_mv.name = {structured_contract}
		LEFT JOIN `tabSales Invoice` return_source
		  ON return_source.name = si.return_against
		LEFT JOIN `tabMietvertrag` return_identity_mv
		  ON return_identity_mv.name = {return_structured_contract}
		WHERE si.docstatus = 1
		  AND EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.item_code = %(bk)s)
		  AND (
				({' OR '.join(own_period_candidates)})
				OR (si.is_return = 1 AND ({' OR '.join(return_period_candidates)}))
				OR {own_identity_candidate}
				OR (si.is_return = 1 AND {return_identity_candidate})
		  )
		ORDER BY si.name
	"""
	if lock:
		sql += "\nFOR UPDATE"
	rows = frappe.db.sql(sql, params, as_dict=True)
	selected: List[str] = []
	missing_apartment: List[str] = []
	contract_cache: Dict[str, Dict[str, Any]] = {}
	if mietvertrag and locked_contract_identity:
		contract_cache[mietvertrag] = locked_contract_identity
	expected_customers = set(customers)
	expected_company = str(company or "").strip()
	for row in rows or []:
		name = str(row.get("name") or "").strip()
		own = _invoice_identity_evidence(
			row,
			prefix="",
			invoice_name=name,
			contract_cache=contract_cache,
		)
		effective = own

		if int(row.get("is_return") or 0):
			return_against = str(row.get("return_against") or "").strip()
			if return_against:
				source_name = str(row.get("return_source_name") or "").strip()
				if (
					source_name != return_against
					or int(row.get("return_source_docstatus") or 0) != 1
					or int(row.get("return_source_is_return") or 0)
					or not int(row.get("return_source_has_item") or 0)
				):
					frappe.throw(
						f"Return {name} kann über return_against "
						f"{return_against} nicht eindeutig als {item_code}-"
						"Vorauszahlung aufgelöst werden. Buchung abgebrochen."
					)
				source = _invoice_identity_evidence(
					row,
					prefix="return_source_",
					invoice_name=return_against,
					contract_cache=contract_cache,
				)
				for key, label in (
					("contract", "Mietvertrag"),
					("customer", "Customer"),
					("wohnung", "Wohnung"),
				):
					if own.get(key) and source.get(key) and own[key] != source[key]:
						frappe.throw(
							f"Return {name} widerspricht return_against "
							f"{return_against} ({label}). Buchung abgebrochen."
						)
				if (
					own.get("explicit_month")
					and source.get("explicit_month")
					and own["explicit_month"] != source["explicit_month"]
				):
					frappe.throw(
						f"Return {name} widerspricht return_against "
						f"{return_against} (Abrechnungsmonat). "
						"Buchung abgebrochen."
					)
				effective = {
					"contract": own.get("contract") or source.get("contract"),
					"customer": own.get("customer") or source.get("customer"),
					"wohnung": own.get("wohnung") or source.get("wohnung"),
					"explicit_month": (
						own.get("explicit_month") or source.get("explicit_month")
					),
					# Ohne expliziten Abrechnungsmonat ist bei einem Return
					# ausschließlich die Periode des Originals maßgeblich.
					"effective_date": source.get("effective_date"),
				}

		if expected_company:
			invoice_company = str(row.get("company") or "").strip()
			source_company = str(row.get("return_source_company") or "").strip()
			exact_target_contract = bool(
				mietvertrag
				and (
					own.get("contract") == mietvertrag
					or effective.get("contract") == mietvertrag
				)
			)
			if exact_target_contract and invoice_company != expected_company:
				frappe.throw(
					f"Sales Invoice {name} trägt die Company "
					f"{invoice_company or 'leer'} statt {expected_company}, "
					f"obwohl sie Mietvertrag {mietvertrag} eindeutig zugeordnet "
					"ist. Buchung abgebrochen."
				)
			if (
				int(row.get("is_return") or 0)
				and row.get("return_against")
				and effective.get("contract") == mietvertrag
				and source_company != expected_company
			):
				frappe.throw(
					f"Return {name} verweist auf eine Sales Invoice der Company "
					f"{source_company or 'leer'} statt {expected_company}. "
					"Buchung abgebrochen."
				)

		if not _period_overlaps(
			effective.get("explicit_month"),
			effective.get("effective_date"),
			from_date,
			to_date,
		):
			continue
		if effective.get("customer") not in expected_customers:
			# Ein über return_against gefundener Beleg mit abweichendem Customer
			# ist kein still zu ignorierender Kandidat.
			if int(row.get("is_return") or 0):
				frappe.throw(
					f"Return {name} gehört nicht zum erwarteten Customer. "
					"Buchung abgebrochen."
				)
			continue

		if expected_company and str(row.get("company") or "").strip() != expected_company:
			# Nicht exakt zugeordnete Belege einer anderen Company sind kein
			# Teil dieser Abrechnung. Exakte Vertragsbelege wurden oben bereits
			# als Widerspruch fail-closed behandelt.
			continue
		if mietvertrag:
			if effective.get("contract") and effective["contract"] != mietvertrag:
				continue
			if not effective.get("wohnung"):
				missing_apartment.append(name)
				continue
			if effective.get("wohnung") != wohnung:
				frappe.throw(
					f"Sales Invoice {name} und Mietvertrag {mietvertrag} "
					"haben keine identische Wohnung. Buchung abgebrochen."
				)
			selected.append(name)
			continue

		if effective.get("wohnung") == wohnung:
			selected.append(name)

	if missing_apartment:
		frappe.throw(
			f"{item_code}-Vorauszahlungsrechnungen ohne eindeutige "
			"Wohnungskennung "
			f"gefunden: {', '.join(missing_apartment[:5])}. Bitte Datenzuordnung "
			"prüfen; es wurde nichts gebucht."
		)
	return selected


def get_bk_expected_sum(
	wohnung: str,
	from_date: Optional[str | date] = None,
	to_date: Optional[str | date] = None,
	item_code: str = BK_ITEM_CODE,
	customer: Optional[str] = None,
	mietvertrag: Optional[str] = None,
	company: Optional[str] = None,
	contract_identity: Optional[Dict[str, Any]] = None,
) -> float:
	"""Summe der erwarteten Vorauszahlungen über Rechnungen (via Mieter/Verträge).

	- Sales Invoices (docstatus=1), gewünschter ``item_code`` (Default
	  ``BK_ITEM_CODE``; für HK ``HK_ITEM_CODE`` übergeben).
	- Effektives Datum = Wertstellung oder Posting.
	- OR‑Filter über (customer & Zeitraum je Vertrag der Wohnung).
	"""
	names = _bk_invoice_names_for_wohnung(
		wohnung,
		from_date,
		to_date,
		item_code=item_code,
		customer=customer,
		mietvertrag=mietvertrag,
		company=company,
		contract_identity=contract_identity,
	)
	if not names:
		return 0.0
	return get_bk_expected_sum_for_invoice_names(names, item_code=item_code)


def get_bk_expected_sum_for_invoice_names(
	names: List[str],
	item_code: str = BK_ITEM_CODE,
	*,
	lock: bool = False,
) -> float:
	"""Summiert den Soll-Anteil einer bereits eindeutig bestimmten Belegmenge."""
	if not names:
		return 0.0
	lock_clause = " FOR UPDATE" if lock else ""
	sql = f"""
		SELECT
			si.name,
			CASE
				WHEN si.is_return = 1 THEN -ABS(sii.net_amount)
				ELSE sii.net_amount
			END AS bk_amount
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE si.name IN %(names)s
		  AND sii.item_code = %(bk)s
		{lock_clause}
	"""
	rows = frappe.db.sql(
		sql,
		{"bk": item_code, "names": tuple(names)},
		as_dict=True,
	)
	by_invoice: Dict[str, Decimal] = {}
	for row in rows or []:
		name = row.get("name")
		by_invoice[name] = by_invoice.get(name, Decimal("0")) + _to_decimal(
			row.get("bk_amount")
		)
	total = sum(
		(_quantize_money(amount) for amount in by_invoice.values()),
		Decimal("0"),
	)
	return _as_money(total)


def get_bk_paid_sum(
	wohnung: str,
	from_date: Optional[str | date] = None,
	to_date: Optional[str | date] = None,
	item_code: str = BK_ITEM_CODE,
	customer: Optional[str] = None,
) -> float:
	"""Summe der tatsächlich geleisteten Zahlungen für Rechnungen (via Mieter/Verträge).

	- Payment Entries (docstatus=1, payment_type='Receive').
	- Zahlungen im Zeitraum per Zahlungs‑Wertstellung (Fallback Posting).
	- Nur der Anteil der Zahlung, der auf den gewünschten ``item_code``-Positionen
	  der Rechnung entfällt, wird gezählt (proportionaler Anteil:
	  Sum(item net) / Sum(alle net) je Rechnung).
	"""
	eff = _payment_effective_date_expr("pe")
	fd, td = _date_range(from_date, to_date)
	segments = _invoice_segments_for_wohnung(wohnung, from_date, to_date, customer)
	if not segments:
		return 0.0
	customers = sorted({seg["customer"] for seg in segments})

	where: List[str] = [
		"pe.docstatus = 1",
		"pe.payment_type IN ('Receive', 'Pay')",
		"per.reference_doctype = 'Sales Invoice'",
		"si.docstatus = 1",
		"si.wohnung = %(wohnung)s",
		"si.customer IN %(customers)s",
		"EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.item_code = %(bk)s)",
	]
	params: Dict[str, Any] = {"customers": tuple(customers), "bk": item_code, "wohnung": wohnung}
	if fd and td:
		where.append(f"{eff} BETWEEN %(fd)s AND %(td)s")
		params.update({"fd": fd, "td": td})
	elif fd:
		where.append(f"{eff} >= %(fd)s")
		params.update({"fd": fd})
	elif td:
		where.append(f"{eff} <= %(td)s")
		params.update({"td": td})

	sql = f"""
		SELECT COALESCE(SUM(
			CASE WHEN si.is_return = 1 THEN -1 ELSE 1 END
			* ABS(per.allocated_amount)
			* COALESCE(ABS(bki.bk_net) / NULLIF(ABS(tot.total_net), 0), 0)
		), 0)
		FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		JOIN `tabSales Invoice` si ON si.name = per.reference_name
		LEFT JOIN (
			SELECT parent, SUM(net_amount) AS bk_net
			FROM `tabSales Invoice Item`
			WHERE item_code = %(bk)s
			GROUP BY parent
		) bki ON bki.parent = si.name
		LEFT JOIN (
			SELECT parent, SUM(net_amount) AS total_net
			FROM `tabSales Invoice Item`
			GROUP BY parent
		) tot ON tot.parent = si.name
		WHERE {' AND '.join(where)}
	"""
	val = frappe.db.sql(sql, params)[0][0]
	return _as_money(_to_decimal(val))


def get_bk_paid_sum_for_period_invoices(
	wohnung: str,
	from_date: Optional[str | date] = None,
	to_date: Optional[str | date] = None,
	item_code: str = BK_ITEM_CODE,
	customer: Optional[str] = None,
	mietvertrag: Optional[str] = None,
	company: Optional[str] = None,
	contract_identity: Optional[Dict[str, Any]] = None,
) -> float:
	"""Summe der bezahlten Anteile für Rechnungen mit Wertstellung im Zeitraum.

	Fachregel:
	- Relevant sind Rechnungen mit dem gewünschten ``item_code``, deren effektives
	  Rechnungsdatum im Abrechnungszeitraum liegt.
	- Von diesen Rechnungen wird nur der tatsächlich per Payment Entry zugeordnete
	  Anteil dieser Position gezählt.
	- Das Zahlungsdatum selbst spielt keine Rolle.
	"""
	names = _bk_invoice_names_for_wohnung(
		wohnung,
		from_date,
		to_date,
		item_code=item_code,
		customer=customer,
		mietvertrag=mietvertrag,
		company=company,
		contract_identity=contract_identity,
	)
	if not names:
		return 0.0
	return get_bk_paid_sum_for_invoice_names(names, item_code=item_code)


def get_bk_paid_sum_for_invoice_names(
	names: List[str],
	item_code: str = BK_ITEM_CODE,
	*,
	lock: bool = False,
) -> float:
	"""Berechnet den bezahlten BK/HK-Anteil einer exakt bestimmten Belegmenge.

	``lock=True`` erzwingt einen Current Read und sperrt die zugehörigen
	Payment- und Journal-Referenzen bis zum Transaktionsende. Das Settlement
	verwendet dies zusammen mit gesperrten Sales Invoices, damit Zahlung und
	Outstanding aus demselben Buchungsstand stammen.

	Payment Entries werden anhand des Return-Kennzeichens der Rechnung
	vorzeichenbehaftet. Es zählen ausschließlich Zahlungen mit einem eindeutigen
	Bank-/Kassen-Gegenkonto und ohne Differenz-/Abschreibungszeilen. Bei Journal
	Entries ist ``credit - debit`` auf der Debitorenzeile bereits der
	vorzeichenbehaftete Ausgleich; auch dort sind ausschließlich reine
	Bank-/Kassenbuchungen zulässig. Nicht zahlungswirksame Verrechnungen oder
	Abschreibungen führen bewusst zu einem Abbruch, damit sie nie als geleistete
	BK/HK-Vorauszahlung erscheinen.
	"""
	if not names:
		return 0.0
	lock_clause = " FOR UPDATE" if lock else ""
	payment_sql = f"""
		SELECT
			pe.name AS payment_entry,
			pe.company AS payment_company,
			pe.payment_type,
			pe.party_type,
			pe.party,
			pe.paid_from,
			pe.paid_to,
			pe.difference_amount,
			per.allocated_amount,
			si.is_return,
			si.company AS invoice_company,
			si.customer AS invoice_customer,
			si.debit_to AS invoice_receivable,
			paid_from_account.company AS paid_from_company,
			paid_from_account.account_type AS paid_from_type,
			paid_to_account.company AS paid_to_company,
			paid_to_account.account_type AS paid_to_type,
			COALESCE((
				SELECT SUM(ABS(COALESCE(ped.amount, 0)))
				FROM `tabPayment Entry Deduction` ped
				WHERE ped.parent = pe.name
			), 0) AS deduction_amount,
			COALESCE(bki.bk_net, 0) AS bk_net,
			COALESCE(tot.total_net, 0) AS total_net
		FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		JOIN `tabSales Invoice` si ON si.name = per.reference_name
		LEFT JOIN `tabAccount` paid_from_account
			ON paid_from_account.name = pe.paid_from
		LEFT JOIN `tabAccount` paid_to_account
			ON paid_to_account.name = pe.paid_to
		LEFT JOIN (
			SELECT parent, SUM(net_amount) AS bk_net
			FROM `tabSales Invoice Item`
			WHERE item_code = %(bk)s
			GROUP BY parent
		) bki ON bki.parent = si.name
		LEFT JOIN (
			SELECT parent, SUM(net_amount) AS total_net
			FROM `tabSales Invoice Item`
			GROUP BY parent
		) tot ON tot.parent = si.name
		WHERE pe.docstatus = 1
		  AND pe.payment_type IN ('Receive', 'Pay')
		  AND per.reference_doctype = 'Sales Invoice'
		  AND si.docstatus = 1
		  AND si.name IN %(names)s
		{lock_clause}
	"""
	payment_rows = frappe.db.sql(
		payment_sql,
		{"bk": item_code, "names": tuple(names)},
		as_dict=True,
	)
	journal_sql = f"""
		SELECT
			je.name AS journal_entry,
			je.company AS journal_company,
			jea.account,
			jea.party_type,
			jea.party,
			jea.reference_type,
			jea.reference_name,
			jea.debit_in_account_currency,
			jea.credit_in_account_currency,
			si.company AS invoice_company,
			si.customer AS invoice_customer,
			si.debit_to AS invoice_receivable,
			COALESCE((
				SELECT COUNT(*)
				FROM `tabJournal Entry Account` cash_row
				JOIN `tabAccount` cash_account
					ON cash_account.name = cash_row.account
				WHERE cash_row.parent = je.name
				  AND (
					ABS(COALESCE(cash_row.debit_in_account_currency, 0))
					+ ABS(COALESCE(cash_row.credit_in_account_currency, 0))
				  ) > 0
				  AND cash_account.company = je.company
				  AND cash_account.account_type IN ('Bank', 'Cash')
			), 0) AS cash_row_count,
			COALESCE((
				SELECT COUNT(*)
				FROM `tabJournal Entry Account` checked_row
				LEFT JOIN `tabAccount` checked_account
					ON checked_account.name = checked_row.account
				LEFT JOIN `tabSales Invoice` checked_invoice
					ON checked_row.reference_type = 'Sales Invoice'
				   AND checked_invoice.name = checked_row.reference_name
				WHERE checked_row.parent = je.name
				  AND (
					ABS(COALESCE(checked_row.debit_in_account_currency, 0))
					+ ABS(COALESCE(checked_row.credit_in_account_currency, 0))
				  ) > 0
				  AND (
					checked_account.name IS NULL
					OR checked_account.company != je.company
					OR (
						checked_account.account_type IN ('Bank', 'Cash')
						AND (
							COALESCE(checked_row.party_type, '') != ''
							OR COALESCE(checked_row.party, '') != ''
							OR COALESCE(checked_row.reference_type, '') != ''
							OR COALESCE(checked_row.reference_name, '') != ''
						)
					)
					OR (
						checked_account.account_type NOT IN ('Bank', 'Cash')
						AND (
							checked_account.account_type != 'Receivable'
							OR checked_row.party_type != 'Customer'
							OR COALESCE(checked_row.party, '') = ''
							OR checked_row.reference_type != 'Sales Invoice'
							OR COALESCE(checked_row.reference_name, '') = ''
							OR checked_invoice.name IS NULL
							OR checked_invoice.docstatus != 1
							OR checked_invoice.company != je.company
							OR checked_invoice.customer != checked_row.party
							OR checked_invoice.debit_to != checked_row.account
						)
					)
				  )
			), 0) AS invalid_row_count,
			COALESCE(bki.bk_net, 0) AS bk_net,
			COALESCE(tot.total_net, 0) AS total_net
		FROM `tabJournal Entry` je
		JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		JOIN `tabSales Invoice` si ON si.name = jea.reference_name
		LEFT JOIN (
			SELECT parent, SUM(net_amount) AS bk_net
			FROM `tabSales Invoice Item`
			WHERE item_code = %(bk)s
			GROUP BY parent
		) bki ON bki.parent = si.name
		LEFT JOIN (
			SELECT parent, SUM(net_amount) AS total_net
			FROM `tabSales Invoice Item`
			GROUP BY parent
		) tot ON tot.parent = si.name
		WHERE je.docstatus = 1
		  AND jea.reference_type = 'Sales Invoice'
		  AND si.docstatus = 1
		  AND si.name IN %(names)s
		{lock_clause}
	"""
	journal_rows = frappe.db.sql(
		journal_sql,
		{"bk": item_code, "names": tuple(names)},
		as_dict=True,
	)
	total = Decimal("0")
	invalid_payments = set()
	for row in payment_rows or []:
		payment_type = str(row.get("payment_type") or "").strip()
		payment_company = str(row.get("payment_company") or "").strip()
		invoice_company = str(row.get("invoice_company") or "").strip()
		invoice_customer = str(row.get("invoice_customer") or "").strip()
		invoice_receivable = str(row.get("invoice_receivable") or "").strip()
		party_type = str(row.get("party_type") or "").strip()
		party = str(row.get("party") or "").strip()
		paid_from = str(row.get("paid_from") or "").strip()
		paid_to = str(row.get("paid_to") or "").strip()
		paid_from_company = str(row.get("paid_from_company") or "").strip()
		paid_to_company = str(row.get("paid_to_company") or "").strip()
		paid_from_type = str(row.get("paid_from_type") or "").strip()
		paid_to_type = str(row.get("paid_to_type") or "").strip()
		common_valid = (
			payment_company
			and payment_company == invoice_company
			and party_type == "Customer"
			and party
			and party == invoice_customer
			and invoice_receivable
			and _to_decimal(row.get("difference_amount")).copy_abs() < MONEY_QUANT
			and _to_decimal(row.get("deduction_amount")).copy_abs() < MONEY_QUANT
		)
		if payment_type == "Receive":
			direction_valid = (
				paid_from == invoice_receivable
				and paid_from_company == payment_company
				and paid_from_type == "Receivable"
				and paid_to_company == payment_company
				and paid_to_type in {"Bank", "Cash"}
			)
		elif payment_type == "Pay":
			direction_valid = (
				paid_to == invoice_receivable
				and paid_to_company == payment_company
				and paid_to_type == "Receivable"
				and paid_from_company == payment_company
				and paid_from_type in {"Bank", "Cash"}
			)
		else:
			direction_valid = False
		if not common_valid or not direction_valid:
			invalid_payments.add(str(row.get("payment_entry") or "?"))
			continue
		total_net = _to_decimal(row.get("total_net"))
		if total_net == 0:
			continue
		item_share = _to_decimal(row.get("bk_net")).copy_abs() / total_net.copy_abs()
		signed_allocation = _to_decimal(row.get("allocated_amount")).copy_abs()
		if int(row.get("is_return") or 0):
			signed_allocation = -signed_allocation
		total += signed_allocation * item_share
	if invalid_payments:
		frappe.throw(
			"BK/HK-Abrechnung abgebrochen: Folgende Payment Entries enthalten "
			"keinen eindeutig nachweisbaren reinen Bank-/Kassenfluss oder "
			"enthalten Differenzen/Abschreibungen: "
			f"{', '.join(sorted(invalid_payments))}.",
			frappe.ValidationError,
		)

	invalid_journals = set()
	for row in journal_rows or []:
		journal_company = str(row.get("journal_company") or "").strip()
		if (
			not journal_company
			or journal_company != str(row.get("invoice_company") or "").strip()
			or str(row.get("account") or "").strip()
			!= str(row.get("invoice_receivable") or "").strip()
			or str(row.get("party_type") or "").strip() != "Customer"
			or str(row.get("party") or "").strip()
			!= str(row.get("invoice_customer") or "").strip()
			or str(row.get("reference_type") or "").strip() != "Sales Invoice"
			or int(row.get("cash_row_count") or 0) < 1
			or int(row.get("invalid_row_count") or 0) != 0
		):
			invalid_journals.add(str(row.get("journal_entry") or "?"))
			continue
		total_net = _to_decimal(row.get("total_net"))
		if total_net == 0:
			continue
		item_share = _to_decimal(row.get("bk_net")).copy_abs() / total_net.copy_abs()
		signed_allocation = (
			_to_decimal(row.get("credit_in_account_currency"))
			- _to_decimal(row.get("debit_in_account_currency"))
		)
		total += signed_allocation * item_share
	if invalid_journals:
		frappe.throw(
			"BK/HK-Abrechnung abgebrochen: Folgende Journal Entries sind keine "
			"reinen Bank-/Kassenbuchungen und dürfen deshalb nicht als "
			"Vorauszahlung zählen: "
			f"{', '.join(sorted(invalid_journals))}.",
			frappe.ValidationError,
		)
	return _as_money(total)


def get_bk_invoice_details(
	wohnung: str,
	from_date: Optional[str | date] = None,
	to_date: Optional[str | date] = None,
	item_code: str = BK_ITEM_CODE,
	customer: Optional[str] = None,
	mietvertrag: Optional[str] = None,
	company: Optional[str] = None,
	contract_identity: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
	"""Details je Rechnung (Name, effektives Datum, Netto-Betrag der item_code-Position, Outstanding), via Mieter/Verträge."""
	names = _bk_invoice_names_for_wohnung(
		wohnung,
		from_date,
		to_date,
		item_code=item_code,
		customer=customer,
		mietvertrag=mietvertrag,
		company=company,
		contract_identity=contract_identity,
	)
	if not names:
		return []
	eff = _invoice_effective_date_expr("si")
	sql = f"""
		SELECT
			si.name,
			si.is_return,
			{eff} AS effective_date,
			si.posting_date,
			si.custom_wertstellungsdatum,
			CASE
				WHEN si.is_return = 1 THEN -ABS(si.outstanding_amount)
				ELSE si.outstanding_amount
			END AS outstanding_amount,
			COALESCE(SUM(
				CASE
					WHEN si.is_return = 1 THEN -ABS(sii.net_amount)
					ELSE sii.net_amount
				END
			), 0) AS bk_amount
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE si.name in %(names)s AND sii.item_code = %(bk)s
		GROUP BY si.name
		ORDER BY effective_date ASC, si.name ASC
	"""
	rows = frappe.db.sql(sql, {"names": tuple(names), "bk": item_code}, as_dict=True)
	# cast types
	for r in rows:
		r["bk_amount"] = _as_money(_to_decimal(r.get("bk_amount")))
		r["outstanding_amount"] = _as_money(_to_decimal(r.get("outstanding_amount")))
	return rows


@frappe.whitelist()
def get_bk_prepayment_summary(
	wohnung: str,
	from_date: Optional[str | date] = None,
	to_date: Optional[str | date] = None,
	customer: Optional[str] = None,
	mietvertrag: Optional[str] = None,
	company: Optional[str] = None,
	contract_identity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
	"""Kompakte Auswertung der BK‑Vorauszahlungen für eine Wohnung.

	Rückgabe:
	{
	  expected_total: float,   # Summe der BK‑Rechnungspositionen (netto) im Zeitraum
	  paid_total: float,       # Summe der zugeordneten Zahlungen im Zeitraum
	  balance: float,          # paid_total - expected_total
	  invoices: [...],         # Detail je Rechnung (siehe get_bk_invoice_details)
	}
	"""
	expected_dec = _quantize_money(
		_to_decimal(
			get_bk_expected_sum(
				wohnung,
				from_date,
				to_date,
				customer=customer,
				mietvertrag=mietvertrag,
				company=company,
				contract_identity=contract_identity,
			)
		)
	)
	paid_dec = _quantize_money(
		_to_decimal(
			get_bk_paid_sum_for_period_invoices(
				wohnung,
				from_date,
				to_date,
				customer=customer,
				mietvertrag=mietvertrag,
				company=company,
				contract_identity=contract_identity,
			)
		)
	)
	details = get_bk_invoice_details(
		wohnung,
		from_date,
		to_date,
		customer=customer,
		mietvertrag=mietvertrag,
		company=company,
		contract_identity=contract_identity,
	)
	return {
		"wohnung": wohnung,
		"customer": customer,
		"mietvertrag": mietvertrag,
		"from_date": getdate(from_date).strftime("%Y-%m-%d") if from_date else None,
		"to_date": getdate(to_date).strftime("%Y-%m-%d") if to_date else None,
		"expected_total": _as_money(expected_dec),
		"paid_total": _as_money(paid_dec),
		"balance": _as_money(_quantize_money(paid_dec - expected_dec)),
		"invoices": details,
	}


def _clip_to_contract_range(mv: Dict[str, Any], from_date: Optional[str | date], to_date: Optional[str | date]) -> Tuple[Optional[str], Optional[str]]:
	"""Schneidet [from_date, to_date] an die Vertragslaufzeit [von, bis] an."""
	start = getdate(from_date) if from_date else None
	end = getdate(to_date) if to_date else None
	v_start = getdate(mv.get("von")) if mv.get("von") else None
	v_end = getdate(mv.get("bis")) if mv.get("bis") else None

	# Max(start, v_start)
	if v_start:
		start = v_start if (start is None or v_start > start) else start
	# Min(end, v_end)
	if v_end:
		end = v_end if (end is None or v_end < end) else end

	if start and end and start > end:
		return None, None
	return (start.strftime("%Y-%m-%d") if start else None, end.strftime("%Y-%m-%d") if end else None)


def _calc_vorauszahlungen(
	mietvertrag: str,
	from_date: Optional[str | date],
	to_date: Optional[str | date],
	item_code: str,
) -> Dict[str, Any]:
	"""Generische Vorauszahlungs-Berechnung über einen Item-Code.

	- Ermittelt die zugehörige Wohnung und Vertragslaufzeit.
	- Prüft, dass der Abrechnungszeitraum den Vertrag überlappt.
	- Nutzt für Rechnungen trotzdem den gesamten Abrechnungszeitraum und
	  trennt die Mieter über den Customer:
	  Rechnungs-Wertstellung bestimmt die Periode, gezählt wird nur bezahlter
	  Anteil der jeweiligen Item-Code-Position.
	Rückgabe: { expected_total, actual_total }
	"""
	mv = frappe.db.get_value("Mietvertrag", mietvertrag, ["wohnung", "von", "bis", "kunde"], as_dict=True)
	if not mv:
		return {"expected_total": 0.0, "actual_total": 0.0}
	whg = mv.get("wohnung")
	if not whg:
		return {"expected_total": 0.0, "actual_total": 0.0}

	fd, td = _clip_to_contract_range(mv, from_date, to_date)
	if fd is None and td is None:
		# kein Überlapp mit Vertragszeitraum
		return {"expected_total": 0.0, "actual_total": 0.0}
	invoice_from = from_date or fd
	invoice_to = to_date or td

	expected = _quantize_money(
		_to_decimal(
			get_bk_expected_sum(
				whg,
				invoice_from,
				invoice_to,
				item_code=item_code,
				customer=mv.get("kunde"),
				mietvertrag=mietvertrag,
			)
		)
	)
	paid = _quantize_money(
		_to_decimal(
			get_bk_paid_sum_for_period_invoices(
				whg,
				invoice_from,
				invoice_to,
				item_code=item_code,
				customer=mv.get("kunde"),
				mietvertrag=mietvertrag,
			)
		)
	)
	return {"expected_total": _as_money(expected), "actual_total": _as_money(paid)}


def calc_bk_vorauszahlungen(mietvertrag: str, from_date: Optional[str | date], to_date: Optional[str | date]) -> Dict[str, Any]:
	"""Ermittelt erwartete/geleistete BK-Vorauszahlungen für einen Mietvertrag."""
	return _calc_vorauszahlungen(mietvertrag, from_date, to_date, item_code=BK_ITEM_CODE)


def calc_hk_vorauszahlungen(mietvertrag: str, from_date: Optional[str | date], to_date: Optional[str | date]) -> Dict[str, Any]:
	"""Ermittelt erwartete/geleistete HK-Vorauszahlungen für einen Mietvertrag.

	Identisches Verfahren wie ``calc_bk_vorauszahlungen``, nur mit Item-Code
	``Heizkosten`` statt ``Betriebskosten``. Quelle sind die monatlichen
	Mietrechnungen — die Heizkosten-Position pro Rechnung wird per
	``custom_wertstellungsdatum`` (= Leistungszeitraum) dem Abrechnungs-
	zeitraum zugeordnet, und nur tatsächlich bezahlter Anteil zählt.
	"""
	return _calc_vorauszahlungen(mietvertrag, from_date, to_date, item_code=HK_ITEM_CODE)
