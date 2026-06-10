# See license.txt

import unittest
from unittest.mock import patch

import frappe
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi
from hausverwaltung.hausverwaltung.page.bankimport_v2 import bankimport_v2 as bv2


class TestBankauszugImport(unittest.TestCase):
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
            self.bank_transaction = None
            self.reference = None
            self.buchungstag = "2026-01-15"
            self.idx = 1
            self.betrag = 42
            self.richtung = "Eingang"
            self.currency = "EUR"
            self.payment_entry = None
            self.journal_entry = None
            self.payment_document_type = None
            self.payment_document = None
            self.row_status = None
            self.auto_match_message = None

        def get(self, key, default=None):
            return getattr(self, key, default)

        def db_set(self, fieldname, value):
            setattr(self, fieldname, value)

    class _FakeDoc:
        def __init__(self, name: str, rows):
            self.name = name
            self._rows = rows
            self.rows = rows
            self.bank_account = "BANK-1"
            self.saved = False
            self.ignore_permissions = None

        def get(self, key, default=None):
            if key == "rows":
                return self._rows
            return getattr(self, key, default)

        def save(self, ignore_permissions=False):
            self.saved = True
            self.ignore_permissions = ignore_permissions

        def reload(self):
            return None

    class _FakeBT:
        def __init__(self, name: str, party_type=None, party=None):
            self.name = name
            self.party_type = party_type
            self.party = party
            self.bank_account = "BANK-1"
            self.values = {}
            self.inserted = False
            self.submitted = False
            self.deleted = False

        def db_set(self, fieldname, value, update_modified=False):
            self.values[fieldname] = value
            setattr(self, fieldname, value)

        def set(self, fieldname, value):
            self.values[fieldname] = value
            setattr(self, fieldname, value)

        def insert(self, ignore_permissions=False):
            self.inserted = True
            self.ignore_permissions = ignore_permissions

        def submit(self):
            self.submitted = True

        def delete(self, ignore_permissions=False):
            self.deleted = True

    class _FakeMeta:
        def __init__(self, fieldnames, is_submittable=0):
            self.fields = [type("F", (), {"fieldname": fieldname, "label": fieldname})() for fieldname in fieldnames]
            self.is_submittable = is_submittable

    def test_get_party_by_iban_returns_single_unique_party(self):
        with patch.object(
            bi.frappe,
            "get_all",
            return_value=[
                {"party_type": "Customer", "party": "CUST-1"},
                {"party_type": "Customer", "party": "CUST-1"},
            ],
        ):
            res = bi._get_party_by_iban("DE123")

        self.assertEqual(res, ("Customer", "CUST-1"))

    def test_get_party_by_iban_leaves_ambiguous_parties_unresolved(self):
        with patch.object(
            bi.frappe,
            "get_all",
            return_value=[
                {"party_type": "Customer", "party": "CUST-1"},
                {"party_type": "Customer", "party": "CUST-2"},
            ],
        ):
            res = bi._get_party_by_iban("DE123")

        self.assertIsNone(res)

    def test_create_party_and_bank_for_row_updates_row_and_returns_payload(self):
        row = self._FakeRow(name="ROW-1", auftraggeber="Max Mustermann", iban="DE123")
        doc = self._FakeDoc("IMP-1", [row])
        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "_create_party_if_missing", return_value=("Max Mustermann", True)), \
             patch.object(bi, "_get_or_create_party_bank_account", return_value=("BA-1", True)), \
             patch.object(
                 bi,
                 "_link_customer_bank_account_to_mietvertraege",
                 return_value={"updated": 1, "unchanged": 0, "errors": []},
             ) as link_contract:
            res = bi.create_party_and_bank_for_row("IMP-1", "ROW-1", "Customer", None)

        self.assertEqual(res["party_type"], "Customer")
        self.assertEqual(res["party"], "Max Mustermann")
        self.assertEqual(res["bank_account"], "BA-1")
        self.assertEqual(res["mietvertrag_links"]["updated"], 1)
        link_contract.assert_called_once_with("Max Mustermann", "BA-1")
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

    def test_link_customer_bank_account_adds_missing_mietvertrag_kontoverbindung(self):
        class _FakePartner:
            mieter = "CONTACT-1"

        class _FakeMietvertrag:
            def __init__(self):
                self.name = "MV-1"
                self.kontoverbindungen = []
                self.mieter = [_FakePartner()]
                self.saved = False
                self.ignore_permissions = None

            def get(self, key):
                return getattr(self, key)

            def append(self, key, value):
                self.kontoverbindungen.append(type("Link", (), value)())

            def save(self, ignore_permissions=False):
                self.saved = True
                self.ignore_permissions = ignore_permissions

        mv = _FakeMietvertrag()

        def _get_all(doctype, **kwargs):
            if doctype == "Mietvertrag":
                return [{"name": "MV-1"}]
            if doctype == "Dynamic Link":
                return ["CONTACT-1"]
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_all", side_effect=_get_all), \
             patch.object(bi.frappe, "get_doc", return_value=mv):
            res = bi._link_customer_bank_account_to_mietvertraege("CUST-1", "BA-1")

        self.assertEqual(res["updated"], 1)
        self.assertEqual(res["unchanged"], 0)
        self.assertEqual(mv.kontoverbindungen[0].bankkonto, "BA-1")
        self.assertEqual(mv.kontoverbindungen[0].kontakt, "CONTACT-1")
        self.assertTrue(mv.saved)
        self.assertTrue(mv.ignore_permissions)

    def test_link_customer_bank_account_skips_existing_mietvertrag_kontoverbindung(self):
        class _FakeLink:
            bankkonto = "BA-1"

        class _FakeMietvertrag:
            def __init__(self):
                self.name = "MV-1"
                self.kontoverbindungen = [_FakeLink()]
                self.mieter = []

            def get(self, key):
                return getattr(self, key)

            def save(self, ignore_permissions=False):
                raise AssertionError("unchanged contract should not be saved")

        with patch.object(bi.frappe, "get_all", return_value=[{"name": "MV-1"}]), \
             patch.object(bi.frappe, "get_doc", return_value=_FakeMietvertrag()):
            res = bi._link_customer_bank_account_to_mietvertraege("CUST-1", "BA-1")

        self.assertEqual(res["updated"], 0)
        self.assertEqual(res["unchanged"], 1)

    def test_create_party_requires_valid_party_type(self):
        row = self._FakeRow(name="ROW-3", auftraggeber="Test")
        doc = self._FakeDoc("IMP-3", [row])

        def _throw(msg):
            raise Exception(msg)

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe, "throw", side_effect=_throw):
            with self.assertRaisesRegex(Exception, "Party Typ muss Mieter oder Supplier sein."):
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
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-1")), \
             patch.object(bi, "_recompute_doc_status"):
            res = bi.relink_parties_for_all_rows("IMP-A")

        self.assertEqual(res["updated"], 1)
        self.assertEqual(bt.party_type, "Customer")
        self.assertEqual(bt.party, "CUST-1")
        self.assertEqual(row.party_type, "Customer")
        self.assertEqual(row.party, "CUST-1")

    def test_find_existing_bank_transaction_rejects_same_amount_different_purpose(self):
        meta = type(
            "M",
            (),
            {
                "fields": [
                    type("F", (), {"fieldname": "date"})(),
                    type("F", (), {"fieldname": "deposit"})(),
                    type("F", (), {"fieldname": "withdrawal"})(),
                    type("F", (), {"fieldname": "bank_party_iban"})(),
                    type("F", (), {"fieldname": "description"})(),
                ]
            },
        )()

        with patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(
                 bi.frappe,
                 "get_all",
                 return_value=[{"name": "BT-1", "description": "Neue Gesamtmiete, Mai 2026"}],
             ):
            res = bi._find_existing_bank_transaction(
                bank_account="BANK-1",
                buchungstag="2026-04-10",
                betrag=625,
                richtung="Eingang",
                iban="DE77100900002807151005",
                verwendungszweck="Neue Gesamtmiete, April 2026",
            )

        self.assertIsNone(res)

    def test_find_existing_bank_transaction_accepts_same_purpose(self):
        meta = type(
            "M",
            (),
            {
                "fields": [
                    type("F", (), {"fieldname": "date"})(),
                    type("F", (), {"fieldname": "deposit"})(),
                    type("F", (), {"fieldname": "withdrawal"})(),
                    type("F", (), {"fieldname": "bank_party_iban"})(),
                    type("F", (), {"fieldname": "description"})(),
                ]
            },
        )()

        with patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(
                 bi.frappe,
                 "get_all",
                 return_value=[{"name": "BT-1", "description": "Neue Gesamtmiete, April 2026"}],
             ):
            res = bi._find_existing_bank_transaction(
                bank_account="BANK-1",
                buchungstag="2026-04-10",
                betrag=625,
                richtung="Eingang",
                iban="DE77100900002807151005",
                verwendungszweck="Neue Gesamtmiete, April 2026",
            )

        self.assertEqual(res, "BT-1")

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
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-NEW")), \
             patch.object(bi, "_recompute_doc_status"):
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
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_get_party_by_iban", return_value=None), \
             patch.object(bi, "_recompute_doc_status"):
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
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", return_value=None), \
             patch.object(bi, "_recompute_doc_status"):
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
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", side_effect=_by_iban), \
             patch.object(bi, "_recompute_doc_status"):
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
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "C-OK")), \
             patch.object(bi, "_recompute_doc_status"):
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
             patch.object(bi, "_get_party_by_iban", return_value=("Supplier", "SUP-I")), \
             patch.object(bi, "_recompute_doc_status"):
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

    def test_change_row_party_resets_existing_booking_before_changing_party(self):
        row = self._FakeRow(name="ROW-CHG", iban="DE10")
        row.party_type = "Customer"
        row.party = "CUST-OLD"
        row.bank_transaction = "BT-CHG"
        row.payment_entry = "PE-OLD"
        doc = self._FakeDoc("IMP-CHG", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "reset_row_booking", return_value={"ok": True, "reset": True}) as reset, \
             patch.object(bi, "_set_bt_party", return_value={"updated": True, "bank_transaction": "BT-CHG"}) as set_bt, \
             patch.object(bi, "_auto_create_transaction_for_ready_row", return_value={"attempted": 1, "created": ["BT-NEW"], "errors": []}) as auto_create, \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            res = bi.change_row_party("IMP-CHG", "ROW-CHG", party_type="Supplier", party="SUP-NEW")

        reset.assert_called_once_with("IMP-CHG", "ROW-CHG")
        set_bt.assert_called_once_with(row, "Supplier", "SUP-NEW", clear=False)
        auto_create.assert_called_once_with("IMP-CHG", "ROW-CHG")
        recompute.assert_called_once_with("IMP-CHG")
        refresh.assert_called_once_with("IMP-CHG")
        self.assertEqual(row.party_type, "Supplier")
        self.assertEqual(row.party, "SUP-NEW")
        self.assertEqual(row.auto_match_message, "Partei geändert: Supplier SUP-NEW")
        self.assertEqual(res["old_party"], "CUST-OLD")
        self.assertEqual(res["row_party"], "SUP-NEW")
        self.assertTrue(doc.saved)

    def test_change_row_party_clear_removes_party_and_does_not_auto_create_transaction(self):
        row = self._FakeRow(name="ROW-CLEAR", iban="DE11")
        row.party_type = "Customer"
        row.party = "CUST-OLD"
        row.bank_transaction = "BT-CLEAR"
        doc = self._FakeDoc("IMP-CLEAR", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi, "reset_row_booking", return_value={"ok": True, "reset": False}), \
             patch.object(bi, "_set_bt_party", return_value={"updated": True, "bank_transaction": "BT-CLEAR"}) as set_bt, \
             patch.object(bi, "_auto_create_transaction_for_ready_row") as auto_create, \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party("IMP-CLEAR", "ROW-CLEAR", clear_party=1)

        set_bt.assert_called_once_with(row, None, None, clear=True)
        auto_create.assert_not_called()
        self.assertIsNone(row.party_type)
        self.assertIsNone(row.party)
        self.assertEqual(row.auto_match_message, "Partei entfernt.")
        self.assertEqual(res["auto_create"], {"attempted": 0, "created": [], "errors": []})

    def test_change_row_party_propagates_same_unique_iban_only_to_unbooked_rows(self):
        target = self._FakeRow(name="ROW-TARGET", iban="DE 12")
        target.party_type = "Customer"
        target.party = "CUST-OLD"
        target.bank_transaction = "BT-TARGET"
        same_open = self._FakeRow(name="ROW-SAME-OPEN", iban="DE12")
        same_open.bank_transaction = "BT-SAME"
        same_booked = self._FakeRow(name="ROW-SAME-BOOKED", iban="DE12")
        same_booked.payment_entry = "PE-BOOKED"
        different = self._FakeRow(name="ROW-DIFF", iban="DE99")
        doc = self._FakeDoc("IMP-PROP", [target, same_open, same_booked, different])

        def _set_bt(row, party_type, party, clear=False):
            return {"updated": True, "bank_transaction": row.bank_transaction}

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "reset_row_booking", return_value={"ok": True, "reset": False}), \
             patch.object(bi, "_set_bt_party", side_effect=_set_bt), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-NEW")), \
             patch.object(bi, "_auto_create_transaction_for_ready_row", return_value={"attempted": 0, "created": [], "errors": []}), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party(
                "IMP-PROP",
                "ROW-TARGET",
                party_type="Customer",
                party="CUST-NEW",
                propagate_same_iban=1,
            )

        self.assertEqual(same_open.party_type, "Customer")
        self.assertEqual(same_open.party, "CUST-NEW")
        self.assertIsNone(same_booked.party)
        self.assertIsNone(different.party)
        self.assertEqual(res["propagated_rows"], [
            {"row": "ROW-SAME-OPEN", "bank_transaction": "BT-SAME", "bt_updated": True}
        ])

    def test_change_row_party_skips_propagation_when_iban_mapping_is_ambiguous(self):
        target = self._FakeRow(name="ROW-TARGET", iban="DE12")
        same_open = self._FakeRow(name="ROW-SAME", iban="DE12")
        doc = self._FakeDoc("IMP-AMB", [target, same_open])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "reset_row_booking", return_value={"ok": True, "reset": False}), \
             patch.object(bi, "_set_bt_party", return_value={"updated": False}), \
             patch.object(bi, "_get_party_by_iban", return_value=None), \
             patch.object(bi, "_auto_create_transaction_for_ready_row", return_value={"attempted": 0, "created": [], "errors": []}), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party(
                "IMP-AMB",
                "ROW-TARGET",
                party_type="Customer",
                party="CUST-NEW",
                propagate_same_iban=1,
            )

        self.assertIsNone(same_open.party)
        self.assertEqual(res["propagated_rows"], [])
        self.assertEqual(res["propagation_skipped"], "iban_not_unique")

    def test_change_row_party_update_iban_mapping_unlinks_old_and_links_new_bank_account(self):
        row = self._FakeRow(name="ROW-IBAN", iban="DE13")
        row.party_type = "Customer"
        row.party = "CUST-OLD"
        doc = self._FakeDoc("IMP-IBAN", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "reset_row_booking", return_value={"ok": True, "reset": False}), \
             patch.object(bi, "unlink_party_bank_account_for_row", return_value={"updated": 1, "bank_accounts": ["BA-OLD"]}) as unlink, \
             patch.object(bi, "_get_or_create_party_bank_account", return_value=("BA-NEW", True)) as link, \
             patch.object(bi, "_link_customer_bank_account_to_mietvertraege", return_value={"updated": 2, "unchanged": 0, "errors": []}) as link_mv, \
             patch.object(bi, "_set_bt_party", return_value={"updated": False}), \
             patch.object(bi, "_auto_create_transaction_for_ready_row", return_value={"attempted": 0, "created": [], "errors": []}), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party(
                "IMP-IBAN",
                "ROW-IBAN",
                party_type="Customer",
                party="CUST-NEW",
                update_iban_mapping=1,
            )

        unlink.assert_called_once_with(row, "Customer", "CUST-OLD")
        link.assert_called_once_with(party_type="Customer", party="CUST-NEW", iban="DE13")
        link_mv.assert_called_once_with("CUST-NEW", "BA-NEW")
        self.assertEqual(res["bank_account_unlink"]["bank_accounts"], ["BA-OLD"])
        self.assertEqual(res["bank_account_link"]["bank_account"], "BA-NEW")
        self.assertEqual(res["bank_account_link"]["mietvertrag_links"]["updated"], 2)

    def test_create_bank_transactions_returns_warning_for_missing_party_without_creating(self):
        row = self._FakeRow(name="ROW-MISS", iban="DE14")
        doc = self._FakeDoc("IMP-MISS", [row])
        bank_account = type("BankAccount", (), {"is_company_account": 1})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return bank_account
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "new_doc") as new_doc:
            res = bi.create_bank_transactions("IMP-MISS", allow_missing_party=0)

        new_doc.assert_not_called()
        self.assertEqual(res["created"], [])
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["warning"]["missing_count"], 1)
        self.assertIn("Zeile ROW-MISS", res["warning"]["preview_lines"][0])

    def test_create_bank_transactions_allows_missing_party_and_creates_neutral_bank_transaction(self):
        row = self._FakeRow(name="ROW-NEUTRAL", iban="DE15", verwendungszweck="Bankgebühr")
        doc = self._FakeDoc("IMP-NEUTRAL", [row])
        bank_account = type("BankAccount", (), {"is_company_account": 1})()
        bt = self._FakeBT("BT-NEUTRAL")
        meta = self._FakeMeta(
            ["date", "deposit", "withdrawal", "description", "party_type", "party", "status", "unallocated_amount"]
        )

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return bank_account
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi.frappe, "new_doc", return_value=bt), \
             patch.object(bi.frappe.db, "get_single_value", return_value=None), \
             patch.object(bi, "_find_existing_bank_transaction", return_value=None), \
             patch.object(bi, "_get_party_by_iban", return_value=None), \
             patch("hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction", return_value={"matched": False, "reason": "no_party", "message": "Keine Party"}), \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_recompute_doc_status"):
            res = bi.create_bank_transactions("IMP-NEUTRAL", allow_missing_party=1)

        self.assertEqual(res["created"], ["BT-NEUTRAL"])
        self.assertEqual(res["created_without_party"], 1)
        self.assertEqual(row.bank_transaction, "BT-NEUTRAL")
        self.assertEqual(row.row_status, "success")
        self.assertIsNone(getattr(bt, "party", None))
        self.assertEqual(bt.description, "Bankgebühr")
        self.assertTrue(bt.inserted)

    def test_create_bank_transactions_links_duplicate_instead_of_creating_new_transaction(self):
        row = self._FakeRow(name="ROW-DUP", iban="DE16")
        doc = self._FakeDoc("IMP-DUP", [row])
        bank_account = type("BankAccount", (), {"is_company_account": 1})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return bank_account
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe.db, "get_single_value", return_value=None), \
             patch.object(bi, "_build_missing_party_warning_payload", return_value=None), \
             patch.object(bi, "_find_existing_bank_transaction", return_value="BT-EXISTING"), \
             patch.object(bi.frappe, "new_doc") as new_doc, \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_recompute_doc_status"):
            res = bi.create_bank_transactions("IMP-DUP")

        new_doc.assert_not_called()
        self.assertEqual(res["created"], [])
        self.assertEqual(row.bank_transaction, "BT-EXISTING")
        self.assertEqual(row.reference, "BT-EXISTING")
        self.assertEqual(row.row_status, "schon vorhanden")

    def test_create_bank_transactions_skips_rows_before_configured_start_date(self):
        row = self._FakeRow(name="ROW-OLD", iban="DE17")
        row.party_type = "Customer"
        row.party = "CUST-1"
        row.buchungstag = "2026-01-01"
        doc = self._FakeDoc("IMP-OLD", [row])
        bank_account = type("BankAccount", (), {"is_company_account": 1})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return bank_account
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe.db, "get_single_value", return_value="2026-02-01"), \
             patch.object(bi, "_build_missing_party_warning_payload", return_value=None), \
             patch.object(bi.frappe, "new_doc") as new_doc, \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_recompute_doc_status"):
            res = bi.create_bank_transactions("IMP-OLD")

        new_doc.assert_not_called()
        self.assertEqual(res["skipped_before_cutoff"], 1)
        self.assertEqual(res["cutoff_date"], "2026-02-01")
        self.assertEqual(row.row_status, "vor Start-Datum")

    def test_create_bank_transactions_marks_error_rows_failed_and_continues_with_other_rows(self):
        bad = self._FakeRow(name="ROW-BAD", error="Ungültiges Datum")
        good = self._FakeRow(name="ROW-GOOD", iban="DE18")
        good.party_type = "Customer"
        good.party = "CUST-1"
        doc = self._FakeDoc("IMP-MIX", [bad, good])
        bank_account = type("BankAccount", (), {"is_company_account": 1})()
        bt = self._FakeBT("BT-GOOD")
        meta = self._FakeMeta(["date", "deposit", "withdrawal", "description", "party_type", "party"])

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return bank_account
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi.frappe, "new_doc", return_value=bt), \
             patch.object(bi.frappe.db, "get_single_value", return_value=None), \
             patch.object(bi, "_build_missing_party_warning_payload", return_value=None), \
             patch.object(bi, "_find_existing_bank_transaction", return_value=None), \
             patch("hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction", return_value={"matched": False, "reason": "no_open_invoices", "message": "Keine Rechnung"}), \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_recompute_doc_status"):
            res = bi.create_bank_transactions("IMP-MIX")

        self.assertEqual(bad.row_status, "failed")
        self.assertEqual(res["errors"], [{"row": "ROW-BAD", "error": "Ungültiges Datum"}])
        self.assertEqual(res["created"], ["BT-GOOD"])
        self.assertEqual(good.row_status, "success")

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

    def test_change_row_party_without_bt_updates_row(self):
        row = self._FakeRow(name="ROW-CHANGE-1", iban="")
        doc = self._FakeDoc("IMP-CHANGE-1", [row])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party("IMP-CHANGE-1", "ROW-CHANGE-1", "Customer", "CUST-1")

        self.assertTrue(res["ok"])
        self.assertEqual(row.party_type, "Customer")
        self.assertEqual(row.party, "CUST-1")
        self.assertEqual(res["bank_transaction"]["reason"], "no_bank_transaction")
        recompute.assert_called_once_with("IMP-CHANGE-1")

    def test_change_row_party_with_bt_updates_row_and_bt_directly(self):
        row = self._FakeRow(name="ROW-CHANGE-2", iban="DE-OLD")
        row.bank_transaction = "BT-CHANGE-2"
        row.party_type = "Customer"
        row.party = "CUST-OLD"
        doc = self._FakeDoc("IMP-CHANGE-2", [row])
        bt = self._FakeBT("BT-CHANGE-2", party_type="Customer", party="CUST-OLD")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party("IMP-CHANGE-2", "ROW-CHANGE-2", "Supplier", "SUP-NEW")

        self.assertEqual(row.party_type, "Supplier")
        self.assertEqual(row.party, "SUP-NEW")
        self.assertEqual(bt.party_type, "Supplier")
        self.assertEqual(bt.party, "SUP-NEW")
        self.assertTrue(res["bank_transaction"]["updated"])

    def test_change_row_party_clear_removes_party_from_row_and_bt(self):
        row = self._FakeRow(name="ROW-CLEAR", iban="DE-CLEAR")
        row.bank_transaction = "BT-CLEAR"
        row.party_type = "Customer"
        row.party = "CUST-CLEAR"
        doc = self._FakeDoc("IMP-CLEAR", [row])
        bt = self._FakeBT("BT-CLEAR", party_type="Customer", party="CUST-CLEAR")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party("IMP-CLEAR", "ROW-CLEAR", clear_party=1)

        self.assertIsNone(row.party_type)
        self.assertIsNone(row.party)
        self.assertIsNone(bt.party_type)
        self.assertIsNone(bt.party)
        self.assertTrue(res["bank_transaction"]["updated"])

    def test_reset_row_booking_cancels_payment_entry_and_clears_row(self):
        row = self._FakeRow(name="ROW-RESET", iban="DE-RESET")
        row.payment_entry = "PE-RESET"
        row.payment_document_type = "Payment Entry"
        row.payment_document = "PE-RESET"
        row.row_status = "success"
        row.auto_match_message = "done"
        doc = self._FakeDoc("IMP-RESET", [row])

        class _Voucher:
            name = "PE-RESET"
            flags = frappe._dict()

            def cancel(self):
                self.cancelled = True

        voucher = _Voucher()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Payment Entry":
                return voucher
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "get_value", return_value=1), \
             patch("hausverwaltung.hausverwaltung.utils.bank_transaction_links.remove_bank_transaction_payment_links", return_value=["BT-1"]) as remove_links, \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.reset_row_booking("IMP-RESET", "ROW-RESET")

        self.assertTrue(res["reset"])
        self.assertTrue(voucher.cancelled)
        remove_links.assert_called_once_with("Payment Entry", "PE-RESET")
        self.assertIsNone(row.payment_entry)
        self.assertIsNone(row.payment_document_type)
        self.assertIsNone(row.payment_document)
        self.assertIsNone(row.row_status)
        self.assertIn("PE-RESET", row.auto_match_message)

    def test_change_row_party_does_not_propagate_when_iban_not_unique(self):
        row = self._FakeRow(name="ROW-AMB-1", iban="DE-AMB")
        other = self._FakeRow(name="ROW-AMB-2", iban="DE-AMB")
        doc = self._FakeDoc("IMP-AMB", [row, other])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi, "_get_party_by_iban", return_value=None), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party(
                "IMP-AMB",
                "ROW-AMB-1",
                "Customer",
                "CUST-AMB",
                propagate_same_iban=1,
            )

        self.assertEqual(row.party, "CUST-AMB")
        self.assertIsNone(other.party)
        self.assertEqual(res["propagation_skipped"], "iban_not_unique")

    def test_change_row_party_propagates_only_unbooked_same_unique_iban_rows(self):
        row = self._FakeRow(name="ROW-PROP-1", iban="DE-PROP")
        other = self._FakeRow(name="ROW-PROP-2", iban="DE-PROP")
        other.bank_transaction = "BT-PROP-2"
        booked = self._FakeRow(name="ROW-PROP-3", iban="DE-PROP")
        booked.payment_entry = "PE-BOOKED"
        doc = self._FakeDoc("IMP-PROP", [row, other, booked])
        bt = self._FakeBT("BT-PROP-2")
        meta = type("M", (), {"fields": [type("F", (), {"fieldname": "party_type"})(), type("F", (), {"fieldname": "party"})()]})()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-PROP")), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.change_row_party(
                "IMP-PROP",
                "ROW-PROP-1",
                "Customer",
                "CUST-PROP",
                propagate_same_iban=1,
            )

        self.assertEqual(other.party, "CUST-PROP")
        self.assertEqual(bt.party, "CUST-PROP")
        self.assertIsNone(booked.party)
        self.assertEqual(len(res["propagated_rows"]), 1)

    def test_create_bank_transactions_returns_warning_when_any_row_has_no_party(self):
        row_ok = self._FakeRow(name="ROW-J1", iban="DE12")
        row_bad = self._FakeRow(name="ROW-J2", iban="")
        doc = self._FakeDoc("IMP-J", [row_ok, row_bad])

        class _BankAccount:
            is_company_account = 1

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return _BankAccount()
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi, "_resolve_row_party_for_validation", side_effect=[("Customer", "C1"), None]):
            res = bi.create_bank_transactions("IMP-J")

        self.assertEqual(res["created"], [])
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["warning"]["missing_count"], 1)
        self.assertIn("Zeilen ohne Party", res["warning"]["message"])

    def test_create_bank_transactions_warns_even_if_row_has_error_or_existing_bt(self):
        row_err = self._FakeRow(name="ROW-K1", iban="", error="Ungültig")
        row_err.bank_transaction = "BT-K1"
        row_ok = self._FakeRow(name="ROW-K2", iban="DE13")
        doc = self._FakeDoc("IMP-K", [row_err, row_ok])

        class _BankAccount:
            is_company_account = 1

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return _BankAccount()
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi, "_resolve_row_party_for_validation", side_effect=[None, ("Supplier", "S1")]):
            res = bi.create_bank_transactions("IMP-K")

        self.assertEqual(res["created"], [])
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["warning"]["missing_count"], 1)
        self.assertIn("Zeilen ohne Party", res["warning"]["message"])

    def test_create_bank_transactions_allows_when_party_resolved_via_iban(self):
        row = self._FakeRow(name="ROW-L1", iban="DE14")
        row.bank_transaction = "BT-L1"
        row.buchungstag = "2026-01-15"
        row.idx = 1
        row.betrag = 42
        row.richtung = "Eingang"
        row.currency = "EUR"
        doc = self._FakeDoc("IMP-L", [row])
        doc.bank_account = "BANK-1"

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

    def test_create_bank_transactions_preserves_existing_row_status(self):
        row = self._FakeRow(name="ROW-L2", iban="DE15")
        row.bank_transaction = "BT-L2"
        row.reference = None
        row.row_status = "success"
        row.db_updates = {}
        doc = self._FakeDoc("IMP-L2", [row])
        doc.bank_account = "BANK-1"
        doc.rows = [row]

        class _BankAccount:
            is_company_account = 1

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "get_cached_doc", return_value=_BankAccount()), \
             patch.object(bi.frappe.db, "get_single_value", return_value=None), \
             patch.object(bi, "_build_missing_party_warning_payload", return_value=None), \
             patch.object(bi, "_refresh_saldo_fields", return_value=None), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction",
                 return_value={"matched": False},
             ):
            bi.create_bank_transactions("IMP-L2")

        self.assertEqual(row.row_status, "success")

    def test_create_bank_transaction_for_row_delegates_with_row_scope(self):
        with patch.object(bi, "create_bank_transactions", return_value={"created": ["BT-1"]}) as create:
            res = bi.create_bank_transaction_for_row("IMP-ROW", "ROW-1", allow_missing_party=1)

        self.assertEqual(res["created"], ["BT-1"])
        create.assert_called_once_with(
            docname="IMP-ROW",
            row_name="ROW-1",
            allow_missing_party=1,
        )

    def test_auto_create_transactions_for_ready_rows_only_processes_party_rows(self):
        row_ready = self._FakeRow(name="ROW-READY", iban="DE1")
        row_ready.party_type = "Customer"
        row_ready.party = "CUST-1"
        row_missing_party = self._FakeRow(name="ROW-MISSING", iban="DE2")
        row_existing = self._FakeRow(name="ROW-EXISTING", iban="DE3")
        row_existing.party_type = "Customer"
        row_existing.party = "CUST-2"
        row_existing.bank_transaction = "BT-EXISTING"
        doc = self._FakeDoc("IMP-AUTO", [row_ready, row_missing_party, row_existing])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(
                 bi,
                 "create_bank_transactions",
                 return_value={
                     "created": ["BT-1"],
                     "auto_matched": ["BT-1"],
                     "auto_abschlag_matched": [],
                     "auto_kredit_matched": [],
                     "auto_match_failed": [],
                     "errors": [],
                 },
             ) as create:
            res = bi._auto_create_transactions_for_ready_rows("IMP-AUTO")

        self.assertEqual(res["attempted"], 1)
        self.assertEqual(res["created"], ["BT-1"])
        self.assertEqual(res["auto_matched"], ["BT-1"])
        create.assert_called_once_with(
            docname="IMP-AUTO",
            row_name="ROW-READY",
            allow_missing_party=0,
        )

    def test_retry_auto_match_only_processes_open_bank_transaction_rows(self):
        row_open = self._FakeRow(name="ROW-OPEN", iban="DE1")
        row_open.bank_transaction = "BT-OPEN"
        row_done = self._FakeRow(name="ROW-DONE", iban="DE2")
        row_done.bank_transaction = "BT-DONE"
        row_done.payment_entry = "PE-DONE"
        row_no_bt = self._FakeRow(name="ROW-NO-BT", iban="DE3")
        doc = self._FakeDoc("IMP-RETRY", [row_open, row_done, row_no_bt])

        with patch.object(bi.frappe, "get_doc", return_value=doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(
                 bi,
                 "_retry_auto_match_for_row",
                 return_value={"row": "ROW-OPEN", "matched": True, "payment_entry": "PE-1"},
             ) as retry, \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.retry_auto_match("IMP-RETRY")

        self.assertEqual(res["processed"], 1)
        self.assertEqual(len(res["matched"]), 1)
        retry.assert_called_once_with("IMP-RETRY", "ROW-OPEN")
        self.assertIsNone(row_open.payment_entry)

    def test_create_bank_transactions_marks_row_failed_when_submit_fails(self):
        row = self._FakeRow(name="ROW-SUBMIT-FAIL", iban="DE16")
        row.bank_transaction = None
        row.reference = None
        row.row_status = None
        row.buchungstag = "2026-01-15"
        row.idx = 1
        row.betrag = 42
        row.richtung = "Eingang"
        row.currency = "EUR"
        row.verwendungszweck = "Test"
        row.db_updates = {}

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set
        doc = self._FakeDoc("IMP-SUBMIT-FAIL", [row])
        doc.bank_account = "BANK-1"
        doc.rows = [row]
        doc.reload = lambda: None

        class _BankAccount:
            is_company_account = 1

        class _BankTransaction:
            name = "BT-SUBMIT-FAIL"

            def set(self, fieldname, value):
                setattr(self, fieldname, value)

            def insert(self, ignore_permissions=False):
                self.inserted = True

            def submit(self):
                raise Exception("submit boom")

            def delete(self, ignore_permissions=False):
                self.deleted = True
                self.delete_ignore_permissions = ignore_permissions

        bt = _BankTransaction()

        meta = type(
            "M",
            (),
            {
                "is_submittable": 1,
                "fields": [
                    type("F", (), {"fieldname": "date"})(),
                    type("F", (), {"fieldname": "deposit"})(),
                    type("F", (), {"fieldname": "withdrawal"})(),
                    type("F", (), {"fieldname": "description"})(),
                    type("F", (), {"fieldname": "currency"})(),
                ],
            },
        )()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return _BankAccount()
            raise AssertionError(f"unexpected doctype {doctype}")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "new_doc", return_value=bt), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi.frappe.db, "get_single_value", return_value=None), \
             patch.object(bi, "_build_missing_party_warning_payload", return_value=None), \
             patch.object(bi, "_find_existing_bank_transaction", return_value=None), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-1")), \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi.frappe, "log_error"), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction",
                 return_value={"matched": True, "payment_entry": "PE-1"},
             ) as auto_match:
            res = bi.create_bank_transactions("IMP-SUBMIT-FAIL")

        self.assertEqual(row.row_status, "failed")
        self.assertIn("submit boom", row.error)
        self.assertIsNone(row.bank_transaction)
        self.assertIsNone(row.reference)
        self.assertEqual(res["created"], [])
        self.assertEqual(res["errors"][0]["row"], "ROW-SUBMIT-FAIL")
        self.assertTrue(bt.deleted)
        self.assertTrue(bt.delete_ignore_permissions)
        auto_match.assert_not_called()

    def test_create_bank_transactions_marks_submitted_transaction_success(self):
        row = self._FakeRow(name="ROW-SUBMIT-OK", iban="DE17")
        row.bank_transaction = None
        row.reference = None
        row.row_status = None
        row.buchungstag = "2026-01-15"
        row.idx = 1
        row.betrag = 42
        row.richtung = "Eingang"
        row.currency = "EUR"
        row.verwendungszweck = "Test"

        doc = self._FakeDoc("IMP-SUBMIT-OK", [row])
        doc.bank_account = "BANK-1"
        doc.rows = [row]
        doc.reload = lambda: None

        class _BankAccount:
            is_company_account = 1

        class _BankTransaction:
            name = "BT-SUBMIT-OK"

            def set(self, fieldname, value):
                setattr(self, fieldname, value)

            def insert(self, ignore_permissions=False):
                self.inserted = True

            def submit(self):
                self.submitted = True

        meta = type(
            "M",
            (),
            {
                "is_submittable": 1,
                "fields": [
                    type("F", (), {"fieldname": "date"})(),
                    type("F", (), {"fieldname": "deposit"})(),
                    type("F", (), {"fieldname": "withdrawal"})(),
                    type("F", (), {"fieldname": "description"})(),
                    type("F", (), {"fieldname": "currency"})(),
                ],
            },
        )()

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Account":
                return _BankAccount()
            raise AssertionError(f"unexpected doctype {doctype}")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "new_doc", return_value=_BankTransaction()), \
             patch.object(bi.frappe, "get_meta", return_value=meta), \
             patch.object(bi.frappe.db, "get_single_value", return_value=None), \
             patch.object(bi, "_build_missing_party_warning_payload", return_value=None), \
             patch.object(bi, "_find_existing_bank_transaction", return_value=None), \
             patch.object(bi, "_get_party_by_iban", return_value=("Customer", "CUST-1")), \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_recompute_doc_status"), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction",
                 return_value={"matched": False, "message": "kein Match"},
             ) as auto_match:
            res = bi.create_bank_transactions("IMP-SUBMIT-OK")

        self.assertEqual(row.row_status, "success")
        self.assertEqual(row.bank_transaction, "BT-SUBMIT-OK")
        self.assertEqual(row.reference, "BT-SUBMIT-OK")
        self.assertEqual(res["created"], ["BT-SUBMIT-OK"])
        auto_match.assert_called_once_with("BT-SUBMIT-OK")

    def test_sync_cancelled_payment_entry_links_keeps_active_payment_entry(self):
        rows = [
            frappe._dict({
                "name": "ROW-ACTIVE",
                "parent": "IMP-ACTIVE",
                "payment_entry": "PE-ACTIVE",
                "payment_document_type": "Payment Entry",
                "payment_document": "PE-ACTIVE",
                "journal_entry": None,
                "row_status": "success",
                "error": None,
            })
        ]

        with patch.object(bi.frappe.db, "sql", return_value=rows), \
             patch.object(bi.frappe.db, "get_value", return_value=1), \
             patch.object(bi.frappe.db, "set_value") as set_value, \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            res = bi.sync_cancelled_payment_entry_links(payment_entry_name="PE-ACTIVE")

        self.assertEqual(res["cleared"], 0)
        set_value.assert_not_called()
        recompute.assert_not_called()
        refresh.assert_not_called()

    def test_sync_cancelled_payment_entry_links_clears_cancelled_payment_entry(self):
        rows = [
            frappe._dict({
                "name": "ROW-CANCELLED",
                "parent": "IMP-CANCELLED",
                "payment_entry": "PE-CANCELLED",
                "payment_document_type": "Payment Entry",
                "payment_document": "PE-CANCELLED",
                "journal_entry": None,
                "row_status": "success",
                "error": None,
            })
        ]

        with patch.object(bi.frappe.db, "sql", return_value=rows), \
             patch.object(bi.frappe.db, "get_value", return_value=2), \
             patch.object(bi.frappe.db, "set_value") as set_value, \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            res = bi.sync_cancelled_payment_entry_links(payment_entry_name="PE-CANCELLED")

        self.assertEqual(res["cleared"], 1)
        updates = set_value.call_args[0][2]
        self.assertIsNone(updates["payment_entry"])
        self.assertIsNone(updates["payment_document_type"])
        self.assertIsNone(updates["payment_document"])
        self.assertIsNone(updates["row_status"])
        self.assertIn("PE-CANCELLED", updates["auto_match_message"])
        recompute.assert_called_once_with("IMP-CANCELLED")
        refresh.assert_called_once_with("IMP-CANCELLED")

    def test_sync_cancelled_payment_entry_links_clears_payment_document_only_link(self):
        rows = [
            frappe._dict({
                "name": "ROW-DOC-LINK",
                "parent": "IMP-DOC-LINK",
                "payment_entry": None,
                "payment_document_type": "Payment Entry",
                "payment_document": "PE-DOC-LINK",
                "journal_entry": None,
                "row_status": "success",
                "error": None,
            })
        ]

        with patch.object(bi.frappe.db, "sql", return_value=rows), \
             patch.object(bi.frappe.db, "get_value", return_value=2), \
             patch.object(bi.frappe.db, "set_value") as set_value, \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.sync_cancelled_payment_entry_links(import_name="IMP-DOC-LINK")

        self.assertEqual(res["cleared"], 1)
        updates = set_value.call_args[0][2]
        self.assertIsNone(updates["payment_entry"])
        self.assertIsNone(updates["payment_document_type"])
        self.assertIsNone(updates["payment_document"])

    def test_sync_cancelled_payment_entry_links_ignores_journal_entry_rows(self):
        rows = [
            frappe._dict({
                "name": "ROW-JOURNAL",
                "parent": "IMP-JOURNAL",
                "payment_entry": "PE-CANCELLED",
                "payment_document_type": "Payment Entry",
                "payment_document": "PE-CANCELLED",
                "journal_entry": "JE-1",
                "row_status": "success",
                "error": None,
            })
        ]

        with patch.object(bi.frappe.db, "sql", return_value=rows), \
             patch.object(bi.frappe.db, "get_value", return_value=2), \
             patch.object(bi.frappe.db, "set_value") as set_value:
            res = bi.sync_cancelled_payment_entry_links(payment_entry_name="PE-CANCELLED")

        self.assertEqual(res["cleared"], 0)
        set_value.assert_not_called()

    def test_sync_cancelled_journal_entry_links_clears_cancelled_journal_entry(self):
        rows = [
            frappe._dict({
                "name": "ROW-JE-CANCELLED",
                "parent": "IMP-JE-CANCELLED",
                "payment_entry": None,
                "payment_document_type": "Journal Entry",
                "payment_document": "JE-CANCELLED",
                "journal_entry": "JE-CANCELLED",
                "row_status": "success",
                "error": None,
            })
        ]

        with patch.object(bi.frappe.db, "sql", return_value=rows), \
             patch.object(bi.frappe.db, "get_value", return_value=2), \
             patch.object(bi.frappe.db, "set_value") as set_value, \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh, \
             patch(
                 "hausverwaltung.hausverwaltung.utils.bank_transaction_links.remove_bank_transaction_payment_links",
             ) as remove_links:
            res = bi.sync_cancelled_journal_entry_links(journal_entry_name="JE-CANCELLED")

        self.assertEqual(res["cleared"], 1)
        updates = set_value.call_args[0][2]
        self.assertIsNone(updates["journal_entry"])
        self.assertIsNone(updates["payment_document_type"])
        self.assertIsNone(updates["payment_document"])
        self.assertIsNone(updates["row_status"])
        self.assertIn("JE-CANCELLED", updates["auto_match_message"])
        remove_links.assert_called_once_with("Journal Entry", "JE-CANCELLED")
        recompute.assert_called_once_with("IMP-JE-CANCELLED")
        refresh.assert_called_once_with("IMP-JE-CANCELLED")

    def test_sync_cancelled_journal_entry_links_keeps_error_status(self):
        rows = [
            frappe._dict({
                "name": "ROW-JE-ERROR",
                "parent": "IMP-JE-ERROR",
                "payment_entry": None,
                "payment_document_type": "Journal Entry",
                "payment_document": "JE-CANCELLED",
                "journal_entry": "JE-CANCELLED",
                "row_status": "failed",
                "error": "boom",
            })
        ]

        with patch.object(bi.frappe.db, "sql", return_value=rows), \
             patch.object(bi.frappe.db, "get_value", return_value=2), \
             patch.object(bi.frappe.db, "set_value") as set_value, \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.bank_transaction_links.remove_bank_transaction_payment_links",
             ):
            bi.sync_cancelled_journal_entry_links(journal_entry_name="JE-CANCELLED")

        updates = set_value.call_args[0][2]
        self.assertNotIn("row_status", updates)

    def test_get_abschlagsplan_candidates_filters_and_sorts_plan_rows(self):
        row = self._FakeRow(name="ROW-ABS", iban="DE16")
        row.richtung = "Ausgang"
        row.party_type = "Supplier"
        row.party = "SUP-1"
        row.betrag = 120.0
        row.buchungstag = "2026-05-05"
        row.bank_transaction = "BT-ABS"
        doc = self._FakeDoc("IMP-ABS", [row])
        bt = type("BT", (), {"name": "BT-ABS", "bank_account": "BA-1"})()

        sql_rows = [
            {
                "row_name": "ROW-FAR",
                "row_idx": 3,
                "faelligkeitsdatum": "2026-08-01",
                "betrag": 120.0,
                "zahlungsplan": "ZP-FAR",
                "bank_account": "BA-1",
                "cost_center": "CC-1",
            },
            {
                "row_name": "ROW-BANK-MISMATCH",
                "row_idx": 2,
                "faelligkeitsdatum": "2026-05-05",
                "betrag": 120.0,
                "zahlungsplan": "ZP-BAD",
                "bank_account": "BA-2",
                "cost_center": "CC-1",
            },
            {
                "row_name": "ROW-OK",
                "row_idx": 1,
                "faelligkeitsdatum": "2026-05-06",
                "betrag": 120.0,
                "zahlungsplan": "ZP-OK",
                "bank_account": "BA-1",
                "cost_center": "CC-1",
            },
        ]

        def _get_doc(doctype, name=None):
            if doctype == "Bankauszug Import":
                return doc
            if doctype == "Bank Transaction":
                return bt
            raise AssertionError("unexpected doctype")

        with patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch.object(bi.frappe, "has_permission", return_value=True), \
             patch.object(bi.frappe.db, "exists", return_value=True), \
             patch.object(bi.frappe.db, "sql", return_value=sql_rows), \
             patch(
                 "hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan._get_abschlag_tolerance_days",
                 return_value=7,
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match._resolve_expected_cost_center_for_bt",
                 return_value="CC-1",
             ):
            res = bi.get_abschlagsplan_candidates_for_row("IMP-ABS", "ROW-ABS")

        self.assertEqual([c["row_name"] for c in res["candidates"]], ["ROW-OK"])
        self.assertEqual(res["candidates"][0]["delta_days"], 1)
        self.assertEqual(res["manual_window_days"], 45)

    def test_manually_reconcile_row_reconcile_failure_leaves_row_unset(self):
        row = self._FakeRow(name="ROW-INV-FAIL", iban="DE15")
        row.party_type = "Customer"
        row.party = "CUST-1"
        row.betrag = 100.0
        row.payment_entry = None
        row.journal_entry = None
        row.row_status = None
        row.db_updates = {}

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set
        bt = type("BT", (), {"name": "BT-INV-FAIL"})()
        pe = type("PE", (), {"name": "PE-INV-FAIL"})()
        invoice = frappe._dict(name="SINV-FAIL", outstanding_amount=100.0, posting_date="2026-05-05")

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch.object(bi.frappe.db, "get_value", return_value=invoice), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_payment_entry_for_invoices",
                 return_value=pe,
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
                 side_effect=RuntimeError("simulated"),
             ), \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            with self.assertRaises(RuntimeError):
                bi.manually_reconcile_row("IMP-INV-FAIL", "ROW-INV-FAIL", "SINV-FAIL")

        self.assertIsNone(row.payment_entry)
        self.assertIsNone(getattr(row, "payment_document", None))
        self.assertIsNone(row.row_status)
        recompute.assert_not_called()
        refresh.assert_not_called()

    def test_manually_reconcile_row_rejects_explicit_allocations_above_bank_amount(self):
        import json as _json

        row = self._FakeRow(name="ROW-INV-OVER", iban="DE15")
        row.party_type = "Customer"
        row.party = "CUST-1"
        row.betrag = 150.0
        row.payment_entry = None
        row.journal_entry = None
        bt = type("BT", (), {"name": "BT-INV-OVER"})()

        invoices = {
            "SINV-A": frappe._dict(name="SINV-A", outstanding_amount=100.0, posting_date="2026-05-05"),
            "SINV-B": frappe._dict(name="SINV-B", outstanding_amount=100.0, posting_date="2026-05-06"),
        }

        def _get_value(doctype, name, fields, as_dict=False):
            return invoices.get(name)

        payload = _json.dumps([
            {"name": "SINV-A", "allocated_amount": 100.0},
            {"name": "SINV-B", "allocated_amount": 100.0},
        ])

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch.object(bi.frappe.db, "get_value", side_effect=_get_value), \
             patch.object(bi.frappe, "throw", side_effect=Exception) as throw, \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_payment_entry_for_invoices",
             ) as create_pe:
            with self.assertRaises(Exception):
                bi.manually_reconcile_row("IMP-INV-OVER", "ROW-INV-OVER", payload)

        create_pe.assert_not_called()
        self.assertIn("Zuweisungen summieren", throw.call_args[0][0])

    def test_manually_reconcile_row_rejects_implicit_partial_allocation(self):
        row = self._FakeRow(name="ROW-INV-PARTIAL", iban="DE15")
        row.party_type = "Customer"
        row.party = "CUST-1"
        row.betrag = 100.0
        row.payment_entry = None
        row.journal_entry = None
        bt = type("BT", (), {"name": "BT-INV-PARTIAL"})()

        invoices = {
            "SINV-A": frappe._dict(name="SINV-A", outstanding_amount=80.0, posting_date="2026-05-05"),
            "SINV-B": frappe._dict(name="SINV-B", outstanding_amount=80.0, posting_date="2026-05-06"),
        }

        def _get_value(doctype, name, fields, as_dict=False):
            return invoices.get(name)

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch.object(bi.frappe.db, "get_value", side_effect=_get_value), \
             patch.object(bi.frappe, "throw", side_effect=Exception) as throw, \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_payment_entry_for_invoices",
             ) as create_pe:
            with self.assertRaises(Exception):
                bi.manually_reconcile_row("IMP-INV-PARTIAL", "ROW-INV-PARTIAL", "SINV-A,SINV-B")

        create_pe.assert_not_called()
        self.assertIn("Ausgewählte Rechnungen summieren", throw.call_args[0][0])

    def test_assign_abschlagsplan_row_creates_payment_and_marks_plan_row(self):
        row = self._FakeRow(name="ROW-ASSIGN", iban="DE17", verwendungszweck="Abschlag")
        row.richtung = "Ausgang"
        row.party_type = "Supplier"
        row.party = "SUP-1"
        row.betrag = 120.0
        row.buchungstag = "2026-05-05"
        row.payment_entry = None
        row.journal_entry = None
        row.db_updates = {}

        def _row_db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _row_db_set
        doc = self._FakeDoc("IMP-ASSIGN", [row])
        bt = type("BT", (), {"name": "BT-ASSIGN", "bank_account": "BA-1"})()
        pe = type("PE", (), {"name": "PE-ASSIGN"})()
        plan_row = frappe._dict({
            "name": "PLAN-ROW-1",
            "parent": "ZP-1",
            "idx": 4,
            "faelligkeitsdatum": "2026-05-05",
            "betrag": 120.0,
            "payment_entry": None,
        })

        class _Plan:
            name = "ZP-1"
            bank_account = "BA-1"
            cost_center = "CC-1"

            def get(self, key, default=None):
                return {
                    "modus": "Abschlagsplan",
                    "status": "Läuft",
                    "lieferant": "SUP-1",
                    "bank_account": "BA-1",
                    "cost_center": "CC-1",
                }.get(key, default)

        class _PlanRowDoc:
            def __init__(self):
                self.db_updates = {}

            def db_set(self, fieldname, value, update_modified=False):
                self.db_updates[fieldname] = value
                setattr(self, fieldname, value)

        plan_row_doc = _PlanRowDoc()

        def _get_doc(doctype, name=None):
            if doctype == "Zahlungsplan":
                return _Plan()
            if doctype == "Zahlungsplan Zeile":
                return plan_row_doc
            raise AssertionError("unexpected doctype")

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(doc, row, bt)), \
             patch.object(bi.frappe.db, "get_value", return_value=plan_row), \
             patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match._resolve_expected_cost_center_for_bt",
                 return_value="CC-1",
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_standalone_payment_entry",
                 return_value=pe,
             ) as create_pe, \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
             ) as reconcile, \
             patch.object(bi, "_recompute_doc_status"), \
             patch.object(bi, "_refresh_and_persist_saldo"):
            res = bi.assign_abschlagsplan_row("IMP-ASSIGN", "ROW-ASSIGN", "PLAN-ROW-1")

        create_pe.assert_called_once()
        reconcile.assert_called_once_with(bt, "Payment Entry", "PE-ASSIGN", 120.0)
        self.assertEqual(row.payment_entry, "PE-ASSIGN")
        self.assertEqual(row.payment_document_type, "Payment Entry")
        self.assertEqual(row.payment_document, "PE-ASSIGN")
        self.assertEqual(row.row_status, "success")
        self.assertEqual(plan_row_doc.payment_entry, "PE-ASSIGN")
        self.assertEqual(plan_row_doc.bank_transaction, "BT-ASSIGN")
        self.assertEqual(str(plan_row_doc.gebucht_am), "2026-05-05")
        self.assertEqual(res["zahlungsplan"], "ZP-1")

    def test_assign_abschlagsplan_row_reconcile_failure_leaves_links_unset(self):
        row = self._FakeRow(name="ROW-ASSIGN-FAIL", iban="DE17", verwendungszweck="Abschlag")
        row.richtung = "Ausgang"
        row.party_type = "Supplier"
        row.party = "SUP-1"
        row.betrag = 120.0
        row.buchungstag = "2026-05-05"
        row.payment_entry = None
        row.journal_entry = None
        row.row_status = None
        row.db_updates = {}

        def _row_db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _row_db_set
        doc = self._FakeDoc("IMP-ASSIGN-FAIL", [row])
        bt = type("BT", (), {"name": "BT-ASSIGN-FAIL", "bank_account": "BA-1"})()
        pe = type("PE", (), {"name": "PE-ASSIGN-FAIL"})()
        plan_row = frappe._dict({
            "name": "PLAN-ROW-FAIL",
            "parent": "ZP-1",
            "idx": 4,
            "faelligkeitsdatum": "2026-05-05",
            "betrag": 120.0,
            "payment_entry": None,
        })

        class _Plan:
            name = "ZP-1"
            bank_account = "BA-1"
            cost_center = "CC-1"

            def get(self, key, default=None):
                return {
                    "modus": "Abschlagsplan",
                    "status": "Läuft",
                    "lieferant": "SUP-1",
                    "bank_account": "BA-1",
                    "cost_center": "CC-1",
                }.get(key, default)

        class _PlanRowDoc:
            def db_set(self, fieldname, value, update_modified=False):
                setattr(self, fieldname, value)

        plan_row_doc = _PlanRowDoc()

        def _get_doc(doctype, name=None):
            if doctype == "Zahlungsplan":
                return _Plan()
            if doctype == "Zahlungsplan Zeile":
                return plan_row_doc
            raise AssertionError("unexpected doctype")

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(doc, row, bt)), \
             patch.object(bi.frappe.db, "get_value", return_value=plan_row), \
             patch.object(bi.frappe, "get_doc", side_effect=_get_doc), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match._resolve_expected_cost_center_for_bt",
                 return_value="CC-1",
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_standalone_payment_entry",
                 return_value=pe,
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
                 side_effect=RuntimeError("simulated"),
             ), \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            with self.assertRaises(RuntimeError):
                bi.assign_abschlagsplan_row("IMP-ASSIGN-FAIL", "ROW-ASSIGN-FAIL", "PLAN-ROW-FAIL")

        self.assertIsNone(row.payment_entry)
        self.assertIsNone(getattr(row, "payment_document", None))
        self.assertIsNone(row.row_status)
        self.assertFalse(hasattr(plan_row_doc, "payment_entry"))
        self.assertFalse(hasattr(plan_row_doc, "bank_transaction"))
        recompute.assert_not_called()
        refresh.assert_not_called()

    def test_create_standalone_payment_for_row_reconcile_failure_leaves_row_unset(self):
        row = self._FakeRow(name="ROW-PE-FAIL", iban="DE18")
        row.party_type = "Customer"
        row.party = "CUST-1"
        row.betrag = 80.0
        row.payment_entry = None
        row.journal_entry = None
        row.row_status = None
        row.db_updates = {}

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set
        bt = type("BT", (), {"name": "BT-PE-FAIL"})()
        pe = type("PE", (), {"name": "PE-FAIL"})()

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_standalone_payment_entry",
                 return_value=pe,
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
                 side_effect=RuntimeError("simulated"),
             ), \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            with self.assertRaises(RuntimeError):
                bi.create_standalone_payment_for_row("IMP-PE-FAIL", "ROW-PE-FAIL")

        self.assertIsNone(row.payment_entry)
        self.assertIsNone(getattr(row, "payment_document", None))
        self.assertIsNone(row.row_status)
        recompute.assert_not_called()
        refresh.assert_not_called()

    def test_create_journal_entry_for_row_sets_journal_entry_and_success_status(self):
        row = self._FakeRow(name="ROW-JE", iban="DE16")
        row.bank_transaction = "BT-JE"
        row.betrag = 12.34
        row.journal_entry = None
        row.payment_entry = None
        row.db_updates = {}

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set
        bt = type("BT", (), {"name": "BT-JE"})()
        je = type("JE", (), {"name": "JE-1"})()

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_journal_entry_for_bt",
                 return_value=je,
             ) as create_je, \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
                 return_value=None,
             ) as reconcile:
            res = bi.create_journal_entry_for_row(
                "IMP-JE",
                "ROW-JE",
                "6300 - Hausmeister-Vergütung - HP",
                None,
                "Test JE",
            )

        self.assertEqual(res["journal_entry"], "JE-1")
        self.assertEqual(row.journal_entry, "JE-1")
        self.assertEqual(row.payment_document_type, "Journal Entry")
        self.assertEqual(row.payment_document, "JE-1")
        self.assertEqual(row.row_status, "success")
        self.assertIn("Buchungssatz", row.auto_match_message)
        create_je.assert_called_once()
        reconcile.assert_called_once_with(bt, "Journal Entry", "JE-1", 12.34)

    def test_create_journal_entry_for_row_reconcile_failure_leaves_row_unset(self):
        row = self._FakeRow(name="ROW-JE-FAIL", iban="DE16")
        row.bank_transaction = "BT-JE-FAIL"
        row.betrag = 12.34
        row.journal_entry = None
        row.payment_entry = None
        row.row_status = None
        row.db_updates = {}

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set
        bt = type("BT", (), {"name": "BT-JE-FAIL"})()
        je = type("JE", (), {"name": "JE-FAIL"})()

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_journal_entry_for_bt",
                 return_value=je,
             ), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
                 side_effect=RuntimeError("simulated"),
             ), \
             patch.object(bi, "_recompute_doc_status") as recompute, \
             patch.object(bi, "_refresh_and_persist_saldo") as refresh:
            with self.assertRaises(RuntimeError):
                bi.create_journal_entry_for_row(
                    "IMP-JE-FAIL",
                    "ROW-JE-FAIL",
                    "6300 - Hausmeister-Vergütung - HP",
                    None,
                    "Test JE",
                )

        self.assertIsNone(row.journal_entry)
        self.assertIsNone(getattr(row, "payment_document", None))
        self.assertIsNone(row.row_status)
        recompute.assert_not_called()
        refresh.assert_not_called()

    def test_create_journal_entry_for_row_with_splits_passes_list_to_backend(self):
        import json as _json

        row = self._FakeRow(name="ROW-JE-SPLIT", iban="DE16")
        row.bank_transaction = "BT-JE-SPLIT"
        row.betrag = 305.00
        row.journal_entry = None
        row.payment_entry = None
        row.db_updates = {}

        def _db_set(fieldname, value):
            row.db_updates[fieldname] = value
            setattr(row, fieldname, value)

        row.db_set = _db_set
        bt = type("BT", (), {"name": "BT-JE-SPLIT"})()
        je = type("JE", (), {"name": "JE-SPLIT-1"})()

        splits_payload = _json.dumps([
            {"account": "4400 - Mieteinnahmen - HP", "cost_center": "Haus A - HP", "amount": 300.0},
            {"account": "4490 - Saeumniszuschlag - HP", "cost_center": "Haus A - HP", "amount": 5.0},
        ])

        with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, bt)), \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.create_journal_entry_for_bt",
                 return_value=je,
             ) as create_je, \
             patch(
                 "hausverwaltung.hausverwaltung.utils.payment_auto_match.reconcile_created_voucher_or_rollback",
                 return_value=None,
             ) as reconcile:
            res = bi.create_journal_entry_for_row(
                "IMP-JE-SPLIT",
                "ROW-JE-SPLIT",
                splits=splits_payload,
            )

        self.assertEqual(res["journal_entry"], "JE-SPLIT-1")
        self.assertEqual(row.journal_entry, "JE-SPLIT-1")
        self.assertEqual(row.row_status, "success")
        self.assertIn("Buchungssatz", row.auto_match_message)
        self.assertIn("2 Konten", row.auto_match_message)
        # Backend muss die geparste Liste bekommen, nicht den JSON-String
        kwargs = create_je.call_args.kwargs
        self.assertIsInstance(kwargs.get("splits"), list)
        self.assertEqual(len(kwargs["splits"]), 2)
        self.assertEqual(kwargs["splits"][0]["amount"], 300.0)
        reconcile.assert_called_once_with(bt, "Journal Entry", "JE-SPLIT-1", 305.0)

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

    def test_collect_rows_missing_party_ignores_existing_rows(self):
        row_existing = self._FakeRow(name="ROW-EXISTING", iban="")
        row_existing.row_status = "schon vorhanden"
        row_open = self._FakeRow(name="ROW-OPEN", iban="")
        doc = self._FakeDoc("IMP-SKIP", [row_existing, row_open])

        with patch.object(bi, "_resolve_row_party_for_validation", return_value=None):
            missing = bi._collect_rows_missing_party(doc)

        self.assertEqual([m["row"] for m in missing], ["ROW-OPEN"])

    def test_recompute_doc_status_excludes_existing_rows_from_open_count(self):
        rows = [
            frappe._dict(row_status="schon vorhanden", party_type=None, party=None, bank_transaction="BT-1"),
            frappe._dict(row_status=None, party_type=None, party=None, bank_transaction=None),
        ]

        with patch.object(bi.frappe, "get_all", return_value=rows), \
             patch.object(bi.frappe.db, "set_value") as set_value:
            status = bi._recompute_doc_status("IMP-STATUS")

        self.assertIn("Phase 1: 0/1 Parteien zugeordnet", status)
        self.assertIn("Übersprungen: 1", status)
        self.assertEqual(set_value.call_args.args[2]["offene_buchungen"], 1)

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


class TestBankauszugImportDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        self.created_docs = []
        self.suffix = frappe.generate_hash(length=8)
        company_rows = frappe.get_all("Company", pluck="name", limit=1)
        if not company_rows:
            self.skipTest("Integrationstest benötigt mindestens eine Company.")
        self.company = company_rows[0]

        self.bank_gl_account = self._make_bank_gl_account()
        self.bank_account = self._make_company_bank_account()

    def tearDown(self):
        for doctype, name in reversed(self.created_docs):
            if not frappe.db.exists(doctype, name):
                continue
            try:
                doc = frappe.get_doc(doctype, name)
                if getattr(doc, "docstatus", 0) == 1:
                    doc.cancel()
            except Exception:
                pass
            try:
                frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
            except TypeError:
                frappe.delete_doc(doctype, name, ignore_permissions=True)
            except Exception:
                pass

    def _track(self, doc):
        self.created_docs.append((doc.doctype, doc.name))
        return doc

    def _bank_parent_account(self):
        preferred = frappe.get_all(
            "Account",
            filters={
                "company": self.company,
                "is_group": 1,
                "root_type": "Asset",
                "account_name": ["in", ["Bank Accounts", "Bank", "Bankkonten"]],
            },
            pluck="name",
            limit=1,
        )
        if preferred:
            return preferred[0]

        asset_groups = frappe.get_all(
            "Account",
            filters={"company": self.company, "is_group": 1, "root_type": "Asset"},
            pluck="name",
            order_by="lft desc",
            limit=1,
        )
        if not asset_groups:
            self.skipTest("Integrationstest benötigt eine Asset-Konto-Gruppe.")
        return asset_groups[0]

    def _make_bank_gl_account(self):
        account = frappe.get_doc({
            "doctype": "Account",
            "account_name": f"HV Test Bank GL {self.suffix}",
            "parent_account": self._bank_parent_account(),
            "company": self.company,
            "account_type": "Bank",
            "is_group": 0,
        }).insert(ignore_permissions=True)
        self._track(account)
        return account.name

    def _make_company_bank_account(self):
        bank_name = f"HV Test Bank {self.suffix}"
        if not frappe.db.exists("Bank", bank_name):
            self._track(
                frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(
                    ignore_permissions=True
                )
            )
        bank_account = frappe.get_doc({
            "doctype": "Bank Account",
            "account_name": f"HV Test Bankkonto {self.suffix}",
            "bank": bank_name,
            "company": self.company,
            "account": self.bank_gl_account,
            "is_company_account": 1,
            "disabled": 0,
            "iban": "DE89370400440532013000",
        }).insert(ignore_permissions=True)
        self._track(bank_account)
        return bank_account.name

    def _make_file(self):
        file_doc = save_file(
            f"hv-bankimport-{self.suffix}.csv",
            b"Buchungstag;Betrag;Verwendungszweck\n",
            "",
            "",
            is_private=1,
        )
        self._track(file_doc)
        return file_doc

    def _make_import(self, rows):
        file_doc = self._make_file()
        import_doc = frappe.get_doc({
            "doctype": "Bankauszug Import",
            "bank_account": self.bank_account,
            "csv_file": file_doc.file_url,
        })
        for row in rows:
            import_doc.append("rows", row)
        import_doc.insert(ignore_permissions=True)
        self._track(import_doc)
        return import_doc

    def _neutral_row(self, **overrides):
        row = {
            "buchungstag": "2026-04-03",
            "betrag": 42.35,
            "richtung": "Eingang",
            "auftraggeber": f"HV Integration {self.suffix}",
            "verwendungszweck": f"Integrationstest {self.suffix}",
            "iban": "DE89370400440532013000",
            "currency": "EUR",
        }
        row.update(overrides)
        return row

    def _create_transactions_without_auto_match(self, import_name):
        with patch(
            "hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction",
            return_value={"matched": False, "reason": "no_party", "message": "Keine Party"},
        ), \
             patch.object(bi, "_refresh_saldo_fields"), \
             patch.object(bi, "_persist_saldo_fields"):
            return bi.create_bank_transactions(import_name, allow_missing_party=1)

    def test_real_import_document_persists_rows_and_computes_title(self):
        doc = self._make_import([
            self._neutral_row(betrag=10.5, verwendungszweck="Erste echte Zeile"),
            self._neutral_row(
                buchungstag="2026-04-05",
                betrag=15.25,
                richtung="Ausgang",
                verwendungszweck="Zweite echte Zeile",
            ),
        ])

        doc.reload()

        self.assertEqual(len(doc.rows), 2)
        self.assertIn("2 Buchungen", doc.title)
        self.assertEqual(doc.rows[0].betrag, 10.5)
        self.assertEqual(doc.rows[1].richtung, "Ausgang")

    def test_real_create_bank_transactions_creates_submitted_bt_and_updates_row(self):
        doc = self._make_import([self._neutral_row()])

        result = self._create_transactions_without_auto_match(doc.name)

        doc.reload()
        row = doc.rows[0]
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["created"], [row.bank_transaction])
        self.assertTrue(frappe.db.exists("Bank Transaction", row.bank_transaction))
        self.created_docs.append(("Bank Transaction", row.bank_transaction))
        bt = frappe.get_doc("Bank Transaction", row.bank_transaction)
        self.assertEqual(bt.bank_account, self.bank_account)
        self.assertEqual(bt.deposit, 42.35)
        self.assertEqual(bt.withdrawal, 0)
        self.assertEqual(bt.status, "Unreconciled")
        self.assertEqual(row.row_status, "success")
        self.assertEqual(row.reference, row.bank_transaction)

    def test_real_delete_import_blocks_without_cascade_when_import_owns_bank_transaction(self):
        doc = self._make_import([self._neutral_row(betrag=71.9)])
        result = self._create_transactions_without_auto_match(doc.name)
        self.created_docs.append(("Bank Transaction", result["created"][0]))

        with self.assertRaises(frappe.ValidationError):
            bv2.delete_import(doc.name, cascade=0)

        self.assertTrue(frappe.db.exists("Bankauszug Import", doc.name))
        doc.reload()
        self.assertEqual(doc.rows[0].bank_transaction, result["created"][0])
