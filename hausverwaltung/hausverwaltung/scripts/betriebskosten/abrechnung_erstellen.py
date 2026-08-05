"""
Erstellung fertiger Betriebskostenabrechnungen (Mieter und optional je Immobilie).

Nutzt vorhandene Hilfsfunktionen:
- allocate_kosten_auf_wohnungen: Verteilung der Kosten je Wohnung & Betriebskostenart
- get_bk_prepayment_summary: Vorauszahlungen (erwartet/bezahlt) je Wohnung

Whitelisted Endpunkte:
- create_bk_abrechnungen_immobilie(von, bis, immobilie, submit=False, stichtag=None)
- create_bk_abrechnung_wohnung(von, bis, wohnung, submit=False, stichtag=None)
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import cint, cstr, getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
    _prorated_festbetrag_rows,
    allocate_kosten_auf_wohnungen,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
    BK_ITEM_CODE,
    get_bk_expected_sum_for_invoice_names,
    get_bk_paid_sum_for_invoice_names,
    get_bk_prepayment_summary,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.rounding import (
    ROUNDING_METHOD_LARGEST_REMAINDER,
    ROUNDING_METHOD_LEGACY,
    ROUNDING_METHOD_ONLY,
    get_bk_rounding_method,
    round_money_allocations,
)
from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
    _company_via_wohnung,
)
from hausverwaltung.hausverwaltung.utils.betriebskostenregelung import (
    bk_invoice_period_for_segment,
    get_bk_regelungen_for_contracts,
    ist_bk_abrechenbar,
    normalize_bk_regelung,
    split_contract_segments_by_bk_regelung,
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


def _booking_decimal(value: Any, *, field_label: str) -> Decimal:
    """Parse a booking amount without silently converting corrupt data to zero."""
    if value in (None, ""):
        frappe.throw(
            f"{field_label} hat keinen Betrag; Buchung abgebrochen.",
            frappe.ValidationError,
        )
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(
            f"{field_label} enthält einen ungültigen Betrag ({value!r}); "
            "Buchung abgebrochen.",
            frappe.ValidationError,
        )
    if not amount.is_finite():
        frappe.throw(
            f"{field_label} enthält keinen endlichen Betrag ({value!r}); "
            "Buchung abgebrochen.",
            frappe.ValidationError,
        )
    return amount


def _bk_settlement_marker(abrechnung: str) -> str:
    owner = cstr(abrechnung or "").strip()
    if not owner or any(character in owner for character in "[]\r\n"):
        frappe.throw(
            "BK-Settlement abgebrochen: Der Child-Name ist für einen "
            "eindeutigen Ownership-Marker ungeeignet.",
            frappe.ValidationError,
        )
    return f"[BK-SETTLEMENT:{owner}]"


def _build_settlement_remark(
    von: Any = None,
    bis: Any = None,
    *,
    abrechnung: Optional[str] = None,
) -> str:
    """Erzeugt die sichtbare Bemerkung fuer BK-Nachzahlungen/Guthaben."""
    von_date = getdate(von) if von else None
    bis_date = getdate(bis) if bis else None
    if von_date and bis_date:
        visible = f"Betriebskostenabrechnung {von_date:%d.%m.%Y} bis {bis_date:%d.%m.%Y}"
    elif bis_date:
        visible = f"Betriebskostenabrechnung {bis_date.year}"
    elif von_date:
        visible = f"Betriebskostenabrechnung ab {von_date:%d.%m.%Y}"
    else:
        visible = "Betriebskostenabrechnung"
    settlement_name = cstr(abrechnung or "").strip()
    if settlement_name:
        return f"{_bk_settlement_marker(settlement_name)} {visible}"
    return visible


def _as_money(value: Decimal) -> float:
    return float(_quantize_money(value))


def _zustand_am(wohnung: str, stichtag: str) -> Optional[str]:
    rows = frappe.get_all(
        "Wohnungszustand",
        filters={"wohnung": wohnung, "ab": ("<=", stichtag)},
        fields=["name"],
        order_by="ab desc",
        limit=1,
    )
    return rows[0].name if rows else None


def _groesse_qm(wohnung: str, stichtag: str) -> float:
    z = _zustand_am(wohnung, stichtag)
    if not z:
        return 0.0
    # Versuche mit "größe" und Fallback "groesse"
    val = frappe.db.get_value("Wohnungszustand", z, "größe")
    if val is None:
        val = frappe.db.get_value("Wohnungszustand", z, "groesse")
    try:
        return float(val or 0)
    except Exception:
        return 0.0


def _immobilie_von_wohnung(wohnung: str) -> Optional[str]:
    try:
        return frappe.get_cached_value("Wohnung", wohnung, "immobilie")
    except Exception:
        return None


def _canonical_immobilie_root(immobilie: str) -> str:
    from hausverwaltung.hausverwaltung.scripts.betriebskosten.gl_kosten_pro_haus import (
        _immobilie_zu_root_map,
    )

    name = cstr(immobilie or "").strip()
    root = cstr((_immobilie_zu_root_map() or {}).get(name) or "").strip()
    if not name or not root:
        frappe.throw(
            f"Immobilie {name or 'leer'} kann keiner kanonischen "
            "Root-Immobilie zugeordnet werden.",
            frappe.ValidationError,
        )
    return root


def _wohnung_belongs_to_immobilie_hierarchy(
    wohnung: str,
    immobilie: str,
) -> bool:
    from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
        _wohnungen_in_haus,
    )

    return cstr(wohnung or "").strip() in set(
        _wohnungen_in_haus(immobilie=immobilie)
    )


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.get_meta(doctype).get_field(fieldname))
    except Exception:
        return False


def _cost_center_for_wohnung(wohnung: Optional[str]) -> Optional[str]:
    if not wohnung:
        return None
    immobilie = _immobilie_von_wohnung(wohnung)
    if not immobilie:
        return None
    try:
        return frappe.get_cached_value("Immobilie", immobilie, "kostenstelle")
    except Exception:
        return None


def _cost_center_for_abrechnung_doc(doc) -> Optional[str]:
    cost_center = doc.get("cost_center") if hasattr(doc, "get") else None
    if cost_center:
        return cost_center

    immobilie = doc.get("immobilie") if hasattr(doc, "get") else None
    if immobilie:
        try:
            cost_center = frappe.get_cached_value("Immobilie", immobilie, "kostenstelle")
        except Exception:
            cost_center = None
        if cost_center:
            return cost_center

    locked_identity = getattr(doc, "_locked_mietvertrag_identity", None) or {}
    wohnung = locked_identity.get("wohnung") or (
        doc.get("wohnung") if hasattr(doc, "get") else None
    )
    return _cost_center_for_wohnung(wohnung)


def _get_default_company(doc: Any = None) -> Optional[str]:
    if doc is not None:
        locked_identity = getattr(doc, "_locked_mietvertrag_identity", None) or {}
        wohnung = locked_identity.get("wohnung") or (
            doc.get("wohnung") if hasattr(doc, "get") else None
        )
        company = _company_via_wohnung(wohnung, for_update=True)
        if company:
            return company
        frappe.throw(
            "Für die Wohnung ist keine eindeutige Company aus der Immobilie "
            "ableitbar. In einer Multi-Company-Umgebung muss mindestens eine "
            "Kostenstelle, ein Konto oder ein Bankkonto der Immobilie eindeutig "
            "zugeordnet sein. Es wurde nichts gebucht."
        )
    try:
        d = frappe.defaults.get_defaults() or {}
        comp = d.get("company")
        if comp:
            return comp
        rows = frappe.get_all("Company", pluck="name", limit=1)
        return rows[0] if rows else None
    except Exception:
        return None


def _find_income_account(company: Optional[str]) -> Optional[str]:
    filters = {"root_type": "Income", "is_group": 0}
    if company:
        filters["company"] = company
    # Only a unique, explicitly named setup may be selected automatically.
    # Picking an arbitrary income account is an accounting mutation, not a
    # harmless default.
    rows = frappe.get_all(
        "Account",
        filters={
            **filters,
            "account_name": "Betriebskostenabrechnung",
        },
        pluck="name",
        limit_page_length=0,
    )
    return rows[0] if len(rows or []) == 1 else None


def _ensure_item_with_income(item_code: str, item_name: str, company: Optional[str]) -> str:
    """Create/complete a settlement item using the current user's permissions.

    Settlement is a user-triggered accounting operation.  Missing master data
    must therefore never be created or changed with elevated permissions.
    ``insert``/``save`` deliberately enforce the caller's Item permissions; the
    surrounding self-check turns a denial into a clear setup error.
    """
    if frappe.db.exists("Item", item_code):
        if company:
            it = frappe.get_doc("Item", item_code)
            has_def = any(d.company == company and d.income_account for d in (it.item_defaults or []))
            if not has_def:
                inc = _find_income_account(company)
                if not inc:
                    frappe.throw(
                        f"Artikel '{item_code}' hat für {company} kein "
                        "eindeutig konfiguriertes Income Account Default.",
                        frappe.ValidationError,
                    )
                it.append("item_defaults", {"company": company, "income_account": inc})
                it.save()
        return item_code
    it = frappe.new_doc("Item")
    it.item_code = item_code
    it.item_name = item_name
    it.item_group = "All Item Groups"
    it.is_sales_item = 1
    it.maintain_stock = 0
    it.stock_uom = "Nos"
    if company:
        inc = _find_income_account(company)
        if not inc:
            frappe.throw(
                f"Artikel '{item_code}' fehlt und für {company} ist kein "
                "eindeutiges Settlement-Income-Konto konfiguriert.",
                frappe.ValidationError,
            )
        it.append("item_defaults", {"company": company, "income_account": inc})
    it.insert()
    return item_code


def _mietvertraege_fuer_zeitraum(wohnung: str, von: str, bis: str) -> List[dict]:
    where = ["wohnung = %(whg)s", "von <= %(bis)s", "(bis IS NULL OR bis >= %(von)s)"]
    params = {"whg": wohnung, "von": getdate(von), "bis": getdate(bis)}
    return frappe.db.sql(
        f"""
        SELECT name, von, bis, kunde
        FROM `tabMietvertrag`
        WHERE {' AND '.join(where)}
        ORDER BY von ASC
        """,
        params,
        as_dict=True,
    )


def _mietvertrag_segmente_fuer_zeitraum(
    wohnung: str,
    von: str,
    bis: str,
    *,
    lock_regelungen: bool = False,
) -> List[dict]:
    """Ermittle Vertrags- und BK-Regelungssegmente im Zeitraum.

    Segmente werden auf [von,bis] geclippt und an jeder Änderung zwischen
    Vorauszahlung und Pauschale/Inklusivmiete geteilt. Vertragsüberlappungen
    führen weiterhin zu einem Fehler.
    """
    mv_list = _mietvertraege_fuer_zeitraum(wohnung, von, bis)
    if not mv_list:
        return []
    von_d = getdate(von)
    bis_d = getdate(bis)
    segments: List[dict] = []
    for mv in mv_list or []:
        mv_von = getdate(mv.get("von")) if mv.get("von") else None
        mv_bis = getdate(mv.get("bis")) if mv.get("bis") else None
        if not mv_von:
            continue
        seg_start = mv_von if mv_von > von_d else von_d
        seg_end = mv_bis if mv_bis and mv_bis < bis_d else bis_d
        if seg_start > seg_end:
            continue
        seg_days = (seg_end - seg_start).days + 1
        segments.append(
            {
                "mietvertrag": mv.get("name"),
                "kunde": mv.get("kunde"),
                "start": seg_start,
                "end": seg_end,
                "days": seg_days,
                "raw": mv,
            }
        )
    segments.sort(key=lambda s: s["start"])

    # Overlap-Check
    for i in range(1, len(segments)):
        prev = segments[i - 1]
        cur = segments[i]
        if cur["start"] <= prev["end"]:
            pv = prev["raw"]
            cv = cur["raw"]
            if cur["start"] == prev["end"]:
                # Same-day-Wechsel ist mehrdeutig (wem gehoert der Tag?) — Daten-
                # Eingabe-Fehler in 99% der Faelle. Spezifische Meldung mit klarer
                # Handlungsanweisung, statt heimlich eine Konvention zu waehlen.
                frappe.throw(
                    "Same-day-Wechsel der Mietverträge nicht erlaubt: "
                    f"{pv.get('name')} endet am {pv.get('bis')}, "
                    f"{cv.get('name')} startet am {cv.get('von')} — derselbe Tag. "
                    "Bitte ein Datum korrigieren: Vor-Mieter einen Tag früher beenden "
                    "oder Nach-Mieter einen Tag später beginnen lassen."
                )
            frappe.throw(
                "Überlappende Mietverträge gefunden: "
                f"{pv.get('name')} ({pv.get('von')} - {pv.get('bis') or 'offen'}) und "
                f"{cv.get('name')} ({cv.get('von')} - {cv.get('bis') or 'offen'})."
            )
    regelungen = get_bk_regelungen_for_contracts(
        [segment.get("mietvertrag") for segment in segments],
        lock=lock_regelungen,
    )
    return split_contract_segments_by_bk_regelung(segments, regelungen)


def _abrechenbare_bk_segmente(segments: List[dict]) -> List[dict]:
    return [segment for segment in segments if ist_bk_abrechenbar(segment.get("abrechnungsart"))]


def _bestehender_mietvertrag_fuer_stichtag(wohnung: str, stichtag: str) -> Optional[str]:
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabMietvertrag`
        WHERE wohnung = %(wohnung)s
          AND von <= %(stichtag)s
          AND (bis IS NULL OR bis >= %(stichtag)s)
        ORDER BY von DESC
        LIMIT 1
        """,
        {"wohnung": wohnung, "stichtag": getdate(stichtag)},
        as_dict=True,
    )
    return rows[0].name if rows else None


