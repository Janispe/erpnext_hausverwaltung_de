import frappe
from frappe import _
from frappe.utils import add_days, get_first_day, get_last_day, add_months, now_datetime, getdate
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP


def _parse_monat_jahr(monat: str | int | None, jahr: str | int | None) -> date:
    """Ermittle das Ziel-Datum als erster Tag im Monat."""
    heute = datetime.today()
    m = int(monat) if monat else int(heute.strftime("%m"))
    j = int(jahr) if jahr else int(heute.strftime("%Y"))
    return date(j, m, 1)


def _staffelbetrag(mv_name: str, parentfield: str, zum: date) -> float:
    """Hole den Betrag aus der Staffeltabelle (miete|betriebskosten|heizkosten), der am Datum gilt.

    Hinweis: Für Miete wird in dieser Datei eine spezielle Monatsberechnung verwendet.
    Diese generische Funktion bleibt für BK/Heizkosten erhalten (kein Pro‑Rata).
    """
    betrag = frappe.db.get_value(
        "Staffelmiete",
        {
            "parent": mv_name,
            "parenttype": "Mietvertrag",
            "parentfield": parentfield,
            "von": ("<=", zum),
        },
        "miete",
        order_by="von desc",
    )
    try:
        return float(betrag) if betrag else 0.0
    except Exception:
        return 0.0


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


def _miete_betrag_fuer_monat(mv_row: frappe._dict, anchor: date) -> float:
    """Berechnet den Mietbetrag für den Anker‑Monat:
    - Art 'Monatlich': anteilig nach Tagen im Monat (inkl. Staffelwechsel innerhalb des Monats)
    - Art 'Gesamter Zeitraum': voller Betrag, wenn Zeitraum in diesem Monat liegt
    Berücksichtigt Vertragslaufzeit (nur überlappende Tage).
    """
    mv_name = mv_row.name
    month_start, month_end_excl, days_in_month = _month_window(anchor)

    # Vertragsfenster (exklusive Ende)
    contract_start = mv_row.von or date(1900, 1, 1)
    contract_end_excl = (mv_row.bis + timedelta(days=1)) if mv_row.bis else date(9999, 12, 31)

    # Monat × Vertrag überlappen?
    ov_start, ov_end_excl, ov_days = _overlap(month_start, month_end_excl, contract_start, contract_end_excl)
    if ov_days == 0:
        return 0.0

    total = 0.0

    # 1) Monatlich (pro‑rata)
    monatlich_rows = frappe.get_all(
        "Staffelmiete",
        filters={
            "parent": mv_name,
            "parenttype": "Mietvertrag",
            "parentfield": "miete",
            "art": "Monatlich",
            # Relevanz: alle mit 'von' < Monatsende
            "von": ("<", month_end_excl),
        },
        fields=["von", "miete"],
        order_by="von asc",
    )

    # Aktiver Satz zu ov_start finden (letzter mit von <= ov_start)
    current_rate = 0.0
    for r in monatlich_rows:
        if r.von <= ov_start:
            current_rate = float(r.miete or 0)  # Kandidat
        else:
            break

    # Zeitscheiben: Wechselpunkte innerhalb [ov_start, ov_end_excl)
    change_points = [r.von for r in monatlich_rows if ov_start < r.von < ov_end_excl]
    segment_starts = [ov_start] + sorted(change_points)
    segment_ends = segment_starts[1:] + [ov_end_excl]

    # Rate laufend aktualisieren, wenn wir an einen Wechsel kommen
    # Dazu benötigen wir ein Iterator über alle Rows ab ov_start
    rows_iter = iter([r for r in monatlich_rows if r.von >= ov_start])
    next_row = next(rows_iter, None)

    for seg_start, seg_end in zip(segment_starts, segment_ends):
        # Falls ein Wechsel exakt zu seg_start vorliegt → Rate aktualisieren
        while next_row and next_row.von == seg_start:
            current_rate = float(next_row.miete or 0)
            next_row = next(rows_iter, None)
        days = (seg_end - seg_start).days
        if days > 0 and current_rate > 0:
            total += current_rate * (days / days_in_month)

    # 2) Gesamter Zeitraum (voller Betrag, nur wenn Zeitraum innerhalb eines Monats liegt)
    ges_rows = frappe.get_all(
        "Staffelmiete",
        filters={
            "parent": mv_name,
            "parenttype": "Mietvertrag",
            "parentfield": "miete",
            "art": "Gesamter Zeitraum",
            # nur Startpunkte dieses Monats betrachten
            "von": ("between", [month_start, add_days(month_end_excl, -1)]),
        },
        fields=["name", "von", "miete"],
        order_by="von asc",
    )

    if ges_rows:
        # Um das Ende zu bestimmen, brauchen wir alle 'Gesamter Zeitraum'-Zeilen im Vertrag
        alle_ges = frappe.get_all(
            "Staffelmiete",
            filters={
                "parent": mv_name,
                "parenttype": "Mietvertrag",
                "parentfield": "miete",
                "art": "Gesamter Zeitraum",
            },
            fields=["name", "von", "miete"],
            order_by="von asc",
        )
        # Map name -> index
        index_by_name = {row.name: i for i, row in enumerate(alle_ges)}
        for r in ges_rows:
            i = index_by_name.get(r.name)
            if i is None:
                continue
            r_start = r.von
            # Ende ist Vortag des nächsten Starts, oder Vertragsende, oder Monatsende (falls offen)
            if i + 1 < len(alle_ges):
                next_start = alle_ges[i + 1].von
                r_end_excl = next_start
            else:
                # letztes Intervall: Vertragsende nutzen, sonst Monatsende dieses Starts
                if mv_row.bis:
                    r_end_excl = mv_row.bis + timedelta(days=1)
                else:
                    # auf Monatsende clippen
                    r_end_excl = add_months(get_first_day(r_start), 1)
            # Nur wenn Start und (inklusive) Ende im selben Monat liegen, gilt der volle Betrag
            end_incl = r_end_excl - timedelta(days=1)
            if r_start.year == end_incl.year and r_start.month == end_incl.month:
                # und der Zeitraum muss den Vertrag schneiden
                _, _, cut_days = _overlap(r_start, r_end_excl, contract_start, contract_end_excl)
                if cut_days > 0:
                    total += float(r.miete or 0)

    return round(float(total), 2)


