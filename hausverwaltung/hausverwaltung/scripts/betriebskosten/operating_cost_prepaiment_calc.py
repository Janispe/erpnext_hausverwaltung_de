from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import getdate


BK_ITEM_CODE = "Betriebskosten"

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


def _bk_invoice_names_for_wohnung(wohnung: str, from_date: Optional[str | date], to_date: Optional[str | date]) -> List[str]:
	"""Liefert alle Sales Invoice Namen (docstatus=1) für die Wohnung über Mieter/Verträge.

	Filter: Artikel 'Betriebskosten' UND (OR über (customer & effektives Datum in Segment)).
	"""
	eff = _invoice_effective_date_expr("si")
	segments = _customer_segments_for_wohnung(wohnung, from_date, to_date)
	if not segments:
		return []

	ors: List[str] = []
	params: Dict[str, Any] = {"bk": BK_ITEM_CODE}
	for i, seg in enumerate(segments):
		c = seg["customer"]
		f = seg.get("start")
		t = seg.get("end")
		if f and t:
			ors.append(f"(si.customer = %(c{i})s AND {eff} BETWEEN %(f{i})s AND %(t{i})s)")
			params.update({f"c{i}": c, f"f{i}": f, f"t{i}": t})
		elif f:
			ors.append(f"(si.customer = %(c{i})s AND {eff} >= %(f{i})s)")
			params.update({f"c{i}": c, f"f{i}": f})
		elif t:
			ors.append(f"(si.customer = %(c{i})s AND {eff} <= %(t{i})s)")
			params.update({f"c{i}": c, f"t{i}": t})
		else:
			ors.append(f"(si.customer = %(c{i})s)")
			params.update({f"c{i}": c})

	sql = f"""
		SELECT si.name
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1
		  AND EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.item_code = %(bk)s)
		  AND ({' OR '.join(ors)})
	"""
	return [r[0] for r in frappe.db.sql(sql, params)]


def get_bk_expected_sum(wohnung: str, from_date: Optional[str | date] = None, to_date: Optional[str | date] = None) -> float:
	"""Summe der erwarteten BK-Vorauszahlungen über Rechnungen (via Mieter/Verträge).

	- Sales Invoices (docstatus=1), Artikel 'Betriebskosten'.
	- Effektives Datum = Wertstellung oder Posting.
	- OR‑Filter über (customer & Zeitraum je Vertrag der Wohnung).
	"""
	eff = _invoice_effective_date_expr("si")
	segments = _customer_segments_for_wohnung(wohnung, from_date, to_date)
	if not segments:
		return 0.0

	ors: List[str] = []
	params: Dict[str, Any] = {"bk": BK_ITEM_CODE}
	for i, seg in enumerate(segments):
		c = seg["customer"]
		f = seg.get("start")
		t = seg.get("end")
		if f and t:
			ors.append(f"(si.customer = %(c{i})s AND {eff} BETWEEN %(f{i})s AND %(t{i})s)")
			params.update({f"c{i}": c, f"f{i}": f, f"t{i}": t})
		elif f:
			ors.append(f"(si.customer = %(c{i})s AND {eff} >= %(f{i})s)")
			params.update({f"c{i}": c, f"f{i}": f})
		elif t:
			ors.append(f"(si.customer = %(c{i})s AND {eff} <= %(t{i})s)")
			params.update({f"c{i}": c, f"t{i}": t})
		else:
			ors.append(f"(si.customer = %(c{i})s)")
			params.update({f"c{i}": c})

	sql = f"""
		SELECT
			si.name,
			COALESCE(SUM(sii.net_amount), 0) AS bk_amount
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE si.docstatus = 1
		  AND sii.item_code = %(bk)s
		  AND ({' OR '.join(ors)})
		GROUP BY si.name
	"""
	rows = frappe.db.sql(sql, params, as_dict=True)
	total = Decimal("0")
	for row in rows or []:
		amount = _to_decimal(row.get("bk_amount"))
		total += _quantize_money(amount)
	return _as_money(total)


