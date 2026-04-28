from __future__ import annotations

from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	get_sales_invoice_writeoff_status,
)


class CustomSalesInvoice(SalesInvoice):
	def set_status(self, update=False, status=None, update_modified=True):
		super().set_status(update=False, status=status, update_modified=update_modified)

		writeoff_status = get_sales_invoice_writeoff_status(
			self.name,
			outstanding_amount=self.outstanding_amount,
		)
		if not status and writeoff_status:
			self.status = writeoff_status

		if update:
			self.db_set("status", self.status, update_modified=update_modified)
