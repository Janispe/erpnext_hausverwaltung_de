# See license.txt

import base64
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.page.bankimport_v2 import bankimport_v2 as bv2


class _FakeBT:
	"""Minimal-Stand-In für eine Bank Transaction — nur die Felder, die
	``prepare_invoice_match`` liest."""

	def __init__(self, *, name="BT-1", party_type="Customer", party="MIETER-1",
				 deposit=0.0, withdrawal=0.0, payment_entries=None):
		self.name = name
		self.party_type = party_type
		self.party = party
		self.deposit = deposit
		self.withdrawal = withdrawal
		self._pe = payment_entries or []

	def get(self, key, default=None):
		if key == "payment_entries":
			return self._pe
		return getattr(self, key, default)


class _FakeInvoice:
	def __init__(self, name, outstanding_amount, posting_date="2026-01-15"):
		self.name = name
		self.outstanding_amount = outstanding_amount
		self.posting_date = posting_date

	def __getitem__(self, key):
		return getattr(self, key)

	def get(self, key, default=None):
		return getattr(self, key, default)


class _OverviewRow:
	def __init__(self):
		self.name = "ROW-OVERVIEW"
		self.buchungstag = "2026-04-27"
		self.betrag = 625.0
		self.richtung = "Eingang"
		self.iban = "DE123"
		self.auftraggeber = "Mieter"
		self.verwendungszweck = "Miete"
		self.party_type = "Customer"
		self.party = "MIETER-1"
		self.bank_transaction = "BT-1"
		self.payment_entry = "PE-CANCELLED"
		self.journal_entry = None
		self.payment_document = "PE-CANCELLED"
		self.payment_document_type = "Payment Entry"
		self.row_status = "success"
		self.error = None
		self.auto_match_message = ""
		self.owner = "importer@example.test"
		self.creation = "2026-04-27 09:30:00"
		self.modified_by = "user@example.test"
		self.modified = "2026-04-27 10:15:00"

	def get(self, key, default=None):
		return getattr(self, key, default)

	def as_dict(self):
		return {
			"payment_entry": self.payment_entry,
			"journal_entry": self.journal_entry,
			"bank_transaction": self.bank_transaction,
			"party_type": self.party_type,
			"party": self.party,
			"row_status": self.row_status,
			"error": self.error,
		}


class _OverviewDoc:
	def __init__(self, row):
		self.name = "IMP-OVERVIEW"
		self.title = "Import"
		self.bank_account = "BANK-1"
		self.csv_file = None
		self.status = "stale"
		self.rows = [row]

	def get(self, key, default=None):
		return getattr(self, key, default)

	def reload(self):
		return None

	def _bank_account_label(self):
		return "Bank"


class _FakeBankAccount:
	def __init__(self, *, name="BANK-1", is_company_account=1, disabled=0, account="1800"):
		self.name = name
		self.is_company_account = is_company_account
		self.disabled = disabled
		self.account = account

	def get(self, key, default=None):
		return getattr(self, key, default)


class TestListImports(unittest.TestCase):
	def test_uses_dict_syntax_for_row_count_aggregate(self):
		imports = [
			frappe._dict(
				name="BAI-1",
				title="Import",
				status="Offen",
				offene_buchungen=1,
				modified="2026-05-31 10:00:00",
			)
		]
		rows = [frappe._dict(parent="BAI-1", total_rows=3)]

		with patch("frappe.get_list", return_value=imports), \
			 patch("frappe.get_all", return_value=rows) as get_all:
			result = bv2.list_imports()

		self.assertEqual(result["items"][0]["total_rows"], 3)
		self.assertEqual(
			get_all.call_args.kwargs["fields"],
			["parent", {"COUNT": "name", "as": "total_rows"}],
		)