def _cost_center_via_wohnung(wohnung: str | None) -> str | None:
    if not wohnung:
        return None
    immobilie = frappe.db.get_value("Wohnung", wohnung, "immobilie")
    if not immobilie:
        return None
    return frappe.db.get_value("Immobilie", immobilie, "kostenstelle")


def _company_for_cost_center(cost_center: str | None) -> str | None:
    if not cost_center:
        return None
    return frappe.db.get_value("Cost Center", cost_center, "company")


def _company_via_wohnung(
    wohnung: str | None,
    *,
    for_update: bool = False,
) -> str | None:
    """Resolve the property's company without consulting user/global defaults.

    A default company is user-dependent and therefore not a safe booking
    identity in a multi-company site. Configured property cost centers,
    accounts and bank accounts must all point to one company. If no financial
    link exists, only a site with exactly one active company is unambiguous.
    """
    if not wohnung:
        immobilie = None
    else:
        immobilie = frappe.db.get_value(
            "Wohnung",
            wohnung,
            "immobilie",
            for_update=for_update,
        )
    origin_immobilie = immobilie
    sources: list[tuple[str, str, str]] = []
    visited: set[str] = set()
    while immobilie:
        if immobilie in visited:
            frappe.throw(
                _("Die Immobilien-Hierarchie enthält einen Kreis bei {0}.").format(
                    immobilie
                )
            )
        visited.add(immobilie)
        values = frappe.db.get_value(
            "Immobilie",
            immobilie,
            [
                "kostenstelle",
                "haupt_bank_account",
                "konto",
                "kassenkonto",
                "parent_immobilie",
                "old_parent",
            ],
            as_dict=True,
            for_update=for_update,
        ) or {}
        if values.get("kostenstelle"):
            sources.append(("Cost Center", values.kostenstelle, "company"))
        if values.get("haupt_bank_account"):
            sources.append(("Bank Account", values.haupt_bank_account, "company"))
        for account in (values.get("konto"), values.get("kassenkonto")):
            if account:
                sources.append(("Account", account, "company"))
        for child_doctype in ("Immobilie Bankkonto", "Immobilie Kassenkonto"):
            if for_update:
                account_rows = frappe.db.sql(
                    f"""
                    SELECT konto
                    FROM `tab{child_doctype}`
                    WHERE parent = %s
                    ORDER BY name ASC
                    FOR UPDATE
                    """,
                    (immobilie,),
                )
                accounts = [row[0] for row in account_rows]
            else:
                accounts = frappe.get_all(
                    child_doctype,
                    filters={"parent": immobilie},
                    pluck="konto",
                    order_by="name asc",
                )
            for account in accounts:
                if account:
                    sources.append(("Account", account, "company"))
        immobilie = values.get("parent_immobilie") or values.get("old_parent")

    companies: set[str] = set()
    # Shared financial masters are always locked in one global order.  Two
    # properties referencing the same accounts in a different child-row order
    # must not be able to deadlock each other.
    for doctype, name, fieldname in sorted(set(sources)):
        company = frappe.db.get_value(
            doctype,
            name,
            fieldname,
            for_update=for_update,
        )
        if not company:
            frappe.throw(
                _(
                    "Die Finanzzuordnung {0} {1} der Immobilie {2} hat keine "
                    "eindeutige Company. Es wurde nichts gebucht."
                ).format(doctype, name, origin_immobilie or "—")
            )
        companies.add(company)
    if len(companies) > 1:
        frappe.throw(
            _(
                "Die Finanzzuordnungen der Immobilie {0} gehören zu mehreren "
                "Companies ({1}). Es wurde nichts gebucht."
            ).format(origin_immobilie or "—", ", ".join(sorted(companies)))
        )
    if companies:
        return next(iter(companies))

    try:
        active_companies = frappe.get_all(
            "Company",
            filters={"disabled": 0},
            pluck="name",
        )
    except Exception:
        active_companies = frappe.get_all("Company", pluck="name")
    return active_companies[0] if len(active_companies) == 1 else None


def _immobilie_via_wohnung(wohnung: str | None) -> str | None:
    if not wohnung:
        return None
    return frappe.db.get_value("Wohnung", wohnung, "immobilie")


