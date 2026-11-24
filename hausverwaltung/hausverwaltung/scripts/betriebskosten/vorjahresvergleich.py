"""Lesender Belegnachweis zur Kostenbasis einer Immobilienabrechnung."""

from collections import defaultdict
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import add_years, getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.gl_kosten_pro_haus import (
    _immobilie_zu_root_map,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
    _allocate_kosten_auf_wohnungen,
    _quantize_money,
    _wohnungen_in_haus,
    summiere_kostenarten,
)
from hausverwaltung.hausverwaltung.utils.bk_sort import sort_key


def _period(von, bis, stichtag, offset=0):
    return {
        key: str(add_years(getdate(value), offset) if offset else getdate(value))
        for key, value in (("von", von), ("bis", bis), ("stichtag", stichtag))
    }


def _require_readable(documents):
    for doctype, name in sorted(documents, key=lambda key: tuple(str(value or "") for value in key)):
        if not doctype or not name or not frappe.has_permission(doctype, ptype="read", doc=name, throw=False):
            frappe.throw(
                _("Für den vollständigen Vorjahresvergleich fehlen Leserechte."),
                frappe.PermissionError,
            )


def _cost_basis(immobilie, period, *, historical=False):
    sources = []
    allocation = _allocate_kosten_auf_wohnungen(
        **period, immobilie=immobilie, sources=sources, historical_comparison=historical,
    )
    totals = {
        art: Decimal(str(amount))
        for art, amount in summiere_kostenarten(allocation["matrix"]).items()
    }
    return totals, sources


def _evidence_by_cost_type(totals, sources):
    # Ein Beleg kann mehrere GL-Zeilen derselben Kostenart und Zuordnung haben.
    grouped = defaultdict(Decimal)
    for row in sources:
        key = (
            row["kostenart"], row["wirksam_von"], row.get("wirksam_bis"),
            row["art"], row["doctype"], row["beleg"], row.get("wohnung"),
        )
        grouped[key] += row["betrag"]

    evidence = defaultdict(list)
    shown_amounts = defaultdict(Decimal)
    for key in sorted(grouped, key=lambda key: tuple(str(value or "") for value in key)):
        art, von, bis, kind, doctype, beleg, wohnung = key
        amount = _quantize_money(grouped[key])
        shown_amounts[art] += amount
        evidence[art].append({
            "art": kind,
            "doctype": doctype,
            "beleg": beleg,
            "wohnung": wohnung,
            "wirksam_von": str(von),
            "wirksam_bis": str(bis) if bis else None,
            "betrag": float(amount),
        })
    return {
        art: {
            "betrag": float(amount),
            "belege": evidence[art],
            "rundung": float(amount - shown_amounts[art]),
        }
        for art, amount in totals.items()
    }


def _read_cost_bases(immobilie, current, previous):
    # Validierungsfehler können fremde Namen enthalten, etwa bei einer
    # falsch gebuchten Wohnungsdimension. Details bleiben serverseitig.
    message_count = len(frappe.local.message_log)
    try:
        roots = _immobilie_zu_root_map()
        root = roots[immobilie]
        properties = {("Immobilie", node) for node, owner in roots.items() if owner == root}
        apartments = {("Wohnung", name) for name in _wohnungen_in_haus(immobilie=root)}
        _require_readable(properties | apartments)
        current_totals, current_sources = _cost_basis(root, current)
        previous_totals, previous_sources = _cost_basis(root, previous, historical=True)
        sources = current_sources + previous_sources
        _require_readable(
            {(row["doctype"], row["beleg"]) for row in sources}
            | {("GL Entry", row["gl_entry"]) for row in sources if "gl_entry" in row}
        )
        return root, current_totals, current_sources, previous_totals, previous_sources
    except (frappe.ValidationError, frappe.DoesNotExistError, KeyError):
        del frappe.local.message_log[message_count:]
        return None


@frappe.whitelist(methods=["GET"])
def get_vorjahresvergleich(name: str) -> dict:
    """Leitet Objekt und Zeiträume ausschließlich aus dem gespeicherten Kopf ab."""
    doc = frappe.get_doc("Betriebskostenabrechnung Immobilie", name)
    doc.check_permission("read")
    _require_readable({("Immobilie", doc.immobilie)})
    current = _period(doc.von, doc.bis, doc.stichtag or doc.bis)
    previous = _period(doc.von, doc.bis, doc.stichtag or doc.bis, offset=-1)

    basis = _read_cost_bases(doc.immobilie, current, previous)
    if basis is None:
        frappe.throw(
            _("Der Vorjahresvergleich konnte nicht berechnet werden. Bitte prüfen Sie die Zuordnung und Verteilungsbasis der Abrechnung."),
        )
    root, current_totals, current_sources, previous_totals, previous_sources = basis
    current_evidence = _evidence_by_cost_type(current_totals, current_sources)
    previous_evidence = _evidence_by_cost_type(previous_totals, previous_sources)
    rows = []
    for art in sorted(current_totals.keys() | previous_totals.keys(), key=sort_key):
        prior = previous_totals.get(art)
        delta = current_totals.get(art, Decimal(0)) - prior if prior is not None else None
        rows.append({
            "kostenart": art,
            "aktuell": current_evidence.get(art),
            "vorjahr": previous_evidence.get(art),
            "differenz": float(delta) if delta is not None else None,
            "prozent": float(_quantize_money(delta * 100 / abs(prior))) if prior else None,
        })
    return {"immobilie": root, "aktuell": current, "vorjahr": previous, "kostenarten": rows}
