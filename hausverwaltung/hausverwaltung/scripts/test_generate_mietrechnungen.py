import unittest
from datetime import date
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts import generate_mietrechnungen


class TestGenerateMietrechnungen(unittest.TestCase):
    def test_company_via_wohnung_uses_property_financial_identity(self):
        def get_value(doctype, name, fieldname, **kwargs):
            if doctype == "Wohnung":
                return "IMMO-1"
            if doctype == "Immobilie":
                self.assertTrue(kwargs.get("as_dict"))
                return frappe._dict(
                    kostenstelle="CC-A",
                    haupt_bank_account=None,
                    konto=None,
                    kassenkonto=None,
                )
            if doctype == "Cost Center":
                return "COMP-A"
            self.fail(f"Unerwarteter Lookup: {doctype} {name} {fieldname}")

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", side_effect=get_value),
            patch.object(generate_mietrechnungen.frappe, "get_all", return_value=[]),
        ):
            company = generate_mietrechnungen._company_via_wohnung("WHG-1")

        self.assertEqual(company, "COMP-A")

    def test_company_via_wohnung_inherits_identity_from_parent_property(self):
        def get_value(doctype, name, _fieldname, **_kwargs):
            if doctype == "Wohnung":
                return "IMMO-CHILD"
            if doctype == "Immobilie" and name == "IMMO-CHILD":
                return frappe._dict(
                    kostenstelle=None,
                    haupt_bank_account=None,
                    konto=None,
                    kassenkonto=None,
                    parent_immobilie="IMMO-ROOT",
                )
            if doctype == "Immobilie" and name == "IMMO-ROOT":
                return frappe._dict(
                    kostenstelle="CC-A",
                    haupt_bank_account=None,
                    konto=None,
                    kassenkonto=None,
                    parent_immobilie=None,
                )
            if doctype == "Cost Center":
                return "COMP-A"
            self.fail(f"Unerwarteter Lookup: {doctype} {name}")

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", side_effect=get_value),
            patch.object(generate_mietrechnungen.frappe, "get_all", return_value=[]),
        ):
            company = generate_mietrechnungen._company_via_wohnung("WHG-1")

        self.assertEqual(company, "COMP-A")

    def test_company_via_wohnung_rejects_conflicting_property_links(self):
        def get_value(doctype, name, fieldname, **_kwargs):
            if doctype == "Wohnung":
                return "IMMO-1"
            if doctype == "Immobilie":
                return frappe._dict(
                    kostenstelle="CC-A",
                    haupt_bank_account=None,
                    konto="BANK-B",
                    kassenkonto=None,
                )
            if doctype == "Cost Center":
                return "COMP-A"
            if doctype == "Account":
                return "COMP-B"
            self.fail(f"Unerwarteter Lookup: {doctype} {name} {fieldname}")

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", side_effect=get_value),
            patch.object(generate_mietrechnungen.frappe, "get_all", return_value=[]),
            self.assertRaises(frappe.ValidationError),
        ):
            generate_mietrechnungen._company_via_wohnung("WHG-1")

    def test_company_via_wohnung_does_not_guess_in_multi_company_site(self):
        def get_value(doctype, _name, _fieldname, **_kwargs):
            if doctype == "Wohnung":
                return "IMMO-1"
            if doctype == "Immobilie":
                return frappe._dict(
                    kostenstelle=None,
                    haupt_bank_account=None,
                    konto=None,
                    kassenkonto=None,
                )
            self.fail(f"Unerwarteter Lookup: {doctype}")

        def get_all(doctype, **_kwargs):
            if doctype in {"Immobilie Bankkonto", "Immobilie Kassenkonto"}:
                return []
            if doctype == "Company":
                return ["COMP-A", "COMP-B"]
            self.fail(f"Unerwarteter Lookup: {doctype}")

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", side_effect=get_value),
            patch.object(generate_mietrechnungen.frappe, "get_all", side_effect=get_all),
        ):
            company = generate_mietrechnungen._company_via_wohnung("WHG-1")

        self.assertIsNone(company)

    def test_invoice_exists_scopes_every_lookup_to_company(self):
        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(
                generate_mietrechnungen,
                "_locked_invoice_guard_rows",
                return_value=[],
            ) as guard_rows,
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 7, 1),
                "MV-1",
                "Miete",
                company="COMP-1",
                wohnung="WHG-1",
            )

        self.assertFalse(exists)
        self.assertEqual(guard_rows.call_args.kwargs["company"], "COMP-1")
        self.assertEqual(guard_rows.call_args.kwargs["customer"], "CUST-1")

    def test_invoice_exists_still_recognizes_regular_invoice(self):
        invoice = frappe._dict(
            name="SINV-REGULAR",
            mietabrechnung_id="MV-1|07/2026",
            wohnung="WHG-1",
            remarks="Miete 07/2026",
            is_return=0,
            posting_date=date(2026, 7, 1),
        )

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(generate_mietrechnungen, "_locked_invoice_guard_rows", return_value=[invoice]),
            patch.object(generate_mietrechnungen, "_locked_linked_return_rows", return_value=[]),
            patch.object(
                generate_mietrechnungen.frappe.db,
                "sql",
                return_value=[frappe._dict(parent="SINV-REGULAR", amount=500)],
            ),
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 7, 1),
                "MV-1",
                "Miete",
                company="COMP-1",
                wohnung="WHG-1",
            )

        self.assertTrue(exists)

    def test_invoice_exists_does_not_reuse_invoice_of_second_contract_for_same_customer(self):
        invoice = frappe._dict(
            name="SINV-MV-1",
            mietabrechnung_id="MV-1|07/2026",
            wohnung="WHG-1",
            remarks="Miete 07/2026",
            is_return=0,
            posting_date=date(2026, 7, 1),
        )

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(generate_mietrechnungen, "_locked_invoice_guard_rows", return_value=[invoice]),
            patch.object(generate_mietrechnungen.frappe.db, "sql") as sql,
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-SAME",
                date(2026, 7, 1),
                "MV-2",
                "Miete",
                company="COMP-1",
                wohnung="WHG-2",
            )

        self.assertFalse(exists)
        sql.assert_not_called()

    def test_invoice_exists_recognizes_legacy_invoice_only_for_exact_wohnung(self):
        invoice = frappe._dict(
            name="SINV-LEGACY",
            mietabrechnung_id=None,
            wohnung="WHG-1",
            remarks="Miete 07/2026",
            is_return=0,
            posting_date=date(2026, 7, 1),
        )

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(generate_mietrechnungen, "_locked_invoice_guard_rows", return_value=[invoice]),
            patch.object(generate_mietrechnungen, "_locked_linked_return_rows", return_value=[]),
            patch.object(
                generate_mietrechnungen.frappe.db,
                "sql",
                return_value=[frappe._dict(parent="SINV-LEGACY", amount=500)],
            ),
        ):
            self.assertTrue(
                generate_mietrechnungen._invoice_exists(
                    "CUST-SAME",
                    date(2026, 7, 1),
                    "MV-1",
                    "Miete",
                    company="COMP-1",
                    wohnung="WHG-1",
                )
            )
            self.assertFalse(
                generate_mietrechnungen._invoice_exists(
                    "CUST-SAME",
                    date(2026, 7, 1),
                    "MV-2",
                    "Miete",
                    company="COMP-1",
                    wohnung="WHG-2",
                )
            )

    def test_invoice_exists_finds_later_correction_replacement_by_structured_id(self):
        replacement = frappe._dict(
            name="SINV-REPLACEMENT",
            mietabrechnung_id="MV-1|05/2026",
            wohnung="WHG-1",
            remarks="[KORREKTUR] [TYPE:Miete] [MV:MV-1] 05/2026",
            is_return=0,
            posting_date=date(2026, 7, 30),
        )

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(
                generate_mietrechnungen,
                "_locked_invoice_guard_rows",
                return_value=[replacement],
            ) as guard_rows,
            patch.object(generate_mietrechnungen, "_locked_linked_return_rows", return_value=[]),
            patch.object(
                generate_mietrechnungen.frappe.db,
                "sql",
                return_value=[frappe._dict(parent="SINV-REPLACEMENT", amount=520)],
            ),
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 5, 1),
                "MV-1",
                "Miete",
                company="COMP-1",
                wohnung="WHG-1",
            )

        self.assertTrue(exists)
        self.assertEqual(guard_rows.call_args.kwargs["target_id"], "MV-1|05/2026")
        self.assertEqual(guard_rows.call_args.kwargs["month_start"], date(2026, 5, 1))

    def test_invoice_exists_uses_net_effect_of_original_and_return(self):
        original = frappe._dict(
            name="SINV-ORIGINAL",
            mietabrechnung_id="MV-1|05/2026",
            wohnung="WHG-1",
            remarks="Miete 05/2026",
            is_return=0,
            posting_date=date(2026, 5, 1),
        )
        credit = frappe._dict(
            name="SINV-CREDIT",
            mietabrechnung_id=None,
            wohnung="WHG-1",
            remarks="[KORREKTUR-STORNO] [TYPE:Miete] [MV:MV-1] 05/2026",
            docstatus=1,
            is_return=1,
            return_against="SINV-ORIGINAL",
            posting_date=date(2026, 7, 30),
        )

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(
                generate_mietrechnungen,
                "_locked_invoice_guard_rows",
                return_value=[original, credit],
            ),
            patch.object(
                generate_mietrechnungen,
                "_locked_linked_return_rows",
                return_value=[credit],
            ),
            patch.object(
                generate_mietrechnungen.frappe.db,
                "sql",
                return_value=[
                    frappe._dict(parent="SINV-ORIGINAL", amount=500),
                    frappe._dict(parent="SINV-CREDIT", amount=-500),
                ],
            ),
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 5, 1),
                "MV-1",
                "Miete",
                company="COMP-1",
                wohnung="WHG-1",
            )

        self.assertFalse(exists)

    def test_invoice_exists_ignores_draft_return_for_submitted_invoice(self):
        original = frappe._dict(
            name="SINV-ORIGINAL",
            mietabrechnung_id="MV-1|05/2026",
            wohnung="WHG-1",
            remarks="Miete 05/2026",
            docstatus=1,
            is_return=0,
            posting_date=date(2026, 5, 1),
        )
        draft_credit = frappe._dict(
            name="SINV-DRAFT-CREDIT",
            mietabrechnung_id="MV-1|05/2026",
            wohnung="WHG-1",
            remarks="[KORREKTUR-STORNO] [TYPE:Miete] [MV:MV-1] 05/2026",
            docstatus=0,
            is_return=1,
            return_against="SINV-ORIGINAL",
            posting_date=date(2026, 7, 30),
        )

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(
                generate_mietrechnungen,
                "_locked_invoice_guard_rows",
                return_value=[original, draft_credit],
            ),
            patch.object(
                generate_mietrechnungen,
                "_locked_linked_return_rows",
                return_value=[],
            ),
            patch.object(
                generate_mietrechnungen.frappe.db,
                "sql",
                return_value=[frappe._dict(parent="SINV-ORIGINAL", amount=500)],
            ) as sql,
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 5, 1),
                "MV-1",
                "Miete",
                company="COMP-1",
                wohnung="WHG-1",
            )

        self.assertTrue(exists)
        self.assertEqual(sql.call_args.args[1]["parents"], ("SINV-ORIGINAL",))
        self.assertIn("(si.is_return = 0 OR si.docstatus = 1)", sql.call_args.args[0])

    def test_invoice_guard_query_is_company_scoped_current_read(self):
        with patch.object(generate_mietrechnungen.frappe.db, "sql", return_value=[]) as sql:
            rows = generate_mietrechnungen._locked_invoice_guard_rows(
                company="COMP-1",
                customer="CUST-1",
                month_start=date(2026, 5, 1),
                month_end=date(2026, 5, 31),
                target_id="MV-1|05/2026",
                legacy_marker="[TYPE:Miete] [MV:MV-1] 05/2026",
                include_drafts=True,
                has_structured_id=True,
                has_wohnung=True,
            )

        self.assertEqual(rows, [])
        query = sql.call_args.args[0]
        params = sql.call_args.args[1]
        self.assertIn("FOR UPDATE", query)
        self.assertIn("si.mietabrechnung_id = %(target_id)s", query)
        self.assertIn("si.company = %(company)s", query)
        self.assertIn("si.docstatus", query)
        self.assertEqual(params["company"], "COMP-1")
        self.assertEqual(params["target_id"], "MV-1|05/2026")

    def test_mietvertrag_lock_uses_for_update_and_returns_fresh_row(self):
        fresh = frappe._dict(
            name="MV-1",
            kunde="CUST-NEW",
            wohnung="WHG-1",
            immobilie="IMM-1",
            von=date(2026, 1, 1),
            bis=None,
        )
        with patch.object(generate_mietrechnungen.frappe.db, "sql", return_value=[fresh]) as sql:
            result = generate_mietrechnungen._lock_and_reload_mietvertrag("MV-1")

        self.assertIs(result, fresh)
        self.assertIn("FOR UPDATE", sql.call_args.args[0])
        self.assertEqual(sql.call_args.args[1], ("MV-1",))
        self.assertTrue(sql.call_args.kwargs["as_dict"])

    def test_locked_property_identity_uses_current_cost_center_and_company(self):
        queries = []

        def sql(query, params, as_dict=False):
            queries.append((query, params, as_dict))
            if "FROM `tabWohnung`" in query:
                return [frappe._dict(name="WHG-1", immobilie="IMM-CURRENT")]
            if "FROM `tabImmobilie`" in query:
                return [
                    frappe._dict(
                        name="IMM-CURRENT",
                        kostenstelle="CC-CURRENT",
                        erworben_am=date(2025, 1, 1),
                    )
                ]
            self.fail(f"Unerwartete SQL-Abfrage: {query}")

        with (
            patch.object(generate_mietrechnungen.frappe.db, "sql", side_effect=sql),
            patch.object(
                generate_mietrechnungen,
                "_company_via_wohnung",
                return_value="COMP-CURRENT",
            ) as company_via_wohnung,
            patch.object(
                generate_mietrechnungen.frappe.db,
                "get_value",
                return_value=frappe._dict(
                    name="CC-CURRENT",
                    company="COMP-CURRENT",
                    disabled=0,
                    is_group=0,
                ),
            ) as get_value,
        ):
            identity = generate_mietrechnungen._lock_property_booking_identity("WHG-1")

        self.assertEqual(identity.immobilie, "IMM-CURRENT")
        self.assertEqual(identity.cost_center, "CC-CURRENT")
        self.assertEqual(identity.company, "COMP-CURRENT")
        self.assertEqual([params for _query, params, _as_dict in queries], [("WHG-1",), ("IMM-CURRENT",)])
        self.assertTrue(all("FOR UPDATE" in query for query, _params, _as_dict in queries))
        company_via_wohnung.assert_called_once_with("WHG-1", for_update=True)
        self.assertTrue(get_value.call_args.kwargs["for_update"])

    def test_locked_property_identity_fails_closed_without_cost_center(self):
        def sql(query, _params, as_dict=False):
            self.assertTrue(as_dict)
            if "FROM `tabWohnung`" in query:
                return [frappe._dict(name="WHG-1", immobilie="IMM-1")]
            if "FROM `tabImmobilie`" in query:
                return [
                    frappe._dict(
                        name="IMM-1",
                        kostenstelle=None,
                        erworben_am=None,
                    )
                ]
            self.fail(f"Unerwartete SQL-Abfrage: {query}")

        with (
            patch.object(generate_mietrechnungen.frappe.db, "sql", side_effect=sql),
            patch.object(generate_mietrechnungen, "_company_via_wohnung") as company_via_wohnung,
            self.assertRaisesRegex(frappe.ValidationError, "keine Kostenstelle"),
        ):
            generate_mietrechnungen._lock_property_booking_identity("WHG-1")

        company_via_wohnung.assert_not_called()

    def test_booking_identity_rejects_stale_contract_property_after_locked_current_read(self):
        current_contract = frappe._dict(
            name="MV-1",
            kunde="CUST-CURRENT",
            wohnung="WHG-CURRENT",
            immobilie="IMM-STALE",
            von=date(2026, 1, 1),
            bis=None,
        )
        current_property = frappe._dict(
            wohnung="WHG-CURRENT",
            immobilie="IMM-CURRENT",
            cost_center="CC-CURRENT",
            company="COMP-CURRENT",
            immobilie_erworben_am=None,
        )

        with (
            patch.object(
                generate_mietrechnungen,
                "_lock_and_reload_mietvertrag",
                return_value=current_contract,
            ),
            patch.object(
                generate_mietrechnungen,
                "_lock_property_booking_identity",
                return_value=current_property,
            ),
            self.assertRaisesRegex(frappe.ValidationError, "IMM-STALE"),
        ):
            generate_mietrechnungen.lock_mietvertrag_booking_identity("MV-1")

    def test_kunde_des_vertrags_prefers_direct_customer(self):
        row = frappe._dict(name="MV-DIREKT", kunde="CUST-DIREKT")

        with patch.object(generate_mietrechnungen.frappe.db, "get_value") as get_value:
            self.assertEqual(generate_mietrechnungen._kunde_des_vertrags(row), "CUST-DIREKT")

        get_value.assert_not_called()

    def test_kunde_des_vertrags_does_not_fall_back_to_contact_customer(self):
        row = frappe._dict(name="MV-FALLBACK", kunde=None)

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value="CONTACT-1") as get_value,
            patch.object(generate_mietrechnungen.frappe, "get_all", return_value=["CUST-1"]) as get_all,
        ):
            self.assertIsNone(generate_mietrechnungen._kunde_des_vertrags(row))

        get_value.assert_not_called()
        get_all.assert_not_called()

    def test_kunde_des_vertrags_returns_none_without_contract_customer(self):
        row = frappe._dict(name="MV-NO-CUSTOMER", kunde=None)

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value") as get_value,
            patch.object(generate_mietrechnungen.frappe, "get_all") as get_all,
        ):
            self.assertIsNone(generate_mietrechnungen._kunde_des_vertrags(row))
        get_value.assert_not_called()
        get_all.assert_not_called()

    def test_immobilie_without_erworben_am_is_active(self):
        with patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value=None):
            self.assertTrue(
                generate_mietrechnungen._immobilie_active_for_month(
                    "IMM-ALT",
                    date(2026, 12, 1),
                )
            )

    def test_immobilie_with_erworben_am_in_month_is_active(self):
        with patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value=date(2026, 1, 31)):
            self.assertTrue(
                generate_mietrechnungen._immobilie_active_for_month(
                    "IMM-WARTESTR",
                    date(2026, 1, 1),
                )
            )

    def test_immobilie_with_erworben_am_after_month_is_inactive(self):
        with patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value=date(2026, 1, 1)):
            self.assertFalse(
                generate_mietrechnungen._immobilie_active_for_month(
                    "IMM-WARTESTR",
                    date(2025, 12, 1),
                )
            )
