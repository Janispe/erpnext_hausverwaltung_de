import frappe


def execute():
    if not frappe.db.table_exists("Bankauszug Import Row"):
        return

    columns = set(frappe.db.get_table_columns("Bankauszug Import Row"))
    required = {"payment_entry", "journal_entry", "payment_document_type", "payment_document"}
    if not required.issubset(columns):
        return

    frappe.db.sql(
        """
        update `tabBankauszug Import Row`
        set
            payment_document_type = 'Payment Entry',
            payment_document = payment_entry
        where ifnull(payment_document, '') = ''
          and ifnull(payment_entry, '') != ''
        """
    )
    frappe.db.sql(
        """
        update `tabBankauszug Import Row`
        set
            payment_document_type = 'Journal Entry',
            payment_document = journal_entry
        where ifnull(payment_document, '') = ''
          and ifnull(journal_entry, '') != ''
        """
    )
