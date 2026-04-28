"""Initialize the new auto-computed `status` field on Abschlagszahlung.

Replaces the legacy `aktiv` checkbox. Statuses: Läuft / Abgerechnet / Vergangenheit.
"""

import frappe


def execute():
    if not frappe.db.exists("DocType", "Abschlagszahlung"):
        return

    from hausverwaltung.hausverwaltung.doctype.abschlagszahlung.abschlagszahlung import update_statuses_for_list

    update_statuses_for_list()
    frappe.db.commit()
