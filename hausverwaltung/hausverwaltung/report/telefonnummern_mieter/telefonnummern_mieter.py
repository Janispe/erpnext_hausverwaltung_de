import re

import frappe

from hausverwaltung.hausverwaltung.utils.gebaeudeteil import split_lage_gebaeudeteil
from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles


def execute(filters=None):
    filters = filters or {}

    raw_pro_wohnung = filters.get("pro_wohnung")
    pro_wohnung = str(raw_pro_wohnung or "").strip().lower() in {"1", "true", "yes", "on"}

    contact_phone_expr = "NULLIF(c.phone, '')"
    try:
        if frappe.db.table_exists("Contact Phone"):
            contact_phone_expr = """COALESCE(
                NULLIF(c.phone, ''),
                NULLIF((
                    SELECT cp.phone
                    FROM `tabContact Phone` cp
                    WHERE cp.parent = c.name
                    ORDER BY COALESCE(cp.is_primary_phone, 0) DESC, cp.idx ASC
                    LIMIT 1
                ), '')
            )"""
    except Exception:
        # `table_exists` not always available; fall back to `c.phone`
        pass

    conditions = [
        "(mv.von IS NULL OR mv.von <= CURDATE())",
        "(mv.bis IS NULL OR mv.bis >= CURDATE())",
        "(vp.eingezogen IS NULL OR vp.eingezogen <= CURDATE())",
        "(vp.ausgezogen IS NULL OR vp.ausgezogen >= CURDATE())",
        "COALESCE(vp.rolle, '') != 'Ausgezogen'",
    ]
    values = {}

    immobilie = filters.get("immobilie")
    if immobilie:
        conditions.append("w.immobilie = %(immobilie)s")
        values["immobilie"] = immobilie

    if pro_wohnung:
        data = frappe.db.sql(
            f"""
            SELECT
                mv.wohnung AS wohnung,
                w.immobilie AS immobilie,
                w.gebaeudeteil AS gebaeudeteil,
                w.name__lage_in_der_immobilie AS lage_in_der_immobilie,
                GROUP_CONCAT(
                    CONCAT(
                        COALESCE(
                            NULLIF(TRIM(CONCAT_WS(' ', c.last_name, c.first_name)), ''),
                            vp.mieter
                        ),
                        CASE
                            WHEN vp.rolle IS NOT NULL AND vp.rolle != '' THEN CONCAT(' (', vp.rolle, ')')
                            ELSE ''
                        END
                    )
                    ORDER BY vp.idx
                    SEPARATOR '\\n'
                ) AS mieter,
                GROUP_CONCAT(
                    COALESCE(
                        NULLIF(
                            TRIM(
                                CONCAT_WS(
                                    ' / ',
                                    {contact_phone_expr},
                                    CASE
                                        WHEN c.mobile_no IS NOT NULL
                                            AND c.mobile_no != ''
                                            AND c.mobile_no != COALESCE({contact_phone_expr}, '')
                                        THEN c.mobile_no
                                        ELSE NULL
                                    END
                                )
                            ),
                            ''
                        ),
                        '—'
                    )
                    ORDER BY vp.idx
                    SEPARATOR '\\n'
                ) AS telefonnummern
            FROM
                `tabMietvertrag` mv
            JOIN
                `tabWohnung` w ON w.name = mv.wohnung
            JOIN
                `tabVertragspartner` vp ON vp.parent = mv.name
                    AND vp.parenttype = 'Mietvertrag'
                    AND vp.parentfield = 'mieter'
            LEFT JOIN
                `tabContact` c ON c.name = vp.mieter
            WHERE
                {" AND ".join(conditions)}
            GROUP BY
                mv.wohnung,
                w.immobilie,
                w.gebaeudeteil,
                w.name__lage_in_der_immobilie
            ORDER BY
                mv.wohnung
            """,
            values=values,
            as_dict=True,
        )
    else:
        data = frappe.db.sql(
            f"""
            SELECT
                mv.wohnung AS wohnung,
                w.immobilie AS immobilie,
                w.gebaeudeteil AS gebaeudeteil,
                w.name__lage_in_der_immobilie AS lage_in_der_immobilie,
                CONCAT(
                    COALESCE(
                        NULLIF(TRIM(CONCAT_WS(' ', c.last_name, c.first_name)), ''),
                        vp.mieter
                    ),
                    CASE
                        WHEN vp.rolle IS NOT NULL AND vp.rolle != '' THEN CONCAT(' (', vp.rolle, ')')
                        ELSE ''
                    END
                ) AS mieter,
                COALESCE(
                    NULLIF(
                        TRIM(
                            CONCAT_WS(
                                ' / ',
                                {contact_phone_expr},
                                CASE
                                    WHEN c.mobile_no IS NOT NULL
                                        AND c.mobile_no != ''
                                        AND c.mobile_no != COALESCE({contact_phone_expr}, '')
                                    THEN c.mobile_no
                                    ELSE NULL
                                END
                            )
                        ),
                        ''
                    ),
                    '—'
                ) AS telefonnummern,
                vp.idx AS mieter_idx
            FROM
                `tabMietvertrag` mv
            JOIN
                `tabWohnung` w ON w.name = mv.wohnung
            JOIN
                `tabVertragspartner` vp ON vp.parent = mv.name
                    AND vp.parenttype = 'Mietvertrag'
                    AND vp.parentfield = 'mieter'
            LEFT JOIN
                `tabContact` c ON c.name = vp.mieter
            WHERE
                {" AND ".join(conditions)}
            ORDER BY
                mv.wohnung,
                vp.idx
            """,
            values=values,
            as_dict=True,
        )

    order = {"VH": 0, "SF": 1, "HH": 2}
    for row in data:
        teil = (row.get("gebaeudeteil") or "").strip()
        if not teil:
            teil_from_lage, _rest = split_lage_gebaeudeteil(row.get("lage_in_der_immobilie"))
            if teil_from_lage:
                row["gebaeudeteil"] = teil_from_lage
        row["telefonnummern"] = _format_phone_number_list(row.get("telefonnummern"))

    data.sort(
        key=lambda r: (
            (r.get("immobilie") or ""),
            order.get((r.get("gebaeudeteil") or "").strip().upper(), 99),
            (r.get("wohnung") or ""),
            int(r.get("mieter_idx") or 0),
        )
    )

    columns = [
        {
            "fieldname": "wohnung",
            "fieldtype": "Link",
            "label": "Wohnung",
            "options": "Wohnung",
            "width": 220,
        },
        {
            "fieldname": "immobilie",
            "fieldtype": "Link",
            "label": "Immobilie",
            "options": "Immobilie",
            "width": 220,
        },
        {
            "fieldname": "gebaeudeteil",
            "fieldtype": "Data",
            "label": "Gebäudeteil",
            "width": 90,
        },
        {"fieldname": "mieter", "fieldtype": "Data", "label": "Mieter", "width": 320},
        {
            "fieldname": "telefonnummern",
            "fieldtype": "Data",
            "label": "Telefonnummern",
            "width": 280,
        },
    ]

    enrich_link_titles(data, columns)
    return columns, data


