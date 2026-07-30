"""Server endpoints for the Buchungs-Cockpit.

Replaces the intermediary DocTypes VereinfachteBuchung / VereinfachteMieterRechnung
by creating Purchase Invoice / Sales Invoice directly from the submitted tool dialog.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import cstr, flt, getdate, nowdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.gl_kosten_pro_haus import (
    _kostenstelle_zu_haus_map,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
    validate_wohnung_cost_center_pair,
)
from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
    _company_via_wohnung,
)
from hausverwaltung.hausverwaltung.utils.buchung import ensure_default_service_item
from hausverwaltung.hausverwaltung.utils.income_accounts import get_hv_income_accounts
from hausverwaltung.hausverwaltung.utils.rent_items import (
    MISC_TENANT_ITEM_CODE,
    ensure_rent_items,
)

EINGABEQUELLE_EINGANG = "Vereinfachte Buchung"
EINGABEQUELLE_AUSGANG = "Vereinfachte Mieterrechnung"
ZAHLUNGSSTATUS_SOFORT = "Sofort bezahlt/verrechnet"
ZAHLUNGSART_BANKIMPORT = "Überweisung / Bankimport"
ZAHLUNGSART_SOFORT = {
    "Barzahlung",
    "Vorschuss/Auslage",
    "Sonstige Verrechnung",
}

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


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja", "on"}
    return bool(value)


def _require_document_permissions(doctype: str, *, submit: bool = False) -> None:
    """Fail before any write when the caller may not create/submit a voucher."""
    if not frappe.has_permission(doctype, "create"):
        frappe.throw(
            f"Keine Berechtigung zum Anlegen von {doctype}.",
            frappe.PermissionError,
        )
    if submit and not frappe.has_permission(doctype, "submit"):
        frappe.throw(
            f"Keine Berechtigung zum Buchen von {doctype}.",
            frappe.PermissionError,
        )


def _lock_booking_proposal(vorschlag_name: str) -> dict:
    """Lock a proposal for the enclosing request transaction.

    A submitted linked invoice is treated as an idempotent retry. All other
    non-ready states are rejected instead of creating a second invoice.
    """
    if not frappe.has_permission("Buchungs Vorschlag", "read") or not frappe.has_permission(
        "Buchungs Vorschlag", "write"
    ):
        frappe.throw(
            "Keine Berechtigung zum Buchen dieses Buchungsvorschlags.",
            frappe.PermissionError,
        )

    proposal = frappe.db.get_value(
        "Buchungs Vorschlag",
        vorschlag_name,
        ["name", "status", "linked_purchase_invoice"],
        as_dict=True,
        for_update=True,
    )
    if not proposal:
        frappe.throw(f"Buchungsvorschlag '{vorschlag_name}' wurde nicht gefunden.")

    linked_invoice = proposal.get("linked_purchase_invoice")
    if proposal.get("status") == "Booked" and linked_invoice:
        docstatus = frappe.db.get_value("Purchase Invoice", linked_invoice, "docstatus")
        if int(docstatus or 0) == 1:
            return {
                "name": linked_invoice,
                "submitted": True,
                "settlement_journal_entry": None,
                "idempotent": True,
            }
        frappe.throw(
            f"Buchungsvorschlag '{vorschlag_name}' ist inkonsistent: "
            "Status 'Booked', aber keine gebuchte Eingangsrechnung ist verknüpft."
        )

    if proposal.get("status") != "Ready":
        frappe.throw(
            f"Buchungsvorschlag '{vorschlag_name}' kann im Status "
            f"'{proposal.get('status') or 'unbekannt'}' nicht gebucht werden."
        )
    return {}


def _link_locked_booking_proposal(vorschlag_name: str, pi_name: str) -> None:
    """Link a previously locked proposal without committing independently."""
    frappe.db.set_value(
        "Buchungs Vorschlag",
        vorschlag_name,
        {"status": "Booked", "linked_purchase_invoice": pi_name},
    )


def _has_field(doctype: str, fieldname: str) -> bool:
    # A genuinely absent optional field is harmless.  A metadata/database
    # failure is not: treating it as "field absent" could silently drop a
    # booking dimension such as Wohnung from a voucher.
    return bool(frappe.get_meta(doctype).get_field(fieldname))


def _normalize_sales_invoice_user_remark(raw: Any) -> str:
    remark = (cstr(raw) or "").strip()
    if not remark:
        return ""

    compact = " ".join(remark.split())
    if compact.startswith("Erfasst über Buchungs-Cockpit") and (
        "Mietvertrag:" in compact or "Referenz:" in compact
    ):
        return ""

    return remark


def _rent_item_for_income_account(
    income_account: str | None,
    income_accounts: dict[str, str],
) -> str:
    """Map configured rent income accounts to Mieterkonto-compatible items."""
    for item_code in ("Miete", "Betriebskosten", "Heizkosten", "Untermietzuschlag"):
        if income_account and income_account == income_accounts.get(item_code):
            return item_code
    return MISC_TENANT_ITEM_CODE


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


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def toplevel_kostenstelle_query(doctype, txt, searchfield, start, page_len, filters):
    """Custom Link-Query: liefert nur Cost Centers, die einer Top-Level-
    Immobilie (parent_immobilie leer) als ``kostenstelle`` zugeordnet sind.

    Sub-Immobilien (Gebäudeteile HH/VH/SF) werden ausgeblendet, damit Buchungen
    nur auf Gebäude-Ebene möglich sind. Wird im Buchungs-Cockpit und im
    Zahlungsplan-Formular für die Kostenstellen-Auswahl verwendet.
    """
    return frappe.db.sql(
        """
        SELECT DISTINCT i.kostenstelle
        FROM `tabImmobilie` i
        WHERE (i.parent_immobilie IS NULL OR i.parent_immobilie = '')
          AND i.kostenstelle IS NOT NULL
          AND i.kostenstelle != ''
          AND i.kostenstelle LIKE %(txt)s
        ORDER BY i.kostenstelle
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
                f"Konto „{row['konto']}“ ist weder als umlagefähige Kostenart noch als "
                f"Kostenart nicht umlagefaehig hinterlegt. Bitte zuerst ein Stammdatum "
                f"anlegen, das dieses Konto referenziert."
            )
        doctype = match["doctype"]
        name = match["name"]

    if not (doctype and name):
        return None
    allowed_doctypes = {
        "Betriebskostenart",
        "Kostenart nicht umlagefaehig",
    }
    if doctype not in allowed_doctypes:
        frappe.throw(
            f"Ungültiger Kostenart-Typ '{doctype}'. Bitte die Kostenart erneut auswählen."
        )

    fields = ["name", "konto", "artikel"]
    if doctype == "Betriebskostenart":
        fields.append("verteilung")
    vals = frappe.db.get_value(
        doctype,
        name,
        fields,
        as_dict=True,
        for_update=True,
    ) or {}
    if not vals.get("name"):
        frappe.throw(
            f"Kostenart-Stammdatum '{name}' ({doctype}) wurde nicht gefunden "
            "oder inzwischen gelöscht. Buchung abgebrochen."
        )
    if not cstr(vals.get("konto")).strip():
        frappe.throw(
            f"Kostenart '{name}' ({doctype}) hat kein Aufwandskonto. "
            "Buchung abgebrochen."
        )
    if not cstr(vals.get("artikel")).strip():
        frappe.throw(
            f"Kostenart '{name}' ({doctype}) hat keinen Artikel. "
            "Buchung abgebrochen."
        )

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
        values = frappe.db.get_value(
            "Betriebskostenart",
            bk,
            ["name", "verteilung"],
            as_dict=True,
            for_update=True,
        ) or {}
        if not values.get("name"):
            frappe.throw(
                f"Umlagefähige Kostenart '{bk}' wurde nicht gefunden oder "
                "inzwischen gelöscht. Buchung abgebrochen."
            )
        cache[bk] = values.get("verteilung") or ""
    return cstr(cache.get(bk) or "").lower() == "einzeln"


