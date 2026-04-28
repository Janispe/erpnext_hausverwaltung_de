import frappe
from frappe import _
from frappe.utils import cint, flt
from hausverwaltung.hausverwaltung.utils.immobilie_accounts import get_immobilie_account_map

def execute(filters=None):
    filters = filters or {}
    cols = get_columns(filters)
    data, message = get_data(filters)

    # Für hierarchische Darstellung benötigt
    chart = None
    summary = None

    return cols, data, message, chart, summary

def get_columns(f):
    show_details = f.get("show_details")

    if show_details:
        columns = [
            {"label": _("Datum"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
            {"label": _("Konto"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 250},
            {"label": _("Belegart"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
            {"label": _("Beleg"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 150},
            {"label": _("Beschreibung"), "fieldname": "remarks", "fieldtype": "Data", "width": 250},
            {"label": _("Einnahmen"), "fieldname": "income", "fieldtype": "Currency", "width": 120},
            {"label": _("Ausgaben"), "fieldname": "expense", "fieldtype": "Currency", "width": 120},
            {"label": _("EÜR"), "fieldname": "euer_relevant", "fieldtype": "Check", "width": 60},
        ]
    else:
        columns = [
            {"label": _("Konto"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 300},
            {"label": _("Einnahmen"), "fieldname": "income", "fieldtype": "Currency", "width": 150},
            {"label": _("Ausgaben"), "fieldname": "expense", "fieldtype": "Currency", "width": 150},
            {"label": _("Saldo"), "fieldname": "balance", "fieldtype": "Currency", "width": 150},
        ]
    return columns

def _get_bank_cash_accounts(company: str) -> set[str]:
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabAccount`
        WHERE company = %(company)s
          AND is_group = 0
          AND account_type IN ('Bank', 'Cash')
        """,
        {"company": company},
        as_dict=True,
    )
    return {r["name"] for r in rows or [] if r.get("name")}

def _normalize_cost_centers(cost_centers) -> tuple[str, ...]:
    if not cost_centers:
        return ()
    if isinstance(cost_centers, str):
        return (cost_centers,)
    out = []
    for cc in cost_centers:
        if cc:
            out.append(str(cc))
    return tuple(sorted(set(out)))


def _get_immobilie_scope(immobilie: str | None) -> dict:
    scope = {
        "immobilien": [],
        "cost_centers": tuple(),
        "bank_accounts": set(),
    }
    if not immobilie:
        return scope

    immobilien = _get_descendant_immobilien(immobilie)

    rows = frappe.get_all(
        "Immobilie",
        filters={"name": ("in", immobilien)},
        fields=["name", "kostenstelle"],
        limit_page_length=0,
    )
    account_map = get_immobilie_account_map(immobilien)

    bank_accounts: set[str] = set()
    cost_centers: set[str] = set()
    names: list[str] = []
    for row in rows or []:
        name = row.get("name")
        if name:
            names.append(name)
        accounts = account_map.get(name) or {}
        for fieldname in ("bank_accounts", "cash_accounts"):
            for account in accounts.get(fieldname) or []:
                if account:
                    bank_accounts.add(str(account))
        kostenstelle = row.get("kostenstelle")
        if kostenstelle:
            cost_centers.add(str(kostenstelle))

    scope["immobilien"] = names or immobilien
    scope["cost_centers"] = tuple(sorted(cost_centers))
    scope["bank_accounts"] = bank_accounts
    return scope


def _get_descendant_immobilien(root_immobilie: str) -> list[str]:
    seen = {root_immobilie}
    ordered = [root_immobilie]
    queue = [root_immobilie]

    while queue:
        parent = queue.pop(0)
        children = frappe.get_all(
            "Immobilie",
            filters={"parent_immobilie": parent},
            pluck="name",
            limit_page_length=0,
        )
        for child in children or []:
            if not child or child in seen:
                continue
            seen.add(child)
            ordered.append(child)
            queue.append(child)

    return ordered


def _infer_bank_cash_accounts(company: str, cost_centers, to_date) -> set[str]:
    cost_centers = _normalize_cost_centers(cost_centers)
    if not cost_centers or not to_date:
        return set()
    cc_sub, cc_params = _gl_distinct_vouchers_subquery(
        "infer_cc",
        company=company,
        to_date=to_date,
        cost_centers=cost_centers,
        include_voucher_type=True,
    )
    rows = frappe.db.sql(
        f"""
        SELECT DISTINCT gle.account AS name
        FROM `tabGL Entry` gle
        INNER JOIN {cc_sub} cc
            ON cc.voucher_type = gle.voucher_type
           AND cc.voucher_no = gle.voucher_no
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.docstatus = 1
          AND gle.is_cancelled = 0
          AND gle.company = %(company)s
          AND gle.posting_date <= %(to_date)s
          AND acc.is_group = 0
          AND acc.account_type IN ('Bank', 'Cash')
        """,
        {"company": company, "to_date": to_date, **cc_params},
        as_dict=True,
    )
    return {r["name"] for r in rows or [] if r.get("name")}

def _get_bank_balance(company: str, bank_accounts: set[str], to_date, cost_centers=None, *, strict_before: bool = False) -> float:
    if not bank_accounts or not to_date:
        return 0.0

    conditions = [
        "gle.docstatus = 1",
        "gle.is_cancelled = 0",
        "gle.company = %(company)s",
        "gle.account IN %(bank_accounts)s",
    ]
    params = {"company": company, "bank_accounts": tuple(sorted(bank_accounts))}
    joins: list[str] = []

    if strict_before:
        conditions.append("gle.posting_date < %(to_date)s")
    else:
        conditions.append("gle.posting_date <= %(to_date)s")
    params["to_date"] = to_date

    cost_centers = _normalize_cost_centers(cost_centers)
    if cost_centers:
        cc_sub, cc_params = _gl_distinct_vouchers_subquery(
            "bal_cc",
            company=company,
            to_date=to_date,
            to_date_op="<" if strict_before else "<=",
            cost_centers=cost_centers,
            include_voucher_type=True,
        )
        joins.append(
            f"INNER JOIN {cc_sub} bal_cc ON bal_cc.voucher_type = gle.voucher_type AND bal_cc.voucher_no = gle.voucher_no"
        )
        params.update(cc_params)

    row = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(gle.debit - gle.credit), 0) AS bal
        FROM `tabGL Entry` gle
        {" ".join(joins)}
        WHERE {" AND ".join(conditions)}
        """,
        params,
        as_dict=True,
    )
    return flt((row or [{}])[0].get("bal"))

def _get_bank_movement_by_voucher(
    company: str,
    bank_accounts: set[str],
    from_date,
    to_date,
    cost_centers=None,
) -> dict[tuple[str, str], float]:
    if not bank_accounts or not from_date or not to_date:
        return {}

    conditions = [
        "gle.docstatus = 1",
        "gle.is_cancelled = 0",
        "gle.company = %(company)s",
        "gle.account IN %(bank_accounts)s",
        "gle.posting_date >= %(from_date)s",
        "gle.posting_date <= %(to_date)s",
        "gle.voucher_no IS NOT NULL",
        "gle.voucher_no != ''",
    ]
    params = {
        "company": company,
        "bank_accounts": tuple(sorted(bank_accounts)),
        "from_date": from_date,
        "to_date": to_date,
    }
    joins: list[str] = []

    cost_centers = _normalize_cost_centers(cost_centers)
    if cost_centers:
        cc_sub, cc_params = _gl_distinct_vouchers_subquery(
            "mv_cc",
            company=company,
            from_date=from_date,
            to_date=to_date,
            cost_centers=cost_centers,
            include_voucher_type=True,
        )
        joins.append(
            f"INNER JOIN {cc_sub} mv_cc ON mv_cc.voucher_type = gle.voucher_type AND mv_cc.voucher_no = gle.voucher_no"
        )
        params.update(cc_params)

    rows = frappe.db.sql(
        f"""
        SELECT gle.voucher_type, gle.voucher_no, COALESCE(SUM(gle.debit - gle.credit), 0) AS bank_net
        FROM `tabGL Entry` gle
        {" ".join(joins)}
        WHERE {" AND ".join(conditions)}
        GROUP BY gle.voucher_type, gle.voucher_no
        """,
        params,
        as_dict=True,
    )

    out = {}
    for r in rows or []:
        vt = (r.get("voucher_type") or "").strip()
        vn = (r.get("voucher_no") or "").strip()
        if not vt or not vn:
            continue
        out[(vt, vn)] = flt(r.get("bank_net"))
    return out

def _split_cash_in_out(amount: float) -> tuple[float, float]:
    amount = flt(amount)
    if amount >= 0:
        return amount, 0.0
    return 0.0, -amount

def _find_account_group_bounds(company: str, like: str) -> tuple[int, int] | None:
    row = frappe.db.sql(
        """
        SELECT lft, rgt
        FROM `tabAccount`
        WHERE company = %(company)s
          AND is_group = 1
          AND (name LIKE %(like)s OR account_name LIKE %(like)s)
        ORDER BY
            (account_name = REPLACE(%(like)s, '%%', '')) DESC,
            (name = REPLACE(%(like)s, '%%', '')) DESC,
            (rgt - lft) DESC
        LIMIT 1
        """,
        {"company": company, "like": like},
        as_dict=True,
    )
    if not row:
        return None
    lft = row[0].get("lft")
    rgt = row[0].get("rgt")
    if lft is None or rgt is None:
        return None
    return int(lft), int(rgt)

def _get_mieterforderungen_bounds(company: str) -> tuple[int, int] | None:
    """Return (lft, rgt) for the Sammelkonto Debitoren (account_number=1300, leaf or group).

    Im Sammelkonto-Modell ist 1300 ein Leaf — (lft, rgt) deckt dann nur dieses eine Konto ab.
    Falls das Konto noch als Gruppe (mit Per-Mieter-Children) existiert, deckt der Range alle Children mit.
    """
    row = frappe.db.sql(
        """
        SELECT name, lft, rgt
        FROM `tabAccount`
        WHERE company = %(company)s
          AND account_number = '1300'
        ORDER BY is_group DESC
        LIMIT 1
        """,
        {"company": company},
        as_dict=True,
    )
    if row:
        r = row[0]
        if r.get("lft") is not None and r.get("rgt") is not None:
            return int(r["lft"]), int(r["rgt"])

    row = frappe.db.sql(
        """
        SELECT name, lft, rgt
        FROM `tabAccount`
        WHERE company = %(company)s
          AND (name LIKE %(like)s OR account_name LIKE %(like)s)
        ORDER BY is_group DESC
        LIMIT 1
        """,
        {"company": company, "like": "%Mieterforderungen%"},
        as_dict=True,
    )
    if row:
        r = row[0]
        if r.get("lft") is not None and r.get("rgt") is not None:
            return int(r["lft"]), int(r["rgt"])

    return None

def _accounts_in_bounds(company: str, accounts: set[str], bounds: tuple[int, int]) -> set[str]:
    if not accounts:
        return set()
    lft, rgt = bounds
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabAccount`
        WHERE company = %(company)s
          AND name IN %(names)s
          AND lft >= %(lft)s
          AND rgt <= %(rgt)s
        """,
        {"company": company, "names": tuple(sorted(accounts)), "lft": lft, "rgt": rgt},
        as_dict=True,
    )
    return {r["name"] for r in rows or [] if r.get("name")}

def _gl_distinct_vouchers_subquery(
    prefix: str,
    *,
    company: str,
    voucher_type: str | None = None,
    exclude_voucher_types: tuple[str, ...] | None = None,
    from_date=None,
    to_date=None,
    to_date_op: str = "<=",
    bank_accounts: set[str] | None = None,
    cost_centers=None,
    include_voucher_type: bool = False,
) -> tuple[str, dict]:
    if bank_accounts is not None and not bank_accounts:
        # Join-safe empty set: yields no rows.
        cols = "voucher_type, voucher_no" if include_voucher_type else "voucher_no"
        return f"(SELECT NULL AS {cols.replace(', ', ', NULL AS ')} WHERE 1=0)", {}

    conditions = [
        "docstatus = 1",
        "is_cancelled = 0",
        f"company = %({prefix}_company)s",
        "voucher_no IS NOT NULL",
        "voucher_no != ''",
    ]
    params: dict = {f"{prefix}_company": company}

    if voucher_type:
        conditions.append(f"voucher_type = %({prefix}_voucher_type)s")
        params[f"{prefix}_voucher_type"] = voucher_type
    if exclude_voucher_types:
        conditions.append(f"voucher_type NOT IN %({prefix}_exclude_voucher_types)s")
        params[f"{prefix}_exclude_voucher_types"] = tuple(exclude_voucher_types)

    if from_date:
        conditions.append(f"posting_date >= %({prefix}_from_date)s")
        params[f"{prefix}_from_date"] = from_date
    if to_date:
        if to_date_op not in ("<", "<="):
            raise ValueError("to_date_op must be '<' or '<='")
        conditions.append(f"posting_date {to_date_op} %({prefix}_to_date)s")
        params[f"{prefix}_to_date"] = to_date

    if bank_accounts is not None:
        conditions.append(f"account IN %({prefix}_bank_accounts)s")
        params[f"{prefix}_bank_accounts"] = tuple(sorted(bank_accounts))

    cost_centers = _normalize_cost_centers(cost_centers)
    if cost_centers:
        conditions.append(f"cost_center IN %({prefix}_cost_centers)s")
        params[f"{prefix}_cost_centers"] = cost_centers

    cols = "voucher_type, voucher_no" if include_voucher_type else "voucher_no"
    return (
        f"(SELECT DISTINCT {cols} FROM `tabGL Entry` WHERE {' AND '.join(conditions)})",
        params,
    )

def get_data(f):
    company = f.get("company")
    immobilie = f.get("immobilie")
    show_details = f.get("show_details")
    include_non_euer_accounts = cint(f.get("include_non_euer_accounts")) == 1
    show_bank_check = cint(f.get("show_bank_check")) == 1

    if not company:
        company = frappe.defaults.get_user_default("Company")

    if not company:
        frappe.throw(_("Bitte eine Company auswählen."))

    # Optional: Filter nach Immobilie (über Kostenstelle)
    immobilie_scope = _get_immobilie_scope(immobilie) if immobilie else {"cost_centers": tuple(), "bank_accounts": set()}
    kostenstellen = immobilie_scope.get("cost_centers") or tuple()
    selected_accounts = set(_coerce_multi_filter(f.get("konten")))
    if immobilie:
        pass

    from_date = f.get("from_date")
    to_date = f.get("to_date")

    # EÜR = Zufluss-/Abflussprinzip (Cash Basis)
    # Wir müssen zwei Arten von Zahlungen erfassen:
    #
    # 1. Payment Entries die Sales/Purchase Invoices bezahlen
    #    → Zahlungsdatum + Income/Expense aus der Invoice
    #
    # 2. Journal Entries die direkt Income/Expense buchen
    #    → Buchungsdatum + Income/Expense-Konto

    all_entries = []
    pe_cashflow_by_voucher = {}
    bank_accounts: set[str] = set()
    bank_accounts_specific = False
    bank_accounts_inferred = False

    if immobilie:
        bank_accounts.update(immobilie_scope.get("bank_accounts") or set())
        bank_accounts_specific = bool(bank_accounts)

        if kostenstellen:
            inferred_accounts = _infer_bank_cash_accounts(company, kostenstellen, to_date)
            if inferred_accounts:
                bank_accounts.update(inferred_accounts)
                bank_accounts_inferred = True

    if not bank_accounts:
        bank_accounts = _get_bank_cash_accounts(company)
        bank_accounts_specific = False
        bank_accounts_inferred = False

    if selected_accounts:
        bank_accounts &= selected_accounts
        bank_accounts_specific = True

    if not bank_accounts:
        return [], _("Keine passenden Bank-/Kassenkonten für die aktuelle Filterkombination gefunden.")

    # Für Immobilien-Scope behalten wir die Kostenstelle immer als zusätzlichen Filter aktiv.
    # Explizit hinterlegte Bank/Kasse-Konten können unvollständig sein; die Kostenstelle grenzt den Belegsatz sauber ein.
    apply_cost_center_filter = bool(kostenstellen)

    # ========== Teil 1: Payment Entries ==========
    pe_conditions = ["pe.docstatus = 1", "pe.company = %(company)s"]
    pe_params = {"company": company}
    pe_joins: list[str] = []

    if from_date:
        pe_conditions.append("pe.posting_date >= %(from_date)s")
        pe_params["from_date"] = from_date
    if to_date:
        pe_conditions.append("pe.posting_date <= %(to_date)s")
        pe_params["to_date"] = to_date

    bank_pe_sub, bank_pe_params = _gl_distinct_vouchers_subquery(
        "pe_bank",
        company=company,
        voucher_type="Payment Entry",
        from_date=from_date,
        to_date=to_date,
        bank_accounts=bank_accounts,
    )
    pe_joins.append(f"INNER JOIN {bank_pe_sub} pe_bank ON pe_bank.voucher_no = pe.name")
    pe_params.update(bank_pe_params)

    if apply_cost_center_filter and kostenstellen:
        cc_pe_sub, cc_pe_params = _gl_distinct_vouchers_subquery(
            "pe_cc",
            company=company,
            voucher_type="Payment Entry",
            from_date=from_date,
            to_date=to_date,
            cost_centers=kostenstellen,
        )
        pe_joins.append(f"INNER JOIN {cc_pe_sub} pe_cc ON pe_cc.voucher_no = pe.name")
        pe_params.update(cc_pe_params)

    # Hole alle Payment Entries mit ihren verlinkten Invoices
    payment_entries = frappe.db.sql(
        f"""
        SELECT
            pe.name as payment_name,
            pe.posting_date,
            pe.remarks,
            per.reference_doctype,
            per.reference_name,
            per.allocated_amount
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        {" ".join(pe_joins)}
        WHERE {" AND ".join(pe_conditions)}
          AND per.reference_doctype IN ('Sales Invoice', 'Purchase Invoice')
        ORDER BY pe.posting_date ASC
        """,
        pe_params,
        as_dict=True,
    )
    mapped_payment_entries = {str(pe.get("payment_name")) for pe in payment_entries or [] if pe.get("payment_name")}
    invoice_payment_entry_names = sorted(mapped_payment_entries)
    pe_posting_date_by_voucher = {
        str(pe.get("payment_name")): pe.get("posting_date")
        for pe in (payment_entries or [])
        if pe.get("payment_name")
    }

    # Additional Payment Entries with receivable "Mieterforderungen" contra account but no invoice reference.
    # These are treated as EÜR-relevant cashflow and shown under Einnahmen/Ausgaben as "Guthaben Mieter".
    guthaben_mieter_entries: list[dict] = []
    try:
        bounds = _get_mieterforderungen_bounds(company)
        if bounds and bank_accounts:
            pe2_conditions = ["pe.docstatus = 1", "pe.company = %(company)s"]
            pe2_params = {"company": company}
            pe2_joins: list[str] = []

            if from_date:
                pe2_conditions.append("pe.posting_date >= %(from_date)s")
                pe2_params["from_date"] = from_date
            if to_date:
                pe2_conditions.append("pe.posting_date <= %(to_date)s")
                pe2_params["to_date"] = to_date

            bank_pe2_sub, bank_pe2_params = _gl_distinct_vouchers_subquery(
                "pe2_bank",
                company=company,
                voucher_type="Payment Entry",
                from_date=from_date,
                to_date=to_date,
                bank_accounts=bank_accounts,
            )
            pe2_joins.append(f"INNER JOIN {bank_pe2_sub} pe2_bank ON pe2_bank.voucher_no = pe.name")
            pe2_params.update(bank_pe2_params)

            if apply_cost_center_filter and kostenstellen:
                cc_pe2_sub, cc_pe2_params = _gl_distinct_vouchers_subquery(
                    "pe2_cc",
                    company=company,
                    voucher_type="Payment Entry",
                    from_date=from_date,
                    to_date=to_date,
                    cost_centers=kostenstellen,
                )
                pe2_joins.append(f"INNER JOIN {cc_pe2_sub} pe2_cc ON pe2_cc.voucher_no = pe.name")
                pe2_params.update(cc_pe2_params)

            # Only those without invoice references (Sales/Purchase Invoice).
            pe2_rows = frappe.db.sql(
                f"""
                SELECT pe.name, pe.posting_date, pe.remarks
                FROM `tabPayment Entry` pe
                {" ".join(pe2_joins)}
                WHERE {" AND ".join(pe2_conditions)}
                  AND pe.name NOT IN %(mapped)s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM `tabPayment Entry Reference` per
                      WHERE per.parent = pe.name
                        AND per.reference_doctype IN ('Sales Invoice', 'Purchase Invoice')
                  )
                """,
                {**pe2_params, "mapped": tuple(invoice_payment_entry_names) or ("",)},
                as_dict=True,
            )
            pe2_names = [r["name"] for r in pe2_rows or [] if r.get("name")]

            if pe2_names:
                # Determine the strongest receivable contra account per voucher.
                contra_rows = frappe.db.sql(
                    """
                    SELECT
                        gle.voucher_no,
                        gle.account,
                        SUM(ABS(gle.debit - gle.credit)) AS weight
                    FROM `tabGL Entry` gle
                    INNER JOIN `tabAccount` acc ON acc.name = gle.account
                    WHERE gle.docstatus = 1
                      AND gle.is_cancelled = 0
                      AND gle.company = %(company)s
                      AND gle.voucher_type = 'Payment Entry'
                      AND gle.voucher_no IN %(voucher_nos)s
                      AND acc.account_type = 'Receivable'
                    GROUP BY gle.voucher_no, gle.account
                    """,
                    {"company": company, "voucher_nos": tuple(pe2_names)},
                    as_dict=True,
                )
                contra_by_voucher = {}
                receivable_accounts = set()
                for r in contra_rows or []:
                    vno = r.get("voucher_no")
                    acc = r.get("account")
                    if not vno or not acc:
                        continue
                    receivable_accounts.add(acc)
                    weight = flt(r.get("weight"))
                    prev = contra_by_voucher.get(vno)
                    if not prev or weight > flt(prev.get("weight")):
                        contra_by_voucher[vno] = {"account": acc, "weight": weight}

                mieterkonten = _accounts_in_bounds(company, receivable_accounts, bounds)
                if mieterkonten:
                    bank_net_rows = frappe.db.sql(
                        """
                        SELECT gle.voucher_no, SUM(gle.debit - gle.credit) AS bank_net
                        FROM `tabGL Entry` gle
                        WHERE gle.docstatus = 1
                          AND gle.is_cancelled = 0
                          AND gle.company = %(company)s
                          AND gle.voucher_type = 'Payment Entry'
                          AND gle.voucher_no IN %(voucher_nos)s
                          AND gle.account IN %(bank_accounts)s
                        GROUP BY gle.voucher_no
                        """,
                        {
                            "company": company,
                            "voucher_nos": tuple(pe2_names),
                            "bank_accounts": tuple(sorted(bank_accounts)),
                        },
                        as_dict=True,
                    )
                    bank_net_by_voucher = {
                        r["voucher_no"]: flt(r.get("bank_net"))
                        for r in bank_net_rows or []
                        if r.get("voucher_no")
                    }

                    remarks_by_voucher = {r["name"]: (r.get("remarks") or "") for r in pe2_rows or [] if r.get("name")}
                    posting_date_by_voucher = {r["name"]: r.get("posting_date") for r in pe2_rows or [] if r.get("name")}

                    for vno in pe2_names:
                        contra = contra_by_voucher.get(vno) or {}
                        contra_acc = contra.get("account")
                        if not contra_acc or contra_acc not in mieterkonten:
                            continue
                        bank_net = flt(bank_net_by_voucher.get(vno))
                        if bank_net == 0:
                            continue
                        inc, exp = _split_cash_in_out(bank_net)
                        root_type = "Income" if inc else ("Expense" if exp else None)
                        guthaben_mieter_entries.append(
                            {
                                "posting_date": posting_date_by_voucher.get(vno),
                                "account": "Guthaben Mieter",
                                "voucher_type": "Payment Entry",
                                "voucher_no": vno,
                                "remarks": remarks_by_voucher.get(vno) or "Guthaben Mieter (Payment Entry ohne Rechnung)",
                                "income": inc,
                                "expense": exp,
                                "root_type": root_type,
                                "euer_relevant_override": 1,
                            }
                        )
    except Exception:
        # Never break the report for this convenience bucket.
        guthaben_mieter_entries = []

    # Prefetch invoice items/totals to avoid N+1 queries and to support Teilzahlungen.
    sales_invoices = sorted(
        {
            str(pe.reference_name)
            for pe in payment_entries
            if pe.get("reference_doctype") == "Sales Invoice" and pe.get("reference_name")
        }
    )
    purchase_invoices = sorted(
        {
            str(pe.reference_name)
            for pe in payment_entries
            if pe.get("reference_doctype") == "Purchase Invoice" and pe.get("reference_name")
        }
    )

    sales_grand_total_by_invoice = {}
    if sales_invoices:
        rows = frappe.db.sql(
            """
            SELECT name, grand_total
            FROM `tabSales Invoice`
            WHERE name IN %(names)s
            """,
            {"names": tuple(sales_invoices)},
            as_dict=True,
        )
        sales_grand_total_by_invoice = {r["name"]: flt(r.get("grand_total")) for r in rows or []}

    purchase_grand_total_by_invoice = {}
    if purchase_invoices:
        rows = frappe.db.sql(
            """
            SELECT name, grand_total
            FROM `tabPurchase Invoice`
            WHERE name IN %(names)s
            """,
            {"names": tuple(purchase_invoices)},
            as_dict=True,
        )
        purchase_grand_total_by_invoice = {r["name"]: flt(r.get("grand_total")) for r in rows or []}

    from collections import defaultdict

    sales_items_by_invoice = defaultdict(list)
    if sales_invoices:
        rows = frappe.db.sql(
            """
            SELECT parent, income_account as account, amount
            FROM `tabSales Invoice Item`
            WHERE parent IN %(names)s
            """,
            {"names": tuple(sales_invoices)},
            as_dict=True,
        )
        for r in rows or []:
            if not r.get("account"):
                continue
            sales_items_by_invoice[r["parent"]].append(
                {"account": r["account"], "amount": flt(r.get("amount"))}
            )

    purchase_items_by_invoice = defaultdict(list)
    if purchase_invoices:
        rows = frappe.db.sql(
            """
            SELECT parent, expense_account as account, amount
            FROM `tabPurchase Invoice Item`
            WHERE parent IN %(names)s
            """,
            {"names": tuple(purchase_invoices)},
            as_dict=True,
        )
        for r in rows or []:
            if not r.get("account"):
                continue
            purchase_items_by_invoice[r["parent"]].append(
                {"account": r["account"], "amount": flt(r.get("amount"))}
            )

    used_accounts = set()
    for items in sales_items_by_invoice.values():
        for it in items:
            used_accounts.add(it["account"])
    for items in purchase_items_by_invoice.values():
        for it in items:
            used_accounts.add(it["account"])

    account_root_type = {}
    if used_accounts:
        rows = frappe.db.sql(
            """
            SELECT name, root_type
            FROM `tabAccount`
            WHERE name IN %(names)s
            """,
            {"names": tuple(sorted(used_accounts))},
            as_dict=True,
        )
        account_root_type = {r["name"]: r.get("root_type") for r in rows or []}

    # Für jede Payment Entry: Hole das Income/Expense-Konto aus der verlinkten Invoice
    for pe in payment_entries:
        if not pe.reference_name:
            continue

        allocated_amount = flt(pe.get("allocated_amount"))
        if allocated_amount == 0:
            continue
        allocated_abs = abs(allocated_amount)

        # Hole Income/Expense-Konten aus der Invoice
        if pe.reference_doctype == "Sales Invoice":
            invoice = str(pe.reference_name)
            items = sales_items_by_invoice.get(invoice) or []
            if not items:
                continue

            denom = sales_grand_total_by_invoice.get(invoice)
            if not denom or denom == 0:
                denom = sum(flt(it.get("amount")) for it in items)
            if not denom or denom == 0:
                continue

            scale = min(1.0, allocated_abs / abs(denom))
            for item in items:
                root_type = account_root_type.get(item["account"])
                if root_type in ("Income", "Expense"):
                    amt = flt(item.get("amount")) * scale
                    if amt == 0:
                        continue
                    all_entries.append({
                        "posting_date": pe.posting_date,
                        "account": item["account"],
                        "voucher_type": "Payment Entry",
                        "voucher_no": pe.payment_name,
                        "remarks": pe.remarks or f"Zahlung für {invoice}",
                        "income": amt if root_type == "Income" else 0,
                        "expense": amt if root_type == "Expense" else 0,
                        "root_type": root_type,
                    })
                    pe_cashflow_by_voucher[pe.payment_name] = flt(pe_cashflow_by_voucher.get(pe.payment_name, 0.0)) + (
                        amt if root_type == "Income" else -amt
                    )

        elif pe.reference_doctype == "Purchase Invoice":
            invoice = str(pe.reference_name)
            items = purchase_items_by_invoice.get(invoice) or []
            if not items:
                continue

            denom = purchase_grand_total_by_invoice.get(invoice)
            if not denom or denom == 0:
                denom = sum(flt(it.get("amount")) for it in items)
            if not denom or denom == 0:
                continue

            scale = min(1.0, allocated_abs / abs(denom))
            for item in items:
                root_type = account_root_type.get(item["account"])
                if root_type in ("Income", "Expense"):
                    amt = flt(item.get("amount")) * scale
                    if amt == 0:
                        continue
                    all_entries.append({
                        "posting_date": pe.posting_date,
                        "account": item["account"],
                        "voucher_type": "Payment Entry",
                        "voucher_no": pe.payment_name,
                        "remarks": pe.remarks or f"Zahlung für {invoice}",
                        "income": amt if root_type == "Income" else 0,
                        "expense": amt if root_type == "Expense" else 0,
                        "root_type": root_type,
                    })
                    pe_cashflow_by_voucher[pe.payment_name] = flt(pe_cashflow_by_voucher.get(pe.payment_name, 0.0)) + (
                        amt if root_type == "Income" else -amt
                    )

    # Zusätzliche GL-Linien aus Payment Entry (z.B. Bankgebühren/Deductions) mitnehmen.
    # (Receivable/Payable lassen wir hier bewusst weg, weil die via Invoice-Items abgebildet werden.)
    if invoice_payment_entry_names:
        gle_conditions = [
            "gle.docstatus = 1",
            "gle.is_cancelled = 0",
            "gle.company = %(company)s",
            "gle.voucher_type = 'Payment Entry'",
            "gle.voucher_no IN %(voucher_nos)s",
            "gle.account NOT IN %(bank_accounts)s",
            "acc.account_type NOT IN ('Receivable', 'Payable')",
        ]
        gle_params = {
            "company": company,
            "voucher_nos": tuple(invoice_payment_entry_names),
            "bank_accounts": tuple(sorted(bank_accounts)) if bank_accounts else ("",),
        }
        if from_date:
            gle_conditions.append("gle.posting_date >= %(from_date)s")
            gle_params["from_date"] = from_date
        if to_date:
            gle_conditions.append("gle.posting_date <= %(to_date)s")
            gle_params["to_date"] = to_date
        if apply_cost_center_filter and kostenstellen:
            gle_conditions.append(
                "EXISTS (SELECT 1 FROM `tabGL Entry` cc WHERE cc.docstatus = 1 AND cc.is_cancelled = 0 AND cc.company = gle.company AND cc.voucher_type = gle.voucher_type AND cc.voucher_no = gle.voucher_no AND cc.cost_center IN %(cost_centers)s)"
            )
            gle_params["cost_centers"] = kostenstellen

        extra_pe_gl = frappe.db.sql(
            f"""
            SELECT
                gle.posting_date,
                gle.account,
                gle.debit,
                gle.credit,
                gle.voucher_no,
                gle.remarks,
                acc.root_type
            FROM `tabGL Entry` gle
            INNER JOIN `tabAccount` acc ON acc.name = gle.account
            WHERE {" AND ".join(gle_conditions)}
            ORDER BY gle.posting_date ASC
            """,
            gle_params,
            as_dict=True,
        )

        for row in extra_pe_gl or []:
            root_type = row.get("root_type")
            if root_type == "Income":
                income_val = flt(row.get("credit")) - flt(row.get("debit"))
                expense_val = 0.0
            elif root_type == "Expense":
                income_val = 0.0
                expense_val = flt(row.get("debit")) - flt(row.get("credit"))
            else:
                if not include_non_euer_accounts:
                    continue
                income_val, expense_val = _split_cash_in_out(flt(row.get("credit")) - flt(row.get("debit")))

            if income_val == 0 and expense_val == 0:
                continue
            all_entries.append(
                {
                    "posting_date": row.get("posting_date"),
                    "account": row.get("account"),
                    "voucher_type": "Payment Entry",
                    "voucher_no": row.get("voucher_no"),
                    "remarks": row.get("remarks") or "",
                    "income": income_val,
                    "expense": expense_val,
                    "root_type": root_type,
                }
            )
            pe_cashflow_by_voucher[row.get("voucher_no")] = flt(
                pe_cashflow_by_voucher.get(row.get("voucher_no"), 0.0)
            ) + (flt(income_val) - flt(expense_val))

    # Add "Guthaben Mieter" entries (Payment Entries without invoices but against Mieterkonto).
    # Wenn Nicht‑EÜR Konten angezeigt werden, werden diese Payment Entries ohnehin später als Direct‑PE
    # über die GL-Linien (Receivable/Payable etc.) erfasst – sonst würden wir doppelt zählen.
    if guthaben_mieter_entries and not include_non_euer_accounts:
        for e in guthaben_mieter_entries:
            all_entries.append(e)

    # Overpayment/unallocated-Anteile bei Payment Entries, die (teilweise) Rechnungen bezahlen, aber auf
    # Mieterforderungskonten (Debitor/Mieterkonto) laufen, sollen im normalen Modus ebenfalls als
    # EÜR-relevanter Cashflow unter "Guthaben Mieter" erscheinen.
    if invoice_payment_entry_names and not include_non_euer_accounts:
        try:
            bounds = _get_mieterforderungen_bounds(company)
            if bounds and bank_accounts:
                net_conditions = [
                    "gle.docstatus = 1",
                    "gle.is_cancelled = 0",
                    "gle.company = %(company)s",
                    "gle.voucher_type = 'Payment Entry'",
                    "gle.voucher_no IN %(voucher_nos)s",
                    "acc.account_type IN ('Bank', 'Cash')",
                ]
                net_params = {"company": company, "voucher_nos": tuple(invoice_payment_entry_names)}
                if from_date:
                    net_conditions.append("gle.posting_date >= %(from_date)s")
                    net_params["from_date"] = from_date
                if to_date:
                    net_conditions.append("gle.posting_date <= %(to_date)s")
                    net_params["to_date"] = to_date
                if apply_cost_center_filter and kostenstellen:
                    net_conditions.append(
                        "EXISTS (SELECT 1 FROM `tabGL Entry` cc WHERE cc.docstatus = 1 AND cc.is_cancelled = 0 AND cc.company = gle.company AND cc.voucher_type = gle.voucher_type AND cc.voucher_no = gle.voucher_no AND cc.cost_center IN %(cost_centers)s)"
                    )
                    net_params["cost_centers"] = kostenstellen

                bank_net_rows = frappe.db.sql(
                    f"""
                    SELECT gle.voucher_no, SUM(gle.debit - gle.credit) AS bank_net
                    FROM `tabGL Entry` gle
                    INNER JOIN `tabAccount` acc ON acc.name = gle.account
                    WHERE {" AND ".join(net_conditions)}
                    GROUP BY gle.voucher_no
                    """,
                    net_params,
                    as_dict=True,
                )
                bank_net_by_voucher = {
                    r["voucher_no"]: flt(r.get("bank_net"))
                    for r in bank_net_rows or []
                    if r.get("voucher_no")
                }

                party_rows = frappe.db.sql(
                    f"""
                    SELECT
                        gle.voucher_no,
                        gle.account,
                        acc.root_type,
                        SUM(ABS(gle.debit - gle.credit)) AS weight
                    FROM `tabGL Entry` gle
                    INNER JOIN `tabAccount` acc ON acc.name = gle.account
                    WHERE gle.docstatus = 1
                      AND gle.is_cancelled = 0
                      AND gle.company = %(company)s
                      AND gle.voucher_type = 'Payment Entry'
                      AND gle.voucher_no IN %(voucher_nos)s
                      AND acc.account_type IN ('Receivable', 'Payable')
                      {"AND gle.posting_date >= %(from_date)s" if from_date else ""}
                      {"AND gle.posting_date <= %(to_date)s" if to_date else ""}
                      {"AND EXISTS (SELECT 1 FROM `tabGL Entry` cc WHERE cc.docstatus = 1 AND cc.is_cancelled = 0 AND cc.company = gle.company AND cc.voucher_type = gle.voucher_type AND cc.voucher_no = gle.voucher_no AND cc.cost_center IN %(cost_centers)s)" if (apply_cost_center_filter and kostenstellen) else ""}
                    GROUP BY gle.voucher_no, gle.account, acc.root_type
                    """,
                    {
                        "company": company,
                        "voucher_nos": tuple(invoice_payment_entry_names),
                        **({"from_date": from_date} if from_date else {}),
                        **({"to_date": to_date} if to_date else {}),
                        **({"cost_centers": kostenstellen} if (apply_cost_center_filter and kostenstellen) else {}),
                    },
                    as_dict=True,
                )
                party_by_voucher = {}
                for r in party_rows or []:
                    vno = r.get("voucher_no")
                    if not vno:
                        continue
                    weight = flt(r.get("weight"))
                    prev = party_by_voucher.get(vno)
                    if not prev or weight > flt(prev.get("weight")):
                        party_by_voucher[vno] = {"account": r.get("account"), "weight": weight}

                mieterkonten = _accounts_in_bounds(
                    company,
                    {v.get("account") for v in party_by_voucher.values() if v.get("account")},
                    bounds,
                )
                if mieterkonten:
                    for vno, bank_net in bank_net_by_voucher.items():
                        added = flt(pe_cashflow_by_voucher.get(vno, 0.0))
                        diff = flt(bank_net - added)
                        if abs(diff) < 0.005:
                            continue
                        party_account = (party_by_voucher.get(vno) or {}).get("account")
                        if not party_account or party_account not in mieterkonten:
                            continue
                        inc, exp = _split_cash_in_out(diff)
                        if inc == 0 and exp == 0:
                            continue
                        root_type = "Income" if inc else ("Expense" if exp else None)
                        all_entries.append(
                            {
                                "posting_date": pe_posting_date_by_voucher.get(vno),
                                "account": "Guthaben Mieter",
                                "voucher_type": "Payment Entry",
                                "voucher_no": vno,
                                "remarks": f"Guthaben/Nachzahlung Mieter (Restbetrag / unallocated) [{party_account}]",
                                "income": inc,
                                "expense": exp,
                                "root_type": root_type,
                                "euer_relevant_override": 1,
                            }
                        )
        except Exception:
            pass

    # Restbetrag (unallocated / Overpayment / etc.) pro Payment Entry ausgleichen, sonst passt Bank-Abgleich nicht.
    if include_non_euer_accounts and invoice_payment_entry_names:
        net_conditions = [
            "gle.docstatus = 1",
            "gle.is_cancelled = 0",
            "gle.company = %(company)s",
            "gle.voucher_type = 'Payment Entry'",
            "gle.voucher_no IN %(voucher_nos)s",
            "acc.account_type IN ('Bank', 'Cash')",
        ]
        net_params = {"company": company, "voucher_nos": tuple(invoice_payment_entry_names)}
        if from_date:
            net_conditions.append("gle.posting_date >= %(from_date)s")
            net_params["from_date"] = from_date
        if to_date:
            net_conditions.append("gle.posting_date <= %(to_date)s")
            net_params["to_date"] = to_date
        if apply_cost_center_filter and kostenstellen:
            net_conditions.append(
                "EXISTS (SELECT 1 FROM `tabGL Entry` cc WHERE cc.docstatus = 1 AND cc.is_cancelled = 0 AND cc.company = gle.company AND cc.voucher_type = gle.voucher_type AND cc.voucher_no = gle.voucher_no AND cc.cost_center IN %(cost_centers)s)"
            )
            net_params["cost_centers"] = kostenstellen

        bank_net_rows = frappe.db.sql(
            f"""
            SELECT gle.voucher_no, SUM(gle.debit - gle.credit) AS bank_net
            FROM `tabGL Entry` gle
            INNER JOIN `tabAccount` acc ON acc.name = gle.account
            WHERE {" AND ".join(net_conditions)}
            GROUP BY gle.voucher_no
            """,
            net_params,
            as_dict=True,
        )
        bank_net_by_voucher = {r["voucher_no"]: flt(r.get("bank_net")) for r in bank_net_rows or [] if r.get("voucher_no")}

        party_rows = frappe.db.sql(
            f"""
            SELECT
                gle.voucher_no,
                gle.account,
                acc.root_type,
                SUM(ABS(gle.debit - gle.credit)) AS weight
            FROM `tabGL Entry` gle
            INNER JOIN `tabAccount` acc ON acc.name = gle.account
            WHERE gle.docstatus = 1
              AND gle.is_cancelled = 0
              AND gle.company = %(company)s
              AND gle.voucher_type = 'Payment Entry'
              AND gle.voucher_no IN %(voucher_nos)s
              AND acc.account_type IN ('Receivable', 'Payable')
              {"AND gle.posting_date >= %(from_date)s" if from_date else ""}
              {"AND gle.posting_date <= %(to_date)s" if to_date else ""}
              {"AND EXISTS (SELECT 1 FROM `tabGL Entry` cc WHERE cc.docstatus = 1 AND cc.is_cancelled = 0 AND cc.company = gle.company AND cc.voucher_type = gle.voucher_type AND cc.voucher_no = gle.voucher_no AND cc.cost_center IN %(cost_centers)s)" if (apply_cost_center_filter and kostenstellen) else ""}
            GROUP BY gle.voucher_no, gle.account, acc.root_type
            """,
            {
                "company": company,
                "voucher_nos": tuple(invoice_payment_entry_names),
                **({"from_date": from_date} if from_date else {}),
                **({"to_date": to_date} if to_date else {}),
                **({"cost_centers": kostenstellen} if (apply_cost_center_filter and kostenstellen) else {}),
            },
            as_dict=True,
        )
        party_by_voucher = {}
        for r in party_rows or []:
            vno = r.get("voucher_no")
            if not vno:
                continue
            weight = flt(r.get("weight"))
            prev = party_by_voucher.get(vno)
            if not prev or weight > flt(prev.get("weight")):
                party_by_voucher[vno] = {
                    "account": r.get("account"),
                    "root_type": r.get("root_type"),
                    "weight": weight,
                }

        # Wenn der "Restbetrag" auf einem Mieterkonto (Mieterforderungen/Debitoren) liegt,
        # soll er auch im Modus "Nicht‑EÜR Konten anzeigen" als EÜR-relevantes "Guthaben Mieter"
        # erscheinen (statt als Asset/Receivable).
        mieterkonten = set()
        try:
            bounds = _get_mieterforderungen_bounds(company)
            if bounds and party_by_voucher:
                mieterkonten = _accounts_in_bounds(
                    company,
                    {v.get("account") for v in party_by_voucher.values() if v.get("account")},
                    bounds,
                )
        except Exception:
            mieterkonten = set()

        for vno, bank_net in bank_net_by_voucher.items():
            added = flt(pe_cashflow_by_voucher.get(vno, 0.0))
            diff = flt(bank_net - added)
            if abs(diff) < 0.005:
                continue
            party = party_by_voucher.get(vno) or {}
            party_account = party.get("account")
            if not party_account:
                continue
            inc, exp = _split_cash_in_out(diff)
            if party_account in mieterkonten:
                root_type = "Income" if inc else ("Expense" if exp else None)
                all_entries.append(
                    {
                        "posting_date": pe_posting_date_by_voucher.get(vno),
                        "account": "Guthaben Mieter",
                        "voucher_type": "Payment Entry",
                        "voucher_no": vno,
                        "remarks": f"Guthaben/Nachzahlung Mieter (Restbetrag / unallocated) [{party_account}]",
                        "income": inc,
                        "expense": exp,
                        "root_type": root_type,
                        "euer_relevant_override": 1,
                    }
                )
            else:
                all_entries.append(
                    {
                        "posting_date": pe_posting_date_by_voucher.get(vno),
                        "account": party_account,
                        "voucher_type": "Payment Entry",
                        "voucher_no": vno,
                        "remarks": "Restbetrag / unallocated (Payment Entry)",
                        "income": inc,
                        "expense": exp,
                        "root_type": party.get("root_type"),
                    }
                )

    # ========== Teil 2: Journal Entries ==========
    # Nur Journal Entries, die Bank/Kasse enthalten (Cash Basis)
    je_conditions = [
        "gle.company = %(company)s",
        "gle.docstatus = 1",
        "gle.is_cancelled = 0",
        "gle.voucher_type = 'Journal Entry'",
        "gle.account NOT IN %(bank_accounts)s",
    ]
    je_params = {"company": company, "bank_accounts": tuple(sorted(bank_accounts)) if bank_accounts else ("",)}
    je_joins: list[str] = []

    bank_je_sub, bank_je_params = _gl_distinct_vouchers_subquery(
        "je_bank",
        company=company,
        voucher_type="Journal Entry",
        from_date=from_date,
        to_date=to_date,
        bank_accounts=bank_accounts,
    )
    je_joins.append(f"INNER JOIN {bank_je_sub} je_bank ON je_bank.voucher_no = gle.voucher_no")
    je_params.update(bank_je_params)

    if from_date:
        je_conditions.append("gle.posting_date >= %(from_date)s")
        je_params["from_date"] = from_date
    if to_date:
        je_conditions.append("gle.posting_date <= %(to_date)s")
        je_params["to_date"] = to_date
    if apply_cost_center_filter and kostenstellen:
        cc_je_sub, cc_je_params = _gl_distinct_vouchers_subquery(
            "je_cc",
            company=company,
            voucher_type="Journal Entry",
            from_date=from_date,
            to_date=to_date,
            cost_centers=kostenstellen,
        )
        je_joins.append(f"INNER JOIN {cc_je_sub} je_cc ON je_cc.voucher_no = gle.voucher_no")
        je_params.update(cc_je_params)

    journal_entries = frappe.db.sql(
        f"""
        SELECT
            gle.posting_date,
            gle.account,
            gle.debit,
            gle.credit,
            gle.voucher_no,
            gle.remarks,
            acc.root_type
        FROM `tabGL Entry` gle
        {" ".join(je_joins)}
        INNER JOIN `tabAccount` acc ON gle.account = acc.name
        WHERE {" AND ".join(je_conditions)}
        ORDER BY gle.posting_date ASC
        """,
        je_params,
        as_dict=True,
    )

    for je in journal_entries:
        root_type = je.get("root_type")
        if root_type == "Income":
            income_val = flt(je.credit) - flt(je.debit)
            expense_val = 0.0
        elif root_type == "Expense":
            income_val = 0.0
            expense_val = flt(je.debit) - flt(je.credit)
        else:
            if not include_non_euer_accounts:
                continue
            income_val, expense_val = _split_cash_in_out(flt(je.credit) - flt(je.debit))

        all_entries.append(
            {
                "posting_date": je.posting_date,
                "account": je.account,
                "voucher_type": "Journal Entry",
                "voucher_no": je.voucher_no,
                "remarks": je.remarks or "",
                "income": income_val,
                "expense": expense_val,
                "root_type": root_type,
                }
            )

    # ========== Teil 2b: Weitere Belege mit Bank/Kasse ==========
    # Einige Belege buchen direkt auf Bank/Kasse (z.B. POS Invoice / Expense Claim / etc.) ohne Payment Entry.
    # Für Cash-Basis-EÜR zählen diese wie Journal Entries: wir nehmen die Gegenkonten (nicht Bank/Kasse).
    other_conditions = [
        "gle.company = %(company)s",
        "gle.docstatus = 1",
        "gle.is_cancelled = 0",
        "gle.voucher_type NOT IN ('Payment Entry', 'Journal Entry')",
        "gle.account NOT IN %(bank_accounts)s",
    ]
    other_params = {"company": company, "bank_accounts": tuple(sorted(bank_accounts)) if bank_accounts else ("",)}
    other_joins: list[str] = []

    bank_other_sub, bank_other_params = _gl_distinct_vouchers_subquery(
        "other_bank",
        company=company,
        exclude_voucher_types=("Payment Entry", "Journal Entry"),
        from_date=from_date,
        to_date=to_date,
        bank_accounts=bank_accounts,
        include_voucher_type=True,
    )
    other_joins.append(
        "INNER JOIN "
        + bank_other_sub
        + " other_bank ON other_bank.voucher_type = gle.voucher_type AND other_bank.voucher_no = gle.voucher_no"
    )
    other_params.update(bank_other_params)

    if from_date:
        other_conditions.append("gle.posting_date >= %(from_date)s")
        other_params["from_date"] = from_date
    if to_date:
        other_conditions.append("gle.posting_date <= %(to_date)s")
        other_params["to_date"] = to_date
    if apply_cost_center_filter and kostenstellen:
        cc_other_sub, cc_other_params = _gl_distinct_vouchers_subquery(
            "other_cc",
            company=company,
            exclude_voucher_types=("Payment Entry", "Journal Entry"),
            from_date=from_date,
            to_date=to_date,
            cost_centers=kostenstellen,
            include_voucher_type=True,
        )
        other_joins.append(
            "INNER JOIN "
            + cc_other_sub
            + " other_cc ON other_cc.voucher_type = gle.voucher_type AND other_cc.voucher_no = gle.voucher_no"
        )
        other_params.update(cc_other_params)

    other_entries = frappe.db.sql(
        f"""
        SELECT
            gle.posting_date,
            gle.account,
            gle.debit,
            gle.credit,
            gle.voucher_type,
            gle.voucher_no,
            gle.remarks,
            acc.root_type
        FROM `tabGL Entry` gle
        {" ".join(other_joins)}
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE {" AND ".join(other_conditions)}
        ORDER BY gle.posting_date ASC
        """,
        other_params,
        as_dict=True,
    )

    for row in other_entries or []:
        root_type = row.get("root_type")
        if root_type == "Income":
            income_val = flt(row.get("credit")) - flt(row.get("debit"))
            expense_val = 0.0
        elif root_type == "Expense":
            income_val = 0.0
            expense_val = flt(row.get("debit")) - flt(row.get("credit"))
        else:
            if not include_non_euer_accounts:
                continue
            income_val, expense_val = _split_cash_in_out(flt(row.get("credit")) - flt(row.get("debit")))

        if income_val == 0 and expense_val == 0:
            continue

        all_entries.append(
            {
                "posting_date": row.get("posting_date"),
                "account": row.get("account"),
                "voucher_type": row.get("voucher_type"),
                "voucher_no": row.get("voucher_no"),
                "remarks": row.get("remarks") or "",
                "income": income_val,
                "expense": expense_val,
                "root_type": root_type,
            }
        )

    # ========== Teil 3: Payment Entries ohne Invoice-Referenz ==========
    # Diese Buchungen sind Cash-relevant, aber nicht über Invoice-Items abgebildet (z.B. Transfers, Privat, Darlehen).
    direct_pe_conditions = list(pe_conditions)
    direct_pe_params = dict(pe_params)
    direct_pe_joins = list(pe_joins)

    direct_payment_entries = frappe.db.sql(
        f"""
        SELECT pe.name
        FROM `tabPayment Entry` pe
        {" ".join(direct_pe_joins)}
        WHERE {" AND ".join(direct_pe_conditions)}
          AND NOT EXISTS (
              SELECT 1
              FROM `tabPayment Entry Reference` per
              WHERE per.parent = pe.name
                AND per.reference_doctype IN ('Sales Invoice', 'Purchase Invoice')
          )
        ORDER BY pe.posting_date ASC
        """,
        direct_pe_params,
        as_dict=True,
    )
    direct_payment_entry_names = [
        str(r.get("name")) for r in (direct_payment_entries or []) if r.get("name") and str(r.get("name")) not in mapped_payment_entries
    ]

    if direct_payment_entry_names:
        gle_conditions = [
            "gle.docstatus = 1",
            "gle.is_cancelled = 0",
            "gle.company = %(company)s",
            "gle.voucher_type = 'Payment Entry'",
            "gle.voucher_no IN %(voucher_nos)s",
        ]
        gle_params = {
            "company": company,
            "voucher_nos": tuple(direct_payment_entry_names),
        }
        if from_date:
            gle_conditions.append("gle.posting_date >= %(from_date)s")
            gle_params["from_date"] = from_date
        if to_date:
            gle_conditions.append("gle.posting_date <= %(to_date)s")
            gle_params["to_date"] = to_date
        if bank_accounts:
            gle_conditions.append("gle.account NOT IN %(bank_accounts)s")
            gle_params["bank_accounts"] = tuple(sorted(bank_accounts))

        pe_gl_entries = frappe.db.sql(
            f"""
            SELECT
                gle.posting_date,
                gle.account,
                gle.debit,
                gle.credit,
                gle.voucher_no,
                gle.remarks,
                acc.root_type
            FROM `tabGL Entry` gle
            INNER JOIN `tabAccount` acc ON acc.name = gle.account
            WHERE {" AND ".join(gle_conditions)}
            ORDER BY gle.posting_date ASC
            """,
            gle_params,
            as_dict=True,
        )

        # Direct-PEs auf Mieterforderungskonten (Debitor/Mieterkonto) sollen als "Guthaben Mieter"
        # EÜR-relevant erscheinen (z.B. Überzahlung + Refund), sonst landen sie als Asset/Receivable ohne EÜR-Haken.
        direct_pe_mieterkonten: set[str] = set()
        try:
            bounds = _get_mieterforderungen_bounds(company)
            if bounds:
                direct_accounts = {r.get("account") for r in (pe_gl_entries or []) if r.get("account")}
                direct_pe_mieterkonten = _accounts_in_bounds(company, direct_accounts, bounds)
        except Exception:
            direct_pe_mieterkonten = set()

        for row in pe_gl_entries or []:
            root_type = row.get("root_type")
            if root_type == "Income":
                income_val = flt(row.get("credit")) - flt(row.get("debit"))
                expense_val = 0.0
            elif root_type == "Expense":
                income_val = 0.0
                expense_val = flt(row.get("debit")) - flt(row.get("credit"))
            else:
                if not include_non_euer_accounts:
                    continue
                income_val, expense_val = _split_cash_in_out(flt(row.get("credit")) - flt(row.get("debit")))

            account = row.get("account")
            if include_non_euer_accounts and account in direct_pe_mieterkonten:
                mapped_root_type = "Income" if income_val else ("Expense" if expense_val else None)
                all_entries.append(
                    {
                        "posting_date": row.get("posting_date"),
                        "account": "Guthaben Mieter",
                        "voucher_type": "Payment Entry",
                        "voucher_no": row.get("voucher_no"),
                        "remarks": f"Guthaben/Nachzahlung Mieter (Direct-PE) [{account}]",
                        "income": income_val,
                        "expense": expense_val,
                        "root_type": mapped_root_type,
                        "euer_relevant_override": 1,
                    }
                )
            else:
                all_entries.append(
                    {
                        "posting_date": row.get("posting_date"),
                        "account": account,
                        "voucher_type": "Payment Entry",
                        "voucher_no": row.get("voucher_no"),
                        "remarks": row.get("remarks") or "",
                        "income": income_val,
                        "expense": expense_val,
                        "root_type": root_type,
                    }
                )

    # Sortiere alle Einträge nach Datum
    all_entries.sort(key=lambda x: (x["posting_date"], x["account"]))

    message = None
    if from_date and to_date and bank_accounts:
        cc_for_balance = kostenstellen if apply_cost_center_filter else None
        opening_balance = _get_bank_balance(company, bank_accounts, from_date, cc_for_balance, strict_before=True)
        closing_balance = _get_bank_balance(company, bank_accounts, to_date, cc_for_balance, strict_before=False)
        cashflow = 0.0
        for e in all_entries:
            cashflow += flt(e.get("income")) - flt(e.get("expense"))
        expected_closing = flt(opening_balance + cashflow)
        diff = flt(expected_closing - closing_balance)

        ok = abs(diff) <= 0.05
        hint = ""
        if not ok and not include_non_euer_accounts:
            hint = " (Tipp: 'Nicht‑EÜR Konten anzeigen' aktivieren)"

        message = (
            f"<b>Bank/Kasse Abgleich</b>: Anfang {opening_balance:.2f} + Bewegung {cashflow:.2f} = {expected_closing:.2f}; "
            f"Ende {closing_balance:.2f}; Differenz {diff:.2f}"
            f"{hint}"
        )

        # Debug-Hilfe: Zeige die größten Abweichungen pro Beleg (nur in Detail-Ansicht, um die UI nicht zu überladen).
        if not ok and show_details:
            bank_by_voucher = _get_bank_movement_by_voucher(
                company,
                bank_accounts,
                from_date,
                to_date,
                cc_for_balance,
            )
            calc_by_voucher: dict[tuple[str, str], float] = {}
            for e in all_entries:
                vt = (e.get("voucher_type") or "").strip()
                vn = (e.get("voucher_no") or "").strip()
                if not vt or not vn:
                    continue
                calc_by_voucher[(vt, vn)] = flt(calc_by_voucher.get((vt, vn), 0.0)) + (
                    flt(e.get("income")) - flt(e.get("expense"))
                )

            deltas = []
            for key, bank_net in bank_by_voucher.items():
                calc_net = flt(calc_by_voucher.get(key, 0.0))
                d = flt(calc_net - bank_net)
                if abs(d) > 0.05:
                    deltas.append((abs(d), key[0], key[1], d))
            deltas.sort(reverse=True)

            if deltas:
                top = deltas[:10]
                details = "; ".join([f"{vt} {vn}: {d:.2f}" for _, vt, vn, d in top])
                message += f"<br><small>Top Abweichungen (calc−bank): {details}</small>"

    # ========== Detail-Ansicht ==========
    if show_details:
        rows = []
        income_total = 0.0
        expense_total = 0.0

        for entry in all_entries:
            income_total += entry["income"]
            expense_total += entry["expense"]

            rows.append({
                "posting_date": entry["posting_date"],
                "account": entry["account"],
                "voucher_type": entry["voucher_type"],
                "voucher_no": entry["voucher_no"],
                "remarks": entry["remarks"],
                "income": entry["income"] if entry["income"] != 0 else None,
                "expense": entry["expense"] if entry["expense"] != 0 else None,
                "euer_relevant": entry.get("euer_relevant_override")
                if entry.get("euer_relevant_override") is not None
                else (1 if entry.get("root_type") in ("Income", "Expense") else 0),
            })

        # Summenzeile
        rows.append({
            "posting_date": None,
            "account": "Gesamt",
            "voucher_type": "",
            "voucher_no": "",
            "remarks": "",
            "income": income_total,
            "expense": expense_total,
            "euer_relevant": None,
            "bold": 1,
        })

        return rows, message

    # ========== Zusammenfassungs-Ansicht mit Gruppierung ==========
    # Gruppiere nach Konto und trenne umlagefähig/nicht umlagefähig (über Kontenstruktur oder Kostenarten).
    umlage_method = (f.get("umlage_method") or "Kontenstruktur").strip()

    candidate_accounts = {
        e.get("account")
        for e in all_entries
        if e.get("account")
        and e.get("root_type") in ("Income", "Expense")
        and e.get("account") != "Guthaben Mieter"
    }

    konto_umlage_set: set[str] = set()
    konto_nicht_umlage_set: set[str] = set()
    account_tree: dict[str, tuple[int, int]] = {}

    try:
        if candidate_accounts:
            if umlage_method == "Kostenarten":
                rows = frappe.db.sql(
                    """
                    SELECT DISTINCT konto
                    FROM `tabBetriebskostenart`
                    WHERE konto IN %(names)s
                    """,
                    {"names": tuple(sorted(candidate_accounts))},
                    as_dict=True,
                )
                konto_umlage_set = {r.get("konto") for r in rows or [] if r.get("konto")}

                rows = frappe.db.sql(
                    """
                    SELECT DISTINCT konto
                    FROM `tabKostenart nicht umlagefaehig`
                    WHERE konto IN %(names)s
                    """,
                    {"names": tuple(sorted(candidate_accounts))},
                    as_dict=True,
                )
                konto_nicht_umlage_set = {r.get("konto") for r in rows or [] if r.get("konto")}
            else:
                rows = frappe.db.sql(
                    """
                    SELECT name, lft, rgt
                    FROM `tabAccount`
                    WHERE company = %(company)s
                      AND name IN %(names)s
                    """,
                    {"company": company, "names": tuple(sorted(candidate_accounts))},
                    as_dict=True,
                )
                for r in rows or []:
                    if r.get("name") and r.get("lft") is not None and r.get("rgt") is not None:
                        account_tree[r["name"]] = (int(r["lft"]), int(r["rgt"]))
    except Exception:
        konto_umlage_set = set()
        konto_nicht_umlage_set = set()
        account_tree = {}

    umlage_bounds = None
    nicht_umlage_bounds = None
    if umlage_method != "Kostenarten":
        try:
            umlage_bounds = _find_account_group_bounds(company, "%Umlagefähig%")
            nicht_umlage_bounds = _find_account_group_bounds(company, "%Nicht Umlagefähig%")
        except Exception:
            umlage_bounds = None
            nicht_umlage_bounds = None

    def _konto_umlage_flag(account: str, root_type: str | None) -> bool | None:
        if root_type not in ("Income", "Expense"):
            return None
        if not account or account == "Guthaben Mieter":
            return None

        if umlage_method == "Kostenarten":
            if account in konto_nicht_umlage_set:
                return False
            if account in konto_umlage_set:
                return True
            return None

        lft_rgt = account_tree.get(account)
        if not lft_rgt:
            return None
        lft, rgt = lft_rgt
        if nicht_umlage_bounds:
            nlft, nrgt = nicht_umlage_bounds
            if lft >= nlft and rgt <= nrgt:
                return False
        if umlage_bounds:
            ulft, urgt = umlage_bounds
            if lft >= ulft and rgt <= urgt:
                return True
        return None

    def _income_group_key(account: str) -> str:
        account_l = (account or "").lower()
        if account == "Guthaben Mieter":
            return "sonstige"
        if any(token in account_l for token in ("miete", "untermiet")):
            return "miete"
        if any(token in account_l for token in ("heizkostenvoraus", "betriebskosten")):
            return "nebenkosten"
        if "guthaben" in account_l or "nachzahlung" in account_l:
            return "sonstige"
        return "sonstige"

    income_accounts = defaultdict(lambda: {"income": 0.0, "umlagefaehig": None})
    expense_accounts = defaultdict(lambda: {"expense": 0.0, "umlagefaehig": None})
    other_accounts = defaultdict(lambda: {"income": 0.0, "expense": 0.0})

    for entry in all_entries:
        account = entry["account"]
        root_type = entry.get("root_type")
        is_umlagefaehig = _konto_umlage_flag(account, root_type)

        if root_type == "Income":
            income_accounts[account]["income"] += entry["income"]
            income_accounts[account]["umlagefaehig"] = is_umlagefaehig
        elif root_type == "Expense":
            expense_accounts[account]["expense"] += entry["expense"]
            expense_accounts[account]["umlagefaehig"] = is_umlagefaehig
        else:
            if not include_non_euer_accounts:
                continue
            other_accounts[account]["income"] += flt(entry.get("income"))
            other_accounts[account]["expense"] += flt(entry.get("expense"))

    # "Guthaben Mieter" kann in einem Zeitraum sowohl Ein- als auch Auszahlungen enthalten
    # (z.B. Überzahlung + Refund). In der Zusammenfassung soll es als Netto-Wert unter
    # Einnahmen erscheinen (statt doppelt: einmal Einnahmen, einmal Ausgaben).
    guthaben_key = "Guthaben Mieter"
    gm_income = flt((income_accounts.get(guthaben_key) or {}).get("income"))
    gm_expense = flt((expense_accounts.get(guthaben_key) or {}).get("expense"))
    if gm_income or gm_expense:
        if guthaben_key in income_accounts:
            del income_accounts[guthaben_key]
        if guthaben_key in expense_accounts:
            del expense_accounts[guthaben_key]
        gm_net = flt(gm_income - gm_expense)
        if gm_net != 0:
            income_accounts[guthaben_key] = {"income": gm_net, "umlagefaehig": None}

    rows = []

    # ========== EINNAHMEN ==========
    income_total = 0.0
    if income_accounts:
        income_miete = {}
        income_nebenkosten = {}
        income_sonstige = {}
        for konto, totals in income_accounts.items():
            group_key = _income_group_key(konto)
            if group_key == "miete":
                income_miete[konto] = totals
            elif group_key == "nebenkosten":
                income_nebenkosten[konto] = totals
            else:
                income_sonstige[konto] = totals

        rows.append({"account": "Einnahmen", "income": None, "expense": None, "balance": None, "bold": 1})

        def _append_income_group(title: str, group: dict) -> float:
            if not group:
                return 0.0
            group_total = 0.0
            rows.append({"account": title, "income": None, "expense": None, "balance": None, "bold": 1})
            for konto in sorted(group.keys()):
                income_val = flt(group[konto]["income"])
                group_total += income_val
                rows.append(
                    {
                        "account": konto,
                        "income": income_val if income_val != 0 else None,
                        "expense": None,
                        "balance": income_val,
                        "indent": 0,
                    }
                )
            rows.append(
                {
                    "account": f"Summe {title}",
                    "income": group_total if group_total != 0 else None,
                    "expense": None,
                    "balance": group_total,
                    "indent": 0,
                    "bold": 1,
                }
            )
            return group_total

        income_total += _append_income_group("Mieteinnahmen", income_miete)
        income_total += _append_income_group("Nebenkostenvorauszahlungen", income_nebenkosten)
        income_total += _append_income_group("Sonstige Einnahmen", income_sonstige)

        rows.append(
            {
                "account": "Summe Einnahmen",
                "income": income_total if income_total != 0 else None,
                "expense": None,
                "balance": income_total,
                "indent": 0,
                "bold": 1,
            }
        )

    # ========== AUSGABEN ==========
    expense_total = 0.0
    if expense_accounts:
        # Gruppiere Ausgaben nach umlagefähig/nicht umlagefähig
        umlagefaehig = {}
        nicht_umlagefaehig = {}
        sonstige = {}

        for konto, data in expense_accounts.items():
            if data["umlagefaehig"] is True:
                umlagefaehig[konto] = data
            elif data["umlagefaehig"] is False:
                nicht_umlagefaehig[konto] = data
            else:
                sonstige[konto] = data

        # Umlagefähige Ausgaben
        if umlagefaehig:
            umlagefaehig_total = 0.0
            rows.append({"account": "Umlagefähige Ausgaben", "income": None, "expense": None, "balance": None, "bold": 1})
            for konto in sorted(umlagefaehig.keys()):
                expense_val = umlagefaehig[konto]["expense"]
                umlagefaehig_total += expense_val
                rows.append({
                    "account": konto,
                    "income": None,
                    "expense": expense_val if expense_val != 0 else None,
                    "balance": -expense_val,
                    "indent": 0,
                })

            rows.append({
                "account": "Summe Umlagefähige Ausgaben",
                "income": None,
                "expense": umlagefaehig_total,
                "balance": -umlagefaehig_total,
                "indent": 0,
                "bold": 1,
            })
            expense_total += umlagefaehig_total

        # Nicht umlagefähige Ausgaben
        if nicht_umlagefaehig:
            nicht_umlagefaehig_total = 0.0
            rows.append({"account": "Nicht umlagefähige Ausgaben", "income": None, "expense": None, "balance": None, "bold": 1})
            for konto in sorted(nicht_umlagefaehig.keys()):
                expense_val = nicht_umlagefaehig[konto]["expense"]
                nicht_umlagefaehig_total += expense_val
                rows.append({
                    "account": konto,
                    "income": None,
                    "expense": expense_val if expense_val != 0 else None,
                    "balance": -expense_val,
                    "indent": 0,
                })

            rows.append({
                "account": "Summe Nicht umlagefähige Ausgaben",
                "income": None,
                "expense": nicht_umlagefaehig_total,
                "balance": -nicht_umlagefaehig_total,
                "indent": 0,
                "bold": 1,
            })
            expense_total += nicht_umlagefaehig_total

        # Sonstige Ausgaben
        if sonstige:
            sonstige_total = 0.0
            rows.append({"account": "Sonstige Ausgaben", "income": None, "expense": None, "balance": None, "bold": 1})
            for konto in sorted(sonstige.keys()):
                expense_val = sonstige[konto]["expense"]
                sonstige_total += expense_val
                rows.append({
                    "account": konto,
                    "income": None,
                    "expense": expense_val if expense_val != 0 else None,
                    "balance": -expense_val,
                    "indent": 0,
                })

            rows.append({
                "account": "Summe Sonstige Ausgaben",
                "income": None,
                "expense": sonstige_total,
                "balance": -sonstige_total,
                "indent": 0,
                "bold": 1,
            })
            expense_total += sonstige_total

        # Summe aller Ausgaben
        rows.append({
            "account": "Summe Ausgaben",
            "income": None,
            "expense": expense_total,
            "balance": -expense_total,
            "indent": 0,
            "bold": 1,
        })

    # ========== GESAMTSALDO ==========
    rows.append({
        "account": "Überschuss/Verlust",
        "income": income_total if income_total != 0 else None,
        "expense": expense_total if expense_total != 0 else None,
        "balance": income_total - expense_total,
        "indent": 0,
        "bold": 1,
    })

    # ========== NICHT-EÜR KONTEN (separat) ==========
    if include_non_euer_accounts and other_accounts:
        rows.append({"account": "Nicht‑EÜR Konten", "income": None, "expense": None, "balance": None, "bold": 1})

        other_income_total = 0.0
        other_expense_total = 0.0
        for konto in sorted(other_accounts.keys()):
            vals = other_accounts[konto]
            in_val = flt(vals.get("income"))
            out_val = flt(vals.get("expense"))
            other_income_total += in_val
            other_expense_total += out_val
            rows.append(
                {
                    "account": konto,
                    "income": in_val if in_val != 0 else None,
                    "expense": out_val if out_val != 0 else None,
                    "balance": in_val - out_val,
                    "indent": 0,
                }
            )

        rows.append(
            {
                "account": "Summe Nicht‑EÜR",
                "income": other_income_total if other_income_total != 0 else None,
                "expense": other_expense_total if other_expense_total != 0 else None,
                "balance": other_income_total - other_expense_total,
                "indent": 0,
                "bold": 1,
            }
        )

    # ========== BANK/KASSE CHECK (Anfang + Summe = Ende) ==========
    if from_date and to_date and bank_accounts and show_bank_check:
        cc_for_balance = kostenstellen if apply_cost_center_filter else None
        opening_balance = _get_bank_balance(company, bank_accounts, from_date, cc_for_balance, strict_before=True)
        closing_balance = _get_bank_balance(company, bank_accounts, to_date, cc_for_balance, strict_before=False)
        cashflow = 0.0
        for e in all_entries:
            cashflow += flt(e.get("income")) - flt(e.get("expense"))
        expected_closing = flt(opening_balance + cashflow)
        diff = flt(expected_closing - closing_balance)

        rows.append({"account": "Bank/Kasse Abgleich", "income": None, "expense": None, "balance": None, "bold": 1})
        rows.append({"account": "Anfangsbestand", "income": None, "expense": None, "balance": opening_balance})
        rows.append({"account": "Bewegung (Summe)", "income": None, "expense": None, "balance": cashflow})
        rows.append({"account": "Endbestand", "income": None, "expense": None, "balance": closing_balance})
        rows.append({"account": "Differenz", "income": None, "expense": None, "balance": diff, "bold": 1})

    return rows, message


def _coerce_multi_filter(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        try:
            parsed = frappe.parse_json(value)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


@frappe.whitelist()
def get_account_filter_options(txt: str = "", company: str | None = None, immobilie: str | None = None) -> list[dict]:
    txt = (txt or "").strip().lower()
    if immobilie:
        accounts = sorted(_get_immobilie_scope(immobilie).get("bank_accounts") or set())
    else:
        accounts = sorted(_get_bank_cash_accounts(company)) if company else []

    out: list[dict] = []
    for account in accounts:
        if txt and txt not in account.lower():
            continue
        out.append({"value": account, "description": ""})
    return out
