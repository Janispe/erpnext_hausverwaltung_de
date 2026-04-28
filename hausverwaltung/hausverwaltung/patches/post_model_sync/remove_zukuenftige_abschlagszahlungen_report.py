"""Remove the legacy 'Zukünftige Abschlagszahlungen' Report.

The report has been replaced by 'Offene Abschlagszahlungen', which covers both
overdue and upcoming plan rows.
"""

import frappe


def execute():
    name = "Zukünftige Abschlagszahlungen"
    if frappe.db.exists("Report", name):
        frappe.delete_doc("Report", name, ignore_permissions=True, force=1)