def _get_payable_account(*, company: str, supplier: str) -> str:
    """Resolve one authoritative, current Payable account.

    The Company fallback is used only when the Supplier schema verifiably has no
    default field or that field is verifiably empty. A configured but broken
    Supplier account, metadata failure, or database failure must abort instead
    of silently posting to another account.
    """
    supplier_meta = frappe.get_meta("Supplier")
    supplier_default = None
    if supplier_meta.has_field("default_payable_account"):
        supplier_default = cstr(
            frappe.db.get_value(
                "Supplier",
                supplier,
                "default_payable_account",
            )
            or ""
        ).strip()

    account_source = f"Lieferant '{supplier}'"
    account = supplier_default
    if not account:
        account_source = f"Company '{company}'"
        account = cstr(
            frappe.db.get_value(
                "Company",
                company,
                "default_payable_account",
            )
            or ""
        ).strip()
    if not account:
        frappe.throw(
            "Kein Kreditorenkonto (Payable Account) gefunden. Bitte beim "
            "Lieferanten oder in der Company ein 'Default Payable Account' pflegen."
        )

    values = frappe.db.get_value(
        "Account",
        account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
        for_update=True,
    ) or {}
    if not values.get("name"):
        frappe.throw(
            f"Das in {account_source} konfigurierte Kreditorenkonto "
            f"'{account}' wurde nicht gefunden."
        )
    if cstr(values.get("company")).strip() != company:
        frappe.throw(
            f"Das Kreditorenkonto '{account}' aus {account_source} gehört "
            f"nicht zur Company '{company}'."
        )
    if flt(values.get("is_group")) or flt(values.get("disabled")):
        frappe.throw(
            f"Das Kreditorenkonto '{account}' aus {account_source} ist nicht "
            "aktiv bebuchbar."
        )
    if values.get("account_type") != "Payable":
        frappe.throw(
            f"Das Konto '{account}' aus {account_source} ist kein "
            "Kreditorenkonto (Account Type Payable)."
        )

    company_currency = cstr(
        frappe.db.get_value("Company", company, "default_currency") or ""
    ).strip()
    if not company_currency:
        frappe.throw(f"An der Company '{company}' fehlt die Standardwährung.")
    account_currency = cstr(values.get("account_currency")).strip()
    if account_currency != company_currency:
        frappe.throw(
            f"Das Kreditorenkonto '{account}' hat Währung "
            f"'{account_currency or 'nicht gesetzt'}', erwartet ist "
            f"'{company_currency}'. Fremdwährungsbuchung abgebrochen."
        )
    return account


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