def _immobilie_active_for_month(immobilie: str | None, anchor: date) -> bool:
    """Immobilien ohne Erwerbsdatum gelten als aktiv, um Bestandsdaten nicht auszuschliessen."""
    if not immobilie:
        return True
    erworben_am = frappe.db.get_value("Immobilie", immobilie, "erworben_am")
    if not erworben_am:
        return True
    return getdate(erworben_am) <= get_last_day(anchor)


def _third_working_day(month_anchor: date, company: str | None) -> date:
    """Berechne den 3. Werktag (Mo–Fr) des Monats.
    Berücksichtigt optional die Holiday List der Company (wenn gesetzt).
    """
    start = date(month_anchor.year, month_anchor.month, 1)
    # Feiertage des Monats sammeln
    holidays: set[date] = set()
    try:
        if company:
            holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
            if holiday_list:
                hols = frappe.get_all(
                    "Holiday",
                    filters={
                        "parent": holiday_list,
                        "holiday_date": ("between", [get_first_day(start), get_last_day(start)]),
                    },
                    pluck="holiday_date",
                )
                holidays = set(hols or [])
    except Exception:
        # Fallback ohne Holiday-Handling
        holidays = set()

    d = start
    count = 0
    for _day_index in range(31):  # max. Tage im Monat
        if d.weekday() < 5 and d not in holidays:  # Mo–Fr und kein Feiertag
            count += 1
            if count == 3:
                return d
        d = d + timedelta(days=1)
    # Fallback: notfalls 5 Tage nach Start
    return start + timedelta(days=5)


def _kunde_des_vertrags(mv_row: frappe._dict) -> str | None:
    """Return the single authoritative Customer stored on the contract.

    Contact links are deliberately not a fallback: they can point to several
    customers and would turn a missing contract invariant into an ambiguous
    accounting assignment.
    """
    return (getattr(mv_row, "kunde", None) or "").strip() or None


def _locked_invoice_guard_rows(
    *,
    company: str,
    customer: str,
    month_start: date,
    month_end: date,
    target_id: str,
    legacy_marker: str,
    include_drafts: bool,
    has_structured_id: bool,
    has_wohnung: bool,
) -> list[frappe._dict]:
    """Liest Idempotenz-Kandidaten als Current Read unter ``FOR UPDATE``.

    Das ist bei MariaDB ``REPEATABLE-READ`` nötig: Ein wartender paralleler
    Generatorlauf darf nach dem Vertrags-Lock nicht auf seinem älteren
    Transaktions-Snapshot weiterprüfen.
    """
    docstatus_sql = "IN (0, 1)" if include_drafts else "= 1"
    structured_select = "si.mietabrechnung_id" if has_structured_id else "NULL AS mietabrechnung_id"
    wohnung_select = "si.wohnung" if has_wohnung else "NULL AS wohnung"
    structured_condition = "si.mietabrechnung_id = %(target_id)s OR" if has_structured_id else ""
    return frappe.db.sql(
        f"""
        SELECT
            si.name,
            si.remarks,
            si.docstatus,
            si.is_return,
            si.return_against,
            si.posting_date,
            {structured_select},
            {wohnung_select}
        FROM `tabSales Invoice` si
        WHERE si.company = %(company)s
          AND si.customer = %(customer)s
          AND si.docstatus {docstatus_sql}
          AND (
                {structured_condition}
                si.remarks LIKE %(legacy_marker)s
                OR si.posting_date BETWEEN %(month_start)s AND %(month_end)s
          )
        FOR UPDATE
        """,
        {
            "company": company,
            "customer": customer,
            "target_id": target_id,
            "legacy_marker": f"%{legacy_marker}%",
            "month_start": month_start,
            "month_end": month_end,
        },
        as_dict=True,
    )


def _locked_linked_return_rows(
    *,
    company: str,
    customer: str,
    parent_names: tuple[str, ...],
    has_structured_id: bool,
    has_wohnung: bool,
) -> list[frappe._dict]:
    if not parent_names:
        return []
    structured_select = "si.mietabrechnung_id" if has_structured_id else "NULL AS mietabrechnung_id"
    wohnung_select = "si.wohnung" if has_wohnung else "NULL AS wohnung"
    return frappe.db.sql(
        f"""
        SELECT
            si.name,
            si.remarks,
            si.is_return,
            si.return_against,
            si.posting_date,
            {structured_select},
            {wohnung_select}
        FROM `tabSales Invoice` si
        WHERE si.company = %(company)s
          AND si.customer = %(customer)s
          AND si.docstatus = 1
          AND si.is_return = 1
          AND si.return_against IN %(parent_names)s
        FOR UPDATE
        """,
        {
            "company": company,
            "customer": customer,
            "parent_names": parent_names,
        },
        as_dict=True,
    )