def get_bk_paid_sum(wohnung: str, from_date: Optional[str | date] = None, to_date: Optional[str | date] = None) -> float:
	"""Summe der tatsächlich geleisteten Zahlungen für BK-Rechnungen (via Mieter/Verträge).

	- Payment Entries (docstatus=1, payment_type='Receive').
	- Zahlungen im Zeitraum per Zahlungs‑Wertstellung (Fallback Posting).
	- Nur der Anteil der Zahlung, der auf BK‑Positionen der Rechnung entfällt, wird gezählt
	  (proportionaler Anteil: Sum(BK net) / Sum(alle net) je Rechnung).
	"""
	eff = _payment_effective_date_expr("pe")
	fd, td = _date_range(from_date, to_date)
	segments = _customer_segments_for_wohnung(wohnung, from_date, to_date)
	if not segments:
		return 0.0
	customers = sorted({seg["customer"] for seg in segments})

	where: List[str] = [
		"pe.docstatus = 1",
		"pe.payment_type = 'Receive'",
		"per.reference_doctype = 'Sales Invoice'",
		"si.docstatus = 1",
		"si.customer IN %(customers)s",
		"EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii WHERE sii.parent = si.name AND sii.item_code = %(bk)s)",
	]
	params: Dict[str, Any] = {"customers": tuple(customers), "bk": BK_ITEM_CODE}
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
		SELECT COALESCE(SUM(per.allocated_amount * COALESCE(bki.bk_net / NULLIF(tot.total_net, 0), 0)), 0)
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
) -> float:
	"""Summe der bezahlten BK-Anteile für Rechnungen mit Wertstellung im Zeitraum.

	Fachregel:
	- Relevant sind BK-Rechnungen, deren effektives Rechnungsdatum im Abrechnungszeitraum liegt.
	- Von diesen Rechnungen wird nur der tatsächlich per Payment Entry zugeordnete BK-Anteil gezählt.
	- Das Zahlungsdatum selbst spielt keine Rolle.
	"""
	names = _bk_invoice_names_for_wohnung(wohnung, from_date, to_date)
	if not names:
		return 0.0

	sql = """
		SELECT COALESCE(
			SUM(per.allocated_amount * COALESCE(bki.bk_net / NULLIF(tot.total_net, 0), 0)),
			0
		)
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
		WHERE pe.docstatus = 1
		  AND pe.payment_type = 'Receive'
		  AND per.reference_doctype = 'Sales Invoice'
		  AND si.docstatus = 1
		  AND si.name IN %(names)s
	"""
	val = frappe.db.sql(sql, {"bk": BK_ITEM_CODE, "names": tuple(names)})[0][0]
	return _as_money(_to_decimal(val))


def get_bk_invoice_details(wohnung: str, from_date: Optional[str | date] = None, to_date: Optional[str | date] = None) -> List[Dict[str, Any]]:
	"""Details je BK-Rechnung (Name, effektives Datum, Netto BK-Betrag, Outstanding), via Mieter/Verträge."""
	names = _bk_invoice_names_for_wohnung(wohnung, from_date, to_date)
	if not names:
		return []
	eff = _invoice_effective_date_expr("si")
	sql = f"""
		SELECT
			si.name,
			{eff} AS effective_date,
			si.posting_date,
			si.custom_wertstellungsdatum,
			si.outstanding_amount,
			COALESCE(SUM(sii.net_amount), 0) AS bk_amount
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE si.name in %(names)s AND sii.item_code = %(bk)s
		GROUP BY si.name
		ORDER BY effective_date ASC, si.name ASC
	"""
	rows = frappe.db.sql(sql, {"names": tuple(names), "bk": BK_ITEM_CODE}, as_dict=True)
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
	expected_dec = _quantize_money(_to_decimal(get_bk_expected_sum(wohnung, from_date, to_date)))
	paid_dec = _quantize_money(_to_decimal(get_bk_paid_sum_for_period_invoices(wohnung, from_date, to_date)))
	details = get_bk_invoice_details(wohnung, from_date, to_date)
	return {
		"wohnung": wohnung,
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


def calc_bk_vorauszahlungen(mietvertrag: str, from_date: Optional[str | date], to_date: Optional[str | date]) -> Dict[str, Any]:
	"""Kompatibilitäts-Funktion: Ermittelt erwartete/geleistete BK‑Vorauszahlungen für einen Mietvertrag.

	- Ermittelt die zugehörige Wohnung und Vertragslaufzeit.
	- Schneidet den angefragten Zeitraum an die Vertragslaufzeit an.
	- Nutzt die per‑Wohnung Logik:
	  Rechnungs-Wertstellung bestimmt die Periode, gezählt wird nur bezahlter BK-Anteil.
	Rückgabe: { expected_total, actual_total }
	"""
	mv = frappe.db.get_value("Mietvertrag", mietvertrag, ["wohnung", "von", "bis"], as_dict=True)
	if not mv:
		return {"expected_total": 0.0, "actual_total": 0.0}
	whg = mv.get("wohnung")
	if not whg:
		return {"expected_total": 0.0, "actual_total": 0.0}

	fd, td = _clip_to_contract_range(mv, from_date, to_date)
	if fd is None and td is None:
		# kein Überlapp mit Vertragszeitraum
		return {"expected_total": 0.0, "actual_total": 0.0}

	expected = _quantize_money(_to_decimal(get_bk_expected_sum(whg, fd, td)))
	paid = _quantize_money(_to_decimal(get_bk_paid_sum_for_period_invoices(whg, fd, td)))
	return {"expected_total": _as_money(expected), "actual_total": _as_money(paid)}
