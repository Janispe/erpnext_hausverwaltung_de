from __future__ import annotations

import json
import os
from pathlib import Path
import hashlib
from typing import Any

import frappe


_PERMISSION_FIELDS = (
    "read",
    "write",
    "create",
    "delete",
    "submit",
    "cancel",
    "amend",
    "report",
    "export",
    "import",
    "share",
    "print",
    "email",
    "select",
)


def _fixture_name(*, role: str, parent: str, permlevel: int) -> str:
    digest = hashlib.sha1(f"{role}:{parent}:{permlevel}".encode("utf-8")).hexdigest()[:10]
    return f"admin_{digest}"


def _ensure_role_perms(*, role: str, doctypes: list[str]) -> dict[str, Any]:
    if not role:
        role = "Administrator"

    if not frappe.db.exists("Role", role):
        frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)

    created = 0
    updated = 0
    errors: list[str] = []

    for doctype in doctypes:
        try:
            existing = (
                frappe.get_all(
                    "Custom DocPerm",
                    filters={"parent": doctype, "role": role, "permlevel": 0},
                    pluck="name",
                )
                or []
            )

            if not existing:
                doc = frappe.get_doc(
                    {
                        "doctype": "Custom DocPerm",
                        "parent": doctype,
                        "role": role,
                        "permlevel": 0,
                        "if_owner": 0,
                        "docstatus": 0,
                        **{field: 1 for field in _PERMISSION_FIELDS},
                    }
                )
                doc.insert(ignore_permissions=True)
                created += 1
                continue

            for name in existing:
                doc = frappe.get_doc("Custom DocPerm", name)
                changed = False

                if getattr(doc, "if_owner", 0):
                    doc.if_owner = 0
                    changed = True

                for field in _PERMISSION_FIELDS:
                    if getattr(doc, field, 0) != 1:
                        setattr(doc, field, 1)
                        changed = True

                if changed:
                    doc.save(ignore_permissions=True)
                    updated += 1
        except Exception as exc:
            errors.append(f"{doctype}: {exc}")

    frappe.clear_cache()
    frappe.db.commit()

    return {
        "role": role,
        "doctypes": len(doctypes),
        "created": created,
        "updated": updated,
        "errors": errors,
    }


def run(role: str = "Administrator") -> dict[str, Any]:
    doctypes = frappe.get_all("DocType", pluck="name") or []
    return _ensure_role_perms(role=role, doctypes=doctypes)


def run_for_custom_doctypes(role: str = "System Manager") -> dict[str, Any]:
    doctypes = [
        row[0]
        for row in frappe.db.sql("SELECT DISTINCT parent FROM `tabCustom DocPerm`")
    ]
    result = _ensure_role_perms(role=role, doctypes=doctypes)
    result["doctypes_list"] = doctypes
    return result


def write_fixture(app: str | None = None, role: str = "Administrator") -> dict[str, Any]:
    app = (app or os.environ.get("APP") or "hausverwaltung").strip() or "hausverwaltung"

    fixture_path = Path(frappe.get_app_path(app, "fixtures", "custom_docperm.json"))
    fixture_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing = json.loads(fixture_path.read_text(encoding="utf-8")) if fixture_path.exists() else []
    except Exception:
        existing = []

    if not isinstance(existing, list):
        existing = []

    existing = [row for row in existing if isinstance(row, dict) and row.get("role") != role]

    admin_rows: list[dict[str, Any]] = []
    doctypes = frappe.get_all("DocType", pluck="name") or []
    for doctype in doctypes:
        admin_rows.append(
            {
                "doctype": "Custom DocPerm",
                "name": _fixture_name(role=role, parent=doctype, permlevel=0),
                "parent": doctype,
                "role": role,
                "permlevel": 0,
                "if_owner": 0,
                "docstatus": 0,
                **{field: 1 for field in _PERMISSION_FIELDS},
            }
        )

    merged = existing + admin_rows

    tmp_path = fixture_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(merged, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    tmp_path.replace(fixture_path)

    return {
        "fixture_path": str(fixture_path),
        "role": role,
        "doctypes": len(doctypes),
        "existing_rows": len(existing),
        "admin_rows": len(admin_rows),
        "total_rows": len(merged),
    }