def _invoice_exists(
    customer: str,
    von: date,
    mv_name: str,
    typ: str,
    *,
    company: str,
    wohnung: str | None = None,
    include_drafts: bool = True,
) -> bool:
    item_code = {
        "Miete": "Miete",
        "Betriebskosten": "Betriebskosten",
        "Heizkosten": "Heizkosten",
        "Untermietzuschlag": "Untermietzuschlag",
    }.get(typ, typ)
    has_structured_id = _has_field("Sales Invoice", "mietabrechnung_id")
    has_wohnung = _has_field("Sales Invoice", "wohnung")

    target_id = f"{mv_name}|{von.strftime('%m/%Y')}"
    legacy_marker = f"[TYPE:{typ}] [MV:{mv_name}] {von.strftime('%m/%Y')}"
    invoice_by_name = {
        invoice.name: invoice
        for invoice in _locked_invoice_guard_rows(
            company=company,
            customer=customer,
            month_start=get_first_day(von),
            month_end=get_last_day(von),
            target_id=target_id,
            legacy_marker=legacy_marker,
            include_drafts=include_drafts,
            has_structured_id=has_structured_id,
            has_wohnung=has_wohnung,
        )
        or []
    }

    candidates: dict[str, frappe._dict] = {}
    for invoice in invoice_by_name.values():
        # A draft credit note has no ledger effect yet.  Counting it as a
        # negative invoice would make a submitted rent invoice appear fully
        # cancelled and a parallel/monthly generator run could create the
        # charge a second time.  Draft positive invoices still block retries.
        if int(invoice.get("is_return") or 0) and int(invoice.get("docstatus") or 0) != 1:
            continue
        invoice_wohnung = (invoice.get("wohnung") or "").strip() if has_wohnung else ""
        if wohnung and (not has_wohnung or invoice_wohnung != wohnung):
            continue

        structured_id = (invoice.get("mietabrechnung_id") or "").strip() if has_structured_id else ""
        remarks = invoice.get("remarks") or ""
        has_mv_marker = "[MV:" in remarks
        if structured_id:
            if structured_id != target_id:
                continue
            if has_mv_marker and legacy_marker not in remarks:
                continue
        elif has_mv_marker:
            if legacy_marker not in remarks:
                continue
        elif int(invoice.get("is_return") or 0):
            # Unmarkierte Gutschriften werden nur über return_against geerbt.
            continue

        candidates[invoice.name] = invoice

    # Eine Gutschrift neutralisiert ihre Originalrechnung. Sie muss deshalb in
    # die Netto-Wirkung einfließen, selbst wenn sie später gebucht wurde und
    # keine eigene mietabrechnung_id trägt.
    if candidates:
        linked_returns = _locked_linked_return_rows(
            company=company,
            customer=customer,
            parent_names=tuple(sorted(candidates)),
            has_structured_id=has_structured_id,
            has_wohnung=has_wohnung,
        )
        for invoice in linked_returns or []:
            invoice_wohnung = (invoice.get("wohnung") or "").strip() if has_wohnung else ""
            if wohnung and (not has_wohnung or invoice_wohnung != wohnung):
                continue
            structured_id = (invoice.get("mietabrechnung_id") or "").strip() if has_structured_id else ""
            remarks = invoice.get("remarks") or ""
            if structured_id and structured_id != target_id:
                continue
            if "[MV:" in remarks and legacy_marker not in remarks:
                continue
            candidates[invoice.name] = invoice

    if not candidates:
        return False

    item_rows = frappe.db.sql(
        """
        SELECT
            sii.parent,
            CASE
                WHEN si.is_return = 1 THEN -ABS(sii.amount)
                ELSE sii.amount
            END AS amount
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE sii.parent IN %(parents)s
          AND sii.item_code = %(item_code)s
          AND (si.is_return = 0 OR si.docstatus = 1)
        FOR UPDATE
        """,
        {"parents": tuple(sorted(candidates)), "item_code": item_code},
        as_dict=True,
    )
    net_amount = sum((Decimal(str(row.get("amount") or 0)) for row in item_rows or []), Decimal("0"))
    return net_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) >= Decimal("0.01")


def _lock_and_reload_mietvertrag(name: str) -> frappe._dict | None:
    """Serialisiert Sollstellungsläufe pro Vertrag und lädt aktuelle Werte."""
    rows = frappe.db.sql(
        """
        SELECT name, kunde, wohnung, immobilie, von, bis
        FROM `tabMietvertrag`
        WHERE name = %s
          AND docstatus != 2
        FOR UPDATE
        """,
        (name,),
        as_dict=True,
    )
    return rows[0] if rows else None


