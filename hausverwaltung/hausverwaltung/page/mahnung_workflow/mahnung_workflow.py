"""Server-Side API für die Frappe Page ``mahnung-workflow``.

Die separate Mahnungsseite nutzt dieselbe Dunning-Draft-Logik wie der produktive
OP-Workflow. Submit, Buchung der Mahngebühr und Storno bleiben damit weiterhin
zentral an den Dunning-DocEvents.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, nowdate, add_days, date_diff

from hausverwaltung.hausverwaltung.page.op_workflow.op_workflow import (
    _resolve_dunning_type,
    create_bulk_dunning as create_op_bulk_dunning,
)
from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_pdf_for_print_format


# ───────────────────────────────────────────────────────────────────────────
# Phase 2 · Datenbereitstellung
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_dunning_context(party: str | None = None) -> dict:
    """Baut das komplette Frontend-Context-Objekt für den Mahnung-Editor.

    Args:
        party: optional vorausgewählter Customer (aus ?party=). Wenn None, werden
            alle mahnreifen Kunden geladen (für den Mieter-Switcher).

    Returns:
        ``{today, basiszins, absender, mieter:[...], vorlagen:[...]}``
        Schema siehe data-mahnung.js (Studio-Mock) — das Frontend erwartet es 1:1.
    """
    if not frappe.has_permission("Sales Invoice", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    # ─── Vorlagen ──────────────────────────────────────────────────────────
    # Option A: aus Dunning Type (ERPNext-Standard)
    # Option B: aus eurem Serienbrief-Modul, Kategorie "Mahnungen"
    vorlagen = _load_vorlagen()

    # ─── Mahnreife Kunden + Posten ─────────────────────────────────────────
    customers = [party] if party else _mahnreife_customers()
    mieter = [_build_mieter(c) for c in customers]

    return {
        "today": nowdate(),
        "basiszins": _basiszins(),
        "absender": _absender(),
        "mieter": [m for m in mieter if m],
        "vorlagen": vorlagen,
    }


def _basiszins() -> float:
    """Configured Bundesbank base interest rate, in percent."""
    default = 1.27
    try:
        if not frappe.get_meta("Hausverwaltung Einstellungen").get_field("mahnung_basiszins"):
            return default
        value = frappe.db.get_single_value("Hausverwaltung Einstellungen", "mahnung_basiszins")
    except Exception:
        return default
    return flt(value if value is not None else default)


def _absender() -> dict:
    """Absender/Bankdaten aus der Default-Company. Felder ggf. anpassen."""
    company = frappe.defaults.get_user_default("Company")
    doc = frappe.get_cached_doc("Company", company) if company else None
    # Beispiel-Mapping — an eure Letterhead/Bank-Felder anpassen:
    return {
        "firma": getattr(doc, "company_name", "Hausverwaltung"),
        "strasse": "",
        "plz_ort": "",
        "telefon": getattr(doc, "phone_no", ""),
        "email": getattr(doc, "email", ""),
        "ust": getattr(doc, "tax_id", ""),
        "geschaeftsfuehrer": "",
        "sachbearbeiter": frappe.session.user_fullname or frappe.session.user,
        "bank": "",
        "iban": getattr(doc, "default_bank_account", "") or "",
        "bic": "",
        "konto_forderungen": "1400 — Forderungen Mieter",
        "konto_erloese_mahn": "8950 — Mahngebühren-Erlöse",
    }


def _load_vorlagen() -> list[dict]:
    """Mahn-Vorlagen aus echten ERPNext ``Dunning Type``-Datensätzen."""
    fields = ["name", "dunning_type", "dunning_fee", "rate_of_interest"]
    has_serienbrief_werte = bool(frappe.get_meta("Dunning Type").get_field("hv_serienbrief_werte"))
    for fieldname in ("hv_serienbrief_vorlage",):
        if frappe.get_meta("Dunning Type").get_field(fieldname):
            fields.append(fieldname)

    types = frappe.get_all("Dunning Type", fields=fields, order_by="creation asc")
    vorlagen = []
    for row in types:
        key = frappe.scrub(row.name)
        serienbrief_vorlage = row.get("hv_serienbrief_vorlage")
        variablen = [
            {"name": "frist_tage", "type": "Zahl", "default": "7", "desc": "Zahlungsfrist in Tagen"},
            {
                "name": "mahngebuehr",
                "type": "Zahl",
                "default": str(flt(row.get("dunning_fee"))),
                "desc": "Mahngebühr in Euro",
            },
            {"name": "kontonummer", "type": "String", "default": _absender().get("iban") or "", "desc": "Empfänger-IBAN"},
        ]
        werte_rows = []
        if has_serienbrief_werte:
            try:
                werte_rows = frappe.get_cached_doc("Dunning Type", row.name).get("hv_serienbrief_werte") or []
            except frappe.DoesNotExistError:
                werte_rows = []
        for wert in werte_rows:
            variable = (wert.get("variable") or "").strip()
            if not variable:
                continue
            scrubbed = frappe.scrub(variable)
            if scrubbed in {v["name"] for v in variablen}:
                continue
            variablen.append({"name": scrubbed, "type": "String", "default": wert.get("wert") or "", "desc": variable})

        label = row.get("dunning_type") or row.name
        vorlagen.append(
            {
                "key": key,
                "tpl_id": serienbrief_vorlage or row.name,
                "dunning_type": row.name,
                "serienbrief_vorlage": serienbrief_vorlage,
                "label": label,
                "kategorie": "Mahnungen",
                "stufe_nr": _dunning_stage_from_type(label),
                "ton": "sachlich",
                "gebuehr": flt(row.get("dunning_fee")),
                "zinsen": flt(row.get("rate_of_interest")) > 0,
                "variablen": variablen,
                "betreff": f"{label} — Objekt {{objekt}}",
                "einleitung": "bitte gleichen Sie die unten aufgeführten offenen Forderungen bis zum {frist} aus.",
                "schluss": "Sollten Sie die Zahlung zwischenzeitlich veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.",
            }
        )
    return vorlagen


def _dunning_stage_from_type(dunning_type: str | None) -> int:
    dunning_type = dunning_type or ""
    if dunning_type.startswith("Zahlungserinnerung"):
        return 0
    if dunning_type.startswith("1. Mahnung"):
        return 1
    if dunning_type.startswith("2. Mahnung"):
        return 2
    return 3


def _vorlage_key_for_dunning_type(dunning_type: str | None) -> str | None:
    return frappe.scrub(dunning_type) if dunning_type else None


def _mahnreife_customers() -> list[str]:
    """Kunden mit mindestens einer überfälligen, offenen Sales Invoice."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT customer
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          AND due_date < %(today)s
        """,
        {"today": nowdate()},
        as_dict=True,
    )
    return [r.customer for r in rows]


def _build_mieter(customer: str) -> dict | None:
    """Baut einen Mieter-Eintrag inkl. überfälliger Posten + Mahnhistorie."""
    if not customer:
        return None
    cust = frappe.get_doc("Customer", customer)

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "posting_date", "due_date", "grand_total",
                "outstanding_amount", "remarks"],
        order_by="due_date asc",
    )
    posten = [{
        "beleg": inv.name,
        "art": "Sales Invoice",
        "bez": inv.remarks or "Mietabrechnung",
        "posting": str(inv.posting_date),
        "faellig": str(inv.due_date),
        "betrag": flt(inv.grand_total),
        "bezahlt": flt(inv.grand_total) - flt(inv.outstanding_amount),
        "offen": flt(inv.outstanding_amount),
        "overdue_days": max(0, date_diff(nowdate(), inv.due_date)),
    } for inv in invoices]

    history = frappe.get_all(
        "Dunning",
        filters={"customer": customer, "docstatus": 1},
        fields=["name", "posting_date", "dunning_type"],
        order_by="posting_date asc",
    )
    historie = [_history_entry(h.name) for h in history]

    mahnstufe = len([h for h in history])
    try:
        empf_vorlage = _vorlage_key_for_dunning_type(_resolve_dunning_type(min(4, mahnstufe + 1)))
    except Exception:
        empf_vorlage = None
    return {
        "id": cust.name,
        "name": cust.customer_name,
        "anrede": f"Sehr geehrte Damen und Herren,",
        "adresse": [cust.customer_name],
        "objekt": "",
        "einheit": "",
        "kostenstelle": "",
        "email": getattr(cust, "email_id", "") or "",
        "verbrauchertyp": "gewerbe" if cust.customer_type == "Company" else "privat",
        "mahnstufe": mahnstufe,
        "empf_vorlage": empf_vorlage,
        "historie": historie,
        "posten": posten,
    }


def _history_entry(dunning_name: str) -> dict:
    doc = frappe.get_doc("Dunning", dunning_name)
    belege = [
        {
            "beleg": row.get("sales_invoice"),
            "betrag": flt(row.get("outstanding") or row.get("outstanding_amount") or row.get("amount")),
        }
        for row in doc.get("overdue_payments", [])
        if row.get("sales_invoice")
    ]
    outstanding = flt(
        doc.get("total_outstanding_amount")
        or doc.get("total_outstanding")
        or doc.get("outstanding_amount")
        or sum(row["betrag"] for row in belege)
    )
    zinsbetrag = flt(doc.get("interest_amount"))
    gebuehr = flt(doc.get("dunning_fee"))
    summe = flt(doc.get("grand_total") or outstanding + zinsbetrag + gebuehr)
    return {
        "datum": str(doc.get("posting_date") or ""),
        "stufe": doc.get("dunning_type"),
        "vorlageKey": frappe.scrub(doc.get("dunning_type") or ""),
        "beleg": doc.name,
        "kanal": "Brief",
        "status": "Gebucht",
        "frist": str(doc.get("due_date") or ""),
        "belege": belege,
        "hauptforderung": outstanding,
        "zinsBetrag": zinsbetrag,
        "gebuehr": gebuehr,
        "summe": summe,
        "docs": [{"id": doc.name, "desc": f"Dunning-Doc · {doc.get('dunning_type')}", "amount": summe}],
    }


# ───────────────────────────────────────────────────────────────────────────
# Phase 3 · Mahnung erstellen
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def create_dunning(
    sales_invoices: str | list,
    dunning_type: str,
    posting_date: str | None = None,
    frist_tage: int = 7,
    mahngebuehr: float | None = None,
    zinsen_aktiv: bool = True,
    kanal: str = "Brief",
    serienbrief_vorlage: str | None = None,
    serienbrief_werte: str | list | dict | None = None,
    finalize: bool = True,
) -> dict:
    """Erzeugt und finalisiert eine Mahnung aus dem separaten Mahnungs-Workflow.

    Der OP-Workflow bleibt Draft-orientiert. Diese Seite ist der geführte
    Abschluss: Dunning-Draft anlegen, submitten, PDF sichern und optional mailen.
    """
    if isinstance(sales_invoices, str):
        sales_invoices = json.loads(sales_invoices)
    sales_invoices = [name for name in (sales_invoices or []) if name]

    if not frappe.has_permission("Dunning", "create"):
        frappe.throw(_("Keine Berechtigung Mahnungen zu erstellen."), frappe.PermissionError)
    if not sales_invoices:
        frappe.throw(_("Keine Posten ausgewählt."))

    invoices = [frappe.get_doc("Sales Invoice", name) for name in sales_invoices]
    customers = {si.customer for si in invoices}
    if len(customers) != 1:
        frappe.throw(_("Eine Mahnung darf nur Rechnungen eines Mieters enthalten."))
    customer = invoices[0].customer
    email_recipients = _customer_email_recipients(customer) if "E-Mail" in (kanal or "") else []
    if "E-Mail" in (kanal or "") and not email_recipients:
        frappe.throw(_("Für {0} ist keine E-Mail-Adresse hinterlegt.").format(customer))
    new_due_date = add_days(posting_date or nowdate(), int(frist_tage or 7))

    result = create_op_bulk_dunning(
        invoices_by_customer={customer: sales_invoices},
        dunning_type_per_customer={customer: dunning_type},
        posting_date=posting_date,
        new_due_date=new_due_date,
        mahngebuehr_per_customer={customer: mahngebuehr} if mahngebuehr is not None else None,
        zinsen_aktiv=zinsen_aktiv,
        serienbrief_vorlage_per_customer={customer: serienbrief_vorlage} if serienbrief_vorlage else None,
        serienbrief_werte_per_customer={customer: serienbrief_werte} if serienbrief_werte else None,
    )
    if result.get("errors"):
        frappe.throw("<br>".join(e.get("msg") or str(e) for e in result.get("errors") or []))

    docs = result.get("docs") or []
    dunning_name = (result.get("created") or [None])[0]
    if not dunning_name and docs:
        dunning_name = docs[0].get("dunning") or docs[0].get("name")
    if not dunning_name:
        frappe.throw(_("Die Mahnung konnte nicht erstellt werden."))

    doc = frappe.get_doc("Dunning", dunning_name)
    summe = flt(getattr(doc, "grand_total", 0) or getattr(doc, "outstanding_amount", 0) or sum(flt(si.outstanding_amount) for si in invoices))
    if not _as_bool(finalize):
        return {
            "dunning": dunning_name,
            "summe": summe,
            "docs": [{"id": dunning_name, "desc": f"Dunning-Draft · {doc.dunning_type}", "amount": summe}],
            "docstatus": doc.docstatus,
            "draft": True,
            "kanal": kanal,
        }

    if doc.docstatus == 0:
        doc.submit()
        doc.reload()

    summe = flt(getattr(doc, "grand_total", 0) or getattr(doc, "outstanding_amount", 0) or sum(flt(si.outstanding_amount) for si in invoices))
    pdf_content = _render_dunning_pdf(doc)
    pdf_file = _save_dunning_pdf(doc, pdf_content)
    email_queue = None
    if "E-Mail" in (kanal or ""):
        email_queue = _send_dunning_email(doc, recipients=email_recipients, pdf_content=pdf_content)

    docs = [{"id": dunning_name, "desc": f"Dunning · {doc.dunning_type}", "amount": summe}]
    if doc.get("hv_dunning_fee_sales_invoice"):
        docs.append(
            {
                "id": doc.get("hv_dunning_fee_sales_invoice"),
                "desc": "Sales Invoice · Mahngebühr/Verzugszinsen",
                "amount": flt(doc.get("dunning_amount")),
            }
        )
    if pdf_file:
        docs.append({"id": pdf_file.file_url, "desc": "PDF · HV Dunning Letter", "amount": None})
    if email_queue:
        docs.append({"id": email_queue, "desc": "E-Mail Queue · Mahnung", "amount": None})

    return {
        "dunning": dunning_name,
        "summe": summe,
        "docs": docs,
        "docstatus": doc.docstatus,
        "draft": False,
        "kanal": kanal,
        "pdf": pdf_file.file_url if pdf_file else None,
        "email_queue": email_queue,
    }


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "no", "nein", ""}
    return bool(value)


def _render_dunning_pdf(doc) -> bytes:
    pdf = render_serienbrief_pdf_for_print_format(
        "HV Dunning Letter",
        doc=doc,
        docname=doc.name,
        doctype="Dunning",
    )
    if pdf:
        return pdf

    html = frappe.get_print("Dunning", doc.name, print_format="HV Dunning Letter", doc=doc)
    from frappe.utils.pdf import get_pdf

    return get_pdf(html)


def _save_dunning_pdf(doc, pdf_content: bytes):
    import hashlib
    import os

    from frappe.core.doctype.file.utils import generate_file_name
    from frappe.utils.file_manager import get_files_path

    content_hash = hashlib.sha1(pdf_content).hexdigest()
    target_dir = get_files_path(is_private=1)
    frappe.create_folder(target_dir)
    safe_name = generate_file_name(
        name=f"{doc.name}.pdf",
        suffix=content_hash[-6:],
        is_private=True,
    )
    full_path = os.path.join(target_dir, safe_name)
    with open(full_path, "wb") as f:
        f.write(pdf_content)

    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": safe_name,
            "file_url": f"/private/files/{safe_name}",
            "attached_to_doctype": "Dunning",
            "attached_to_name": doc.name,
            "is_private": 1,
            "file_size": len(pdf_content),
            "content_hash": content_hash,
            "folder": "Home",
        }
    )
    file_doc.flags.copy_from_existing_file = True
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc


def _customer_email_recipients(customer: str) -> list[str]:
    recipients: list[str] = []
    email = frappe.db.get_value("Customer", customer, "email_id")
    if email:
        recipients.append(email)

    contact_links = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
        pluck="parent",
        limit_page_length=0,
    )
    if contact_links:
        for row in frappe.get_all(
            "Contact Email",
            filters={"parent": ("in", contact_links)},
            fields=["email_id"],
            limit_page_length=0,
        ):
            if row.email_id:
                recipients.append(row.email_id)

    out = []
    for value in recipients:
        value = (value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _send_dunning_email(doc, *, recipients: list[str], pdf_content: bytes) -> str | None:
    subject = _("Mahnung {0}").format(doc.name)
    message = _(
        "Sehr geehrte Damen und Herren,<br><br>"
        "anbei erhalten Sie unsere Mahnung {0}. Bitte gleichen Sie die offenen Beträge "
        "bis zur angegebenen Frist aus.<br><br>Mit freundlichen Grüßen"
    ).format(doc.name)

    queue_doc = frappe.sendmail(
        recipients=recipients,
        subject=subject,
        message=message,
        attachments=[{"fname": f"{doc.name}.pdf", "fcontent": pdf_content}],
        reference_doctype="Dunning",
        reference_name=doc.name,
        delayed=True,
    )
    return getattr(queue_doc, "name", None)


@frappe.whitelist()
def cancel_dunning(dunning: str) -> dict:
    """Cancel a submitted Dunning from the guided Mahnung editor."""
    if not dunning:
        frappe.throw(_("Keine Mahnung angegeben."))

    doc = frappe.get_doc("Dunning", dunning)
    doc.check_permission("cancel")
    if doc.docstatus == 2:
        return {"dunning": doc.name, "docstatus": doc.docstatus, "cancelled": True}
    if doc.docstatus != 1:
        frappe.throw(_("Nur gebuchte Mahnungen können storniert werden."))

    fee_invoice = doc.get("hv_dunning_fee_sales_invoice")
    doc.cancel()
    doc.reload()
    return {
        "dunning": doc.name,
        "docstatus": doc.docstatus,
        "cancelled": True,
        "fee_sales_invoice": fee_invoice,
    }


@frappe.whitelist()
def get_dunning_detail(dunning: str) -> dict:
    """Detail einer bereits gebuchten Mahnung (für die Read-only-Ansicht)."""
    if not frappe.has_permission("Dunning", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    doc = frappe.get_doc("Dunning", dunning)
    belege = [{"beleg": p.sales_invoice, "betrag": flt(p.outstanding)}
              for p in doc.get("overdue_payments", [])]
    outstanding = flt(
        doc.get("total_outstanding_amount")
        or doc.get("total_outstanding")
        or doc.get("outstanding_amount")
        or sum(row["betrag"] for row in belege)
    )
    zinsbetrag = flt(doc.get("interest_amount"))
    gebuehr = flt(doc.get("dunning_fee"))
    summe = flt(doc.get("grand_total") or outstanding + zinsbetrag + gebuehr)
    return {
        "beleg": doc.name,
        "datum": str(doc.get("posting_date") or ""),
        "stufe": doc.get("dunning_type"),
        "vorlageKey": frappe.scrub(doc.get("dunning_type") or ""),
        "kanal": "Brief",
        "status": "Gebucht",
        "frist": str(doc.get("due_date") or ""),
        "belege": belege,
        "hauptforderung": outstanding,
        "zinsBetrag": zinsbetrag,
        "gebuehr": gebuehr,
        "summe": summe,
        "docs": [{"id": doc.name, "desc": f"Dunning-Doc · {doc.get('dunning_type')}", "amount": summe}],
    }