class TestListBankAccounts(unittest.TestCase):
	class _Meta:
		def has_field(self, fieldname):
			return fieldname in {"iban", "disabled"}

	def test_filters_out_disabled_bank_accounts(self):
		with patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.get_list", return_value=[]) as get_list:
			bv2.list_bank_accounts()

		self.assertEqual(
			get_list.call_args.kwargs["filters"],
			{"is_company_account": 1, "disabled": 0},
		)

	def test_skips_bank_accounts_with_disabled_gl_account(self):
		rows = [
			frappe._dict(name="Active Bank", bank="Postbank", account="1800", iban="DE-ACTIVE"),
			frappe._dict(name="Disabled GL Bank", bank="Postbank", account="1810", iban="DE-DISABLED"),
		]

		def get_value(doctype, name, fieldname):
			if doctype == "Account" and fieldname == "disabled":
				return 1 if name == "1810" else 0
			if doctype == "Account" and fieldname == "account_number":
				return name
			return None

		with patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.get_list", return_value=rows), \
			 patch("frappe.db.get_value", side_effect=get_value):
			result = bv2.list_bank_accounts()

		self.assertEqual([item["value"] for item in result["items"]], ["Active Bank"])

	def test_search_text_adds_name_and_bank_or_filters_without_dropping_active_filter(self):
		rows = [
			frappe._dict(name="Hausbank Betrieb - HV", bank="Sparkasse", account="1800", iban="DE-ACTIVE"),
		]

		with patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.get_list", return_value=rows) as get_list, \
			 patch("frappe.db.get_value", side_effect=lambda doctype, name, fieldname: "1800" if fieldname == "account_number" else 0):
			result = bv2.list_bank_accounts("spark")

		self.assertEqual(result["items"][0]["value"], "Hausbank Betrieb - HV")
		self.assertEqual(
			get_list.call_args.kwargs["filters"],
			{"is_company_account": 1, "disabled": 0},
		)
		self.assertEqual(
			get_list.call_args.kwargs["or_filters"],
			[["name", "like", "%spark%"], ["bank", "like", "%spark%"]],
		)
		self.assertEqual(result["items"][0]["label"], "Hausbank Betrieb (1800)")


class TestBankimportRulesPanel(unittest.TestCase):
	def test_list_bankimport_rules_groups_rule_types_and_scope_rows(self):
		def fake_get_all(doctype, **kwargs):
			if doctype == "Bankimport Party Regel":
				return [
					frappe._dict(
						name="party.unique_iban_to_party",
						rule_key="party.unique_iban_to_party",
						enabled=1,
						priority=10,
						rule_code="result = {'matched': False}",
						stop_on_match=1,
						requires_review=0,
						parameters_json="",
						description="IBAN",
						modified="2026-06-30 10:00:00",
					)
				]
			if doctype == "Bankimport Buchungsregel":
				return [
					frappe._dict(
						name="booking.invoice_auto_match",
						rule_key="booking.invoice_auto_match",
						enabled=0,
						priority=100,
						rule_code="result = auto_match_invoice(row=row, bt=bt, context=context)",
						auto_apply=1,
						stop_on_match=1,
						requires_review=0,
						parameters_json="",
						description="Invoice",
						modified="2026-06-30 11:00:00",
					)
				]
			if doctype == "Bankimport Regel Scope":
				parenttype = kwargs["filters"]["parenttype"]
				if parenttype == "Bankimport Party Regel":
					return [
						frappe._dict(
							parent="party.unique_iban_to_party",
							mode="Sperren",
							scope_type="IBAN",
							iban="de12 3456",
							party_type=None,
							party=None,
							description="",
						)
					]
				return []
			raise AssertionError(f"unexpected doctype {doctype}")

		with patch.object(bv2, "ensure_default_bankimport_rules") as ensure_defaults, \
			 patch("frappe.has_permission") as has_permission, \
			 patch("frappe.get_all", side_effect=fake_get_all):
			result = bv2.list_bankimport_rules()

		ensure_defaults.assert_called_once()
		self.assertEqual(has_permission.call_count, 2)
		self.assertEqual(result["groups"]["party"]["counts"]["enabled"], 1)
		self.assertEqual(result["groups"]["booking"]["counts"]["disabled"], 1)
		self.assertTrue(result["groups"]["party"]["items"][0]["hasRuleCode"])
		self.assertEqual(
			result["groups"]["party"]["items"][0]["scope"][0]["iban"],
			"DE123456",
		)
		self.assertEqual(
			result["groups"]["booking"]["items"][0]["ruleKey"],
			"booking.invoice_auto_match",
		)

	def test_set_bankimport_rule_enabled_validates_doctype_and_sets_value(self):
		with patch("frappe.has_permission") as has_permission, \
			 patch("frappe.db.exists", return_value=True), \
			 patch("frappe.db.set_value") as set_value:
			result = bv2.set_bankimport_rule_enabled(
				"Bankimport Party Regel",
				"party.unique_iban_to_party",
				0,
			)

		has_permission.assert_called_once_with("Bankimport Party Regel", "write", throw=True)
		set_value.assert_called_once_with(
			"Bankimport Party Regel",
			"party.unique_iban_to_party",
			"enabled",
			0,
		)
		self.assertEqual(result["enabled"], 0)


