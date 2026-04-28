"""Add fields for the simplified-entry tool flow.

On Purchase Invoice / Sales Invoice:
    hv_eingabequelle   : tag that marks invoices created via the simplified tool
On Purchase Invoice Item:
    hv_umlagefaehig    : originating Kostenart DocType (Betriebskostenart vs Nicht umlagefaehig)
    hv_kostenart       : concrete Kostenart record (Dynamic Link)

These replace the VereinfachteBuchung/VereinfachteMieterRechnung intermediary DocTypes.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


EINGABEQUELLE_OPTIONS = "\nVereinfachte Buchung\nVereinfachte Mieterrechnung"


def _upsert_custom_field(doctype: str, custom_field: dict) -> None:
    existing = frappe.db.exists(
        "Custom Field",
        {"dt": doctype, "fieldname": custom_field["fieldname"]},
    )
    if existing:
        doc = frappe.get_doc("Custom Field", existing)
        updated = False
        for key, value in custom_field.items():
            if doc.get(key) != value:
                doc.set(key, value)
                updated = True
        if updated:
            doc.save()
        return

    create_custom_field(doctype, custom_field, ignore_validate=True)


def execute():
    _upsert_custom_field(
        "Purchase Invoice",
        {
            "fieldname": "hv_eingabequelle",
            "label": "Eingabequelle (HV)",
            "fieldtype": "Select",
            "options": EINGABEQUELLE_OPTIONS,
            "insert_after": "remarks",
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            "description": "Gesetzt vom Buchungs-Cockpit. Identifiziert vereinfacht gebuchte Belege.",
        },
    )

    _upsert_custom_field(
        "Sales Invoice",
        {
            "fieldname": "hv_eingabequelle",
            "label": "Eingabequelle (HV)",
            "fieldtype": "Select",
            "options": EINGABEQUELLE_OPTIONS,
            "insert_after": "remarks",
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            "description": "Gesetzt vom Buchungs-Cockpit. Identifiziert vereinfacht gebuchte Belege.",
        },
    )

    _upsert_custom_field(
        "Purchase Invoice Item",
        {
            "fieldname": "hv_umlagefaehig",
            "label": "Umlagefähig (HV)",
            "fieldtype": "Select",
            "options": "\nBetriebskostenart\nKostenart nicht umlagefaehig",
            "insert_after": "expense_account",
            "no_copy": 1,
            "print_hide": 1,
            "description": "Herkunftstyp der Kostenart. Wird vom Buchungs-Cockpit gesetzt.",
        },
    )

    _upsert_custom_field(
        "Purchase Invoice Item",
        {
            "fieldname": "hv_kostenart",
            "label": "Kostenart (HV)",
            "fieldtype": "Dynamic Link",
            "options": "hv_umlagefaehig",
            "insert_after": "hv_umlagefaehig",
            "no_copy": 1,
            "print_hide": 1,
            "description": "Konkrete Kostenart zu der diese Position gehört.",
        },
    )
