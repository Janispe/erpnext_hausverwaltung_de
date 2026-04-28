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

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import getdate, cstr

from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
    _prorated_festbetrag_rows,
    allocate_kosten_auf_wohnungen,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
    get_bk_prepayment_summary,
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

def _get_default_company() -> Optional[str]:
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
    # Bevorzugt dediziertes Konto "Betriebskostenabrechnung"
    rows = frappe.get_all("Account", filters={**filters, "account_name": "Betriebskostenabrechnung"}, pluck="name", limit=1)
    if rows:
        return rows[0]
    rows = frappe.get_all("Account", filters=filters, pluck="name", limit=1)
    return rows[0] if rows else None


def _ensure_item_with_income(item_code: str, item_name: str, company: Optional[str]) -> str:
    if frappe.db.exists("Item", item_code):
        if company:
            it = frappe.get_doc("Item", item_code)
            has_def = any(d.company == company and d.income_account for d in (it.item_defaults or []))
            if not has_def:
                inc = _find_income_account(company)
                if inc:
                    it.append("item_defaults", {"company": company, "income_account": inc})
                    it.save(ignore_permissions=True)
        return item_code
    it = frappe.new_doc("Item")
    it.item_code = item_code
    it.item_name = item_name
    it.item_group = "All Item Groups"
    it.is_sales_item = 1
    it.maintain_stock = 0
    if company:
        inc = _find_income_account(company)
        if inc:
            it.append("item_defaults", {"company": company, "income_account": inc})
    it.insert(ignore_permissions=True)
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


