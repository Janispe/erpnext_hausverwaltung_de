from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, get_last_day, getdate

INVOICE_TYPES = ("Miete", "Betriebskosten", "Heizkosten")
ITEM_CODE_BY_TYP = {
    "Miete": "Miete",
    "Betriebskosten": "Betriebskosten",
    "Heizkosten": "Heizkosten",
}
SUM_TOLERANCE = 0.01


def execute(filters=None):
    filters = frappe._dict(filters or {})

    company = filters.get("company")
    if not company:
        frappe.throw(_("Bitte eine Firma wählen."))

    from_month = _normalize_month_start(filters.get("from_month"))
    to_month = _normalize_month_start(filters.get("to_month"))

    if not from_month or not to_month:
        frappe.throw(_("Bitte Zeitraum mit Von-Monat und Bis-Monat wählen."))

    if from_month > to_month:
        frappe.throw(_("Von-Monat darf nicht nach Bis-Monat liegen."))

    show_ok_rows = cint(filters.get("show_ok_rows") or 0)
    only_issues = cint(filters.get("only_issues") if filters.get("only_issues") is not None else 1)

    month_starts = _iter_month_starts(from_month, to_month)
    period_start = from_month
    period_end = get_last_day(to_month)

    contracts = _get_contracts(period_start=period_start, period_end=period_end)
    staffel_by_contract = _get_staffelmieten_by_contract([c.name for c in contracts])

    rows = []
    for month_start in month_starts:
        active_contracts = [c for c in contracts if _contract_overlaps_month(c, month_start)]
        customers = {str(c.get("kunde") or "").strip() for c in active_contracts if c.get("kunde")}
        month_invoice_map = _get_invoice_map_for_month(company=company, month_start=month_start, customers=customers)
        month_label = month_start.strftime("%Y-%m")

        for contract in active_contracts:
            expected = _expected_amounts_for_month(contract, month_start, staffel_by_contract.get(contract.name, {}))
            customer = (contract.get("kunde") or "").strip()

            for typ in INVOICE_TYPES:
                expected_amount = flt(expected.get(typ) or 0)
                invoice_bucket = month_invoice_map.get((customer, typ), {"invoice_names": [], "actual_amount": 0.0})
                has_invoice = bool(invoice_bucket.get("invoice_names"))
                actual_amount = flt(invoice_bucket.get("actual_amount") or 0)

                if expected_amount <= 0:
                    status = "OK"
                    delta = 0.0
                    details = _("Erwarteter Betrag ist 0.")
                else:
                    status, delta, details = _evaluate_row(expected_amount, actual_amount, has_invoice, SUM_TOLERANCE)

                if not _should_emit_row(status, show_ok_rows, only_issues):
                    continue

                invoice_names = invoice_bucket.get("invoice_names") or []
                sales_invoice = invoice_names[0] if invoice_names else ""
                if len(invoice_names) > 1:
                    details = f"{details} | Weitere Rechnungen: {', '.join(invoice_names[1:])}"

                rows.append(
                    {
                        "monat": month_label,
                        "mietvertrag": contract.name,
                        "wohnung": contract.wohnung,
                        "kunde": contract.kunde,
                        "typ": typ,
                        "status": status,
                        "expected_amount": round(expected_amount, 2),
                        "actual_amount": round(actual_amount, 2),
                        "delta": round(delta, 2),
                        "sales_invoice": sales_invoice,
                        "details": details,
                    }
                )

    rows.sort(key=lambda r: (r.get("monat") or "", r.get("wohnung") or "", r.get("mietvertrag") or "", r.get("typ") or ""))
    return get_columns(), rows


def get_columns():
    return [
        {"label": "Monat", "fieldname": "monat", "fieldtype": "Data", "width": 90},
        {"label": "Mietvertrag", "fieldname": "mietvertrag", "fieldtype": "Link", "options": "Mietvertrag", "width": 260},
        {"label": "Wohnung", "fieldname": "wohnung", "fieldtype": "Link", "options": "Wohnung", "width": 160},
        {"label": "Mieter", "fieldname": "kunde", "fieldtype": "Link", "options": "Customer", "width": 220},
        {"label": "Typ", "fieldname": "typ", "fieldtype": "Data", "width": 130},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 130},
        {"label": "Erwartet", "fieldname": "expected_amount", "fieldtype": "Currency", "width": 120},
        {"label": "Ist", "fieldname": "actual_amount", "fieldtype": "Currency", "width": 120},
        {"label": "Delta", "fieldname": "delta", "fieldtype": "Currency", "width": 120},
        {"label": "Sales Invoice", "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 220},
        {"label": "Details", "fieldname": "details", "fieldtype": "Data", "width": 280},
    ]


def _normalize_month_start(value: object) -> date | None:
    if not value:
        return None
    return getdate(get_first_day(getdate(value)))


def _iter_month_starts(from_month: date, to_month: date) -> list[date]:
    out = []
    current = from_month
    while current <= to_month:
        out.append(current)
        current = add_months(current, 1)
    return out


