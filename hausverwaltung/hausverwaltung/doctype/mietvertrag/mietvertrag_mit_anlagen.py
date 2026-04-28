from frappe.utils.safe_eval import safe_eval
from PyPDF2 import PdfMerger
import frappe
import os


import pdfkit

def _render_html_to_pdf(html, output_path):
    pdfkit.from_string(html, output_path, options={"quiet": ""})


@frappe.whitelist()
def generiere_mietvertrag_mit_anlagen(docname):
    builder = frappe.get_doc("Mietvertragsbuilder", docname)

    # 1. HTML für Seite 9 aus Child-Tabelle bauen
    seite_9_html = "<h2>Weitere Bestimmungen</h2>"
    dateianhang_pfade = []

    for baustein in builder.textbausteine:
        sichtbar = True
        if baustein.sichtbar_wenn:
            try:
                sichtbar = safe_eval(baustein.sichtbar_wenn, {"doc": builder.as_dict()})
            except:
                sichtbar = False

        if sichtbar:
            seite_9_html += f"<h4>{baustein.titel}</h4>{baustein.text_html or ''}"
            if baustein.datei:
                pfad = frappe.get_site_path("public", baustein.datei)
                if os.path.exists(pfad):
                    dateianhang_pfade.append(pfad)

    # 2. Seite 9 als PDF rendern (z. B. über HTML-to-PDF)
    seite_9_pdf = f"/tmp/{builder.name}_seite9.pdf"
    _render_html_to_pdf(seite_9_html, seite_9_pdf)  # eigene Funktion, siehe unten

    # 3. Hauptvertrag generieren
    haupt_pdf_path = builder.get_print("Mietvertragsbuilder – Hauptteil", as_file=True).name
    haupt_pdf = frappe.get_site_path("public", "files", haupt_pdf_path)

    # 4. PDFs zusammenfügen
    merger = PdfMerger()
    merger.append(haupt_pdf)
    merger.append(seite_9_pdf)

    for anhang in dateianhang_pfade:
        merger.append(anhang)

    final_path = frappe.get_site_path("public", "files", f"{builder.name}_komplett.pdf")
    merger.write(final_path)
    merger.close()

    frappe.get_doc({
        "doctype": "File",
        "file_url": f"/files/{builder.name}_komplett.pdf",
        "attached_to_doctype": "Mietvertragsbuilder",
        "attached_to_name": builder.name
    }).insert()

    return f"/files/{builder.name}_komplett.pdf"