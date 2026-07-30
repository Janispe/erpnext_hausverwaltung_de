"""
Teilt Betriebskosten eines Hauses auf einzelne Wohnungen auf.

Unterstützte Verteilungsarten je Betriebskostenart:
- "qm": anhand Wohnungsfläche (m²) aus dem Wohnungszustand zum Stichtag
- "Einzeln": direkt über die Accounting Dimension "wohnung" auf dem GL‑Eintrag
- "Festbetrag": dimensionsgebuchte Kosten direkt je Wohnung plus die im
  Mietvertrag gepflegten Festbeträge
- "Schlüssel": anhand eines Zustandsschlüssels im Wohnungszustand zum Stichtag

Nicht implementiert (wirft Fehler, wenn verwendet):
- "Bewohner", "Verbrauch", "Formel"

Zeitfenster der Kostenbestimmung wie in gl_kosten_pro_haus:
- Effektives Datum eines GL Entry ist Wertstellungsdatum der verknüpften Rechnung
  (Feld custom_wertstellungsdatum); bei Purchase Invoice sonst due_date, sonst
  posting_date.

Rückgabe:
- rows:   Liste von {wohnung, kostenart, betrag}
- matrix: {wohnung: {kostenart: betrag}}
- periode: {von, bis}

Aufruf (Bench Console):
  frappe.call("hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.allocate_kosten_auf_wohnungen",
              {"von": "2025-01-01", "bis": "2025-12-31", "immobilie": "<Haus>"})
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import cstr, getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.rounding import (
    get_bk_rounding_method,
    round_money_allocations,
)

# Reuse helpers from GL aggregation
from hausverwaltung.hausverwaltung.scripts.betriebskosten.gl_kosten_pro_haus import (
    _konto_zu_kostenart_map,
    _kostenstelle_zu_haus_map,
    _immobilie_zu_root_map,
    _prefetch_wertstellungsdaten,
    _effective_date,
)
from hausverwaltung.hausverwaltung.doctype.zustandsschluessel.zustandsschluessel import (
    get_effective_zustandsschluessel_value,
)


MONEY_QUANT = Decimal("0.01")
MIN_SIGNIFICANT = Decimal("0.000000001")


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _overlap_days(start_a: str | date, end_a: str | date, start_b: str | date, end_b: str | date) -> int:
    start = max(getdate(start_a), getdate(start_b))
    end = min(getdate(end_a), getdate(end_b))
    if start > end:
        return 0
    return (end - start).days + 1


def _period_days(start: str | date, end: str | date) -> int:
    start_d = getdate(start)
    end_d = getdate(end)
    if start_d > end_d:
        return 0
    return (end_d - start_d).days + 1


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        meta = frappe.get_meta(doctype)
        return bool(meta.get_field(fieldname))
    except Exception:
        return False


def validate_wohnung_cost_center_pair(
    wohnung: str,
    cost_center: str,
    *,
    cost_center_to_immobilie: Optional[Dict[str, str]] = None,
    wohnung_to_immobilie: Optional[Dict[str, Optional[str]]] = None,
    context: Optional[str] = None,
) -> str:
    """Validiert eine Wohnungsdimension fail-closed gegen ihre Kostenstelle.

    Eine dimensionsgebuchte Wohnung darf nur verwendet werden, wenn ihre
    Stammdaten-Immobilie exakt der Immobilie entspricht, die der Kostenstelle
    zugeordnet ist. Fehlende Stammdaten werden nicht still übersprungen.
    """
    label = f"{context}: " if context else ""
    wohnung = cstr(wohnung).strip()
    cost_center = cstr(cost_center).strip()
    if not wohnung:
        frappe.throw(f"{label}Wohnung fehlt.")
    if not cost_center:
        frappe.throw(f"{label}Kostenstelle fehlt.")

    cc_map = (
        cost_center_to_immobilie
        if cost_center_to_immobilie is not None
        else _kostenstelle_zu_haus_map()
    )
    expected_immobilie = cstr(cc_map.get(cost_center)).strip()
    if not expected_immobilie:
        frappe.throw(
            f"{label}Kostenstelle '{cost_center}' ist keiner Immobilie zugeordnet."
        )

    wohnung_cache = (
        wohnung_to_immobilie if wohnung_to_immobilie is not None else {}
    )
    if wohnung not in wohnung_cache:
        wohnung_cache[wohnung] = frappe.db.get_value(
            "Wohnung", wohnung, "immobilie"
        )
    actual_immobilie = cstr(wohnung_cache.get(wohnung)).strip()
    if not actual_immobilie:
        frappe.throw(
            f"{label}Wohnung '{wohnung}' wurde nicht gefunden oder hat keine "
            "Immobilie."
        )

    # Fast path for the normal case.  If Wohnung or Cost Center points to a
    # building-part node, compare both through the exact same canonical-root
    # resolver used by the GL allocator.
    actual_root = actual_immobilie
    expected_root = expected_immobilie
    if actual_immobilie != expected_immobilie:
        immobilie_roots = _immobilie_zu_root_map()
        actual_root = cstr(immobilie_roots.get(actual_immobilie)).strip()
        expected_root = cstr(immobilie_roots.get(expected_immobilie)).strip()
        if not actual_root or not expected_root:
            frappe.throw(
                f"{label}Wohnung '{wohnung}' gehört zur Immobilie "
                f"'{actual_immobilie}', die Kostenstelle '{cost_center}' zur "
                f"Immobilie '{expected_immobilie}'; mindestens eine davon "
                "konnte keiner kanonischen Root-Immobilie zugeordnet werden. "
                "Buchung abgebrochen."
            )

    if actual_root != expected_root:
        frappe.throw(
            f"{label}Wohnung '{wohnung}' gehört zur Immobilie "
            f"'{actual_immobilie}' (Root '{actual_root}'), die Kostenstelle "
            f"'{cost_center}' aber zur Immobilie '{expected_immobilie}' "
            f"(Root '{expected_root}'). Buchung abgebrochen."
        )
    return expected_root


def _wohnungen_in_haus(
    immobilie: str | None = None,
    kostenstelle: str | None = None,
) -> List[str]:
    """Liefert deterministisch alle Wohnungen der kanonischen Root-Immobilie.

    ``Wohnung.immobilie`` kann auf die Root-Immobilie oder einen ihrer Knoten
    zeigen; ``immobilie_knoten`` kann zusätzlich den Gebäudeteil präzisieren.
    Beide Zuordnungen werden über denselben Hierarchie-Resolver vereinheitlicht
    und anschließend vereinigt. So hängt die Ergebnismenge nicht davon ab, ob
    zufällig bereits eine Wohnung direkt auf einem einzelnen Knoten gefunden
    wurde.
    """
    requested_immobilie = cstr(immobilie).strip()
    requested_cost_center = cstr(kostenstelle).strip()
    if not requested_immobilie and not requested_cost_center:
        return []

    immobilie_roots = _immobilie_zu_root_map()
    roots: set[str] = set()
    if requested_immobilie:
        root = cstr(immobilie_roots.get(requested_immobilie)).strip()
        if not root:
            frappe.throw(
                f"Immobilie '{requested_immobilie}' konnte keiner kanonischen "
                "Root-Immobilie zugeordnet werden. Kostenverteilung abgebrochen."
            )
        roots.add(root)

    if requested_cost_center:
        cc_root = cstr(
            _kostenstelle_zu_haus_map().get(requested_cost_center)
        ).strip()
        if not cc_root:
            frappe.throw(
                f"Kostenstelle '{requested_cost_center}' ist keiner Immobilie "
                "zugeordnet. Kostenverteilung abgebrochen."
            )
        roots.add(cc_root)

    if len(roots) != 1:
        frappe.throw(
            f"Immobilie '{requested_immobilie}' und Kostenstelle "
            f"'{requested_cost_center}' gehören nicht zur selben "
            "Root-Immobilie. Kostenverteilung abgebrochen."
        )
    root = next(iter(roots))
    hierarchy_nodes = sorted(
        name for name, node_root in immobilie_roots.items() if node_root == root
    )
    if not hierarchy_nodes:
        frappe.throw(
            f"Root-Immobilie '{root}' enthält keine auflösbaren "
            "Hierarchieknoten. Kostenverteilung abgebrochen."
        )

    has_node_field = _has_field("Wohnung", "immobilie_knoten")
    fields = ["name", "immobilie"]
    if has_node_field:
        fields.append("immobilie_knoten")

    rows_by_name: Dict[str, Any] = {}
    for fieldname in ("immobilie", "immobilie_knoten"):
        if fieldname == "immobilie_knoten" and not has_node_field:
            continue
        rows = frappe.get_all(
            "Wohnung",
            filters={fieldname: ("in", hierarchy_nodes)},
            fields=fields,
            order_by="name asc",
            limit_page_length=0,
        )
        for row in rows or []:
            name = cstr(row.get("name")).strip()
            if name:
                rows_by_name[name] = row

    result: List[str] = []
    for name in sorted(rows_by_name):
        row = rows_by_name[name]
        primary = cstr(row.get("immobilie")).strip()
        node = cstr(row.get("immobilie_knoten")).strip() if has_node_field else ""
        assigned_roots: set[str] = set()
        for fieldname, value in (("immobilie", primary), ("immobilie_knoten", node)):
            if not value:
                continue
            assigned_root = cstr(immobilie_roots.get(value)).strip()
            if not assigned_root:
                frappe.throw(
                    f"Wohnung '{name}' verweist in {fieldname} auf die nicht "
                    f"auflösbare Immobilie '{value}'. Kostenverteilung abgebrochen."
                )
            assigned_roots.add(assigned_root)
        if len(assigned_roots) > 1:
            frappe.throw(
                f"Wohnung '{name}' ist über Immobilie und Immobilien-Knoten "
                "verschiedenen Root-Immobilien zugeordnet. "
                "Kostenverteilung abgebrochen."
            )
        if root in assigned_roots:
            result.append(name)
    return result


def _validate_gl_allocation_totals(
    expected_by_basis: Dict[Tuple[str, str], Decimal],
    allocation_matrix_by_basis: Dict[
        Tuple[str, str],
        Dict[str, Decimal],
    ],
) -> None:
    """Stellt sicher, dass jede relevante GL-Kostenbasis vollständig ankommt."""
    for (haus, kostenart), expected in sorted(expected_by_basis.items()):
        allocated = sum(
            allocation_matrix_by_basis.get((haus, kostenart), {}).values(),
            Decimal("0"),
        )
        difference = (
            _quantize_money(expected) - _quantize_money(allocated)
        ).copy_abs()
        if difference != Decimal("0.00"):
            frappe.throw(
                f"GL-Kosten für Haus '{haus}', Kostenart '{kostenart}' wurden "
                "nicht vollständig auf Wohnungen verteilt "
                f"(Basis {_quantize_money(expected):.2f}, verteilt "
                f"{_quantize_money(allocated):.2f}, Differenz "
                f"{difference:.2f}). Kostenverteilung abgebrochen."
            )


def _round_gl_allocation_bases(
    expected_by_basis: Dict[Tuple[str, str], Decimal],
    allocation_matrix_by_basis: Dict[
        Tuple[str, str],
        Dict[str, Decimal],
    ],
    rounding_method: str,
) -> Dict[Tuple[str, str], Dict[str, Decimal]]:
    """Rundet jede Haus/Kostenart-Basis ohne Centverschiebung zu anderen Häusern."""
    rounded_by_basis: Dict[Tuple[str, str], Dict[str, Decimal]] = {}
    for basis, expected in sorted(expected_by_basis.items()):
        entries = sorted(
            allocation_matrix_by_basis.get(basis, {}).items(),
            key=lambda item: item[0],
        )
        rounded = round_money_allocations(
            entries,
            rounding_method,
            target_total=_quantize_money(expected),
        )
        target = _quantize_money(expected)
        rounded_total = _quantize_money(
            sum(rounded.values(), Decimal("0"))
        )
        difference = target - rounded_total
        if difference:
            # Auch das ausdrücklich nicht restverteilende Rundungsverfahren
            # darf im Accounting-Allocator keine GL-Cents verlieren. Der
            # betragsmäßig größte Anteil ist der deterministische Ausgleich.
            if not entries:
                frappe.throw(
                    f"GL-Kostenbasis {basis[0]} / {basis[1]} hat keine "
                    "Wohnungsanteile. Kostenverteilung abgebrochen."
                )
            correction_key = max(
                entries,
                key=lambda item: (item[1].copy_abs(), str(item[0])),
            )[0]
            rounded[correction_key] += difference
        rounded_by_basis[basis] = rounded

    _validate_gl_allocation_totals(expected_by_basis, rounded_by_basis)
    return rounded_by_basis


def _zustand_am(wohnung: str, stichtag: str) -> Optional[str]:
    """Name des aktuellsten Wohnungszustands mit ab <= stichtag."""
    rows = frappe.get_all(
        "Wohnungszustand",
        filters={"wohnung": wohnung, "ab": ("<=", stichtag)},
        fields=["name"],
        order_by="ab desc",
        limit=1,
    )
    return rows[0].name if rows else None


def _bk_abrechnung_aktiv_am(wohnung: str, stichtag: str) -> bool:
    """Prüft, ob im Wohnungszustand zum Stichtag
    das Feld "betriebskostenabrechnung_durch_vermieter" aktiviert ist.

    Falls kein Zustand existiert, gilt dies als nicht aktiviert (False).
    """
    z = _zustand_am(wohnung, stichtag)
    if not z:
        return False
    try:
        val = frappe.db.get_value(
            "Wohnungszustand", z, "betriebskostenabrechnung_durch_vermieter"
        )
        return bool(val)
    except Exception:
        return False


def _flaeche_qm(wohnung: str, stichtag: str) -> float:
    """Fläche (m²) aus dem Wohnungszustand zum Stichtag."""
    z = _zustand_am(wohnung, stichtag)
    if not z:
        return 0.0
    try:
        # Feldname enthält Umlaut, daher als String anfordern
        qm = frappe.db.get_value("Wohnungszustand", z, "größe")
        return float(qm or 0) if qm is not None else 0.0
    except Exception:
        # Einige DBs haben alternativ 'groesse' – Fallback versuchen
        try:
            qm = frappe.db.get_value("Wohnungszustand", z, "groesse")
            return float(qm or 0)
        except Exception:
            return 0.0


def _schluesselwert(wohnung: str, stichtag: str, schluessel: str) -> float:
    """Effektiver Wert eines Zustandsschlüssels am Stichtag."""
    if not schluessel:
        return 0.0
    try:
        return float(get_effective_zustandsschluessel_value(wohnung, stichtag, schluessel) or 0)
    except Exception:
        return 0.0


def _betriebsarten_map() -> Dict[str, dict]:
    """Map Betriebskostenart → {verteilung, schluessel}.

    Achtung: Doc.name == Name (name1) laut Autoname.
    Filtert Heizkosten-Kategorie aus — die werden nicht über diesen Allocator umgelegt.
    """
    rows = frappe.get_all(
        "Betriebskostenart",
        fields=["name", "verteilung", "schlüssel"],
        filters={"kategorie": "Betriebskosten"},
    )
    return {r.name: {"verteilung": r.verteilung, "schluessel": r.get("schlüssel") or r.get("schluessel")}
            for r in rows}


def _prorated_festbetrag_rows(
    immobilie: str,
    von: str,
    bis: str,
    mietvertrag: str | None = None,
) -> List[Dict[str, object]]:
    """Lädt Festbeträge (Mietvertrag-Child-Rows) für den Zeitraum und rechnet anteilig."""
    wohnungen = _wohnungen_in_haus(immobilie=immobilie)
    if not wohnungen:
        return []
    if mietvertrag:
        mv_names = [mietvertrag]
    else:
        mv_names = frappe.get_all(
            "Mietvertrag",
            filters={"wohnung": ("in", wohnungen)},
            pluck="name",
            limit_page_length=0,
        )
    if not mv_names:
        return []
    rows = frappe.get_all(
        "Betriebskosten Festbetrag",
        filters={
            "parenttype": "Mietvertrag",
            "parent": ("in", mv_names),
            "gueltig_von": ("<=", bis),
            "gueltig_bis": (">=", von),
        },
        fields=["parent AS mietvertrag", "betriebskostenart", "bezeichnung", "betrag", "gueltig_von", "gueltig_bis"],
        limit_page_length=0,
    )
    mv_to_wohnung = {
        r.name: r.wohnung
        for r in frappe.get_all("Mietvertrag", filters={"name": ("in", mv_names)}, fields=["name", "wohnung"])
    }
    result: List[Dict[str, object]] = []
    for row in rows or []:
        mietvertrag_name = row.get("mietvertrag")
        wohnung = mv_to_wohnung.get(mietvertrag_name)
        kostenart = row.get("betriebskostenart") or row.get("bezeichnung")
        if not (wohnung and kostenart) or wohnung not in wohnungen:
            continue
        datensatz_tage = _period_days(row.get("gueltig_von"), row.get("gueltig_bis"))
        ueberlappung = _overlap_days(row.get("gueltig_von"), row.get("gueltig_bis"), von, bis)
        if datensatz_tage <= 0 or ueberlappung <= 0:
            continue
        betrag = _to_decimal(row.get("betrag")) * Decimal(str(ueberlappung)) / Decimal(str(datensatz_tage))
        if betrag.copy_abs() < MIN_SIGNIFICANT:
            continue
        result.append(
            {
                "wohnung": wohnung,
                "mietvertrag": mietvertrag_name,
                "kostenart": kostenart,
                "betrag": betrag,
            }
        )
    return result


def _festbetrag_map(immobilie: str, von: str, bis: str) -> Dict[str, Dict[str, Decimal]]:
    result: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    for row in _prorated_festbetrag_rows(immobilie=immobilie, von=von, bis=bis):
        wohnung = row.get("wohnung")
        kostenart = row.get("kostenart")
        if not (wohnung and kostenart):
            continue
        result[wohnung][kostenart] += _to_decimal(row.get("betrag"))
    return result


@frappe.whitelist()
def get_mieter_festbetrag_overview(
    customer: str,
    von: str | None = None,
    bis: str | None = None,
    mietvertrag: str | None = None,
) -> Dict[str, List[Dict[str, object]]]:
    """Zeigt manuelle Festbeträge und Dimensionsbuchungen getrennt je Mieter."""
    empty_result: Dict[str, List[Dict[str, object]]] = {
        "manual_rows": [],
        "dimension_rows": [],
    }
    if not customer:
        return empty_result
    frappe.get_doc("Customer", customer).check_permission("read")

    von_d = getdate(von) if von else None
    bis_d = getdate(bis) if bis else None
    if von_d and bis_d and von_d > bis_d:
        frappe.throw("Von darf nicht nach Bis liegen.")

    contract_filters: Dict[str, object] = {"kunde": customer}
    if mietvertrag:
        contract_filters["name"] = mietvertrag

    contracts = frappe.get_all(
        "Mietvertrag",
        filters=contract_filters,
        fields=["name", "wohnung", "immobilie", "von", "bis"],
        order_by="von desc",
        limit_page_length=0,
    )
    if not contracts:
        return empty_result

    contract_by_name = {row.name: row for row in contracts}
    fest_filters: Dict[str, object] = {
        "parenttype": "Mietvertrag",
        "parent": ("in", list(contract_by_name)),
    }
    if bis:
        fest_filters["gueltig_von"] = ("<=", bis)
    if von:
        fest_filters["gueltig_bis"] = (">=", von)
    fest_rows = frappe.get_all(
        "Betriebskosten Festbetrag",
        filters=fest_filters,
        fields=[
            "parent AS mietvertrag",
            "betriebskostenart",
            "bezeichnung",
            "betrag",
            "gueltig_von",
            "gueltig_bis",
            "idx",
        ],
        order_by="parent asc, idx asc",
        limit_page_length=0,
    )
    art_rows = frappe.get_all(
        "Betriebskostenart",
        filters={"verteilung": "Festbetrag"},
        fields=["name", "konto"],
        limit_page_length=0,
    )
    account_to_art = {row.konto: row.name for row in art_rows if row.konto}

    immobilien = sorted({row.immobilie for row in contracts if row.immobilie})
    immobilie_rows = frappe.get_all(
        "Immobilie",
        filters={"name": ("in", immobilien)},
        fields=["name", "kostenstelle"],
        limit_page_length=0,
    ) if immobilien else []
    cost_center_by_immobilie = {row.name: row.kostenstelle for row in immobilie_rows if row.kostenstelle}

    gl_rows = []
    wohnungen = sorted({row.wohnung for row in contracts if row.wohnung})
    cost_centers = sorted(set(cost_center_by_immobilie.values()))
    if account_to_art and wohnungen and cost_centers and _has_field("GL Entry", "wohnung"):
        gl_rows = frappe.get_all(
            "GL Entry",
            filters={
                "account": ("in", list(account_to_art)),
                "cost_center": ("in", cost_centers),
                "wohnung": ("in", wohnungen),
            },
            fields=[
                "name",
                "posting_date",
                "account",
                "cost_center",
                "wohnung",
                "debit",
                "credit",
                "voucher_type",
                "voucher_no",
            ],
            order_by="posting_date asc",
            limit_page_length=0,
        )
    wert_map = _prefetch_wertstellungsdaten(gl_rows)

    manual_rows: List[Dict[str, object]] = []
    for row in fest_rows:
        contract = contract_by_name.get(row.mietvertrag)
        if not contract:
            continue
        art = row.betriebskostenart
        contract_amount = _to_decimal(row.betrag)
        manual_rows.append({
            "mietvertrag": row.mietvertrag,
            "wohnung": contract.wohnung,
            "bezeichnung": art or row.bezeichnung or "Festbetrag",
            "gueltig_von": cstr(row.gueltig_von),
            "gueltig_bis": cstr(row.gueltig_bis),
            "betrag": float(_quantize_money(contract_amount)),
        })

    dimension_rows: List[Dict[str, object]] = []
    for gl_row in gl_rows:
        art = account_to_art.get(gl_row.account)
        if not art:
            continue
        effective_date = getdate(_effective_date(gl_row, wert_map))
        if von_d and effective_date < von_d:
            continue
        if bis_d and effective_date > bis_d:
            continue
        contract = next(
            (
                candidate
                for candidate in contracts
                if candidate.wohnung == gl_row.get("wohnung")
                and cost_center_by_immobilie.get(candidate.immobilie) == gl_row.cost_center
                and candidate.get("von")
                and getdate(candidate.von) <= effective_date
                and (not candidate.get("bis") or effective_date <= getdate(candidate.bis))
            ),
            None,
        )
        if not contract:
            continue
        dimension_amount = _to_decimal(gl_row.debit) - _to_decimal(gl_row.credit)
        if dimension_amount.copy_abs() < MIN_SIGNIFICANT:
            continue
        dimension_rows.append({
            "mietvertrag": contract.name,
            "wohnung": contract.wohnung,
            "bezeichnung": art,
            "belegdatum": cstr(effective_date),
            "belegtyp": cstr(gl_row.voucher_type),
            "belegnummer": cstr(gl_row.voucher_no),
            "betrag": float(_quantize_money(dimension_amount)),
        })
    return {
        "manual_rows": manual_rows,
        "dimension_rows": dimension_rows,
    }


@frappe.whitelist()
def allocate_kosten_auf_wohnungen(
    von: str,
    bis: str,
    immobilie: Optional[str] = None,
    company: Optional[str] = None,
    stichtag: Optional[str] = None,
) -> dict:
    """Allokiert Betriebskosten auf Wohnungen je Betriebskostenart.

    - Filtert GL Entries auf Konten der Betriebskostenarten und Kostenstellen der Immobilien.
    - Nutzt Wertstellungsdatum der verknüpften Belege zur Periodenfilterung [von, bis].
    - Aggregiert je Immobilie (Haus) und Betriebskostenart und verteilt gemäß Verteilungsart.
    - Für "Einzeln" und "Festbetrag" werden dimensionsgebuchte Beträge direkt
      je GL‑Zeile auf das Feld "wohnung" gebucht (Accounting Dimension erforderlich).
    - Bei "Festbetrag" kommen die im Mietvertrag gepflegten Festbeträge hinzu.
    """
    stichtag = stichtag or bis
    von_d = getdate(von)
    bis_d = getdate(bis)

    konto_map = _konto_zu_kostenart_map()
    # Auch ohne kontobasierte Kostenarten können freie Festbeträge existieren.
    # Diese werden weiter unten direkt aus den Mietverträgen übernommen.

    cc_to_haus = _kostenstelle_zu_haus_map()
    if not cc_to_haus and not immobilie:
        return {"rows": [], "matrix": {}, "periode": {"von": von, "bis": bis}}

    # Vorab-Validierung: Wenn für ein konkretes Haus (Immobilie) abgerechnet werden soll,
    # muss in allen Wohnungen dieses Hauses im Zustand zum Stichtag die Option
    # "Betriebskostenabrechnung durch Vermieter" aktiviert sein.
    if immobilie:
        whg_list_for_check = _wohnungen_in_haus(immobilie=immobilie)
        not_enabled: List[str] = []
        for w in whg_list_for_check:
            if not _bk_abrechnung_aktiv_am(w, cstr(stichtag)):
                not_enabled.append(w)
        if not_enabled:
            names = ", ".join(not_enabled)
            frappe.throw(
                f"Betriebskostenabrechnung für Haus {immobilie} kann nicht erstellt werden: "
                f"In folgenden Wohnungen ist 'Betriebskostenabrechnung durch Vermieter' zum Stichtag {stichtag} nicht aktiviert: {names}."
            )

    # Optional Immobilie→Kostenstelle einschränken
    kostenstellen = list(cc_to_haus.keys())
    if immobilie:
        kostenstellen = [cc for cc, haus in cc_to_haus.items() if haus == immobilie]
        if not kostenstellen:
            kostenstellen = []

    # GL laden (wie im Haus‑Report), optional mit Dimension "wohnung" falls vorhanden
    gl_rows = []
    gl_has_wohnung = _has_field("GL Entry", "wohnung")
    if kostenstellen:
        gl_filters = {
            "account": ("in", list(konto_map.keys())),
            "cost_center": ("in", kostenstellen),
        }
        if company:
            gl_filters["company"] = company

        gl_fields = [
            "name",
            "posting_date",
            "account",
            "cost_center",
            "debit",
            "credit",
            "voucher_type",
            "voucher_no",
        ]
        if gl_has_wohnung:
            gl_fields.append("wohnung")

        gl_rows = frappe.get_all(
            "GL Entry",
            filters=gl_filters,
            fields=gl_fields,
            order_by="posting_date asc",
        )

    wert_map = _prefetch_wertstellungsdaten(gl_rows)

    # Betriebskostenart‑Metadaten
    art_meta = _betriebsarten_map()

    # Ergebniscontainer
    matrix: Dict[str, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    gl_expected_by_basis: Dict[Tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    gl_matrix_by_basis: Dict[
        Tuple[str, str],
        Dict[str, Decimal],
    ] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    manual_matrix: Dict[str, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    festbetrag_gl_rows: list[dict] = []

    # Vorbereitung: Wohnungen je Haus
    whg_cache: Dict[str, List[str]] = {}
    festbetrag_cache: Dict[str, Dict[str, Dict[str, Decimal]]] = {}
    wohnung_immobilie_cache: Dict[str, Optional[str]] = {}

    # Aggregiere je Haus & Kostenart (außer Einzeln) → Summe, die zu verteilen ist
    # Einzeln wird direkt auf Wohnungssumme gebucht
    for g in gl_rows:
        eff = getdate(_effective_date(g, wert_map))
        if eff < von_d or eff > bis_d:
            continue

        haus = cc_to_haus.get(g.cost_center)
        if not haus:
            frappe.throw(
                f"GL Entry {g.get('name')} hat die nicht eindeutig einer "
                f"Immobilie zugeordnete Kostenstelle '{g.get('cost_center')}'. "
                "Kostenverteilung abgebrochen."
            )
        kostenart = konto_map.get(g.account)
        if not kostenart:
            frappe.throw(
                f"GL Entry {g.get('name')} verwendet das nicht eindeutig einer "
                f"Betriebskostenart zugeordnete Konto '{g.get('account')}'. "
                "Kostenverteilung abgebrochen."
            )

        meta = art_meta.get(kostenart) or {}
        verteilung = (meta.get("verteilung") or "").strip()
        schluessel = meta.get("schluessel")

        betrag = _to_decimal(g.debit) - _to_decimal(g.credit)
        if betrag.copy_abs() < MIN_SIGNIFICANT:
            continue
        basis = (haus, kostenart)
        gl_expected_by_basis[basis] += betrag

        if verteilung.lower() in {"einzeln", "festbetrag"}:
            if not gl_has_wohnung:
                frappe.throw(
                    f"Verteilungsart '{verteilung}' erfordert Accounting Dimension 'wohnung' auf GL Entry."
                )
            whg = g.get("wohnung")
            if not whg:
                frappe.throw(
                    f"GL Entry {g.get('name')} ohne 'wohnung' bei Verteilungsart '{verteilung}'."
                )
            validate_wohnung_cost_center_pair(
                whg,
                g.get("cost_center"),
                cost_center_to_immobilie=cc_to_haus,
                wohnung_to_immobilie=wohnung_immobilie_cache,
                context=f"GL Entry {g.get('name')}",
            )
            matrix[whg][kostenart] += betrag
            gl_matrix_by_basis[basis][whg] += betrag
            if verteilung.lower() == "festbetrag":
                festbetrag_gl_rows.append(
                    {
                        "gl_entry": g.get("name"),
                        "wohnung": whg,
                        "kostenart": kostenart,
                        "betrag": float(betrag),
                        "effective_date": cstr(eff),
                    }
                )
            continue

        if verteilung.lower() in {"bewohner", "verbrauch", "formel"}:
            frappe.throw(f"Verteilungsart '{verteilung}' für umlagefähige Kostenart {kostenart} ist noch nicht implementiert.")

        # Wohnungen des Hauses cachen
        if haus not in whg_cache:
            whg_cache[haus] = _wohnungen_in_haus(immobilie=haus)
        whg_list = whg_cache[haus]
        if not whg_list:
            frappe.throw(
                f"GL Entry {g.get('name')} über {_quantize_money(betrag):.2f} "
                f"für Kostenart '{kostenart}' kann nicht verteilt werden: "
                f"Der Root-Immobilie '{haus}' sind keine Wohnungen zugeordnet. "
                "Kostenverteilung abgebrochen."
            )

        # Gewichte je Wohnung bestimmen
        weights: Dict[str, Decimal] = {}
        if verteilung.lower() == "qm":
            for w in whg_list:
                weights[w] = _to_decimal(_flaeche_qm(w, cstr(stichtag)))
        elif verteilung.lower() == "schlüssel" or verteilung.lower() == "schluessel":
            if not schluessel:
                frappe.throw(f"Umlagefähige Kostenart {kostenart} hat keine Schlüssel‑Definition.")
            for w in whg_list:
                weights[w] = _to_decimal(_schluesselwert(w, cstr(stichtag), schluessel))
        else:
            # Unbekannt → Fehler
            frappe.throw(f"Unbekannte Verteilungsart '{verteilung}' für umlagefähige Kostenart {kostenart}.")

        total_weight = sum((v for v in weights.values() if v is not None), Decimal("0"))
        if total_weight <= Decimal("0"):
            # Datenproblem: alle Wohnungen haben am Stichtag 0 Gewicht. Statt
            # heimlich 1/N zu verteilen, klar machen was zu pruefen ist.
            # Echter Leerstand (qm>0, kein Mieter) wird hier nicht abgefangen:
            # Die Kosten bleiben auf Wohnungsebene erhalten. Beim spaeteren
            # Split nach Mietvertraegen wird nur der vermietete Zeitraum an
            # Mieter weiterbelastet; der Rest bleibt beim Vermieter.
            anzahl_whg = len(weights)
            frappe.throw(
                f"Verteilung '{verteilung}' für Kostenart '{kostenart}' (Haus {haus}, "
                f"Stichtag {stichtag}) ergibt keine Gewichte > 0 auf {anzahl_whg} Wohnung(en).<br><br>"
                "Mögliche Ursachen:<br>"
                "• qm-Feld in den Wohnungs-Stammdaten ist leer oder 0<br>"
                "• Schlüsselwert für die Kostenart fehlt<br>"
                "• Wohnungen existieren am Stichtag noch nicht (Stichtag liegt vor Anlage)<br><br>"
                "Bitte Wohnungs-Stammdaten und Stichtag prüfen."
            )

        for w, wgt in weights.items():
            if (wgt or Decimal("0")) <= Decimal("0"):
                continue
            anteil = betrag * (wgt / total_weight)
            matrix[w][kostenart] += anteil
            gl_matrix_by_basis[basis][w] += anteil

    # Manuelle Vertrags-Festbeträge werden erst danach ergänzt. Dadurch ist
    # dieser Abgleich ausschließlich gegen die aus GL Entries stammenden
    # Matrixanteile gerichtet und kann keine ausgelassene GL-Kostenbasis durch
    # einen zufällig gleich hohen Festbetrag verdecken.
    _validate_gl_allocation_totals(
        gl_expected_by_basis,
        gl_matrix_by_basis,
    )

    hauser_to_process = sorted(set(cc_to_haus.values()))
    if immobilie and immobilie not in hauser_to_process:
        hauser_to_process.append(immobilie)

    for haus in hauser_to_process:
        if immobilie and haus != immobilie:
            continue
        if haus not in whg_cache:
            whg_cache[haus] = _wohnungen_in_haus(immobilie=haus)
        if haus not in festbetrag_cache:
            festbetrag_cache[haus] = _festbetrag_map(haus, cstr(von), cstr(bis))
        for wohnung in whg_cache.get(haus, []):
            for kostenart, amount in (festbetrag_cache.get(haus, {}).get(wohnung) or {}).items():
                meta = art_meta.get(kostenart) or {}
                verteilung = (meta.get("verteilung") or "").strip()
                # Freie Bezeichnungen besitzen absichtlich keine Kostenart-
                # Metadaten und werden direkt als Zusatzposten übernommen.
                if meta and verteilung.lower() != "festbetrag":
                    continue
                if _to_decimal(amount).copy_abs() < MIN_SIGNIFICANT:
                    continue
                manual_amount = _to_decimal(amount)
                matrix[wohnung][kostenart] += manual_amount
                manual_matrix[wohnung][kostenart] += manual_amount

    # GL-Anteile werden je Root-Haus/Kostenart separat und summenerhaltend
    # gerundet. Andernfalls könnte eine globale Restverteilung einen Cent von
    # Haus A nach Haus B verschieben. Manuelle Festbeträge bleiben eine eigene
    # Rundungsbasis und können keine fehlenden GL-Anteile kaschieren.
    rounding_method = get_bk_rounding_method()
    rounded_gl_by_basis = _round_gl_allocation_bases(
        gl_expected_by_basis,
        gl_matrix_by_basis,
        rounding_method,
    )
    rounded_matrix_decimal: Dict[str, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    for (_haus, art), entries in rounded_gl_by_basis.items():
        for whg, amount in entries.items():
            rounded_matrix_decimal[whg][art] += amount

    manual_per_art: Dict[str, List[Tuple[str, Decimal]]] = defaultdict(list)
    for whg, arts in manual_matrix.items():
        for art, val in arts.items():
            manual_per_art[art].append((whg, val))

    for art, entries in manual_per_art.items():
        if not entries:
            continue
        rounded_entries = round_money_allocations(entries, rounding_method)
        for whg, rounded in rounded_entries.items():
            rounded_matrix_decimal[whg][art] += rounded

    rounded_matrix: Dict[str, Dict[str, float]] = {}
    for whg, arts in rounded_matrix_decimal.items():
        for art, amount in arts.items():
            rounded_matrix.setdefault(whg, {})[art] = float(amount)

    rows: List[dict] = []
    for whg, arts in rounded_matrix.items():
        for art, amount in arts.items():
            rows.append({"wohnung": whg, "kostenart": art, "betrag": amount})

    return {
        "rows": rows,
        "matrix": rounded_matrix,
        "festbetrag_gl_rows": festbetrag_gl_rows,
        "periode": {"von": von, "bis": bis},
    }
