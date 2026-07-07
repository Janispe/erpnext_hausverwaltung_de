from __future__ import annotations

from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.utils.sollstellung_titel import build_sollstellung_titel
from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	get_sales_invoice_writeoff_status,
)


def default_wertstellungsdatum_from_posting_date(doc):
	"""Default Sales Invoice value date to posting date when no explicit value exists."""
	if not doc.meta.has_field("custom_wertstellungsdatum"):
		return
	if doc.get("custom_wertstellungsdatum") or not doc.get("posting_date"):
		return

	doc.set("custom_wertstellungsdatum", getdate(doc.get("posting_date")))


class CustomSalesInvoice(SalesInvoice):
	def validate(self):
		super().validate()

		default_wertstellungsdatum_from_posting_date(self)

		if self.meta.has_field("hv_sollstellung_titel"):
			self.hv_sollstellung_titel = build_sollstellung_titel(self)

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
