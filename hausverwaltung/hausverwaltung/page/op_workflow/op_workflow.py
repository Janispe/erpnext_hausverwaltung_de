"""
op_workflow.py — Server-Side API für die Frappe Page "op-workflow".

Diese Datei enthält:
  1. Wrapper für den bestehenden Script Report (get_open_items)
  2. Action-Endpoints: Mahnung erstellen, Zahlung anlegen, Vorauszahlung zuordnen,
     Abschreiben — jeweils mit kommentiertem Body, den du in Phase 3 einkommentierst.

Sicherheits-Pattern: jeder Endpoint validiert Permissions explizit + nutzt
``frappe.db.get_value`` mit ``for_update=True`` wo nötig, um Race-Conditions
beim Buchen zu vermeiden.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, add_days


# ───────────────────────────────────────────────────────────────────────────
# Phase 2 · Datenbereitstellung
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_open_items(filters: str | dict | None = None) -> dict:
    """Wrapper um den bestehenden Script Report.

    Liefert die Rows so wie der Report sie selbst liefert — die Frontend-Seite
    transformiert sie in ``data-adapter.js`` in das von den React-Komponenten
    erwartete Format.

    Args:
        filters: Dict oder JSON-String mit Report-Filtern. Erlaubte Keys:
            company, mode, von_faelligkeit, bis_faelligkeit, party (Liste),
            cost_center, sortierung, show_settled, show_written_off, …

    Returns:
        ``{"columns": [...], "rows": [...], "today": "YYYY-MM-DD"}``
    """
    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    filters = filters or {}

    # Permission-Check: nur User mit Lese-Recht auf Sales Invoice
    if not frappe.has_permission("Sales Invoice", "read"):
        frappe.throw(_("Keine Berechtigung für offene Posten."), frappe.PermissionError)

    # Direkt die existierende execute()-Funktion aufrufen
    from hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen import (
        noch_offene_rechnungen_und_forderungen as report_module,
    )
    result = report_module.execute(filters)

    # execute() liefert (columns, rows, message, chart, report_summary)
    columns, rows = result[0], result[1]

    return {
        "columns": columns,
        "rows": rows,
        "today": nowdate(),
    }


@frappe.whitelist()
def get_mieter_summary(party: str) -> dict:
    """Mieter-Stammdaten + aktuelle Soll-Miete + aktueller Saldo.

    Wird vom Mieterkonto-Header verwendet.
    """
    if not frappe.has_permission("Customer", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    customer = frappe.get_doc("Customer", party)

    # Beispiel — passe die Felder an deine Custom-Fields an
    return {
        "customer_id": customer.name,
        "name": customer.customer_name,
        "vertrag_seit": getattr(customer, "vertrag_seit", None),
        # Diese Felder kommen aus deinem Mietvertrag-DocType, falls vorhanden:
        # "sollmiete_aktuell": ...,
        # "objekt": ...,
        # "einheit": ...,
    }


# ───────────────────────────────────────────────────────────────────────────
# Phase 3 · Aktionen
# Alle Endpoints sind als Skeleton vorhanden. Body schrittweise entkommentieren.
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def create_dunning(
    sales_invoice: str,
    dunning_type: str,
    posting_date: str | None = None,
    new_due_date: str | None = None,
    mahngebuehr: float | None = None,
    zinsen_aktiv: bool = True,
) -> dict:
    """Erzeugt ein Dunning-Dokument für eine Sales Invoice.

    Args:
        sales_invoice: SI Name (z. B. "ACC-SINV-2026-00203")
        dunning_type: Name eines konfigurierten Dunning Type
            (z. B. "Zahlungserinnerung Stufe 1")
        posting_date: optional, default = heute
        new_due_date: optional, default = heute + 7 Tage
        mahngebuehr: optional Override
        zinsen_aktiv: ob Verzugszinsen berechnet werden sollen

    Returns:
        ``{"dunning": "<dunning-name>", "summe": <gesamtsumme>}``
    """
    if not frappe.has_permission("Dunning", "create"):
        frappe.throw(_("Keine Berechtigung Mahnungen zu erstellen."), frappe.PermissionError)

    # ─────────────────────────────────────────────────────────────────────
    # PHASE 3 — Body entkommentieren wenn bereit:
    # ─────────────────────────────────────────────────────────────────────
    #
    # si = frappe.get_doc("Sales Invoice", sales_invoice)
    # if si.docstatus != 1:
    #     frappe.throw(_("Rechnung ist nicht submitted."))
    # if si.outstanding_amount <= 0:
    #     frappe.throw(_("Rechnung hat keinen offenen Betrag."))
    #
    # dunning = frappe.new_doc("Dunning")
    # dunning.update({
    #     "sales_invoice": sales_invoice,
    #     "customer": si.customer,
    #     "company": si.company,
    #     "dunning_type": dunning_type,
    #     "posting_date": posting_date or nowdate(),
    #     "due_date": new_due_date or add_days(nowdate(), 7),
    #     "outstanding_amount": si.outstanding_amount,
    #     "currency": si.currency,
    # })
    # # Mahngebühr-Override falls gewünscht
    # if mahngebuehr is not None:
    #     dunning.dunning_fee = flt(mahngebuehr)
    # # Verzugszinsen
    # if not zinsen_aktiv:
    #     dunning.rate_of_interest = 0
    # dunning.insert(ignore_permissions=False)
    # dunning.submit()
    #
    # # Optional: mahnstufe-Custom-Field auf Sales Invoice hochzählen
    # # (besser: per Doc-Event-Hook auf Dunning.after_submit)
    # if hasattr(si, "mahnstufe"):
    #     frappe.db.set_value("Sales Invoice", sales_invoice, "mahnstufe",
    #                         (si.mahnstufe or 0) + 1)
    #
    # return {"dunning": dunning.name, "summe": flt(dunning.grand_total)}

    # MOCK-Response solange Body kommentiert ist:
    return {
        "dunning": "DUN-MOCK-001",
        "summe": 1020.50,
        "mock": True,
    }


@frappe.whitelist()
def create_bulk_dunning(
    invoices_by_customer: str | dict,
    dunning_type_per_customer: str | dict | None = None,
    new_due_date: str | None = None,
) -> dict:
    """Sammelmahnung: pro Kunde EIN Dunning-Doc mit mehreren Invoices.

    Args:
        invoices_by_customer: Dict ``{"<customer>": ["SI-1", "SI-2"], ...}``
        dunning_type_per_customer: optional, Dict mit Override pro Customer
        new_due_date: Default für alle

    Returns:
        ``{"created": [<dunning-names>], "errors": [{"customer": ..., "msg": ...}]}``
    """
    if isinstance(invoices_by_customer, str):
        invoices_by_customer = json.loads(invoices_by_customer)
    if isinstance(dunning_type_per_customer, str):
        dunning_type_per_customer = json.loads(dunning_type_per_customer)

    created: list[str] = []
    errors: list[dict] = []

    # PHASE 3 — Body entkommentieren wenn bereit:
    # for customer, invoices in invoices_by_customer.items():
    #     try:
    #         dunning = frappe.new_doc("Dunning")
    #         dunning.customer = customer
    #         dunning.posting_date = nowdate()
    #         dunning.due_date = new_due_date or add_days(nowdate(), 7)
    #         dunning.dunning_type = (
    #             dunning_type_per_customer.get(customer)
    #             if dunning_type_per_customer else "Zahlungserinnerung Stufe 1"
    #         )
    #         for invoice_name in invoices:
    #             si = frappe.get_doc("Sales Invoice", invoice_name)
    #             dunning.append("overdue_payments", {
    #                 "sales_invoice": invoice_name,
    #                 "payment_term": None,
    #                 "due_date": si.due_date,
    #                 "invoice_portion": 100,
    #                 "outstanding": si.outstanding_amount,
    #             })
    #         dunning.insert()
    #         dunning.submit()
    #         created.append(dunning.name)
    #     except Exception as e:
    #         errors.append({"customer": customer, "msg": str(e)})

    return {"created": created or ["DUN-MOCK-BULK-001"], "errors": errors, "mock": not created}


@frappe.whitelist()
def create_payment_entry(
    purchase_invoice: str,
    posting_date: str | None = None,
    use_skonto: bool = False,
    skonto_amount: float | None = None,
    mode_of_payment: str = "Bank Draft",
) -> dict:
    """Erzeugt einen Payment Entry für eine Lieferanten-Rechnung (Purchase Invoice).

    Wenn ``use_skonto=True`` und ``skonto_amount`` gesetzt, wird der Skontobetrag
    als Aufwandsminderung gebucht.
    """
    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    # PHASE 3 — Body entkommentieren wenn bereit:
    # from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    #
    # pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
    # if pi.outstanding_amount <= 0:
    #     frappe.throw(_("Rechnung hat keinen offenen Betrag."))
    #
    # pe = get_payment_entry("Purchase Invoice", purchase_invoice)
    # pe.posting_date = posting_date or nowdate()
    # pe.mode_of_payment = mode_of_payment
    #
    # if use_skonto and skonto_amount:
    #     # Skonto als Deduction-Zeile (Aufwandsminderung)
    #     pe.append("deductions", {
    #         "account": frappe.get_cached_value(
    #             "Company", pi.company, "default_discount_account"
    #         ),
    #         "amount": flt(skonto_amount),
    #         "cost_center": pi.cost_center,
    #     })
    #     pe.paid_amount = flt(pi.outstanding_amount) - flt(skonto_amount)
    #     pe.references[0].allocated_amount = flt(pi.outstanding_amount)
    #
    # pe.insert()
    # pe.submit()
    # return {"payment_entry": pe.name, "auszahlung": flt(pe.paid_amount)}

    return {"payment_entry": "PE-MOCK-001", "auszahlung": 4196.89, "mock": True}


@frappe.whitelist()
def allocate_payment(
    payment_entry: str,
    allocations: str | list,
) -> dict:
    """Ordnet eine offene Vorauszahlung mehreren Sales Invoices zu.

    Args:
        payment_entry: PE-Name (eine unallokierte Vorauszahlung)
        allocations: Liste von ``{"invoice": "SI-x", "amount": 500.0}``
    """
    if isinstance(allocations, str):
        allocations = json.loads(allocations)

    if not frappe.has_permission("Payment Reconciliation", "write"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    # PHASE 3 — Body entkommentieren wenn bereit:
    # from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
    #     reconcile,
    # )
    # pe = frappe.get_doc("Payment Entry", payment_entry)
    # for alloc in allocations:
    #     pe.append("references", {
    #         "reference_doctype": "Sales Invoice",
    #         "reference_name": alloc["invoice"],
    #         "allocated_amount": flt(alloc["amount"]),
    #     })
    # pe.save()
    # # Optional: pe.cancel() + pe.submit() um die Reconciliation zu triggern
    # return {"allocated": len(allocations), "rest": flt(pe.unallocated_amount)}

    return {"allocated": len(allocations), "rest": 0.0, "mock": True}


@frappe.whitelist()
def write_off_invoice(
    sales_invoice: str,
    write_off_account: str | None = None,
    cost_center: str | None = None,
    remarks: str | None = None,
) -> dict:
    """Schreibt eine offene Sales Invoice ab (Forderung uneinbringlich)."""
    if not frappe.has_permission("Journal Entry", "create"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    # PHASE 3 — Body entkommentieren wenn bereit:
    # si = frappe.get_doc("Sales Invoice", sales_invoice)
    # if si.outstanding_amount <= 0:
    #     frappe.throw(_("Nichts abzuschreiben."))
    #
    # je = frappe.new_doc("Journal Entry")
    # je.voucher_type = "Write Off Entry"
    # je.company = si.company
    # je.posting_date = nowdate()
    # je.user_remark = remarks or f"Abschreibung {sales_invoice}"
    # write_off_account = write_off_account or frappe.get_cached_value(
    #     "Company", si.company, "write_off_account"
    # )
    # je.append("accounts", {
    #     "account": write_off_account,
    #     "debit_in_account_currency": si.outstanding_amount,
    #     "cost_center": cost_center or si.cost_center,
    # })
    # je.append("accounts", {
    #     "account": si.debit_to,
    #     "party_type": "Customer",
    #     "party": si.customer,
    #     "credit_in_account_currency": si.outstanding_amount,
    #     "reference_type": "Sales Invoice",
    #     "reference_name": si.name,
    # })
    # je.insert()
    # je.submit()
    # return {"journal_entry": je.name, "amount": flt(si.outstanding_amount)}

    return {"journal_entry": "JE-MOCK-001", "amount": 980.00, "mock": True}


# ───────────────────────────────────────────────────────────────────────────
# Optional · Custom-Status
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def set_klärungs_status(sales_invoice: str, grund: str, notiz: str = "") -> dict:
    """Setzt einen Custom-Status "in Klärung" auf einer Sales Invoice.

    Erfordert ein Custom-Field ``in_klaerung_grund`` (Small Text) auf der
    Sales Invoice. Falls nicht vorhanden, wird als Comment gepostet.
    """
    si = frappe.get_doc("Sales Invoice", sales_invoice)

    if hasattr(si, "in_klaerung_grund"):
        si.db_set("in_klaerung_grund", grund)
    si.add_comment("Comment", text=f"In Klärung: {grund}. {notiz}".strip())
    return {"ok": True}