def _vertragspartner_rows(mietvertrag: str, von: str, bis: str) -> List[dict]:
    """Filtere Vertragspartner, die im Zeitraum beteiligt sind."""
    children = frappe.get_all(
        "Vertragspartner",
        filters={"parent": mietvertrag},
        fields=["mieter", "rolle", "eingezogen", "ausgezogen"],
        order_by="idx asc",
    )
    von_d = getdate(von)
    bis_d = getdate(bis)
    rows: List[dict] = []
    for r in children or []:
        ein = getdate(r.get("eingezogen")) if r.get("eingezogen") else None
        aus = getdate(r.get("ausgezogen")) if r.get("ausgezogen") else None
        if (ein is None or ein <= bis_d) and (aus is None or aus >= von_d):
            rows.append(r)
    return rows


def _vertragspartner_rows_for_period(wohnung: str, von: str, bis: str) -> List[dict]:
    """Vertragspartner aus allen Mietverträgen, die im Zeitraum überlappen."""
    mv_list = _mietvertraege_fuer_zeitraum(wohnung, von, bis)
    rows: List[dict] = []
    for mv in mv_list or []:
        rows.extend(_vertragspartner_rows(mv.get("name"), von, bis))
    return rows


def _add_abrechnungsposten(doc, posten: Dict[str, Any]):
    for art, betrag in posten.items():
        amount = _to_decimal(betrag)
        if amount.copy_abs() < MIN_SIGNIFICANT:
            continue
        values = {"betrag": _as_money(amount)}
        if frappe.db.exists("Betriebskostenart", art):
            values["betriebskostenart"] = art
        else:
            values["bezeichnung"] = art
        doc.append("abrechnung", values)


def _festbetrag_gl_posten_by_segment(
    segments: list[dict],
    gl_rows: list[dict],
    wohnung: str,
    posten_fest: dict[str, Decimal],
) -> list[dict[str, Decimal]]:
    """Ordnet jede Festbetrag-GL-Zeile vollständig ihrem Mietvertrag zu."""
    result: list[dict[str, Decimal]] = [{} for _segment in segments]
    for row in gl_rows or []:
        if row.get("wohnung") != wohnung:
            continue
        art = row.get("kostenart")
        if art not in posten_fest:
            continue
        effective_date = getdate(row.get("effective_date")) if row.get("effective_date") else None
        matches = [
            index
            for index, segment in enumerate(segments)
            if effective_date and segment["start"] <= effective_date <= segment["end"]
        ]
        gl_entry = row.get("gl_entry") or "unbekannt"
        if not matches:
            frappe.throw(
                f"Festbetrag-Buchung {gl_entry} für Wohnung '{wohnung}' am "
                f"{cstr(effective_date) or 'unbekannten Datum'} kann keinem Mietvertrag zugeordnet werden."
            )
        if len(matches) > 1:
            frappe.throw(
                f"Festbetrag-Buchung {gl_entry} für Wohnung '{wohnung}' am "
                f"{cstr(effective_date)} ist mehreren Mietverträgen zugeordnet."
            )
        amount = _to_decimal(row.get("betrag"))
        if amount.copy_abs() < MIN_SIGNIFICANT:
            continue
        segment_amounts = result[matches[0]]
        segment_amounts[art] = segment_amounts.get(art, Decimal("0")) + amount
    return result


def _build_bk_segment_costs(
    *,
    alloc: dict,
    immobilie: str,
    wohnung: str,
    von: str,
    bis: str,
    posten: Dict[str, Decimal],
    segments: List[dict],
) -> List[Dict[str, Decimal]]:
    """Project the current apartment cost matrix onto current tenant segments."""
    festbetrag_arten = {
        row.get("name")
        for row in (
            frappe.get_all(
                "Betriebskostenart",
                filters={
                    "verteilung": "Festbetrag",
                    "kategorie": "Betriebskosten",
                },
                fields=["name"],
                limit_page_length=0,
            )
            or []
        )
        if row.get("name")
    }
    festbetrag_arten.update(
        row.get("kostenart")
        for row in _prorated_festbetrag_rows(
            immobilie=immobilie,
            von=von,
            bis=bis,
        )
        if row.get("kostenart")
    )
    posten_fest = {
        art: amount for art, amount in posten.items() if art in festbetrag_arten
    }
    posten_zeitanteilig = {
        art: amount
        for art, amount in posten.items()
        if art not in festbetrag_arten
    }
    festbetrag_gl_by_segment = _festbetrag_gl_posten_by_segment(
        segments=segments,
        gl_rows=alloc.get("festbetrag_gl_rows") or [],
        wohnung=wohnung,
        posten_fest=posten_fest,
    )

    period_days = (getdate(bis) - getdate(von)).days + 1
    if period_days <= 0:
        frappe.throw(f"Ungültiger Zeitraum {von} bis {bis}.")
    period_days_dec = Decimal(str(period_days))

    seg_posten: List[Dict[str, Decimal]] = []
    total_unrounded = Decimal("0")
    for segment_index, seg in enumerate(segments):
        seg_start = seg["start"].strftime("%Y-%m-%d")
        seg_end = seg["end"].strftime("%Y-%m-%d")
        factor = Decimal(str(seg["days"])) / period_days_dec
        seg_amounts: Dict[str, Decimal] = dict(
            festbetrag_gl_by_segment[segment_index]
        )
        total_unrounded += sum(seg_amounts.values(), Decimal("0"))
        for art, amount in posten_zeitanteilig.items():
            amt = _to_decimal(amount) * factor
            if amt.copy_abs() < MIN_SIGNIFICANT:
                continue
            seg_amounts[art] = amt
            total_unrounded += amt
        mv = seg.get("mietvertrag")
        if mv and posten_fest:
            fest_rows = _prorated_festbetrag_rows(
                immobilie=immobilie,
                von=seg_start,
                bis=seg_end,
                mietvertrag=mv,
            )
            for row in fest_rows:
                art = row.get("kostenart")
                if art not in posten_fest:
                    continue
                amt = _to_decimal(row.get("betrag"))
                if amt.copy_abs() < MIN_SIGNIFICANT:
                    continue
                seg_amounts[art] = seg_amounts.get(art, Decimal("0")) + amt
                total_unrounded += amt
        seg_posten.append(seg_amounts)

    target_total = _quantize_money(total_unrounded)
    rounding_method = get_bk_rounding_method()
    if rounding_method in {
        ROUNDING_METHOD_LARGEST_REMAINDER,
        ROUNDING_METHOD_ONLY,
    }:
        arts = sorted({art for amounts in seg_posten for art in amounts})
        for art in arts:
            entries = [
                (index, amounts[art])
                for index, amounts in enumerate(seg_posten)
                if art in amounts
            ]
            rounded = round_money_allocations(entries, rounding_method)
            for index, amount in rounded.items():
                seg_posten[index][art] = amount
    elif rounding_method == ROUNDING_METHOD_LEGACY and seg_posten:
        written = sum(
            (
                _quantize_money(amount)
                for amounts in seg_posten
                for amount in amounts.values()
            ),
            Decimal("0"),
        )
        drift = _quantize_money(target_total - written)
        if drift.copy_abs() >= MONEY_QUANT and seg_posten[-1]:
            first_art = next(iter(seg_posten[-1]))
            seg_posten[-1][first_art] += drift
    return seg_posten