class TestDeleteImport(unittest.TestCase):
	def test_delete_import_uses_normal_permissions(self):
		doc = frappe._dict(name="BAI-1", title="Import", rows=[])

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission") as has_permission, \
			 patch("frappe.delete_doc") as delete_doc:
			result = bv2.delete_import("BAI-1")

		has_permission.assert_called_once_with("Bankauszug Import", "delete", doc=doc, throw=True)
		delete_doc.assert_called_once_with("Bankauszug Import", "BAI-1")
		self.assertTrue(result["ok"])
		self.assertEqual(result["name"], "BAI-1")

	def test_delete_impact_separates_import_owned_and_existing_bank_transactions(self):
		doc = frappe._dict(
			name="BAI-1",
			title="Import",
			rows=[
				frappe._dict(name="ROW-1", bank_transaction="BT-OWN", row_status="success"),
				frappe._dict(name="ROW-2", bank_transaction="BT-EXISTING", row_status="schon vorhanden"),
				frappe._dict(
					name="ROW-3",
					bank_transaction="BT-OWN",
					row_status="success",
					payment_document_type="Payment Entry",
					payment_document="PE-1",
				),
			],
		)

		with patch("frappe.db.get_value", return_value=1):
			impact = bv2._delete_impact_for_doc(doc)

		self.assertTrue(impact["requiresCascade"])
		self.assertEqual(impact["counts"]["bankTransactionsToReverse"], 1)
		self.assertEqual(impact["counts"]["bankTransactionsKept"], 1)
		self.assertEqual(impact["counts"]["paymentEntries"], 1)
		self.assertEqual(impact["bankTransactionsToReverse"][0]["name"], "BT-OWN")
		self.assertEqual(impact["bankTransactionsKept"][0]["name"], "BT-EXISTING")

	def test_delete_impact_deduplicates_vouchers_and_bank_transactions_across_rows(self):
		doc = frappe._dict(
			name="BAI-MIXED",
			title="Gemischter Import",
			rows=[
				frappe._dict(
					name="ROW-1",
					bank_transaction="BT-SHARED",
					row_status="success",
					payment_document_type="Payment Entry",
					payment_document="PE-SHARED",
				),
				frappe._dict(
					name="ROW-2",
					bank_transaction="BT-SHARED",
					row_status="success",
					payment_document_type="Payment Entry",
					payment_document="PE-SHARED",
				),
				frappe._dict(
					name="ROW-3",
					reference="BT-EXISTING",
					row_status="vor Start-Datum",
					journal_entry="JE-DRAFT",
				),
			],
		)

		def get_value(doctype, name, fieldname):
			if doctype == "Payment Entry":
				return 1
			if doctype == "Journal Entry":
				return 0
			if doctype == "Bank Transaction" and name == "BT-SHARED":
				return 1
			if doctype == "Bank Transaction" and name == "BT-EXISTING":
				return 2
			return None

		with patch("frappe.db.get_value", side_effect=get_value):
			impact = bv2._delete_impact_for_doc(doc)

		self.assertTrue(impact["requiresCascade"])
		self.assertEqual(impact["counts"], {
			"vouchers": 2,
			"paymentEntries": 1,
			"journalEntries": 1,
			"bankTransactionsToReverse": 1,
			"bankTransactionsKept": 1,
		})
		self.assertEqual(impact["vouchers"][0]["rows"], ["ROW-1", "ROW-2"])
		self.assertEqual(impact["bankTransactionsToReverse"][0]["rows"], ["ROW-1", "ROW-2"])
		self.assertEqual(impact["bankTransactionsKept"][0]["reason"], "already-existing")
		self.assertEqual(impact["bankTransactionsKept"][0]["status"], "cancelled")

	def test_delete_import_requires_cascade_when_followup_documents_exist(self):
		doc = frappe._dict(
			name="BAI-1",
			title="Import",
			rows=[frappe._dict(name="ROW-1", bank_transaction="BT-OWN", row_status="success")],
		)

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission"), \
			 patch("frappe.db.get_value", return_value=1), \
			 self.assertRaises(frappe.ValidationError):
			bv2.delete_import("BAI-1", cascade=0)

	def test_cascade_delete_cancels_vouchers_cleans_owned_bank_transactions_and_deletes_import(self):
		doc = frappe._dict(name="BAI-1")
		impact = {
			"vouchers": [{"type": "Payment Entry", "name": "PE-1"}],
			"bankTransactionsToReverse": [{"name": "BT-1"}],
			"bankTransactionsKept": [{"name": "BT-EXISTING"}],
		}

		with patch("frappe.db.savepoint") as savepoint, \
			 patch.object(bv2, "_cancel_voucher_for_row", return_value={"status": "cancelled"}) as cancel, \
			 patch("hausverwaltung.hausverwaltung.utils.bank_transaction_links.remove_bank_transaction_payment_links", return_value=["BT-1"]) as delink, \
			 patch.object(bv2, "_cleanup_bank_transaction_for_import_delete", return_value={"status": "cancelled"}) as cleanup_bt, \
			 patch("frappe.delete_doc") as delete_doc:
			res = bv2._cascade_delete_import(doc, impact)

		savepoint.assert_called_once_with("bankimport_delete_cascade")
		cancel.assert_called_once_with("Payment Entry", "PE-1")
		delink.assert_called_once_with("Payment Entry", "PE-1")
		cleanup_bt.assert_called_once_with("BT-1")
		delete_doc.assert_called_once_with("Bankauszug Import", "BAI-1")
		self.assertEqual(res["vouchers"][0]["cancel"]["status"], "cancelled")
		self.assertEqual(res["keptBankTransactions"], [{"name": "BT-EXISTING"}])

	def test_cascade_delete_rolls_back_and_keeps_import_when_cleanup_fails(self):
		doc = frappe._dict(name="BAI-ROLLBACK")
		impact = {
			"vouchers": [{"type": "Journal Entry", "name": "JE-1"}],
			"bankTransactionsToReverse": [],
			"bankTransactionsKept": [],
		}

		with patch("frappe.db.savepoint") as savepoint, \
			 patch("frappe.db.rollback") as rollback, \
			 patch.object(bv2, "_cancel_voucher_for_row", side_effect=Exception("cancel failed")), \
			 patch("frappe.delete_doc") as delete_doc, \
			 self.assertRaisesRegex(Exception, "cancel failed"):
			bv2._cascade_delete_import(doc, impact)

		savepoint.assert_called_once_with("bankimport_delete_cascade")
		rollback.assert_called_once_with(save_point="bankimport_delete_cascade")
		delete_doc.assert_not_called()

	def test_delete_import_without_impact_deletes_directly_without_savepoint(self):
		doc = frappe._dict(name="BAI-EMPTY", title="Leerer Import", rows=[])

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission"), \
			 patch("frappe.db.savepoint") as savepoint, \
			 patch("frappe.delete_doc") as delete_doc:
			result = bv2.delete_import("BAI-EMPTY", cascade=0)

		savepoint.assert_not_called()
		delete_doc.assert_called_once_with("Bankauszug Import", "BAI-EMPTY")
		self.assertFalse(result["impact"]["requiresCascade"])
		self.assertEqual(result["cleanup"], {})


