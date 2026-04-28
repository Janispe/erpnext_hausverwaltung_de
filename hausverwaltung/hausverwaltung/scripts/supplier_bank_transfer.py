from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import frappe
from frappe.utils import now

BANK_FIELDS = (
    "name",
    "bank_name",
)

SUPPLIER_FIELDS = (
    "name",
    "supplier_name",
    "supplier_group",
    "supplier_type",
    "tax_id",
    "default_currency",
    "country",
    "disabled",
)

EIGENTUEMER_FIELDS = (
    "name",
    "eigentuemer_name",
    "contact",
)

BANK_ACCOUNT_FIELDS = (
    "name",
    "account_name",
    "bank",
    "party_type",
    "party",
    "is_company_account",
    "company",
    "account",
    "iban",
    "swift_number",
    "branch_code",
    "bank_account_no",
    "account_no",
    "disabled",
)


def _as_name_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(part).strip() for part in value]
    else:
        candidates = [str(value).strip()]

    return [name for name in candidates if name]


def _default_export_path() -> str:
    ts = now().replace(" ", "_").replace(":", "-")
    app_root = Path(frappe.get_app_path("hausverwaltung")).parent
    return str(app_root / "import" / "supplier_bank_transfer" / f"supplier_bank_transfer_{ts}.json")


def _write_json(path: str, payload: dict[str, Any]) -> str:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(frappe.as_json(payload, indent=2), encoding="utf-8")
    return str(out_path)


def _read_json(path: str) -> dict[str, Any]:
    in_path = Path(path)
    if not in_path.exists():
        frappe.throw(f"Datei nicht gefunden: {in_path}")

    data = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        frappe.throw("Ungültiges JSON-Format: Erwartet ein Objekt auf Top-Level.")
    return data


def _get_valid_columns(doctype: str) -> set[str]:
    return set(frappe.get_meta(doctype).get_valid_columns())


def _pick_existing_fields(record: dict[str, Any], valid_columns: set[str]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key in valid_columns and key != "doctype"}


def _query_fields(doctype: str, preferred_fields: tuple[str, ...]) -> list[str]:
    valid = _get_valid_columns(doctype)
    return [field for field in preferred_fields if field in valid]


def _default_supplier_group() -> str:
    if frappe.db.exists("Supplier Group", "All Supplier Groups"):
        return "All Supplier Groups"

    existing = frappe.get_all("Supplier Group", fields=["name"], limit=1)
    if existing:
        return existing[0]["name"]

    doc = frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": "All Supplier Groups"})
    doc.insert(ignore_permissions=True)
    return doc.name


def _upsert_doc(
    *,
    doctype: str,
    record: dict[str, Any],
    valid_columns: set[str],
    update_existing: bool,
    dry_run: bool,
) -> str:
    filtered = _pick_existing_fields(record, valid_columns)
    name = str(record.get("name") or filtered.get("name") or "").strip()

    if not name:
        frappe.throw(f"{doctype}: Datensatz ohne name kann nicht importiert werden.")

    if doctype == "Supplier" and not filtered.get("supplier_group"):
        filtered["supplier_group"] = _default_supplier_group()

    if doctype == "Eigentuemer" and not filtered.get("eigentuemer_name"):
        filtered["eigentuemer_name"] = name

    if doctype == "Bank Account" and not filtered.get("party_type"):
        filtered["party_type"] = "Supplier"

    if doctype == "Bank Account" and not filtered.get("is_company_account"):
        filtered["is_company_account"] = 0

    if frappe.db.exists(doctype, name):
        if not update_existing:
            return "skipped"

        if dry_run:
            return "updated"

        doc = frappe.get_doc(doctype, name)
        for key, value in filtered.items():
            if key == "name":
                continue
            setattr(doc, key, value)
        doc.save(ignore_permissions=True)
        return "updated"

    if dry_run:
        return "created"

    filtered["doctype"] = doctype
    filtered["name"] = name
    doc = frappe.get_doc(filtered)
    doc.insert(ignore_permissions=True)
    return "created"