def _lock_property_booking_identity(wohnung: str) -> frappe._dict:
    """Load Wohnung, Immobilie, Cost Center and Company as one locked identity."""
    wohnung_rows = frappe.db.sql(
        """
        SELECT name, immobilie
        FROM `tabWohnung`
        WHERE name = %s
        FOR UPDATE
        """,
        (wohnung,),
        as_dict=True,
    )
    if not wohnung_rows or not wohnung_rows[0].get("immobilie"):
        frappe.throw(
            _("Wohnung {0} hat keine eindeutige Immobilie; es wurde nichts gebucht.").format(
                wohnung or "—"
            )
        )
    wohnung_row = wohnung_rows[0]

    immobilie_rows = frappe.db.sql(
        """
        SELECT name, kostenstelle, erworben_am
        FROM `tabImmobilie`
        WHERE name = %s
        FOR UPDATE
        """,
        (wohnung_row.immobilie,),
        as_dict=True,
    )
    if not immobilie_rows:
        frappe.throw(
            _("Die Immobilie {0} der Wohnung {1} existiert nicht; es wurde nichts gebucht.").format(
                wohnung_row.immobilie,
                wohnung,
            )
        )
    immobilie_row = immobilie_rows[0]
    cost_center = (immobilie_row.get("kostenstelle") or "").strip()
    if not cost_center:
        frappe.throw(
            _(
                "Immobilie {0} hat keine Kostenstelle. Mietrechnungen dürfen "
                "nicht auf eine Company-Standardkostenstelle fallen; es wurde nichts gebucht."
            ).format(immobilie_row.name)
        )

    # This also locks every configured property account/bank account and
    # rejects conflicting companies.  The required direct Cost Center prevents
    # its single-company fallback from becoming a booking default.
    company = _company_via_wohnung(wohnung, for_update=True)
    cost_center_row = frappe.db.get_value(
        "Cost Center",
        cost_center,
        ["name", "company", "disabled", "is_group"],
        as_dict=True,
        for_update=True,
    )
    if (
        not cost_center_row
        or not cost_center_row.get("company")
        or cost_center_row.get("disabled")
        or cost_center_row.get("is_group")
    ):
        frappe.throw(
            _(
                "Kostenstelle {0} der Immobilie {1} ist nicht als aktive "
                "Buchungskostenstelle eingerichtet; es wurde nichts gebucht."
            ).format(cost_center, immobilie_row.name)
        )
    if not company or company != cost_center_row.company:
        frappe.throw(
            _(
                "Kostenstelle {0} und Finanzzuordnung der Immobilie {1} ergeben "
                "keine identische Company; es wurde nichts gebucht."
            ).format(cost_center, immobilie_row.name)
        )

    return frappe._dict(
        wohnung=wohnung_row.name,
        immobilie=immobilie_row.name,
        cost_center=cost_center,
        company=company,
        immobilie_erworben_am=immobilie_row.get("erworben_am"),
    )


def lock_mietvertrag_booking_identity(name: str) -> frappe._dict:
    """Lock and return the current authoritative contract/property identity.

    Lock order is global and shared by the generator and the Sales Invoice
    override: Mietvertrag -> Wohnung -> Immobilie hierarchy -> financial
    masters.  Every value returned below came from a locking current read.
    """
    contract = _lock_and_reload_mietvertrag(name)
    if not contract:
        frappe.throw(
            _("Mietvertrag {0} existiert nicht oder wurde storniert.").format(name)
        )
    customer = (contract.get("kunde") or "").strip()
    wohnung = (contract.get("wohnung") or "").strip()
    if not customer or not wohnung:
        frappe.throw(
            _(
                "Mietvertrag {0} hat keinen eindeutigen Customer-/Wohnungskontext; "
                "es wurde nichts gebucht."
            ).format(contract.name)
        )

    property_identity = _lock_property_booking_identity(wohnung)
    stored_immobilie = (contract.get("immobilie") or "").strip()
    if stored_immobilie and stored_immobilie != property_identity.immobilie:
        frappe.throw(
            _(
                "Mietvertrag {0} verweist auf Immobilie {1}, seine Wohnung aktuell "
                "aber auf {2}; es wurde nichts gebucht."
            ).format(
                contract.name,
                stored_immobilie,
                property_identity.immobilie,
            )
        )

    return frappe._dict(
        name=contract.name,
        kunde=customer,
        wohnung=property_identity.wohnung,
        immobilie=property_identity.immobilie,
        von=contract.get("von"),
        bis=contract.get("bis"),
        cost_center=property_identity.cost_center,
        company=property_identity.company,
        immobilie_erworben_am=property_identity.immobilie_erworben_am,
    )


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        meta = frappe.get_meta(doctype)
        return bool(meta.get_field(fieldname))
    except Exception:
        return False


def _resolve_company(company: str | None) -> str:
    """Ermittelt eine Company für die Rechnungserstellung.

    Reihenfolge:
    1) explizit übergebene Company
    2) User Default (Company)
    3) Global Default (company)
    4) falls genau eine aktive Company existiert, diese
    """
    if company:
        return company

    company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
    if company:
        return company

    try:
        companies = frappe.get_all("Company", filters={"disabled": 0}, pluck="name")
    except Exception:
        companies = frappe.get_all("Company", pluck="name")

    if len(companies) == 1:
        return companies[0]

    frappe.throw(_("Bitte eine Company auswählen oder eine Standard-Company setzen (User/Global Defaults)."))


def _build_invoice_remark(typ: str, monat_str: str) -> str:
    label = {
        "Miete": "Miete",
        "Betriebskosten": "BK",
        "Heizkosten": "HK",
        "Untermietzuschlag": "UMZ",
    }.get(typ, typ)
    return f"{label} {monat_str}"