class TestCreateImport(unittest.TestCase):
	class _Meta:
		def has_field(self, fieldname):
			return fieldname in {"disabled", "attached_to_field"}

	def _raise_throw(self, msg):
		raise frappe.ValidationError(str(msg))

	def test_rejects_empty_file_payload(self):
		with patch("frappe.has_permission"), \
			 patch("frappe.throw", side_effect=self._raise_throw):
			with self.assertRaisesRegex(frappe.ValidationError, "Bitte eine CSV-Datei auswählen."):
				bv2.create_import("BANK-1", "konto.csv", "")

	def test_rejects_invalid_base64_payload(self):
		with patch("frappe.has_permission"), \
			 patch("frappe.db.exists", return_value=True), \
			 patch("frappe.get_doc", return_value=_FakeBankAccount()), \
			 patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.db.get_value", return_value=0), \
			 patch("frappe.throw", side_effect=self._raise_throw):
			with self.assertRaisesRegex(frappe.ValidationError, "CSV-Datei konnte nicht gelesen"):
				bv2.create_import("BANK-1", "konto.csv", "data:text/csv;base64,%%%")

	def test_rejects_non_company_bank_account(self):
		with patch("frappe.has_permission"), \
			 patch("frappe.db.exists", return_value=True), \
			 patch("frappe.get_doc", return_value=_FakeBankAccount(is_company_account=0)), \
			 patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.throw", side_effect=self._raise_throw):
			with self.assertRaisesRegex(frappe.ValidationError, "Firmen-Bankkonto"):
				bv2.create_import("BANK-1", "konto.csv", "QQ==")

	def test_rejects_disabled_linked_gl_account(self):
		with patch("frappe.has_permission"), \
			 patch("frappe.db.exists", return_value=True), \
			 patch("frappe.get_doc", return_value=_FakeBankAccount(account="1800")), \
			 patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.db.get_value", return_value=1), \
			 patch("frappe.throw", side_effect=self._raise_throw):
			with self.assertRaisesRegex(frappe.ValidationError, "Sachkonto ist deaktiviert"):
				bv2.create_import("BANK-1", "konto.csv", "QQ==")

	def test_rejects_payload_over_ten_megabytes(self):
		too_large = base64.b64encode(b"x" * (10 * 1024 * 1024 + 1)).decode("ascii")
		with patch("frappe.has_permission"), \
			 patch("frappe.db.exists", return_value=True), \
			 patch("frappe.get_doc", return_value=_FakeBankAccount()), \
			 patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.db.get_value", return_value=0), \
			 patch("frappe.throw", side_effect=self._raise_throw):
			with self.assertRaisesRegex(frappe.ValidationError, "zu groß"):
				bv2.create_import("BANK-1", "konto.csv", too_large)

	def test_rejects_missing_bank_account_before_file_decoding(self):
		with patch("frappe.has_permission"), \
			 patch("frappe.throw", side_effect=self._raise_throw), \
			 patch("frappe.db.exists") as exists:
			with self.assertRaisesRegex(frappe.ValidationError, "Bitte ein Bankkonto auswählen."):
				bv2.create_import("", "konto.csv", "not-base64")

		exists.assert_not_called()

	def test_attaches_file_to_import_after_successful_parse(self):
		file_doc = frappe._dict(file_url="/private/files/konto.csv")
		file_doc.db_set = unittest.mock.Mock()
		import_doc = frappe._dict(name="BAI-1", title=None, csv_file=file_doc.file_url)
		import_doc.insert = unittest.mock.Mock()
		import_doc.reload = unittest.mock.Mock(side_effect=lambda: import_doc.update(title="Import 1"))

		def get_doc(arg1, name=None):
			if arg1 == "Bank Account":
				return _FakeBankAccount()
			if isinstance(arg1, dict) and arg1.get("doctype") == "Bankauszug Import":
				self.assertEqual(arg1["bank_account"], "BANK-1")
				self.assertEqual(arg1["csv_file"], file_doc.file_url)
				return import_doc
			raise AssertionError(f"unexpected get_doc call: {arg1!r}, {name!r}")

		payload = base64.b64encode(b"Buchungstag;Betrag\n10.06.2026;1,00").decode("ascii")
		with patch("frappe.has_permission"), \
			 patch("frappe.db.exists", return_value=True), \
			 patch("frappe.get_doc", side_effect=get_doc), \
			 patch("frappe.get_meta", return_value=self._Meta()), \
			 patch("frappe.db.get_value", return_value=0), \
			 patch.object(bv2, "save_file", return_value=file_doc) as save_file, \
			 patch.object(bv2, "parse_csv", return_value={"rows": 1}) as parse_csv:
			result = bv2.create_import("BANK-1", "konto.csv", f"data:text/csv;base64,{payload}")

		save_file.assert_called_once()
		import_doc.insert.assert_called_once()
		parse_csv.assert_called_once_with("BAI-1")
		file_doc.db_set.assert_any_call("attached_to_doctype", "Bankauszug Import")
		file_doc.db_set.assert_any_call("attached_to_name", "BAI-1")
		file_doc.db_set.assert_any_call("attached_to_field", "csv_file")
		self.assertEqual(result["name"], "BAI-1")
		self.assertEqual(result["parse"], {"rows": 1})


