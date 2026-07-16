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


def _wohnungen_in_haus(immobilie: str | None = None, kostenstelle: str | None = None) -> List[str]:
    """Liste der Wohnungen über Immobilie oder (Fallback) über Kostenstelle→Haus.

    Mindestens einer der Parameter sollte gesetzt sein.
    """
    if immobilie:
        # Wenn Immobilie als Baum genutzt wird, können Wohnungen optional einem Knoten zugeordnet sein.
        # Falls der Name eine Knoten-Immobilie ist, liegen die Wohnungen unter `Wohnung.immobilie_knoten`.
        if _has_field("Wohnung", "immobilie_knoten"):
            rows = frappe.get_all(
                "Wohnung",
                filters={"immobilie_knoten": immobilie},
                pluck="name",
                limit=1,
            )
            if rows:
                return frappe.get_all("Wohnung", filters={"immobilie_knoten": immobilie}, pluck="name")

        return frappe.get_all("Wohnung", filters={"immobilie": immobilie}, pluck="name")

    if kostenstelle:
        cc_to_haus = _kostenstelle_zu_haus_map()
        haus = cc_to_haus.get(kostenstelle)
        if haus:
            return frappe.get_all("Wohnung", filters={"immobilie": haus}, pluck="name")
    return []


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
def get_mieter_festbetrag_overview(customer: str) -> List[Dict[str, object]]:
    """Zeigt Vertrags-Festbeträge und passende Dimensionsbuchungen je Mieter.

    Der Zeitraum einer Zeile entspricht dem Gültigkeitszeitraum des im
    Mietvertrag gepflegten Festbetrags. Dimensionsbuchungen werden nach
    Kostenart, Wohnung, Immobilien-Kostenstelle und effektivem Belegdatum
    zugeordnet – genauso wie in der BK-Allokation.
    """
    if not customer:
        return []
    frappe.get_doc("Customer", customer).check_permission("read")

    contracts = frappe.get_all(
        "Mietvertrag",
        filters={"kunde": customer},
        fields=["name", "wohnung", "immobilie"],
        order_by="von desc",
        limit_page_length=0,
    )
    if not contracts:
        return []

    contract_by_name = {row.name: row for row in contracts}
    fest_rows = frappe.get_all(
        "Betriebskosten Festbetrag",
        filters={
            "parenttype": "Mietvertrag",
            "parent": ("in", list(contract_by_name)),
        },
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
    if not fest_rows:
        return []

    kostenarten = sorted({row.betriebskostenart for row in fest_rows if row.betriebskostenart})
    art_rows = frappe.get_all(
        "Betriebskostenart",
        filters={"name": ("in", kostenarten), "verteilung": "Festbetrag"},
        fields=["name", "konto"],
        limit_page_length=0,
    ) if kostenarten else []
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

    result: List[Dict[str, object]] = []
    for row in fest_rows:
        contract = contract_by_name.get(row.mietvertrag)
        if not contract:
            continue
        art = row.betriebskostenart
        expected_cost_center = cost_center_by_immobilie.get(contract.immobilie)
        dimension_amount = Decimal("0")
        if art and row.gueltig_von and row.gueltig_bis and expected_cost_center:
            start = getdate(row.gueltig_von)
            end = getdate(row.gueltig_bis)
            for gl_row in gl_rows:
                if account_to_art.get(gl_row.account) != art:
                    continue
                if gl_row.get("wohnung") != contract.wohnung or gl_row.cost_center != expected_cost_center:
                    continue
                effective_date = getdate(_effective_date(gl_row, wert_map))
                if start <= effective_date <= end:
                    dimension_amount += _to_decimal(gl_row.debit) - _to_decimal(gl_row.credit)

        contract_amount = _to_decimal(row.betrag)
        result.append({
            "mietvertrag": row.mietvertrag,
            "wohnung": contract.wohnung,
            "bezeichnung": art or row.bezeichnung or "Festbetrag",
            "gueltig_von": cstr(row.gueltig_von),
            "gueltig_bis": cstr(row.gueltig_bis),
            "vertrags_festbetrag": float(_quantize_money(contract_amount)),
            "dimensionsbuchungen": float(_quantize_money(dimension_amount)),
            "gesamtbetrag": float(_quantize_money(contract_amount + dimension_amount)),
        })
    return result


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

    # Vorbereitung: Wohnungen je Haus
    whg_cache: Dict[str, List[str]] = {}
    festbetrag_cache: Dict[str, Dict[str, Dict[str, Decimal]]] = {}

    # Aggregiere je Haus & Kostenart (außer Einzeln) → Summe, die zu verteilen ist
    # Einzeln wird direkt auf Wohnungssumme gebucht
    for g in gl_rows:
        eff = getdate(_effective_date(g, wert_map))
        if eff < von_d or eff > bis_d:
            continue

        haus = cc_to_haus.get(g.cost_center)
        if not haus:
            continue
        kostenart = konto_map.get(g.account)
        if not kostenart:
            continue

        meta = art_meta.get(kostenart) or {}
        verteilung = (meta.get("verteilung") or "").strip()
        schluessel = meta.get("schluessel")

        betrag = _to_decimal(g.debit) - _to_decimal(g.credit)
        if betrag.copy_abs() < MIN_SIGNIFICANT:
            continue

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
            matrix[whg][kostenart] += betrag
            continue

        if verteilung.lower() in {"bewohner", "verbrauch", "formel"}:
            frappe.throw(f"Verteilungsart '{verteilung}' für umlagefähige Kostenart {kostenart} ist noch nicht implementiert.")

        # Wohnungen des Hauses cachen
        if haus not in whg_cache:
            whg_cache[haus] = _wohnungen_in_haus(immobilie=haus)
        whg_list = whg_cache[haus]
        if not whg_list:
            # Nichts zu verteilen → überspringen
            continue

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
                matrix[wohnung][kostenart] += _to_decimal(amount)

    # Runden nach dem in den Hausverwaltung-Einstellungen gewählten Verfahren.
    per_art: Dict[str, List[Tuple[str, Decimal]]] = defaultdict(list)
    for whg, arts in matrix.items():
        for art, val in arts.items():
            per_art[art].append((whg, val))

    rounded_matrix: Dict[str, Dict[str, float]] = {}
    rounding_method = get_bk_rounding_method()
    for art, entries in per_art.items():
        if not entries:
            continue
        rounded_entries = round_money_allocations(entries, rounding_method)
        for whg, rounded in rounded_entries.items():
            amount = float(rounded)
            rounded_matrix.setdefault(whg, {})[art] = amount

    rows: List[dict] = []
    for whg, arts in rounded_matrix.items():
        for art, amount in arts.items():
            rows.append({"wohnung": whg, "kostenart": art, "betrag": amount})

    return {"rows": rows, "matrix": rounded_matrix, "periode": {"von": von, "bis": bis}}
