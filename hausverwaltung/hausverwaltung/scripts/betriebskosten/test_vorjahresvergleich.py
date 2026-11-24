import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
    allocate_kosten_auf_wohnungen,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.rounding import ROUNDING_METHOD_TENANT_ONLY
from hausverwaltung.hausverwaltung.scripts.betriebskosten.vorjahresvergleich import (
    get_vorjahresvergleich,
)


class TestVorjahresvergleich(unittest.TestCase):
    def setUp(self):
        self.original_user = frappe.session.user
        frappe.set_user("Administrator")
        frappe.db.savepoint("bk_vergleich")
        self.addCleanup(frappe.set_user, self.original_user)
        self.addCleanup(frappe.db.rollback, save_point="bk_vergleich")

        for suffix in ("A", "B"):
            self._insert("Immobilie", f"BK-Haus-{suffix}", kostenstelle=f"BK-KSt-{suffix}")
            self._insert("Wohnung", f"BK-Wohnung-{suffix}", immobilie=f"BK-Haus-{suffix}")
            self._insert(
                "Wohnungszustand", f"BK-Zustand-{suffix}", wohnung=f"BK-Wohnung-{suffix}",
                ab="2022-01-01", betriebskostenabrechnung_durch_vermieter=1,
                **{"größe": 60},
            )
            self._insert(
                "Betriebskostenabrechnung Immobilie", f"BK-Abrechnung-{suffix}",
                immobilie=f"BK-Haus-{suffix}", von="2024-02-29", bis="2024-06-30",
                stichtag="2024-06-15",
            )
        for art, verteilung in (
            ("Reinigung", "qm"), ("Neu", "qm"), ("Null", "qm"),
            ("Nur-Vorjahr", "qm"), ("Fest", "Festbetrag"),
        ):
            self._insert(
                "Betriebskostenart", f"BK-{art}", name1=f"BK-{art}", kategorie="Betriebskosten",
                konto=f"BK-Konto-{art}", verteilung=verteilung,
            )
        self._expense("Rechnung", "Reinigung", 130, "2024-02-29", posting="2023-12-31")
        self._expense("Gutschrift", "Reinigung", -20, "2024-04-01")
        self._expense("Journal", "Reinigung", 10, "2024-05-01", doctype="Journal Entry")
        self._expense("Vorjahr", "Reinigung", 80, "2023-02-28")
        self._expense("Nicht-wirksam", "Reinigung", 900, "2024-02-28", posting="2024-03-01")
        self._expense("Storniert", "Reinigung", 800, "2024-03-01", cancelled=1)
        self._expense("Fremd", "Reinigung", 700, "2024-03-01", suffix="B")
        self._expense("Neu", "Neu", 17, "2024-03-01")
        self._expense("Null-aktuell", "Null", 15, "2024-03-01")
        self._expense("Null-Vorjahr", "Null", 10, "2023-03-01")
        self._expense("Null-Gutschrift", "Null", -10, "2023-03-02")
        self._expense("Nur-Vorjahr", "Nur-Vorjahr", 9, "2023-03-01")
        self._expense("Wohnung", "Fest", 22, "2024-03-02", wohnung="BK-Wohnung-A")
        self._insert("Customer", "BK-Debitor-A", customer_name="BK-Debitor-A")
        self._insert(
            "Mietvertrag", "BK-Vertrag-A", wohnung="BK-Wohnung-A", kunde="BK-Debitor-A",
            immobilie="BK-Haus-A", von="2022-01-01",
        )
        self._insert(
            "Betriebskosten Festbetrag", "BK-Festbetrag-A", parent="BK-Vertrag-A",
            parenttype="Mietvertrag", parentfield="festbetraege",
            betriebskostenart="BK-Fest", betrag=31, gueltig_von="2024-06-01", gueltig_bis="2024-07-01",
        )

    def _insert(self, doctype, name, **fields):
        # Isolierte Buchungsdaten ohne Belegerstellung oder Abrechnungs-Submit.
        frappe.get_doc({"doctype": doctype, "name": name, **fields}).db_insert()

    def _expense(
        self, name, art, amount, effective, *, posting=None, suffix="A",
        doctype="Purchase Invoice", cancelled=0, wohnung=None,
    ):
        posting = posting or effective
        reference = f"BK-Beleg-{name}"
        self._insert(doctype, reference, posting_date=posting, custom_wertstellungsdatum=effective)
        self._insert(
            "GL Entry", f"BK-GL-{name}", account=f"BK-Konto-{art}", cost_center=f"BK-KSt-{suffix}",
            posting_date=posting, voucher_type=doctype, voucher_no=reference, is_cancelled=cancelled,
            debit=max(amount, 0), credit=max(-amount, 0), wohnung=wohnung,
        )

    def test_period_totals_reconcile_to_both_evidence_and_allocation(self):
        with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
            report = get_vorjahresvergleich("BK-Abrechnung-A")
        for call in sql.call_args_list:
            query = call.args[0] if call.args else call.kwargs["query"]
            self.assertRegex(str(query).lstrip().upper(), r"^(SELECT|SHOW|DESC|WITH)\b")

        self.assertEqual(report["immobilie"], "BK-Haus-A")
        self.assertEqual(report["aktuell"], {"von": "2024-02-29", "bis": "2024-06-30", "stichtag": "2024-06-15"})
        self.assertEqual(report["vorjahr"], {"von": "2023-02-28", "bis": "2023-06-30", "stichtag": "2023-06-15"})
        rows = {row["kostenart"]: row for row in report["kostenarten"]}
        for period in ("aktuell", "vorjahr"):
            allocated = allocate_kosten_auf_wohnungen(**report[period], immobilie="BK-Haus-A")
            self.assertEqual(
                {art: row[period]["betrag"] for art, row in rows.items() if row[period] is not None},
                allocated["matrix"]["BK-Wohnung-A"],
            )
            for row in rows.values():
                basis = row[period]
                if basis is not None:
                    total = sum(Decimal(str(entry["betrag"])) for entry in basis["belege"])
                    self.assertEqual(total + Decimal(str(basis["rundung"])), Decimal(str(basis["betrag"])))

        cleaning = rows["BK-Reinigung"]
        self.assertEqual((cleaning["aktuell"]["betrag"], cleaning["vorjahr"]["betrag"]), (120, 80))
        self.assertEqual((cleaning["differenz"], cleaning["prozent"]), (40, 50))
        self.assertEqual(
            [(r["beleg"], r["doctype"], r["betrag"], r["wirksam_von"]) for r in cleaning["aktuell"]["belege"]],
            [
                ("BK-Beleg-Rechnung", "Purchase Invoice", 130, "2024-02-29"),
                ("BK-Beleg-Gutschrift", "Purchase Invoice", -20, "2024-04-01"),
                ("BK-Beleg-Journal", "Journal Entry", 10, "2024-05-01"),
            ],
        )
        self.assertIsNone(rows["BK-Neu"]["vorjahr"])
        self.assertIsNone(rows["BK-Neu"]["differenz"])
        self.assertIsNone(rows["BK-Neu"]["prozent"])
        self.assertEqual(rows["BK-Null"]["vorjahr"]["betrag"], 0)
        self.assertEqual(rows["BK-Null"]["differenz"], 15)
        self.assertIsNone(rows["BK-Null"]["prozent"])
        self.assertEqual(rows["BK-Nur-Vorjahr"]["differenz"], -9)
        self.assertEqual(rows["BK-Nur-Vorjahr"]["prozent"], -100)
        self.assertEqual(
            [(r["art"], r["beleg"], r["betrag"]) for r in rows["BK-Fest"]["aktuell"]["belege"]],
            [("wohnung", "BK-Beleg-Wohnung", 22), ("vertrag", "BK-Vertrag-A", 30)],
        )

    def test_permissions_cover_head_property_and_both_periods_of_evidence(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            get_vorjahresvergleich("BK-Abrechnung-A")
        frappe.set_user("Administrator")
        has_permission = frappe.has_permission
        for target in (
            ("Immobilie", "BK-Haus-B"),
            ("Purchase Invoice", "BK-Beleg-Vorjahr"),
            ("GL Entry", "BK-GL-Rechnung"),
            ("GL Entry", "BK-GL-Vorjahr"),
        ):
            with self.subTest(target=target):
                def check(doctype, *args, **kwargs):
                    doc = kwargs.get("doc")
                    if (doctype, getattr(doc, "name", doc)) == target:
                        return False
                    return has_permission(doctype, *args, **kwargs)

                name = "BK-Abrechnung-B" if target[0] == "Immobilie" else "BK-Abrechnung-A"
                with patch.object(frappe, "has_permission", side_effect=check):
                    with self.assertRaises(frappe.PermissionError) as denied:
                        get_vorjahresvergleich(name)
                self.assertNotIn(target[1], str(denied.exception))

    def test_subcent_contract_amount_uses_head_precision_before_comparison(self):
        for year, amount, end in ((2023, 0.04, "07-09"), (2024, 0.01, "06-30")):
            self._insert(
                "Betriebskosten Festbetrag", f"BK-Teilcent-{year}", parent="BK-Vertrag-A",
                parenttype="Mietvertrag", parentfield="festbetraege",
                bezeichnung="BK-Teilcent", betrag=amount,
                gueltig_von=f"{year}-06-30", gueltig_bis=f"{year}-{end}",
            )

        head = frappe.get_doc("Betriebskostenabrechnung Immobilie", "BK-Abrechnung-A")
        with patch(
            "hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.get_bk_rounding_method",
            return_value=ROUNDING_METHOD_TENANT_ONLY,
        ):
            report = get_vorjahresvergleich(head.name)
            row = next(row for row in report["kostenarten"] if row["kostenart"] == "BK-Teilcent")
            prior = allocate_kosten_auf_wohnungen(**report["vorjahr"], immobilie=head.immobilie)
            self.assertEqual(prior["matrix"]["BK-Wohnung-A"]["BK-Teilcent"], 0.004)
            for period in ("aktuell", "vorjahr"):
                head.update(report[period])
                head._populate_summary()
                expected = next(cost.betrag for cost in head.kosten_pro_art if cost.bezeichnung == "BK-Teilcent")
                self.assertEqual(row[period]["betrag"], expected)

        self.assertEqual(row["vorjahr"]["betrag"], 0)
        self.assertEqual(len(row["vorjahr"]["belege"]), 1)
        self.assertEqual(row["differenz"], 0.01)
        self.assertIsNone(row["prozent"])

    def test_misbooked_foreign_apartment_never_appears_in_error(self):
        frappe.db.set_value("GL Entry", "BK-GL-Wohnung", "wohnung", "BK-Wohnung-B")
        with self.assertRaises(frappe.ValidationError) as failed:
            get_vorjahresvergleich("BK-Abrechnung-A")
        self.assertNotIn("BK-Wohnung-B", str(failed.exception))
        self.assertTrue(all("BK-Wohnung-B" not in str(msg) for msg in frappe.local.message_log))