def _format_phone_number_list(value: str | None) -> str:
    return "\n".join(
        " / ".join(_format_phone_number(part) for part in line.split(" / "))
        for line in (value or "").splitlines()
    )


def _format_phone_number(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or raw == "—":
        return raw

    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 6:
        return raw

    if raw.lstrip().startswith("+") and digits.startswith("49") and len(digits) > 2:
        separated = _format_separated_german_phone_number(
            re.sub(r"^\s*\+?\s*49[\s().-]*", "0", raw, count=1)
        )
        if separated:
            return separated
        return _format_german_phone_digits("0" + digits[2:])

    separated = _format_separated_german_phone_number(raw)
    if separated:
        return separated

    return _format_german_phone_digits(digits)


def _format_german_phone_digits(digits: str) -> str:
    if digits.startswith("01") and len(digits) > 4:
        return f"{digits[:4]} {_group_phone_subscriber_digits(digits[4:])}"
    if digits.startswith("030") and len(digits) > 3:
        return f"030 {_group_phone_subscriber_digits(digits[3:])}"
    return digits


def _group_phone_subscriber_digits(digits: str) -> str:
    return " ".join(digits[i : i + 3] for i in range(0, len(digits), 3))


def _format_separated_german_phone_number(raw: str) -> str:
    match = re.match(r"^(0\d{1,5})[\s().-]+(\d[\d\s().-]*)$", raw.strip())
    if not match:
        return ""
    subscriber_digits = "".join(ch for ch in match.group(2) if ch.isdigit())
    if not subscriber_digits:
        return ""
    return f"{match.group(1)} {_group_phone_subscriber_digits(subscriber_digits)}"