class TestSuggestInvoiceForRow(unittest.TestCase):
	"""Sichert, dass die Rechnungs-Empfehlung des bankimport_v2-Overview die
	gleiche Single-Exact-Logik wie der echte Auto-Matcher anwendet — nur ohne
	zu buchen."""

	def test_returns_invoice_id_on_single_exact_match(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=1234.56)
		invoices = [
			_FakeInvoice("SI-001", outstanding_amount=999.00),
			_FakeInvoice("SI-002", outstanding_amount=1234.56),  # exact hit
		]
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=invoices):
			result = bv2._suggest_invoice_for_row("BT-1")

		self.assertEqual(result, {
			"rechnungId": "SI-002",
			"reason": "Offener Beleg dieser Höhe gefunden",
		})

	def test_returns_none_when_no_exact_match(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=1234.56)
		invoices = [
			_FakeInvoice("SI-001", outstanding_amount=400.00),
			_FakeInvoice("SI-002", outstanding_amount=500.00),
		]
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=invoices):
			result = bv2._suggest_invoice_for_row("BT-1")

		self.assertIsNone(result)

	def test_returns_none_when_multiple_exact_matches(self):
		"""Ambiguität ist keine Empfehlung — bei mehreren gleichbetraglichen
		offenen Rechnungen wählt der User selbst im Rechnungs-Tab."""
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=1234.56)
		invoices = [
			_FakeInvoice("SI-001", outstanding_amount=1234.56),
			_FakeInvoice("SI-002", outstanding_amount=1234.56),  # zweiter exact match
		]
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=invoices):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_no_open_invoices(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=100.00)
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=[]):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_bt_already_reconciled(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=100.00,
					 payment_entries=[{"payment_entry": "PE-1"}])
		with patch("frappe.get_doc", return_value=bt):
			# get_all darf gar nicht aufgerufen werden — frühes Abbruch in prepare_invoice_match
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_no_party(self):
		bt = _FakeBT(party_type=None, party=None, deposit=100.00)
		with patch("frappe.get_doc", return_value=bt):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_customer_without_deposit(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=0.0, withdrawal=50.00)
		with patch("frappe.get_doc", return_value=bt):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_on_missing_bank_transaction(self):
		import frappe

		def raise_dne(*args, **kwargs):
			raise frappe.DoesNotExistError

		with patch("frappe.get_doc", side_effect=raise_dne):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-NONEXISTENT"))


