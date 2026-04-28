import frappe
from frappe.utils import flt, today


def execute(filters=None):
    filters = frappe._dict(filters or {})

    company = filters.get("company")
    if not company:
        frappe.throw("Bitte eine Firma waehlen.")

    to_date = filters.get("to_date") or today()
    include_groups = bool(filters.get("include_groups"))
    show_zero = bool(filters.get("show_zero"))
    include_disabled = bool(filters.get("include_disabled"))

    account_filters = {"company": company}
    if not include_disabled:
        account_filters["disabled"] = 0

    accounts = frappe.get_all(
        "Account",
        filters=account_filters,
        fields=[
            "name",
            "account_name",
            "account_number",
            "parent_account",
            "is_group",
            "root_type",
            "account_type",
            "lft",
            "rgt",
        ],
        order_by="lft asc",
    )

    if not accounts:
        return get_columns(), []

    account_map = {a.name: a for a in accounts}
    for a in accounts:
        a.balance = 0.0

    gl_rows = frappe.db.sql(
        """
        select account, sum(debit) as debit, sum(credit) as credit
        from `tabGL Entry`
        where company = %(company)s
          and posting_date <= %(to_date)s
          and is_cancelled = 0
        group by account
        """,
        {"company": company, "to_date": to_date},
        as_dict=True,
    )

    for row in gl_rows:
        acc = account_map.get(row.account)
        if not acc:
            continue
        acc.balance = flt(row.debit) - flt(row.credit)

    if include_groups:
        # Roll up balances from leaves to parents using reverse lft order
        for acc in sorted(accounts, key=lambda a: a.lft or 0, reverse=True):
            parent = account_map.get(acc.parent_account)
            if parent:
                parent.balance = flt(parent.balance) + flt(acc.balance)

    currency = frappe.get_cached_value("Company", company, "default_currency")

    data = []
    for acc in accounts:
        if not include_groups and acc.is_group:
            continue

        balance = flt(acc.balance)
        if not show_zero and abs(balance) < 0.000001:
            continue

        indent = get_indent(acc, account_map) if include_groups else 0

        row = {
            "account": acc.name,
            "account_name": acc.account_name,
            "account_number": acc.account_number,
            "root_type": acc.root_type,
            "account_type": acc.account_type,
            "balance": balance,
            "balance_dr": balance if balance > 0 else 0,
            "balance_cr": -balance if balance < 0 else 0,
            "indent": indent,
            "currency": currency,
        }
        data.append(row)

    return get_columns(), data


def get_columns():
    return [
        {
            "label": "Konto",
            "fieldname": "account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 260,
        },
        {
            "label": "Name",
            "fieldname": "account_name",
            "fieldtype": "Data",
            "width": 240,
        },
        {
            "label": "Konto-Nr",
            "fieldname": "account_number",
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "label": "Root Type",
            "fieldname": "root_type",
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "label": "Account Type",
            "fieldname": "account_type",
            "fieldtype": "Data",
            "width": 140,
        },
        {
            "label": "Saldo",
            "fieldname": "balance",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Saldo (Dr)",
            "fieldname": "balance_dr",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 120,
        },
        {
            "label": "Saldo (Cr)",
            "fieldname": "balance_cr",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 120,
        },
    ]


def get_indent(acc, account_map):
    depth = 0
    parent = acc.parent_account
    while parent:
        parent_acc = account_map.get(parent)
        if not parent_acc:
            break
        depth += 1
        parent = parent_acc.parent_account
    return depth

