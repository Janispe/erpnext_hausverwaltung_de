"""
mahnung_workflow.py — Server-Side API für die Frappe Page "mahnung-workflow".

Enthält:
  1. get_dunning_context(party)  — Phase 2: baut das komplette window.MAHNUNG-Objekt
     (Mieter, überfällige Posten, Dunning-Historie, Vorlagen) für das Frontend.
  2. create_dunning(...)         — Phase 3: erzeugt das Dunning-Dokument + Buchungen.

Sicherheits-Pattern: jeder Endpoint prüft Permissions explizit. Bodys der
schreibenden Endpoints sind auskommentiert — in Phase 3 schrittweise scharf
schalten (siehe PHASES.md).
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, nowdate, add_days, date_diff


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
        "basiszins": 1.27,  # ⚠ Bundesbank-Basiszinssatz — zentral pflegen
        "absender": _absender(),
        "mieter": [m for m in mieter if m],
        "vorlagen": vorlagen,
    }


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
    """Mahn-Vorlagen für das Frontend.

    PHASE 2 — eine der beiden Quellen entkommentieren:

    # Variante A · ERPNext Dunning Type
    # types = frappe.get_all("Dunning Type",
    #     fields=["name", "dunning_type", "dunning_fee", "rate_of_interest"])
    # return [{
    #     "key": frappe.scrub(t.name),
    #     "tpl_id": t.name,
    #     "label": t.dunning_type or t.name,
    #     "kategorie": "Mahnungen",
    #     "gebuehr": flt(t.dunning_fee),
    #     "zinsen": flt(t.rate_of_interest) > 0,
    #     "stufe_nr": None,
    #     "ton": "sachlich",
    #     "variablen": [
    #         {"name": "frist_tage", "type": "Zahl", "default": "7", "desc": "Zahlungsfrist in Tagen"},
    #         {"name": "mahngebuehr", "type": "Zahl", "default": str(flt(t.dunning_fee)), "desc": "Mahngebühr in Euro"},
    #         {"name": "kontonummer", "type": "String", "default": "", "desc": "Empfänger-IBAN"},
    #     ],
    #     "betreff": "", "einleitung": "", "schluss": "",
    # } for t in types]

    # Variante B · Serienbrief-Modul (Kategorie "Mahnungen")
    # docs = frappe.get_all("Serienbrief Vorlage",
    #     filters={"kategorie": "Mahnungen"},
    #     fields=["name", "titel", "betreff", "einleitung", "schluss",
    #             "mahngebuehr", "verzugszinsen"])
    # return [_serienbrief_to_vorlage(d) for d in docs]
    """
    # MOCK-Fallback solange beide Varianten kommentiert sind:
    return [
        {
            "key": "mahnung_1", "tpl_id": "TPL-MAHN-001", "label": "1. Mahnung",
            "kategorie": "Mahnungen", "stufe_nr": 1, "ton": "sachlich",
            "gebuehr": 5.0, "zinsen": True,
            "variablen": [
                {"name": "frist_tage", "type": "Zahl", "default": "7", "desc": "Zahlungsfrist in Tagen"},
                {"name": "mahngebuehr", "type": "Zahl", "default": "5,00", "desc": "Mahngebühr in Euro"},
                {"name": "kontonummer", "type": "String", "default": "", "desc": "Empfänger-IBAN"},
            ],
            "betreff": "1. Mahnung — Objekt {objekt}",
            "einleitung": "trotz unserer Zahlungserinnerung ist der Betrag noch offen …",
            "schluss": "Für diese Mahnung berechnen wir eine Mahngebühr.",
        },
    ]


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
        fields=["name", "posting_date", "dunning_type", "grand_total"],
        order_by="posting_date asc",
    )
    historie = [{
        "datum": str(h.posting_date),
        "stufe": h.dunning_type,
        "vorlageKey": frappe.scrub(h.dunning_type or ""),
        "beleg": h.name,
        "kanal": "Brief",
        "status": "Gebucht",
        "summe": flt(h.grand_total),
        # Detail-Felder (belege/docs) bei Bedarf per get_dunning_detail nachladen.
    } for h in history]

    mahnstufe = len([h for h in history])  # grobe Näherung; siehe PHASES.md §2b
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
        "empf_vorlage": None,
        "historie": historie,
        "posten": posten,
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
) -> dict:
    """Erzeugt EIN Dunning-Dokument über mehrere überfällige Sales Invoices.

    Args:
        sales_invoices: Liste von SI-Namen (oder JSON-String)
        dunning_type: Name eines konfigurierten Dunning Type
        posting_date: default heute
        frist_tage: neue Zahlungsfrist in Tagen ab posting_date
        mahngebuehr: optional Override
        zinsen_aktiv: ob Verzugszinsen berechnet werden
        kanal: "Brief" | "E-Mail" | "Brief + E-Mail"

    Returns:
        ``{dunning, summe, docs:[...]}`` — docs füllt das Sent-Overlay im Frontend.
    """
    if isinstance(sales_invoices, str):
        sales_invoices = json.loads(sales_invoices)

    if not frappe.has_permission("Dunning", "create"):
        frappe.throw(_("Keine Berechtigung Mahnungen zu erstellen."), frappe.PermissionError)
    if not sales_invoices:
        frappe.throw(_("Keine Posten ausgewählt."))

    # ─────────────────────────────────────────────────────────────────────
    # PHASE 3 — Body entkommentieren wenn bereit:
    # ─────────────────────────────────────────────────────────────────────
    #
    # first = frappe.get_doc("Sales Invoice", sales_invoices[0])
    # dunning = frappe.new_doc("Dunning")
    # dunning.update({
    #     "customer": first.customer,
    #     "company": first.company,
    #     "dunning_type": dunning_type,
    #     "posting_date": posting_date or nowdate(),
    #     "due_date": add_days(posting_date or nowdate(), int(frist_tage)),
    #     "currency": first.currency,
    # })
    # for name in sales_invoices:
    #     si = frappe.get_doc("Sales Invoice", name)
    #     if si.docstatus != 1 or si.outstanding_amount <= 0:
    #         continue
    #     dunning.append("overdue_payments", {
    #         "sales_invoice": name,
    #         "due_date": si.due_date,
    #         "invoice_portion": 100,
    #         "outstanding": si.outstanding_amount,
    #     })
    # if mahngebuehr is not None:
    #     dunning.dunning_fee = flt(mahngebuehr)
    # if not zinsen_aktiv:
    #     dunning.rate_of_interest = 0
    # dunning.insert()
    # dunning.submit()
    #
    # # PDF erzeugen + (optional) per E-Mail versenden je nach `kanal`
    # # if "E-Mail" in kanal:
    # #     frappe.sendmail(recipients=[first.contact_email], ...)
    #
    # docs = [{"id": dunning.name,
    #          "desc": f"Dunning-Doc · {dunning_type}",
    #          "amount": flt(dunning.grand_total)}]
    # return {"dunning": dunning.name, "summe": flt(dunning.grand_total), "docs": docs}

    # MOCK-Response solange Body kommentiert ist:
    return {
        "dunning": "DUN-MOCK-001",
        "summe": 0.0,
        "docs": [{"id": "DUN-MOCK-001", "desc": f"Dunning-Doc · {dunning_type}", "amount": 0.0}],
        "mock": True,
    }


@frappe.whitelist()
def get_dunning_detail(dunning: str) -> dict:
    """Detail einer bereits gebuchten Mahnung (für die Read-only-Ansicht)."""
    if not frappe.has_permission("Dunning", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    doc = frappe.get_doc("Dunning", dunning)
    belege = [{"beleg": p.sales_invoice, "betrag": flt(p.outstanding)}
              for p in doc.get("overdue_payments", [])]
    return {
        "beleg": doc.name,
        "datum": str(doc.posting_date),
        "stufe": doc.dunning_type,
        "vorlageKey": frappe.scrub(doc.dunning_type or ""),
        "kanal": "Brief",
        "status": "Gebucht",
        "frist": str(doc.due_date),
        "belege": belege,
        "hauptforderung": flt(doc.total_outstanding_amount),
        "zinsBetrag": flt(doc.interest_amount),
        "gebuehr": flt(doc.dunning_fee),
        "summe": flt(doc.grand_total),
        "docs": [{"id": doc.name, "desc": f"Dunning-Doc · {doc.dunning_type}", "amount": flt(doc.grand_total)}],
    }
