"""
mieterkonto_workflow.py — Server-Side API für die Frappe Page "mieterkonto-workflow".

Wrapper um den bestehenden ``mieterkonto.execute``-Report + Stammdaten-Endpoint
für den Mieter-Header.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import nowdate


@frappe.whitelist()
def get_mieterkonto(filters: str | dict | None = None) -> dict:
    """Wrapper um den bestehenden Mieterkonto-Report.

    Liefert die Rows so wie der Report sie selbst liefert — die Frontend-Seite
    transformiert sie in ``mk-data-adapter.js`` in das von den React-Komponenten
    erwartete Format.

    Args:
        filters: company, customer, from_date, to_date, show_kategorien,
                 gruppieren_pro_monat
    """
    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    filters = filters or {}

    if not frappe.has_permission("Sales Invoice", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    from hausverwaltung.hausverwaltung.report.mieterkonto import mieterkonto as report_module
    result = report_module.execute(filters)

    columns, rows = result[0], result[1]
    report_summary = result[4] if len(result) > 4 else []

    return {
        "columns": columns,
        "rows": rows,
        "summary": report_summary,
        "today": nowdate(),
    }


@frappe.whitelist()
def get_mieter_stammdaten(customer: str) -> dict:
    """Mieter-Stammdaten für den Header oben auf der Seite.

    Felder die das Frontend erwartet:
      customer_id, name, objekt, einheit, vertrag_seit, sollmiete_aktuell,
      aufteilung_aktuell, iban_verwendung, firma
    """
    if not frappe.has_permission("Customer", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    cust = frappe.get_doc("Customer", customer)

    # Diese Felder stammen aus deinen Mietvertrag/Objekt-DocTypes.
    # Wenn du keinen Mietvertrag hast, lass leer — der Header zeigt nur Customer-Stamm.
    mietvertrag = None
    try:
        # Beispiel: aktiver Vertrag des Customers
        mietvertrag_name = frappe.db.get_value(
            "Mietvertrag", {"customer": customer, "status": "Aktiv"}, "name"
        )
        if mietvertrag_name:
            mietvertrag = frappe.get_doc("Mietvertrag", mietvertrag_name)
    except Exception:
        pass

    return {
        "customer_id": cust.name,
        "name": cust.customer_name,
        "objekt": getattr(mietvertrag, "objekt", None) if mietvertrag else None,
        "einheit": getattr(mietvertrag, "einheit", None) if mietvertrag else None,
        "vertrag_seit": getattr(mietvertrag, "von", None) if mietvertrag else None,
        "sollmiete_aktuell": getattr(mietvertrag, "sollmiete", None) if mietvertrag else None,
        "aufteilung_aktuell": {
            "miete":              getattr(mietvertrag, "betrag_miete", 0) if mietvertrag else 0,
            "betriebskosten":     getattr(mietvertrag, "betrag_betriebskosten", 0) if mietvertrag else 0,
            "heizkosten":         getattr(mietvertrag, "betrag_heizkosten", 0) if mietvertrag else 0,
            "guthaben_nachzahlungen": 0,
        },
        "iban_verwendung": getattr(mietvertrag, "verwendungszweck", None) if mietvertrag else None,
        "firma": frappe.defaults.get_user_default("Company"),
    }