def export_supplier_bank_data(
    path: str | None = None,
    supplier_names: list[str] | str | None = None,
    include_all_suppliers: int | bool = 0,
    eigentuemer_names: list[str] | str | None = None,
    include_all_eigentuemer: int | bool = 0,
) -> dict[str, Any]:
    """Exportiert Supplier + Eigentuemer + Bank + Bank Accounts als JSON.

    Args:
        path: Optionaler Ausgabe-Pfad. Standard: sites/<site>/private/exports/supplier_bank_transfer_<timestamp>.json
        supplier_names: Optional Liste oder CSV von Supplier-Namen.
        include_all_suppliers: 1/True exportiert alle Supplier; sonst nur Supplier mit Bank Account.
        eigentuemer_names: Optional Liste oder CSV von Eigentuemer-Namen.
        include_all_eigentuemer: 1/True exportiert alle Eigentuemer; sonst nur mit Bank Account.
    """
    explicit_suppliers = _as_name_list(supplier_names)
    explicit_eigentuemer = _as_name_list(eigentuemer_names)

    if explicit_suppliers:
        suppliers = explicit_suppliers
    else:
        include_all = bool(int(include_all_suppliers)) if isinstance(include_all_suppliers, str) else bool(include_all_suppliers)
        if include_all:
            suppliers = frappe.get_all("Supplier", pluck="name") or []
        else:
            suppliers = sorted(
                {
                    row["party"]
                    for row in frappe.get_all(
                        "Bank Account",
                        filters={"party_type": "Supplier"},
                        fields=["party"],
                        limit_page_length=0,
                    )
                    if row.get("party")
                }
            )

    if explicit_eigentuemer:
        eigentuemer = explicit_eigentuemer
    else:
        include_all_owner = (
            bool(int(include_all_eigentuemer))
            if isinstance(include_all_eigentuemer, str)
            else bool(include_all_eigentuemer)
        )
        if include_all_owner:
            eigentuemer = frappe.get_all("Eigentuemer", pluck="name") or []
        else:
            eigentuemer = sorted(
                {
                    row["party"]
                    for row in frappe.get_all(
                        "Bank Account",
                        filters={"party_type": "Eigentuemer"},
                        fields=["party"],
                        limit_page_length=0,
                    )
                    if row.get("party")
                }
            )

    supplier_rows = []
    if suppliers:
        supplier_query_fields = _query_fields("Supplier", SUPPLIER_FIELDS)
        supplier_rows = frappe.get_all(
            "Supplier",
            filters={"name": ["in", suppliers]},
            fields=supplier_query_fields,
            limit_page_length=0,
            order_by="name asc",
        )

    eigentuemer_rows = []
    if eigentuemer:
        eigentuemer_query_fields = _query_fields("Eigentuemer", EIGENTUEMER_FIELDS)
        eigentuemer_rows = frappe.get_all(
            "Eigentuemer",
            filters={"name": ["in", eigentuemer]},
            fields=eigentuemer_query_fields,
            limit_page_length=0,
            order_by="name asc",
        )

    supplier_names_set = {row["name"] for row in supplier_rows}
    eigentuemer_names_set = {row["name"] for row in eigentuemer_rows}
    parties = sorted(supplier_names_set | eigentuemer_names_set)

    bank_account_rows = []
    if parties:
        bank_account_query_fields = _query_fields("Bank Account", BANK_ACCOUNT_FIELDS)
        bank_account_rows = frappe.get_all(
            "Bank Account",
            filters={
                "party_type": ["in", ["Supplier", "Eigentuemer"]],
                "party": ["in", parties],
            },
            fields=bank_account_query_fields,
            limit_page_length=0,
            order_by="name asc",
        )

    bank_names = sorted({row["bank"] for row in bank_account_rows if row.get("bank")})

    bank_rows = []
    if bank_names:
        bank_query_fields = _query_fields("Bank", BANK_FIELDS)
        bank_rows = frappe.get_all(
            "Bank",
            filters={"name": ["in", bank_names]},
            fields=bank_query_fields,
            limit_page_length=0,
            order_by="name asc",
        )

    payload = {
        "meta": {
            "exported_at": now(),
            "site": frappe.local.site,
            "app": "hausverwaltung",
            "version": 1,
        },
        "bank": bank_rows,
        "supplier": supplier_rows,
        "eigentuemer": eigentuemer_rows,
        "bank_account": bank_account_rows,
    }

    output_path = _write_json(path or _default_export_path(), payload)

    return {
        "path": output_path,
        "bank": len(bank_rows),
        "supplier": len(supplier_rows),
        "eigentuemer": len(eigentuemer_rows),
        "bank_account": len(bank_account_rows),
    }