def _create_invoice(
    customer: str,
    posting: date,
    item_code: str,
    beschreibung: str,
    betrag: float,
    income_account: str | None,
    cost_center: str | None,
    remark: str,
    wohnung: str | None,
    company: str,
    mietabrechnung_id: str | None = None,
) -> str:
    if betrag <= 0:
        return ""
    if not income_account:
        frappe.throw(_("Kein Erlöskonto für Mietrechnung hinterlegt. Bitte Hausverwaltung Einstellungen prüfen."))
    sinv = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": company,
            "customer": customer,
            "posting_date": posting,
            # Backdating sicher erlauben
            "set_posting_time": 1,
            # Fällig am 3. Werktag des Monats
            "due_date": _third_working_day(posting, company),
            "remarks": remark,
            "items": [
                {
                    "item_code": item_code,
                    "item_name": item_code,
                    "description": beschreibung,
                    "qty": 1,
                    "rate": betrag,
                    "income_account": income_account,
                    "cost_center": cost_center,
                }
            ],
        }
    )
    # Falls es ein Kostenstellen-Feld auf dem Beleg gibt (Accounting Dimension), auch auf Header setzen
    try:
        if cost_center and _has_field("Sales Invoice", "cost_center"):
            sinv.set("cost_center", cost_center)
    except Exception:
        # robust bleiben, Item-Kostenstelle existiert bereits
        pass
    if wohnung and not _has_field("Sales Invoice", "wohnung"):
        frappe.throw('Feld "wohnung" existiert nicht auf Sales Invoice (Accounting Dimension nicht zugewiesen). Admin bescheid sagen!!!')
    sinv.set("wohnung", wohnung)
    if mietabrechnung_id and _has_field("Sales Invoice", "mietabrechnung_id"):
        sinv.set("mietabrechnung_id", mietabrechnung_id)
    frappe.msgprint("Mietrechnung erfolgreich erstellt!")
    # Auch auf Positionsebene setzen, wenn Feld existiert
    try:
        if sinv.items and wohnung and _has_field("Sales Invoice Item", "wohnung"):
            for it in sinv.items:
                it.set("wohnung", wohnung)
    except Exception as e:
        frappe.log_error(str(e), "Generate Mietrechnung")
    sinv.insert()
    sinv.submit()
    return sinv.name


