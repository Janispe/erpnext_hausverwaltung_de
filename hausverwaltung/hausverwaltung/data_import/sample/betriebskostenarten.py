"""Seed helper for creating example Betriebskostenarten.

Usage (bench console):
    from hausverwaltung.hausverwaltung.data_import.betriebskostenarten import create_sample_betriebskostenarten
    create_sample_betriebskostenarten(company="Demo Hausverwaltung")
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import frappe


def _ensure_zustandsschluessel(name: str, art: str) -> str:
    """Ensure a Zustandsschlüssel exists with given art (Boolean/Gleitkommazahl/Natürliche Zahl)."""
    valid = {"Boolean", "Gleitkommazahl", "Natürliche Zahl"}
    if art not in valid:
        raise ValueError(f"Ungültige Art für Zustandsschlüssel: {art}")

    if frappe.db.exists("Zustandsschluessel", name):
        return name
    doc = frappe.get_doc(
        {
            "doctype": "Zustandsschluessel",
            "name1": name,
            "art": art,
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _try_find_account(candidates: List[str], company: Optional[str] = None) -> Optional[str]:
    """Try to find a matching Account by fuzzy substring on name/account_name."""
    if not candidates:
        return None

    filters = {"is_group": 0}
    if company:
        filters["company"] = company

    rows = frappe.get_all("Account", filters=filters, fields=["name", "account_name"], limit=1000)
    cand_lower = [c.lower() for c in candidates]
    for r in rows:
        hay = f"{r.get('name','')}|{r.get('account_name','')}".lower()
        if any(c in hay for c in cand_lower):
            return r["name"]
    return None


def _ensure_default_service_item() -> str:
    """Use existing utility to ensure a default non-stock service item exists."""
    try:
        from hausverwaltung.hausverwaltung.utils.buchung import ensure_default_service_item

        return ensure_default_service_item()
    except Exception:
        # Minimal fallback
        code = "VHB-SERVICE"
        if frappe.db.exists("Item", code):
            return code
        grp = None
        if frappe.db.exists("Item Group", {"name": "Services", "is_group": 0}):
            grp = "Services"
        else:
            rows = frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name", limit=1)
            grp = rows[0] if rows else "All Item Groups"

        uom = "Nos"
        u = frappe.get_all("UOM", pluck="name", limit=1)
        if u:
            uom = u[0]
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": "Allgemeine Dienstleistung",
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
                "disabled": 0,
                "item_group": grp,
                "stock_uom": uom,
                "standard_rate": 0,
            }
        ).insert(ignore_permissions=True)
        return item.name


def _create_betriebskostenart(
    name: str,
    verteilung: str,
    company: Optional[str],
    konto_candidates: Optional[List[str]] = None,
    artikel_code: Optional[str] = None,
    schluessel: Optional[str] = None,
) -> str:
    """Create or update a Betriebskostenart (idempotent by Name/name1)."""
    if frappe.db.exists("Betriebskostenart", name):
        doc = frappe.get_doc("Betriebskostenart", name)
        # If konto set but invalid, try to resolve or create
        if getattr(doc, "konto", None):
            if not frappe.db.exists("Account", doc.konto):
                acc = _resolve_or_create_account(doc.konto, konto_candidates or [], company)
                if acc:
                    doc.konto = acc
                elif company:
                    # As last resort, create an expense account from first candidate or name
                    fallback_name = (konto_candidates[0] if (konto_candidates and len(konto_candidates) > 0) else name)
                    acc2 = _ensure_expense_account(fallback_name, company)
                    if acc2:
                        doc.konto = acc2
        else:
            acc = _try_find_account(konto_candidates or [], company)
            if not acc and company:
                fallback_name = (konto_candidates[0] if (konto_candidates and len(konto_candidates) > 0) else name)
                acc = _ensure_expense_account(fallback_name, company)
            if acc:
                doc.konto = acc
        if artikel_code and not doc.artikel:
            doc.artikel = artikel_code
        if schluessel and not (doc.get("schlüssel") or doc.get("schluessel")):
            setattr(doc, "schlüssel", schluessel)
        doc.save(ignore_permissions=True)
        return doc.name

    konto = _try_find_account(konto_candidates or [], company)
    if (not konto) and company:
        # Create a simple leaf Expense account as fallback using first candidate or the BK name
        name_to_use = (konto_candidates[0] if (konto_candidates and len(konto_candidates) > 0) else name)
        konto = _ensure_expense_account(name_to_use, company)
    doc = frappe.get_doc(
        {
            "doctype": "Betriebskostenart",
            "name1": name,
            "verteilung": verteilung,
            "konto": konto,
            "artikel": artikel_code,
        }
    )
    if schluessel:
        setattr(doc, "schlüssel", schluessel)
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_expense_account(acc_name: str, company: str) -> Optional[str]:
    """Ensure a leaf Expense account with given name exists for company and return its docname.

    If an account by that name already exists, returns it. Otherwise, creates it
    under the first available Expense group account.
    """
    # Existing by account_name
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "account_name": acc_name, "is_group": 0},
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]

    # Find an Expense group as parent
    parent_rows = frappe.get_all(
        "Account",
        filters={"company": company, "root_type": "Expense", "is_group": 1},
        pluck="name",
        limit=1,
    )
    parent = parent_rows[0] if parent_rows else None

    if not parent:
        # Ensure we have a company root account like "{company} - {abbr}"
        def _company_root() -> Optional[str]:
            try:
                comp = frappe.get_doc("Company", company)
                root_name = f"{company} - {comp.abbr}"
            except Exception:
                # Fall back to a best-effort name
                root_name = f"{company}"
            # try existing
            rows = frappe.get_all(
                "Account", filters={"name": root_name, "is_group": 1}, pluck="name", limit=1
            )
            if rows:
                return rows[0]
            # create root
            try:
                root_doc = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": company,
                        "company": company,
                        "is_group": 1,
                        # root_type intentionally left blank for the company root
                    }
                ).insert(ignore_permissions=True)
                return root_doc.name
            except Exception:
                return None

        root = _company_root()
        if root:
            # Create or reuse an Expense group under the company root
            exp_group = frappe.get_all(
                "Account",
                filters={
                    "company": company,
                    "parent_account": root,
                    "is_group": 1,
                    "account_name": ["in", ["Expenses", "Aufwendungen", "Aufwand"]],
                },
                pluck="name",
                limit=1,
            )
            parent = exp_group[0] if exp_group else None
            if not parent:
                try:
                    grp_doc = frappe.get_doc(
                        {
                            "doctype": "Account",
                            "account_name": "Expenses",
                            "company": company,
                            "is_group": 1,
                            "parent_account": root,
                            "root_type": "Expense",
                            "report_type": "Profit and Loss",
                        }
                    ).insert(ignore_permissions=True)
                    parent = grp_doc.name
                except Exception:
                    parent = None

    if not parent:
        return None

    try:
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": acc_name,
                "company": company,
                "is_group": 0,
                "parent_account": parent,
            }
        ).insert(ignore_permissions=True)
        return doc.name
    except Exception:
        return None


def _split_composite_account(s: str) -> Tuple[Optional[str], Optional[str]]:
    """Try to split a composite label like '6336 - Allgemeinstrom - HP' into (number, name).

    Returns (account_number, account_name) where either can be None.
    """
    if not s:
        return None, None
    parts = [p.strip() for p in str(s).split("-")]
    if not parts:
        return None, None
    # first token may be number possibly with decimal like '6336.0'
    num = parts[0].replace(" ", "")
    if num.replace(".", "").isdigit():
        # normalize e.g. '6336.0' -> '6336'
        try:
            num = str(int(float(num)))
        except Exception:
            pass
        # next token(s) as name if available
        name = parts[1].strip() if len(parts) >= 2 else None
        return num, name
    # else treat whole as name
    return None, str(s).strip()


def _resolve_or_create_account(current_value: str, candidates: List[str], company: Optional[str]) -> Optional[str]:
    """Resolve an Account docname from a composite/current value, or create a fallback.

    Tries by direct name, by account_number, and by candidate names; finally creates
    an Expense account with the best candidate name.
    """
    # 1) Direct match by Account.name
    if frappe.db.exists("Account", current_value):
        return current_value

    # 2) Try account_number parsed from composite label
    acc_no, acc_nm = _split_composite_account(current_value)
    if company and acc_no:
        rows = frappe.get_all(
            "Account",
            filters={"company": company, "account_number": acc_no, "is_group": 0},
            pluck="name",
            limit=1,
        )
        if rows:
            return rows[0]

    # 3) Try by account_name match
    if company and acc_nm:
        rows = frappe.get_all(
            "Account",
            filters={"company": company, "account_name": acc_nm, "is_group": 0},
            pluck="name",
            limit=1,
        )
        if rows:
            return rows[0]

    # 4) Fuzzy with provided candidates
    acc = _try_find_account(candidates, company) if candidates else None
    if acc:
        return acc

    # 5) Create a simple Expense account
    if company:
        name_to_create = (acc_nm or (candidates[0] if candidates else None))
        if name_to_create:
            return _ensure_expense_account(name_to_create, company)
    return None


def create_sample_betriebskostenarten(company: Optional[str] = None) -> List[str]:
    """Create a practical set of example Betriebskostenarten.

    - Verteilungsarten limited to implemented variants: "qm", "Einzeln", "Schlüssel".
    - Try to link fitting Expense accounts heuristically by name.
    - Create required Zustandsschlüssel automatically.

    Returns:
        List of Betriebskostenart names created/ensured.
    """
    created: List[str] = []

    # Keys
    aufzug_key = _ensure_zustandsschluessel("Aufzugfaktor", "Gleitkommazahl")
    muell_key = _ensure_zustandsschluessel("Müllschlüssel", "Natürliche Zahl")

    # Default service item
    service_item = _ensure_default_service_item()

    defs = [
        ("Allgemeinstrom", "qm", ["Allgemeinstrom", "Gemeinschaftsstrom", "Strom"], None),
        ("Treppenhausreinigung", "qm", ["Treppenhausreinigung", "Gebäudereinigung", "Hausreinigung"], None),
        ("Gartenpflege", "qm", ["Gartenpflege"], None),
        ("Hauswart", "qm", ["Hauswart", "Hausmeister"], None),
        ("Haftpflichtversicherung", "qm", ["Haftpflicht", "Versicherung"], None),
        ("Gebäudeversicherung", "qm", ["Gebäudeversicherung", "Versicherung Gebäude"], None),
        ("Grundsteuer", "qm", ["Grundsteuer"], None),
        ("Winterdienst / Straßenreinigung", "qm", ["Winterdienst", "Straßenreinigung", "Strassenreinigung"], None),
        ("Müllabfuhr", "Schlüssel", ["Müll", "Abfall"], muell_key),
        ("Aufzug", "Schlüssel", ["Aufzug", "Fahrstuhl"], aufzug_key),
        ("Individuelle Wasser/Abwasser", "Einzeln", ["Wasser", "Abwasser"], None),
    ]

    for name, verteilung, konto_cands, key in defs:
        bk_name = _create_betriebskostenart(
            name=name,
            verteilung=verteilung,
            company=company,
            konto_candidates=konto_cands,
            artikel_code=service_item,
            schluessel=key,
        )
        created.append(bk_name)

    frappe.db.commit()
    return created