def _validate_cost_center_company(
    cost_center: str,
    company: str,
    *,
    context: str | None = None,
    for_update: bool = False,
) -> None:
    """Require a concrete, non-group Cost Center of the booking company."""
    label = f"{context}: " if context else ""
    values = frappe.db.get_value(
        "Cost Center",
        cost_center,
        ["name", "company", "is_group", "disabled"],
        as_dict=True,
        for_update=for_update,
    ) or {}
    if not values.get("name"):
        frappe.throw(f"{label}Kostenstelle '{cost_center}' wurde nicht gefunden.")
    if flt(values.get("is_group")):
        frappe.throw(
            f"{label}Kostenstelle '{cost_center}' ist eine Gruppe und kann nicht "
            "bebucht werden."
        )
    if flt(values.get("disabled")):
        frappe.throw(
            f"{label}Kostenstelle '{cost_center}' ist deaktiviert und kann nicht "
            "bebucht werden."
        )
    cost_center_company = cstr(values.get("company")).strip()
    if not cost_center_company:
        frappe.throw(
            f"{label}Kostenstelle '{cost_center}' hat keine Company. "
            "Buchung abgebrochen."
        )
    if cost_center_company != company:
        frappe.throw(
            f"{label}Kostenstelle '{cost_center}' gehört zur Company "
            f"'{cost_center_company}', der Beleg aber zur Company '{company}'. "
            "Buchung abgebrochen."
        )


def _validate_expense_account_company(
    account: str,
    company: str,
    company_currency: str,
    *,
    context: str | None = None,
) -> None:
    """Lock and validate an expense/capital account before PI insertion."""
    label = f"{context}: " if context else ""
    values = frappe.db.get_value(
        "Account",
        account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
        for_update=True,
    ) or {}
    if not values.get("name"):
        frappe.throw(f"{label}Konto '{account}' wurde nicht gefunden.")
    if cstr(values.get("company")).strip() != company:
        frappe.throw(
            f"{label}Konto '{account}' gehört nicht zur Company '{company}'."
        )
    if flt(values.get("is_group")) or flt(values.get("disabled")):
        frappe.throw(
            f"{label}Konto '{account}' ist nicht aktiv bebuchbar."
        )
    if values.get("account_type") in {"Receivable", "Payable"}:
        frappe.throw(
            f"{label}Konto '{account}' ist ein Debitoren-/Kreditorenkonto und "
            "kein zulässiges Positionskonto."
        )
    account_currency = cstr(values.get("account_currency")).strip()
    if account_currency != company_currency:
        frappe.throw(
            f"{label}Konto '{account}' hat Währung "
            f"'{account_currency or 'nicht gesetzt'}', erwartet ist "
            f"'{company_currency}'. Fremdwährungsbuchung abgebrochen."
        )


def _resolve_property_booking_identity(
    wohnung: str,
    *,
    selected_cost_center: str | None = None,
    expected_company: str | None = None,
    cost_center_to_immobilie: dict[str, str] | None = None,
    context: str | None = None,
) -> dict:
    """Resolve and lock Wohnung -> Immobilie -> Cost Center -> Company.

    Property-bound vouchers must never inherit a user/global Company or a
    Company default Cost Center.  Missing or conflicting property finance
    master data therefore aborts before an invoice is inserted.
    """
    label = f"{context}: " if context else ""
    wohnung = cstr(wohnung).strip()
    if not wohnung:
        frappe.throw(f"{label}Wohnung fehlt.")

    wohnung_values = frappe.db.get_value(
        "Wohnung",
        wohnung,
        ["name", "immobilie"],
        as_dict=True,
        for_update=True,
    ) or {}
    immobilie = cstr(wohnung_values.get("immobilie")).strip()
    if not wohnung_values.get("name") or not immobilie:
        frappe.throw(
            f"{label}Wohnung '{wohnung}' wurde nicht gefunden oder hat keine "
            "Immobilie. Buchung abgebrochen."
        )

    immobilie_values = frappe.db.get_value(
        "Immobilie",
        immobilie,
        ["name", "kostenstelle"],
        as_dict=True,
        for_update=True,
    ) or {}
    property_cost_center = cstr(immobilie_values.get("kostenstelle")).strip()
    if not immobilie_values.get("name") or not property_cost_center:
        frappe.throw(
            f"{label}An der Immobilie '{immobilie}' der Wohnung '{wohnung}' "
            "ist keine Kostenstelle gepflegt. Buchung abgebrochen."
        )

    company = _company_via_wohnung(wohnung, for_update=True)
    if not company:
        frappe.throw(
            f"{label}Für Wohnung '{wohnung}' konnte aus den gesperrten "
            "Immobilien-Finanzdaten keine eindeutige Company ermittelt werden. "
            "Buchung abgebrochen."
        )
    if expected_company and company != expected_company:
        frappe.throw(
            f"{label}Wohnung '{wohnung}' gehört zur Company '{company}', "
            f"der Beleg aber zur Company '{expected_company}'. "
            "Buchung abgebrochen."
        )

    cost_center = cstr(selected_cost_center).strip() or property_cost_center
    cc_map = (
        cost_center_to_immobilie
        if cost_center_to_immobilie is not None
        else _kostenstelle_zu_haus_map()
    )
    canonical_immobilie = validate_wohnung_cost_center_pair(
        wohnung,
        cost_center,
        cost_center_to_immobilie=cc_map,
        wohnung_to_immobilie={wohnung: immobilie},
        context=context,
    )
    _validate_cost_center_company(
        cost_center,
        company,
        context=context,
        for_update=True,
    )
    return {
        "wohnung": wohnung,
        "immobilie": immobilie,
        "canonical_immobilie": canonical_immobilie,
        "property_cost_center": property_cost_center,
        "cost_center": cost_center,
        "company": company,
    }