@frappe.whitelist()
def generate_miet_und_bk_rechnungen(
    monat: str | int | None = None,
    jahr: str | int | None = None,
    company: str | None = None,
    mietvertrag: str | None = None,
    rechnungstyp: str | None = None,
    include_drafts_in_guard: int | str = 1,
) -> dict:
    """Erzeugt pro aktivem Mietvertrag drei Rechnungen (Miete, BK-VZ, Heiz-VZ) für den Monat.

    ``mietvertrag`` (optional): Wenn gesetzt, wird nur dieser eine Vertrag verarbeitet.
    Genutzt von der Mietrechnungs-Korrektur (utils.mietrechnung_korrektur), um nach einem
    Storno gezielt die fehlende Rechnung neu zu erzeugen — der Idempotenz-Guard
    (`_invoice_exists`) sorgt dafür, dass nur der stornierte Typ neu entsteht.

    ``rechnungstyp`` (optional): Wenn gesetzt, wird nur dieser Typ erzeugt.
    ``include_drafts_in_guard`` bleibt für normale Läufe aktiv; die Korrektur setzt
    es aus, damit alte Entwürfe die Neu-Erzeugung einer stornierten gebuchten
    Rechnung nicht blockieren.

    Rückgabe: Zusammenfassung mit Zählwerten und ggf. Hinweisen.
    """
    datum = _parse_monat_jahr(monat, jahr)
    company = _resolve_company(company)
    only_typ = (rechnungstyp or "").strip() or None
    if only_typ and only_typ not in {"Miete", "Betriebskosten", "Heizkosten", "Untermietzuschlag"}:
        frappe.throw(_("Unbekannter Rechnungstyp: {0}").format(only_typ))
    include_drafts = bool(int(include_drafts_in_guard or 0))

    from hausverwaltung.hausverwaltung.utils.income_accounts import get_hv_income_accounts
    from hausverwaltung.hausverwaltung.utils.rent_items import ensure_rent_items

    income_accounts = get_hv_income_accounts(company)
    ensure_rent_items(company=company)

    created = {"Miete": 0, "Betriebskosten": 0, "Heizkosten": 0, "Untermietzuschlag": 0}
    skipped = []
    skipped_details = []

    durchlauf_doc = None
    try:
        durchlauf_doc = frappe.get_doc(
            {
                "doctype": "Mietrechnungen Durchlauf",
                "company": company,
                "monat": str(datum.month),
                "jahr": datum.year,
                "started_at": now_datetime(),
                "status": "Running",
                "user": frappe.session.user,
            }
        )
        durchlauf_doc.flags.ignore_permissions = True
        durchlauf_doc.insert(ignore_permissions=True)
    except Exception:
        durchlauf_doc = None

    def add_skip(
        *,
        reason: str,
        mietvertrag: str | None,
        wohnung: str | None,
        typ: str | None,
        betrag: float | None,
        message: str,
    ) -> None:
        skipped.append(message)
        skipped_details.append(
            {
                "reason": reason,
                "mietvertrag": mietvertrag,
                "wohnung": wohnung,
                "typ": typ,
                "betrag": betrag,
                "message": message,
            }
        )
        if durchlauf_doc:
            durchlauf_doc.append(
                "skips",
                {
                    "doctype": "Mietrechnungen Durchlauf Skip",
                    "reason": reason,
                    "mietvertrag": mietvertrag,
                    "wohnung": wohnung,
                    "typ": typ,
                    "betrag": betrag,
                    "message": message,
                },
            )

    def add_created(
        *,
        sales_invoice: str,
        typ: str,
        mietvertrag: str | None,
        wohnung: str | None,
        kunde: str | None,
        betrag: float,
        posting_date: date,
    ) -> None:
        if not durchlauf_doc:
            return
        durchlauf_doc.append(
            "rechnungen",
            {
                "doctype": "Mietrechnungen Durchlauf Rechnung",
                "sales_invoice": sales_invoice,
                "typ": typ,
                "mietvertrag": mietvertrag,
                "wohnung": wohnung,
                "kunde": kunde,
                "betrag": betrag,
                "posting_date": posting_date,
            },
        )

    vertrag_filters: dict = {}
    if mietvertrag:
        vertrag_filters["name"] = mietvertrag
    vertrage = frappe.get_all(
        "Mietvertrag",
        filters=vertrag_filters,
        fields=["name", "kunde", "wohnung", "immobilie", "von", "bis"],
        order_by="name asc",
    )

    try:
        for candidate in vertrage:
            # Der Row-Lock bleibt bis zum Request-Commit bestehen. Ein
            # paralleler Lauf prüft deshalb erst nach der ersten Sollstellung
            # erneut auf bereits vorhandene Rechnungen.
            v = lock_mietvertrag_booking_identity(candidate.name)

            # Prüfe, ob der Monat den Vertrag schneidet (auch bei Teilmonaten zulassen)
            month_start, month_end_excl, _ = _month_window(datum)
            c_start = v.von or date(1900, 1, 1)
            c_end_excl = (v.bis + timedelta(days=1)) if v.bis else date(9999, 12, 31)
            _, _, ov_days = _overlap(month_start, month_end_excl, c_start, c_end_excl)
            if ov_days == 0:
                continue

            immobilie = v.immobilie
            if (
                v.immobilie_erworben_am
                and getdate(v.immobilie_erworben_am) > get_last_day(datum)
            ):
                add_skip(
                    reason="immobilie_nicht_aktiv",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ=None,
                    betrag=None,
                    message=f"{v.name}: Immobilie {immobilie} im Sollstellungsmonat noch nicht aktiv",
                )
                continue

            kunde = _kunde_des_vertrags(v)
            if not kunde:
                add_skip(
                    reason="kein_kunde",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ=None,
                    betrag=None,
                    message=f"{v.name}: kein Mieter",
                )
                continue

            kst = v.cost_center
            contract_company = v.company
            if contract_company != company:
                add_skip(
                    reason="andere_company",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ=None,
                    betrag=None,
                    message=f"{v.name}: gehört zu Company {contract_company}, nicht zu {company}",
                )
                continue

            # Beträge je Staffeltabelle holen
            # Miete: neue Logik (Monatlich pro‑rata, Gesamter Zeitraum voll)
            betrag_miete = _miete_betrag_fuer_monat(v, datum)
            betrag_bk = _staffelbetrag(v.name, "betriebskosten", datum)
            betrag_heiz = _staffelbetrag(v.name, "heizkosten", datum)

            # Mietabrechnungs-ID koppelt die getrennten SIs (Miete/BK/HK/UMZ)
            # eines Mietvertrag-Monats für die Display-Aggregation in
            # Mieterkonto und Hauptbuch HV.
            mietabrechnung_id = f"{v.name}|{datum.strftime('%m/%Y')}"

            monat_str = datum.strftime("%m/%Y")

            # Miete
            if only_typ and only_typ != "Miete":
                pass
            elif betrag_miete <= 0:
                add_skip(
                    reason="betrag_0",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Miete",
                    betrag=0.0,
                    message=f"{v.name}: Miete Betrag 0",
                )
            elif _invoice_exists(
                kunde,
                datum,
                v.name,
                "Miete",
                company=contract_company,
                wohnung=v.wohnung,
                include_drafts=include_drafts,
            ):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Miete",
                    betrag=betrag_miete,
                    message=f"{v.name}: Miete bereits vorhanden",
                )
            else:
                remark = _build_invoice_remark("Miete", monat_str)
                desc = f"Nettokaltmiete {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Miete",
                    desc,
                    betrag_miete,
                    income_accounts.get("Miete"),
                    kst,
                    remark,
                    v.wohnung,
                    contract_company,
                    mietabrechnung_id=mietabrechnung_id,
                )
                if sinv_name:
                    created["Miete"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Miete",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_miete,
                        posting_date=datum,
                    )

            # Betriebskosten-Vorauszahlung
            if only_typ and only_typ != "Betriebskosten":
                pass
            elif betrag_bk <= 0:
                add_skip(
                    reason="betrag_0",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Betriebskosten",
                    betrag=0.0,
                    message=f"{v.name}: Betriebskosten Betrag 0",
                )
            elif _invoice_exists(
                kunde,
                datum,
                v.name,
                "Betriebskosten",
                company=contract_company,
                wohnung=v.wohnung,
                include_drafts=include_drafts,
            ):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Betriebskosten",
                    betrag=betrag_bk,
                    message=f"{v.name}: Betriebskosten bereits vorhanden",
                )
            else:
                remark = _build_invoice_remark("Betriebskosten", monat_str)
                desc = f"Betriebskosten-Vorauszahlung {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Betriebskosten",
                    desc,
                    betrag_bk,
                    income_accounts.get("Betriebskosten"),
                    kst,
                    remark,
                    v.wohnung,
                    contract_company,
                    mietabrechnung_id=mietabrechnung_id,
                )
                if sinv_name:
                    created["Betriebskosten"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Betriebskosten",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_bk,
                        posting_date=datum,
                    )

            # Heizkosten-Vorauszahlung (nur wenn Staffeleintrag vorhanden)
            if only_typ and only_typ != "Heizkosten":
                pass
            elif betrag_heiz <= 0:
                add_skip(
                    reason="betrag_0",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Heizkosten",
                    betrag=0.0,
                    message=f"{v.name}: Heizkosten Betrag 0",
                )
            elif _invoice_exists(
                kunde,
                datum,
                v.name,
                "Heizkosten",
                company=contract_company,
                wohnung=v.wohnung,
                include_drafts=include_drafts,
            ):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Heizkosten",
                    betrag=betrag_heiz,
                    message=f"{v.name}: Heizkosten bereits vorhanden",
                )
            else:
                remark = _build_invoice_remark("Heizkosten", monat_str)
                desc = f"Heizkosten-Vorauszahlung {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Heizkosten",
                    desc,
                    betrag_heiz,
                    income_accounts.get("Heizkosten"),
                    kst,
                    remark,
                    v.wohnung,
                    contract_company,
                    mietabrechnung_id=mietabrechnung_id,
                )
                if sinv_name:
                    created["Heizkosten"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Heizkosten",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_heiz,
                        posting_date=datum,
                    )

            # Untermietzuschlag (nur wenn Staffel-Eintrag UND Erlöskonto konfiguriert)
            betrag_umz = _staffelbetrag(v.name, "untermietzuschlag", datum)
            umz_account = income_accounts.get("Untermietzuschlag")
            if only_typ and only_typ != "Untermietzuschlag":
                pass
            elif betrag_umz <= 0:
                # Kein UMZ-Eintrag oder Betrag 0 → still & leise. Mietverträge
                # ohne UMZ sind der Normalfall, kein Skip-Logging nötig.
                pass
            elif not umz_account:
                add_skip(
                    reason="kein_umz_konto",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Untermietzuschlag",
                    betrag=betrag_umz,
                    message=(
                        f"{v.name}: Untermietzuschlag {betrag_umz:.2f} € nicht abgerechnet — "
                        "Erlöskonto Untermietzuschlag in Hausverwaltung Einstellungen pflegen."
                    ),
                )
            elif _invoice_exists(
                kunde,
                datum,
                v.name,
                "Untermietzuschlag",
                company=contract_company,
                wohnung=v.wohnung,
                include_drafts=include_drafts,
            ):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Untermietzuschlag",
                    betrag=betrag_umz,
                    message=f"{v.name}: Untermietzuschlag bereits vorhanden",
                )
            else:
                remark = _build_invoice_remark("Untermietzuschlag", monat_str)
                desc = f"Untermietzuschlag {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Untermietzuschlag",
                    desc,
                    betrag_umz,
                    umz_account,
                    kst,
                    remark,
                    v.wohnung,
                    contract_company,
                    mietabrechnung_id=mietabrechnung_id,
                )
                if sinv_name:
                    created["Untermietzuschlag"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Untermietzuschlag",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_umz,
                        posting_date=datum,
                    )
    except Exception:
        if durchlauf_doc:
            durchlauf_doc.status = "Failed"
            durchlauf_doc.finished_at = now_datetime()
            durchlauf_doc.save(ignore_permissions=True)
        raise

    if durchlauf_doc:
        durchlauf_doc.status = "Completed"
        durchlauf_doc.finished_at = now_datetime()
        durchlauf_doc.created_miete = created.get("Miete", 0)
        durchlauf_doc.created_bk = created.get("Betriebskosten", 0)
        durchlauf_doc.created_heiz = created.get("Heizkosten", 0)
        durchlauf_doc.created_umz = created.get("Untermietzuschlag", 0)
        durchlauf_doc.created_total = sum(created.values())
        durchlauf_doc.skipped_count = len(skipped_details)
        durchlauf_doc.save(ignore_permissions=True)

    return {
        "created": created,
        "skipped": skipped,
        "skipped_details": skipped_details,
        "skipped_count": len(skipped_details),
        "month": datum.strftime("%Y-%m"),
        "durchlauf": durchlauf_doc.name if durchlauf_doc else None,
    }


# Alias, falls der Workspace-Button einen anderen Namen erwartet
@frappe.whitelist()
def generate_mietrechnungen(
    monat: str | int | None = None,
    jahr: str | int | None = None,
    company: str | None = None,
    mietvertrag: str | None = None,
    rechnungstyp: str | None = None,
    include_drafts_in_guard: int | str = 1,
) -> dict:
    return generate_miet_und_bk_rechnungen(
        monat=monat,
        jahr=jahr,
        company=company,
        mietvertrag=mietvertrag,
        rechnungstyp=rechnungstyp,
        include_drafts_in_guard=include_drafts_in_guard,
    )