def _get_contracts(period_start: date, period_end: date) -> list[frappe._dict]:
    return frappe.db.sql(
        """
        SELECT name, kunde, wohnung, von, bis
        FROM `tabMietvertrag`
        WHERE docstatus != 2
          AND (von IS NULL OR von <= %(period_end)s)
          AND (bis IS NULL OR bis >= %(period_start)s)
        ORDER BY wohnung ASC, name ASC
        """,
        {"period_start": period_start, "period_end": period_end},
        as_dict=True,
    )


def _get_staffelmieten_by_contract(contract_names: list[str]) -> dict[str, dict[str, list[frappe._dict]]]:
    out: dict[str, dict[str, list[frappe._dict]]] = {}
    if not contract_names:
        return out

    rows = frappe.get_all(
        "Staffelmiete",
        filters={
            "parent": ("in", contract_names),
            "parenttype": "Mietvertrag",
            "parentfield": ("in", ["miete", "betriebskosten", "heizkosten"]),
        },
        fields=["name", "parent", "parentfield", "von", "miete", "art", "idx"],
        order_by="parent asc, parentfield asc, von asc, idx asc, name asc",
    )

    for row in rows:
        parent_map = out.setdefault(row.parent, {})
        parent_map.setdefault(row.parentfield, []).append(row)

    return out


def _expected_amounts_for_month(contract: frappe._dict, month_start: date, staffel: dict[str, list[frappe._dict]]) -> dict[str, float]:
    miete_rows = staffel.get("miete") or []
    bk_rows = staffel.get("betriebskosten") or []
    hk_rows = staffel.get("heizkosten") or []

    return {
        "Miete": _miete_betrag_fuer_monat_from_rows(contract.von, contract.bis, month_start, miete_rows),
        "Betriebskosten": _staffelbetrag_from_rows(bk_rows, month_start),
        "Heizkosten": _staffelbetrag_from_rows(hk_rows, month_start),
    }


def _month_window(anchor: date) -> tuple[date, date, int]:
    start = get_first_day(anchor)
    end_excl = add_months(start, 1)
    days = (end_excl - start).days
    return start, end_excl, days


def _overlap(a_start: date, a_end_excl: date, b_start: date, b_end_excl: date) -> tuple[date, date, int]:
    s = max(a_start, b_start)
    e = min(a_end_excl, b_end_excl)
    days = max((e - s).days, 0)
    return s, e, days


def _miete_betrag_fuer_monat_from_rows(von: object, bis: object, anchor: date, rows: list[frappe._dict]) -> float:
    month_start, month_end_excl, days_in_month = _month_window(anchor)

    contract_start = getdate(von) if von else date(1900, 1, 1)
    contract_end_excl = getdate(bis) + timedelta(days=1) if bis else date(9999, 12, 31)

    ov_start, ov_end_excl, ov_days = _overlap(month_start, month_end_excl, contract_start, contract_end_excl)
    if ov_days == 0:
        return 0.0

    total = 0.0

    monatlich_rows = []
    for row in rows or []:
        art = (row.get("art") or "Monatlich").strip()
        row_von = getdate(row.get("von")) if row.get("von") else None
        if art == "Monatlich" and row_von and row_von < month_end_excl:
            monatlich_rows.append({"von": row_von, "miete": flt(row.get("miete") or 0)})

    current_rate = 0.0
    for row in monatlich_rows:
        if row["von"] <= ov_start:
            current_rate = flt(row["miete"])
        else:
            break

    change_points = sorted({row["von"] for row in monatlich_rows if ov_start < row["von"] < ov_end_excl})
    segment_starts = [ov_start] + change_points
    segment_ends = segment_starts[1:] + [ov_end_excl]

    future_rows = [row for row in monatlich_rows if row["von"] >= ov_start]
    row_index = 0

    for seg_start, seg_end in zip(segment_starts, segment_ends):
        while row_index < len(future_rows) and future_rows[row_index]["von"] == seg_start:
            current_rate = flt(future_rows[row_index]["miete"])
            row_index += 1

        days = (seg_end - seg_start).days
        if days > 0 and current_rate > 0:
            total += current_rate * (days / days_in_month)

    ges_rows = []
    for row in rows or []:
        art = (row.get("art") or "Monatlich").strip()
        row_von = getdate(row.get("von")) if row.get("von") else None
        if art == "Gesamter Zeitraum" and row_von and month_start <= row_von <= add_days(month_end_excl, -1):
            ges_rows.append({"name": row.get("name"), "von": row_von, "miete": flt(row.get("miete") or 0)})

    if ges_rows:
        alle_ges = []
        for row in rows or []:
            art = (row.get("art") or "Monatlich").strip()
            row_von = getdate(row.get("von")) if row.get("von") else None
            if art == "Gesamter Zeitraum" and row_von:
                alle_ges.append({"name": row.get("name"), "von": row_von, "miete": flt(row.get("miete") or 0)})

        alle_ges.sort(key=lambda r: (r["von"], r.get("name") or ""))
        index_by_name = {row.get("name"): i for i, row in enumerate(alle_ges)}

        for row in ges_rows:
            i = index_by_name.get(row.get("name"))
            if i is None:
                continue

            if i + 1 < len(alle_ges):
                r_end_excl = alle_ges[i + 1]["von"]
            else:
                if bis:
                    r_end_excl = getdate(bis) + timedelta(days=1)
                else:
                    r_end_excl = add_months(get_first_day(row["von"]), 1)

            end_incl = r_end_excl - timedelta(days=1)
            if row["von"].year == end_incl.year and row["von"].month == end_incl.month:
                _, _, cut_days = _overlap(row["von"], r_end_excl, contract_start, contract_end_excl)
                if cut_days > 0:
                    total += flt(row.get("miete") or 0)

    return round(flt(total), 2)