def _lock_mietvertrag_booking_identity(
    mietvertrag: str,
    *,
    cost_center_to_immobilie: dict[str, str] | None = None,
) -> dict:
    """Lock and validate the single Customer/property identity of a contract."""
    mv = frappe.db.get_value(
        "Mietvertrag",
        mietvertrag,
        ["name", "kunde", "wohnung"],
        as_dict=True,
        for_update=True,
    ) or {}
    if not mv.get("name"):
        frappe.throw(f"Mietvertrag '{mietvertrag}' wurde nicht gefunden.")

    customer = cstr(mv.get("kunde")).strip()
    wohnung = cstr(mv.get("wohnung")).strip()
    if not customer:
        frappe.throw(
            f"Mietvertrag '{mietvertrag}' hat keinen eindeutigen Kunden. "
            "Buchung abgebrochen."
        )
    if not wohnung:
        frappe.throw(
            f"Mietvertrag '{mietvertrag}' hat keine Wohnung. "
            "Buchung abgebrochen."
        )

    identity = _resolve_property_booking_identity(
        wohnung,
        cost_center_to_immobilie=cost_center_to_immobilie,
        context=f"Mietvertrag {mietvertrag}",
    )
    identity.update({"mietvertrag": mietvertrag, "customer": customer})
    return identity


def _validate_settlement_account(
    account: str,
    *,
    company: str,
    payable_account: str,
    zahlungsart: str | None = None,
) -> None:
    if not account:
        frappe.throw("Bitte ein Zahlungs-/Verrechnungskonto auswählen.")
    if account == payable_account:
        frappe.throw("Zahlungs-/Verrechnungskonto darf nicht dem Kreditorenkonto entsprechen.")
    if not frappe.db.exists("Account", account):
        frappe.throw(f"Konto '{account}' existiert nicht.")

    values = frappe.db.get_value(
        "Account",
        account,
        ["company", "is_group", "account_type", "root_type"],
        as_dict=True,
    ) or {}
    if values.get("company") and values.get("company") != company:
        frappe.throw(
            f"Konto '{account}' gehört nicht zur Company '{company}'."
        )
    if flt(values.get("is_group")):
        frappe.throw(f"Konto '{account}' ist eine Gruppe und kann nicht bebucht werden.")
    if values.get("account_type") in {"Receivable", "Payable"}:
        frappe.throw(
            "Bitte ein Sachkonto für Kreditkarte/Kasse/Vorschuss wählen, "
            "kein Debitoren-/Kreditorenkonto."
        )
    if (zahlungsart or "").strip() == "Barzahlung" and values.get("account_type") != "Cash":
        frappe.throw("Bei Barzahlung bitte ein Kassenkonto wählen.")
    if values.get("root_type") in {"Income", "Expense"}:
        frappe.throw(
            "Bitte ein Bilanzkonto für Kreditkarte/Kasse/Vorschuss wählen, "
            "kein Ertrags- oder Aufwandskonto."
        )


def _create_purchase_invoice_settlement_journal(
    pi,
    *,
    settlement_account: str,
    posting_date,
    wertstellungsdatum=None,
    zahlungsart: str | None = None,
    remarks: str | None = None,
) -> str:
    """Gleicht eine gebuchte Eingangsrechnung gegen ein Zahlungs-/Clearingkonto aus.

    Genutzt für kleine Ausgaben aus dem Cockpit: Kreditkarte, Kasse, Vorschuss
    Hauswart oder ähnliche Konten. Wir verwenden bewusst einen Journal Entry,
    weil diese Konten nicht zwingend ERPNext-Bankkonten sein müssen.
    """
    amount = (
        flt(pi.get("outstanding_amount"))
        or flt(pi.get("rounded_total"))
        or flt(pi.get("grand_total"))
    )
    if amount <= 0:
        frappe.throw("Die Eingangsrechnung hat keinen offenen Betrag zum Ausgleichen.")

    payable_account = pi.get("credit_to")
    _validate_settlement_account(
        settlement_account,
        company=pi.company,
        payable_account=payable_account,
        zahlungsart=zahlungsart,
    )
    company_currency = frappe.db.get_value("Company", pi.company, "default_currency")
    payable_currency = frappe.db.get_value("Account", payable_account, "account_currency")
    settlement_currency = frappe.db.get_value("Account", settlement_account, "account_currency")
    currencies = {
        currency
        for currency in (company_currency, payable_currency, settlement_currency)
        if currency
    }
    if len(currencies) > 1:
        frappe.throw(
            "Sofortausgleich in Fremdwährung wird im Buchungs-Cockpit nicht unterstützt. "
            "Bitte die Rechnung offen buchen und über einen Payment Entry bezahlen."
        )

    user_remark = (remarks or "").strip() or f"Ausgleich Eingangsrechnung {pi.name}"

    je = frappe.new_doc("Journal Entry")
    je.update({
        "voucher_type": "Journal Entry",
        "company": pi.company,
        "posting_date": getdate(posting_date),
        "user_remark": user_remark,
        "remark": user_remark,
        "custom_remark": 1,
    })
    if wertstellungsdatum and _has_field("Journal Entry", "custom_wertstellungsdatum"):
        je.custom_wertstellungsdatum = getdate(wertstellungsdatum)

    je.append("accounts", {
        "account": payable_account,
        "party_type": "Supplier",
        "party": pi.supplier,
        "reference_type": "Purchase Invoice",
        "reference_name": pi.name,
        "debit_in_account_currency": amount,
    })
    je.append("accounts", {
        "account": settlement_account,
        "credit_in_account_currency": amount,
    })

    je.insert()
    je.submit()
    return je.name