def _mietvertrag_segmente_fuer_zeitraum(wohnung: str, von: str, bis: str) -> List[dict]:
    """Ermittle Mietvertrags-Segmente (tageweise, inklusiv) im Zeitraum.

    Segmente werden auf [von,bis] geclippt. Überlappungen führen zu Fehler.
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
            frappe.throw(
                "Überlappende Mietverträge gefunden: "
                f"{pv.get('name')} ({pv.get('von')} - {pv.get('bis') or 'offen'}) und "
                f"{cv.get('name')} ({cv.get('von')} - {cv.get('bis') or 'offen'})."
            )
    return segments


def _bestehender_mietvertrag_fuer_stichtag(wohnung: str, stichtag: str) -> Optional[str]:
    rows = frappe.get_all(
        "Mietvertrag",
        filters={
            "wohnung": wohnung,
            "von": ("<=", stichtag),
            "bis": ("is", "set"),
        },
        fields=["name", "von"],
        order_by="von desc",
        limit=1,
    )
    if rows:
        return rows[0].name
    # Falls bis NULL (läuft weiter)
    rows = frappe.get_all(
        "Mietvertrag",
        filters={
            "wohnung": wohnung,
            "von": ("<=", stichtag),
            "bis": ("is", "not set"),
        },
        fields=["name", "von"],
        order_by="von desc",
        limit=1,
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
        doc.append(
            "abrechnung",
            {
                "betriebskostenart": art,
                "betrag": _as_money(amount),
            },
        )


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
    stichtag = stichtag or bis

    # Verteilte Kosten (nur für diese Wohnung herausziehen)
    immobilie = _immobilie_von_wohnung(wohnung)
    alloc = allocate_kosten_auf_wohnungen(von=von, bis=bis, immobilie=immobilie, stichtag=stichtag)
    matrix: Dict[str, Dict[str, Any]] = alloc.get("matrix") or {}
    posten_raw = matrix.get(wohnung) or {}
    posten = {art: _to_decimal(amount) for art, amount in posten_raw.items()}
    if not posten:
        frappe.throw(
            f"Keine verteilten Kosten für Wohnung '{wohnung}' im Zeitraum {von} bis {bis} (Stichtag {stichtag}). Prüfe Kostenverteilung/Verteilerschlüssel."
        )

    if not split_by_mietvertrag:
        # Für die Abrechnung zählen BK-Rechnungen der Periode,
        # aber nur soweit deren BK-Anteil tatsächlich bezahlt wurde.
        prep = get_bk_prepayment_summary(wohnung=wohnung, from_date=von, to_date=bis)
        paid_total = _to_decimal(prep.get("paid_total"))

        # Mietvertrag & Mieter
        mv = _bestehender_mietvertrag_fuer_stichtag(wohnung, stichtag)
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
            "customer": _get_customer_for_mietvertrag(mv),
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
            d.insert(ignore_permissions=True)
        except Exception as e:
            frappe.throw(f"Abrechnung konnte nicht angelegt werden: {e}")
        if submit:
            try:
                d.submit()
            except Exception as e:
                frappe.throw(f"Abrechnung konnte nicht eingereicht werden: {e}")
        return d.name

    segments = _mietvertrag_segmente_fuer_zeitraum(wohnung, von, bis)
    if not segments:
        frappe.throw(f"Kein Mietvertrag im Zeitraum {von} bis {bis} für Wohnung '{wohnung}' gefunden.")

    festbetrag_arten = {
        row.get("name")
        for row in (
            frappe.get_all(
                "Betriebskostenart",
                filters={"verteilung": "Festbetrag"},
                fields=["name"],
                limit_page_length=0,
            )
            or []
        )
        if row.get("name")
    }
    posten_fest = {art: amount for art, amount in posten.items() if art in festbetrag_arten}
    posten_zeitanteilig = {art: amount for art, amount in posten.items() if art not in festbetrag_arten}

    # Tagesgenaue Verteilung gegen Gesamtzeitraum (Leerstand bleibt beim Vermieter)
    period_days = (getdate(bis) - getdate(von)).days + 1
    if period_days <= 0:
        frappe.throw(f"Ungültiger Zeitraum {von} bis {bis}.")
    period_days_dec = Decimal(str(period_days))

    # Segmentbeträge vorbereiten (Decimal, unquantized)
    seg_posten: List[Dict[str, Decimal]] = []
    total_unrounded = Decimal("0")
    for seg in segments:
        seg_start = seg["start"].strftime("%Y-%m-%d")
        seg_end = seg["end"].strftime("%Y-%m-%d")
        factor = Decimal(str(seg["days"])) / period_days_dec
        seg_amounts: Dict[str, Decimal] = {}
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

    # Zielsumme (gerundet) über alle Segmente
    target_total = _quantize_money(total_unrounded)

    created: List[str] = []
    sum_written = Decimal("0")
    for idx, seg in enumerate(segments):
        seg_start = seg["start"].strftime("%Y-%m-%d")
        seg_end = seg["end"].strftime("%Y-%m-%d")
        seg_stichtag = stichtag
        if seg_stichtag:
            seg_stichtag = min(getdate(seg_stichtag), getdate(seg_end)).strftime("%Y-%m-%d")
        else:
            seg_stichtag = seg_end

        # Segmentweise: Rechnung muss im Segment liegen, gezählt wird nur bezahlter BK-Anteil.
        prep = get_bk_prepayment_summary(wohnung=wohnung, from_date=seg_start, to_date=seg_end)
        paid_total = _to_decimal(prep.get("paid_total"))

        mv = seg.get("mietvertrag")
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
            "customer": _get_customer_for_mietvertrag(mv),
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
        if idx == len(segments) - 1 and seg_amounts:
            # Remainder auf letzte Abrechnung legen (erste Kostenart)
            current_sum = Decimal("0")
            for amt in seg_amounts.values():
                current_sum += _quantize_money(amt)
            sum_written_before = sum_written + current_sum
            drift = _quantize_money(target_total - sum_written_before)
            if drift.copy_abs() >= MONEY_QUANT:
                first_art = next(iter(seg_amounts.keys()))
                seg_amounts[first_art] = seg_amounts[first_art] + drift

        # Kosten schreiben und Summe merken
        _add_abrechnungsposten(d, seg_amounts)
        seg_written = Decimal("0")
        for amt in seg_amounts.values():
            seg_written += _quantize_money(_to_decimal(amt))
        sum_written += seg_written

        d.flags.skip_auto_settle = True
        d.flags.allow_manual_create = True
        try:
            d.insert(ignore_permissions=True)
        except Exception as e:
            frappe.throw(f"Abrechnung konnte nicht angelegt werden: {e}")
        if submit:
            try:
                d.submit()
            except Exception as e:
                frappe.throw(f"Abrechnung konnte nicht eingereicht werden: {e}")
        created.append(d.name)

    return created


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
    stichtag = stichtag or bis
    alloc = allocate_kosten_auf_wohnungen(von=von, bis=bis, immobilie=immobilie, stichtag=stichtag)
    matrix: Dict[str, Dict[str, float]] = alloc.get("matrix") or {}
    if not matrix:
        frappe.throw(
            f"Keine verteilten Kosten/ Wohnungen gefunden für Immobilie '{immobilie}' im Zeitraum {von} bis {bis} (Stichtag {stichtag}). Prüfe Kostenbuchungen, Verteilerschlüssel und Zuordnung der Wohnungen zur Immobilie."
        )

    if not head:
        frappe.throw("Bitte zuerst das Objekt 'Betriebskostenabrechnung Immobilie' anlegen und dessen Name als 'head' übergeben.")

    created: List[str] = []
    head_name = head
    for whg in sorted(matrix.keys()):
        res = create_bk_abrechnung_wohnung(
            von=von,
            bis=bis,
            wohnung=whg,
            submit=False,
            stichtag=stichtag,
            head=head_name,
            split_by_mietvertrag=split_by_mietvertrag,
        )
        if isinstance(res, list):
            created.extend(res)
        else:
            created.append(res)

    if not created:
        frappe.throw(
            f"Es konnten keine Mieter‑Abrechnungen erzeugt werden für Immobilie '{immobilie}' im Zeitraum {von} bis {bis}."
        )
    return {"created": created, "count": len(created)}


# -----------------------------
# Abschluss: Nachzahlung / Guthaben
# -----------------------------

def _ensure_item(code: str, name: Optional[str] = None) -> str:
    name = name or code
    if frappe.db.exists("Item", code):
        return code
    item = frappe.new_doc("Item")
    item.item_code = code
    item.item_name = name
    item.item_group = "All Item Groups"
    item.is_sales_item = 1
    item.maintain_stock = 0
    item.insert(ignore_permissions=True)
    return code


def _get_customer_for_mietvertrag(mv: Optional[str]) -> Optional[str]:
    if not mv:
        return None
    try:
        return frappe.get_cached_value("Mietvertrag", mv, "kunde")
    except Exception:
        return None


def _bk_invoice_outstanding_shares(wohnung: str, from_date: str, to_date: str) -> List[dict]:
    """Ermittelt pro BK-Rechnung den offenen Anteil (nur BK-Anteil)."""
    from .operating_cost_prepaiment_calc import _bk_invoice_names_for_wohnung

    names = _bk_invoice_names_for_wohnung(wohnung, from_date, to_date)
    if not names:
        return []
    sql = """
        SELECT si.name,
               si.outstanding_amount,
               COALESCE(bki.bk_net, 0) AS bk_net,
               COALESCE(tot.total_net, 0) AS total_net,
               COALESCE(si.outstanding_amount * COALESCE(bki.bk_net / NULLIF(tot.total_net, 0), 0), 0) AS outstanding_bk_share
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
    rows = frappe.db.sql(sql, {"names": tuple(names), "bk": "Betriebskosten"}, as_dict=True)
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
) -> str:
    post_date = getdate(posting_date)
    si = frappe.new_doc("Sales Invoice")
    si.customer = customer
    if company:
        si.company = company
    # Fälligkeit: 3 Wochen nach Buchung; Payment Terms Templates bewusst ignorieren
    si.posting_date = post_date
    if due_date:
        si.due_date = getdate(due_date)
    else:
        si.due_date = post_date + timedelta(days=21)
    si.ignore_default_payment_terms_template = 1
    si.set("payment_terms_template", None)
    si.set("payment_schedule", [])
    si.set("is_return", is_return)
    # Für Return-Beleg werden Mengen/Rate negativ erwartet
    qty = 1
    amount_dec = _quantize_money(_to_decimal(amount))
    rate = _as_money(amount_dec)
    if is_return:
        # ERPNext returns expect negative qty with positive rate (unless negative rates are allowed)
        qty = -1
        rate = abs(rate)
    si.append("items", {"item_code": item_code, "qty": qty, "rate": rate})
    si.insert(ignore_permissions=True)
    if do_submit:
        si.submit()
    return si.name


