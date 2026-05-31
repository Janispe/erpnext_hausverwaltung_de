"""
op_workflow.py — Server-Side API für die Frappe Page "op-workflow".

Diese Datei enthält:
  1. Wrapper für den bestehenden Script Report (get_open_items)
  2. Action-Endpoints: Mahnung erstellen, Zahlung anlegen, Vorauszahlung zuordnen,
     Abschreiben — jeweils mit kommentiertem Body, den du in Phase 3 einkommentierst.

Sicherheits-Pattern: jeder Endpoint validiert Permissions explizit + nutzt
``frappe.db.get_value`` mit ``for_update=True`` wo nötig, um Race-Conditions
beim Buchen zu vermeiden.
"""

from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate, add_days


_MV_MARKER_RE = re.compile(r"\[MV:([^\]]+)\]")
_DUNNING_DOCSTATUS_LABEL = {
    0: "Draft",
    1: "Submitted",
    2: "Cancelled",
}


# ───────────────────────────────────────────────────────────────────────────
# Phase 2 · Datenbereitstellung
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_open_items(filters: str | dict | None = None) -> dict:
    """Wrapper um den bestehenden Script Report.

    Liefert die Rows so wie der Report sie selbst liefert — die Frontend-Seite
    transformiert sie in ``data-adapter.js`` in das von den React-Komponenten
    erwartete Format.

    Args:
        filters: Dict oder JSON-String mit Report-Filtern. Erlaubte Keys:
            company, mode, von_faelligkeit, bis_faelligkeit, party (Liste),
            cost_center, sortierung, show_settled, show_written_off, …

    Returns:
        ``{"columns": [...], "rows": [...], "today": "YYYY-MM-DD"}``
    """
    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    filters = filters or {}

    # Permission-Check: nur User mit Lese-Recht auf Sales Invoice
    if not frappe.has_permission("Sales Invoice", "read"):
        frappe.throw(_("Keine Berechtigung für offene Posten."), frappe.PermissionError)

    # Direkt die existierende execute()-Funktion aufrufen
    from hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen import (
        noch_offene_rechnungen_und_forderungen as report_module,
    )
    result = report_module.execute(filters)

    # execute() liefert (columns, rows, message, chart, report_summary)
    columns, rows = result[0], result[1]

    return {
        "columns": columns,
        "rows": rows,
        "today": nowdate(),
    }