def import_supplier_bank_data(
    path: str,
    update_existing: int | bool = 1,
    dry_run: int | bool = 0,
    setup_payable_accounts: int | bool = 1,
    company: str | None = None,
) -> dict[str, Any]:
    """Importiert Supplier + Eigentuemer + Bank + Bank Account aus JSON-Datei.

    Reihenfolge: Bank -> Supplier -> Eigentuemer -> Bank Account.

    Args:
        path: JSON-Datei aus export_supplier_bank_data.
        update_existing: 1/True aktualisiert bestehende Datensätze anhand name.
        dry_run: 1/True führt keine Schreiboperation aus.
        setup_payable_accounts: 1/True führt nach dem Import zusätzlich
            `setup_payable_account_for_all(company)` aus — sichert das
            Standard-Kreditorenkonto auf der Company und setzt es auf alle
            Lieferanten. Default an. Bei dry_run automatisch übersprungen.
        company: Company für die Payable-Account-Logik. Wenn nicht gesetzt:
            Frappe-Default-Company.
    """
    data = _read_json(path)
    update_flag = bool(int(update_existing)) if isinstance(update_existing, str) else bool(update_existing)
    dry_run_flag = bool(int(dry_run)) if isinstance(dry_run, str) else bool(dry_run)
    setup_payable_flag = (
        bool(int(setup_payable_accounts))
        if isinstance(setup_payable_accounts, str)
        else bool(setup_payable_accounts)
    )

    results: dict[str, dict[str, int]] = {
        "Bank": {"created": 0, "updated": 0, "skipped": 0, "errors": 0},
        "Supplier": {"created": 0, "updated": 0, "skipped": 0, "errors": 0},
        "Eigentuemer": {"created": 0, "updated": 0, "skipped": 0, "errors": 0},
        "Bank Account": {"created": 0, "updated": 0, "skipped": 0, "errors": 0},
    }
    errors: list[str] = []

    valid_columns = {
        "Bank": _get_valid_columns("Bank"),
        "Supplier": _get_valid_columns("Supplier"),
        "Eigentuemer": _get_valid_columns("Eigentuemer"),
        "Bank Account": _get_valid_columns("Bank Account"),
    }

    batches = (
        ("Bank", data.get("bank") or []),
        ("Supplier", data.get("supplier") or []),
        ("Eigentuemer", data.get("eigentuemer") or []),
        ("Bank Account", data.get("bank_account") or []),
    )

    for doctype, records in batches:
        for record in records:
            try:
                if not isinstance(record, dict):
                    raise ValueError(f"Ungültiger Datensatz-Typ in {doctype}: {type(record)}")

                status = _upsert_doc(
                    doctype=doctype,
                    record=record,
                    valid_columns=valid_columns[doctype],
                    update_existing=update_flag,
                    dry_run=dry_run_flag,
                )
                results[doctype][status] += 1
            except Exception as exc:
                results[doctype]["errors"] += 1
                record_name = record.get("name") if isinstance(record, dict) else "<unknown>"
                errors.append(f"{doctype} {record_name}: {exc}")

    if not dry_run_flag:
        frappe.db.commit()

    payable_setup: dict[str, Any] | None = None
    if setup_payable_flag and not dry_run_flag:
        try:
            from hausverwaltung.hausverwaltung.scripts.payable_account import (
                setup_payable_account_for_all,
            )
            target_company = (
                company
                or frappe.db.get_default("Company")
                or frappe.db.get_value("Global Defaults", None, "default_company")
            )
            if target_company:
                payable_setup = setup_payable_account_for_all(target_company)
            else:
                errors.append(
                    "setup_payable_accounts übersprungen: keine Default-Company gefunden. "
                    "Bitte company= explizit übergeben."
                )
        except Exception as exc:
            errors.append(f"setup_payable_accounts fehlgeschlagen: {exc}")

    return {
        "path": str(Path(path)),
        "update_existing": update_flag,
        "dry_run": dry_run_flag,
        "results": results,
        "errors": errors,
        "payable_setup": payable_setup,
    }
