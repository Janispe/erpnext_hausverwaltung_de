"""Exercise the cockpit endpoints against real ERPNext and optional ALYF."""

import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

import frappe
from frappe.utils import add_days, cint, getdate, nowdate
from lxml import etree
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit as cockpit
from hausverwaltung.hausverwaltung.services import structured_invoice
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture

CII_XML = Path(__file__).with_name("test_fixtures").joinpath("cii.xml").read_bytes()
UBL_XML = b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>'


def make_pdf(xml=None, *, af_only=False):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if xml is not None:
        writer.add_attachment("factur-x.xml", xml)
        catalog = writer.root_object
        file_spec = catalog["/Names"]["/EmbeddedFiles"]["/Names"][1]
        file_spec.get_object()[NameObject("/AFRelationship")] = NameObject("/Alternative")
        catalog[NameObject("/AF")] = ArrayObject([file_spec])
        if af_only:
            del catalog["/Names"]
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class TestStructuredInvoiceDetection(unittest.TestCase):
    def test_formats_without_optional_app(self):
        self.assertEqual(structured_invoice.detect(make_pdf(), "normal.pdf"), ("pdf", None))
        self.assertEqual(structured_invoice.detect(UBL_XML, "ubl.xml"), ("ubl", UBL_XML))
        self.assertEqual(structured_invoice.detect(CII_XML, "cii.xml"), ("cii", CII_XML))
        self.assertEqual(structured_invoice.detect(make_pdf(CII_XML), "factur-x.pdf"), ("cii", CII_XML))
        self.assertEqual(structured_invoice.detect(make_pdf(CII_XML, af_only=True), "af-only.pdf"), ("cii", CII_XML))
        with self.assertRaisesRegex(structured_invoice.StructuredInvoiceError, "fehlerhaft"):
            structured_invoice.detect(make_pdf(b"<broken"), "factur-x.pdf")
        with self.assertRaisesRegex(structured_invoice.StructuredInvoiceError, "installiert"):
            with patch.object(frappe, "get_installed_apps", return_value=["hausverwaltung"]):
                structured_invoice.parse(CII_XML, "cii.xml")


