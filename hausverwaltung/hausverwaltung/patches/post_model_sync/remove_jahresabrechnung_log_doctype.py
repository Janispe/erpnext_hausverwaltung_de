"""Remove the legacy 'Abschlagszahlung Jahresabrechnung' Child-DocType.

The log table on Abschlagszahlung was redundant under the assumption '1 Abschlagszahlung-Doc = 1 Jahr'.
Result fields (ja_purchase_invoice, ja_differenz, ja_status) are sufficient; full audit lives on the PI.
"""

import frappe


def execute():
    name = "Abschlagszahlung Jahresabrechnung"
    if frappe.db.exists("DocType", name):
        frappe.delete_doc("DocType", name, ignore_permissions=True, force=1)
