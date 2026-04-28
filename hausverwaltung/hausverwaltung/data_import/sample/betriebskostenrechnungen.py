"""Sample: Eingangsrechnungen für Betriebskosten erzeugen.

Erzeugt über die Buchungs-Cockpit-API einige typische Betriebskostenrechnungen und
reicht die erzeugten Eingangsrechnungen automatisch ein.

Usage (bench console):
    from hausverwaltung.hausverwaltung.data_import.sample.betriebskostenrechnungen import (
        create_sample_betriebskosten_invoices,
    )
    create_sample_betriebskosten_invoices(company="Demo Hausverwaltung")
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import getdate
from .sample_data import (
    _ensure_company_account_defaults,  # reuse defaults initializer
    _find_bank_or_cash_account,        # for payment creation
    _ensure_default_bank,              # for company Bank Account creation
    _ensure_supplier_group_all,        # ensure Supplier Group exists
)


def _ensure_betriebskostenarten(company: Optional[str]) -> List[str]:
    """Ensure the example Betriebskostenarten exist and return their names."""
    try:
        # Prefer our local sample helper (idempotent)
        from .betriebskostenarten import create_sample_betriebskostenarten

        return create_sample_betriebskostenarten(company=company)
    except Exception:
        # As a fallback, just return whatever exists
        return frappe.get_all("Betriebskostenart", pluck="name")


def _get_company_abbr(company: str) -> str:
    try:
        comp = frappe.get_doc("Company", company)
        return comp.abbr
    except Exception:
        return ""


def _get_or_create_cost_center(name: str, company: Optional[str]) -> Optional[str]:
    """Return a Cost Center by name for company, creating a leaf if missing."""
    if not company:
        # best-effort: any leaf CC
        rows = frappe.get_all("Cost Center", filters={"is_group": 0}, pluck="name", limit=1)
        return rows[0] if rows else None

    rows = frappe.get_all(
        "Cost Center",
        filters={"cost_center_name": name, "company": company},
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]

    parent = f"{company} - {_get_company_abbr(company)}"
    try:
        doc = frappe.get_doc(
            {
                "doctype": "Cost Center",
                "cost_center_name": name,
                "is_group": 0,
                "parent_cost_center": parent,
                "company": company,
            }
        ).insert(ignore_permissions=True)
        return doc.name
    except Exception:
        return None


def _get_or_create_supplier(name: str, company: Optional[str]) -> str:
    """Buchung läuft über Sammelkonto Kreditoren — pro Supplier kein eigenes Konto pinnen."""
    _ = company  # parameter retained for caller compatibility; payable kommt vom Company-Default
    if frappe.db.exists("Supplier", name):
        return name
    supplier_group = _ensure_supplier_group_all()
    payload = {
        "doctype": "Supplier",
        "supplier_name": name,
        "supplier_type": "Company",
        "supplier_group": supplier_group,
    }
    return frappe.get_doc(payload).insert(ignore_permissions=True).name


def _bk_by_name(name1: str) -> Optional[str]:
    """Return the Betriebskostenart docname by its field name1."""
    rows = frappe.get_all(
        "Betriebskostenart",
        filters={"name1": name1},
        pluck="name",
        limit=1,
    )
    return rows[0] if rows else None


def _ensure_pi_via_cockpit_and_submit(
    *,
    supplier: str,
    bill_no: str,
    bill_date: str,
    row_specs: List[Tuple[str, float, str]],  # (bk_name1, amount, cost_center)
    bankkonto: Optional[str] = None,
) -> Optional[str]:
    """Create and submit a Purchase Invoice via the Buchungs-Cockpit API.

    Skips creation if a Purchase Invoice with matching bill_no+supplier already exists.
    """
    try:
        existing_pi = frappe.get_all(
            "Purchase Invoice",
            filters={"supplier": supplier, "bill_no": bill_no},
            pluck="name",
            limit=1,
        )
        if existing_pi:
            return existing_pi[0]

        positionen = []
        for bk_name1, amount, cc in row_specs:
            bk = _bk_by_name(bk_name1)
            if not bk:
                continue
            positionen.append(
                {
                    "betrag": float(amount),
                    "umlagefaehig": "Betriebskostenart",
                    "kostenart": bk,
                    "kostenstelle": cc,
                    "zahldatum": str(getdate(bill_date)),
                    "wertstellungsdatum": str(getdate(bill_date)),
                }
            )

        if not positionen:
            return None

        from hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit import (
            create_purchase_invoice,
        )

        result = create_purchase_invoice(
            lieferant=supplier,
            rechnungsdatum=str(getdate(bill_date)),
            rechnungsname=bill_no,
            positionen=positionen,
        )
        return (result or {}).get("name")
    except Exception as exc:
        try:
            print(f"⚠️  Betriebskosten invoice seed failed for {supplier} / {bill_no}: {exc}")
        except Exception:
            pass
        try:
            frappe.log_error(
                title=f"Sample Betriebskosten-Rechnung fehlgeschlagen: {supplier} / {bill_no}",
                message=frappe.get_traceback(),
            )
        except Exception:
            pass
        return None


def _get_or_create_company_bank_account(company: str) -> Optional[str]:
    """Return a Bank Account (doctype) that is linked to the given Company."""
    try:
        rows = frappe.get_all(
            "Bank Account",
            filters={"company": company, "is_company_account": 1},
            pluck="name",
            limit=1,
        )
        if rows:
            return rows[0]

        bank = _ensure_default_bank()
        gl_acc = frappe.db.get_value("Company", company, "default_bank_account") or _find_bank_or_cash_account(company)
        payload = {
            "doctype": "Bank Account",
            "account_name": f"Firmenkonto {company}",
            "bank": bank,
            "is_company_account": 1,
            "company": company,
        }
        if gl_acc:
            payload["account"] = gl_acc

        doc = frappe.get_doc(payload).insert(ignore_permissions=True)
        return doc.name
    except Exception:
        return None


def _create_payment_for_purchase_invoice(pi_name: str, *, submit: bool = True) -> Optional[str]:
    """Create a Payment Entry for a given Purchase Invoice (Supplier payment).

    Tries ERPNext's get_payment_entry first (allocates against the PI). If that
    fails, creates a simple unallocated 'Pay' entry with Supplier/Company bank.
    """
    try:
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    except Exception:
        get_payment_entry = None  # type: ignore

    try:
        pi = frappe.get_doc("Purchase Invoice", pi_name)
    except Exception:
        return None

    # 1) Try auto-mapping helper
    if get_payment_entry is not None:
        try:
            pe = get_payment_entry("Purchase Invoice", pi_name)
            pe.posting_date = pi.posting_date
            try:
                pe.reference_date = pi.posting_date
            except Exception:
                pass
            if not getattr(pe, "reference_no", None):
                pe.reference_no = f"PAY-{pi.supplier}-{pi.posting_date}"
            pe.set_missing_values()
            pe.set_amounts()
            if not getattr(pe, "paid_from", None):
                bank = _find_bank_or_cash_account(pi.company)
                if bank:
                    pe.paid_from = bank
            pe.insert(ignore_permissions=True)
            if submit:
                pe.submit()
            return pe.name
        except Exception:
            pass

    # 2) Fallback: unallocated payment
    try:
        bank = _find_bank_or_cash_account(pi.company)
        if not bank:
            return None
        # Try party account from Company default
        party_acc = frappe.db.get_value("Company", pi.company, "default_payable_account")
        if not party_acc:
            # Best-effort: any payable leaf
            rows = frappe.get_all(
                "Account",
                filters={"company": pi.company, "is_group": 0, "account_type": "Payable"},
                pluck="name",
                limit=1,
            )
            party_acc = rows[0] if rows else None
        if not party_acc:
            return None

        amt = float(getattr(pi, "outstanding_amount", None) or getattr(pi, "grand_total", 0) or 0)
        if amt <= 0:
            return None

        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "company": pi.company,
                "payment_type": "Pay",
                "party_type": "Supplier",
                "party": pi.supplier,
                "posting_date": pi.posting_date,
                "reference_no": f"PAY-{pi.supplier}-{pi.posting_date}",
                "reference_date": pi.posting_date,
                "paid_from": bank,
                "paid_to": party_acc,
                "paid_amount": amt,
                "received_amount": amt,
                # No references -> unallocated payment
            }
        )
        pe.set_missing_values()
        pe.insert(ignore_permissions=True)
        if submit:
            pe.submit()
        return pe.name
    except Exception:
        return None


def create_sample_betriebskosten_invoices(company: Optional[str] = None, *, with_payments: bool = False) -> Dict[str, List[str]]:
    """Erzeugt Beispiel-Eingangsrechnungen für mehrere Betriebskostenarten.

    - Stellt Beispiel-Betriebskostenarten sicher (idempotent)
    - Erzeugt 3 Monatsrechnungen (Jan–Mär 2025) mit typischen Kostenarten
    - Nutzt Kostenstelle "Musterhaus Berlin" (wird angelegt, falls fehlend)

    Returns dict with created names per DocType.
    """
    created: Dict[str, List[str]] = {"Purchase Invoice": [], "Payment Entry": []}

    # Ensure a Cost Center (same as in sample_data) and company defaults
    cc = _get_or_create_cost_center("Musterhaus Berlin", company)
    if company:
        try:
            _ensure_company_account_defaults(company, cost_center=cc)
        except Exception:
            pass
    bankkonto = _get_or_create_company_bank_account(company) if company else None

    # Ensure BK-Arten exist (after defaults)
    _ensure_betriebskostenarten(company)

    # Ensure a few demo suppliers
    supp_strom = _get_or_create_supplier("Stadtwerke Musterstadt GmbH", company)
    supp_reinigung = _get_or_create_supplier("Clean & Shine GmbH", company)
    supp_muell = _get_or_create_supplier("Müllentsorgung AG", company)
    supp_vers = _get_or_create_supplier("Versicherung Ideal AG", company)

    # Plan a few monthly bills
    plans: List[Tuple[str, str, List[Tuple[str, float, str]]]] = [
        (
            "BK-STROM-REINIGUNG-2025-01",
            "2025-01-15",
            [
                ("Allgemeinstrom", 250.0, cc or ""),
                ("Treppenhausreinigung", 150.0, cc or ""),
            ],
        ),
        (
            "BK-MUELL-HAUSWART-2025-02",
            "2025-02-15",
            [
                ("Müllabfuhr", 95.0, cc or ""),
                ("Hauswart", 220.0, cc or ""),
            ],
        ),
        (
            "BK-VERSICHERUNG-GARTEN-2025-03",
            "2025-03-15",
            [
                ("Gebäudeversicherung", 600.0, cc or ""),
                ("Gartenpflege", 130.0, cc or ""),
            ],
        ),
    ]

    # Create via Buchungs-Cockpit API, distributing to fitting suppliers
    supplier_cycle = [supp_strom, supp_reinigung, supp_muell, supp_vers]
    for idx, (bill_no, bill_date, rows) in enumerate(plans):
        supplier = supplier_cycle[idx % len(supplier_cycle)]
        pi_name = _ensure_pi_via_cockpit_and_submit(
            supplier=supplier,
            bill_no=bill_no,
            bill_date=bill_date,
            row_specs=rows,
            bankkonto=bankkonto,
        )
        if pi_name:
            created["Purchase Invoice"].append(pi_name)
            if with_payments:
                pe_name = _create_payment_for_purchase_invoice(pi_name)
                if pe_name:
                    created["Payment Entry"].append(pe_name)

    frappe.db.commit()
    return created