class TestStructuredInvoiceIntegration(unittest.TestCase):
    def setUp(self):
        if not (
            cint(frappe.conf.get("allow_tests"))
            and cint(frappe.conf.get("hv_isolated_integration_test"))
            and "eu_einvoice" in frappe.get_installed_apps()
        ):
            self.skipTest("Requires an isolated test site with ALYF eu_einvoice")

        previous_user = frappe.session.user
        frappe.set_user("Administrator")
        self.addCleanup(frappe.set_user, previous_user)
        self.token = "HV64-" + frappe.generate_hash(length=10)
        self.files = []
        frappe.db.savepoint("structured_invoice_test")
        self.addCleanup(self._rollback)

        self.company, self.cost_center, _, apartment, _ = fixture(compact=True)
        self.apartment = apartment.name
        self.company_name = frappe.db.get_value("Company", self.company, "company_name")
        expense = self._account("Expense")
        self.expense_type = frappe.get_doc({
            "doctype": "Kostenart nicht umlagefaehig", "name1": self.token,
            "konto": expense, "artikel": cockpit.ensure_default_service_item(),
        }).insert().name
        self.tax = self._account("Asset", "Tax")
        self.supplier_name = self.token + " Testlieferant"
        self.supplier = frappe.get_doc({
            "doctype": "Supplier", "supplier_name": self.supplier_name, "supplier_type": "Company",
            "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
        }).insert().name

    def _account(self, root_type, account_type=None):
        parent = frappe.db.get_value("Account", {
            "company": self.company, "root_type": root_type, "is_group": 1,
        }, "name")
        return frappe.get_doc({
            "doctype": "Account", "company": self.company, "account_name": f"{self.token}-{root_type}",
            "parent_account": parent, "account_type": account_type,
        }).insert().name

    def _rollback(self):
        frappe.set_user("Administrator")
        for url in self.files:
            Path(frappe.get_site_path(url.lstrip("/"))).unlink(missing_ok=True)
        frappe.db.rollback(save_point="structured_invoice_test")
        frappe.clear_cache()

    def _xml(self, *, suffix="", credit=False):
        return (
            CII_XML.replace(b"HV-TEST-NUMMER", (self.token + suffix).encode())
            .replace(b"HV-TEST-LIEFERANT", escape(self.supplier_name).encode())
            .replace(b"HV-TEST-FIRMA", escape(self.company_name).encode())
            .replace(b"20261124", getdate(nowdate()).strftime("%Y%m%d").encode())
            .replace(b"20261208", getdate(add_days(nowdate(), 14)).strftime("%Y%m%d").encode())
            .replace(b"<ram:TypeCode>380", b"<ram:TypeCode>381" if credit else b"<ram:TypeCode>380")
        )

    def _upload(self, content, extension):
        with (
            patch.object(frappe.local, "uploaded_file", content, create=True),
            patch.object(frappe.local, "uploaded_filename", self.token + extension, create=True),
        ):
            response = cockpit.upload_invoice_pdf()
        if response["is_new_file"]:
            self.files.append(response["file_url"])
        return response

    def _prepare(self, response):
        file_url = response["file_url"]
        preview = cockpit.preview_structured_invoice(file_url)
        self.assertEqual(preview["company"], self.company)
        self.assertEqual(preview["supplier"], self.supplier)
        self.assertEqual(preview["lines"][0]["name"], "Fensterreinigung")
        self.assertEqual(preview["due_date"], add_days(nowdate(), 14))
        self.assertFalse(frappe.db.exists("Purchase Invoice", {"bill_no": preview["number"]}))
        args = {
            "file_url": file_url, "digest": preview["digest"], "company": self.company,
            "supplier": self.supplier, "tax_accounts": [self.tax],
            "positionen": [{
                "kostenstelle": self.cost_center, "kostenart": self.expense_type, "wohnung": self.apartment,
                "umlagefaehig": "Kostenart nicht umlagefaehig",
            }],
        }
        return preview, args

    def _assert_draft(self, args, expected):
        result = cockpit.create_structured_invoice(**args)
        draft = frappe.get_doc("Purchase Invoice", result["name"])
        self.assertEqual((draft.docstatus, bool(draft.is_return)), (0, expected < 0))
        sign = 1 if expected > 0 else -1
        self.assertEqual((draft.net_total, draft.total_taxes_and_charges, draft.grand_total), (100 * sign, 19 * sign, expected))
        due_date = getdate(add_days(nowdate(), 14))
        self.assertEqual(draft.due_date, due_date)
        if expected > 0:
            self.assertEqual([(row.due_date, row.payment_amount) for row in draft.payment_schedule], [(due_date, expected)])
        self.assertEqual(draft.items[0].hv_kostenart, self.expense_type)
        self.assertEqual(draft.items[0].cost_center, self.cost_center)
        self.assertEqual(draft.items[0].wohnung, self.apartment)
        self.assertTrue(frappe.db.exists("File", {
            "file_url": args["file_url"], "is_private": 1, "attached_to_doctype": "Purchase Invoice",
            "attached_to_name": draft.name,
        }))

    def test_xml_and_pdf_credit_save_private_drafts(self):
        purchase = self._upload(self._xml(), ".xml")
        self.assertEqual(purchase["invoice_format"], "cii")
        preview, args = self._prepare(purchase)
        self.assertEqual(preview["profile"], "XRECHNUNG")
        self._assert_draft(args, 119)
        with self.assertRaisesRegex(frappe.ValidationError, "bereits eine Eingangsrechnung"):
            cockpit.create_structured_invoice(**args)
        # Different container and XML bytes, same business identity.
        other = self._upload(make_pdf(self._xml() + b"\n"), ".pdf")
        args["file_url"] = other["file_url"]
        args["digest"] = cockpit.preview_structured_invoice(other["file_url"])["digest"]
        with self.assertRaisesRegex(frappe.ValidationError, "bereits eine Eingangsrechnung"):
            cockpit.create_structured_invoice(**args)

        xml = self._xml(suffix="-CREDIT", credit=True).replace(
            b"#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0", b""
        )
        credit = self._upload(make_pdf(xml), ".pdf")
        self.assertEqual(credit["invoice_format"], "cii")
        preview, args = self._prepare(credit)
        self.assertEqual(preview["gross"], -119)
        self._assert_draft(args, -119)

    def test_mixed_taxes_require_manual_line_allocation(self):
        ns = structured_invoice.NS
        root = etree.fromstring(self._xml())
        trade = root.find("rsm:SupplyChainTradeTransaction", ns)
        line = deepcopy(trade.find("ram:IncludedSupplyChainTradeLineItem", ns))
        line.find(".//ram:LineID", ns).text = "2"
        line.find(".//ram:CategoryCode", ns).text = "E"
        line.find(".//ram:RateApplicablePercent", ns).text = "0"
        trade.insert(1, line)
        settlement = trade.find("ram:ApplicableHeaderTradeSettlement", ns)
        taxable = settlement.find("ram:ApplicableTradeTax", ns)
        exempt = deepcopy(taxable)
        exempt.find("ram:CalculatedAmount", ns).text = "0.00"
        exempt.find("ram:RateApplicablePercent", ns).text = "0"
        exempt.find("ram:CategoryCode", ns).text = "E"
        taxable.addnext(exempt)
        totals = settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", ns)
        for name in ("LineTotalAmount", "TaxBasisTotalAmount"):
            totals.find(f"ram:{name}", ns).text = "200.00"
        for name in ("GrandTotalAmount", "DuePayableAmount"):
            totals.find(f"ram:{name}", ns).text = "219.00"
        upload = self._upload(etree.tostring(root), ".xml")
        with self.assertRaisesRegex(frappe.ValidationError, "Steuergruppen.*manuelle Zuordnung je Position"):
            cockpit.preview_structured_invoice(upload["file_url"])

    def test_installments_require_manual_review(self):
        xml = self._xml().replace(
            b"</ram:SpecifiedTradePaymentTerms>",
            b"<ram:PartialPaymentAmount>59.50</ram:PartialPaymentAmount></ram:SpecifiedTradePaymentTerms>",
        )
        upload = self._upload(xml, ".xml")
        with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsbedingungen.*manuelle Prüfung"):
            cockpit.preview_structured_invoice(upload["file_url"])

    def test_bt20_discount_with_due_date_requires_manual_review(self):
        xml = self._xml().replace(
            b"Zahlbar innerhalb von 14 Tagen",
            b"#SKONTO#TAGE=10#PROZENT=2.00#&#10;Zahlbar innerhalb von 14 Tagen",
        )
        upload = self._upload(xml, ".xml")
        with self.assertRaisesRegex(frappe.ValidationError, "XRechnungs-Skonto.*manuelle Prüfung"):
            cockpit.preview_structured_invoice(upload["file_url"])

    def test_formats_totals_and_permissions(self):
        normal = self._upload(make_pdf(), ".pdf")
        self.assertEqual(normal["invoice_format"], "pdf")
        structured_invoice.require_ordinary_pdf(make_pdf(), "normal.pdf")
        ubl = self._upload(UBL_XML, ".xml")
        self.assertEqual(ubl["invoice_format"], "ubl")
        with self.assertRaisesRegex(frappe.ValidationError, "UBL-XRechnung erkannt.*manuell"):
            cockpit.preview_structured_invoice(ubl["file_url"])
        bad_totals = self._upload(self._xml().replace(b"119.00", b"120.00"), ".xml")
        with self.assertRaisesRegex(frappe.ValidationError, "Summenfehler"):
            cockpit.preview_structured_invoice(bad_totals["file_url"])
        unsupported = self._upload(self._xml().replace(b"xrechnung_3.0", b"xrechnung_0.0"), ".xml")
        with self.assertRaisesRegex(frappe.ValidationError, "E-Rechnungsprofil.*nicht unterstützt"):
            cockpit.preview_structured_invoice(unsupported["file_url"])
        _, args = self._prepare(self._upload(self._xml(), ".xml"))
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            cockpit.preview_structured_invoice(args["file_url"])
        with self.assertRaises(frappe.PermissionError):
            cockpit.create_structured_invoice(**args)