def _staffelbetrag_from_rows(rows: list[frappe._dict], zum: date) -> float:
    anchor = getdate(zum)
    best_von = None
    best_value = 0.0

    for row in rows or []:
        row_von = row.get("von")
        if not row_von:
            continue
        row_von = getdate(row_von)
        if row_von <= anchor and (best_von is None or row_von > best_von):
            best_von = row_von
            best_value = flt(row.get("miete") or 0)

    return round(flt(best_value), 2)


def _contract_overlaps_month(contract: frappe._dict, month_start: date) -> bool:
    month_start, month_end_excl, _ = _month_window(month_start)

    c_start = getdate(contract.von) if contract.von else date(1900, 1, 1)
    c_end_excl = getdate(contract.bis) + timedelta(days=1) if contract.bis else date(9999, 12, 31)

    _, _, ov_days = _overlap(month_start, month_end_excl, c_start, c_end_excl)
    return ov_days > 0


def _get_invoice_map_for_month(
    company: str,
    month_start: date,
    customers: set[str],
) -> dict[tuple[str, str], dict[str, object]]:
    month_end = get_last_day(month_start)
    if not customers:
        return {}

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "company": company,
            "customer": ("in", tuple(sorted(customers))),
            "posting_date": ("between", [month_start, month_end]),
            "docstatus": ("in", [0, 1]),
        },
        fields=["name", "customer"],
    )

    bucket: dict[tuple[str, str], dict[str, object]] = {}
    invoice_names = [inv.name for inv in (invoices or [])]

    if not invoice_names:
        return bucket

    item_rows = frappe.db.sql(
        """
        SELECT parent, item_code, COALESCE(SUM(amount), 0) AS amount
        FROM `tabSales Invoice Item`
        WHERE parent IN %(parents)s
          AND item_code IN ('Miete', 'Betriebskosten', 'Heizkosten')
        GROUP BY parent, item_code
        """,
        {"parents": tuple(invoice_names)},
        as_dict=True,
    )

    amount_by_invoice_and_code = {(r.parent, r.item_code): flt(r.amount) for r in (item_rows or [])}
    invoice_code_pairs = set(amount_by_invoice_and_code.keys())

    for inv in invoices or []:
        customer = (inv.customer or "").strip()
        if not customer:
            continue

        for typ, item_code in ITEM_CODE_BY_TYP.items():
            pair = (inv.name, item_code)
            if pair not in invoice_code_pairs:
                continue

            key = (customer, typ)
            entry = bucket.setdefault(key, {"invoice_names": [], "actual_amount": 0.0})
            entry["invoice_names"].append(inv.name)
            entry["actual_amount"] = flt(entry.get("actual_amount") or 0) + _amount_for_invoice_type(
                inv.name,
                typ,
                amount_by_invoice_and_code,
            )

    for entry in bucket.values():
        entry["invoice_names"] = sorted(set(entry.get("invoice_names") or []))
        entry["actual_amount"] = round(flt(entry.get("actual_amount") or 0), 2)

    return bucket


def _amount_for_invoice_type(invoice_name: str, typ: str, amount_by_invoice_and_code: dict[tuple[str, str], float]) -> float:
    item_code = ITEM_CODE_BY_TYP.get(typ)
    if not item_code:
        return 0.0
    return flt(amount_by_invoice_and_code.get((invoice_name, item_code), 0.0))


def _evaluate_row(expected_amount: float, actual_amount: float, has_invoice: bool, tolerance: float) -> tuple[str, float, str]:
    expected_amount = flt(expected_amount)
    actual_amount = flt(actual_amount)
    delta = round(actual_amount - expected_amount, 2)

    if not has_invoice:
        return "FEHLT", delta, _("Keine Rechnung zum Mieter gefunden.")

    if abs(delta) >= flt(tolerance):
        return "FALSCHE_SUMME", delta, _("Abweichung ist größer oder gleich 0,01 EUR.")

    return "OK", delta, _("Rechnungssumme entspricht dem erwarteten Betrag.")


def _should_emit_row(status: str, show_ok_rows: int, only_issues: int) -> bool:
    if status != "OK":
        return True

    # "OK-Zeilen anzeigen" hat Vorrang. Dadurch liefert die Kombination
    # (show_ok_rows=1, only_issues=1) weiterhin sinnvolle Ergebnisse.
    if show_ok_rows:
        return True

    if only_issues:
        return False
    return False
