"""Narrow reference adapter for explicitly confirmed stored legacy letters."""
from erpnext.accounts.doctype.dunning.dunning import Dunning

from hausverwaltung.hausverwaltung.utils.dunning_creation import lock_dunning_invoices
from hausverwaltung.hausverwaltung.utils.legacy_dunning_confirmation import require_confirmation


class CustomDunning(Dunning):
	def validate_overdue_payment_references(self):
		payments = self.get("overdue_payments") or []
		# All regular cases keep the complete installed ERPNext validator.
		# The adapter never filters rows or fabricates a Payment Schedule.
		if getattr(self, "_action", None) == "submit" and any(not row.get("payment_schedule") for row in payments):
			names = [row.sales_invoice for row in payments if row.get("sales_invoice")]
			invoices = lock_dunning_invoices(names, self.posting_date) if names else []
			if any(not invoice.get("payment_schedule") for invoice in invoices):
				require_confirmation(self, invoices)
				return
		return super().validate_overdue_payment_references()
