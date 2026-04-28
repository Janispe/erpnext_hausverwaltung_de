# See license.txt

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi


class TestBankauszugImport(FrappeTestCase):
    class _FakeRow:
        def __init__(
            self,
            *,
            name: str,
            auftraggeber: str = "",
            verwendungszweck: str = "",
            iban: str = "",
            error: str | None = None,
        ):
            self.name = name
            self.auftraggeber = auftraggeber
            self.verwendungszweck = verwendungszweck
            self.iban = iban
            self.error = error
            self.party_type = None
            self.party = None

    class _FakeDoc:
        def __init__(self, name: str, rows):
            self.name = name
            self._rows = rows
            self.saved = False
            self.ignore_permissions = None

        def get(self, key):
            if key == "rows":
                return self._rows
            return None

        def save(self, ignore_permissions=False):
            self.saved = True
            self.ignore_permissions = ignore_permissions

    class _FakeBT:
        def __init__(self, name: str, party_type=None, party=None):
            self.name = name
            self.party_type = party_type
            self.party = party
            self.values = {}

        def db_set(self, fieldname, value, update_modified=False):
            self.values[fieldname] = value
            setattr(self, fieldname, value)

    def test_create_party_and_bank_for_row_updates_row_and_returns_payload(self):
        row = self._FakeRow(name="ROW-1", auftraggeber="Max Mustermann", iban="DE123")
        doc = self._FakeDoc("IMP-1", [row])
        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "_create_party_if_missing", return_value=("Max Mustermann", True)), \
             patch.object(bi, "_get_or_create_party_bank_account", return_value=("BA-1", True)):
            res = bi.create_party_and_bank_for_row("IMP-1", "ROW-1", "Customer", None)

        self.assertEqual(res["party_type"], "Customer")
        self.assertEqual(res["party"], "Max Mustermann")
        self.assertEqual(res["bank_account"], "BA-1")
        self.assertTrue(res["party_created"])
        self.assertTrue(res["bank_account_created"])
        self.assertEqual(row.party_type, "Customer")
        self.assertEqual(row.party, "Max Mustermann")
        self.assertTrue(doc.saved)
        self.assertTrue(doc.ignore_permissions)

    def test_create_party_uses_verwendungszweck_as_name_fallback(self):
        row = self._FakeRow(name="ROW-2", auftraggeber="", verwendungszweck="Miete Januar", iban="DE456")
        doc = self._FakeDoc("IMP-2", [row])
        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "_get_or_create_party_bank_account", return_value=(None, False)), \
             patch.object(bi, "_create_party_if_missing", return_value=("Miete Januar", True)) as create_party:
            bi.create_party_and_bank_for_row("IMP-2", "ROW-2", "Supplier", None)

        create_party.assert_called_once_with("Supplier", "Miete Januar")
        self.assertEqual(row.party_type, "Supplier")
        self.assertEqual(row.party, "Miete Januar")

    def test_create_party_requires_valid_party_type(self):
        row = self._FakeRow(name="ROW-3", auftraggeber="Test")
        doc = self._FakeDoc("IMP-3", [row])

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "throw", side_effect=_throw):
            with self.assertRaisesRegex(Exception, "Party Typ muss Customer oder Supplier sein."):
                bi.create_party_and_bank_for_row("IMP-3", "ROW-3", "Employee", None)

    def test_create_party_requires_name_if_no_fallback(self):
        row = self._FakeRow(name="ROW-4", auftraggeber="", verwendungszweck="", iban="DE789")
        doc = self._FakeDoc("IMP-4", [row])

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "throw", side_effect=_throw):
            with self.assertRaisesRegex(Exception, "Kein Name vorhanden. Bitte Name im Dialog eingeben."):
                bi.create_party_and_bank_for_row("IMP-4", "ROW-4", "Customer", None)

    def test_relink_all_updates_bt_when_iban_mapping_found(self):
        row = self._FakeRow(name="ROW-A", iban="DE1")
        row.bank_transaction = "BT-1"
        doc = self._FakeDoc("IMP-A", [row])
        bt = self._FakeBT("BT-1")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-1")):
            res = bi.relink_parties_for_all_rows("IMP-A")

        self.assertEqual(res["updated"], 1)
        self.assertEqual(bt.party_type, "Customer")
        self.assertEqual(bt.party, "CUST-1")
        self.assertEqual(row.party_type, "Customer")
        self.assertEqual(row.party, "CUST-1")

    def test_relink_all_overwrites_existing_bt_party(self):
        row = self._FakeRow(name="ROW-B", iban="DE2")
        row.bank_transaction = "BT-2"
        doc = self._FakeDoc("IMP-B", [row])
        bt = self._FakeBT("BT-2", party_type="Supplier", party="SUP-OLD")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-NEW")):
            res = bi.relink_parties_for_all_rows("IMP-B", overwrite=1)

        self.assertEqual(res["updated"], 1)
        self.assertEqual(bt.party_type, "Customer")
        self.assertEqual(bt.party, "CUST-NEW")
        self.assertEqual(res["changes"][0]["from_party"], "SUP-OLD")

    def test_relink_all_skips_without_bank_transaction(self):
        row = self._FakeRow(name="ROW-C", iban="DE3")
        row.bank_transaction = None
        doc = self._FakeDoc("IMP-C", [row])
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta):
            res = bi.relink_parties_for_all_rows("IMP-C")

        self.assertEqual(res["processed"], 1)
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(res["updated"], 0)

    def test_relink_all_fallbacks_to_row_party_if_no_iban_mapping(self):
        row = self._FakeRow(name="ROW-D", iban="DE4")
        row.bank_transaction = "BT-4"
        row.party_type = "Supplier"
        row.party = "SUP-1"
        doc = self._FakeDoc("IMP-D", [row])
        bt = self._FakeBT("BT-4")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_get_party_by_iban", return_value=None):
            res = bi.relink_parties_for_all_rows("IMP-D")

        self.assertEqual(res["updated"], 1)
        self.assertEqual(bt.party_type, "Supplier")
        self.assertEqual(bt.party, "SUP-1")

    def test_relink_all_reports_changes_and_counts(self):
        row1 = self._FakeRow(name="ROW-E1", iban="DE5")
        row1.bank_transaction = "BT-5-1"
        row2 = self._FakeRow(name="ROW-E2", iban="DE6")
        row2.bank_transaction = "BT-5-2"
        row3 = self._FakeRow(name="ROW-E3", iban="")
        row3.bank_transaction = None
        doc = self._FakeDoc("IMP-E", [row1, row2, row3])
        bt1 = self._FakeBT("BT-5-1", party_type="Customer", party="C1")
        bt2 = self._FakeBT("BT-5-2", party_type="Supplier", party="S1")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction" and name == "BT-5-1":
                return bt1
            if doctype == "Bank Transaction" and name == "BT-5-2":
                return bt2
            raise AssertionError("unexpected doctype")

        def _by_iban(iban):
            if iban == "DE5":
                return ("Customer", "C1")
            if iban == "DE6":
                return ("Customer", "C2")
            return None

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_get_party_by_iban", side_effect=_by_iban):
            res = bi.relink_parties_for_all_rows("IMP-E")

        self.assertEqual(res["processed"], 3)
        self.assertEqual(res["updated"], 1)
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(len(res["changes"]), 1)
        self.assertEqual(res["changes"][0]["bank_transaction"], "BT-5-2")

    def test_relink_all_handles_per_row_errors_without_abort(self):
        row1 = self._FakeRow(name="ROW-F1", iban="DE7")
        row1.bank_transaction = "BT-ERR"
        row2 = self._FakeRow(name="ROW-F2", iban="DE8")
        row2.bank_transaction = "BT-OK"
        doc = self._FakeDoc("IMP-F", [row1, row2])
        bt2 = self._FakeBT("BT-OK")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction" and name == "BT-ERR":
                raise Exception("kaputt")
            if doctype == "Bank Transaction" and name == "BT-OK":
                return bt2
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi.frappe, "get_traceback", return_value="trace"), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "C-OK")):
            res = bi.relink_parties_for_all_rows("IMP-F")

        self.assertEqual(res["updated"], 1)
        self.assertEqual(len(res["errors"]), 1)

    def test_relink_all_uses_reference_when_bank_transaction_missing(self):
        row = self._FakeRow(name="ROW-I", iban="DE11")
        row.bank_transaction = None
        row.reference = "BT-I"
        doc = self._FakeDoc("IMP-I", [row])
        bt = self._FakeBT("BT-I")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", return_value=("Supplier", "SUP-I")):
            res = bi.relink_parties_for_all_rows("IMP-I")

        self.assertEqual(res["updated"], 1)
        self.assertEqual(bt.party_type, "Supplier")
        self.assertEqual(bt.party, "SUP-I")

    def test_apply_party_to_row_and_relink_updates_row_from_saved_doc(self):
        row = self._FakeRow(name="ROW-G", iban="DE9")
        row.bank_transaction = "BT-G"
        doc = self._FakeDoc("IMP-G", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "_update_bt_party_from_row", return_value={"updated": True}), \
             patch.object(bi, "_get_party_by_iban", return_value=None):
            res = bi.apply_party_to_row_and_relink("IMP-G", "ROW-G", "Customer", "CUST-G")

        self.assertEqual(row.party_type, "Customer")
        self.assertEqual(row.party, "CUST-G")
        self.assertTrue(doc.saved)
        self.assertEqual(res["row_party"], "CUST-G")
        self.assertTrue(res["relink"]["updated"])

    def test_apply_party_to_row_and_relink_accepts_eigentuemer(self):
        row = self._FakeRow(name="ROW-GE", iban="DE9E")
        row.bank_transaction = "BT-GE"
        doc = self._FakeDoc("IMP-GE", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "_update_bt_party_from_row", return_value={"updated": True}), \
             patch.object(bi, "_get_party_by_iban", return_value=None):
            res = bi.apply_party_to_row_and_relink("IMP-GE", "ROW-GE", "Eigentuemer", "EIG-1")

        self.assertEqual(row.party_type, "Eigentuemer")
        self.assertEqual(row.party, "EIG-1")
        self.assertTrue(doc.saved)
        self.assertEqual(res["row_party_type"], "Eigentuemer")
        self.assertEqual(res["row_party"], "EIG-1")

    def test_apply_party_to_row_and_relink_prefers_iban_mapping(self):
        row = self._FakeRow(name="ROW-H", iban="DE10")
        row.bank_transaction = "BT-H"
        row.party_type = "Customer"
        row.party = "CUST-OLD"
        doc = self._FakeDoc("IMP-H", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "_update_bt_party_from_row", return_value={"updated": False, "reason": "unchanged"}), \
             patch.object(bi, "_get_party_by_iban", return_value=("Supplier", "SUP-H")):
            res = bi.apply_party_to_row_and_relink("IMP-H", "ROW-H", "Customer", "CUST-H")

        self.assertEqual(row.party_type, "Supplier")
        self.assertEqual(row.party, "SUP-H")
        self.assertTrue(doc.saved)
        self.assertEqual(res["row_party_type"], "Supplier")

    def test_create_bank_transactions_blocks_when_any_row_has_no_party(self):
        row_ok = self._FakeRow(name="ROW-J1", iban="DE12")
        row_bad = self._FakeRow(name="ROW-J2", iban="")
        doc = self._FakeDoc("IMP-J", [row_ok, row_bad])

        class _BankAccount:
            is_company_account = 1

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "get_cached_doc", return_value=_BankAccount()), \
             patch.object(bi.frappe, "throw", side_effect=_throw), \
             patch.object(bi, "_resolve_row_party_for_validation", side_effect=[("Customer", "C1"), None]):
            with self.assertRaisesRegex(Exception, "Zeilen ohne Party"):
                bi.create_bank_transactions("IMP-J")

    def test_create_bank_transactions_blocks_even_if_row_has_error_or_existing_bt(self):
        row_err = self._FakeRow(name="ROW-K1", iban="", error="Ungültig")
        row_err.bank_transaction = "BT-K1"
        row_ok = self._FakeRow(name="ROW-K2", iban="DE13")
        doc = self._FakeDoc("IMP-K", [row_err, row_ok])

        class _BankAccount:
            is_company_account = 1

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "get_cached_doc", return_value=_BankAccount()), \
             patch.object(bi.frappe, "throw", side_effect=_throw), \
             patch.object(bi, "_resolve_row_party_for_validation", side_effect=[None, ("Supplier", "S1")]):
            with self.assertRaisesRegex(Exception, "Zeilen ohne Party"):
                bi.create_bank_transactions("IMP-K")

    def test_create_bank_transactions_allows_when_party_resolved_via_iban(self):
        row = self._FakeRow(name="ROW-L1", iban="DE14")
        row.bank_transaction = "BT-L1"
        doc = self._FakeDoc("IMP-L", [row])

        class _BankAccount:
            is_company_account = 1

        meta = type("M", (), {"fields": [], "is_submittable": 0})()

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "get_cached_doc", return_value=_BankAccount()), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_resolve_row_party_for_validation", return_value=("Customer", "C2")), \
             patch.object(bi.frappe, "get_all", return_value=[]):
            res = bi.create_bank_transactions("IMP-L")

        self.assertIn("created", res)
        self.assertEqual(res["errors"], [])

    def test_block_message_contains_row_details(self):
        row = self._FakeRow(name="ROW-M1", iban="", verwendungszweck="Test")
        doc = self._FakeDoc("IMP-M", [row])

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "throw", side_effect=_throw), \
             patch.object(bi, "_resolve_row_party_for_validation", return_value=None):
            with self.assertRaises(Exception) as exc:
                bi._throw_if_missing_party_rows(doc)

        msg = str(exc.exception)
        self.assertIn("ROW-M1", msg)
        self.assertIn("Grund", msg)
        self.assertIn("Betrag", msg)

    def test_block_message_truncates_long_list(self):
        rows = [self._FakeRow(name=f"ROW-N{i}", iban="") for i in range(15)]
        doc = self._FakeDoc("IMP-N", rows)

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "throw", side_effect=_throw), \
             patch.object(bi, "_resolve_row_party_for_validation", return_value=None):
            with self.assertRaises(Exception) as exc:
                bi._throw_if_missing_party_rows(doc)

        msg = str(exc.exception)
        self.assertIn("... und 3 weitere", msg)

    def test_resolve_row_party_accepts_eigentuemer(self):
        row = self._FakeRow(name="ROW-O", iban="")
        row.party_type = "Eigentuemer"
        row.party = "EIG-1"

        with patch.object(bi, "_get_party_by_iban", return_value=None):
            res = bi._resolve_row_party(row)

        self.assertEqual(res, ("Eigentuemer", "EIG-1"))

    def test_collect_rows_missing_party_does_not_mark_eigentuemer_invalid(self):
        row = self._FakeRow(name="ROW-P", iban="")
        row.party_type = "Eigentuemer"
        row.party = "EIG-2"
        doc = self._FakeDoc("IMP-P", [row])

        with patch.object(bi, "_resolve_row_party_for_validation", return_value=None):
            missing = bi._collect_rows_missing_party(doc)

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["reason"], "no_party_mapping")