def _require_bk_generation_authorization(
    *,
    head: Optional[str],
    von: str,
    bis: str,
    stichtag: Optional[str] = None,
    immobilie: Optional[str] = None,
    wohnung: Optional[str] = None,
    submit: bool = False,
):
    """Authorize internal tenant-settlement generation through its exact head.

    ``Betriebskostenabrechnung Mieter`` is intentionally not directly
    createable in the role model.  Its whitelisted generator therefore needs a
    narrow, document-bound authorization before the internal child insert may
    bypass that create permission.
    """
    submit = bool(cint(submit))
    if submit:
        frappe.throw(
            "Direktes Einreichen über den BK-Generator ist nicht erlaubt. "
            "Bitte die Betriebskostenabrechnung Immobilie einreichen.",
            frappe.ValidationError,
        )

    head_name = cstr(head or "").strip()
    if not head_name:
        frappe.throw(
            "Mieter-Abrechnungen dürfen nur über eine "
            "Betriebskostenabrechnung Immobilie erzeugt werden; 'head' fehlt.",
            frappe.PermissionError,
        )

    try:
        head_doc = frappe.get_doc(
            "Betriebskostenabrechnung Immobilie",
            head_name,
            for_update=True,
        )
    except frappe.DoesNotExistError:
        frappe.throw(
            f"Betriebskostenabrechnung Immobilie {head_name} wurde nicht gefunden.",
            frappe.ValidationError,
        )

    for permission_type in ("read", "write"):
        if not frappe.has_permission(
            "Betriebskostenabrechnung Immobilie",
            ptype=permission_type,
            doc=head_doc,
        ):
            frappe.throw(
                "Keine Berechtigung für Betriebskostenabrechnung Immobilie: "
                f"{permission_type}.",
                frappe.PermissionError,
            )

    if cint(getattr(head_doc, "docstatus", 0)) != 0:
        frappe.throw(
            f"Betriebskostenabrechnung Immobilie {head_name} ist nicht mehr "
            "im Entwurf. Mieter-Abrechnungen werden ausschließlich unter "
            "einem gesperrten Entwurfs-Kopf erzeugt.",
            frappe.ValidationError,
        )

    head_immobilie = cstr(getattr(head_doc, "immobilie", None) or "").strip()
    claimed_immobilie = cstr(immobilie or "").strip()
    if not head_immobilie:
        frappe.throw(
            f"Betriebskostenabrechnung Immobilie {head_name} hat keine Immobilie.",
            frappe.ValidationError,
        )
    if claimed_immobilie and (
        _canonical_immobilie_root(claimed_immobilie)
        != _canonical_immobilie_root(head_immobilie)
    ):
        frappe.throw(
            f"Immobilie {claimed_immobilie} passt nicht zum Kopf "
            f"{head_name} ({head_immobilie}).",
            frappe.ValidationError,
        )

    try:
        requested_from = getdate(von)
        requested_to = getdate(bis)
        head_from = getdate(getattr(head_doc, "von", None))
        head_to = getdate(getattr(head_doc, "bis", None))
    except Exception:
        frappe.throw(
            f"Zeitraum von Kopf {head_name} oder Aufruf ist ungültig.",
            frappe.ValidationError,
        )
    if requested_from != head_from or requested_to != head_to:
        frappe.throw(
            f"Zeitraum {requested_from} bis {requested_to} passt nicht zum "
            f"Kopf {head_name} ({head_from} bis {head_to}).",
            frappe.ValidationError,
        )

    requested_stichtag = getdate(stichtag or bis)
    head_stichtag = getdate(getattr(head_doc, "stichtag", None) or head_to)
    if requested_stichtag != head_stichtag:
        frappe.throw(
            f"Stichtag {requested_stichtag} passt nicht zum Kopf "
            f"{head_name} ({head_stichtag}).",
            frappe.ValidationError,
        )

    if wohnung:
        if not _wohnung_belongs_to_immobilie_hierarchy(
            wohnung,
            head_immobilie,
        ):
            frappe.throw(
                f"Wohnung {wohnung} gehört nicht zur kanonischen "
                f"Immobilienhierarchie von Kopf {head_name} "
                f"({head_immobilie}).",
                frappe.ValidationError,
            )

    return head_doc


def _existing_bk_children_for_head_wohnung(
    head: str,
    wohnung: str,
    expected_segments: List[dict],
) -> List[str]:
    """Current/locking idempotency read for one header/apartment pair."""
    rows = frappe.db.sql(
        """
        SELECT name, docstatus, wohnung, mietvertrag, von, bis, abrechnungsart
        FROM `tabBetriebskostenabrechnung Mieter`
        WHERE immobilien_abrechnung = %s
          AND wohnung = %s
          AND docstatus < 2
        ORDER BY name
        FOR UPDATE
        """,
        (head, wohnung),
        as_dict=True,
    )
    non_drafts = [
        cstr(row.get("name"))
        for row in rows or []
        if cint(row.get("docstatus")) != 0
    ]
    if non_drafts:
        frappe.throw(
            "Inkonsistenter BK-Entwurf: Unter dem Entwurfs-Kopf existieren "
            "bereits eingereichte Mieter-Abrechnungen "
            f"({', '.join(non_drafts)}). Es wurde nichts erzeugt.",
            frappe.ValidationError,
        )
    if not rows:
        return []

    expected_keys = [
        (
            wohnung,
            cstr(segment.get("mietvertrag") or "").strip(),
            getdate(segment.get("start")),
            getdate(segment.get("end")),
            normalize_bk_regelung(segment.get("abrechnungsart")),
        )
        for segment in expected_segments
    ]
    actual_keys = [
        (
            cstr(row.get("wohnung") or "").strip(),
            cstr(row.get("mietvertrag") or "").strip(),
            getdate(row.get("von")),
            getdate(row.get("bis")),
            normalize_bk_regelung(row.get("abrechnungsart")),
        )
        for row in rows
    ]
    if (
        len(set(expected_keys)) != len(expected_keys)
        or len(set(actual_keys)) != len(actual_keys)
        or sorted(expected_keys) != sorted(actual_keys)
    ):
        frappe.throw(
            "BK-Generator abgebrochen: Bereits vorhandene Mieter-Entwürfe "
            f"für Kopf {head} / Wohnung {wohnung} bilden nicht exakt die "
            "aktuellen Mietvertragssegmente ab (fehlend, zusätzlich oder "
            "doppelt). Bitte den Kopf verwerfen und neu erzeugen.",
            frappe.ValidationError,
        )
    return [cstr(row.get("name")) for row in rows if row.get("name")]


def _insert_authorized_bk_child(doc) -> None:
    """Insert a header-authorized child, then restore normal permissions."""
    try:
        # The child DocType deliberately has no public create permission.  The
        # caller must have passed _require_bk_generation_authorization first.
        doc.insert(ignore_permissions=True)
    finally:
        # ``insert(ignore_permissions=True)`` persists this flag on the
        # Document.  Never let it leak into submit or later operations.
        doc.flags.ignore_permissions = False


def _create_bk_abrechnung_wohnung(
    von: str,
    bis: str,
    wohnung: str,
    submit: bool = False,
    stichtag: Optional[str] = None,
    head: Optional[str] = None,
    split_by_mietvertrag: bool = False,
    allocation: Optional[Dict[str, Any]] = None,
) -> str | List[str]:
    """Erstellt eine Wohnungsabrechnung mit optional vorab berechneter Verteilung."""
    submit = bool(cint(submit))
    split_by_mietvertrag = bool(cint(split_by_mietvertrag))
    if submit:
        frappe.throw(
            "Direktes Einreichen über den BK-Generator ist nicht erlaubt. "
            "Bitte die Betriebskostenabrechnung Immobilie einreichen.",
            frappe.ValidationError,
        )
    stichtag = stichtag or bis

    head_doc = _require_bk_generation_authorization(
        head=head,
        von=von,
        bis=bis,
        stichtag=stichtag,
        wohnung=wohnung,
        submit=submit,
    )
    generation_segments = _mietvertrag_segmente_fuer_zeitraum(
        wohnung,
        von,
        bis,
        lock_regelungen=True,
    )
    # Auch Pauschal-/Inklusivzeiträume erhalten eine reine
    # Informationsabrechnung. Nur die spätere finanzielle Abwicklung hängt von
    # ``abrechnungsart`` ab.
    expected_segments = generation_segments
    if not split_by_mietvertrag:
        period_start = getdate(von)
        period_end = getdate(bis)
        if (
            len(generation_segments) != 1
            or expected_segments[0]["start"] != period_start
            or expected_segments[0]["end"] != period_end
        ):
            frappe.throw(
                "Eine wohnungsweite BK-Abrechnung ohne Aufteilung ist nur "
                "zulässig, wenn genau ein Mietvertrag den gesamten Zeitraum "
                "abdeckt. Bitte nach Mietvertrag aufteilen."
            )
    existing = _existing_bk_children_for_head_wohnung(
        head_doc.name,
        wohnung,
        expected_segments,
    )
    if existing:
        return existing if split_by_mietvertrag or len(existing) != 1 else existing[0]
    # Verteilte Kosten (nur für diese Wohnung herausziehen)
    immobilie = head_doc.immobilie
    abrechnung_company = _get_default_company(frappe._dict(wohnung=wohnung))
    alloc = allocation
    if alloc is None:
        alloc = allocate_kosten_auf_wohnungen(
            von=von,
            bis=bis,
            immobilie=immobilie,
            stichtag=stichtag,
        )
    matrix: Dict[str, Dict[str, Any]] = alloc.get("matrix") or {}
    posten_raw = matrix.get(wohnung) or {}
    posten = {art: _to_decimal(amount) for art, amount in posten_raw.items()}
    if not posten:
        frappe.throw(
            f"Keine verteilten Kosten für Wohnung '{wohnung}' im Zeitraum {von} bis {bis} (Stichtag {stichtag}). Prüfe Kostenverteilung/Verteilerschlüssel."
        )

    if not split_by_mietvertrag:
        unsplit_segments = generation_segments
        mv = unsplit_segments[0]["mietvertrag"]
        customer = _get_customer_for_mietvertrag(mv)
        abrechnungsart = normalize_bk_regelung(
            unsplit_segments[0].get("abrechnungsart")
        )
        paid_total = Decimal("0")
        if ist_bk_abrechenbar(abrechnungsart):
            # Für die Abrechnung zählen BK-Rechnungen der Periode,
            # aber nur soweit deren BK-Anteil tatsächlich bezahlt wurde.
            prep = get_bk_prepayment_summary(
                wohnung=wohnung,
                from_date=von,
                to_date=bis,
                customer=customer,
                mietvertrag=mv,
                company=abrechnung_company,
            )
            paid_total = _to_decimal(prep.get("paid_total"))

        # Mietvertrag & Mieter
        # Mieter aus allen überlappenden Verträgen im Zeitraum sammeln
        mieter_rows = _vertragspartner_rows_for_period(wohnung, von, bis)

        # Zustand
        zustand = _zustand_am(wohnung, stichtag)
        groesse = _groesse_qm(wohnung, stichtag)

        d = frappe.new_doc("Betriebskostenabrechnung Mieter")
        d.update({
            "datum": cstr(stichtag),
            "von": cstr(von),
            "bis": cstr(bis),
            "wohnung": wohnung,
            "mietvertrag": mv,
            "customer": customer,
            "abrechnungsart": abrechnungsart,
            "vorrauszahlungen": _as_money(paid_total),
            "wohnungszustand": zustand,
            "größe": groesse,
        })
        if head:
            d.immobilien_abrechnung = head

        for r in mieter_rows:
            d.append("mieter", {
                "mieter": r.get("mieter"),
                "rolle": r.get("rolle"),
                "eingezogen": r.get("eingezogen"),
                "ausgezogen": r.get("ausgezogen"),
            })

        _add_abrechnungsposten(d, posten)

        # Beim Insert die automatische after_insert vermeiden und Settlement hier explizit ausführen,
        # damit Fehler direkt an den Aufrufer gehen.
        d.flags.skip_auto_settle = True
        d.flags.allow_manual_create = True
        try:
            _insert_authorized_bk_child(d)
        except Exception as e:
            frappe.throw(f"Abrechnung konnte nicht angelegt werden: {e}")
        return d.name

    segments = generation_segments
    if not segments:
        frappe.throw(
            f"Keine Mieter-Abrechnung erzeugt: Im Zeitraum {von} bis {bis} "
            f"existiert kein Mietvertrag für Wohnung '{wohnung}'."
        )

    seg_posten = _build_bk_segment_costs(
        alloc=alloc,
        immobilie=immobilie,
        wohnung=wohnung,
        von=von,
        bis=bis,
        posten=posten,
        segments=segments,
    )

    created: List[str] = []
    for idx, seg in enumerate(segments):
        seg_start = seg["start"].strftime("%Y-%m-%d")
        seg_end = seg["end"].strftime("%Y-%m-%d")
        seg_stichtag = stichtag
        if seg_stichtag:
            seg_stichtag = min(getdate(seg_stichtag), getdate(seg_end)).strftime("%Y-%m-%d")
        else:
            seg_stichtag = seg_end

        mv = seg.get("mietvertrag")
        customer = _get_customer_for_mietvertrag(mv)
        abrechnungsart = normalize_bk_regelung(seg.get("abrechnungsart"))
        paid_total = Decimal("0")
        if ist_bk_abrechenbar(abrechnungsart):
            # Regelungssegmente dürfen nur ihre eigenen BK-Rechnungsmonate
            # verrechnen. Bei einem untermonatigen Vertragsbeginn liegt die
            # monatliche Wertstellung technisch am Monatsersten; nur dort
            # erweitern wir den Start auf diesen Monatsersten.
            raw_contract = seg.get("raw") or {}
            prep_from, prep_to = bk_invoice_period_for_segment(
                seg_start,
                seg_end,
                raw_contract.get("von"),
            )
            prep = get_bk_prepayment_summary(
                wohnung=wohnung,
                from_date=prep_from,
                to_date=prep_to,
                customer=customer,
                mietvertrag=mv,
                company=abrechnung_company,
            )
            paid_total = _to_decimal(prep.get("paid_total"))

        mieter_rows = _vertragspartner_rows(mv, seg_start, seg_end) if mv else []

        zustand = _zustand_am(wohnung, seg_stichtag)
        groesse = _groesse_qm(wohnung, seg_stichtag)

        d = frappe.new_doc("Betriebskostenabrechnung Mieter")
        d.update({
            "datum": cstr(seg_stichtag),
            "von": cstr(seg_start),
            "bis": cstr(seg_end),
            "wohnung": wohnung,
            "mietvertrag": mv,
            "customer": customer,
            "abrechnungsart": abrechnungsart,
            "vorrauszahlungen": _as_money(paid_total),
            "wohnungszustand": zustand,
            "größe": groesse,
        })
        if head:
            d.immobilien_abrechnung = head

        for r in mieter_rows:
            d.append("mieter", {
                "mieter": r.get("mieter"),
                "rolle": r.get("rolle"),
                "eingezogen": r.get("eingezogen"),
                "ausgezogen": r.get("ausgezogen"),
            })

        seg_amounts = seg_posten[idx]
        _add_abrechnungsposten(d, seg_amounts)

        d.flags.skip_auto_settle = True
        d.flags.allow_manual_create = True
        try:
            _insert_authorized_bk_child(d)
        except Exception as e:
            frappe.throw(f"Abrechnung konnte nicht angelegt werden: {e}")
        created.append(d.name)

    return created


