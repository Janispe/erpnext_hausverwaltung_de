from __future__ import annotations

import frappe


def execute():
    """Repair tax templates that reference Accounts from another Company.

    This prevents errors like:
      "Account <...> does not belong to company <...>"
    when creating invoices after demo resets / CoA changes.
    """

    try:
        from hausverwaltung.hausverwaltung.utils.tax_template_fixes import repair_tax_template_accounts

        repair_tax_template_accounts(dry_run=False)
    except Exception as exc:  # noqa: BLE001
        try:
            frappe.log_error(message=str(exc), title="HV: repair_tax_template_accounts failed")
        except Exception:
            # last resort: avoid breaking migrations
            pass
