from __future__ import annotations

from typing import Optional

import frappe


def _get_account_details(account_name: str) -> dict:
    try:
        row = frappe.db.get_value(
            "Account",
            account_name,
            ["name", "company", "account_number", "account_name", "is_group"],
            as_dict=True,
        )
        return row or {}
    except Exception:
        return {}


def _find_account_in_company(*, target_company: str, source_account: str) -> Optional[str]:
    """Find a best-effort equivalent Account in target_company.

    Strategy:
      1) Match by account_number within target_company
      2) Match by account_name within target_company
      3) Parse number/name from the display name ("<no> - <name> - <abbr>")
    """

    details = _get_account_details(source_account)
    acc_no = (details.get("account_number") or "").strip()
    acc_name = (details.get("account_name") or "").strip()

    if acc_no:
        cand = frappe.db.get_value(
            "Account",
            {"company": target_company, "account_number": acc_no},
            "name",
        )
        if cand:
            return str(cand)

    if acc_name:
        cand = frappe.db.get_value(
            "Account",
            {"company": target_company, "account_name": acc_name, "is_group": 0},
            "name",
        )
        if cand:
            return str(cand)

    # Fallback parsing from name
    try:
        parts = [p.strip() for p in str(source_account).split(" - ") if p.strip()]
        parsed_no = parts[0] if parts and parts[0].isdigit() else ""
        parsed_name = parts[1] if len(parts) >= 2 else ""
    except Exception:
        parsed_no = ""
        parsed_name = ""

    if parsed_no:
        cand = frappe.db.get_value(
            "Account",
            {"company": target_company, "account_number": parsed_no},
            "name",
        )
        if cand:
            return str(cand)

    if parsed_name:
        cand = frappe.db.get_value(
            "Account",
            {"company": target_company, "account_name": parsed_name, "is_group": 0},
            "name",
        )
        if cand:
            return str(cand)

    return None


def _repair_child_account_link(
    *,
    row_obj,
    fieldname: str,
    target_company: str,
) -> bool:
    current = (row_obj.get(fieldname) or "").strip()
    if not current:
        return False

    details = _get_account_details(current)
    if not details:
        # Account missing: try to resolve to a replacement in target company
        repl = _find_account_in_company(target_company=target_company, source_account=current)
        if repl and repl != current:
            row_obj.set(fieldname, repl)
            return True
        return False

    if details.get("company") == target_company:
        return False

    repl = _find_account_in_company(target_company=target_company, source_account=current)
    if repl and repl != current:
        row_obj.set(fieldname, repl)
        return True

    return False


def repair_tax_template_accounts(*, company: Optional[str] = None, dry_run: bool = False) -> dict:
    """Fix template/account links that point to Accounts of a different Company.

    Repairs:
      - Sales Taxes and Charges Template.taxes[].account_head
      - Purchase Taxes and Charges Template.taxes[].account_head
      - Item Tax Template.taxes[].tax_type

    Returns a summary dict.
    """

    doctypes = [
        ("Sales Taxes and Charges Template", "taxes", "account_head"),
        ("Purchase Taxes and Charges Template", "taxes", "account_head"),
        ("Item Tax Template", "taxes", "tax_type"),
    ]

    companies = [company] if company else (frappe.get_all("Company", pluck="name") or [])

    summary = {
        "companies": companies,
        "changed": [],
        "skipped": [],
        "errors": [],
    }

    for target_company in companies:
        for dt, child_table_field, account_field in doctypes:
            try:
                if not frappe.db.table_exists(dt):
                    continue
            except Exception:
                # table_exists not always available; just try querying
                pass

            try:
                names = frappe.get_all(dt, filters={"company": target_company}, pluck="name")
            except Exception as exc:
                summary["errors"].append({"doctype": dt, "company": target_company, "error": str(exc)})
                continue

            for name in names:
                try:
                    doc = frappe.get_doc(dt, name)
                except Exception as exc:
                    summary["errors"].append({"doctype": dt, "name": name, "error": str(exc)})
                    continue

                changed = False
                rows = list(getattr(doc, child_table_field, []) or [])
                for row in rows:
                    try:
                        if _repair_child_account_link(
                            row_obj=row,
                            fieldname=account_field,
                            target_company=target_company,
                        ):
                            changed = True
                    except Exception as exc:
                        summary["errors"].append(
                            {
                                "doctype": dt,
                                "name": name,
                                "row": getattr(row, "idx", None),
                                "error": str(exc),
                            }
                        )

                if changed:
                    summary["changed"].append({"doctype": dt, "name": name, "company": target_company})
                    if not dry_run:
                        try:
                            doc.save(ignore_permissions=True)
                        except Exception as exc:
                            summary["errors"].append({"doctype": dt, "name": name, "error": str(exc)})
                else:
                    summary["skipped"].append({"doctype": dt, "name": name, "company": target_company})

    if not dry_run:
        try:
            frappe.db.commit()
        except Exception:
            pass

    return summary
