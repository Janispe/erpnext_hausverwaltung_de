"""House-management-specific presentation.

These optional adapters live with the application, never in mail_merge.
"""


def print_profile(run):
    if run.get("iteration_doctype") != "Betriebskostenabrechnung Mieter":
        return {}
    return {"css": CSS, "classes": "hv-bk-mieter-print", "options": {"page-size": "A4", "margin-top": "12mm", "margin-right": "12mm", "margin-bottom": "8mm", "margin-left": "20mm"}}


CSS = '\n\t\t\t@page {\n\t\t\t\tsize: A4;\n\t\t\t\tmargin: 12mm 12mm 8mm 20mm;\n\t\t\t}\n\t\t\tbody,\n\t\t\t.serienbrief-root.hv-bk-mieter-print,\n\t\t\t.print-format .serienbrief-root.hv-bk-mieter-print {\n\t\t\t\tfont-size: 10pt !important;\n\t\t\t\tline-height: 1.22;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print .sb-letterhead {\n\t\t\t\tmargin-top: 0.2cm;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print .sb-address-window {\n\t\t\t\tpadding-top: 2.2cm;\n\t\t\t\tfont-size: 9pt;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print .sb-sender {\n\t\t\t\tfont-size: 8pt;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print .sb-office-hours,\n\t\t\t.serienbrief-root.hv-bk-mieter-print .sb-return-address {\n\t\t\t\tfont-size: 7pt;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print .sb-date {\n\t\t\t\tmargin-top: 0.2cm;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print p {\n\t\t\t\tline-height: 1.22;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print .serienbrief-block {\n\t\t\t\tmargin-bottom: 6px;\n\t\t\t}\n\t\t\t.serienbrief-root.hv-bk-mieter-print table {\n\t\t\t\tline-height: 1.15;\n\t\t\t}\n\t\t\t'