@frappe.whitelist()
def create_bk_abrechnung_wohnung(
    von: str,
    bis: str,
    wohnung: str,
    submit: bool = False,
    stichtag: Optional[str] = None,
    head: Optional[str] = None,
    split_by_mietvertrag: bool = False,
) -> str | List[str]:
    """Erstellt eine Betriebskostenabrechnung (Mieter) für eine Wohnung."""
    return _create_bk_abrechnung_wohnung(
        von=von,
        bis=bis,
        wohnung=wohnung,
        submit=submit,
        stichtag=stichtag,
        head=head,
        split_by_mietvertrag=split_by_mietvertrag,
    )


@frappe.whitelist()
def create_bk_abrechnungen_immobilie(
    von: str,
    bis: str,
    immobilie: str,
    submit: bool = False,
    stichtag: Optional[str] = None,
    head: Optional[str] = None,
    split_by_mietvertrag: bool = False,
) -> dict:
    """Erstellt alle Mieter‑Abrechnungen für ein Haus und optional den Kopfdatensatz."""
    submit = bool(cint(submit))
    split_by_mietvertrag = bool(cint(split_by_mietvertrag))
    if submit:
        frappe.throw(
            "Direktes Einreichen über den BK-Generator ist nicht erlaubt. "
            "Bitte die Betriebskostenabrechnung Immobilie einreichen.",
            frappe.ValidationError,
        )
    stichtag = stichtag or bis
    _require_bk_generation_authorization(
        head=head,
        von=von,
        bis=bis,
        stichtag=stichtag,
        immobilie=immobilie,
        submit=submit,
    )
    alloc = allocate_kosten_auf_wohnungen(von=von, bis=bis, immobilie=immobilie, stichtag=stichtag)
    matrix: Dict[str, Dict[str, float]] = alloc.get("matrix") or {}
    if not matrix:
        frappe.throw(
            f"Keine verteilten Kosten/ Wohnungen gefunden für Immobilie '{immobilie}' im Zeitraum {von} bis {bis} (Stichtag {stichtag}). Prüfe Kostenbuchungen, Verteilerschlüssel und Zuordnung der Wohnungen zur Immobilie."
        )

    created: List[str] = []
    head_name = head
    for whg in sorted(matrix.keys()):
        res = _create_bk_abrechnung_wohnung(
            von=von,
            bis=bis,
            wohnung=whg,
            submit=False,
            stichtag=stichtag,
            head=head_name,
            split_by_mietvertrag=split_by_mietvertrag,
            allocation=alloc,
        )
        if isinstance(res, list):
            created.extend(res)
        else:
            created.append(res)

    # Ein reines Pauschal-/Inklusivmietobjekt besitzt bewusst keine
    # Mieter-Abrechnungen. Der Immobilienkopf bleibt trotzdem gültig und weist
    # die vollständigen Kosten als Vermieteranteil aus.
    return {"created": created, "count": len(created)}


# -----------------------------
# Abschluss: Nachzahlung / Guthaben
# -----------------------------

def _ensure_item(code: str, name: Optional[str] = None) -> str:
    """Legacy helper kept permission-safe for any future caller."""
    name = name or code
    if frappe.db.exists("Item", code):
        return code
    item = frappe.new_doc("Item")
    item.item_code = code
    item.item_name = name
    item.item_group = "All Item Groups"
    item.is_sales_item = 1
    item.maintain_stock = 0
    item.stock_uom = "Nos"
    item.insert()
    return code


def _get_customer_for_mietvertrag(mv: Optional[str]) -> Optional[str]:
    if not mv:
        return None
    try:
        return frappe.get_cached_value("Mietvertrag", mv, "kunde")
    except Exception:
        return None


def _bk_invoice_outstanding_shares(
    wohnung: str,
    from_date: str,
    to_date: str,
    customer: Optional[str] = None,
    mietvertrag: Optional[str] = None,
    company: Optional[str] = None,
    contract_identity: Optional[Dict[str, Any]] = None,
    *,
    lock: bool = False,
) -> List[dict]:
    """Ermittelt pro BK-Rechnung den offenen Anteil des aktuellen Mieters.

    Eine Wohnung kann im Abrechnungszeitraum mehrere Mieter haben. Deshalb darf
    die spätere Verrechnung niemals nur über Wohnung + Zeitraum laufen, sondern
    muss zusätzlich auf den Customer des konkreten Mietvertrags begrenzt sein.
    """
    from .operating_cost_prepaiment_calc import _bk_invoice_names_for_wohnung

    names = _bk_invoice_names_for_wohnung(
        wohnung,
        from_date,
        to_date,
        customer=customer,
        mietvertrag=mietvertrag,
        company=company,
        contract_identity=contract_identity,
        lock=lock,
    )
    if not names:
        return []
    sql = """
        SELECT si.name,
               si.is_return,
               si.company,
               si.currency,
               si.conversion_rate,
               si.debit_to,
               CASE
                   WHEN si.is_return = 1 THEN -ABS(si.outstanding_amount)
                   ELSE si.outstanding_amount
               END AS outstanding_amount,
               COALESCE(bki.bk_net, 0) AS bk_net,
               COALESCE(tot.total_net, 0) AS total_net,
               COALESCE(
                   CASE
                       WHEN si.is_return = 1 THEN -ABS(si.outstanding_amount)
                       ELSE si.outstanding_amount
                   END
                   * COALESCE(ABS(bki.bk_net) / NULLIF(ABS(tot.total_net), 0), 0),
                   0
               ) AS outstanding_bk_share
        FROM `tabSales Invoice` si
        LEFT JOIN (
            SELECT parent, SUM(net_amount) AS bk_net
            FROM `tabSales Invoice Item`
            WHERE item_code = %(bk)s
            GROUP BY parent
        ) bki ON bki.parent = si.name
        LEFT JOIN (
            SELECT parent, SUM(net_amount) AS total_net
            FROM `tabSales Invoice Item`
            GROUP BY parent
        ) tot ON tot.parent = si.name
        WHERE si.name in %(names)s AND si.docstatus = 1
    """
    if lock:
        sql += "\nFOR UPDATE"
    rows = frappe.db.sql(sql, {"names": tuple(names), "bk": BK_ITEM_CODE}, as_dict=True)
    for r in rows:
        r["outstanding_bk_share"] = _as_money(_to_decimal(r.get("outstanding_bk_share")))
    return rows