class TestGetOverviewSync(unittest.TestCase):
	def test_row_audit_contains_actor_dates_and_manual_source(self):
		row = _OverviewRow()
		row.auto_match_message = "Manuell zugeordnet: 1 Rechnung(en), 625.00 €"

		with patch.object(bv2, "_doc_audit", side_effect=lambda doctype, name: {
			"doctype": doctype,
			"name": name,
			"createdBy": "creator@example.test",
			"createdAt": "2026-04-27 10:00:00",
			"modifiedBy": "editor@example.test",
			"modifiedAt": "2026-04-27 10:01:00",
		} if name else None):
			audit = bv2._row_audit(row)

		self.assertEqual(audit["row"]["createdBy"], "importer@example.test")
		self.assertEqual(audit["row"]["createdAt"], "2026-04-27 09:30:00")
		self.assertEqual(audit["assignment"]["source"], "Manuell")
		self.assertEqual(audit["assignment"]["by"], "user@example.test")
		self.assertEqual(audit["assignment"]["at"], "2026-04-27 10:15:00")
		self.assertEqual(audit["party"]["doctype"], "Customer")
		self.assertEqual(audit["bankTransaction"]["name"], "BT-1")
		self.assertEqual(audit["paymentDocument"]["doctype"], "Payment Entry")

	def test_row_audit_marks_auto_message_as_automatic(self):
		row = _OverviewRow()
		row.auto_match_message = "Automatisch gebucht: PE-1"

		with patch.object(bv2, "_doc_audit", return_value=None):
			audit = bv2._row_audit(row)

		self.assertEqual(audit["assignment"]["source"], "Automatisch")

	def test_row_without_party_with_bank_transaction_is_bookable_phase_3(self):
		row = {
			"payment_entry": None,
			"journal_entry": None,
			"bank_transaction": "BT-1",
			"party_type": None,
			"party": None,
			"row_status": None,
		}

		phase = bv2._row_phase(row)

		self.assertEqual(phase, 3)
		self.assertEqual(bv2._row_status(row, phase), "phase3-open")

	def test_existing_row_is_done_phase_without_party(self):
		row = {
			"payment_entry": None,
			"journal_entry": None,
			"bank_transaction": "BT-1",
			"party_type": None,
			"party": None,
			"row_status": "schon vorhanden",
		}

		phase = bv2._row_phase(row)

		self.assertEqual(phase, 4)
		self.assertEqual(bv2._row_status(row, phase), "existing")

	def test_failed_import_row_is_error_not_party_assignment(self):
		row = {
			"payment_entry": None,
			"journal_entry": None,
			"bank_transaction": None,
			"party_type": None,
			"party": None,
			"row_status": "failed",
			"error": "Ungültiges Datum",
		}

		phase = bv2._row_phase(row)

		self.assertEqual(phase, 3)
		self.assertEqual(bv2._row_status(row, phase), "error")

	def test_get_overview_syncs_cancelled_payment_entry_before_response(self):
		row = _OverviewRow()
		doc = _OverviewDoc(row)

		def sync_side_effect(import_name=None, payment_entry_name=None):
			row.payment_entry = None
			row.payment_document = None
			row.payment_document_type = None
			row.row_status = None
			row.auto_match_message = (
				"Automatisch zurückgesetzt: Payment Entry PE-CANCELLED ist storniert."
			)
			return {"cleared": 1}

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission", return_value=True), \
			 patch.object(bv2, "sync_cancelled_payment_entry_links", side_effect=sync_side_effect) as sync, \
			 patch.object(bv2, "sync_cancelled_journal_entry_links") as sync_journal, \
			 patch.object(bv2, "_recompute_doc_status"), \
			 patch.object(bv2, "_refresh_saldo_fields"), \
			 patch.object(bv2, "_persist_saldo_fields"), \
			 patch.object(bv2, "_suggest_invoice_for_row", return_value=None):
			res = bv2.get_overview("IMP-OVERVIEW")

		sync.assert_called_once_with(import_name="IMP-OVERVIEW")
		sync_journal.assert_called_once_with(import_name="IMP-OVERVIEW")
		out = res["rows"][0]
		self.assertIsNone(out["paymentEntry"])
		self.assertIsNone(out["paymentDocument"])
		self.assertEqual(out["phase"], 3)
		self.assertEqual(out["rowStatus"], "phase3-open")

	def test_get_overview_syncs_cancelled_journal_entry_before_response(self):
		row = _OverviewRow()
		row.payment_entry = None
		row.payment_document_type = "Journal Entry"
		row.payment_document = "JE-CANCELLED"
		row.journal_entry = "JE-CANCELLED"
		doc = _OverviewDoc(row)

		def sync_side_effect(import_name=None, journal_entry_name=None):
			row.journal_entry = None
			row.payment_document = None
			row.payment_document_type = None
			row.row_status = None
			row.auto_match_message = (
				"Automatisch zurückgesetzt: Journal Entry JE-CANCELLED ist storniert."
			)
			return {"cleared": 1}

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission", return_value=True), \
			 patch.object(bv2, "sync_cancelled_payment_entry_links") as sync_payment, \
			 patch.object(bv2, "sync_cancelled_journal_entry_links", side_effect=sync_side_effect) as sync_journal, \
			 patch.object(bv2, "_recompute_doc_status"), \
			 patch.object(bv2, "_refresh_saldo_fields"), \
			 patch.object(bv2, "_persist_saldo_fields"), \
			 patch.object(bv2, "_suggest_invoice_for_row", return_value=None):
			res = bv2.get_overview("IMP-OVERVIEW")

		sync_payment.assert_called_once_with(import_name="IMP-OVERVIEW")
		sync_journal.assert_called_once_with(import_name="IMP-OVERVIEW")
		out = res["rows"][0]
		self.assertIsNone(out["journalEntry"])
		self.assertIsNone(out["paymentDocument"])
		self.assertEqual(out["phase"], 3)
		self.assertEqual(out["rowStatus"], "phase3-open")

	def test_get_overview_returns_outgoing_amounts_as_negative_and_counts_phases(self):
		incoming = _OverviewRow()
		incoming.name = "ROW-IN"
		incoming.betrag = 625.0
		incoming.richtung = "Eingang"
		incoming.payment_entry = None
		incoming.payment_document = None
		incoming.payment_document_type = None
		incoming.row_status = None

		outgoing = _OverviewRow()
		outgoing.name = "ROW-OUT"
		outgoing.betrag = 89.9
		outgoing.richtung = "Ausgang"
		outgoing.party_type = "Supplier"
		outgoing.party = "SUP-1"
		outgoing.bank_transaction = None
		outgoing.payment_entry = None
		outgoing.payment_document = None
		outgoing.payment_document_type = None
		outgoing.row_status = None

		done = _OverviewRow()
		done.name = "ROW-DONE"
		done.betrag = 100.0
		done.richtung = "Eingang"
		done.payment_entry = "PE-1"
		done.payment_document = "PE-1"
		done.payment_document_type = "Payment Entry"
		done.row_status = "success"

		doc = _OverviewDoc(incoming)
		doc.rows = [incoming, outgoing, done]

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission", return_value=True), \
			 patch.object(bv2, "sync_cancelled_payment_entry_links"), \
			 patch.object(bv2, "sync_cancelled_journal_entry_links"), \
			 patch.object(bv2, "_recompute_doc_status"), \
			 patch.object(bv2, "_refresh_saldo_fields"), \
			 patch.object(bv2, "_persist_saldo_fields"), \
			 patch.object(bv2, "_bank_account_iban", return_value="DE-BANK"), \
			 patch.object(bv2, "_suggest_invoice_for_row", return_value=None):
			res = bv2.get_overview("IMP-OVERVIEW")

		rows = {row["id"]: row for row in res["rows"]}
		self.assertEqual(rows["ROW-IN"]["betrag"], 625.0)
		self.assertEqual(rows["ROW-OUT"]["betrag"], -89.9)
		self.assertEqual(rows["ROW-DONE"]["betrag"], 100.0)
		self.assertEqual(res["phaseCounts"], {1: 0, 2: 1, 3: 1, 4: 1})
		self.assertEqual(rows["ROW-OUT"]["rowStatus"], "phase2-no-bt")
		self.assertEqual(rows["ROW-DONE"]["rowStatus"], "done")

	def test_get_overview_keeps_response_stable_when_invoice_suggestion_fails(self):
		row = _OverviewRow()
		row.payment_entry = None
		row.payment_document = None
		row.payment_document_type = None
		row.row_status = None
		doc = _OverviewDoc(row)

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission", return_value=True), \
			 patch.object(bv2, "sync_cancelled_payment_entry_links"), \
			 patch.object(bv2, "sync_cancelled_journal_entry_links"), \
			 patch.object(bv2, "_recompute_doc_status"), \
			 patch.object(bv2, "_refresh_saldo_fields"), \
			 patch.object(bv2, "_persist_saldo_fields"), \
			 patch.object(bv2, "_suggest_invoice_for_row", side_effect=Exception("matcher down")):
			res = bv2.get_overview("IMP-OVERVIEW")

		self.assertIsNone(res["rows"][0]["autoMatch"])
		self.assertEqual(res["rows"][0]["phase"], 3)
		self.assertEqual(res["rows"][0]["rowStatus"], "phase3-open")

	def test_get_overview_maps_mixed_error_existing_and_needs_review_rows(self):
		error_row = _OverviewRow()
		error_row.name = "ROW-ERROR"
		error_row.error = "Betrag fehlt"
		error_row.row_status = "failed"
		error_row.bank_transaction = None
		error_row.party_type = None
		error_row.party = None
		error_row.payment_entry = None
		error_row.payment_document = None
		error_row.payment_document_type = None

		existing_row = _OverviewRow()
		existing_row.name = "ROW-EXISTING"
		existing_row.row_status = "schon vorhanden"
		existing_row.payment_entry = None
		existing_row.payment_document = None
		existing_row.payment_document_type = None

		review_row = _OverviewRow()
		review_row.name = "ROW-REVIEW"
		review_row.row_status = "needs_review"
		review_row.payment_entry = None
		review_row.payment_document = None
		review_row.payment_document_type = None

		doc = _OverviewDoc(error_row)
		doc.rows = [error_row, existing_row, review_row]

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission", return_value=True), \
			 patch.object(bv2, "sync_cancelled_payment_entry_links"), \
			 patch.object(bv2, "sync_cancelled_journal_entry_links"), \
			 patch.object(bv2, "_recompute_doc_status"), \
			 patch.object(bv2, "_refresh_saldo_fields"), \
			 patch.object(bv2, "_persist_saldo_fields"), \
			 patch.object(bv2, "_bank_account_iban", return_value="DE-BANK"), \
			 patch.object(bv2, "_suggest_invoice_for_row", return_value=None):
			res = bv2.get_overview("IMP-OVERVIEW")

		rows = {row["id"]: row for row in res["rows"]}
		self.assertEqual(rows["ROW-ERROR"]["phase"], 3)
		self.assertEqual(rows["ROW-ERROR"]["rowStatus"], "error")
		self.assertEqual(rows["ROW-EXISTING"]["phase"], 4)
		self.assertEqual(rows["ROW-EXISTING"]["rowStatus"], "existing")
		self.assertEqual(rows["ROW-REVIEW"]["phase"], 3)
		self.assertEqual(rows["ROW-REVIEW"]["rowStatus"], "needs_review")
		self.assertEqual(res["phaseCounts"], {1: 0, 2: 0, 3: 2, 4: 1})


