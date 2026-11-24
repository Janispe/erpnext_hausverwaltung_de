"""Format detection and optional ALYF v16 adapter for incoming e-invoices."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import PurePath

import frappe
from lxml import etree
from pypdf import PdfReader

CII = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
UBL = "urn:oasis:names:specification:ubl:schema:xsd:"
NS = {
    "rsm": CII,
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
XML_LIMIT = 5 * 1024 * 1024
INVOICE_XML_NAMES = {"factur-x.xml", "zugferd-invoice.xml", "zugferd.xml", "xrechnung.xml"}
MANUAL = (
    "Bitte die Rechnung im Buchen-Cockpit über „Eingangsrechnung“ manuell erfassen "
    "und den Originalbeleg am Entwurf anhängen oder eine unterstützte CII-Datei anfordern."
)


class StructuredInvoiceError(ValueError):
    """A format or invoice problem that requires visible user feedback."""


def _xml_root(content):
    if len(content) > XML_LIMIT:
        raise StructuredInvoiceError("Die eingebettete oder hochgeladene XML-Datei ist zu groß.")
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise StructuredInvoiceError("Die Rechnungs-XML ist fehlerhaft.") from exc
    if root.getroottree().docinfo.doctype:
        raise StructuredInvoiceError("Die Rechnungs-XML enthält eine unzulässige DTD.")
    return root


def _xml_format(root):
    if root.tag == f"{{{CII}}}CrossIndustryInvoice":
        return "cii"
    if root.tag in (f"{{{UBL}Invoice-2}}Invoice", f"{{{UBL}CreditNote-2}}CreditNote"):
        return "ubl"
    return "unsupported"


def _embedded_invoice(content):
    try:
        reader = PdfReader(BytesIO(content))
    except Exception:
        # Existing PDF extraction may handle PDFs pypdf cannot open.
        return None
    candidates = []
    try:
        attachments = list(reader.attachment_list)
        # PDF/A-3 can reference the file via /AF independently of the name tree.
        from pypdf.generic import EmbeddedFile

        catalog = reader.root_object
        for ref in catalog.get("/AF") or []:
            spec = ref.get_object()
            name = spec.get("/UF") or spec.get("/F")
            if name and spec.get("/EF"):
                attachments.append(EmbeddedFile(str(name), spec))
        for attachment in attachments:
            name = (attachment.alternative_name or attachment.name).lower()
            if not name.endswith(".xml"):
                continue
            known = PurePath(name).name in INVOICE_XML_NAMES
            try:
                xml = attachment.content
                root = _xml_root(xml)
            except StructuredInvoiceError:
                if known:
                    raise
                continue
            if known or _xml_format(root) != "unsupported":
                if xml not in candidates:
                    candidates.append(xml)
    except StructuredInvoiceError:
        raise
    except Exception as exc:
        raise StructuredInvoiceError("PDF-Anhänge konnten nicht sicher gelesen werden.") from exc
    if len(candidates) > 1:
        raise StructuredInvoiceError("Das PDF enthält mehrere unterschiedliche Rechnungs-XML-Dateien.")
    if candidates:
        return candidates[0]
    metadata = catalog.get("/Metadata")
    if metadata:
        try:
            xmp = metadata.get_object().get_data()
        except Exception:
            # Malformed XMP can occur in ordinary PDFs too.
            return None
        if b"pdfa:CrossIndustryDocument:invoice" in xmp:
            raise StructuredInvoiceError("Im ZUGFeRD-/Factur-X-PDF fehlt eine lesbare Rechnungs-XML.")
    return None


def detect(content, filename):
    """Return a format and the original XML bytes, without importing ALYF."""
    if b"%PDF-" in content[:1024]:
        xml = _embedded_invoice(content)
        if xml is None:
            return "pdf", None
    elif filename.lower().endswith(".xml") or content.lstrip().startswith((b"<", b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        xml = content
    else:
        raise StructuredInvoiceError("Bitte eine PDF- oder XML-Rechnung hochladen.")
    return _xml_format(_xml_root(xml)), xml


def read_file(file_url, *, private=False):
    from frappe.utils.file_manager import get_file

    filters = {"file_url": file_url}
    if private:
        filters["is_private"] = 1
        if not (file_url or "").startswith("/private/files/"):
            frappe.throw("Bitte den privaten Originalbeleg hochladen.", frappe.PermissionError)
    name = frappe.db.get_value("File", filters, "name", order_by="creation asc, name asc")
    if not name:
        frappe.throw("Die hochgeladene Datei wurde nicht gefunden.")
    source = frappe.get_doc("File", name)
    source.check_permission("read")
    _, content = get_file(file_url)
    return source, content.encode("utf-8") if isinstance(content, str) else content


def require_ordinary_pdf(content, filename):
    try:
        kind, _ = detect(content, filename)
        if kind != "pdf":
            raise StructuredInvoiceError(
                "Für strukturierte Rechnungen bitte die E-Rechnungsvorschau im Datei-Upload verwenden."
            )
    except StructuredInvoiceError as exc:
        frappe.throw(f"{exc} {MANUAL}")


def _text(node, path, default=""):
    return (node.findtext(path, default=default, namespaces=NS) or "").strip()


def _number(node, path, *, default=""):
    try:
        value = Decimal(_text(node, path, default))
        if value.is_finite() and abs(value) < Decimal("1e12"):
            return value
    except InvalidOperation:
        pass
    raise StructuredInvoiceError("Die Rechnung enthält einen fehlenden oder ungültigen Zahlenwert.")


def _money(node, path, *, default=""):
    value = _number(node, path, default=default)
    if value != value.quantize(Decimal("0.01")):
        raise StructuredInvoiceError("Rechnungsbeträge müssen auf Cent lauten.")
    return value


def _profile_and_validation(root):
    if "eu_einvoice" not in frappe.get_installed_apps():
        raise StructuredInvoiceError("Für den strukturierten Import muss ALYF eu_einvoice auf dieser Site installiert sein.")
    try:
        from eu_einvoice.schematron import get_validation_errors
        from eu_einvoice.utils import get_profile
    except ImportError as exc:
        raise StructuredInvoiceError("ALYF eu_einvoice ist nicht vollständig eingerichtet.") from exc
    guideline = _text(root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
    profile = get_profile(guideline)
    if profile is None:
        raise StructuredInvoiceError("Das E-Rechnungsprofil wird von ALYF nicht unterstützt.")
    return profile, get_validation_errors


def _invoice_data(root):
    header = root.find("rsm:ExchangedDocument", NS)
    trade = root.find("rsm:SupplyChainTradeTransaction", NS)
    agreement = trade.find("ram:ApplicableHeaderTradeAgreement", NS)
    settlement = trade.find("ram:ApplicableHeaderTradeSettlement", NS)
    totals = settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", NS)
    currency = _text(settlement, "ram:InvoiceCurrencyCode")
    if currency != "EUR":
        raise StructuredInvoiceError("Der Cockpit-Import unterstützt EUR-Rechnungen.")
    adjustments = ("AllowanceTotalAmount", "ChargeTotalAmount", "TotalPrepaidAmount", "RoundingAmount")
    if any(_money(totals, f"ram:{field}", default="0") for field in adjustments):
        raise StructuredInvoiceError("Kopfabschläge, Kopfzuschläge, Vorauszahlungen und Rundungsbeträge erfordern eine manuelle Erfassung.")

    kind = _text(header, "ram:TypeCode")
    if kind not in {"380", "381"}:
        raise StructuredInvoiceError("Der Rechnungstyp wird im Cockpit nicht unterstützt.")
    number = _text(header, "ram:ID")
    seller = _text(agreement, "ram:SellerTradeParty/ram:Name")
    buyer = _text(agreement, "ram:BuyerTradeParty/ram:Name")
    if not all((number, seller, buyer)) or len(number) > 140:
        raise StructuredInvoiceError("Rechnungsnummer, Lieferant oder Rechnungsempfänger fehlen oder sind ungültig.")
    date_value = _text(header, "ram:IssueDateTime/udt:DateTimeString[@format='102']")
    if len(date_value) != 8:
        raise StructuredInvoiceError("Das Rechnungsdatum muss im CII-Format JJJJMMTT vorliegen.")
    date = datetime.strptime(date_value, "%Y%m%d").date()
    net = _money(totals, "ram:TaxBasisTotalAmount")
    gross = _money(totals, "ram:GrandTotalAmount")
    total_tax = _money(totals, "ram:TaxTotalAmount[@currencyID='EUR']")
    multiplier = -1 if kind == "381" and gross > 0 else 1

    lines = []
    for line in trade.findall("ram:IncludedSupplyChainTradeLineItem", NS):
        line_tax = line.find("ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax", NS)
        lines.append({
            "name": _text(line, "ram:SpecifiedTradeProduct/ram:Name"),
            "description": _text(line, "ram:SpecifiedTradeProduct/ram:Description"),
            "quantity": _number(line, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"),
            "unit": line.find("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS).get("unitCode", ""),
            "net": multiplier * _money(line, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount"),
            "tax_rate": _number(line_tax, "ram:RateApplicablePercent", default="0"),
            "tax_category": _text(line_tax, "ram:CategoryCode"),
        })

    taxes = []
    for tax in settlement.findall("ram:ApplicableTradeTax", NS):
        if _text(tax, "ram:TypeCode") != "VAT":
            raise StructuredInvoiceError("Der Cockpit-Import unterstützt Umsatzsteuer.")
        category = _text(tax, "ram:CategoryCode")
        if category not in {"S", "Z", "E", "O"}:
            raise StructuredInvoiceError("Diese Umsatzsteuerkategorie erfordert eine manuelle steuerliche Zuordnung.")
        taxes.append({
            "basis": multiplier * _money(tax, "ram:BasisAmount"),
            "amount": multiplier * _money(tax, "ram:CalculatedAmount"),
            "rate": _number(tax, "ram:RateApplicablePercent", default="0"),
            "category": category,
            "exemption": _text(tax, "ram:ExemptionReason"),
        })
    is_return = kind == "381" or gross < 0
    if not lines or not taxes or (
        sum(line["net"] for line in lines) != multiplier * net
        or _money(totals, "ram:LineTotalAmount") != net
        or sum(tax["basis"] for tax in taxes) != multiplier * net
        or sum(tax["amount"] for tax in taxes) != multiplier * total_tax
        or net + total_tax != gross
        or _money(totals, "ram:DuePayableAmount") != gross
    ):
        raise StructuredInvoiceError("Summenfehler: Positionen, Netto, Steuer und Brutto stimmen nicht überein.")
    if is_return and (
        multiplier * net >= 0 or multiplier * gross >= 0
        or any(line["net"] > 0 for line in lines) or any(tax["amount"] > 0 for tax in taxes)
    ):
        raise StructuredInvoiceError("Die Gutschrift enthält unvereinbare Vorzeichen.")

    return {
        "number": number, "date": date.isoformat(), "currency": currency,
        "seller": seller, "buyer": buyer, "is_return": is_return,
        "seller_tax_id": _text(agreement, "ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']"),
        "lines": lines, "taxes": taxes, "net": multiplier * net,
        "tax": multiplier * total_tax, "gross": multiplier * gross,
    }


def parse(content, filename):
    kind, xml = detect(content, filename)
    if kind == "ubl":
        raise StructuredInvoiceError("UBL-XRechnung erkannt. Das Cockpit unterstützt CII-XRechnung und ZUGFeRD/Factur-X.")
    if kind != "cii":
        raise StructuredInvoiceError("Die Datei enthält keine unterstützte CII-Rechnung.")
    root = _xml_root(xml)
    profile, validate = _profile_and_validation(root)
    try:
        data = _invoice_data(root)
    except StructuredInvoiceError:
        raise
    except (ValueError, AttributeError) as exc:
        raise StructuredInvoiceError("In der CII-Rechnung fehlen Pflichtangaben oder sie sind ungültig.") from exc
    try:
        errors, warnings = validate(etree.tostring(root, encoding="unicode"), profile)
    except Exception as exc:
        raise StructuredInvoiceError("ALYF konnte das Rechnungsprofil nicht validieren.") from exc
    if errors:
        message = frappe.utils.escape_html(" ".join(errors[:5])[:1800])
        raise StructuredInvoiceError(f"Die Rechnung verletzt die Regeln für {profile.value}. {message}")
    return {**data, "profile": profile.value, "warnings": warnings}
