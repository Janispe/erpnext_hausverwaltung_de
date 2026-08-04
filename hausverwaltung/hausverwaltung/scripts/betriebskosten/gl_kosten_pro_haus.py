"""
Ermittelt Betriebskosten je Haus (Immobilie) und Kostenart aus GL-Einträgen.

Wichtig: Wenn ein GL Entry auf eine Rechnung (Purchase/Sales Invoice) zeigt,
verwenden wir das Wertstellungsdatum des Belegs (Custom-Feld
`custom_wertstellungsdatum`) als Leistungszeitpunkt. Bei Purchase Invoices
fällt ein leeres Wertstellungsdatum auf das Fälligkeitsdatum zurück, danach auf
das Buchungsdatum. Nur Buchungen mit Leistungszeitpunkt innerhalb des
angegebenen Zeitraums [von, bis] werden berücksichtigt.

Rückgabe ist sowohl als flache Liste als auch als verschachtelte Matrix möglich.

Whitelisted Funktion:
    get_kosten_pro_haus(von: str, bis: str, company: Optional[str] = None)

Beispielaufruf (Bench Console):
    frappe.call("hausverwaltung.hausverwaltung.scripts.betriebskosten.gl_kosten_pro_haus.get_kosten_pro_haus",
                {"von": "2025-01-01", "bis": "2025-12-31"})
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

import frappe
from frappe.utils import getdate, cstr


def _konto_zu_kostenart_map() -> Dict[str, str]:
    """Konto -> Betriebskostenart (nur Einträge mit Konto, Kategorie 'Betriebskosten').

    Heizkosten-Kostenarten werden bewusst ausgefiltert: ihre Umlage erfolgt
    außerhalb dieses BK-Allocators (über die Heizkostenabrechnung Immobilie).
    """
    rows = frappe.get_all(
        "Betriebskostenart",
        fields=["name", "konto"],
        filters={"kategorie": "Betriebskosten"},
    )
    return {r.konto: r.name for r in rows if r.konto}


def _immobilien_hierarchy_maps(
    rows: Optional[Iterable[dict]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Resolve Immobilie tree nodes and Cost Centers to canonical roots.

    A Cost Center is sometimes configured both on the top-level property and
    on its building-part nodes (for example ``Haus``, ``Haus - HH``,
    ``Haus - SF`` and ``Haus - VH``).  A plain dict comprehension made the
    selected property depend on database row order and could therefore make
    the allocator silently ignore all GL costs for the actual top-level
    property.

    Duplicate assignments are safe only when every owner belongs to the same
    Immobilie tree.  Assignments spanning unrelated trees are accounting-data
    ambiguity and fail closed.

    Returns:
        ``(immobilie_name -> root_name, cost_center -> root_name)``
    """
    if rows is None:
        rows = frappe.get_all(
            "Immobilie",
            fields=[
                "name",
                "kostenstelle",
                "parent_immobilie",
                "old_parent",
            ],
            filters={},
            limit_page_length=0,
        )

    nodes: Dict[str, dict] = {}
    for raw_row in rows or []:
        row = frappe._dict(raw_row)
        name = cstr(row.get("name")).strip()
        if not name:
            continue
        parent = cstr(row.get("parent_immobilie")).strip()
        old_parent = cstr(row.get("old_parent")).strip()
        if parent and old_parent and parent != old_parent:
            frappe.throw(
                f"Immobilie '{name}' hat widersprüchliche Eltern-Zuordnungen "
                f"('{parent}' / '{old_parent}'). Kostenverteilung abgebrochen."
            )
        nodes[name] = {
            "parent": parent or old_parent,
            "kostenstelle": cstr(row.get("kostenstelle")).strip(),
        }

    roots: Dict[str, str] = {}

    def resolve_root(name: str, path: tuple[str, ...] = ()) -> str:
        if name in roots:
            return roots[name]
        if name in path:
            cycle = " → ".join((*path, name))
            frappe.throw(
                f"Die Immobilien-Hierarchie enthält einen Kreis ({cycle}). "
                "Kostenverteilung abgebrochen."
            )
        node = nodes.get(name)
        if not node:
            frappe.throw(
                f"Immobilie '{name}' fehlt in der Immobilien-Hierarchie. "
                "Kostenverteilung abgebrochen."
            )
        parent = node.get("parent")
        if parent:
            if parent not in nodes:
                frappe.throw(
                    f"Immobilie '{name}' verweist auf die fehlende "
                    f"Parent-Immobilie '{parent}'. Kostenverteilung abgebrochen."
                )
            root = resolve_root(parent, (*path, name))
        else:
            root = name
        roots[name] = root
        return root

    cost_center_roots: Dict[str, set[str]] = defaultdict(set)
    cost_center_owners: Dict[str, list[str]] = defaultdict(list)
    for name in nodes:
        resolve_root(name)
    for name, node in nodes.items():
        cost_center = node.get("kostenstelle")
        if not cost_center:
            continue
        root = roots[name]
        cost_center_roots[cost_center].add(root)
        cost_center_owners[cost_center].append(name)

    cost_center_map: Dict[str, str] = {}
    for cost_center, assigned_roots in cost_center_roots.items():
        if len(assigned_roots) != 1:
            owners = ", ".join(sorted(cost_center_owners[cost_center]))
            root_names = ", ".join(sorted(assigned_roots))
            frappe.throw(
                f"Kostenstelle '{cost_center}' ist mehreren unverbundenen "
                f"Immobilien zugeordnet ({owners}; Root-Immobilien: "
                f"{root_names}). Kostenverteilung abgebrochen."
            )
        cost_center_map[cost_center] = next(iter(assigned_roots))

    return roots, cost_center_map