def _should_settle_purchase_invoice_now(kwargs: dict) -> bool:
    """Backwards-compatible immediate-settlement switch for cockpit expenses."""
    if "zahlung_sofort" in kwargs:
        raw = kwargs.get("zahlung_sofort")
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "ja", "on"}
        return bool(raw)

    zahlungsart = (kwargs.get("zahlungsart") or "").strip()
    if zahlungsart:
        return zahlungsart in ZAHLUNGSART_SOFORT
    return (kwargs.get("zahlungsstatus") or "") == ZAHLUNGSSTATUS_SOFORT


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
        zahlungsart: "Überweisung / Bankimport" | "Barzahlung" | "Kreditkarte" | ...
        zahlung_sofort: 1/0, ob direkt gegen zahlungskonto ausgeglichen werden soll
        zahlungsstatus: legacy fallback, "offen" | "Sofort bezahlt/verrechnet"
        zahlungskonto: GL Account für sofortige Zahlung/Verrechnung (optional)
        zahlungsbemerkung: optionale Bemerkung für den Ausgleichs-Journal-Entry
        positionen: list of dicts with keys
            betrag, konto, kostenstelle, umlagefaehig, kostenart, wohnung (optional)
    """
    submit_flag = _as_bool(kwargs.get("submit_doc", 1))
    vorschlag_name = (kwargs.get("vorschlag_name") or "").strip()
    if vorschlag_name and not submit_flag:
        frappe.throw(
            "Ein Buchungsvorschlag kann nicht als Entwurf gespeichert werden. "
            "Bitte den Vorschlag buchen oder den Dialog ohne Vorschlag öffnen."
        )

    settle_now = submit_flag and _should_settle_purchase_invoice_now(kwargs)
    _require_document_permissions("Purchase Invoice", submit=submit_flag)
    if settle_now:
        _require_document_permissions("Journal Entry", submit=True)

    idempotent_result = _lock_booking_proposal(vorschlag_name) if vorschlag_name else {}
    if idempotent_result:
        return idempotent_result

    supplier = kwargs.get("lieferant")
    if not supplier:
        frappe.throw("Bitte einen Lieferanten auswählen.")

    rows = _parse_rows(kwargs.get("positionen"))
    if not rows:
        frappe.throw("Es sind keine Positionen erfasst.")
    for idx, row in enumerate(rows, start=1):
        if row.get("betrag") in (None, ""):
            frappe.throw(f"Position {idx}: Betrag fehlt.")

    wohnung_rows = [
        (idx, row)
        for idx, row in enumerate(rows, start=1)
        if cstr(row.get("wohnung")).strip()
    ]
    cost_center_to_immobilie: dict[str, str] | None = None
    property_identities: dict[int, dict] = {}
    company: str | None = None
    if wohnung_rows:
        cost_center_to_immobilie = _kostenstelle_zu_haus_map()
        for idx, row in wohnung_rows:
            identity = _resolve_property_booking_identity(
                row.get("wohnung"),
                selected_cost_center=row.get("kostenstelle"),
                expected_company=company,
                cost_center_to_immobilie=cost_center_to_immobilie,
                context=f"Position {idx}",
            )
            company = company or identity["company"]
            property_identities[idx] = identity
    else:
        company = _derive_company_from_rows(rows)

    if not company:
        frappe.throw(
            "Konnte keine Company ermitteln. Bitte in mindestens einer Position "
            "eine Kostenstelle angeben."
        )

    first_cost_center = next(
        (cstr(r.get("kostenstelle")).strip() for r in rows if r.get("kostenstelle")),
        None,
    )
    company_default_cost_center: str | None = None
    effective_cost_centers: dict[int, str] = {}
    for idx, row in enumerate(rows, start=1):
        property_identity = property_identities.get(idx)
        if property_identity:
            cost_center = property_identity["cost_center"]
        else:
            cost_center = cstr(row.get("kostenstelle")).strip() or first_cost_center
            if not cost_center:
                if company_default_cost_center is None:
                    company_default_cost_center = frappe.get_cached_value(
                        "Company", company, "cost_center"
                    )
                cost_center = company_default_cost_center
        if not cost_center:
            frappe.throw(f"Position {idx}: Bitte eine Kostenstelle wählen.")
        _validate_cost_center_company(
            cost_center,
            company,
            context=f"Position {idx}",
            for_update=True,
        )
        effective_cost_centers[idx] = cost_center

    posting_date = kwargs.get("rechnungsdatum") or nowdate()
    bill_no = kwargs.get("rechnungsname")

    service_item_code = ensure_default_service_item()

    pi = frappe.new_doc("Purchase Invoice")
    user_remarks = (kwargs.get("remarks") or "").strip()
    pi.update({
        "company": company,
        "supplier": supplier,
        "posting_date": posting_date,
        "bill_date": posting_date,
        "bill_no": bill_no,
        "remarks": user_remarks,
    })

    payable_account = _get_payable_account(company=company, supplier=supplier)
    pi.credit_to = payable_account

    company_currency = frappe.db.get_value("Company", company, "default_currency")
    payable_currency = frappe.db.get_value("Account", payable_account, "account_currency")
    if not company_currency:
        frappe.throw(f"An der Company '{company}' fehlt die Standardwährung.")
    if payable_currency and payable_currency != company_currency:
        frappe.throw(
            f"Das Kreditorenkonto '{payable_account}' wird in {payable_currency} geführt. "
            "Fremdwährungsrechnungen bitte im regulären Purchase-Invoice-Formular "
            "mit geprüftem Wechselkurs erfassen."
        )
    pi.currency = company_currency
    pi.conversion_rate = 1

    items: list[dict] = []
    verteilung_cache: dict[str, str] = {}
    wohnung_to_immobilie: dict[str, str | None] = {}

    for idx, row in enumerate(rows, start=1):
        betrag = row.get("betrag")

        kostenart_info = _get_kostenart_details(row)
        if kostenart_info:
            # A selected Kostenart is authoritative. Never fall back to a
            # request-row or Company account after its master-data lookup.
            expense_account = kostenart_info.get("konto")
            if row.get("umlagefaehig") == "Betriebskostenart":
                verteilung_cache[row.get("kostenart")] = (
                    kostenart_info.get("verteilung") or ""
                )
        else:
            expense_account = row.get("konto")
        if not expense_account:
            expense_account = frappe.get_cached_value("Company", company, "default_expense_account")
            if not expense_account:
                frappe.throw(
                    f"Position {idx}: Bitte ein Aufwandskonto wählen "
                    "(in der Kostenart oder direkt in der Position)."
                )
        _validate_expense_account_company(
            expense_account,
            company,
            company_currency,
            context=f"Position {idx}",
        )

        cost_center = effective_cost_centers[idx]

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
                    f"Position {idx}: Umlagefähige Kostenart '{row.get('kostenart')}' ist auf 'Einzeln' "
                    "verteilt — bitte eine Wohnung auswählen."
                )
            if not _has_field("Purchase Invoice Item", "wohnung"):
                frappe.throw(
                    "Accounting Dimension 'Wohnung' ist nicht verfügbar (Feld 'wohnung' fehlt auf Purchase Invoice Item)."
                )
        if row.get("wohnung"):
            if cost_center_to_immobilie is None:
                cost_center_to_immobilie = _kostenstelle_zu_haus_map()
            validate_wohnung_cost_center_pair(
                row.get("wohnung"),
                cost_center,
                cost_center_to_immobilie=cost_center_to_immobilie,
                wohnung_to_immobilie=wohnung_to_immobilie,
                context=f"Position {idx}",
            )
            if _has_field("Purchase Invoice Item", "wohnung"):
                item_row["wohnung"] = row.get("wohnung")

        items.append(item_row)

    pi.set("items", items)

    wertstellungsdatum = kwargs.get("wertstellungsdatum")
    if wertstellungsdatum and _has_field("Purchase Invoice", "custom_wertstellungsdatum"):
        pi.custom_wertstellungsdatum = getdate(wertstellungsdatum)

    if _has_field("Purchase Invoice", "hv_eingabequelle"):
        pi.hv_eingabequelle = EINGABEQUELLE_EINGANG

    pi.insert()

    _attach_source_file(pi, kwargs.get("attached_file_url"))

    settlement_journal = None
    if submit_flag:
        pi.submit()
        if settle_now:
            settlement_journal = _create_purchase_invoice_settlement_journal(
                pi,
                settlement_account=kwargs.get("zahlungskonto"),
                posting_date=posting_date,
                wertstellungsdatum=wertstellungsdatum,
                zahlungsart=kwargs.get("zahlungsart"),
                remarks=kwargs.get("zahlungsbemerkung") or user_remarks,
            )
        if vorschlag_name:
            _link_locked_booking_proposal(vorschlag_name, pi.name)
        frappe.msgprint(
            f"Eingangsrechnung {pi.name} wurde erstellt und eingereicht.", alert=True
        )
    else:
        frappe.msgprint(
            f"Eingangsrechnung {pi.name} wurde als Entwurf gespeichert.", alert=True
        )
    return {
        "name": pi.name,
        "submitted": submit_flag,
        "settlement_journal_entry": settlement_journal,
    }


def _attach_source_file(pi, file_url: str | None) -> None:
    """Hängt das Quell-PDF aus der LLM-Extraktion an die Purchase Invoice an.

    Wir legen NICHT die Datei neu auf disk (würde Frappe's File.get_content() +
    save_file() durchlaufen — beides hat denselben Binary-Encoding-Bug, den
    upload_invoice_pdf umgeht). Stattdessen erzeugen wir nur einen weiteren
    File-Doc-Record, der auf die existierende file_url zeigt und die
    Attach-Verknüpfung zur PI trägt. Disk bleibt unangetastet, kein Mojibake.
    """
    if not file_url:
        return
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        return
    src = frappe.get_doc("File", file_name)
    attach = frappe.get_doc({
        "doctype": "File",
        "file_name": src.file_name,
        "file_url": src.file_url,
        "is_private": src.is_private,
        "file_size": src.file_size,
        "content_hash": src.content_hash,
        "folder": "Home/Attachments",
        "attached_to_doctype": "Purchase Invoice",
        "attached_to_name": pi.name,
    })
    # `copy_from_existing_file` skippt before_insert das save_file/get_content-
    # Re-Encoding-Pattern (siehe upload_invoice_pdf für Hintergrund).
    attach.flags.copy_from_existing_file = True
    attach.flags.ignore_permissions = True
    attach.insert()


@frappe.whitelist()
def save_vorlage_from_cockpit(**kwargs) -> dict:
    """Persistiert den aktuellen Cockpit-Dialog-State als Eingangsrechnung Vorlage.

    Erwartete kwargs (vom Cockpit-Dialog):
        titel: Pflicht — eindeutiger Vorlagentitel
        lieferant: Supplier (Pflicht)
        eingabemodus: "Kostenart" | "Konto"
        remarks: Standard-Anmerkungen (optional)
        positionen: Liste mit Dialog-Row-Dicts (kostenart, typ, kostenstelle, konto, wohnung, betrag)
    """
    titel = (kwargs.get("titel") or "").strip()
    if not titel:
        frappe.throw("Bitte einen Titel für die Vorlage angeben.")

    lieferant = kwargs.get("lieferant")
    if not lieferant:
        frappe.throw("Bitte einen Lieferanten auswählen.")

    rows = _parse_rows(kwargs.get("positionen"))
    if not rows:
        frappe.throw("Es sind keine Positionen erfasst.")

    doc = frappe.new_doc("Eingangsrechnung Vorlage")
    doc.update({
        "titel": titel,
        "lieferant": lieferant,
        "eingabemodus": kwargs.get("eingabemodus") or "Kostenart",
        "standard_remarks": (kwargs.get("remarks") or "").strip() or None,
    })

    for idx, row in enumerate(rows, start=1):
        typ = "nicht umlegbar" if row.get("typ") == "nicht umlegbar" else "umlegbar"
        bk_name: str | None = None
        nul_name: str | None = None

        row_konto = (row.get("konto") or "").strip() or None
        raw_kostenart = (row.get("kostenart") or "").strip()
        if raw_kostenart:
            info = _resolve_kostenart_name(raw_kostenart)
            if info:
                dt, name = info
                if dt == "Betriebskostenart":
                    bk_name = name
                else:
                    nul_name = name
            else:
                konto_match = _find_kostenart_for_konto(raw_kostenart)
                if konto_match:
                    row_konto = raw_kostenart
                    if konto_match["doctype"] == "Betriebskostenart":
                        bk_name = konto_match["name"]
                    else:
                        nul_name = konto_match["name"]
                else:
                    frappe.throw(
                        f"Position {idx}: Kostenart '{raw_kostenart}' konnte nicht aufgelöst werden."
                    )
        else:
            # Legacy-Picker (verstecktes Link-Feld) als Fallback
            bk_name = row.get("betriebskostenart") or None
            nul_name = row.get("kostenart_nicht_ul") or None

        if typ == "umlegbar" and not bk_name:
            frappe.throw(
                f"Position {idx}: Für 'umlegbar' wird eine umlagefähige Kostenart benötigt."
            )
        if typ == "nicht umlegbar" and not nul_name:
            frappe.throw(
                f"Position {idx}: Für 'nicht umlegbar' wird eine Kostenart (nicht umlegbar) benötigt."
            )

        # Defensive: konsistenten Zustand herstellen — die andere Seite muss leer sein,
        # damit der validate-Hook im Parent nicht throwt.
        if typ == "umlegbar":
            nul_name = None
        else:
            bk_name = None

        try:
            betrag_default = float(row.get("betrag") or 0) or None
        except (TypeError, ValueError):
            betrag_default = None

        doc.append("positionen", {
            "typ": typ,
            "betriebskostenart": bk_name,
            "kostenart_nicht_ul": nul_name,
            "kostenstelle": row.get("kostenstelle"),
            "konto": row_konto,
            "wohnung": row.get("wohnung") or None,
            "betrag_default": betrag_default,
        })

    doc.insert()
    return {"name": doc.name, "titel": doc.titel}


@frappe.whitelist()
def load_vorlage_for_cockpit(name: str) -> dict:
    """Liefert eine Eingangsrechnung Vorlage in Cockpit-Dialog-Form.

    Konvertiert die persistierte Struktur zurück in die Felder, die der Dialog
    (open_eingangsrechnung_dialog) erwartet — insbesondere wird der
    `kostenart`-Autocomplete-String aus dem passenden Link-Feld rekonstruiert.
    """
    if not name:
        frappe.throw("Vorlage-Name fehlt.")

    doc = frappe.get_doc("Eingangsrechnung Vorlage", name)
    if doc.get("disabled"):
        frappe.throw(f"Vorlage '{name}' ist deaktiviert.")

    positionen: list[dict] = []
    konto_mode = (doc.eingabemodus or "Kostenart") == "Konto"
    for row in doc.get("positionen") or []:
        typ = row.get("typ") or "umlegbar"
        if konto_mode and row.get("konto"):
            kostenart = row.get("konto") or ""
        elif typ == "umlegbar":
            kostenart = row.get("betriebskostenart") or ""
        else:
            kostenart = row.get("kostenart_nicht_ul") or ""

        positionen.append({
            "typ": typ,
            "kostenart": kostenart,
            "betriebskostenart": row.get("betriebskostenart") or "",
            "kostenart_nicht_ul": row.get("kostenart_nicht_ul") or "",
            "kostenstelle": row.get("kostenstelle") or "",
            "konto": row.get("konto") or "",
            "wohnung": row.get("wohnung") or "",
            "betrag": float(row.get("betrag_default") or 0) or None,
        })

    return {
        "name": doc.name,
        "titel": doc.titel,
        "lieferant": doc.lieferant,
        "eingabemodus": doc.eingabemodus or "Kostenart",
        "remarks": doc.standard_remarks or "",
        "positionen": positionen,
    }


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
        bemerkung: optionale freie Bemerkung — landet in si.remarks. Wenn leer,
            werden standardmäßig die Positions-Beschreibungen übernommen.
        positionen: list of dicts with keys
            beschreibung, betrag, artikel, erloeskonto
    """
    submit_flag = _as_bool(kwargs.get("submit_doc", 1))
    _require_document_permissions("Sales Invoice", submit=submit_flag)

    mietvertrag = kwargs.get("mietvertrag")
    if not mietvertrag:
        frappe.throw("Bitte einen Mietvertrag auswählen.")

    cost_center_to_immobilie = _kostenstelle_zu_haus_map()
    booking_identity = _lock_mietvertrag_booking_identity(
        mietvertrag,
        cost_center_to_immobilie=cost_center_to_immobilie,
    )
    customer = booking_identity["customer"]
    wohnung = booking_identity["wohnung"]
    company = booking_identity["company"]
    default_cost_center = booking_identity["cost_center"]

    posting_date = getdate(kwargs.get("rechnungsdatum") or nowdate())
    due_date = getdate(kwargs.get("faellig_am") or (posting_date + timedelta(days=21)))

    rows = _parse_rows(kwargs.get("positionen"))
    if not rows:
        frappe.throw("Es sind keine Positionen erfasst.")

    amounts: list[float] = []
    for idx, row in enumerate(rows, start=1):
        raw_amount = row.get("betrag")
        if raw_amount in (None, ""):
            frappe.throw(f"Position {idx}: Betrag fehlt.")
        amounts.append(flt(raw_amount))

    has_positive_amount = any(amount > 0 for amount in amounts)
    has_negative_amount = any(amount < 0 for amount in amounts)
    if has_positive_amount and has_negative_amount:
        frappe.throw(
            "Positive Forderungen und negative Guthaben können nicht in derselben Sollstellung "
            "gebucht werden. Bitte dafür zwei getrennte Belege erfassen."
        )
    is_credit_note = has_negative_amount

    ensure_rent_items(company=company)
    hv_income_accounts = get_hv_income_accounts(company)
    default_income_account = frappe.db.get_value("Company", company, "default_income_account")

    items: list[dict] = []
    position_descriptions: list[str] = []
    for idx, (r, amount) in enumerate(zip(rows, amounts), start=1):

        income_account = r.get("erloeskonto") or default_income_account
        item_code = r.get("artikel") or _rent_item_for_income_account(
            income_account,
            hv_income_accounts,
        )
        beschreibung = (r.get("beschreibung") or "").strip()
        desc = beschreibung or kwargs.get("rechnungsname") or kwargs.get("referenz") or "Sonstige Leistung"
        if beschreibung:
            position_descriptions.append(beschreibung)

        item_row: dict[str, Any] = {
            "item_code": item_code,
            "item_name": item_code,
            "description": desc,
            # ERPNext bildet eine Gutschrift als Return mit negativer Menge
            # und positivem Preis ab. Der Cockpit-Nutzer gibt das Guthaben
            # intuitiv als negativen Betrag ein; hier erfolgt die Umwandlung.
            "qty": -1 if is_credit_note else 1,
            "rate": abs(amount) if is_credit_note else amount,
            "cost_center": default_cost_center,
        }

        if income_account:
            item_row["income_account"] = income_account
        elif not default_income_account:
            frappe.throw(
                f"Position {idx}: Bitte ein Erlöskonto angeben oder in der Company ein default_income_account pflegen."
            )

        items.append(item_row)

    # Bemerkung: echte freie User-Eingabe hat Vorrang. Der alte automatisch
    # erzeugte Cockpit-Text wird verworfen; danach greifen Positions-
    # Beschreibungen, und wenn es die nicht gibt, bleibt die Bemerkung leer.
    user_remark = _normalize_sales_invoice_user_remark(kwargs.get("bemerkung"))
    remarks = user_remark or "\n".join(d for d in position_descriptions if d)

    si = frappe.new_doc("Sales Invoice")
    si.update({
        "company": company,
        "customer": customer,
        "posting_date": posting_date,
        "due_date": posting_date if is_credit_note else due_date,
        "is_return": 1 if is_credit_note else 0,
        "ignore_default_payment_terms_template": 1,
        "remarks": remarks,
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

    if _has_field("Sales Invoice", "mietabrechnung_id"):
        si.set("mietabrechnung_id", None)

    si.insert()
    if submit_flag:
        si.submit()
        belegart = "Gutschrift" if is_credit_note else "Rechnung"
        frappe.msgprint(f"{belegart} {si.name} wurde erstellt und eingereicht.", alert=True)
    else:
        belegart = "Gutschrift" if is_credit_note else "Rechnung"
        frappe.msgprint(f"{belegart} {si.name} wurde als Entwurf gespeichert.", alert=True)
    return {"name": si.name, "submitted": submit_flag, "is_credit_note": is_credit_note}


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
        import os as _os

        from frappe.core.doctype.file.utils import generate_file_name
        from frappe.utils.file_manager import get_files_path

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
