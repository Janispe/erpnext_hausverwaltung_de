"""
Validierung für Mieterforderungskonten (Receivable Accounts).

Prüft, dass alle Buchungen auf Mieterforderungskonten ausschließlich durch
Sales Invoices, Payment Entries oder gezielte Abschreibungs-Journal-Entries erfolgen.
"""
from typing import List, Dict, Any

import frappe

from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
    is_receivable_writeoff_journal_entry,
)


def _company_abbr(company: str) -> str:
    """Ermittelt die Abkürzung einer Company."""
    try:
        return (frappe.db.get_value("Company", company, "abbr") or "").strip() or "HP"
    except Exception:
        return "HP"


def _with_abbr(account_name: str, abbr: str) -> str:
    """Fügt Company-Abkürzung zum Kontonamen hinzu, falls nicht vorhanden."""
    suffix = f" - {abbr}"
    if account_name.endswith(suffix):
        return account_name
    return f"{account_name}{suffix}"


def get_receivable_accounts(company: str) -> List[str]:
    """
    Ermittelt alle Receivable-Konten für eine Company.

    Im Sammelkonto-Modell ist das in der Regel ein einziges Konto
    (Company.default_receivable_account, typischerweise '1300 - Mieterforderungen' Leaf).
    Falls Legacy-Per-Mieter-Konten noch existieren, werden sie ebenfalls erfasst.

    Args:
        company: Name der Company

    Returns:
        Liste der Account-Namen (mit Abkürzung)
    """
    accounts: list[str] = []
    sammelkonto = (
        frappe.db.get_value("Company", company, "default_receivable_account") or ""
    ).strip()
    if sammelkonto and frappe.db.exists("Account", sammelkonto):
        accounts.append(sammelkonto)

    legacy = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "account_type": "Receivable",
            "is_group": 0,
        },
        pluck="name",
    )
    for name in legacy:
        if name not in accounts:
            accounts.append(name)
    return accounts


def validate_receivable_account_entries(
    company: str,
    from_date: str | None = None,
    to_date: str | None = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Validiert, dass alle Buchungen auf Mieterforderungskonten
    nur durch Sales Invoice, Payment Entry oder gezielte Abschreibungs-Journal-Entries erfolgt sind.

    Args:
        company: Name der Company
        from_date: Optionales Start-Datum für Filterung (Format: YYYY-MM-DD)
        to_date: Optionales End-Datum für Filterung (Format: YYYY-MM-DD)
        verbose: Bei True werden Warnungen direkt ausgegeben

    Returns:
        Dictionary mit Validierungsergebnissen:
        {
            "valid": bool,
            "warnings": List[str],
            "receivable_accounts": List[str],
            "invalid_entries": List[Dict],
        }
    """
    receivable_accounts = get_receivable_accounts(company)

    if not receivable_accounts:
        result = {
            "valid": True,
            "warnings": [f"⚠️ Keine Mieterforderungskonten für Company '{company}' gefunden."],
            "receivable_accounts": [],
            "invalid_entries": [],
        }
        if verbose:
            print(result["warnings"][0])
        return result

    warnings = []
    invalid_entries = []

    # Prüfe Journal Entries auf diesen Konten
    filters = {
        "account": ["in", receivable_accounts],
        "docstatus": 1,  # nur submitted
    }

    if from_date:
        filters["posting_date"] = [">=", from_date]
    if to_date:
        if "posting_date" in filters:
            filters["posting_date"] = ["between", [from_date, to_date]]
        else:
            filters["posting_date"] = ["<=", to_date]

    # Hole alle GL Entries für diese Konten
    gl_entries = frappe.get_all(
        "GL Entry",
        filters=filters,
        fields=["name", "account", "posting_date", "voucher_type", "voucher_no", "debit", "credit", "against"],
        order_by="posting_date desc, creation desc"
    )

    # Filtere ungültige Einträge. Journal Entries sind nur erlaubt, wenn sie eine
    # konkrete Sales Invoice auf ein Aufwandskonto abschreiben.
    allowed_voucher_types = {"Sales Invoice", "Payment Entry"}

    for entry in gl_entries:
        is_allowed_writeoff = (
            entry.voucher_type == "Journal Entry"
            and is_receivable_writeoff_journal_entry(
                entry.voucher_no,
                receivable_account=entry.account,
            )
        )

        if entry.voucher_type not in allowed_voucher_types and not is_allowed_writeoff:
            invalid_entries.append(entry)
            warning_msg = (
                f"⚠️ Ungültige Buchung auf Mieterforderungskonto '{entry.account}':\n"
                f"   Datum: {entry.posting_date}, Typ: {entry.voucher_type}, "
                f"Beleg: {entry.voucher_no}, "
                f"Soll: {entry.debit:.2f}, Haben: {entry.credit:.2f}"
            )
            warnings.append(warning_msg)

    result = {
        "valid": len(invalid_entries) == 0,
        "warnings": warnings,
        "receivable_accounts": receivable_accounts,
        "invalid_entries": invalid_entries,
    }

    if verbose:
        if result["valid"]:
            print(f"✅ Alle Buchungen auf Mieterforderungskonten sind gültig ({len(gl_entries)} Einträge geprüft).")
        else:
            print(f"\n⚠️ WARNUNG: {len(invalid_entries)} ungültige Buchung(en) gefunden:")
            for warning in warnings:
                print(warning)

    return result


def validate_receivable_entries_for_all_companies(
    from_date: str | None = None,
    to_date: str | None = None,
    verbose: bool = True
) -> Dict[str, Dict[str, Any]]:
    """
    Führt die Validierung für alle Companies durch.

    Args:
        from_date: Optionales Start-Datum für Filterung (Format: YYYY-MM-DD)
        to_date: Optionales End-Datum für Filterung (Format: YYYY-MM-DD)
        verbose: Bei True werden Warnungen direkt ausgegeben

    Returns:
        Dictionary mit Ergebnissen pro Company
    """
    companies = frappe.get_all("Company", pluck="name")
    results = {}

    for company in companies:
        if verbose:
            print(f"\n{'='*60}")
            print(f"Prüfe Company: {company}")
            print(f"{'='*60}")

        results[company] = validate_receivable_account_entries(
            company=company,
            from_date=from_date,
            to_date=to_date,
            verbose=verbose
        )

    return results