def _immobilie_zu_root_map() -> Dict[str, str]:
    """Immobilie node -> canonical top-level Immobilie."""
    return _immobilien_hierarchy_maps()[0]


def _kostenstelle_zu_haus_map() -> Dict[str, str]:
    """Cost Center -> canonical top-level Immobilie (Haus), fail closed."""
    return _immobilien_hierarchy_maps()[1]


def _prefetch_wertstellungsdaten(
    gl_rows: List[dict],
) -> Dict[Tuple[str, str], str]:
    """Holt Wertstellungsdaten für verknüpfte Rechnungen vorab.

    Liefert Mapping (voucher_type, voucher_no) -> effektives Datum (YYYY-MM-DD).
    Für Purchase Invoices wird auf due_date, dann posting_date zurückgegriffen.
    Für andere Belegtypen wird auf deren posting_date zurückgegriffen. Andere
    Belegtypen werden nicht erfasst und fallen auf GL.posting_date zurück.
    """
    # Relevante Voucher separieren
    per_type: Dict[str, List[str]] = defaultdict(list)
    for g in gl_rows:
        vt = g.get("voucher_type")
        vn = g.get("voucher_no")
        if vt in ("Purchase Invoice", "Sales Invoice", "Journal Entry") and vn:
            per_type[vt].append(vn)

    result: Dict[Tuple[str, str], str] = {}

    if per_type.get("Purchase Invoice"):
        pris = frappe.get_all(
            "Purchase Invoice",
            filters={"name": ("in", list(set(per_type["Purchase Invoice"])))}
            ,
            fields=["name", "custom_wertstellungsdatum", "due_date", "posting_date"],
        )
        for r in pris:
            eff = r.custom_wertstellungsdatum or r.due_date or r.posting_date
            result[("Purchase Invoice", r.name)] = cstr(eff)

    if per_type.get("Sales Invoice"):
        sis = frappe.get_all(
            "Sales Invoice",
            filters={"name": ("in", list(set(per_type["Sales Invoice"])))}
            ,
            fields=["name", "custom_wertstellungsdatum", "posting_date"],
        )
        for r in sis:
            eff = r.custom_wertstellungsdatum or r.posting_date
            result[("Sales Invoice", r.name)] = cstr(eff)

    if per_type.get("Journal Entry"):
        jes = frappe.get_all(
            "Journal Entry",
            filters={"name": ("in", list(set(per_type["Journal Entry"])))}
            ,
            fields=["name", "custom_wertstellungsdatum", "posting_date"],
        )
        for r in jes:
            eff = r.custom_wertstellungsdatum or r.posting_date
            result[("Journal Entry", r.name)] = cstr(eff)

    return result


