"""Erstellt eine Beispiel-Serienbrief Vorlage mit einem PDF-Formular-Textbaustein.

Aufruf:
    bench execute hausverwaltung.hausverwaltung.scripts.create_sample_pdf_vorlage.execute
"""
from __future__ import annotations

from io import BytesIO

import frappe
from frappe.utils import today

# ---------------------------------------------------------------------------
# 1. PDF-Formular erzeugen (mit ausfüllbaren Feldern)
# ---------------------------------------------------------------------------

def _create_sample_pdf_form() -> bytes:
    """Erzeugt ein einfaches PDF-Formular mit Feldern: name, adresse, datum, betrag.

    Verwendet nur pypdf (keine externen Abhängigkeiten wie reportlab).
    """
    try:
        from pypdf import PdfWriter
        from pypdf.generic import (
            ArrayObject, DictionaryObject, DecodedStreamObject,
            NameObject, NumberObject, TextStringObject,
        )
    except ImportError:
        from PyPDF2 import PdfWriter
        from PyPDF2.generic import (
            ArrayObject, DictionaryObject, DecodedStreamObject,
            NameObject, NumberObject, TextStringObject,
        )

    writer = PdfWriter()
    # A4 in PDF points (72 dpi)
    page_w, page_h = 595.28, 841.89
    page = writer.add_blank_page(width=page_w, height=page_h)

    # -- Built-in Type1 fonts --
    f1 = DictionaryObject()
    f1.update({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    f2 = DictionaryObject()
    f2.update({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
    })
    f3 = DictionaryObject()
    f3.update({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica-Oblique"),
    })
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = writer._add_object(f1)
    fonts[NameObject("/F2")] = writer._add_object(f2)
    fonts[NameObject("/F3")] = writer._add_object(f3)
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources

    # -- Page content (text labels) --
    # PDF text operators: BT = begin text, ET = end text, Tf = font, Td = move, Tj = show
    content = (
        "BT /F2 16 Tf 85 770 Td (Musterformular - Mieterbescheinigung) Tj ET\n"
        "BT /F1 11 Tf 85 700 Td (Name des Mieters:) Tj ET\n"
        "BT /F1 11 Tf 85 660 Td (Adresse:) Tj ET\n"
        "BT /F1 11 Tf 85 620 Td (Datum:) Tj ET\n"
        "BT /F1 11 Tf 85 580 Td (Monatliche Miete EUR:) Tj ET\n"
        "BT /F1 11 Tf 85 530 Td (Kaution hinterlegt:) Tj ET\n"
        "BT /F3 9 Tf 85 50 Td (Dieses Formular wurde automatisch generiert.) Tj ET\n"
    )
    stream = DecodedStreamObject()
    stream.set_data(content.encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    # -- Form fields (text inputs + checkbox) --
    fields_arr: list = []
    text_field_defs = [
        ("name",    260, 696, 250, 18),
        ("adresse", 260, 656, 250, 18),
        ("datum",   260, 616, 150, 18),
        ("betrag",  260, 576, 150, 18),
    ]
    for fname, x, y, w, h in text_field_defs:
        field = DictionaryObject()
        field.update({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(fname),
            NameObject("/Rect"): ArrayObject([
                NumberObject(x), NumberObject(y),
                NumberObject(x + w), NumberObject(y + h),
            ]),
            NameObject("/F"): NumberObject(4),
            NameObject("/P"): page.indirect_reference,
        })
        fields_arr.append(writer._add_object(field))

    # Checkbox
    cb = DictionaryObject()
    cb.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Btn"),
        NameObject("/T"): TextStringObject("kaution_hinterlegt"),
        NameObject("/Rect"): ArrayObject([
            NumberObject(260), NumberObject(526),
            NumberObject(274), NumberObject(540),
        ]),
        NameObject("/F"): NumberObject(4),
        NameObject("/P"): page.indirect_reference,
    })
    fields_arr.append(writer._add_object(cb))

    # Annotations on page + AcroForm in catalog
    page[NameObject("/Annots")] = ArrayObject(fields_arr)
    acro_form = DictionaryObject()
    acro_form[NameObject("/Fields")] = ArrayObject(fields_arr)
    writer._root_object[NameObject("/AcroForm")] = acro_form

    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 2. Hauptskript
# ---------------------------------------------------------------------------

KATEGORIE_NAME = "Beispiel"
TEXTBAUSTEIN_NAME = "Mieterbescheinigung PDF"
VORLAGE_NAME = "Beispiel Vorlage mit PDF"


def _ensure_kategorie() -> str:
    if frappe.db.exists("Serienbrief Kategorie", KATEGORIE_NAME):
        return KATEGORIE_NAME

    doc = frappe.get_doc({
        "doctype": "Serienbrief Kategorie",
        "title": KATEGORIE_NAME,
        "is_group": 0,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def _upload_pdf(pdf_bytes: bytes, filename: str) -> str:
    """Speichert die PDF als Frappe File und gibt die file_url zurück."""
    existing = frappe.db.get_value("File", {"file_name": filename}, "file_url")
    if existing:
        return existing

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": pdf_bytes,
        "is_private": 1,
    })
    file_doc.save(ignore_permissions=True)
    return file_doc.file_url


def _ensure_textbaustein(pdf_file_url: str) -> str:
    if frappe.db.exists("Serienbrief Textbaustein", TEXTBAUSTEIN_NAME):
        print(f"  Textbaustein '{TEXTBAUSTEIN_NAME}' existiert bereits.")
        return TEXTBAUSTEIN_NAME

    doc = frappe.get_doc({
        "doctype": "Serienbrief Textbaustein",
        "title": TEXTBAUSTEIN_NAME,
        "content_type": "PDF Formular",
        "pdf_file": pdf_file_url,
        "pdf_flatten": 1,
        "pdf_field_mappings": [
            {
                "doctype": "Serienbrief PDF Feld Mapping",
                "pdf_field_name": "name",
                "value_path": "mieter.full_name",
                "fallback_value": "Max Mustermann",
                "value_type": "String",
            },
            {
                "doctype": "Serienbrief PDF Feld Mapping",
                "pdf_field_name": "adresse",
                "value_path": "wohnung.adresse_einzeilig",
                "fallback_value": "Musterstraße 1, 12345 Musterstadt",
                "value_type": "String",
            },
            {
                "doctype": "Serienbrief PDF Feld Mapping",
                "pdf_field_name": "datum",
                "value_path": "",
                "fallback_value": today(),
                "value_type": "Datum",
            },
            {
                "doctype": "Serienbrief PDF Feld Mapping",
                "pdf_field_name": "betrag",
                "value_path": "doc.grundmiete",
                "fallback_value": "500,00",
                "value_type": "String",
            },
        ],
        "standardpfade": [
            {
                "doctype": "Serienbrief Textbaustein Standardpfad",
                "startobjekt": "Mietvertrag",
            },
        ],
    })
    doc.insert(ignore_permissions=True)
    print(f"  Textbaustein '{doc.name}' erstellt.")
    return doc.name


def _ensure_text_baustein() -> str:
    """Einfacher Rich-Text Baustein als Anschreiben vor dem PDF."""
    name = "Beispiel Anschreiben"
    if frappe.db.exists("Serienbrief Textbaustein", name):
        return name

    doc = frappe.get_doc({
        "doctype": "Serienbrief Textbaustein",
        "title": name,
        "content_type": "Textbaustein (Rich Text)",
        "text_content": (
            "<h2>Mieterbescheinigung</h2>"
            "<p>Sehr geehrte Damen und Herren,</p>"
            "<p>anbei erhalten Sie die Mieterbescheinigung für das laufende Jahr.</p>"
            "<p>Mit freundlichen Grüßen<br>Ihre Hausverwaltung</p>"
        ),
    })
    doc.insert(ignore_permissions=True)
    print(f"  Textbaustein '{doc.name}' erstellt.")
    return doc.name


def _ensure_vorlage(text_baustein: str, pdf_baustein: str, kategorie: str) -> str:
    if frappe.db.exists("Serienbrief Vorlage", VORLAGE_NAME):
        print(f"  Vorlage '{VORLAGE_NAME}' existiert bereits.")
        return VORLAGE_NAME

    doc = frappe.get_doc({
        "doctype": "Serienbrief Vorlage",
        "title": VORLAGE_NAME,
        "haupt_verteil_objekt": "Mietvertrag",
        "kategorie": kategorie,
        "content_type": "Textbaustein (Rich Text)",
        "content_position": "Vor Bausteinen",
        "textbausteine": [
            {
                "doctype": "Serienbrief Vorlagenbaustein",
                "baustein": text_baustein,
            },
            {
                "doctype": "Serienbrief Vorlagenbaustein",
                "baustein": pdf_baustein,
            },
        ],
    })
    doc.insert(ignore_permissions=True)
    print(f"  Vorlage '{doc.name}' erstellt.")
    return doc.name


def execute():
    print("Erstelle Beispiel-Serienbrief Vorlage mit PDF-Formular ...")

    # Kategorie
    kategorie = _ensure_kategorie()
    print(f"  Kategorie: {kategorie}")

    # PDF erzeugen & hochladen
    pdf_bytes = _create_sample_pdf_form()
    pdf_url = _upload_pdf(pdf_bytes, "mieterbescheinigung_formular.pdf")
    print(f"  PDF hochgeladen: {pdf_url}")

    # Textbausteine
    text_baustein = _ensure_text_baustein()
    pdf_baustein = _ensure_textbaustein(pdf_url)

    # Vorlage
    vorlage = _ensure_vorlage(text_baustein, pdf_baustein, kategorie)

    frappe.db.commit()
    print(f"\nFertig! Vorlage '{vorlage}' kann jetzt in einem Serienbrief Durchlauf verwendet werden.")