def _get_si_debit_to(name: str) -> Optional[str]:
    try:
        return frappe.get_cached_value("Sales Invoice", name, "debit_to")
    except Exception:
        return None


def _allocate_via_journal_entry(
    company: str, entries: List[dict], posting_date: str, wertstellungsdatum: Optional[str] = None
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
    if wertstellungsdatum:
        je.custom_wertstellungsdatum = wertstellungsdatum
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for e in entries:
        row = je.append("accounts", {})
        row.account = e.get("account")
        row.party_type = e.get("party_type")
        row.party = e.get("party")
        row.reference_type = e.get("reference_type")
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
    je.insert(ignore_permissions=True)
    je.submit()
    return je.name


@frappe.whitelist()
def create_bk_settlement_documents(abrechnung: str, consolidate_unpaid: bool = False) -> dict:
    """Erstellt Nachzahlung (SI) oder Guthaben (Credit Note) für eine Mieter-Abrechnung.

    Optional: listet offene BK-Rechnungen im Zeitraum (BK-Anteil) als Bericht auf.
    """
    doc = frappe.get_doc("Betriebskostenabrechnung Mieter", abrechnung)
    wohnung = doc.wohnung
    mv = doc.mietvertrag
    customer = doc.customer or _get_customer_for_mietvertrag(mv)
    if not customer:
        frappe.throw("Kein Mieter auf dem Mietvertrag gefunden.")

    posting_date = cstr(doc.bis or doc.datum or frappe.utils.today())
    due_date = None
    head_name = (doc.immobilien_abrechnung or "").strip()
    if head_name:
        try:
            head_doc = frappe.get_doc("Betriebskostenabrechnung Immobilie", head_name)
            due_date = cstr(getattr(head_doc, "nachzahlung_faellig_am", None) or "")
        except Exception:
            due_date = None
    # Differenz robust berechnen: Summe Abrechnungsposten minus Vorauszahlungen
    try:
        total = Decimal("0")
        for r in getattr(doc, "abrechnung", []) or []:
            total += _to_decimal(r.get("betrag"))
        vor = _to_decimal(getattr(doc, "vorrauszahlungen", 0))
        diff = _quantize_money(total - vor)
    except Exception:
        diff = Decimal("0")

    # Selfcheck: wirf Fehler, wenn Setup unvollständig
    _run_settlement_selfcheck(doc)
    company = _get_default_company()
    # Sicherstellen: Artikel existieren und haben Income Account Defaults
    code_nach = _ensure_item_with_income("BK Nachzahlung", "Betriebskosten Nachzahlung", company)
    code_guth = _ensure_item_with_income("BK Guthaben", "Betriebskosten Guthaben", company)

    created: Dict[str, Optional[str]] = {"sales_invoice": None, "credit_note": None, "journal_entry": None}
    new_doc_name = None
    new_doc_is_return = 0
    base_amount = Decimal("0")
    applied = Decimal("0")

    # Unbezahlte BK-Anteile ermitteln (zur optionalen Konsolidierung)
    report: List[Dict[str, Any]] = []
    total_out_bk = Decimal("0")
    rows = []
    if wohnung and doc.von and doc.bis:
        rows = _bk_invoice_outstanding_shares(wohnung, cstr(doc.von), cstr(doc.bis))
        for r in rows:
            amt = _quantize_money(_to_decimal(r.get("outstanding_bk_share")))
            if amt > MONEY_QUANT:
                report.append({"invoice": r.get("name"), "outstanding_bk_share": _as_money(amt)})
                total_out_bk += amt

    if diff > MONEY_QUANT:
        # Nachzahlung: wende offene Alt-BK bis zur Höhe der Differenz an
        applied = min(total_out_bk, diff)
        base_amount = _quantize_money(diff - applied) if diff > applied else Decimal("0")
        try:
            new_doc_name = _make_sales_invoice(
                customer,
                posting_date,
                code_nach,
                base_amount,
                is_return=0,
                do_submit=True,
                company=company,
                due_date=due_date or None,
            )
        except Exception as e:
            frappe.throw(f"Nachzahlung konnte nicht erstellt werden: {e}")
        new_doc_is_return = 0
        created["sales_invoice"] = new_doc_name
    elif diff < -MONEY_QUANT:
        # Guthaben: Credit Note; ggfs. Teil des Guthabens zur Schließung alter Offenen verwenden
        diff_abs = diff.copy_abs()
        applied = min(total_out_bk, diff_abs)
        base_amount = _quantize_money(diff_abs - applied) if diff_abs > applied else Decimal("0")
        try:
            new_doc_name = _make_sales_invoice(customer, posting_date, code_guth, base_amount, is_return=1, do_submit=True, company=company)
        except Exception as e:
            frappe.throw(f"Guthaben konnte nicht erstellt werden: {e}")
        new_doc_is_return = 1
        created["credit_note"] = new_doc_name
    else:
        created["note"] = "Abrechnung ist ausgeglichen."

    # Konsolidierung via Journal Entry: alte Offene schließen und auf neuen Beleg übertragen
    if consolidate_unpaid and applied > MONEY_QUANT and new_doc_name:
        # Konten bestimmen
        entries: List[dict] = []
        # company und receivable account vom neuen Beleg ziehen
        si_doc = frappe.get_doc("Sales Invoice", new_doc_name)
        company = si_doc.company
        new_acc = si_doc.debit_to
        # Debit auf neuen Beleg (Nachzahlung) oder auf Credit Note (reduziert deren Gutschrift)
        if applied > MONEY_QUANT:
            entries.append({
                "account": new_acc,
                "party_type": "Customer",
                "party": si_doc.customer,
                "reference_type": "Sales Invoice",
                "reference_name": new_doc_name,
                "debit": _quantize_money(applied),
                "credit": Decimal("0"),
            })
        # Credits je alte Rechnung (BK-Anteil)
        remaining = applied
        for r in rows:
            if remaining <= MONEY_QUANT:
                break
            amt = _quantize_money(_to_decimal(r.get("outstanding_bk_share")))
            if amt <= MONEY_QUANT:
                continue
            use = amt if amt <= remaining else remaining
            old_name = r.get("name")
            old_acc = _get_si_debit_to(old_name) or new_acc
            entries.append({
                "account": old_acc,
                "party_type": "Customer",
                "party": si_doc.customer,
                "reference_type": "Sales Invoice",
                "reference_name": old_name,
                "debit": Decimal("0"),
                "credit": _quantize_money(use),
            })
            remaining = _quantize_money(remaining - use)
        je_name = _allocate_via_journal_entry(company, entries, posting_date, posting_date)
        if je_name:
            created["journal_entry"] = je_name

    if report:
        doc.add_comment(
            "Comment",
            text=(
                "Offene BK-Anteile früherer Rechnungen (Bericht):\n" +
                "\n".join([f"- {row['invoice']}: {row['outstanding_bk_share']:.2f}" for row in report]) +
                f"\nSumme: {_as_money(total_out_bk):.2f}"
            ),
        )

    # Verlinkungen am Abrechnungs-Datensatz speichern (read-only Felder)
    try:
        updates = {}
        if created.get("sales_invoice"):
            updates["sales_invoice"] = created["sales_invoice"]
        if created.get("credit_note"):
            updates["credit_note"] = created["credit_note"]
        if created.get("journal_entry"):
            updates["consolidation_journal_entry"] = created["journal_entry"]
        if updates:
            doc.db_set(updates)
    except Exception:
        # Verlinkung optional; bei Fehler nicht blockieren
        pass

    return {"created": created, "unpaid_report": report, "unpaid_sum": _as_money(total_out_bk)}


def _run_settlement_selfcheck(doc) -> None:
    issues: list[str] = []
    # Company vorhanden?
    company = _get_default_company()
    if not company:
        issues.append("Keine Company in den Standardwerten gefunden. Bitte unter System Defaults eine Company setzen.")
    # Mieter vorhanden?
    mv = doc.mietvertrag
    customer = None
    if mv:
        try:
            customer = frappe.get_cached_value("Mietvertrag", mv, "kunde")
        except Exception:
            customer = None
    if not customer:
        issues.append("Kein Mieter am Mietvertrag hinterlegt.")
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
        if not inc_acc:
            issues.append(f"Kein Ertragskonto (Income) für Company {company} vorhanden.")
        for code, name in required_items:
            try:
                if not frappe.db.exists("Item", code):
                    _ensure_item_with_income(code, name, company)
                # Sicherstellen, dass ein Income Account Default gesetzt ist
                it = frappe.get_doc("Item", code)
                has_def = any(d.company == company and d.income_account for d in (it.item_defaults or []))
                if not has_def and inc_acc:
                    it.append("item_defaults", {"company": company, "income_account": inc_acc})
                    it.save(ignore_permissions=True)
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