@frappe.whitelist()
def get_mieter_summary(party: str) -> dict:
    """Mieter-Stammdaten + aktuelle Soll-Miete + aktueller Saldo.

    Wird vom Mieterkonto-Header verwendet.
    """
    if not frappe.has_permission("Customer", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    customer = frappe.get_doc("Customer", party)

    # Beispiel — passe die Felder an deine Custom-Fields an
    return {
        "customer_id": customer.name,
        "name": customer.customer_name,
        "vertrag_seit": getattr(customer, "vertrag_seit", None),
        # Diese Felder kommen aus deinem Mietvertrag-DocType, falls vorhanden:
        # "sollmiete_aktuell": ...,
        # "objekt": ...,
        # "einheit": ...,
    }


@frappe.whitelist()
def list_dunning_types() -> list[str]:
    """Liefert verfügbare Dunning Types für die OP-Workflow-Auswahl."""
    if not frappe.has_permission("Dunning Type", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    return frappe.get_all("Dunning Type", pluck="name", order_by="name asc")


@frappe.whitelist()
def list_serienbrief_vorlagen(doctype: str | None = "Dunning") -> list[str]:
    """Liefert Serienbrief-Vorlagen für Mahnungs-Auswahlfelder."""
    if not frappe.has_permission("Serienbrief Vorlage", "read"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    filters = {}
    if doctype and _meta_has_field("Serienbrief Vorlage", "haupt_verteil_objekt"):
        filters = {"haupt_verteil_objekt": ("in", [doctype, "", None])}

    return frappe.get_all("Serienbrief Vorlage", filters=filters, pluck="name", order_by="name asc")


def _parse_filters(filters: str | dict | None) -> dict:
    if isinstance(filters, str):
        return json.loads(filters or "{}")
    return filters or {}


def _date_days_overdue(due_date) -> int:
    if not due_date:
        return 0
    return max(0, (getdate(nowdate()) - getdate(due_date)).days)


def _normalize_docstatus(value) -> int:
    return cint(value or 0)


def _dunning_status_label(row: dict) -> str:
    if row.get("status") == "Resolved":
        return "Resolved"
    return _DUNNING_DOCSTATUS_LABEL.get(_normalize_docstatus(row.get("docstatus")), row.get("status") or "")


def _serienbrief_vorlage_for_dunning_type(dunning_type: str | None) -> str | None:
    if not dunning_type or not _meta_has_field("Dunning Type", "hv_serienbrief_vorlage"):
        return None
    return frappe.db.get_value("Dunning Type", dunning_type, "hv_serienbrief_vorlage")


def _resolve_invoice_mietvertrag(si) -> dict[str, str | None]:
    """Best-effort-Auflösung einer Mietrechnung auf Mietvertrag/Wohnung."""
    remarks = getattr(si, "remarks", None) or ""
    marker = _MV_MARKER_RE.search(remarks)
    mietvertrag = marker.group(1).strip() if marker else None

    mietabrechnung_id = getattr(si, "mietabrechnung_id", None)
    if not mietvertrag and mietabrechnung_id and "|" in str(mietabrechnung_id):
        candidate = str(mietabrechnung_id).split("|", 1)[0].strip()
        if candidate:
            mietvertrag = candidate

    if not mietvertrag and _meta_has_field("Sales Invoice", "mietvertrag"):
        mietvertrag = getattr(si, "mietvertrag", None)

    if not mietvertrag:
        try:
            from hausverwaltung.hausverwaltung.utils.mietabrechnung import resolve_mietabrechnung_id

            resolved = resolve_mietabrechnung_id(
                customer=getattr(si, "customer", None),
                posting_date=getattr(si, "posting_date", None) or getattr(si, "due_date", None),
                wohnung=getattr(si, "wohnung", None) if _meta_has_field("Sales Invoice", "wohnung") else None,
            )
            if resolved and "|" in resolved:
                mietvertrag = resolved.split("|", 1)[0].strip()
        except Exception:
            mietvertrag = None

    wohnung = None
    if mietvertrag and frappe.db.exists("Mietvertrag", mietvertrag):
        wohnung = frappe.db.get_value("Mietvertrag", mietvertrag, "wohnung")
    elif _meta_has_field("Sales Invoice", "wohnung"):
        wohnung = getattr(si, "wohnung", None)

    return {"mietvertrag": mietvertrag, "wohnung": wohnung}


def _sales_invoice_fields_for_mahnkandidaten() -> list[str]:
    fields = [
        "name",
        "customer",
        "customer_name",
        "company",
        "posting_date",
        "due_date",
        "outstanding_amount",
        "grand_total",
        "currency",
        "status",
        "remarks",
    ]
    for fieldname in ("mietabrechnung_id", "mietvertrag", "wohnung", "cost_center"):
        if _meta_has_field("Sales Invoice", fieldname):
            fields.append(fieldname)
    return fields


def _dunning_fields_for_history() -> list[str]:
    fields = ["name", "docstatus", "status", "posting_date", "customer", "company", "dunning_type"]
    for fieldname in (
        "hv_serienbrief_vorlage",
        "hv_dunning_fee_sales_invoice",
        "grand_total",
        "outstanding_amount",
        "dunning_amount",
    ):
        if _meta_has_field("Dunning", fieldname):
            fields.append(fieldname)
    return fields


def _dunnings_for_invoices(invoice_names: list[str]) -> dict[str, list[dict]]:
    if not invoice_names:
        return {}

    invoice_set = set(invoice_names)
    parent_to_invoices: dict[str, set[str]] = {}

    if frappe.db.has_column("Dunning", "sales_invoice"):
        direct = frappe.get_all(
            "Dunning",
            filters={"sales_invoice": ("in", invoice_names)},
            fields=["name", "sales_invoice"],
            limit_page_length=0,
        )
        for row in direct:
            parent_to_invoices.setdefault(row.name, set()).add(row.sales_invoice)

    table_field = frappe.get_meta("Dunning").get_field("overdue_payments")
    if table_field and table_field.options and frappe.db.has_column(table_field.options, "sales_invoice"):
        child_rows = frappe.get_all(
            table_field.options,
            filters={
                "parenttype": "Dunning",
                "sales_invoice": ("in", invoice_names),
            },
            fields=["parent", "sales_invoice"],
            limit_page_length=0,
        )
        for row in child_rows:
            parent_to_invoices.setdefault(row.parent, set()).add(row.sales_invoice)

    if not parent_to_invoices:
        return {name: [] for name in invoice_names}

    dunning_docs = frappe.get_all(
        "Dunning",
        filters={"name": ("in", list(parent_to_invoices))},
        fields=_dunning_fields_for_history(),
        limit_page_length=0,
        order_by="posting_date desc, creation desc",
    )

    result: dict[str, list[dict]] = {name: [] for name in invoice_names}
    for doc in dunning_docs:
        amount = (
            flt(doc.get("grand_total"))
            or flt(doc.get("dunning_amount"))
            or flt(doc.get("outstanding_amount"))
        )
        item = {
            "name": doc.name,
            "docstatus": _normalize_docstatus(doc.docstatus),
            "status": _dunning_status_label(doc),
            "posting_date": doc.get("posting_date"),
            "dunning_type": doc.get("dunning_type"),
            "serienbrief_vorlage": doc.get("hv_serienbrief_vorlage"),
            "fee_sales_invoice": doc.get("hv_dunning_fee_sales_invoice"),
            "amount": amount,
        }
        for invoice in parent_to_invoices.get(doc.name, set()) & invoice_set:
            result.setdefault(invoice, []).append(item)
    return result


def _next_dunning_type_for_invoices(invoice_names: list[str], history_by_invoice: dict[str, list[dict]]) -> tuple[int, str | None]:
    submitted_count = 0
    for invoice in invoice_names:
        submitted_count = max(
            submitted_count,
            len([row for row in history_by_invoice.get(invoice, []) if _normalize_docstatus(row.get("docstatus")) == 1]),
        )
    next_level = min(4, submitted_count + 1)
    try:
        return next_level, _resolve_dunning_type(next_level)
    except Exception:
        return next_level, None


@frappe.whitelist()
def get_mahnkandidaten(filters: str | dict | None = None) -> dict:
    """Gruppierte Mahnkandidaten inkl. offener Rechnungen und Mahnhistorie."""
    filters = _parse_filters(filters)

    if not frappe.has_permission("Sales Invoice", "read") or not frappe.has_permission("Dunning", "read"):
        frappe.throw(_("Keine Berechtigung für Mahnkandidaten."), frappe.PermissionError)

    si_filters: dict[str, Any] = {
        "docstatus": 1,
        "outstanding_amount": (">", 0),
        "status": ("not in", ["Paid", "Credit Note Issued", "Written Off", "Partly Paid and Written Off"]),
        "due_date": ("<=", nowdate()),
    }
    if filters.get("company"):
        si_filters["company"] = filters.get("company")
    if filters.get("include_not_due"):
        si_filters.pop("due_date", None)
    if filters.get("bis_faelligkeit"):
        bis = getdate(filters.get("bis_faelligkeit"))
        if not filters.get("include_not_due"):
            bis = min(bis, getdate(nowdate()))
        si_filters["due_date"] = ("<=", bis)
    if filters.get("von_faelligkeit") and filters.get("include_not_due"):
        si_filters["due_date"] = ("between", [filters.get("von_faelligkeit"), filters.get("bis_faelligkeit") or nowdate()])

    invoices = frappe.get_all(
        "Sales Invoice",
        filters=si_filters,
        fields=_sales_invoice_fields_for_mahnkandidaten(),
        limit_page_length=0,
        order_by="due_date asc, customer asc, name asc",
    )
    invoice_names = [row.name for row in invoices]
    history_by_invoice = _dunnings_for_invoices(invoice_names)

    groups: dict[str, dict] = {}
    for si in invoices:
        resolved = _resolve_invoice_mietvertrag(si)
        mietvertrag = resolved.get("mietvertrag")
        wohnung = resolved.get("wohnung")
        key = f"MV::{mietvertrag}" if mietvertrag else f"CUSTOMER::{si.customer}"
        group = groups.setdefault(
            key,
            {
                "key": key,
                "customer": si.customer,
                "customer_name": si.get("customer_name") or si.customer,
                "mietvertrag": mietvertrag,
                "wohnung": wohnung,
                "company": si.company,
                "currency": si.currency,
                "offen": 0.0,
                "invoice_count": 0,
                "oldest_due_date": si.due_date,
                "oldest_age_days": _date_days_overdue(si.due_date),
                "invoices": [],
                "mahnungen": [],
            },
        )
        if not group.get("mietvertrag") and mietvertrag:
            group["mietvertrag"] = mietvertrag
        if not group.get("wohnung") and wohnung:
            group["wohnung"] = wohnung

        amount = flt(si.outstanding_amount)
        group["offen"] += amount
        group["invoice_count"] += 1
        if si.due_date and (not group.get("oldest_due_date") or getdate(si.due_date) < getdate(group["oldest_due_date"])):
            group["oldest_due_date"] = si.due_date
            group["oldest_age_days"] = _date_days_overdue(si.due_date)

        group["invoices"].append(
            {
                "sales_invoice": si.name,
                "name": si.name,
                "customer": si.customer,
                "customer_name": si.get("customer_name") or si.customer,
                "company": si.company,
                "posting_date": si.posting_date,
                "due_date": si.due_date,
                "outstanding_amount": amount,
                "grand_total": flt(si.grand_total),
                "currency": si.currency,
                "status": si.status,
                "remarks": si.get("remarks"),
                "mietabrechnung_id": si.get("mietabrechnung_id"),
                "mietvertrag": mietvertrag,
                "wohnung": wohnung,
                "cost_center": si.get("cost_center"),
                "mahnungen": history_by_invoice.get(si.name, []),
            }
        )

    for group in groups.values():
        invoice_names = [row["sales_invoice"] for row in group["invoices"]]
        seen: set[str] = set()
        history: list[dict] = []
        for invoice in invoice_names:
            for mahnung in history_by_invoice.get(invoice, []):
                if mahnung["name"] in seen:
                    continue
                seen.add(mahnung["name"])
                history.append(mahnung)
        history.sort(key=lambda row: (row.get("posting_date") or "", row.get("name") or ""), reverse=True)

        next_level, dunning_type = _next_dunning_type_for_invoices(invoice_names, history_by_invoice)
        template = _serienbrief_vorlage_for_dunning_type(dunning_type)
        group.update(
            {
                "mahnungen": history,
                "draft_warning": any(_normalize_docstatus(row.get("docstatus")) == 0 for row in history),
                "next_level": next_level,
                "next_dunning_type": dunning_type,
                "serienbrief_vorlage": template,
                "serienbrief_vorlage_source": "dunning_type" if template else "none",
                "submitted_mahnung_count": len([row for row in history if _normalize_docstatus(row.get("docstatus")) == 1]),
            }
        )

    candidates = sorted(
        groups.values(),
        key=lambda row: (row.get("oldest_age_days") or 0, row.get("offen") or 0),
        reverse=True,
    )
    return {"rows": candidates, "today": nowdate()}


# ───────────────────────────────────────────────────────────────────────────
# Phase 3 · Aktionen
# Endpoints erzeugen bewusst Draft-Belege. Submit/Buchung passiert im Desk.
# ───────────────────────────────────────────────────────────────────────────


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "no", "nein", ""}
    return bool(value)


def _meta_has_field(doctype: str, fieldname: str) -> bool:
    return bool(frappe.get_meta(doctype).get_field(fieldname))


def _set_if_field(doc, fieldname: str, value) -> None:
    if value is not None and _meta_has_field(doc.doctype, fieldname):
        doc.set(fieldname, value)


def _child_fieldnames(parent_doctype: str, table_fieldname: str) -> set[str]:
    table_field = frappe.get_meta(parent_doctype).get_field(table_fieldname)
    if not table_field or not table_field.options:
        return set()
    return {df.fieldname for df in frappe.get_meta(table_field.options).fields}


def _append_child_if_table(doc, table_fieldname: str, values: dict[str, Any]) -> bool:
    allowed = _child_fieldnames(doc.doctype, table_fieldname)
    if not allowed:
        return False
    doc.append(table_fieldname, {key: value for key, value in values.items() if key in allowed})
    return True


def _parse_serienbrief_werte(values: str | list | dict | None) -> list[dict[str, Any]]:
    if isinstance(values, str):
        values = json.loads(values or "[]")
    if isinstance(values, dict):
        values = [{"variable": key, "wert": value} for key, value in values.items()]

    rows: list[dict[str, Any]] = []
    for row in values or []:
        variable = (row.get("variable") or "").strip()
        if not variable:
            continue
        rows.append({
            "variable": variable,
            "wert": row.get("wert"),
            "beschreibung": row.get("beschreibung"),
        })
    return rows


def _append_serienbrief_werte(doc, values: str | list | dict | None) -> None:
    for row in _parse_serienbrief_werte(values):
        _append_child_if_table(doc, "hv_serienbrief_werte", row)


def _draft_response(doc, key: str, **extra) -> dict:
    return {
        "doctype": doc.doctype,
        "name": doc.name,
        key: doc.name,
        "docstatus": cint(doc.docstatus),
        "draft": cint(doc.docstatus) == 0,
        **extra,
    }


def _require_submitted_invoice(doctype: str, name: str):
    doc = frappe.get_doc(doctype, name)
    if cint(doc.docstatus) != 1:
        frappe.throw(_("{0} ist nicht submitted.").format(name))
    if flt(getattr(doc, "outstanding_amount", 0)) <= 0:
        frappe.throw(_("{0} hat keinen offenen Betrag.").format(name))
    return doc


def _resolve_dunning_type(level: int, explicit: str | None = None) -> str:
    if explicit and frappe.db.exists("Dunning Type", explicit):
        return explicit

    stage_candidates = {
        1: [
            "Zahlungserinnerung - HP",
            "Zahlungserinnerung",
            "Zahlungserinnerung Stufe 1",
        ],
        2: [
            "1. Mahnung - HP",
            "1. Mahnung",
            "Mahnung Stufe 1",
            "Mahnung M1",
            "M1",
        ],
        3: [
            "2. Mahnung - HP",
            "2. Mahnung",
            "Mahnung Stufe 2",
            "Mahnung M2",
            "M2",
        ],
        4: [
            "Letzte Mahnung - HP",
            "Letzte Mahnung",
            "Letzte Mahnung Stufe 3",
            "Mahnung Stufe 3",
            "Mahnung M3",
            "M3",
        ],
    }
    candidates = stage_candidates.get(min(4, max(1, level)), [])

    for candidate in candidates:
        if frappe.db.exists("Dunning Type", candidate):
            return candidate

    first = frappe.db.get_value("Dunning Type", {}, "name", order_by="creation asc")
    if first:
        return first
    frappe.throw(_("Bitte zuerst mindestens einen Dunning Type anlegen."))


def _submitted_dunning_count(sales_invoice: str) -> int:
    dunning_names: set[str] = set()
    if frappe.db.has_column("Dunning", "sales_invoice"):
        dunning_names.update(frappe.get_all(
            "Dunning",
            filters={"docstatus": 1, "sales_invoice": sales_invoice},
            pluck="name",
        ))

    table_field = frappe.get_meta("Dunning").get_field("overdue_payments")
    if table_field and table_field.options:
        child_dt = table_field.options
        if frappe.db.has_column(child_dt, "sales_invoice"):
            parents = frappe.get_all(
                child_dt,
                filters={
                    "parenttype": "Dunning",
                    "sales_invoice": sales_invoice,
                },
                pluck="parent",
            )
            parents = list(set(parents))
            if parents:
                dunning_names.update(frappe.get_all(
                    "Dunning",
                    filters={"name": ("in", parents), "docstatus": 1},
                    pluck="name",
                ))
    return len(dunning_names)


def _resolve_mode_of_payment(mode_of_payment: str | None) -> str | None:
    if mode_of_payment and frappe.db.exists("Mode of Payment", mode_of_payment):
        return mode_of_payment
    if mode_of_payment == "SEPA-Überweisung" and frappe.db.exists("Mode of Payment", "Bank Draft"):
        return "Bank Draft"
    return frappe.db.get_value("Mode of Payment", {"enabled": 1}, "name")


@frappe.whitelist()
def create_dunning(
    sales_invoice: str,
    dunning_type: str,
    posting_date: str | None = None,
    new_due_date: str | None = None,
    mahngebuehr: float | None = None,
    zinsen_aktiv: bool = True,
    serienbrief_vorlage: str | None = None,
    serienbrief_werte: str | list | dict | None = None,
) -> dict:
    """Erzeugt ein Dunning-Dokument für eine Sales Invoice.

    Args:
        sales_invoice: SI Name (z. B. "ACC-SINV-2026-00203")
        dunning_type: Name eines konfigurierten Dunning Type
            (z. B. "Zahlungserinnerung Stufe 1")
        posting_date: optional, default = heute
        new_due_date: optional, default = heute + 7 Tage
        mahngebuehr: optional Override
        zinsen_aktiv: ob Verzugszinsen berechnet werden sollen

    Returns:
        ``{"dunning": "<dunning-name>", "docstatus": 0, "draft": true}``
    """
    if not frappe.has_permission("Dunning", "create"):
        frappe.throw(_("Keine Berechtigung Mahnungen zu erstellen."), frappe.PermissionError)

    si = _require_submitted_invoice("Sales Invoice", sales_invoice)
    level = min(4, _submitted_dunning_count(sales_invoice) + 1)
    resolved_type = _resolve_dunning_type(level, dunning_type)

    dunning = frappe.new_doc("Dunning")
    for fieldname, value in {
        "sales_invoice": sales_invoice,
        "customer": si.customer,
        "company": si.company,
        "dunning_type": resolved_type,
        "posting_date": posting_date or nowdate(),
        "due_date": new_due_date or add_days(nowdate(), 7),
        "outstanding_amount": si.outstanding_amount,
        "currency": si.currency,
        "conversion_rate": flt(getattr(si, "conversion_rate", None)) or 1,
        "dunning_fee": flt(mahngebuehr) if mahngebuehr is not None else None,
        "rate_of_interest": None if _as_bool(zinsen_aktiv) else 0,
        "hv_serienbrief_vorlage": serienbrief_vorlage or _serienbrief_vorlage_for_dunning_type(resolved_type),
    }.items():
        _set_if_field(dunning, fieldname, value)

    _append_child_if_table(
        dunning,
        "overdue_payments",
        {
            "sales_invoice": si.name,
            "payment_term": None,
            "due_date": si.due_date,
            "invoice_portion": 100,
            "outstanding": si.outstanding_amount,
            "outstanding_amount": si.outstanding_amount,
            "amount": si.outstanding_amount,
        },
    )
    _append_serienbrief_werte(dunning, serienbrief_werte)

    dunning.insert(ignore_permissions=False)
    return _draft_response(
        dunning,
        "dunning",
        summe=flt(getattr(dunning, "grand_total", 0) or getattr(si, "outstanding_amount", 0)),
        dunning_type=resolved_type,
        serienbrief_vorlage=getattr(dunning, "hv_serienbrief_vorlage", None),
        mahnstufe=level,
    )


@frappe.whitelist()
def create_bulk_dunning(
    invoices_by_customer: str | dict,
    dunning_type_per_customer: str | dict | None = None,
    new_due_date: str | None = None,
    serienbrief_vorlage_per_customer: str | dict | None = None,
    serienbrief_vorlage: str | None = None,
    serienbrief_werte_per_customer: str | dict | None = None,
    serienbrief_werte: str | list | dict | None = None,
) -> dict:
    """Sammelmahnung: pro Kunde EIN Dunning-Doc mit mehreren Invoices.

    Args:
        invoices_by_customer: Dict ``{"<customer>": ["SI-1", "SI-2"], ...}``
        dunning_type_per_customer: optional, Dict mit Override pro Customer
        new_due_date: Default für alle

    Returns:
        ``{"created": [<dunning-names>], "errors": [{"customer": ..., "msg": ...}]}``
    """
    if isinstance(invoices_by_customer, str):
        invoices_by_customer = json.loads(invoices_by_customer)
    if isinstance(dunning_type_per_customer, str):
        dunning_type_per_customer = json.loads(dunning_type_per_customer)
    if isinstance(serienbrief_vorlage_per_customer, str):
        serienbrief_vorlage_per_customer = json.loads(serienbrief_vorlage_per_customer)
    if isinstance(serienbrief_werte_per_customer, str):
        serienbrief_werte_per_customer = json.loads(serienbrief_werte_per_customer)

    created: list[str] = []
    errors: list[dict] = []
    docs: list[dict] = []

    for customer, invoices in (invoices_by_customer or {}).items():
        try:
            invoice_names = [name for name in invoices if name]
            if not invoice_names:
                continue

            sales_invoices = [_require_submitted_invoice("Sales Invoice", name) for name in invoice_names]
            companies = {si.company for si in sales_invoices}
            customers = {si.customer for si in sales_invoices}
            if len(companies) != 1 or len(customers) != 1 or customer not in customers:
                frappe.throw(_("Sammelmahnung darf nur Rechnungen einer Firma und eines Mieters enthalten."))

            next_level = min(4, max(_submitted_dunning_count(si.name) for si in sales_invoices) + 1)
            explicit_type = (dunning_type_per_customer or {}).get(customer) if dunning_type_per_customer else None
            resolved_type = _resolve_dunning_type(next_level, explicit_type)
            explicit_template = None
            if serienbrief_vorlage_per_customer:
                explicit_template = serienbrief_vorlage_per_customer.get(customer)
            effective_template = explicit_template or serienbrief_vorlage or _serienbrief_vorlage_for_dunning_type(resolved_type)

            dunning = frappe.new_doc("Dunning")
            first = sales_invoices[0]
            for fieldname, value in {
                "customer": customer,
                "company": first.company,
                "dunning_type": resolved_type,
                "posting_date": nowdate(),
                "due_date": new_due_date or add_days(nowdate(), 7),
                "currency": first.currency,
                "conversion_rate": flt(getattr(first, "conversion_rate", None)) or 1,
                "outstanding_amount": sum(flt(si.outstanding_amount) for si in sales_invoices),
                "hv_serienbrief_vorlage": effective_template,
            }.items():
                _set_if_field(dunning, fieldname, value)

            for si in sales_invoices:
                _append_child_if_table(
                    dunning,
                    "overdue_payments",
                    {
                        "sales_invoice": si.name,
                        "payment_term": None,
                        "due_date": si.due_date,
                        "invoice_portion": 100,
                        "outstanding": si.outstanding_amount,
                        "outstanding_amount": si.outstanding_amount,
                        "amount": si.outstanding_amount,
                    },
                )
            customer_werte = (serienbrief_werte_per_customer or {}).get(customer) if serienbrief_werte_per_customer else None
            _append_serienbrief_werte(dunning, customer_werte or serienbrief_werte)

            dunning.insert(ignore_permissions=False)
            created.append(dunning.name)
            docs.append(
                _draft_response(
                    dunning,
                    "dunning",
                    dunning_type=resolved_type,
                    serienbrief_vorlage=getattr(dunning, "hv_serienbrief_vorlage", None),
                    mahnstufe=next_level,
                )
            )
        except Exception as e:
            errors.append({"customer": customer, "msg": str(e)})

    return {"created": created, "docs": docs, "errors": errors, "draft": True}


@frappe.whitelist()
def create_payment_entry(
    purchase_invoice: str,
    posting_date: str | None = None,
    use_skonto: bool = False,
    skonto_amount: float | None = None,
    mode_of_payment: str = "Bank Draft",
) -> dict:
    """Erzeugt einen Payment Entry für eine Lieferanten-Rechnung (Purchase Invoice).

    Wenn ``use_skonto=True`` und ``skonto_amount`` gesetzt, wird der Skontobetrag
    als Aufwandsminderung gebucht.
    """
    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    pi = _require_submitted_invoice("Purchase Invoice", purchase_invoice)
    pe = get_payment_entry("Purchase Invoice", purchase_invoice)
    pe.posting_date = posting_date or nowdate()

    resolved_mode = _resolve_mode_of_payment(mode_of_payment)
    if resolved_mode:
        pe.mode_of_payment = resolved_mode

    if _as_bool(use_skonto) and flt(skonto_amount):
        discount_account = frappe.get_cached_value(
            "Company", pi.company, "default_discount_account"
        )
        if not discount_account:
            frappe.throw(_("Für Skonto fehlt an der Firma das Default Discount Account."))
        pe.append(
            "deductions",
            {
                "account": discount_account,
                "amount": flt(skonto_amount),
                "cost_center": getattr(pi, "cost_center", None),
            },
        )
        pe.paid_amount = flt(pi.outstanding_amount) - flt(skonto_amount)
        if pe.references:
            pe.references[0].allocated_amount = flt(pi.outstanding_amount)

    pe.insert(ignore_permissions=False)
    return _draft_response(pe, "payment_entry", auszahlung=flt(pe.paid_amount), mode_of_payment=resolved_mode)


@frappe.whitelist()
def create_refund_payment(
    sales_invoice: str,
    posting_date: str | None = None,
    bank_account: str | None = None,
    mode_of_payment: str | None = None,
) -> dict:
    """Erzeugt einen Payment-Entry-Draft zur Auszahlung eines Mieter-Guthabens.

    Unterstützt bewusst nur Sales Invoices / Credit Notes mit negativem
    ``outstanding_amount``. Unzugeordnete Payment Entries/Vorauszahlungen werden
    hier nicht automatisch ausgezahlt, weil dafür ein anderer Abstimmungsprozess
    nötig ist.
    """
    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    si = frappe.get_doc("Sales Invoice", sales_invoice)
    if cint(si.docstatus) != 1:
        frappe.throw(_("{0} ist nicht submitted.").format(sales_invoice))

    outstanding = flt(si.outstanding_amount)
    if outstanding >= -0.01:
        frappe.throw(_("{0} hat kein auszahlbares Guthaben.").format(sales_invoice))

    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    pe = get_payment_entry("Sales Invoice", sales_invoice, bank_account=bank_account)
    pe.posting_date = posting_date or nowdate()
    pe.payment_type = "Pay"

    resolved_mode = _resolve_mode_of_payment(mode_of_payment)
    if resolved_mode:
        pe.mode_of_payment = resolved_mode

    amount = abs(outstanding)
    pe.paid_amount = amount
    pe.received_amount = amount
    for ref in pe.references:
        if ref.reference_doctype == "Sales Invoice" and ref.reference_name == sales_invoice:
            ref.outstanding_amount = outstanding
            ref.allocated_amount = outstanding

    pe.remarks = _("Auszahlung Guthaben {0} an {1}").format(sales_invoice, si.customer)
    pe.insert(ignore_permissions=False)
    return _draft_response(
        pe,
        "payment_entry",
        auszahlung=amount,
        customer=si.customer,
        sales_invoice=sales_invoice,
        mode_of_payment=resolved_mode,
    )


@frappe.whitelist()
def allocate_payment(
    payment_entry: str,
    allocations: str | list,
) -> dict:
    """Ordnet eine offene Vorauszahlung mehreren Sales Invoices zu.

    Args:
        payment_entry: PE-Name (eine unallokierte Vorauszahlung)
        allocations: Liste von ``{"invoice": "SI-x", "amount": 500.0}``
    """
    if isinstance(allocations, str):
        allocations = json.loads(allocations)

    if not frappe.has_permission("Payment Reconciliation", "create"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)
    pe = frappe.get_doc("Payment Entry", payment_entry)
    if cint(pe.docstatus) != 1:
        frappe.throw(_("Nur submitted Payment Entries können zur Abstimmung vorbereitet werden."))

    reconciliation = frappe.new_doc("Payment Reconciliation")
    for fieldname, value in {
        "company": pe.company,
        "party_type": getattr(pe, "party_type", None),
        "party": getattr(pe, "party", None),
        "receivable_payable_account": getattr(pe, "paid_from", None) or getattr(pe, "paid_to", None),
    }.items():
        _set_if_field(reconciliation, fieldname, value)

    lines = []
    allocated = 0.0
    for alloc in allocations or []:
        invoice = alloc.get("invoice")
        amount = flt(alloc.get("amount"))
        if not invoice or amount <= 0:
            continue
        lines.append(f"{invoice}: {frappe.format_value(amount, {'fieldtype': 'Currency'})}")
        allocated += amount

    reconciliation.insert(ignore_permissions=False)
    reconciliation.add_comment(
        "Comment",
        text=_("Vorbereitete Zuordnung für {0}:<br>{1}").format(
            payment_entry,
            "<br>".join(lines) if lines else _("Keine gültigen Zuordnungen ausgewählt."),
        ),
    )
    rest = flt(getattr(pe, "unallocated_amount", 0)) - allocated
    return _draft_response(
        reconciliation,
        "payment_reconciliation",
        allocated=len(lines),
        allocated_amount=allocated,
        rest=rest,
    )


@frappe.whitelist()
def write_off_invoice(
    sales_invoice: str,
    write_off_account: str | None = None,
    cost_center: str | None = None,
    remarks: str | None = None,
) -> dict:
    """Schreibt eine offene Sales Invoice ab (Forderung uneinbringlich)."""
    if not frappe.has_permission("Journal Entry", "create"):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    si = _require_submitted_invoice("Sales Invoice", sales_invoice)
    write_off_account = write_off_account or frappe.get_cached_value(
        "Company", si.company, "write_off_account"
    )
    if not write_off_account:
        frappe.throw(_("Für die Firma ist kein Write Off Account hinterlegt."))

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Write Off Entry"
    je.company = si.company
    je.posting_date = nowdate()
    je.user_remark = remarks or _("Abschreibung {0}").format(sales_invoice)
    amount = flt(si.outstanding_amount)
    je.append(
        "accounts",
        {
            "account": write_off_account,
            "debit_in_account_currency": amount,
            "cost_center": cost_center or getattr(si, "cost_center", None),
        },
    )
    je.append(
        "accounts",
        {
            "account": si.debit_to,
            "party_type": "Customer",
            "party": si.customer,
            "credit_in_account_currency": amount,
            "reference_type": "Sales Invoice",
            "reference_name": si.name,
        },
    )
    je.insert(ignore_permissions=False)
    return _draft_response(je, "journal_entry", amount=amount)


@frappe.whitelist()
def set_stundung_comment(
    sales_invoice: str,
    grund: str,
    notiz: str = "",
    stundung_bis: str | None = None,
) -> dict:
    """Dokumentiert eine Stundung als Kommentar auf der Sales Invoice."""
    if not frappe.has_permission("Sales Invoice", "write", sales_invoice):
        frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)

    si = frappe.get_doc("Sales Invoice", sales_invoice)
    parts = [_("Stundung vereinbart")]
    if stundung_bis:
        parts.append(_("bis {0}").format(stundung_bis))
    if grund:
        parts.append(_("Grund: {0}").format(grund))
    if notiz:
        parts.append(notiz)
    si.add_comment("Comment", text=". ".join(parts))
    return {"ok": True, "sales_invoice": sales_invoice}


# ───────────────────────────────────────────────────────────────────────────
# Optional · Custom-Status
# ───────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def set_klärungs_status(sales_invoice: str, grund: str, notiz: str = "") -> dict:
    """Setzt einen Custom-Status "in Klärung" auf einer Sales Invoice.

    Erfordert ein Custom-Field ``in_klaerung_grund`` (Small Text) auf der
    Sales Invoice. Falls nicht vorhanden, wird als Comment gepostet.
    """
    si = frappe.get_doc("Sales Invoice", sales_invoice)

    if hasattr(si, "in_klaerung_grund"):
        si.db_set("in_klaerung_grund", grund)
    si.add_comment("Comment", text=f"In Klärung: {grund}. {notiz}".strip())
    return {"ok": True}