def _make_sales_invoice(
    customer: str,
    posting_date: str,
    item_code: str,
    amount: Decimal,
    is_return: int = 0,
    do_submit: bool = True,
    company: Optional[str] = None,
    due_date: Optional[str] = None,
    wertstellungsdatum: Optional[str] = None,
    cost_center: Optional[str] = None,
    wohnung: Optional[str] = None,
    remarks: Optional[str] = None,
) -> str:
    post_date = getdate(posting_date)
    si = frappe.new_doc("Sales Invoice")
    si.customer = customer
    if company:
        company_currency = cstr(
            frappe.db.get_value("Company", company, "default_currency") or ""
        ).strip()
        if not company_currency:
            frappe.throw(
                f"Company {company} hat keine Standardwährung; "
                "Ausgleichsbeleg wurde nicht erstellt.",
                frappe.ValidationError,
            )
        si.company = company
        # Settlement amounts are calculated in the canonical company currency.
        # Never allow Customer defaults to reinterpret that amount as FX.
        si.currency = company_currency
        si.conversion_rate = 1
        si.plc_conversion_rate = 1
    # Fälligkeit: 3 Wochen nach Buchung; Payment Terms Templates bewusst ignorieren.
    # set_posting_time=1 verhindert, dass ERPNext posting_date auf "heute" zurücksetzt
    # (siehe transaction_base.py) — sonst wäre due_date inkonsistent mit posting_date.
    si.posting_date = post_date
    si.set_posting_time = 1
    if wertstellungsdatum and _has_field("Sales Invoice", "custom_wertstellungsdatum"):
        si.custom_wertstellungsdatum = getdate(wertstellungsdatum)
    if is_return:
        # Guthaben/Credit Notes sind sofort fällig — keine 21-Tage-Frist sinnvoll.
        si.due_date = post_date
    elif due_date:
        si.due_date = getdate(due_date)
    else:
        si.due_date = post_date + timedelta(days=21)
    si.ignore_default_payment_terms_template = 1
    si.ignore_pricing_rule = 1
    si.set("payment_terms_template", None)
    si.set("payment_schedule", [])
    si.set("taxes_and_charges", None)
    si.set("taxes", [])
    si.set("is_return", is_return)
    if remarks:
        si.remarks = remarks
    # Für Return-Beleg werden Mengen/Rate negativ erwartet
    qty = 1
    amount_dec = _quantize_money(_to_decimal(amount))
    rate = _as_money(amount_dec)
    if is_return:
        # ERPNext returns expect negative qty with positive rate (unless negative rates are allowed)
        qty = -1
        rate = abs(rate)
    if cost_center and _has_field("Sales Invoice", "cost_center"):
        si.cost_center = cost_center
    if wohnung and _has_field("Sales Invoice", "wohnung"):
        si.set("wohnung", wohnung)

    item_row = {"item_code": item_code, "qty": qty, "rate": rate}
    if cost_center:
        item_row["cost_center"] = cost_center
    if wohnung and _has_field("Sales Invoice Item", "wohnung"):
        item_row["wohnung"] = wohnung
    si.append("items", item_row)
    # Do not bypass the target user's create permission.  The explicit
    # permission pre-check is only an early, readable error; Document.insert
    # remains the authoritative enforcement point (including User Permissions).
    si.insert()
    if company:
        _validate_target_sales_invoice_booking_context(
            si,
            company,
            expected_item_code=item_code,
            expected_amount=amount_dec,
            expected_return=bool(is_return),
        )
    if do_submit:
        si.submit()
    return si.name


def _validate_target_sales_invoice_booking_context(
    si,
    company: str,
    *,
    expected_item_code: str,
    expected_amount: Decimal,
    expected_return: bool,
) -> None:
    """Validate the inserted settlement target before it can be submitted."""
    company_currency = cstr(
        frappe.db.get_value("Company", company, "default_currency") or ""
    ).strip()
    account_name = cstr(getattr(si, "debit_to", None) or "").strip()
    account_rows = (
        frappe.db.sql(
            """
            SELECT name, company, account_type, account_currency
            FROM `tabAccount`
            WHERE name = %s
            FOR UPDATE
            """,
            (account_name,),
            as_dict=True,
        )
        if account_name
        else []
    )
    account = account_rows[0] if len(account_rows) == 1 else {}
    try:
        conversion_rate = Decimal(str(getattr(si, "conversion_rate", 0) or 0))
        plc_conversion_rate = Decimal(
            str(getattr(si, "plc_conversion_rate", 0) or 0)
        )
    except (InvalidOperation, TypeError, ValueError):
        conversion_rate = Decimal("0")
        plc_conversion_rate = Decimal("0")
    expected_signed = _quantize_money(
        -expected_amount.copy_abs()
        if expected_return
        else expected_amount.copy_abs()
    )
    items = list(getattr(si, "items", None) or [])
    taxes = list(getattr(si, "taxes", None) or [])
    try:
        grand_total = _quantize_money(
            Decimal(str(getattr(si, "grand_total", 0) or 0))
        )
        base_grand_total = _quantize_money(
            Decimal(str(getattr(si, "base_grand_total", 0) or 0))
        )
        item_net = (
            _quantize_money(
                Decimal(str(getattr(items[0], "net_amount", 0) or 0))
            )
            if len(items) == 1
            else Decimal("0")
        )
        tax_total = _quantize_money(
            Decimal(
                str(getattr(si, "total_taxes_and_charges", 0) or 0)
            )
        )
    except (InvalidOperation, TypeError, ValueError):
        grand_total = base_grand_total = item_net = tax_total = Decimal("0")
    exact_item = (
        len(items) == 1
        and cstr(getattr(items[0], "item_code", None) or "").strip()
        == expected_item_code
    )
    if (
        not company_currency
        or cstr(getattr(si, "company", None) or "").strip() != company
        or cstr(getattr(si, "currency", None) or "").strip()
        != company_currency
        or conversion_rate != Decimal("1")
        or plc_conversion_rate != Decimal("1")
        or cstr(account.get("company") or "").strip() != company
        or cstr(account.get("account_type") or "").strip() != "Receivable"
        or cstr(account.get("account_currency") or "").strip()
        != company_currency
        or cint(getattr(si, "is_return", 0)) != int(expected_return)
        or not exact_item
        or grand_total != expected_signed
        or base_grand_total != expected_signed
        or item_net != expected_signed
        or tax_total != Decimal("0.00")
        or bool(taxes)
    ):
        frappe.throw(
            "Ausgleichsbeleg wurde nicht eingereicht: Company, Währung, "
            "Umrechnungskurs, Debitorenkonto, Betrag, Item oder Steuern "
            f"sind nicht exakt kanonisch für {company}.",
            frappe.ValidationError,
        )


def _get_si_debit_to(name: str) -> Optional[str]:
    try:
        return frappe.get_cached_value("Sales Invoice", name, "debit_to")
    except Exception:
        return None


def _receivable_account_for_existing_invoices(rows: List[dict], fallback_company: Optional[str]) -> Optional[str]:
    for r in rows or []:
        old_name = r.get("name")
        if not old_name:
            continue
        account = _get_si_debit_to(old_name)
        if account:
            return account
    try:
        filters = {"account_type": "Receivable", "is_group": 0}
        if fallback_company:
            filters["company"] = fallback_company
        accounts = frappe.get_all("Account", filters=filters, pluck="name", limit=1)
        return accounts[0] if accounts else None
    except Exception:
        return None


def _allocate_via_journal_entry(
    company: str,
    entries: List[dict],
    posting_date: str,
    wertstellungsdatum: Optional[str] = None,
    *,
    remarks: Optional[str] = None,
) -> Optional[str]:
    """Erstellt und bucht einen Journal Entry mit parteibezogenen Referenzen.

    entries: Liste von Dicts mit Feldern:
      { account, party_type, party, reference_type, reference_name, debit, credit }
    """
    if not entries:
        return None
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = company
    je.posting_date = posting_date
    if remarks:
        je.user_remark = remarks
    if wertstellungsdatum:
        je.custom_wertstellungsdatum = wertstellungsdatum
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for e in entries:
        row = je.append("accounts", {})
        row.account = e.get("account")
        row.party_type = e.get("party_type")
        row.party = e.get("party")
        if e.get("reference_type"):
            row.reference_type = e.get("reference_type")
        if e.get("reference_name"):
            row.reference_name = e.get("reference_name")
        debit = _to_decimal(e.get("debit"))
        credit = _to_decimal(e.get("credit"))
        row.debit_in_account_currency = _as_money(debit)
        row.credit_in_account_currency = _as_money(credit)
        total_debit += debit
        total_credit += credit
    # Safety: müssen ausgeglichen sein
    if _quantize_money(total_debit - total_credit) != Decimal("0.00"):
        debit_val = _as_money(total_debit)
        credit_val = _as_money(total_credit)
        frappe.throw(
            f"Journal Entry nicht ausgeglichen (Debit {debit_val:.2f} != Credit {credit_val:.2f})."
        )
    # Keep Frappe's document and User-Permission enforcement active.
    je.insert()
    je.submit()
    return je.name


