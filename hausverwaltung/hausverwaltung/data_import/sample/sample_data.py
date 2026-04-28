"""Sample/seed data creator for quick testing in development.

Creates:
- 1 Immobilie (Musterhaus Berlin)
- 3 Wohnungen (EG links, 1. OG rechts, DG)
- 3 Customers + Contacts (je Wohnung)
- 3 Mietverträge inkl. einfacher Staffel (Miete/BK/HK Startwerte)
 - Je Customer ein Bank Account mit IBAN (für Bankabgleich)

Usage (bench console):
    # Direkt nur dieses Sample erzeugen
    from hausverwaltung.hausverwaltung.data_import.sample.sample_data import create_sample_data
    create_sample_data(company="Demo Hausverwaltung", with_zustand=True, with_invoices=False, with_payments=False)
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Optional

import frappe
from frappe.utils import getdate
from hausverwaltung.hausverwaltung.utils.immobilie_accounts import (
    get_immobilie_bank_accounts,
    get_immobilie_primary_bank_account,
)


DEMO_MIETER_EMAIL = "test_mieter@example.com"


def _ensure_fiscal_year(*, company: str, year: int) -> str | None:
    """Best-effort ensure a Fiscal Year exists and is usable for the given company/year.

    ERPNext / customizations differ across versions:
    - Some setups use Fiscal Year per company (field `company`)
    - Others use a child table (field `companies`)
    This helper tries to cover both without hard-failing.
    """
    try:
        if not frappe.db.table_exists("Fiscal Year"):
            return None
    except Exception:
        return None

    fy_label = str(int(year))
    try:
        fy_meta = frappe.get_meta("Fiscal Year")
    except Exception:
        fy_meta = None

    def _set_active_fields(doc) -> bool:
        changed = False
        try:
            if fy_meta and fy_meta.has_field("disabled") and getattr(doc, "disabled", None):
                doc.disabled = 0
                changed = True
        except Exception:
            pass
        try:
            if fy_meta and fy_meta.has_field("is_active") and not getattr(doc, "is_active", 1):
                doc.is_active = 1
                changed = True
        except Exception:
            pass
        return changed

    # 1) Find an existing FY by docname or by `year` field
    fy_name = None
    try:
        if frappe.db.exists("Fiscal Year", fy_label):
            fy_name = fy_label
    except Exception:
        fy_name = None

    if not fy_name and fy_meta and fy_meta.has_field("year"):
        try:
            rows = frappe.get_all("Fiscal Year", filters={"year": fy_label}, pluck="name", limit=1)
            fy_name = rows[0] if rows else None
        except Exception:
            fy_name = None

    # 2) Create if missing
    if not fy_name:
        payload = {
            "doctype": "Fiscal Year",
            "year_start_date": f"{fy_label}-01-01",
            "year_end_date": f"{fy_label}-12-31",
        }
        if fy_meta and fy_meta.has_field("year"):
            payload["year"] = fy_label
        if fy_meta and fy_meta.has_field("company"):
            payload["company"] = company
        if fy_meta and fy_meta.has_field("disabled"):
            payload["disabled"] = 0
        if fy_meta and fy_meta.has_field("is_active"):
            payload["is_active"] = 1
        if fy_meta and fy_meta.has_field("companies"):
            payload["companies"] = [{"company": company}]

        try:
            doc = frappe.get_doc(payload).insert(ignore_permissions=True, ignore_if_duplicate=True)
            fy_name = doc.name
        except Exception:
            # Fallback: if `year` naming collides, try reusing the existing one and just link/activate it.
            try:
                if frappe.db.exists("Fiscal Year", fy_label):
                    fy_name = fy_label
            except Exception:
                fy_name = None

    if not fy_name:
        return None

    # 3) Ensure it's active + linked to this company where possible
    try:
        fy = frappe.get_doc("Fiscal Year", fy_name)
    except Exception:
        return fy_name

    changed = False
    try:
        if fy_meta and fy_meta.has_field("company") and getattr(fy, "company", None) != company:
            fy.company = company
            changed = True
    except Exception:
        pass

    changed = _set_active_fields(fy) or changed

    try:
        if fy_meta and fy_meta.has_field("companies"):
            rows = list(getattr(fy, "companies", None) or [])
            if not any(getattr(r, "company", None) == company for r in rows):
                fy.append("companies", {"company": company})
                changed = True
    except Exception:
        pass

    if changed:
        try:
            fy.save(ignore_permissions=True)
        except Exception:
            pass

    # 4) Ensure Company.default_fiscal_year points to a valid FY (if field exists)
    try:
        if frappe.get_meta("Company").has_field("default_fiscal_year"):
            cur = frappe.db.get_value("Company", company, "default_fiscal_year")
            if not cur:
                frappe.db.set_value("Company", company, "default_fiscal_year", fy_name, update_modified=False)
    except Exception:
        pass

    return fy_name


def _ensure_customer_group_root() -> str:
    """Ensure a usable Customer Group root exists and return its name.

    ERPNext standard is "All Customer Groups". In reset/dev environments this
    root can be missing; creating it makes subsequent inserts idempotent.
    """
    preferred = "All Customer Groups"
    try:
        if frappe.db.exists("Customer Group", preferred):
            return preferred
    except Exception:
        pass

    # Try to find any existing root-ish group (best effort)
    try:
        rows = frappe.get_all(
            "Customer Group",
            fields=["name", "parent_customer_group", "is_group"],
            limit=200,
        )
        for row in rows:
            if row.get("name") == preferred:
                return preferred
        for row in rows:
            if row.get("is_group") and not row.get("parent_customer_group"):
                return row["name"]
    except Exception:
        pass

    try:
        doc = frappe.get_doc(
            {
                "doctype": "Customer Group",
                "customer_group_name": preferred,
                "is_group": 1,
            }
        ).insert(ignore_if_duplicate=True, ignore_permissions=True)
        return doc.name
    except Exception:
        return preferred


def _ensure_customer_group_mieter() -> str:
    """Ensure a Customer Group named 'Mieter' exists and return its name."""
    if frappe.db.exists("Customer Group", "Mieter"):
        return "Mieter"
    parent = _ensure_customer_group_root()
    doc = frappe.get_doc(
        {
            "doctype": "Customer Group",
            "customer_group_name": "Mieter",
            # use English root to be compatible with vanilla ERPNext
            "parent_customer_group": parent,
        }
    ).insert(ignore_if_duplicate=True)
    return doc.name


def _ensure_supplier_group_all() -> str:
    """Ensure a Supplier Group exists and return a usable group name.

    Prefer the standard root group "All Supplier Groups". If it does not exist,
    fall back to the first existing Supplier Group, otherwise create the root.
    """
    root = "All Supplier Groups"
    try:
        if frappe.db.exists("Supplier Group", root):
            return root
        existing = frappe.get_all("Supplier Group", pluck="name", limit=1)
        if existing:
            return existing[0]
        doc = frappe.get_doc(
            {
                "doctype": "Supplier Group",
                "supplier_group_name": root,
                "is_group": 1,
            }
        ).insert(ignore_if_duplicate=True, ignore_permissions=True)
        return doc.name
    except Exception:
        # Last resort: return standard name; insert may still succeed later
        return root


def _ensure_zustandsschluessel(name: str, art: str) -> str:
    """Ensure a Zustandsschlüssel with given name/art exists and return its name.

    Art must be one of: "Boolean", "Gleitkommazahl", "Natürliche Zahl".
    """
    valid = {"Boolean", "Gleitkommazahl", "Natürliche Zahl"}
    if art not in valid:
        raise ValueError(f"Ungültige Art für Zustandsschlüssel: {art}")

    try:
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
    except Exception:
        # As a last resort, return the input name (insert may fail on missing DocType)
        return name


def _ensure_muellschluessel_on_zustand(zustand_name: str, wert: int) -> None:
    """Ensure the "Müllschlüssel" int row exists on a Wohnungszustand with provided value.

    - Creates Zustandsschlüssel "Müllschlüssel" (Natürliche Zahl) if missing.
    - Idempotent: updates row when already present.
    """
    try:
        muell_key = _ensure_zustandsschluessel("Müllschlüssel", "Natürliche Zahl")

        zustand = frappe.get_doc("Wohnungszustand", zustand_name)
        found = False
        for row in getattr(zustand, "zustand_int", []) or []:
            if getattr(row, "zustandsschluessel", None) == muell_key:
                if getattr(row, "wert_int", None) != int(wert):
                    row.wert_int = int(wert)
                found = True
                break
        if not found:
            zustand.append(
                "zustand_int",
                {"zustandsschluessel": muell_key, "wert_int": int(wert)},
            )
        zustand.save(ignore_permissions=True)
    except Exception:
        # Keep sample creation resilient even if keys are unavailable
        pass


def _get_company_abbr(company: str) -> str:
    comp = frappe.get_doc("Company", company)
    return comp.abbr


def _get_or_create_cost_center(name: str, company: str) -> str:
    existing = frappe.get_all(
        "Cost Center", filters={"cost_center_name": name, "company": company}, pluck="name"
    )
    if existing:
        # Ensure the BK-Abrechnung-Flag is set on existing records as well
        try:
            doc = frappe.get_doc("Wohnungszustand", existing[0])
            if getattr(doc, "betriebskostenabrechnung_durch_vermieter", 0) != 1:
                doc.betriebskostenabrechnung_durch_vermieter = 1
                doc.save(ignore_permissions=True)
            return doc.name
        except Exception:
            return existing[0]

    parent = f"{company} - {_get_company_abbr(company)}"
    return (
        frappe.get_doc(
            {
                "doctype": "Cost Center",
                "cost_center_name": name,
                "is_group": 0,
                "parent_cost_center": parent,
                "company": company,
            }
        ).insert(ignore_permissions=True)
    ).name


def _get_company_currency(company: str) -> Optional[str]:
    try:
        return frappe.db.get_value("Company", company, "default_currency")
    except Exception:
        return None


def _ensure_site_default_currency(company: str) -> None:
    """Best-effort align site defaults with the given company's currency.

    Some ERPNext flows derive document currency from Global Defaults / (Buying|Selling)
    Settings. In demo/reset environments these can fall back to INR and break
    validations when company accounts are in EUR.
    """
    currency = _get_company_currency(company) or "EUR"

    # Global Defaults (ERPNext)
    try:
        gd = frappe.get_single("Global Defaults")
        if hasattr(gd, "default_currency") and gd.default_currency != currency:
            gd.default_currency = currency
            gd.save(ignore_permissions=True)
    except Exception:
        pass

    # Frappe defaults API (covers keys used by various code paths)
    for key in ("currency", "default_currency"):
        try:
            frappe.defaults.set_global_default(key, currency)
        except Exception:
            pass
    try:
        frappe.defaults.set_user_default("currency", currency)
    except Exception:
        pass

    # Buying/Selling settings defaults (ERPNext)
    for dt in ("Buying Settings", "Selling Settings"):
        try:
            st = frappe.get_single(dt)
            if hasattr(st, "default_currency") and st.default_currency != currency:
                st.default_currency = currency
                st.save(ignore_permissions=True)
        except Exception:
            pass


def _pick_leaf_account_by_keywords(
    *, company: str, keywords: List[str], root_type: Optional[str] = None
) -> Optional[str]:
    """Best-effort pick a leaf account by keyword match on name/account_name."""
    try:
        rows = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 0},
            fields=["name", "account_name", "root_type", "account_type"],
            limit=2000,
        )
    except Exception:
        return None

    keys = [k.lower() for k in (keywords or []) if k]
    for row in rows:
        if root_type and row.get("root_type") and row.get("root_type") != root_type:
            continue
        hay = f"{row.get('name') or ''} {row.get('account_name') or ''}".lower()
        if any(k in hay for k in keys):
            return row["name"]
    return None


def _ensure_account_has_type(acc_name: str, *, account_type: str, root_type: Optional[str] = None) -> Optional[str]:
    """Ensure Account has desired account_type/root_type (best-effort)."""
    if not acc_name or not frappe.db.exists("Account", acc_name):
        return None
    try:
        acc = frappe.get_doc("Account", acc_name)
        updated = False
        if getattr(acc, "account_type", None) != account_type:
            acc.account_type = account_type
            updated = True
        if root_type and (not getattr(acc, "root_type", None)):
            acc.root_type = root_type
            updated = True
        if updated:
            acc.save(ignore_permissions=True)
        return acc.name
    except Exception:
        return acc_name


def _ensure_company_default_account(
    *,
    company: str,
    company_field: str,
    desired_account_type: str,
    desired_root_type: str,
    keyword_candidates: List[str],
    fallback_account_name: str,
) -> Optional[str]:
    """Ensure a Company default account field points to an existing leaf with correct account_type."""
    try:
        if not frappe.get_meta("Company").has_field(company_field):
            return None
    except Exception:
        return None

    try:
        current = frappe.db.get_value("Company", company, company_field)
    except Exception:
        current = None

    if current and frappe.db.exists("Account", current) and frappe.db.get_value("Account", current, "account_type") == desired_account_type:
        return current

    # 1) Any existing leaf with desired account_type
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "account_type": desired_account_type},
        pluck="name",
        limit=1,
    )
    acc_name = rows[0] if rows else None

    # 2) Keyword match (templates like SKR03 often don't set account_type)
    if not acc_name:
        acc_name = _pick_leaf_account_by_keywords(company=company, keywords=keyword_candidates, root_type=desired_root_type)

    # 3) Create a dedicated demo account as last resort
    if not acc_name:
        parent = _find_group_account(company, root_type=desired_root_type) or _find_group_account(company)
        if not parent:
            return None
        acc_currency = _get_company_currency(company)
        acc_name_to_create = f"Demo {fallback_account_name}"
        try:
            acc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": acc_name_to_create,
                    "is_group": 0,
                    "root_type": desired_root_type,
                    "account_type": desired_account_type,
                    **({"account_currency": acc_currency} if acc_currency else {}),
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            acc_name = acc.name
        except Exception:
            # If name collides, try with a suffix
            try:
                acc = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "company": company,
                        "account_name": f"{acc_name_to_create} 1",
                        "is_group": 0,
                        "root_type": desired_root_type,
                        "account_type": desired_account_type,
                        **({"account_currency": acc_currency} if acc_currency else {}),
                        "parent_account": parent,
                    }
                ).insert(ignore_permissions=True)
                acc_name = acc.name
            except Exception:
                return None

    acc_name = _ensure_account_has_type(acc_name, account_type=desired_account_type, root_type=desired_root_type) or acc_name

    # Use direct DB update to avoid Company validation failures when other defaults are stale.
    try:
        frappe.db.set_value("Company", company, company_field, acc_name, update_modified=False)
    except Exception:
        try:
            comp = frappe.get_doc("Company", company)
            setattr(comp, company_field, acc_name)
            comp.save(ignore_permissions=True)
        except Exception:
            pass
    return acc_name


def _get_or_create_contact(first_name: str, customer: str | None = None) -> str:
    rows = frappe.get_all("Contact", filters={"first_name": first_name}, pluck="name")
    if rows:
        contact = frappe.get_doc("Contact", rows[0])
    else:
        contact = frappe.get_doc({"doctype": "Contact", "first_name": first_name}).insert(
            ignore_permissions=True
        )

    if customer and not any(l.link_doctype == "Customer" and l.link_name == customer for l in contact.links):
        contact.append(
            "links",
            {
                "link_doctype": "Customer",
                "link_name": customer,
                "link_title": customer,
            },
        )
        contact.save(ignore_permissions=True)

    return contact.name


def _ensure_contact_email(contact_name: str, email: str) -> None:
    """Ensure the Contact has the given (primary) email address set (idempotent)."""
    if not contact_name or not email:
        return
    try:
        contact = frappe.get_doc("Contact", contact_name)
    except Exception:
        return

    try:
        # Newer ERPNext/Frappe: child table `email_ids` with rows containing `email_id`
        email_rows = list(getattr(contact, "email_ids", None) or [])
        normalized = (email or "").strip()

        if email_rows:
            # If email already present, mark it primary; else overwrite first row for deterministic demo behavior.
            existing = None
            for row in email_rows:
                if (getattr(row, "email_id", "") or "").strip() == normalized:
                    existing = row
                    break
            target = existing or email_rows[0]
            target.email_id = normalized
            if hasattr(target, "is_primary"):
                target.is_primary = 1
        else:
            contact.append("email_ids", {"email_id": normalized, "is_primary": 1})

        # Some installations have a direct `email_id` field on Contact as well.
        if hasattr(contact, "email_id"):
            contact.email_id = normalized

        contact.save(ignore_permissions=True)
    except Exception:
        # Keep sample creation resilient even if Contact schema differs
        pass


def _get_or_create_address(
    title: str,
    *,
    line1: str | None = None,
    pincode: str | None = None,
    city: str | None = None,
    address_type: str = "Other",
) -> str:
    """Return Address name by title; create if missing."""
    existing = frappe.get_all(
        "Address", filters={"address_title": title}, pluck="name", limit=1
    )
    if existing:
        return existing[0]

    def _pick_country() -> str | None:
        # Prefer Global Defaults if set
        try:
            default_country = frappe.db.get_single_value("Global Defaults", "default_country")
            if default_country and frappe.db.exists("Country", default_country):
                return default_country
        except Exception:
            pass
        # Common defaults
        for candidate in ("Germany", "Deutschland"):
            try:
                if frappe.db.exists("Country", candidate):
                    return candidate
            except Exception:
                continue
        # Fallback: any country
        try:
            rows = frappe.get_all("Country", pluck="name", limit=1)
            return rows[0] if rows else None
        except Exception:
            return None

    country = _pick_country()
    doc = frappe.get_doc(
        {
            "doctype": "Address",
            "address_title": title,
            "address_line1": line1 or title,
            "pincode": pincode or "",
            "city": city or "",
            "address_type": address_type,
            "is_primary_address": 1,
            **({"country": country} if country else {}),
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _ensure_address_link(address_name: str, link_doctype: str, link_name: str) -> None:
    """Ensure the Address is linked to the target document."""
    try:
        addr = frappe.get_doc("Address", address_name)
    except Exception:
        return

    if any(l.link_doctype == link_doctype and l.link_name == link_name for l in (addr.links or [])):
        return

    try:
        addr.append("links", {"link_doctype": link_doctype, "link_name": link_name})
        addr.save(ignore_permissions=True)
    except Exception:
        # Keep sample creation resilient
        pass


def _get_or_create_customer(name: str, company: str) -> str:
    """Ensure a Customer exists.

    Buchung läuft über das Sammelkonto Debitoren (Company.default_receivable_account);
    pro Customer wird kein eigenes Konto gepinnt.
    """
    if frappe.db.exists("Customer", name):
        return name

    group = _ensure_customer_group_mieter()
    return (
        frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": name,
                "customer_type": "Individual",
                "customer_group": group,
            }
        ).insert(ignore_permissions=True)
    ).name


def _ensure_default_bank() -> str:
    """Ensure a generic Bank exists and return its name."""
    bank_name = "Demo Bank"
    if not frappe.db.exists("Bank", bank_name):
        frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(
            ignore_permissions=True
        )
    return bank_name


def _alphanum_to_digits(s: str) -> str:
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(ch)
        else:
            out.append(str(ord(ch.upper()) - 55))
    return "".join(out)


def _iban_for_de(bban: str) -> str:
    """Compute a valid German IBAN from an 18-digit BBAN (8 BLZ + 10 Kto).

    Returns string like 'DEkk<BBAN>' with correct checksum.
    """
    if not (bban and bban.isdigit() and len(bban) == 18):
        raise ValueError("BBAN must be 18 digits for DE IBAN")
    country = "DE"
    rearranged = f"{bban}{country}00"
    num = int(_alphanum_to_digits(rearranged))
    checksum = 98 - (num % 97)
    return f"{country}{checksum:02d}{bban}"


def _demo_iban_customer(idx: int) -> str:
    """Return a valid, deterministic DE IBAN for demo customers (idx starting at 0)."""
    # Use a fixed BLZ (37040044 – example from docs) and vary the account number tail
    blz = "37040044"
    konto_base = 532013000  # 9 digits base from example 0532013000
    konto = f"{konto_base + (idx + 1):010d}"
    bban = f"{blz}{konto}"
    return _iban_for_de(bban)


def _demo_iban_supplier() -> str:
    # Another deterministic account for supplier
    blz = "50010517"  # sample BLZ
    konto = "0123456789"
    bban = f"{blz}{konto}"
    return _iban_for_de(bban)


def _get_or_create_bank_account_for_customer(
    customer: str, *, iban: Optional[str] = None
) -> Optional[str]:
    """Create a party Bank Account with IBAN for the given Customer (idempotent)."""
    iban_clean = (iban or "").replace(" ", "").upper()
    if not iban_clean:
        return None

    rows = frappe.get_all(
        "Bank Account",
        filters={"iban": iban_clean, "party_type": "Customer", "party": customer},
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]

    # If a bank account with this IBAN already exists (e.g. created by another import),
    # ensure it is linked to the customer instead of creating a duplicate.
    try:
        candidates = frappe.get_all(
            "Bank Account",
            filters={"iban": iban_clean},
            fields=["name", "is_company_account", "party_type", "party"],
            limit=50,
        )
    except Exception:
        candidates = []

    for c in candidates:
        # Never reassign company bank accounts.
        if c.get("is_company_account"):
            continue
        try:
            doc = frappe.get_doc("Bank Account", c["name"])
        except Exception:
            continue
        changed = False
        if getattr(doc, "party_type", None) != "Customer":
            doc.party_type = "Customer"
            changed = True
        if getattr(doc, "party", None) != customer:
            doc.party = customer
            changed = True
        if hasattr(doc, "is_company_account") and getattr(doc, "is_company_account", 0) != 0:
            doc.is_company_account = 0
            changed = True
        if changed:
            try:
                doc.save(ignore_permissions=True)
            except Exception:
                pass
        return doc.name

    bank = _ensure_default_bank()
    doc = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Konto {customer}",
            "bank": bank,
            "iban": iban_clean,
            "is_company_account": 0,
            "party_type": "Customer",
            "party": customer,
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _ensure_wohnungszustand(wohnung: str, ab: str, groesse: float) -> str | None:
    """Create a simple Wohnungszustand if the DocType exists.

    Returns the document name or None when the table is not available.
    """
    try:
        if not frappe.db.table_exists("Wohnungszustand"):
            return None
    except Exception:
        return None

    # idempotent by (wohnung, ab)
    existing = frappe.get_all(
        "Wohnungszustand",
        filters={"wohnung": wohnung, "ab": ab},
        pluck="name",
        limit=1,
    )
    if existing:
        # Ensure the BK-Abrechnung-Flag is set on existing records as well
        try:
            doc = frappe.get_doc("Wohnungszustand", existing[0])
            if getattr(doc, "betriebskostenabrechnung_durch_vermieter", 0) != 1:
                doc.betriebskostenabrechnung_durch_vermieter = 1
                doc.save(ignore_permissions=True)
            return doc.name
        except Exception:
            return existing[0]

    doc = frappe.get_doc(
        {
            "doctype": "Wohnungszustand",
            "wohnung": wohnung,
            "ab": ab,
            "größe": float(groesse),
            "wohnung_aktiv_genutzt": 1,
            # In den Sample-Daten: BK-Abrechnung durch Vermieter aktivieren
            "betriebskostenabrechnung_durch_vermieter": 1,
            "bad": "Mit Fenster",
            "mietspiegelkategorie": 1,
            "merkmalpunkte": 0,
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _find_income_account(company: str | None) -> str | None:
    if not company:
        return None
    acc = frappe.db.get_value("Company", company, "default_income_account")
    if acc:
        return acc
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "root_type": "Income"},
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]
    # Fallback: create a lightweight demo income account under the Income root
    try:
        parent_rows = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 1, "root_type": "Income"},
            pluck="name",
            limit=1,
        )
        if not parent_rows:
            return None
        parent = parent_rows[0]
        demo_name = "Demo Einnahmen"
        existing = frappe.get_all(
            "Account",
            filters={"company": company, "account_name": demo_name, "is_group": 0},
            pluck="name",
            limit=1,
        )
        if existing:
            return existing[0]
        acc_doc = frappe.get_doc(
            {
                "doctype": "Account",
                "company": company,
                "account_name": demo_name,
                "is_group": 0,
                "root_type": "Income",
                "parent_account": parent,
            }
        ).insert(ignore_permissions=True)
        return acc_doc.name
    except Exception:
        return None


def _ensure_income_accounts_split(company: str) -> Dict[str, Optional[str]]:
    """Ensure separate Income accounts for Miete, Betriebskosten and Heizkosten.

    Returns a mapping: {"Miete": account, "Betriebskosten": account, "Heizkosten": account}.

    Tries to reuse existing leaf Income accounts by common names, otherwise
    creates simple leaf accounts under the first available Income group.
    """
    def _find_income_parent() -> Optional[str]:
        parent = _find_group_account(
            company,
            root_type="Income",
            name_contains=["income", "ertrag", "erträge", "erlös", "erlöse"],
        )
        if not parent:
            parent = _find_group_account(company, root_type="Income")
        return parent

    def _find_existing_income_account(candidates: List[str]) -> Optional[str]:
        if not candidates:
            return None
        rows = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 0, "root_type": "Income"},
            fields=["name", "account_name"],
            limit=1000,
        )
        if not rows:
            return None
        cand_low_exact = [c.lower() for c in candidates]
        # Prefer exact account_name matches
        for r in rows:
            nm = (r.get("account_name") or "").lower()
            if nm in cand_low_exact:
                return r["name"]
        # Then fuzzy: substring in name or account_name
        for r in rows:
            hay = f"{r.get('name','')}|{r.get('account_name','')}".lower()
            if any(c in hay for c in cand_low_exact):
                return r["name"]
        return None

    def _ensure_leaf_income(name: str, aliases: List[str]) -> Optional[str]:
        acc = _find_existing_income_account([name] + aliases)
        if acc:
            return acc
        parent = _find_income_parent()
        if not parent:
            return None
        try:
            doc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": name,
                    "is_group": 0,
                    "root_type": "Income",
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            return doc.name
        except Exception:
            return None

    # Define preferred names and aliases by category
    miete_acc = _ensure_leaf_income(
        "Mieterlöse",
        ["Mieterträge", "Mieteinnahmen", "Miete", "Mieterlöse"],
    )
    bk_acc = _ensure_leaf_income(
        "Betriebskostenumlagen",
        ["Betriebskostenumlagen", "BK-Umlagen", "Betriebskosten"],
    )
    hk_acc = _ensure_leaf_income(
        "Erlöse Heizkosten",
        ["Heizkostenvorauszahlungen", "Heizkostenumlagen", "Heizkosten"],
    )

    return {"Miete": miete_acc, "Betriebskosten": bk_acc, "Heizkosten": hk_acc}


def _find_receivable_account(customer: Optional[str], company: str | None) -> str | None:
    """Find or create a valid Receivable account for the given company.

    Order:
    1) Company.default_receivable_account
    2) erpnext.accounts.party.get_party_account('Customer', customer, company)
    3) Any leaf with account_type='Receivable'
    4) Create a leaf under a suitable group (e.g., 'Mieterforderungen') with account_type='Receivable'
    """
    if not company:
        return None

    # 1) Company default
    acc = frappe.db.get_value("Company", company, "default_receivable_account")
    if acc and (not frappe.db.exists("Account", acc) or frappe.db.get_value("Account", acc, "account_type") != "Receivable"):
        acc = None
    if acc:
        return acc

    # 2) ERPNext helper for party account
    try:
        if customer:
            from erpnext.accounts.party import get_party_account  # type: ignore

            party_acc = get_party_account("Customer", customer, company)
            if party_acc:
                return party_acc
    except Exception:
        pass

    # 3) Any leaf Receivable
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "account_type": "Receivable"},
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]

    # 3b) Templates may not set account_type; try keyword match
    acc = _pick_leaf_account_by_keywords(
        company=company,
        keywords=["forderung", "debitor", "receivable", "kunden", "lieferungen und leistungen", "kontokorrent"],
        root_type="Asset",
    )
    if acc:
        return _ensure_account_has_type(acc, account_type="Receivable", root_type="Asset") or acc

    # 4) Create a leaf under an AR group if we can find one
    parent_candidates = frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 1},
        fields=["name", "account_name"],
    )
    parent = None
    for row in parent_candidates:
        nm = (row.get("name") or "") + " " + (row.get("account_name") or "")
        nm_low = nm.lower()
        if "mieterforderung" in nm_low or "debtor" in nm_low or "receivable" in nm_low or "forderungen" in nm_low:
            parent = row["name"]
            break
    if not parent:
        # fallback to any Asset group as parent
        asset_groups = frappe.get_all(
            "Account", filters={"company": company, "is_group": 1, "root_type": "Asset"}, pluck="name", limit=1
        )
        parent = asset_groups[0] if asset_groups else None
    if not parent:
        # last-resort: any group account
        any_group = frappe.get_all("Account", filters={"company": company, "is_group": 1}, pluck="name", limit=1)
        parent = any_group[0] if any_group else None

    if parent:
        try:
            acc_doc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": "Debitoren",
                    "is_group": 0,
                    "root_type": "Asset",
                    "account_type": "Receivable",
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            return acc_doc.name
        except Exception:
            pass
    return None


def _find_group_account(company: str, *, root_type: Optional[str] = None, name_contains: Optional[List[str]] = None) -> Optional[str]:
    """Find a group account by optional root_type and name substrings (case-insensitive)."""
    filters = {"company": company, "is_group": 1}
    if root_type:
        filters["root_type"] = root_type
    rows = frappe.get_all("Account", filters=filters, fields=["name", "account_name"]) or []
    if not rows and root_type:
        # Some templates don't set root_type on group accounts; fall back to any group
        rows = frappe.get_all("Account", filters={"company": company, "is_group": 1}, fields=["name", "account_name"]) or []
    if not name_contains:
        return rows[0]["name"] if rows else None
    name_contains_low = [s.lower() for s in name_contains]
    for row in rows:
        nm = f"{row.get('name') or ''} {row.get('account_name') or ''}".lower()
        if any(s in nm for s in name_contains_low):
            return row["name"]
    return rows[0]["name"] if rows else None


def _ensure_basic_account_groups(company: str) -> Dict[str, Optional[str]]:
    """Ensure a minimal account tree exists (company root + Assets/Liabilities/Income/Expenses groups).

    This is a fallback when the Chart of Accounts was deleted and not re-imported.
    """
    out: Dict[str, Optional[str]] = {"root": None, "asset": None, "liability": None, "income": None, "expense": None}
    try:
        comp = frappe.get_doc("Company", company)
        root_name = f"{company} - {comp.abbr}"
    except Exception:
        root_name = company

    try:
        if frappe.db.exists("Account", root_name):
            root = root_name
        else:
            root = (
                frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": company,
                        "company": company,
                        "is_group": 1,
                    }
                )
                .insert(ignore_permissions=True)
                .name
            )
        out["root"] = root
    except Exception:
        return out

    def _ensure_group(account_name: str, root_type: str, report_type: str) -> Optional[str]:
        try:
            rows = frappe.get_all(
                "Account",
                filters={
                    "company": company,
                    "parent_account": out["root"],
                    "is_group": 1,
                    "root_type": root_type,
                },
                pluck="name",
                limit=1,
            )
            if rows:
                return rows[0]
            doc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": account_name,
                    "is_group": 1,
                    "parent_account": out["root"],
                    "root_type": root_type,
                    "report_type": report_type,
                }
            ).insert(ignore_permissions=True)
            return doc.name
        except Exception:
            return None

    out["asset"] = _ensure_group("Assets", "Asset", "Balance Sheet")
    out["liability"] = _ensure_group("Liabilities", "Liability", "Balance Sheet")
    out["income"] = _ensure_group("Income", "Income", "Profit and Loss")
    out["expense"] = _ensure_group("Expenses", "Expense", "Profit and Loss")
    return out


def _ensure_immobilie_account(immo_label: str, company: str) -> Optional[str]:
    """Ensure an Asset account for the Immobilie exists and return its ledger name."""
    account_variants = [immo_label, f"{immo_label} (Immobilie)"]
    for acc_name in account_variants:
        try:
            rows = frappe.get_all(
                "Account",
                filters={
                    "company": company,
                    "is_group": 0,
                    "account_name": acc_name,
                },
                pluck="name",
                limit=1,
            )
            if rows:
                return rows[0]
        except Exception:
            continue

    parent = _find_group_account(
        company,
        root_type="Asset",
        name_contains=["anlage", "immobil", "asset", "vermögen", "property"],
    ) or _find_group_account(company, root_type="Asset")
    if not parent:
        return None

    account_currency = _get_company_currency(company)
    try:
        acc_doc = frappe.get_doc(
            {
                "doctype": "Account",
                "company": company,
                "account_name": account_variants[-1],
                "is_group": 0,
                "root_type": "Asset",
                "account_type": "Fixed Asset",
                "parent_account": parent,
                **({"account_currency": account_currency} if account_currency else {}),
            }
        ).insert(ignore_permissions=True)
        return acc_doc.name
    except Exception:
        return None


def _ensure_round_off_account(company: str, *, cost_center: Optional[str]) -> Optional[str]:
    """Ensure a P&L account to post rounding differences exists and set on Company."""
    # Try to locate an existing fitting account first
    existing = frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "root_type": "Expense"},
        fields=["name", "account_name"],
    )
    round_off = None
    keywords = [
        "round off",
        "roundoff",
        "rounding",
        "rounding off",
        "rundung",
        "rundungs",
        "rundungsdifferenz",
    ]
    for row in existing:
        nm = (row.get("account_name") or row.get("name") or "").lower()
        if any(k in nm for k in keywords):
            round_off = row["name"]
            break

    if not round_off:
        parent = _find_group_account(company, root_type="Expense", name_contains=["expense", "kosten", "aufwand"])
        if not parent:
            return None
        try:
            acc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": "Round Off",
                    "is_group": 0,
                    "root_type": "Expense",
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            round_off = acc.name
        except Exception:
            return None

    try:
        comp = frappe.get_doc("Company", company)
        changed = False
        if getattr(comp, "round_off_account", None) != round_off:
            comp.round_off_account = round_off
            changed = True
        if cost_center and getattr(comp, "round_off_cost_center", None) != cost_center:
            comp.round_off_cost_center = cost_center
            changed = True
        if changed:
            comp.save(ignore_permissions=True)
        return round_off
    except Exception:
        return None


def _ensure_bank_cash_defaults(company: str) -> Optional[str]:
    """Ensure at least one Bank or Cash ledger exists and set default on Company.

    Returns the chosen bank/cash Account name.
    """
    # Prefer an existing leaf Bank/Cash account
    bank_or_cash = _find_bank_or_cash_account(company)
    if not bank_or_cash:
        # Create a simple Bank account under a suitable Asset group
        parent = _find_group_account(company, root_type="Asset", name_contains=["bank", "cash", "kasse", "liquid", "bargeld"]) or _find_group_account(company, root_type="Asset")
        if not parent:
            return None
        try:
            acc_currency = _get_company_currency(company)
            acc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": "Demo Bank",
                    "is_group": 0,
                    "root_type": "Asset",
                    "account_type": "Bank",
                    **({"account_currency": acc_currency} if acc_currency else {}),
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            bank_or_cash = acc.name
        except Exception:
            return None

    # Store on Company defaults when possible
    try:
        frappe.db.set_value("Company", company, "default_bank_account", bank_or_cash, update_modified=False)
        # If it's Cash-type, also set default_cash_account
        try:
            acc_type = frappe.db.get_value("Account", bank_or_cash, "account_type")
        except Exception:
            acc_type = None
        if acc_type == "Cash":
            try:
                frappe.db.set_value("Company", company, "default_cash_account", bank_or_cash, update_modified=False)
            except Exception:
                pass
    except Exception:
        pass
    return bank_or_cash


def _ensure_company_account_defaults(company: str, *, cost_center: Optional[str]) -> None:
    """Ensure critical Company defaults and minimal accounts exist for demos.

    Sets:
      - round_off_account (+ round_off_cost_center)
      - default_bank_account (creates a Bank ledger if none exists)
      - default_receivable_account (ensures a Receivable ledger exists)
    """
    changed_any = False
    # If CoA/accounts were deleted, first ensure a minimal structure exists so we can create leaf accounts.
    try:
        _ensure_basic_account_groups(company)
    except Exception:
        pass
    try:
        ro = _ensure_round_off_account(company, cost_center=cost_center)
        if ro:
            changed_any = True
    except Exception:
        pass
    try:
        bank = _ensure_bank_cash_defaults(company)
        if bank:
            changed_any = True
    except Exception:
        pass
    try:
        recv = _ensure_company_default_account(
            company=company,
            company_field="default_receivable_account",
            desired_account_type="Receivable",
            desired_root_type="Asset",
            keyword_candidates=["forderung", "debitor", "receivable", "kunden", "lieferungen und leistungen", "kontokorrent"],
            fallback_account_name="Debitoren",
        )
        if recv:
            changed_any = True
    except Exception:
        pass

    # Ensure Payable + Stock Received But Not Billed account defaults on Company
    try:
        pay = _ensure_payable_account_default(company)
        if pay:
            changed_any = True
    except Exception:
        pass
    # Ensure a default Expense account exists (some stock/invoice flows rely on it)
    try:
        exp = _ensure_default_expense_account(company)
        if exp:
            changed_any = True
    except Exception:
        pass
    try:
        srbnb = _ensure_srbnb_account(company)
        if srbnb:
            changed_any = True
    except Exception:
        pass
    # Ensure Fiscal Years exist for our sample posting dates (used by multiple sample modules).
    try:
        _ensure_fiscal_year(company=company, year=2025)
    except Exception:
        pass

    if changed_any:
        try:
            comp = frappe.get_doc("Company", company)
            print(
                "ℹ️  Company defaults ensured:",
                {
                    "round_off_account": getattr(comp, "round_off_account", None),
                    "round_off_cost_center": getattr(comp, "round_off_cost_center", None),
                    "default_bank_account": getattr(comp, "default_bank_account", None),
                    "default_payable_account": getattr(comp, "default_payable_account", None),
                    "default_receivable_account": getattr(comp, "default_receivable_account", None),
                    "default_expense_account": getattr(comp, "default_expense_account", None),
                    "stock_received_but_not_billed": getattr(comp, "stock_received_but_not_billed", None),
                },
            )
        except Exception:
            pass


def _ensure_srbnb_account(company: str) -> Optional[str]:
    """Ensure a 'Stock Received But Not Billed' liability account exists and is set on Company.

    Returns the account name if ensured, else None.
    """
    try:
        # 1) Existing ledger with account_type
        rows = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 0, "account_type": "Stock Received But Not Billed"},
            pluck="name",
            limit=1,
        )
        if rows:
            acc_name = rows[0]
        else:
            # 2) Create one under a Liability group
            parent = _find_group_account(
                company, root_type="Liability", name_contains=["current", "kurzfrist", "verbind", "liabil", "kreditor"]
            ) or _find_group_account(company, root_type="Liability")
            if not parent:
                return None
            acc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": "Stock Received But Not Billed",
                    "is_group": 0,
                    "root_type": "Liability",
                    "account_type": "Stock Received But Not Billed",
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            acc_name = acc.name

        # 3) Set on Company if missing or different
        comp = frappe.get_doc("Company", company)
        if getattr(comp, "stock_received_but_not_billed", None) != acc_name:
            comp.stock_received_but_not_billed = acc_name
            comp.save(ignore_permissions=True)
        return acc_name
    except Exception:
        return None


def _ensure_payable_account_default(company: str) -> Optional[str]:
    """Ensure a leaf Payable ledger exists and set as Company's default_payable_account.

    Returns the account name if ensured, else None.
    """
    return _ensure_company_default_account(
        company=company,
        company_field="default_payable_account",
        desired_account_type="Payable",
        desired_root_type="Liability",
        keyword_candidates=["kreditor", "creditor", "verbindlichkeit", "lieferungen und leistungen"],
        fallback_account_name="Kreditoren",
    )


def _ensure_default_expense_account(company: str) -> Optional[str]:
    """Ensure Company.default_expense_account points to an existing Expense ledger."""
    try:
        if not frappe.get_meta("Company").has_field("default_expense_account"):
            return None

        current = frappe.db.get_value("Company", company, "default_expense_account")
        if current and not frappe.db.exists("Account", current):
            current = None
        if current:
            return current

        rows = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 0, "root_type": "Expense"},
            pluck="name",
            limit=1,
        )
        acc_name = rows[0] if rows else None
        if not acc_name:
            acc_name = _pick_leaf_account_by_keywords(
                company=company,
                keywords=["aufwand", "kosten", "herstellung", "expense"],
                root_type="Expense",
            )
        if not acc_name:
            parent = _find_group_account(
                company, root_type="Expense", name_contains=["expense", "aufwand", "kosten"]
            ) or _find_group_account(company, root_type="Expense")
            if not parent:
                return None
            acc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "company": company,
                    "account_name": "Demo Aufwand",
                    "is_group": 0,
                    "root_type": "Expense",
                    "parent_account": parent,
                }
            ).insert(ignore_permissions=True)
            acc_name = acc.name

        try:
            frappe.db.set_value("Company", company, "default_expense_account", acc_name, update_modified=False)
        except Exception:
            pass
        return acc_name
    except Exception:
        return None


def _ensure_uom(uom_name: str) -> str:
    """Ensure a UOM exists and return its name (docname)."""
    if not uom_name:
        return uom_name
    try:
        if frappe.db.exists("UOM", uom_name):
            return uom_name
    except Exception:
        return uom_name
    try:
        frappe.get_doc({"doctype": "UOM", "uom_name": uom_name}).insert(ignore_permissions=True)
    except Exception:
        pass
    return uom_name


def _ensure_selling_price_list(currency: str) -> Optional[str]:
    """Ensure a basic selling Price List exists and return its name."""
    name = "Standard Selling"
    try:
        if frappe.db.exists("Price List", name):
            try:
                doc = frappe.get_doc("Price List", name)
                updated = False
                if getattr(doc, "currency", None) != currency:
                    doc.currency = currency
                    updated = True
                if getattr(doc, "enabled", None) in (0, None):
                    doc.enabled = 1
                    updated = True
                if getattr(doc, "selling", None) in (0, None):
                    doc.selling = 1
                    updated = True
                if updated:
                    doc.save(ignore_permissions=True)
            except Exception:
                pass
            return name

        doc = frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": name,
                "currency": currency,
                "enabled": 1,
                "selling": 1,
                "buying": 0,
            }
        ).insert(ignore_permissions=True)
        return doc.name
    except Exception:
        return None


def _ensure_item(item_code: str, company: str | None, income_account: str | None) -> str:
    """Ensure a non-stock sales item exists; set/update company income account default if provided."""
    if frappe.db.exists("Item", item_code):
        # Update item defaults for the company if an income account is provided
        if company and income_account:
            try:
                doc = frappe.get_doc("Item", item_code)
                updated = False
                # Find existing row for this company
                found = None
                try:
                    for row in getattr(doc, "item_defaults", []) or []:
                        if row.company == company:
                            found = row
                            break
                except Exception:
                    found = None
                if found:
                    if getattr(found, "income_account", None) != income_account:
                        found.income_account = income_account
                        updated = True
                else:
                    doc.append("item_defaults", {"company": company, "income_account": income_account})
                    updated = True
                if updated:
                    doc.save(ignore_permissions=True)
            except Exception:
                pass
        # Ensure demo items behave like services (non-stock), even if they pre-existed.
        try:
            doc = frappe.get_doc("Item", item_code)
            updated = False
            if getattr(doc, "is_stock_item", None) != 0:
                doc.is_stock_item = 0
                updated = True
            if getattr(doc, "is_sales_item", None) != 1:
                doc.is_sales_item = 1
                updated = True
            if getattr(doc, "disabled", None) not in (0, None):
                doc.disabled = 0
                updated = True
            if not getattr(doc, "stock_uom", None):
                doc.stock_uom = _ensure_uom("Nos")
                updated = True
            if updated:
                doc.save(ignore_permissions=True)
        except Exception:
            pass
        return item_code
    uom = _ensure_uom("Nos")
    payload = {
        "doctype": "Item",
        "item_code": item_code,
        "item_name": item_code,
        "is_stock_item": 0,
        "include_item_in_manufacturing": 0,
        "is_sales_item": 1,
        "item_group": "All Item Groups",
        "stock_uom": uom,
    }
    if company and income_account:
        payload["item_defaults"] = [
            {"company": company, "income_account": income_account}
        ]
    return frappe.get_doc(payload).insert(ignore_permissions=True).name


def _get_or_create_supplier(name: str, company: str) -> str:
    """Ensure a Supplier exists.

    Buchung läuft über das Sammelkonto Kreditoren (Company.default_payable_account);
    pro Supplier wird kein eigenes Konto gepinnt.
    """
    if frappe.db.exists("Supplier", name):
        return name

    supplier_group = _ensure_supplier_group_all()
    payload = {
        "doctype": "Supplier",
        "supplier_name": name,
        "supplier_type": "Company",
        "supplier_group": supplier_group,
    }
    return frappe.get_doc(payload).insert(ignore_permissions=True).name


def _get_or_create_bank_account_for_supplier(
    supplier: str, *, iban: Optional[str] = None
) -> Optional[str]:
    """Create a party Bank Account with IBAN for the given Supplier (idempotent)."""
    iban_clean = (iban or "").replace(" ", "").upper()
    if not iban_clean:
        return None

    rows = frappe.get_all(
        "Bank Account",
        filters={"iban": iban_clean, "party_type": "Supplier", "party": supplier},
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]

    # If a bank account with this IBAN already exists, link it to the supplier instead
    # of creating a duplicate.
    try:
        candidates = frappe.get_all(
            "Bank Account",
            filters={"iban": iban_clean},
            fields=["name", "is_company_account", "party_type", "party"],
            limit=50,
        )
    except Exception:
        candidates = []

    for c in candidates:
        if c.get("is_company_account"):
            continue
        try:
            doc = frappe.get_doc("Bank Account", c["name"])
        except Exception:
            continue
        changed = False
        if getattr(doc, "party_type", None) != "Supplier":
            doc.party_type = "Supplier"
            changed = True
        if getattr(doc, "party", None) != supplier:
            doc.party = supplier
            changed = True
        if hasattr(doc, "is_company_account") and getattr(doc, "is_company_account", 0) != 0:
            doc.is_company_account = 0
            changed = True
        if changed:
            try:
                doc.save(ignore_permissions=True)
            except Exception:
                pass
        return doc.name

    bank = _ensure_default_bank()
    doc = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Konto {supplier}",
            "bank": bank,
            "iban": iban_clean,
            "is_company_account": 0,
            "party_type": "Supplier",
            "party": supplier,
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _create_demo_invoice(
    customer: str,
    items: List[Tuple[str, float]],
    posting_date: str,
    *,
    company: Optional[str] = None,
    cost_center: Optional[str] = None,
    submit_invoice: bool = False,
) -> str | None:
    """Create a simple Sales Invoice with given items.

    Skips gracefully if company/accounts are missing.
    """
    if not company:
        try:
            company = frappe.defaults.get_global_default("company") or frappe.db.get_single_value(
                "Global Defaults", "default_company"
            )
        except Exception:
            company = None
    income_acc = _find_income_account(company) if company else None
    # try to use split income accounts by item code
    income_map: Dict[str, Optional[str]] = (
        _ensure_income_accounts_split(company) if company else {}
    )
    receivable_acc = _find_receivable_account(customer, company) if company else None

    # ensure items exist
    for code, _ in items:
        _ensure_item(code, company, income_map.get(code) or income_acc)

    if not company:
        return None
    currency = _get_company_currency(company) or "EUR"
    selling_price_list = _ensure_selling_price_list(currency)

    si = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": company,
            "customer": customer,
            "posting_date": posting_date,
            "due_date": posting_date,
            "set_posting_time": 1,
            "currency": currency,
            "conversion_rate": 1,
            **({"selling_price_list": selling_price_list} if selling_price_list else {}),
            "price_list_currency": currency,
            "plc_conversion_rate": 1,
            **({"debit_to": receivable_acc} if receivable_acc else {}),
            **({"cost_center": cost_center} if cost_center else {}),
            "items": [
                {
                    "item_code": code,
                    "qty": 1,
                    "rate": amt,
                    **({"cost_center": cost_center} if cost_center else {}),
                    # Prefer a specific income account by item; fallback to general Income
                    **({"income_account": (income_map.get(code) or income_acc)} if (income_map.get(code) or income_acc) else {}),
                }
                for code, amt in items
                if amt > 0
            ],
        }
    )
    try:
        # Let ERPNext fill defaults like receivable account, taxes, etc.
        si.set_missing_values()
        try:
            si.calculate_taxes_and_totals()
        except Exception:
            pass
        si.insert(ignore_permissions=True)
        if submit_invoice and company:
            try:
                _ensure_fiscal_year(company=company, year=int(getdate(posting_date).year))
            except Exception:
                pass
            try:
                si.submit()
            except Exception as exc:
                try:
                    print(f"⚠️  Could not submit Sales Invoice {si.name}: {exc}")
                except Exception:
                    pass
        return si.name
    except Exception as exc:
        try:
            print(f"⚠️  Sales Invoice failed for {customer} on {posting_date}: {exc}")
        except Exception:
            pass
        return None


def _find_bank_or_cash_account(company: Optional[str]) -> Optional[str]:
    """Return any leaf Bank/Cash account for the company, if available.

    Falls back to keyword matching because some CoA templates don't set account_type.
    """
    if not company:
        return None
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "is_group": 0,
            "account_type": ["in", ["Bank", "Cash"]],
        },
        pluck="name",
        limit=1,
    )
    if rows:
        return rows[0]

    acc = _pick_leaf_account_by_keywords(
        company=company,
        keywords=["bank", "kasse", "cash"],
        root_type="Asset",
    )
    if acc:
        # Best-effort set account_type based on the name
        try:
            nm = (frappe.db.get_value("Account", acc, "account_name") or acc or "").lower()
            desired = "Cash" if "kasse" in nm or "cash" in nm else "Bank"
            _ensure_account_has_type(acc, account_type=desired, root_type="Asset")
        except Exception:
            pass
        return acc

    return None


def _create_unallocated_customer_payment(
    *, company: str, customer: str, amount: float, posting_date: str, party_account: Optional[str]
) -> Optional[str]:
    """Create an unallocated 'Receive' Payment Entry for the Customer.

    This is used as a fallback when the invoice cannot be submitted or mapped.
    """
    try:
        bank_acc = _find_bank_or_cash_account(company)
        if not bank_acc:
            print("⚠️  No Bank/Cash account found for Payment Entry fallback; skipping.")
            return None

        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "company": company,
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "posting_date": posting_date,
                "reference_no": f"PAY-{customer}-{posting_date}",
                "reference_date": posting_date,
                "paid_from": party_account or _find_receivable_account(customer, company),
                "paid_to": bank_acc,
                "paid_amount": amount,
                "received_amount": amount,
                # No references -> unallocated payment
            }
        )
        pe.set_missing_values()
        pe.insert(ignore_permissions=True)
        pe.submit()
        return pe.name
    except Exception as exc:
        try:
            print(f"⚠️  Unallocated Payment Entry fallback failed for {customer}: {exc}")
        except Exception:
            pass
        return None


def _create_payment_for_invoice(inv_name: str, *, submit: bool = True) -> Optional[str]:
    """Create a Payment Entry for a given Sales Invoice, if possible.

    1) Try ERPNext's helper `get_payment_entry` and submit.
    2) If that fails, try to create an unallocated 'Receive' payment for the
       same customer and amount as a fallback (helps demo flows).
    """
    # Try the standard helper first
    try:
        from erpnext.accounts.doctype.payment_entry.payment_entry import (
            get_payment_entry,
        )
    except Exception as exc:
        print(f"⚠️  Import error for payment helper on {inv_name}: {exc}")
        get_payment_entry = None  # type: ignore

    si: Optional[frappe.model.document.Document]
    try:
        si = frappe.get_doc("Sales Invoice", inv_name)
    except Exception:
        si = None

    if get_payment_entry is not None and si is not None:
        # If already fully paid, don't try to create more payments.
        try:
            if float(getattr(si, "outstanding_amount", 0) or 0) <= 0:
                return None
        except Exception:
            pass
        try:
            pe = get_payment_entry("Sales Invoice", inv_name)
            # Keep dates aligned for determinism
            pe.posting_date = si.posting_date
            try:
                pe.reference_date = si.posting_date
            except Exception:
                pass
            try:
                if not getattr(pe, "reference_no", None):
                    pe.reference_no = f"PAY-{si.name}"
            except Exception:
                pass
            pe.set_missing_values()
            pe.set_amounts()
            if not getattr(pe, "paid_to", None):
                bank_acc = _find_bank_or_cash_account(pe.company)
                if bank_acc:
                    pe.paid_to = bank_acc
            pe.insert(ignore_permissions=True)
            if submit:
                pe.submit()
            return pe.name
        except Exception as exc:
            try:
                print(f"⚠️  get_payment_entry failed for {inv_name}: {exc}")
            except Exception:
                pass
            # Avoid fallback attempts when ERPNext says it's already paid
            try:
                msg = str(exc).lower()
                if "bereits vollständig bezahlt" in msg or "already fully paid" in msg:
                    return None
            except Exception:
                pass

    # Fallback: create an unallocated payment so there is at least a PE for demos
    try:
        if si is None:
            return None
        # Figure out a reasonable amount and party account
        amount = None
        for fld in ("rounded_total", "grand_total", "outstanding_amount"):
            try:
                val = float(getattr(si, fld)) if getattr(si, fld, None) is not None else None
                if val and val > 0:
                    amount = val
                    break
            except Exception:
                continue
        if not amount:
            # Derive from items if needed
            try:
                amount = sum((row.base_amount or row.amount or 0) for row in getattr(si, "items", []) or [])
            except Exception:
                amount = None
        if not amount or amount <= 0:
            print(f"⚠️  Could not determine positive amount for {inv_name}; skipping PE fallback.")
            return None

        return _create_unallocated_customer_payment(
            company=si.company,
            customer=si.customer,
            amount=float(amount),
            posting_date=si.posting_date,
            party_account=getattr(si, "debit_to", None),
        )
    except Exception:
        return None


def create_sample_data(
    company: str | None = None,
    *,
    with_zustand: bool = True,
    with_invoices: bool = False,
    with_payments: bool = False,
) -> Dict[str, List[str]]:
    """Create a small but complete sample dataset.

    Returns a dict with the created record names per doctype.
    """
    if not company:
        frappe.throw("`company` is required (kein impliziter Default).")

    created: Dict[str, List[str]] = {
        "Immobilie": [],
        "Wohnung": [],
        "Customer": [],
        "Contact": [],
        "Bank Account": [],
        "Mietvertrag": [],
        "Wohnungszustand": [],
        "Sales Invoice": [],
        "Payment Entry": [],
        "Supplier": [],
    }

    # 1) Hausmeister Contact + Kostenstelle + (set Company defaults) + Immobilie
    hausmeister = _get_or_create_contact("Max Meister")
    kst = _get_or_create_cost_center("Musterhaus Berlin", company)
    # Critical defaults for Sales Invoices and Payments
    _ensure_company_account_defaults(company, cost_center=kst)
    _ensure_site_default_currency(company)

    immo_label = "Musterhaus Berlin"
    immo_account = _ensure_immobilie_account(immo_label, company)
    immo_address = _get_or_create_address(
        immo_label,
        line1="Musterstraße 1",
        pincode="10115",
        city="Berlin",
    )

    # create Immobilie if absent
    immo_name = None
    existing_immo = frappe.get_all(
        "Immobilie", filters={"adresse": immo_address}, pluck="name"
    )
    if not existing_immo:
        existing_immo = frappe.get_all(
            "Immobilie", filters={"name": immo_label}, pluck="name"
        )
    if not existing_immo:
        try:
            existing_immo = frappe.get_all(
                "Immobilie", filters={"adresse__name": immo_label}, pluck="name"
            )
        except Exception:
            existing_immo = []
    if existing_immo:
        immo_name = existing_immo[0]
    else:
        immo_fields = {
            "doctype": "Immobilie",
            "immobilien_id": 1001,
            "adresse": immo_address,
            "hausmeister": hausmeister,
            "kostenstelle": kst,
        }
        if immo_account:
            immo_fields["bankkonten"] = [{"konto": immo_account, "ist_hauptkonto": 1}]
        immo = frappe.get_doc(
            immo_fields
        ).insert(ignore_permissions=True)
        immo_name = immo.name
        created["Immobilie"].append(immo_name)

    if immo_name and immo_address:
        _ensure_address_link(immo_address, "Immobilie", immo_name)

    if immo_account and immo_name:
        try:
            current_accounts = get_immobilie_bank_accounts(immo_name)
            current_primary = get_immobilie_primary_bank_account(immo_name)
            if immo_account not in current_accounts:
                immo_doc = frappe.get_doc("Immobilie", immo_name)
                immo_doc.append(
                    "bankkonten",
                    {"konto": immo_account, "ist_hauptkonto": 1 if not current_primary else 0},
                )
                immo_doc.save(ignore_permissions=True)
        except Exception:
            pass

    # 2) Wohnungen
    wohnungen_seed = [
        (1, "EG links", 62.0),
        (2, "1. OG rechts", 68.5),
        (3, "DG", 55.0),
    ]
    wohnung_names: List[str] = []
    for wid, lage, groesse in wohnungen_seed:
        rows = frappe.get_all(
            "Wohnung",
            filters={"id": wid, "immobilie": immo_name},
            pluck="name",
        )
        if rows:
            wohnung_name = rows[0]
        else:
            wohnung = frappe.get_doc(
                {
                    "doctype": "Wohnung",
                    "id": wid,
                    "name__lage_in_der_immobilie": lage,
                    "immobilie": immo_name,
                    "long_text_mthg": "Sample dataset",
                }
            ).insert(ignore_permissions=True)
            wohnung_name = wohnung.name
            created["Wohnung"].append(wohnung_name)
        wohnung_names.append(wohnung_name)
        if with_zustand:
            # Put the Zustand on the same start as first contract below (or today if parsing fails)
            ab = "2025-01-01"
            name_z = _ensure_wohnungszustand(wohnung_name, ab, groesse)
            if name_z:
                created["Wohnungszustand"].append(name_z)
                # Demo-Werte für Müllschlüssel je Wohnung setzen (idempotent)
                # Mapping per Wohnung-ID: 1→2, 2→3, 3→1
                try:
                    muell_demo = {1: 2, 2: 3, 3: 1}.get(int(wid), 1)
                except Exception:
                    muell_demo = 1
                _ensure_muellschluessel_on_zustand(name_z, muell_demo)

    # 3) Customers, Contacts & Mietverträge
    start_dates = ["2025-01-01", "2025-02-01", "2025-03-01"]
    base_rent = [800.0, 900.0, 700.0]
    bk = [180.0, 200.0, 160.0]
    hk = [90.0, 110.0, 80.0]

    for idx, wohnung_name in enumerate(wohnung_names):
        cust_name = f"Muster_Mieter_{idx+1}"
        customer = _get_or_create_customer(cust_name, company)
        contact = _get_or_create_contact(f"{cust_name} Kontakt", customer=customer)
        _ensure_contact_email(contact, DEMO_MIETER_EMAIL)
        created["Customer"].append(customer)
        created["Contact"].append(contact)

        # Deterministic, valid demo-IBAN per Customer
        iban = _demo_iban_customer(idx)
        bank_acc = _get_or_create_bank_account_for_customer(customer, iban=iban)
        if bank_acc:
            created["Bank Account"].append(bank_acc)

        def _ensure_mietvertrag_kontoverbindung(mietvertrag_name: str) -> None:
            if not (mietvertrag_name and bank_acc):
                return
            try:
                mv = frappe.get_doc("Mietvertrag", mietvertrag_name)
            except Exception:
                return
            try:
                rows = getattr(mv, "kontoverbindungen", None) or []
                if any(getattr(r, "bankkonto", None) == bank_acc for r in rows):
                    return
                mv.append("kontoverbindungen", {"bankkonto": bank_acc, "kontakt": contact})
                mv.save(ignore_permissions=True)
            except Exception:
                return

        def _maybe_create_demo_invoices() -> None:
            if not with_invoices:
                return

            posting_date = getdate("2025-01-01").isoformat()
            try:
                _ensure_fiscal_year(company=company, year=int(getdate(posting_date).year))
            except Exception:
                pass

            def _ensure_invoice(kind: str, item_code: str, amount: float) -> Optional[str]:
                remarks = f"HV Sample {kind} {customer} {posting_date}"
                try:
                    existing = frappe.get_all(
                        "Sales Invoice",
                        filters={"company": company, "customer": customer, "posting_date": posting_date, "remarks": remarks},
                        pluck="name",
                        limit=1,
                    )
                except Exception:
                    existing = []

                if existing:
                    inv_name = existing[0]
                    # Best-effort: ensure submitted if possible.
                    try:
                        if int(frappe.db.get_value("Sales Invoice", inv_name, "docstatus") or 0) != 1:
                            frappe.get_doc("Sales Invoice", inv_name).submit()
                    except Exception:
                        pass
                    return inv_name

                return _create_demo_invoice(
                    customer,
                    items=[(item_code, amount)],
                    posting_date=posting_date,
                    company=company,
                    cost_center=kst,
                    submit_invoice=True,
                )

            for kind, item_code, amount in (
                ("Miete", "Miete", base_rent[idx]),
                ("Betriebskosten", "Betriebskosten", bk[idx]),
                ("Heizkosten", "Heizkosten", hk[idx]),
            ):
                inv = _ensure_invoice(kind, item_code, amount)
                if not inv:
                    continue
                created["Sales Invoice"].append(inv)
                if with_payments:
                    pe = _create_payment_for_invoice(inv)
                    if pe:
                        created["Payment Entry"].append(pe)

        # Idempotent: skip if a contract for this Wohnung and start date already exists
        existing_mv = frappe.get_all(
            "Mietvertrag",
            filters={"wohnung": wohnung_name, "von": getdate(start_dates[idx])},
            pluck="name",
            limit=1,
        )
        if existing_mv:
            created["Mietvertrag"].append(existing_mv[0])
            _ensure_mietvertrag_kontoverbindung(existing_mv[0])
            _maybe_create_demo_invoices()
            continue

        vertrag = frappe.get_doc(
            {
                "doctype": "Mietvertrag",
                "wohnung": wohnung_name,
                "von": getdate(start_dates[idx]),
                "kunde": customer,
                "notizen": "Sample dataset",
            }
        )
        vertrag.append("mieter", {"mieter": contact, "rolle": "Hauptmieter"})
        vertrag.append("personen", {"von": getdate(start_dates[idx]), "personen": 1})
        if bank_acc:
            vertrag.append("kontoverbindungen", {"bankkonto": bank_acc, "kontakt": contact})

        # Simple starting values as one staffel entry per table
        vertrag.append("miete", {"von": getdate(start_dates[idx]), "miete": base_rent[idx]})
        vertrag.append(
            "betriebskosten", {"von": getdate(start_dates[idx]), "miete": bk[idx]}
        )
        vertrag.append("heizkosten", {"von": getdate(start_dates[idx]), "miete": hk[idx]})

        vertrag.insert(ignore_permissions=True)
        created["Mietvertrag"].append(vertrag.name)

        _maybe_create_demo_invoices()

    # 4) One demo Supplier with IBAN and payable account
    try:
        supplier_name = "Demo Lieferant GmbH"
        supplier = _get_or_create_supplier(supplier_name, company)
        created["Supplier"].append(supplier)
        # Deterministic valid IBAN for supplier as well
        iban = _demo_iban_supplier()
        supp_bank_acc = _get_or_create_bank_account_for_supplier(supplier, iban=iban)
        if supp_bank_acc:
            created["Bank Account"].append(supp_bank_acc)
    except Exception:
        # Keep sample creation resilient if accounts are missing
        pass

    frappe.db.commit()
    return created