def _effective_date(g: dict, wert_map: Dict[Tuple[str, str], str]) -> str:
    key = (g.get("voucher_type"), g.get("voucher_no"))
    return wert_map.get(key) or cstr(g.get("posting_date"))


@frappe.whitelist()
def get_kosten_pro_haus(von: str, bis: str, company: Optional[str] = None) -> dict:
    """Summiert Betriebskosten je Haus und Kostenart aus GL-Einträgen.

    Regeln:
    - Es werden nur GL-Entries mit Account = Konto einer Betriebskostenart gezählt.
    - Zuordnung Haus via GL.cost_center == Immobilie.kostenstelle.
    - Leistungszeitpunkt ist das Wertstellungsdatum verknüpfter Rechnungen,
      bei Purchase Invoice danach due_date, ansonsten GL.posting_date.
      Nur Einträge innerhalb [von, bis] werden gezählt.

    Args:
        von: ISO-Datum (YYYY-MM-DD)
        bis: ISO-Datum (YYYY-MM-DD)
        company: optional zur weiteren Eingrenzung

    Returns:
        dict mit Schlüsseln:
          - rows:   Liste von {haus, kostenart, betrag}
          - matrix: {haus: {kostenart: betrag}}
          - periode: {von, bis}
    """
    von_d = getdate(von)
    bis_d = getdate(bis)

    konto_map = _konto_zu_kostenart_map()
    if not konto_map:
        return {"rows": [], "matrix": {}, "periode": {"von": von, "bis": bis}}

    cc_to_haus = _kostenstelle_zu_haus_map()
    if not cc_to_haus:
        return {"rows": [], "matrix": {}, "periode": {"von": von, "bis": bis}}

    gl_filters = {
        "account": ("in", list(konto_map.keys())),
        "cost_center": ("in", list(cc_to_haus.keys())),
    }
    if company:
        gl_filters["company"] = company

    # Nicht nach Datum filtern – der effektive Zeitraum wird via Wertstellungsdatum geprüft
    gl_rows = frappe.get_all(
        "GL Entry",
        filters=gl_filters,
        fields=[
            "posting_date",
            "account",
            "cost_center",
            "debit",
            "credit",
            "voucher_type",
            "voucher_no",
        ],
        order_by="posting_date asc",
    )

    if not gl_rows:
        return {"rows": [], "matrix": {}, "periode": {"von": von, "bis": bis}}

    wert_map = _prefetch_wertstellungsdaten(gl_rows)

    # Aggregation
    totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rows: List[dict] = []

    for g in gl_rows:
        eff_date = getdate(_effective_date(g, wert_map))
        if eff_date < von_d or eff_date > bis_d:
            continue

        haus = cc_to_haus.get(g.cost_center)
        if not haus:
            continue

        kostenart = konto_map.get(g.account)
        if not kostenart:
            continue

        betrag = (g.debit or 0) - (g.credit or 0)
        if abs(betrag) < 1e-9:
            continue

        totals[haus][kostenart] += betrag

    # Flache Rows erzeugen
    for haus, arts in totals.items():
        for art, summe in arts.items():
            rows.append({"haus": haus, "kostenart": art, "betrag": round(summe, 2)})

    # Rundung in Matrix anwenden
    matrix = {
        h: {a: round(v, 2) for a, v in arts.items()} for h, arts in totals.items()
    }

    return {"rows": rows, "matrix": matrix, "periode": {"von": von, "bis": bis}}
