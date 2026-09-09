import unittest

from hausverwaltung.hausverwaltung.utils.insurance_receivables import _replace_cash_accounts


class TestInsuranceCashAttribution(unittest.TestCase):
	def test_mixed_payment_preserves_invoice_and_unallocated_remainder(self):
		entries = [
			dict(voucher_type="Payment Entry", voucher_no="PE1", account="Other expense", expense=100),
			dict(voucher_type="Payment Entry", voucher_no="PE1", account="Guthaben Mieter", expense=300),
		]
		mapped = [
			dict(
				voucher_type="Payment Entry",
				voucher_no="PE1",
				source_account="Debitor",
				account="Glaser",
				expense=200,
			)
		]
		result = _replace_cash_accounts(entries, mapped)
		self.assertEqual(sum(r.get("expense", 0) for r in result), 400)
		self.assertEqual(
			{r["account"]: r.get("expense") for r in result},
			{"Other expense": 100, "Guthaben Mieter": 100, "Glaser": 200},
		)
		self.assertEqual(entries[1]["expense"], 300)

	def test_receipt_replaces_asset_account_without_double_income(self):
		entry = dict(voucher_type="Journal Entry", voucher_no="JE1", account="Insurance asset", income=200)
		mapping = dict(
			voucher_type="Journal Entry",
			voucher_no="JE1",
			source_account="Insurance asset",
			account="Insurance income",
			income=200,
		)
		result = _replace_cash_accounts([entry], [mapping])
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["income"], 200)
		self.assertEqual(result[0]["account"], "Insurance income")

	def test_cash_basis_adds_income_when_asset_accounts_are_hidden(self):
		mapping = dict(
			voucher_type="Journal Entry",
			voucher_no="JE1",
			source_account="Insurance asset",
			account="Insurance income",
			income=200,
		)
		result = _replace_cash_accounts([], [mapping])
		self.assertEqual(result[0]["income"], 200)