def _get_locked_settlement_document(abrechnung: str):
    """Sperrt die Mieterabrechnung bis zum Transaktionsende und lädt sie danach neu.

    Dadurch kann ein zweiter, paralleler Request die Idempotenzprüfung erst
    ausführen, nachdem der erste Request seine Beleg-Links gespeichert hat.
    """
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabBetriebskostenabrechnung Mieter`
        WHERE name = %s
        FOR UPDATE
        """,
        (abrechnung,),
    )
    if not rows:
        frappe.throw(f"Betriebskostenabrechnung Mieter {abrechnung} wurde nicht gefunden.")
    doc = frappe.get_doc(
        "Betriebskostenabrechnung Mieter",
        abrechnung,
        for_update=True,
    )
    mietvertrag = cstr(doc.get("mietvertrag") or "").strip()
    if not mietvertrag:
        frappe.throw(
            "Die Mieter-Abrechnung hat keinen Mietvertrag; Settlement "
            "abgebrochen."
        )
    contract_rows = frappe.db.sql(
        """
        SELECT name, kunde, wohnung, von, bis
        FROM `tabMietvertrag`
        WHERE name = %s
        FOR UPDATE
        """,
        (mietvertrag,),
        as_dict=True,
    )
    if not contract_rows:
        frappe.throw(
            f"Mietvertrag {mietvertrag} wurde nicht gefunden; "
            "Settlement abgebrochen."
        )
    identity = frappe._dict(contract_rows[0])
    locked_customer = cstr(identity.get("kunde") or "").strip()
    locked_wohnung = cstr(identity.get("wohnung") or "").strip()
    if not locked_customer or not locked_wohnung:
        frappe.throw(
            f"Mietvertrag {mietvertrag} hat keinen eindeutigen Customer oder "
            "keine Wohnung; Settlement abgebrochen."
        )
    document_customer = cstr(doc.get("customer") or "").strip()
    document_wohnung = cstr(doc.get("wohnung") or "").strip()
    if document_customer != locked_customer or document_wohnung != locked_wohnung:
        frappe.throw(
            "Die gespeicherte Customer-/Wohnungsidentität der "
            f"Mieter-Abrechnung widerspricht dem aktuell gesperrten Mietvertrag "
            f"{mietvertrag}; Settlement abgebrochen."
        )
    # Ausschließlich dieser Current Read darf die nachfolgende Belegauswahl,
    # Company-Auflösung und Zielbeleg-Erstellung steuern.
    doc._locked_mietvertrag_identity = frappe._dict(
        name=mietvertrag,
        kunde=locked_customer,
        wohnung=locked_wohnung,
        von=identity.get("von"),
        bis=identity.get("bis"),
    )
    return doc


def _get_locked_submitted_bk_head(abrechnung: str):
    """Discover, lock and validate the mandatory submitted settlement header.

    The initial child-link read is only used to discover the lock target.  The
    relation is checked again after locking header and child so a concurrent
    relink cannot authorize a booking.
    """
    head_name = cstr(
        frappe.db.get_value(
            "Betriebskostenabrechnung Mieter",
            abrechnung,
            "immobilien_abrechnung",
        )
        or ""
    ).strip()
    if not head_name:
        frappe.throw(
            "Buchung abgebrochen: Die Mieter-Abrechnung ist mit keiner "
            "Betriebskostenabrechnung Immobilie verknüpft.",
            frappe.ValidationError,
        )
    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabBetriebskostenabrechnung Immobilie`
        WHERE name = %s
        FOR UPDATE
        """,
        (head_name,),
    )
    if not rows:
        frappe.throw(
            f"Buchung abgebrochen: Der verknüpfte BK-Kopf {head_name} fehlt.",
            frappe.ValidationError,
        )
    head_doc = frappe.get_doc(
        "Betriebskostenabrechnung Immobilie",
        head_name,
        for_update=True,
    )
    if cint(getattr(head_doc, "docstatus", 0)) != 1:
        frappe.throw(
            f"Buchung abgebrochen: Der verknüpfte BK-Kopf {head_name} ist "
            "nicht eingereicht.",
            frappe.ValidationError,
        )
    return head_doc


def _authoritative_bk_consolidation_choice(
    head_doc,
    requested: Any = None,
) -> bool:
    """Return the immutable server-side choice and reject API overrides."""
    authoritative = bool(
        cint(getattr(head_doc, "offene_bk_vorauszahlungen_verrechnen", 0))
    )
    if requested not in (None, ""):
        normalized_request = bool(cint(requested))
        if normalized_request != authoritative:
            frappe.throw(
                "Der API-Parameter 'consolidate_unpaid' widerspricht dem "
                "eingereichten BK-Kopf. Ausschließlich die Checkbox des "
                "Kopfes ist maßgeblich.",
                frappe.ValidationError,
            )
    return authoritative


def _require_bk_settlement_head_permissions(head_doc) -> None:
    for permission_type in ("read", "write"):
        if not frappe.has_permission(
            "Betriebskostenabrechnung Immobilie",
            ptype=permission_type,
            doc=head_doc,
        ):
            frappe.throw(
                "Keine Berechtigung für den maßgeblichen BK-Kopf: "
                f"{permission_type}.",
                frappe.PermissionError,
            )


def _validate_bk_settlement_head_identity(doc, head_doc) -> None:
    if cstr(getattr(doc, "immobilien_abrechnung", None) or "").strip() != cstr(
        getattr(head_doc, "name", None) or ""
    ).strip():
        frappe.throw(
            "Buchung abgebrochen: Die gesperrte Mieter-Abrechnung verweist "
            "nicht mehr auf den gesperrten BK-Kopf.",
            frappe.ValidationError,
        )

    head_immobilie = cstr(getattr(head_doc, "immobilie", None) or "").strip()
    locked_identity = getattr(doc, "_locked_mietvertrag_identity", None) or {}
    wohnung = cstr(
        locked_identity.get("wohnung")
        or getattr(doc, "wohnung", None)
        or ""
    ).strip()
    if (
        not head_immobilie
        or not _wohnung_belongs_to_immobilie_hierarchy(
            wohnung,
            head_immobilie,
        )
    ):
        frappe.throw(
            "Buchung abgebrochen: Wohnung und Immobilie des BK-Kopfes sind "
            "nicht identisch.",
            frappe.ValidationError,
        )

    head_from = getdate(getattr(head_doc, "von", None))
    head_to = getdate(getattr(head_doc, "bis", None))
    child_from = getdate(getattr(doc, "von", None))
    child_to = getdate(getattr(doc, "bis", None))
    expected_cutoff = min(
        getdate(getattr(head_doc, "stichtag", None) or head_to),
        child_to,
    )
    if (
        child_from < head_from
        or child_to > head_to
        or child_from > child_to
        or getdate(getattr(doc, "datum", None)) != expected_cutoff
    ):
        frappe.throw(
            "Buchung abgebrochen: Zeitraum oder Stichtag der "
            "Mieter-Abrechnung passt nicht zum eingereichten BK-Kopf.",
            frappe.ValidationError,
        )


def _validate_bk_prepayment_booking_context(
    invoice_rows: List[dict],
    company: str,
) -> None:
    """Fail closed before ``O`` is calculated from foreign/misconfigured SIs."""
    if not invoice_rows:
        return
    company_currency = cstr(
        frappe.db.get_value("Company", company, "default_currency") or ""
    ).strip()
    if not company_currency:
        frappe.throw(
            f"Company {company} hat keine Standardwährung; Buchung abgebrochen.",
            frappe.ValidationError,
        )

    accounts = sorted(
        {
            cstr(row.get("debit_to") or "").strip()
            for row in invoice_rows
            if cstr(row.get("debit_to") or "").strip()
        }
    )
    account_rows = (
        frappe.get_all(
            "Account",
            filters={"name": ("in", accounts)},
            fields=["name", "company", "account_type", "account_currency"],
            limit_page_length=0,
        )
        if accounts
        else []
    )
    account_by_name = {
        cstr(row.get("name")): row
        for row in account_rows or []
        if row.get("name")
    }

    invalid: List[str] = []
    for row in invoice_rows:
        name = cstr(row.get("name") or "unbekannt")
        account_name = cstr(row.get("debit_to") or "").strip()
        account = account_by_name.get(account_name) or {}
        try:
            conversion_rate = Decimal(
                str(row.get("conversion_rate") or 0)
            )
        except (InvalidOperation, TypeError, ValueError):
            conversion_rate = Decimal("0")
        if (
            cstr(row.get("company") or "").strip() != company
            or cstr(row.get("currency") or "").strip() != company_currency
            or conversion_rate != Decimal("1")
            or not account_name
            or cstr(account.get("company") or "").strip() != company
            or cstr(account.get("account_type") or "").strip() != "Receivable"
            or cstr(account.get("account_currency") or "").strip()
            != company_currency
        ):
            invalid.append(name)
    if invalid:
        frappe.throw(
            "Buchung abgebrochen: BK-Vorauszahlungsbelege haben eine fremde "
            "Company, Währung oder kein passendes Debitorenkonto "
            f"({', '.join(invalid[:10])}). Sie wurden nicht in O eingerechnet.",
            frappe.ValidationError,
        )


def _validate_locked_prepayment_snapshot(doc, invoice_rows: List[dict]) -> None:
    """Prüft Soll, Zahlung und OP unter denselben Belegsperren.

    Der Entwurf speichert die bis dahin bezahlten Vorauszahlungen. Vor der
    endgültigen Buchung müssen sie noch exakt dem aktuellen Zahlungsstand
    entsprechen. Außerdem gilt für unveränderte Vorauszahlungsrechnungen:
    Soll = bezahlt + offen. Abweichungen (z. B. Write-off oder uneindeutige
    Legacy-Daten) werden fail-closed behandelt.
    """
    names = [row.get("name") for row in invoice_rows or [] if row.get("name")]
    live_paid = _quantize_money(
        _to_decimal(
            get_bk_paid_sum_for_invoice_names(
                names,
                item_code=BK_ITEM_CODE,
                lock=True,
            )
        )
    )
    expected = _quantize_money(
        _to_decimal(
            get_bk_expected_sum_for_invoice_names(
                names,
                item_code=BK_ITEM_CODE,
                lock=True,
            )
        )
    )
    outstanding = Decimal("0")
    for row in invoice_rows or []:
        amount = _quantize_money(_to_decimal(row.get("outstanding_bk_share")))
        if amount.copy_abs() >= MONEY_QUANT:
            outstanding += amount
    outstanding = _quantize_money(outstanding)
    stored_paid = _quantize_money(_to_decimal(getattr(doc, "vorrauszahlungen", 0)))

    if live_paid != stored_paid:
        frappe.throw(
            "Der Zahlungsstand der BK-Vorauszahlungen hat sich seit Erstellung "
            f"der Abrechnung geändert (Entwurf {stored_paid:.2f}, aktuell "
            f"{live_paid:.2f}). Bitte Abrechnung neu erzeugen; es wurde nichts "
            "gebucht."
        )
    if expected != _quantize_money(live_paid + outstanding):
        frappe.throw(
            "BK-Vorauszahlungen sind nicht eindeutig auflösbar: "
            f"Signed Soll {expected:.2f} != signed bezahlt {live_paid:.2f} "
            f"+ signed offen "
            f"{outstanding:.2f}. Bitte Write-offs, Gutschriften und "
            "Legacy-Zuordnungen prüfen; es wurde nichts gebucht."
        )


def _require_settlement_permissions(
    doc,
    source_doctype: str,
    *,
    require_journal_entry: bool = False,
) -> None:
    """Blockiert Draft-/API-Buchungen ohne explizite Quell- und Zielrechte."""
    if cint(getattr(doc, "docstatus", 0)) != 1:
        frappe.throw(
            f"{source_doctype} muss vor der Belegerzeugung eingereicht sein.",
            frappe.ValidationError,
        )

    checks = [
        (source_doctype, "read", {"doc": doc}),
        (source_doctype, "write", {"doc": doc}),
        ("Sales Invoice", "create", {}),
        ("Sales Invoice", "submit", {}),
    ]
    if require_journal_entry:
        checks.extend(
            [
                ("Journal Entry", "create", {}),
                ("Journal Entry", "submit", {}),
            ]
        )

    for doctype, permission_type, kwargs in checks:
        # Always pass the DocType explicitly.  Besides being compatible with
        # Frappe versions where it is positional/required, this prevents mocks
        # from hiding a production-only TypeError on document-level checks.
        allowed = frappe.has_permission(doctype, ptype=permission_type, **kwargs)
        if not allowed:
            frappe.throw(
                f"Keine Berechtigung für {doctype}: {permission_type}.",
                frappe.PermissionError,
            )


@frappe.whitelist()
def create_bk_settlement_documents(
    abrechnung: str,
    consolidate_unpaid: Optional[bool] = None,
) -> dict:
    """Erstellt Nachzahlung (SI) oder Guthaben (Credit Note) für eine Mieter-Abrechnung.

    Offene BK-Rechnungen des Zeitraums werden immer als Bericht ausgewiesen,
    aber nur bei ausdrücklichem Opt-in per Journal Entry verrechnet.
    """
    # Lock order is always header -> child -> contract -> source invoices.
    # The API parameter is compatibility-only and can never override the head.
    head_doc = _get_locked_submitted_bk_head(abrechnung)
    _require_bk_settlement_head_permissions(head_doc)
    consolidate_unpaid = _authoritative_bk_consolidation_choice(
        head_doc,
        consolidate_unpaid,
    )
    doc = _get_locked_settlement_document(abrechnung)
    _validate_bk_settlement_head_identity(doc, head_doc)
    if not ist_bk_abrechenbar(getattr(doc, "abrechnungsart", None)):
        frappe.throw(
            f"Für die Informationsabrechnung {doc.name} "
            f"({normalize_bk_regelung(getattr(doc, 'abrechnungsart', None))}) "
            "darf keine Nachzahlung oder Gutschrift erzeugt werden.",
            frappe.ValidationError,
        )
    _bk_settlement_marker(doc.name)
    _require_settlement_permissions(
        doc,
        "Betriebskostenabrechnung Mieter",
        require_journal_entry=consolidate_unpaid,
    )
    # Doppel-Trigger, Job-Retry und parallele Requests verhindern. Auch ein
    # alleiniger Konsolidierungs-JE ist ein bereits erzeugtes Settlement.
    existing_si = (doc.get("sales_invoice") or "").strip()
    existing_cn = (doc.get("credit_note") or "").strip()
    existing_je = (doc.get("consolidation_journal_entry") or "").strip()
    if existing_si or existing_cn or existing_je:
        validator = getattr(doc, "_validated_settlement_documents", None)
        if not callable(validator):
            frappe.throw(
                "Settlement-Retry abgebrochen: Vorhandene Beleglinks können "
                "nicht auf Ownership geprüft werden.",
                frappe.ValidationError,
            )
        validated_documents = validator()
        if any(cint(getattr(linked, "docstatus", 0)) != 1 for linked in validated_documents):
            frappe.throw(
                "Settlement-Retry abgebrochen: Mindestens ein verknüpfter "
                "Ausgleichsbeleg ist nicht mehr eingereicht.",
                frappe.ValidationError,
            )
        return {
            "created": {
                "sales_invoice": existing_si or None,
                "credit_note": existing_cn or None,
                "journal_entry": existing_je or None,
                "note": "Settlement bereits erzeugt. Felder erst leeren, um neu zu generieren.",
            },
            "unpaid_report": [],
            "unpaid_sum": 0.0,
            "consolidate_unpaid": consolidate_unpaid,
            "consolidated_sum": 0.0,
            "consolidated_gross_sum": 0.0,
            "consolidated_signed_sum": 0.0,
        }
    locked_contract_identity = (
        getattr(doc, "_locked_mietvertrag_identity", None)
        or frappe._dict(
            name=doc.mietvertrag,
            kunde=doc.customer,
            wohnung=doc.wohnung,
        )
    )
    mv = cstr(locked_contract_identity.get("name") or "").strip()
    customer = cstr(locked_contract_identity.get("kunde") or "").strip()
    wohnung = cstr(locked_contract_identity.get("wohnung") or "").strip()
    if not mv or not customer or not wohnung:
        frappe.throw(
            "Der gesperrte Mietvertrag hat keine eindeutige "
            "Customer-/Wohnungsidentität."
        )

    # Die Forderung bzw. das Guthaben entsteht mit Erstellung der Abrechnung und
    # wird deshalb heute gebucht. Das Ende des Abrechnungszeitraums dient nur als
    # Leistungs-/Wertstellungsdatum für die periodische Zuordnung.
    posting_date = cstr(frappe.utils.today())
    wertstellungsdatum = cstr(doc.bis or doc.datum or posting_date)
    due_date = None
    invoice_from, invoice_to = bk_invoice_period_for_segment(
        doc.von,
        doc.bis,
        locked_contract_identity.get("von"),
    )
    # Bei None faellt _make_sales_invoice auf Default (+21 Tage) zurueck.
    due_date = getattr(head_doc, "nachzahlung_faellig_am", None) or None
    # Kein Parse-Fehler darf aus einer kaputten Abrechnung einen vermeintlich
    # ausgeglichenen Nullbetrag machen.
    total = Decimal("0")
    for index, row in enumerate(getattr(doc, "abrechnung", []) or [], start=1):
        total += _booking_decimal(
            row.get("betrag"),
            field_label=f"Abrechnungsposten {index}",
        )
    vor = _booking_decimal(
        getattr(doc, "vorrauszahlungen", None),
        field_label="Vorauszahlungen",
    )
    try:
        diff = _quantize_money(total - vor)
    except InvalidOperation:
        frappe.throw(
            "Die Differenz aus Abrechnungsposten und Vorauszahlungen konnte "
            "nicht centgenau berechnet werden; Buchung abgebrochen.",
            frappe.ValidationError,
        )

    # Selfcheck: wirf Fehler, wenn Setup unvollständig
    company = _get_default_company(doc)
    _run_settlement_selfcheck(
        doc,
        contract_identity=locked_contract_identity,
        company=company,
    )
    cost_center = _cost_center_for_abrechnung_doc(doc)
    settlement_remark = _build_settlement_remark(
        doc.von,
        doc.bis,
        abrechnung=doc.name,
    )
    # Sicherstellen: Artikel existieren und haben Income Account Defaults
    code_nach = _ensure_item_with_income("BK Nachzahlung", "Betriebskosten Nachzahlung", company)
    code_guth = _ensure_item_with_income("BK Guthaben", "Betriebskosten Guthaben", company)

    created: Dict[str, Optional[str]] = {"sales_invoice": None, "credit_note": None, "journal_entry": None}
    new_doc_name = None
    base_amount = Decimal("0")
    # Absolute/signed amounts actually consolidated by the optional JE.
    applied = Decimal("0")
    applied_signed = Decimal("0")

    # Vorzeichenbehaftete offene BK-Anteile ermitteln. Positive Werte sind
    # Forderungen, negative Werte offene Gutschriften. Nur die positive
    # Teilmenge darf später per JE konsolidiert werden.
    report: List[Dict[str, Any]] = []
    total_out_bk = Decimal("0")
    positive_out_bk = Decimal("0")
    negative_out_bk = Decimal("0")
    rows = []
    if wohnung and invoice_from and invoice_to:
        rows = _bk_invoice_outstanding_shares(
            wohnung,
            invoice_from,
            invoice_to,
            customer=customer,
            mietvertrag=mv,
            company=company,
            contract_identity=locked_contract_identity,
            lock=True,
        )
        _validate_bk_prepayment_booking_context(rows, company)
        _validate_locked_prepayment_snapshot(doc, rows)
        for r in rows:
            amt = _quantize_money(_to_decimal(r.get("outstanding_bk_share")))
            if amt.copy_abs() >= MONEY_QUANT:
                report.append({"invoice": r.get("name"), "outstanding_bk_share": _as_money(amt)})
                total_out_bk += amt
                if amt > 0:
                    positive_out_bk += amt
                else:
                    negative_out_bk += amt.copy_abs()
    total_out_bk = _quantize_money(total_out_bk)
    positive_out_bk = _quantize_money(positive_out_bk)
    negative_out_bk = _quantize_money(negative_out_bk)

    # Eine einzige Algebra gilt für Nachzahlung, Guthaben und gemischte
    # Forderungs-/Gutschrift-OP:
    #
    #   neuer Ausgleich = (Kosten - signed bezahlt) - signed offen
    #
    # Dadurch neutralisiert eine offene Return-CN die zugehörige Alt-Forderung,
    # ohne selbst als Zahlung oder als JE-Ziel missverstanden zu werden.
    adjustment = _quantize_money(diff - total_out_bk)

    if adjustment >= MONEY_QUANT:
        base_amount = adjustment
        try:
            new_doc_name = _make_sales_invoice(
                customer,
                posting_date,
                code_nach,
                base_amount,
                is_return=0,
                do_submit=True,
                company=company,
                due_date=due_date,
                wertstellungsdatum=wertstellungsdatum,
                cost_center=cost_center,
                wohnung=wohnung,
                remarks=settlement_remark,
            )
        except Exception as e:
            frappe.throw(f"Nachzahlung konnte nicht erstellt werden: {e}")
        created["sales_invoice"] = new_doc_name
    elif adjustment <= -MONEY_QUANT:
        base_amount = adjustment.copy_abs()
        try:
            new_doc_name = _make_sales_invoice(
                customer,
                posting_date,
                code_guth,
                base_amount,
                is_return=1,
                do_submit=True,
                company=company,
                wertstellungsdatum=wertstellungsdatum,
                cost_center=cost_center,
                wohnung=wohnung,
                remarks=settlement_remark,
            )
        except Exception as e:
            frappe.throw(f"Guthaben konnte nicht erstellt werden: {e}")
        created["credit_note"] = new_doc_name
    else:
        if report:
            created["note"] = (
                "Abrechnung wird bereits exakt durch die signed offenen "
                "BK-Vorauszahlungsbelege abgebildet; kein Null-Euro-Beleg und "
                "keine Umbuchung erstellt."
            )
        else:
            created["note"] = "Abrechnung ist ausgeglichen."

    # Signed consolidation:
    # 1. positive/negative old OPs can cross-clear each other,
    # 2. only the signed residual is transferred to the marked target,
    # 3. an opposite-sign target is never crossed through zero,
    # 4. without a non-zero target reference no source-only JE is created.
    consolidated_by_invoice: Dict[str, Decimal] = {}
    positive_to_apply = Decimal("0")
    negative_to_apply = Decimal("0")
    if consolidate_unpaid and new_doc_name:
        cross_clear = min(positive_out_bk, negative_out_bk)
        positive_residual = _quantize_money(positive_out_bk - cross_clear)
        negative_residual = _quantize_money(negative_out_bk - cross_clear)
        positive_target_transfer = Decimal("0")
        negative_target_transfer = Decimal("0")
        if adjustment > 0:
            if positive_residual >= MONEY_QUANT:
                # Debit residual can safely increase a debit target.
                positive_target_transfer = positive_residual
            elif negative_residual >= MONEY_QUANT:
                # Credit residual may reduce, but never invert, the target SI.
                negative_target_transfer = min(negative_residual, base_amount)
        elif adjustment < 0:
            if positive_residual >= MONEY_QUANT:
                # Debit residual may reduce, but never invert, the target CN.
                positive_target_transfer = min(positive_residual, base_amount)
            # A credit reference against a Credit Note is rejected by
            # ERPNext's invoice-reference validation. Same-sign old and target
            # Credit Notes therefore deliberately remain separate.

        if (
            positive_target_transfer >= MONEY_QUANT
            or negative_target_transfer >= MONEY_QUANT
        ):
            positive_to_apply = _quantize_money(
                cross_clear + positive_target_transfer
            )
            negative_to_apply = _quantize_money(
                cross_clear + negative_target_transfer
            )
            applied_signed = _quantize_money(
                positive_to_apply - negative_to_apply
            )
            applied = _quantize_money(positive_to_apply + negative_to_apply)

    if applied >= MONEY_QUANT:
        # Konten bestimmen
        entries: List[dict] = []
        # company und receivable account vom neuen Beleg ziehen
        si_doc = frappe.get_doc("Sales Invoice", new_doc_name)
        company = si_doc.company
        new_acc = si_doc.debit_to
        new_party = si_doc.customer
        if applied_signed > 0:
            entries.append({
                "account": new_acc,
                "party_type": "Customer",
                "party": new_party,
                "reference_type": "Sales Invoice",
                "reference_name": new_doc_name,
                "debit": applied_signed,
                "credit": Decimal("0"),
            })
        elif applied_signed < 0:
            entries.append({
                "account": new_acc,
                "party_type": "Customer",
                "party": new_party,
                "reference_type": "Sales Invoice",
                "reference_name": new_doc_name,
                "debit": Decimal("0"),
                "credit": applied_signed.copy_abs(),
            })
        else:
            frappe.throw(
                "Konsolidierung abgebrochen: Ein source-only Journal Entry "
                "ohne eigene Ausgleichsbeleg-Referenz ist nicht erlaubt.",
                frappe.ValidationError,
            )

        positive_remaining = positive_to_apply
        negative_remaining = negative_to_apply
        for r in rows:
            amt = _quantize_money(_to_decimal(r.get("outstanding_bk_share")))
            if amt.copy_abs() < MONEY_QUANT:
                continue
            old_name = r.get("name")
            old_acc = _get_si_debit_to(old_name) or new_acc
            if amt > 0 and positive_remaining >= MONEY_QUANT:
                use = min(amt, positive_remaining)
                entries.append({
                    "account": old_acc,
                    "party_type": "Customer",
                    "party": new_party,
                    "reference_type": "Sales Invoice",
                    "reference_name": old_name,
                    "debit": Decimal("0"),
                    "credit": _quantize_money(use),
                })
                consolidated_by_invoice[cstr(old_name)] = _quantize_money(use)
                positive_remaining = _quantize_money(
                    positive_remaining - use
                )
            elif amt < 0 and negative_remaining >= MONEY_QUANT:
                use = min(amt.copy_abs(), negative_remaining)
                entries.append({
                    "account": old_acc,
                    "party_type": "Customer",
                    "party": new_party,
                    "reference_type": "Sales Invoice",
                    "reference_name": old_name,
                    "debit": _quantize_money(use),
                    "credit": Decimal("0"),
                })
                consolidated_by_invoice[cstr(old_name)] = -_quantize_money(use)
                negative_remaining = _quantize_money(
                    negative_remaining - use
                )
        if (
            positive_remaining.copy_abs() >= MONEY_QUANT
            or negative_remaining.copy_abs() >= MONEY_QUANT
        ):
            frappe.throw(
                "Konsolidierung abgebrochen: Die signed Quellbeträge konnten "
                "nicht exakt auf die gesperrten Belege verteilt werden.",
                frappe.ValidationError,
            )

        target_after = _quantize_money(adjustment + applied_signed)
        allocated_signed = _quantize_money(
            sum(consolidated_by_invoice.values(), Decimal("0"))
        )
        total_debit = _quantize_money(
            sum((_to_decimal(entry.get("debit")) for entry in entries), Decimal("0"))
        )
        total_credit = _quantize_money(
            sum((_to_decimal(entry.get("credit")) for entry in entries), Decimal("0"))
        )
        if allocated_signed != applied_signed or total_debit != total_credit:
            frappe.throw(
                "Konsolidierung abgebrochen: Quellzuordnung und Journal Entry "
                "sind nicht centgenau ausgeglichen.",
                frappe.ValidationError,
            )
        if (
            adjustment > 0 and target_after < 0
        ) or (adjustment < 0 and target_after > 0):
            frappe.throw(
                "Konsolidierung abgebrochen: Zielvorzeichen wäre verletzt.",
                frappe.ValidationError,
            )
        je_name = _allocate_via_journal_entry(
            company,
            entries,
            posting_date,
            wertstellungsdatum,
            remarks=_bk_settlement_marker(doc.name),
        )
        if not je_name:
            frappe.throw(
                "Konsolidierung abgebrochen: Journal Entry wurde nicht "
                "eindeutig erzeugt.",
                frappe.ValidationError,
            )
        created["journal_entry"] = je_name

    for row in report:
        signed_amount = consolidated_by_invoice.get(
            cstr(row.get("invoice")),
            Decimal("0"),
        )
        row["consolidated_bk_share"] = _as_money(signed_amount)

    if report:
        if created.get("journal_entry"):
            settlement_status = (
                f"\nAuf den Ausgleichsbeleg übertragen: "
                f"{_as_money(applied_signed.copy_abs()):.2f}; "
                f"Quell-OP brutto geschlossen: {_as_money(applied):.2f}; "
                f"signed: {_as_money(applied_signed):.2f}"
            )
        elif consolidate_unpaid:
            settlement_status = "\nKeine automatische Verrechnung durchgeführt; die Posten bleiben getrennt offen."
        else:
            settlement_status = "\nAutomatische Verrechnung: aus; die Posten bleiben getrennt offen."
        doc.add_comment(
            "Comment",
            text=(
                "Offene BK-Vorauszahlungsanteile dieses Abrechnungszeitraums:\n" +
                "\n".join([f"- {row['invoice']}: {row['outstanding_bk_share']:.2f}" for row in report]) +
                f"\nSumme: {_as_money(total_out_bk):.2f}" +
                settlement_status
            ),
        )

    # Die Verlinkung ist Teil derselben Transaktion wie die erzeugten Belege.
    # Ein Fehler muss propagieren, damit Frappe alles zurückrollt und kein
    # unverlinkter Beleg bei einem Retry doppelt gebucht wird.
    updates = {}
    if created.get("sales_invoice"):
        updates["sales_invoice"] = created["sales_invoice"]
    if created.get("credit_note"):
        updates["credit_note"] = created["credit_note"]
    if created.get("journal_entry"):
        updates["consolidation_journal_entry"] = created["journal_entry"]
    if updates:
        doc.db_set(updates)

    return {
        "created": created,
        "unpaid_report": report,
        "unpaid_sum": _as_money(total_out_bk),
        "consolidate_unpaid": consolidate_unpaid,
        "consolidated_sum": (
            _as_money(applied_signed.copy_abs())
            if created.get("journal_entry")
            else 0.0
        ),
        "consolidated_gross_sum": (
            _as_money(applied)
            if created.get("journal_entry")
            else 0.0
        ),
        "consolidated_signed_sum": (
            _as_money(applied_signed)
            if created.get("journal_entry")
            else 0.0
        ),
    }


def _run_settlement_selfcheck(
    doc,
    *,
    contract_identity: Optional[Dict[str, Any]] = None,
    company: Optional[str] = None,
) -> None:
    issues: list[str] = []
    # Company vorhanden?
    company = company or _get_default_company(doc)
    if not company:
        issues.append("Keine Company in den Standardwerten gefunden. Bitte unter System Defaults eine Company setzen.")
    # Mieter vorhanden?
    mv = doc.mietvertrag
    customer = None
    contract_wohnung = None
    locked_identity = contract_identity or getattr(
        doc,
        "_locked_mietvertrag_identity",
        None,
    )
    if locked_identity:
        customer = locked_identity.get("kunde")
        contract_wohnung = locked_identity.get("wohnung")
    elif mv:
        try:
            identity = frappe.db.get_value(
                "Mietvertrag",
                mv,
                ["kunde", "wohnung"],
                as_dict=True,
            ) or {}
            customer = identity.get("kunde")
            contract_wohnung = identity.get("wohnung")
        except Exception:
            customer = None
    if not customer:
        issues.append("Kein Mieter am Mietvertrag hinterlegt.")
    elif getattr(doc, "customer", None) and doc.customer != customer:
        issues.append(
            f"Customer {doc.customer} passt nicht zum Mietvertrag {mv} ({customer})."
        )
    if contract_wohnung and getattr(doc, "wohnung", None) != contract_wohnung:
        issues.append(
            f"Wohnung {getattr(doc, 'wohnung', None)} passt nicht zum "
            f"Mietvertrag {mv} ({contract_wohnung})."
        )
    # Receivable Account vorhanden?
    if company:
        receivables = frappe.get_all(
            "Account",
            filters={"company": company, "account_type": "Receivable", "is_group": 0},
            pluck="name",
            limit=1,
        )
        if not receivables:
            issues.append(f"Kein Debitorenkonto (Receivable) für Company {company} vorhanden.")
    # Items + Income Account Defaults: fehlende Items automatisch anlegen/ergänzen
    if company:
        required_items = (
            ("BK Nachzahlung", "Betriebskosten Nachzahlung"),
            ("BK Guthaben", "Betriebskosten Guthaben"),
        )
        inc_acc = _find_income_account(company)
        for code, name in required_items:
            try:
                if not frappe.db.exists("Item", code):
                    if not inc_acc:
                        issues.append(
                            f"Artikel '{code}' fehlt und es existiert kein "
                            f"eindeutig konfiguriertes Settlement-Income-Konto "
                            f"für {company}."
                        )
                        continue
                    _ensure_item_with_income(code, name, company)
                # Sicherstellen, dass ein Income Account Default gesetzt ist
                it = frappe.get_doc("Item", code)
                has_def = any(d.company == company and d.income_account for d in (it.item_defaults or []))
                if not has_def and inc_acc:
                    it.append("item_defaults", {"company": company, "income_account": inc_acc})
                    it.save()
                # Nach dem Versuch erneut prüfen
                it.reload()
                has_def = any(d.company == company and d.income_account for d in (it.item_defaults or []))
                if not has_def:
                    issues.append(f"Artikel '{code}' hat keinen Income Account für Company {company} in Item Defaults.")
            except Exception as e:
                issues.append(f"Artikel '{code}' konnte nicht automatisch vorbereitet werden: {e}")
    # Abrechnungsdaten vorhanden?
    if not (doc.wohnung and doc.von and doc.bis):
        issues.append("Abrechnung unvollständig: Wohnung, Von und Bis müssen gesetzt sein.")

    if issues:
        raise frappe.ValidationError("Voraussetzungen nicht erfüllt:\n- " + "\n- ".join(issues))


@frappe.whitelist()
def run_bk_settlement_selfcheck(abrechnung: str) -> dict:
    doc = frappe.get_doc("Betriebskostenabrechnung Mieter", abrechnung)
    _run_settlement_selfcheck(doc)
    return {"ok": True}