class TestSearchPartiesAndAccounts(unittest.TestCase):
	def test_search_parties_validates_party_type_before_query(self):
		with patch("frappe.throw", side_effect=frappe.ValidationError("bad party")), \
			 patch("frappe.get_list") as get_list, \
			 self.assertRaisesRegex(frappe.ValidationError, "bad party"):
			bv2.search_parties("User", "abc")

		get_list.assert_not_called()

	def test_search_parties_maps_titles_and_descriptions(self):
		rows = [
			frappe._dict(name="CUST-1", title="Max Mustermann"),
			frappe._dict(name="CUST-2", title="CUST-2"),
		]

		with patch("frappe.get_list", return_value=rows) as get_list:
			result = bv2.search_parties("Customer", "max")

		self.assertEqual(
			get_list.call_args.kwargs["or_filters"],
			[["name", "like", "%max%"], ["customer_name", "like", "%max%"]],
		)
		self.assertEqual(result["items"], [
			{"value": "CUST-1", "label": "Max Mustermann", "description": "CUST-1"},
			{"value": "CUST-2", "label": "CUST-2", "description": None},
		])

	def test_search_accounts_merges_cockpit_and_leaf_accounts_without_duplicates(self):
		cockpit_item = {
			"value": "4930 - Bankgebühren - HV",
			"label": "4930 Bankgebühren",
			"description": "Cockpit",
		}
		sql_rows = [
			frappe._dict(
				name="4930 - Bankgebühren - HV",
				account_number="4930",
				account_name="Bankgebühren",
				root_type="Expense",
				report_type="Profit and Loss",
			),
			frappe._dict(
				name="1800 - Bank - HV",
				account_number="1800",
				account_name="Bank",
				root_type="Asset",
				report_type="Balance Sheet",
			),
		]

		with patch(
			"hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit.autocomplete_konten",
			return_value=[cockpit_item],
		) as autocomplete, \
			 patch("frappe.db.sql", return_value=sql_rows) as sql:
			result = bv2.search_accounts("bank")

		autocomplete.assert_called_once_with(txt="bank", typ="alle")
		self.assertIn("name LIKE %s", sql.call_args.args[0])
		self.assertEqual(sql.call_args.args[1], ["%bank%", "%bank%", "%bank%"])
		self.assertEqual([item["value"] for item in result["items"]], [
			"4930 - Bankgebühren - HV",
			"1800 - Bank - HV",
		])
		self.assertEqual(result["items"][1]["label"], "1800 Bank")
		self.assertEqual(result["items"][1]["description"], "Asset / Balance Sheet")
