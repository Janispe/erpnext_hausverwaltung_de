import frappe
from frappe.utils import add_months, flt, getdate, today


def execute(filters=None):
    filters = frappe._dict(filters or {})

    today_d = getdate(today())
    from_date = getdate(filters.get("von") or add_months(today_d, -12))
    to_date = getdate(filters.get("bis") or add_months(today_d, 12))

    if to_date < from_date:
        frappe.throw("'Bis' darf nicht vor 'Von' liegen.")

    conditions = [
        "az.status != 'Abgerechnet'",
        "p.payment_entry IS NULL",
        "p.faelligkeitsdatum BETWEEN %(from_date)s AND %(to_date)s",
    ]
    params = {"from_date": from_date, "to_date": to_date}
    if filters.get("immobilie"):
        conditions.append("az.immobilie = %(immobilie)s")
        params["immobilie"] = filters.get("immobilie")

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            p.faelligkeitsdatum AS faellig_am,
            p.betrag AS betrag,
            p.bemerkung AS bemerkung,
            az.name AS abschlagszahlung,
            az.bezeichnung AS bezeichnung,
            az.company AS company,
            az.lieferant AS lieferant,
            az.immobilie AS immobilie,
            az.wohnung AS wohnung
        FROM `tabAbschlagszahlung Plan` p
        INNER JOIN `tabAbschlagszahlung` az ON az.name = p.parent
        WHERE {where}
        ORDER BY p.faelligkeitsdatum ASC, az.name ASC
        """,
        params,
        as_dict=True,
    )

    company_currency_cache: dict[str, str | None] = {}
    total = 0.0
    overdue_total = 0.0
    overdue_count = 0
    for row in rows:
        faellig = getdate(row.get("faellig_am"))
        tage_offen = (today_d - faellig).days
        row["tage_offen"] = tage_offen
        row["status"] = "Überfällig" if tage_offen > 0 else ("Heute" if tage_offen == 0 else "Anstehend")
        row["currency"] = _get_company_currency(row.get("company"), company_currency_cache)
        amount = flt(row.get("betrag"))
        total += amount
        if tage_offen > 0:
            overdue_total += amount
            overdue_count += 1

    # Most overdue first; future entries follow in chronological order
    rows.sort(key=lambda r: (-r.get("tage_offen", 0), r.get("faellig_am") or today_d))

    summary = []
    if rows:
        currency = rows[0].get("currency")
        summary = [
            {
                "value": overdue_total,
                "indicator": "red" if overdue_count else "green",
                "label": "Summe überfällig",
                "datatype": "Currency",
                "currency": currency,
            },
            {
                "value": overdue_count,
                "indicator": "red" if overdue_count else "green",
                "label": "Überfällige Plan-Zeilen",
                "datatype": "Int",
            },
            {
                "value": total,
                "indicator": "blue",
                "label": "Summe gesamt",
                "datatype": "Currency",
                "currency": currency,
            },
            {
                "value": len(rows),
                "indicator": "blue",
                "label": "Offene Plan-Zeilen",
                "datatype": "Int",
            },
        ]

    return get_columns(), rows, None, summary


def get_columns():
    return [
        {
            "label": "Status",
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "label": "Tage offen",
            "fieldname": "tage_offen",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "label": "Fällig am",
            "fieldname": "faellig_am",
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "label": "Betrag",
            "fieldname": "betrag",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 120,
        },
        {
            "label": "Immobilie",
            "fieldname": "immobilie",
            "fieldtype": "Link",
            "options": "Immobilie",
            "width": 160,
        },
        {
            "label": "Wohnung",
            "fieldname": "wohnung",
            "fieldtype": "Link",
            "options": "Wohnung",
            "width": 140,
        },
        {
            "label": "Bezeichnung",
            "fieldname": "bezeichnung",
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "label": "Lieferant",
            "fieldname": "lieferant",
            "fieldtype": "Link",
            "options": "Supplier",
            "width": 160,
        },
        {
            "label": "Abschlagszahlung",
            "fieldname": "abschlagszahlung",
            "fieldtype": "Link",
            "options": "Abschlagszahlung",
            "width": 150,
        },
        {
            "label": "Bemerkung",
            "fieldname": "bemerkung",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": "Firma",
            "fieldname": "company",
            "fieldtype": "Link",
            "options": "Company",
            "width": 140,
        },
    ]


def _get_company_currency(company, cache):
    if not company:
        return None
    if company not in cache:
        cache[company] = frappe.get_cached_value("Company", company, "default_currency")
    return cache[company]
