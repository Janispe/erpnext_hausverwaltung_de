"""Server endpoints for the Buchungs-Cockpit.

Replaces the intermediary DocTypes VereinfachteBuchung / VereinfachteMieterRechnung
by creating Purchase Invoice / Sales Invoice directly from the submitted tool dialog.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import add_days, cstr, getdate, nowdate
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.utils.buchung import ensure_default_service_item


EINGABEQUELLE_EINGANG = "Vereinfachte Buchung"
EINGABEQUELLE_AUSGANG = "Vereinfachte Mieterrechnung"

# Mapping deutscher → englischer Ländernamen für die ERPNext-Country-Tabelle.
# Wir nehmen die häufigsten DACH/EU-Länder, das Frontend tippt sonst sowieso
# Englisch dank Country-Link-Autocomplete.
_DE_COUNTRY_MAP = {
    "Deutschland": "Germany",
    "Österreich": "Austria",
    "Oesterreich": "Austria",
    "Schweiz": "Switzerland",
    "Niederlande": "Netherlands",
    "Belgien": "Belgium",
    "Frankreich": "France",
    "Italien": "Italy",
    "Spanien": "Spain",
    "Polen": "Poland",
    "Tschechien": "Czech Republic",
    "Dänemark": "Denmark",
}


# ---------------------------------------------------------------------------
# Helpers (shared between PI and SI creation)
# ---------------------------------------------------------------------------


def _parse_rows(rows: Any) -> list[dict]:
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except json.JSONDecodeError:
            frappe.throw("Positionen konnten nicht gelesen werden (ungültiges JSON).")
    if not isinstance(rows, list):
        frappe.throw("Positionen müssen als Liste übergeben werden.")
    return [dict(r or {}) for r in rows]


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.get_meta(doctype).get_field(fieldname))
    except Exception:
        return False


def _resolve_kostenart_name(raw_name: str) -> tuple[str, str] | None:
    """Findet zu einem Kostenart-Namen den passenden Doctype.

    Probiert in Reihenfolge: Betriebskostenart → Kostenart nicht umlagefaehig →
    Suffix-Variante "<name> (nicht umlegbar)" für Namens-Kollisionen.
    Liefert (doctype, real_name) oder None.
    """
    if not raw_name:
        return None
    if frappe.db.exists("Betriebskostenart", raw_name):
        return ("Betriebskostenart", raw_name)
    if frappe.db.exists("Kostenart nicht umlagefaehig", raw_name):
        return ("Kostenart nicht umlagefaehig", raw_name)
    suffix = " (nicht umlegbar)"
    if raw_name.endswith(suffix):
        stripped = raw_name[: -len(suffix)]
        if frappe.db.exists("Kostenart nicht umlagefaehig", stripped):
            return ("Kostenart nicht umlagefaehig", stripped)
    return None


def _find_kostenart_for_konto(konto: str) -> dict | None:
    """Reverse-Lookup: zu einem Konto die zugehörige BK oder Kostenart-nicht-UL finden.

    Liefert {"doctype", "name", "artikel"} oder None. Voraussetzung: das Konto ist
    durch die Validierung in höchstens einer der beiden Listen vorhanden.
    """
    if not konto:
        return None

    bk_name = frappe.db.get_value("Betriebskostenart", {"konto": konto}, "name")
    if bk_name:
        artikel = frappe.db.get_value("Betriebskostenart", bk_name, "artikel")
        return {"doctype": "Betriebskostenart", "name": bk_name, "artikel": artikel}

    nul_name = frappe.db.get_value(
        "Kostenart nicht umlagefaehig", {"konto": konto}, "name"
    )
    if nul_name:
        artikel = frappe.db.get_value("Kostenart nicht umlagefaehig", nul_name, "artikel")
        return {
            "doctype": "Kostenart nicht umlagefaehig",
            "name": nul_name,
            "artikel": artikel,
        }

    return None


@frappe.whitelist()
def resolve_kostenart_by_konto(konto: str) -> dict | None:
    """Whitelist-Wrapper für `_find_kostenart_for_konto` — zur Nutzung aus dem Cockpit-JS."""
    return _find_kostenart_for_konto(konto)


@frappe.whitelist()
def autocomplete_kostenarten(txt: str = "", typ: str = "alle", **_kwargs) -> list[dict]:
    """Autocomplete-Endpoint für die Kostenart-Spalte.

    Args:
        txt: Suchtext (LIKE-Filter auf den Namen).
        typ: "umlegbar" | "nicht_umlegbar" | "alle" — entspricht dem Per-Zeile-Typ-Select.
    """
    rows = list_eligible_kostenarten(typ=typ)
    if txt:
        txt_lower = txt.lower()
        rows = [r for r in rows if txt_lower in (r.get("value") or "").lower()]
    return rows


@frappe.whitelist()
def autocomplete_konten(txt: str = "", typ: str = "alle", **_kwargs) -> list[dict]:
    """Autocomplete-Endpoint für die Konto-Spalte (im Konto-Modus).

    Args:
        txt: Suchtext.
        typ: "umlegbar" -> nur Konten aus Betriebskostenart;
             "nicht_umlegbar" -> nur Konten aus Kostenart-nicht-UL;
             "alle" -> beide.
    """
    typ = (typ or "alle").lower()
    bk_clause = """
        SELECT konto, name AS kostenart, 'umlegbar' AS typ FROM `tabBetriebskostenart`
            WHERE konto IS NOT NULL AND konto != ''
              AND artikel IS NOT NULL AND artikel != ''
    """
    nul_clause = """
        SELECT konto, name AS kostenart, 'nicht umlegbar' AS typ FROM `tabKostenart nicht umlagefaehig`
            WHERE konto IS NOT NULL AND konto != ''
              AND artikel IS NOT NULL AND artikel != ''
    """
    if typ == "umlegbar":
        sql = bk_clause
    elif typ == "nicht_umlegbar":
        sql = nul_clause
    else:
        sql = f"{bk_clause} UNION {nul_clause}"
    sql += " ORDER BY konto"

    rows = frappe.db.sql(sql, as_dict=True) or []
    if txt:
        txt_lower = txt.lower()
        rows = [r for r in rows if txt_lower in (r.get("konto") or "").lower()]
    return [
        {"value": r["konto"], "description": f"{r['typ']} – {r['kostenart']}"}
        for r in rows
    ]


@frappe.whitelist()
def list_eligible_konten() -> list[dict]:
    """Liefert alle Konten, die in BK oder Kostenart-nicht-UL mit Konto+Artikel hinterlegt sind.

    Format: [{"value": "4400 Heizkosten", "description": "umlegbar – Heizung"}, ...]
    Genutzt im Cockpit, wenn der Eingabemodus „Konto" aktiv ist.
    """
    rows = frappe.db.sql(
        """
        SELECT konto, name AS kostenart, 'umlegbar' AS typ FROM `tabBetriebskostenart`
            WHERE konto IS NOT NULL AND konto != ''
              AND artikel IS NOT NULL AND artikel != ''
        UNION
        SELECT konto, name AS kostenart, 'nicht umlegbar' AS typ FROM `tabKostenart nicht umlagefaehig`
            WHERE konto IS NOT NULL AND konto != ''
              AND artikel IS NOT NULL AND artikel != ''
        ORDER BY konto
        """,
        as_dict=True,
    )
    return [
        {"value": r["konto"], "description": f"{r['typ']} – {r['kostenart']}"}
        for r in rows or []
    ]


@frappe.whitelist()
def list_eligible_kostenarten(typ: str = "alle") -> list[dict]:
    """Liefert buchbare Kostenart-Einträge (Konto UND Artikel gesetzt).

    Args:
        typ: "umlegbar" -> nur Betriebskostenart, "nicht_umlegbar" -> nur
            Kostenart nicht umlagefaehig, "alle" -> beide kombiniert mit
            Suffix-Konfliktbehandlung (Default).

    Format: [{"value": "Heizung", "description": "umlegbar"}, ...]
    """
    typ = (typ or "alle").lower()

    out: list[dict] = []
    bks: list[str] = []
    nuls: list[str] = []

    if typ in ("umlegbar", "alle"):
        bks = frappe.get_all(
            "Betriebskostenart",
            filters={"konto": ["is", "set"], "artikel": ["is", "set"]},
            pluck="name",
            order_by="name",
        )
    if typ in ("nicht_umlegbar", "alle"):
        nuls = frappe.get_all(
            "Kostenart nicht umlagefaehig",
            filters={"konto": ["is", "set"], "artikel": ["is", "set"]},
            pluck="name",
            order_by="name",
        )

    bk_set = set(bks)
    for n in bks:
        out.append({"value": n, "description": "umlegbar"})
    for n in nuls:
        # Bei Namens-Kollision mit BK den Typ explizit ans Ende hängen (nur im "alle"-Fall relevant).
        if n in bk_set:
            out.append({"value": f"{n} (nicht umlegbar)", "description": "nicht umlegbar"})
        else:
            out.append({"value": n, "description": "nicht umlegbar"})
    return out


@frappe.whitelist()
def eligible_konten_query(doctype, txt, searchfield, start, page_len, filters):
    """Custom Link-Query: liefert nur Accounts, die in BK oder Kostenart-nicht-UL referenziert sind.

    Wird im Cockpit für das Konto-Suchfeld verwendet, wenn der Eingabemodus „Konto" aktiv ist.
    Damit sieht der User nur Konten, für die ein Reverse-Lookup gelingen wird.
    """
    return frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE name IN (
            SELECT konto FROM `tabBetriebskostenart`
                WHERE konto IS NOT NULL AND konto != ''
                  AND artikel IS NOT NULL AND artikel != ''
            UNION
            SELECT konto FROM `tabKostenart nicht umlagefaehig`
                WHERE konto IS NOT NULL AND konto != ''
                  AND artikel IS NOT NULL AND artikel != ''
        )
        AND name LIKE %(txt)s
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "txt": f"%{txt or ''}%",
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )


def _get_kostenart_details(row: dict) -> dict | None:
    """Resolve konto/artikel from whichever Kostenart-DocType the row references.

    Populates row["umlagefaehig"] + row["kostenart"] as side-effects so the
    downstream item gets correctly tagged on the PI.

    Supports four shapes:
      - row["betriebskostenart"]  -> Betriebskostenart (umlegbar)
      - row["kostenart_nicht_ul"] -> Kostenart nicht umlagefaehig
      - row["kostenart"] + optional row["umlagefaehig"] (legacy/explicit)
      - row["konto"] (only)        -> Reverse-Lookup; wirft, wenn das Konto in keiner
                                       der beiden Listen vorkommt.
    """
    doctype = None
    name = None

    if row.get("betriebskostenart"):
        doctype = "Betriebskostenart"
        name = row.get("betriebskostenart")
    elif row.get("kostenart_nicht_ul"):
        doctype = "Kostenart nicht umlagefaehig"
        name = row.get("kostenart_nicht_ul")
    elif row.get("kostenart"):
        raw_name = row.get("kostenart")
        explicit_doctype = row.get("umlagefaehig")
        if explicit_doctype:
            doctype = explicit_doctype
            name = raw_name
        else:
            resolved = _resolve_kostenart_name(raw_name)
            if resolved:
                doctype, name = resolved
            else:
                # Fallback: vielleicht ist der Wert ein Konto-Name (Konto-Modus im Cockpit).
                konto_match = _find_kostenart_for_konto(raw_name)
                if konto_match:
                    doctype = konto_match["doctype"]
                    name = konto_match["name"]
                else:
                    frappe.throw(
                        f"„{raw_name}“ wurde weder als Kostenart noch als hinterlegtes "
                        f"Konto gefunden. Bitte aus dem Auswahl-Dropdown wählen."
                    )
    elif row.get("konto"):
        match = _find_kostenart_for_konto(row["konto"])
        if not match:
            frappe.throw(
                f"Konto „{row['konto']}“ ist weder als Betriebskostenart noch als "
                f"Kostenart nicht umlagefaehig hinterlegt. Bitte zuerst ein Stammdatum "
                f"anlegen, das dieses Konto referenziert."
            )
        doctype = match["doctype"]
        name = match["name"]

    if not (doctype and name):
        return None
    if not frappe.db.exists(doctype, name):
        return None

    try:
        vals = frappe.get_value(doctype, name, ["konto", "artikel"], as_dict=True)
    except Exception:
        return None
    if not vals:
        return None

    row["umlagefaehig"] = doctype
    row["kostenart"] = name
    return dict(vals)


def _row_requires_wohnung(row: dict, cache: dict[str, str]) -> bool:
    if row.get("umlagefaehig") != "Betriebskostenart":
        return False
    bk = row.get("kostenart")
    if not bk:
        return False
    if bk not in cache:
        try:
            cache[bk] = frappe.db.get_value("Betriebskostenart", bk, "verteilung") or ""
        except Exception:
            cache[bk] = ""
    return cstr(cache.get(bk) or "").lower() == "einzeln"


def _get_payable_account(*, company: str, supplier: str) -> str:
    candidates: list[str] = []
    supplier_default = None
    try:
        if frappe.get_meta("Supplier").has_field("default_payable_account"):
            supplier_default = frappe.db.get_value("Supplier", supplier, "default_payable_account")
    except Exception:
        supplier_default = None
    if supplier_default:
        candidates.append(supplier_default)
    company_default = frappe.db.get_value("Company", company, "default_payable_account")
    if company_default:
        candidates.append(company_default)

    for account in candidates:
        if not frappe.db.exists("Account", account):
            continue
        acc_company = frappe.db.get_value("Account", account, "company")
        if acc_company and acc_company != company:
            continue
        return account

    frappe.throw(
        "Kein gültiges Kreditorenkonto (Payable Account) gefunden. "
        "Bitte beim Lieferanten oder in der Company ein 'Default Payable Account' pflegen."
    )


def _derive_company_from_rows(rows: list[dict]) -> str | None:
    for row in rows:
        cc = row.get("kostenstelle")
        if cc:
            company = frappe.get_cached_value("Cost Center", cc, "company")
            if company:
                return company
    return None


def _derive_company_from_mietvertrag(mietvertrag: str) -> str | None:
    wohnung = frappe.db.get_value("Mietvertrag", mietvertrag, "wohnung")
    if not wohnung:
        return None
    immobilie = frappe.db.get_value("Wohnung", wohnung, "immobilie")
    if not immobilie:
        return None
    kostenstelle = frappe.db.get_value("Immobilie", immobilie, "kostenstelle")
    if not kostenstelle:
        return None
    return frappe.db.get_value("Cost Center", kostenstelle, "company")


def _derive_cost_center_from_mietvertrag(mietvertrag: str) -> str | None:
    wohnung = frappe.db.get_value("Mietvertrag", mietvertrag, "wohnung")
    if not wohnung:
        return None
    immobilie = frappe.db.get_value("Wohnung", wohnung, "immobilie")
    if not immobilie:
        return None
    return frappe.db.get_value("Immobilie", immobilie, "kostenstelle")


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_purchase_invoice(**kwargs) -> dict:
    """Create and submit a Purchase Invoice from the Buchungs-Cockpit tool.

    Expected kwargs:
        lieferant: Supplier name (required)
        rechnungsdatum: ISO date (defaults to today)
        wertstellungsdatum: ISO date (Leistungszeitraum, optional) — landet in custom_wertstellungsdatum
        rechnungsname: free-form invoice number / label
        remarks: optional Notiz / Verwendungszweck (landet in pi.remarks)
        positionen: list of dicts with keys
            betrag, konto, kostenstelle, umlagefaehig, kostenart, wohnung (optional)
    """
    supplier = kwargs.get("lieferant")
    if not supplier:
        frappe.throw("Bitte einen Lieferanten auswählen.")

    rows = _parse_rows(kwargs.get("positionen"))
    if not rows:
        frappe.throw("Es sind keine Positionen erfasst.")

    company = _derive_company_from_rows(rows)
    if not company:
        frappe.throw(
            "Konnte keine Company ermitteln. Bitte in mindestens einer Position eine Kostenstelle angeben."
        )

    posting_date = kwargs.get("rechnungsdatum") or nowdate()
    bill_no = kwargs.get("rechnungsname")

    service_item_code = ensure_default_service_item()

    pi = frappe.new_doc("Purchase Invoice")
    user_remarks = (kwargs.get("remarks") or "").strip()
    remarks_lines = ["Erfasst über Buchungs-Cockpit"]
    if user_remarks:
        remarks_lines.append(user_remarks)
    pi.update({
        "company": company,
        "supplier": supplier,
        "posting_date": posting_date,
        "bill_date": posting_date,
        "bill_no": bill_no,
        "remarks": "\n".join(remarks_lines),
    })

    payable_account = _get_payable_account(company=company, supplier=supplier)
    pi.credit_to = payable_account

    try:
        pi_currency = frappe.db.get_value("Account", payable_account, "account_currency")
        if not pi_currency:
            pi_currency = frappe.db.get_value("Company", company, "default_currency")
        if pi_currency:
            pi.currency = pi_currency
            pi.conversion_rate = 1
    except Exception:
        pass

    items: list[dict] = []
    verteilung_cache: dict[str, str] = {}
    first_cost_center = next((r.get("kostenstelle") for r in rows if r.get("kostenstelle")), None)

    for idx, row in enumerate(rows, start=1):
        betrag = row.get("betrag")
        if betrag in (None, ""):
            frappe.throw(f"Position {idx}: Betrag fehlt.")

        kostenart_info = _get_kostenart_details(row)
        expense_account = (kostenart_info.get("konto") if kostenart_info else None) or row.get("konto")
        if not expense_account:
            expense_account = frappe.get_cached_value("Company", company, "default_expense_account")
            if not expense_account:
                frappe.throw(
                    f"Position {idx}: Bitte ein Aufwandskonto wählen "
                    "(in der Kostenart oder direkt in der Position)."
                )

        cost_center = (
            row.get("kostenstelle")
            or first_cost_center
            or frappe.get_cached_value("Company", company, "cost_center")
        )
        if not cost_center:
            frappe.throw(f"Position {idx}: Bitte eine Kostenstelle wählen.")

        desc_parts = []
        if row.get("umlagefaehig"):
            desc_parts.append(f"Typ: {row.get('umlagefaehig')}")
        if row.get("kostenart"):
            desc_parts.append(f"Kostenart: {row.get('kostenart')}")
        description = "; ".join(desc_parts) or kwargs.get("rechnungsname") or "Ausgabe"

        item_code = (
            kostenart_info.get("artikel")
            if kostenart_info and kostenart_info.get("artikel")
            else service_item_code
        )

        item_row: dict[str, Any] = {
            "item_code": item_code,
            "item_name": "Ausgabe",
            "description": description,
            "qty": 1,
            "rate": float(betrag),
            "expense_account": expense_account,
            "cost_center": cost_center,
        }

        if _has_field("Purchase Invoice Item", "hv_umlagefaehig") and row.get("umlagefaehig"):
            item_row["hv_umlagefaehig"] = row.get("umlagefaehig")
        if _has_field("Purchase Invoice Item", "hv_kostenart") and row.get("kostenart"):
            item_row["hv_kostenart"] = row.get("kostenart")

        if _row_requires_wohnung(row, verteilung_cache):
            if not row.get("wohnung"):
                frappe.throw(
                    f"Position {idx}: Betriebskostenart '{row.get('kostenart')}' ist auf 'Einzeln' "
                    "verteilt — bitte eine Wohnung auswählen."
                )
            if not _has_field("Purchase Invoice Item", "wohnung"):
                frappe.throw(
                    "Accounting Dimension 'Wohnung' ist nicht verfügbar (Feld 'wohnung' fehlt auf Purchase Invoice Item)."
                )
            item_row["wohnung"] = row.get("wohnung")
        elif row.get("wohnung") and _has_field("Purchase Invoice Item", "wohnung"):
            item_row["wohnung"] = row.get("wohnung")

        items.append(item_row)

    pi.set("items", items)

    wertstellungsdatum = kwargs.get("wertstellungsdatum")
    if wertstellungsdatum and _has_field("Purchase Invoice", "custom_wertstellungsdatum"):
        pi.custom_wertstellungsdatum = getdate(wertstellungsdatum)

    if _has_field("Purchase Invoice", "hv_eingabequelle"):
        pi.hv_eingabequelle = EINGABEQUELLE_EINGANG

    pi.insert(ignore_permissions=True)

    _attach_source_file(pi, kwargs.get("attached_file_url"))

    vorschlag_name = (kwargs.get("vorschlag_name") or "").strip()
    if vorschlag_name:
        from hausverwaltung.hausverwaltung.services.bulk_extraction import (
            link_vorschlag_to_pi,
        )
        link_vorschlag_to_pi(vorschlag_name, pi.name)

    submit_doc_raw = kwargs.get("submit_doc", 1)
    submit_flag = (
        bool(int(submit_doc_raw))
        if isinstance(submit_doc_raw, str)
        else bool(submit_doc_raw)
    )
    if submit_flag:
        pi.submit()
        frappe.msgprint(
            f"Eingangsrechnung {pi.name} wurde erstellt und eingereicht.", alert=True
        )
    else:
        frappe.msgprint(
            f"Eingangsrechnung {pi.name} wurde als Entwurf gespeichert.", alert=True
        )
    return {"name": pi.name, "submitted": submit_flag}


def _attach_source_file(pi, file_url: str | None) -> None:
    """Hängt das Quell-PDF aus der LLM-Extraktion an die Purchase Invoice an.

    Pattern aus integrations/paperless.py:1031.
    """
    if not file_url:
        return
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        return
    file_doc = frappe.get_doc("File", file_name)
    try:
        content = file_doc.get_content()
    except Exception:
        return
    save_file(
        file_doc.file_name,
        content,
        "Purchase Invoice",
        pi.name,
        is_private=1,
        df=None,
    )


@frappe.whitelist()
def create_sales_invoice(**kwargs) -> dict:
    """Create and submit a Sales Invoice from the Buchungs-Cockpit tool.

    Expected kwargs:
        mietvertrag: Mietvertrag name (required)
        rechnungsdatum: ISO date (defaults to today)
        faellig_am: ISO date (defaults to posting + 21 days)
        wertstellungsdatum: ISO date (Leistungszeitraum, optional) — landet in custom_wertstellungsdatum
        rechnungsname: free-form label
        referenz: optional reference
        positionen: list of dicts with keys
            beschreibung, betrag, artikel, erloeskonto
    """
    mietvertrag = kwargs.get("mietvertrag")
    if not mietvertrag:
        frappe.throw("Bitte einen Mietvertrag auswählen.")

    mv = frappe.db.get_value("Mietvertrag", mietvertrag, ["kunde", "wohnung"], as_dict=True) or {}
    customer = mv.get("kunde")
    wohnung = mv.get("wohnung")
    if not customer:
        frappe.throw("Kein Mieter im Mietvertrag hinterlegt.")

    company = _derive_company_from_mietvertrag(mietvertrag) or frappe.defaults.get_global_default("company")
    if not company:
        frappe.throw("Konnte keine Company ermitteln.")

    posting_date = getdate(kwargs.get("rechnungsdatum") or nowdate())
    due_date = getdate(kwargs.get("faellig_am") or (posting_date + timedelta(days=21)))

    rows = _parse_rows(kwargs.get("positionen"))
    if not rows:
        frappe.throw("Es sind keine Positionen erfasst.")

    default_item_code = ensure_default_service_item()
    default_cost_center = (
        _derive_cost_center_from_mietvertrag(mietvertrag)
        or frappe.db.get_value("Company", company, "cost_center")
    )
    if not default_cost_center:
        frappe.throw(
            "Konnte keine Kostenstelle ermitteln. Bitte an der Immobilie eine 'kostenstelle' pflegen "
            "(oder Company.cost_center setzen)."
        )
    default_income_account = frappe.db.get_value("Company", company, "default_income_account")

    items: list[dict] = []
    for idx, r in enumerate(rows, start=1):
        betrag = r.get("betrag")
        if betrag in (None, ""):
            frappe.throw(f"Position {idx}: Betrag fehlt.")

        item_code = r.get("artikel") or default_item_code
        desc = r.get("beschreibung") or kwargs.get("rechnungsname") or kwargs.get("referenz") or "Sonstige Leistung"

        item_row: dict[str, Any] = {
            "item_code": item_code,
            "item_name": item_code,
            "description": desc,
            "qty": 1,
            "rate": float(betrag),
            "cost_center": default_cost_center,
        }

        income_account = r.get("erloeskonto") or default_income_account
        if income_account:
            item_row["income_account"] = income_account
        elif not default_income_account:
            frappe.throw(
                f"Position {idx}: Bitte ein Erlöskonto angeben oder in der Company ein default_income_account pflegen."
            )

        items.append(item_row)

    si = frappe.new_doc("Sales Invoice")
    si.update({
        "company": company,
        "customer": customer,
        "posting_date": posting_date,
        "due_date": due_date,
        "ignore_default_payment_terms_template": 1,
        "remarks": f"Erfasst über Buchungs-Cockpit | Mietvertrag: {mietvertrag} | Referenz: {kwargs.get('referenz') or ''}",
    })
    si.set("payment_terms_template", None)
    si.set("payment_schedule", [])

    wertstellungsdatum = kwargs.get("wertstellungsdatum")
    if wertstellungsdatum and _has_field("Sales Invoice", "custom_wertstellungsdatum"):
        si.custom_wertstellungsdatum = getdate(wertstellungsdatum)

    if wohnung and _has_field("Sales Invoice", "wohnung"):
        si.set("wohnung", wohnung)
        if _has_field("Sales Invoice Item", "wohnung"):
            for it in items:
                it["wohnung"] = wohnung

    si.set("items", items)

    if _has_field("Sales Invoice", "hv_eingabequelle"):
        si.hv_eingabequelle = EINGABEQUELLE_AUSGANG

    si.insert(ignore_permissions=True)

    submit_doc_raw = kwargs.get("submit_doc", 1)
    submit_flag = (
        bool(int(submit_doc_raw))
        if isinstance(submit_doc_raw, str)
        else bool(submit_doc_raw)
    )
    if submit_flag:
        si.submit()
        frappe.msgprint(f"Rechnung {si.name} wurde erstellt und eingereicht.", alert=True)
    else:
        frappe.msgprint(f"Rechnung {si.name} wurde als Entwurf gespeichert.", alert=True)
    return {"name": si.name, "submitted": submit_flag}


# ---------------------------------------------------------------------------
# LLM-basierte Rechnungsextraktion
# ---------------------------------------------------------------------------


@frappe.whitelist()
def upload_invoice_pdf() -> dict:
    """Idempotenter Datei-Upload für den Cockpit + Duplicate-Status.

    Wird vom Frappe-FileUploader via ``method=...upload_invoice_pdf`` aufgerufen.
    Frappe's ``handler.upload_file`` liest die Datei schon vorher in
    ``frappe.local.uploaded_file`` und ``frappe.local.uploaded_filename`` —
    wir greifen darauf zu, NICHT auf ``frappe.request.files`` (Stream ist
    bereits konsumiert zu dem Zeitpunkt).

    Verhalten:
    - Berechnet den content_hash (SHA-1, identisch zur Frappe-Konvention).
    - Wenn die Datei bereits in tabFile liegt: existing file_url zurückgeben
      (kein Re-Upload — umgeht den Frappe-pypika-RecursionError beim Standard-Duplicate-Path).
    - Sucht zusätzlich Buchungs Vorschläge zu dieser file_url und liefert deren
      Status — das Frontend zeigt darauf basierend einen Duplicate-Dialog.
    """
    import hashlib

    from frappe.utils.file_manager import save_file

    # Frappe's Standard-save_file()-Pipeline hat einen Bug bei Binary-Files:
    # File.get_content() decoded die bytes via FILE_ENCODING_OPTIONS zu str
    # (utf-8/windows-1252), dann encoded write_file() das wieder als utf-8 —
    # was die binary PDF-Magic-Bytes (>=0x80) durch Doppel-Encoding zerstört.
    # Wir umgehen das, indem wir die Datei direkt auf disk schreiben und das
    # File-Doc nur mit Metadaten erzeugen (kein content-Field, kein get_content).
    files = getattr(frappe.request, "files", None) if frappe.request else None
    content: bytes | None = None
    if files and "file" in files:
        file_obj = files["file"]
        try:
            file_obj.stream.seek(0)
            content = file_obj.stream.read()
        except Exception:
            content = None
    if not content:
        content = getattr(frappe.local, "uploaded_file", None)
        if isinstance(content, str):
            content = content.encode("latin-1", errors="replace")

    filename = getattr(frappe.local, "uploaded_filename", None) or "upload.pdf"
    if not content:
        frappe.throw("Hochgeladene Datei ist leer.")
    content_hash = hashlib.sha1(content).hexdigest()

    existing_file = frappe.db.get_value(
        "File",
        {"content_hash": content_hash},
        ["name", "file_url", "file_name"],
        as_dict=True,
    )
    if existing_file:
        file_url = existing_file.file_url
        file_name = existing_file.file_name
        is_new_file = False
    else:
        # Direkt auf disk schreiben + minimales File-Doc — umgeht den
        # Frappe-Decode-Encode-Bug bei Binary-Files (siehe Kommentar oben).
        from frappe.core.doctype.file.utils import generate_file_name
        from frappe.utils.file_manager import get_files_path
        import os as _os

        target_dir = get_files_path(is_private=1)
        frappe.create_folder(target_dir)
        safe_name = generate_file_name(
            name=filename,
            suffix=content_hash[-6:],
            is_private=True,
        )
        full_path = _os.path.join(target_dir, safe_name)
        with open(full_path, "wb") as f:
            f.write(content)

        file_url = f"/private/files/{safe_name}"
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": safe_name,
            "file_url": file_url,
            "is_private": 1,
            "file_size": len(content),
            "content_hash": content_hash,
            "folder": "Home",
            # `flags.copy_from_existing_file` umgeht in before_insert das
            # save_file()/get_content()-Re-Encoding-Pattern. Wir haben die
            # Datei oben schon korrekt geschrieben.
        })
        file_doc.flags.copy_from_existing_file = True
        file_doc.flags.ignore_permissions = True
        file_doc.insert()
        file_name = file_doc.file_name
        is_new_file = True

    existing_vorschlag = _lookup_vorschlag_by_file_url(file_url)

    # `doctype: "File"` ist erforderlich, sonst verwirft Frappes FileUploader.vue:601
    # die Response und ruft on_success mit `null` auf.
    return {
        "doctype": "File",
        "file_url": file_url,
        "file_name": file_name,
        "is_new_file": is_new_file,
        "existing_vorschlag": existing_vorschlag,
    }


def _lookup_vorschlag_by_file_url(file_url: str) -> dict | None:
    """Findet den jüngsten Buchungs Vorschlag zu einer file_url (alle Status).

    Liefert {name, status, linked_purchase_invoice, session_id, original_filename}
    oder None.
    """
    if not file_url:
        return None
    rows = frappe.get_all(
        "Buchungs Vorschlag",
        filters={"file_url": file_url},
        fields=[
            "name",
            "status",
            "linked_purchase_invoice",
            "session_id",
            "original_filename",
        ],
        order_by="creation desc",
        limit_page_length=1,
    )
    return dict(rows[0]) if rows else None


@frappe.whitelist()
def extract_invoice_from_file(file_url: str) -> dict:
    """Liest ein hochgeladenes PDF und liefert Vorschläge zum Vorbefüllen des
    Eingangsrechnungs-Dialogs.

    Frontend ruft das nach dem Upload, vor dem Öffnen des PI-Dialogs.
    """
    from hausverwaltung.hausverwaltung.services.invoice_extraction import (
        extract_from_file_url,
    )
    from hausverwaltung.hausverwaltung.services.mistral_client import (
        MistralPermanentError,
        MistralTransientError,
    )

    if not (file_url or "").strip():
        frappe.throw("Bitte eine PDF-Datei hochladen.")
    try:
        return extract_from_file_url(file_url)
    except MistralPermanentError as exc:
        frappe.throw(str(exc))
    except MistralTransientError as exc:
        frappe.throw(
            f"Mistral-Aufruf fehlgeschlagen, bitte später erneut versuchen: {exc}"
        )


@frappe.whitelist()
def create_supplier_from_extraction(**kwargs) -> dict:
    """Legt einen neuen Lieferanten + ggf. Adresse aus den LLM-Vorschlagsdaten an.

    Aufrufer (Cockpit-JS) übergibt die im Quick-Create-Dialog ggf. korrigierten Werte.

    Expected kwargs:
        supplier_name: required
        supplier_group: required (Frontend liefert default)
        country: optional (default Deutschland)
        tax_id: optional
        iban: optional — wird ans Feld supplier_details als Notiz gehängt,
              da Bank-Account-Erstellung eine Bank-Doc voraussetzt.
        strasse, plz, ort: optional — ergeben einen Address-Doc, wenn alle drei da sind.
    """
    supplier_name = (kwargs.get("supplier_name") or "").strip()
    if not supplier_name:
        frappe.throw("Bitte einen Lieferantennamen angeben.")
    if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
        frappe.throw(f"Lieferant '{supplier_name}' existiert bereits.")
    supplier_group = (kwargs.get("supplier_group") or "").strip()
    if not supplier_group:
        frappe.throw("Bitte eine Lieferantengruppe wählen.")
    country = (kwargs.get("country") or "Germany").strip() or "Germany"
    country = _DE_COUNTRY_MAP.get(country, country)
    if not frappe.db.exists("Country", country):
        # Defensiver Fallback — wenn der Country-Name keiner gültigen Option entspricht,
        # auf den ERPNext-Standard "Germany" zurückfallen.
        country = "Germany"
    tax_id = (kwargs.get("tax_id") or "").strip()
    iban = (kwargs.get("iban") or "").strip()
    strasse = (kwargs.get("strasse") or "").strip()
    plz = (kwargs.get("plz") or "").strip()
    ort = (kwargs.get("ort") or "").strip()

    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = supplier_name
    supplier.supplier_group = supplier_group
    supplier.country = country
    if tax_id:
        supplier.tax_id = tax_id
    details_lines = []
    if iban:
        details_lines.append(f"IBAN: {iban}")
        details_lines.append("(Bitte über das Supplier-Formular einen Bank Account mit dieser IBAN anlegen.)")
    if details_lines:
        supplier.supplier_details = "\n".join(details_lines)
    supplier.insert(ignore_permissions=True)

    address_name: str | None = None
    if strasse and plz and ort:
        address = frappe.new_doc("Address")
        address.address_title = supplier.name
        address.address_type = "Billing"
        address.address_line1 = strasse
        address.pincode = plz
        address.city = ort
        address.country = country
        address.append(
            "links",
            {"link_doctype": "Supplier", "link_name": supplier.name},
        )
        address.insert(ignore_permissions=True)
        address_name = address.name
        # Frappe pflegt supplier_primary_address über einen Hook bei Adress-Save —
        # falls nicht greift, setzen wir's defensiv.
        try:
            frappe.db.set_value(
                "Supplier", supplier.name, "supplier_primary_address", address_name
            )
        except Exception:
            pass

    bank_account_name = _try_create_bank_account_for_supplier(supplier.name, iban)

    return {
        "name": supplier.name,
        "supplier_name": supplier.supplier_name,
        "address_name": address_name,
        "bank_account_name": bank_account_name,
        "iban_stored_as_note": bool(iban) and not bank_account_name,
    }


def _try_create_bank_account_for_supplier(
    supplier_name: str, iban: str
) -> str | None:
    """Versucht Bank + Bank Account aus IBAN zu erzeugen.

    Liefert den Bank-Account-Namen bei Erfolg oder None wenn:
    - keine IBAN
    - keine deutsche IBAN (nur DE-Lookup unterstützt)
    - BLZ nicht in der Lookup-Tabelle
    - Pflege-Fehler (defensiv: keine Exceptions, IBAN bleibt dann nur als Notiz)
    """
    from hausverwaltung.hausverwaltung.services.blz_lookup import lookup_iban

    if not iban:
        return None
    info = lookup_iban(iban)
    if not info:
        return None
    bank_name = info["bank_name"] or f"Bank {info['blz']}"
    try:
        bank_doc_name = _ensure_bank_doc(bank_name, info.get("bic") or "")
    except Exception:
        return None
    try:
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"{supplier_name} - {bank_name}"
        ba.bank = bank_doc_name
        ba.iban = iban
        kontonr = info.get("kontonummer") or ""
        if kontonr:
            ba.bank_account_no = kontonr
        ba.party_type = "Supplier"
        ba.party = supplier_name
        ba.is_company_account = 0
        ba.insert(ignore_permissions=True)
        # Auch als default_bank_account auf Supplier setzen.
        try:
            frappe.db.set_value(
                "Supplier", supplier_name, "default_bank_account", ba.name
            )
        except Exception:
            pass
        return ba.name
    except Exception:
        return None


def _ensure_bank_doc(bank_name: str, bic: str = "") -> str:
    """Get-or-create für Bank-DocType. Idempotent."""
    if frappe.db.exists("Bank", bank_name):
        return bank_name
    bank = frappe.new_doc("Bank")
    bank.bank_name = bank_name
    if bic:
        bank.swift_number = bic
    bank.insert(ignore_permissions=True)
    return bank.name


# ---------------------------------------------------------------------------
# Dashboard / cockpit lookups
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_defaults_from_mietvertrag(mietvertrag: str) -> dict:
    if not mietvertrag:
        return {}
    mv = frappe.db.get_value("Mietvertrag", mietvertrag, ["kunde", "wohnung"], as_dict=True) or {}
    return {
        "kunde": mv.get("kunde"),
        "wohnung": mv.get("wohnung"),
        "company": _derive_company_from_mietvertrag(mietvertrag),
    }


@frappe.whitelist()
def get_cockpit_overview(limit: int = 10) -> dict:
    """Data for the cockpit: recently created simplified invoices + active Abschlagszahlungen."""
    limit = max(1, min(int(limit or 10), 50))

    recent_pi: list[dict] = []
    recent_si: list[dict] = []
    if _has_field("Purchase Invoice", "hv_eingabequelle"):
        recent_pi = frappe.get_all(
            "Purchase Invoice",
            filters={"hv_eingabequelle": EINGABEQUELLE_EINGANG, "docstatus": ["<", 2]},
            fields=["name", "supplier", "grand_total", "posting_date", "docstatus"],
            order_by="posting_date desc, creation desc",
            limit_page_length=limit,
        )
    if _has_field("Sales Invoice", "hv_eingabequelle"):
        recent_si = frappe.get_all(
            "Sales Invoice",
            filters={"hv_eingabequelle": EINGABEQUELLE_AUSGANG, "docstatus": ["<", 2]},
            fields=["name", "customer", "grand_total", "posting_date", "docstatus"],
            order_by="posting_date desc, creation desc",
            limit_page_length=limit,
        )

    abschlaege = frappe.get_all(
        "Zahlungsplan",
        filters={"status": "Läuft"},
        fields=["name", "bezeichnung", "lieferant", "betrag"],
        order_by="modified desc",
        limit_page_length=limit,
    )

    return {
        "recent_purchase_invoices": recent_pi,
        "recent_sales_invoices": recent_si,
        "active_abschlagszahlungen": abschlaege,
    }
