from __future__ import annotations

from typing import Iterable

import frappe


def ensure_role_profile(
    *,
    role_profile: str,
    roles: Iterable[str],
    remove_roles: Iterable[str] = (),
) -> dict:
    """Create/update a Role Profile by adding missing roles (idempotent).

    Notes:
      - Adds missing roles from `roles`.
      - Optionally removes roles listed in `remove_roles`.
      - Skips roles that don't exist on the site.
      - No-ops when the Role Profile DocType isn't available.
    """

    try:
        if not frappe.db.exists("DocType", "Role Profile"):
            return {"status": "skipped", "reason": "doctype-missing"}
    except Exception:
        return {"status": "skipped", "reason": "doctype-check-failed"}

    profile_name = None
    try:
        if frappe.db.exists("Role Profile", role_profile):
            profile_name = role_profile
        else:
            profile_name = frappe.db.get_value("Role Profile", {"role_profile": role_profile}, "name")
    except Exception:
        profile_name = None

    created = False
    if profile_name:
        doc = frappe.get_doc("Role Profile", profile_name)
    else:
        doc = frappe.get_doc({"doctype": "Role Profile", "role_profile": role_profile})
        created = True

    existing_roles = {row.role for row in (doc.get("roles") or []) if row.role}
    added: list[str] = []
    removed: list[str] = []

    for role in roles:
        role = (role or "").strip()
        if not role or role in existing_roles:
            continue
        try:
            if not frappe.db.exists("Role", role):
                continue
        except Exception:
            continue
        doc.append("roles", {"role": role})
        existing_roles.add(role)
        added.append(role)

    remove_set = {(r or "").strip() for r in (remove_roles or ()) if (r or "").strip()}
    if remove_set and doc.get("roles"):
        for row in list(doc.get("roles") or []):
            r = (getattr(row, "role", None) or "").strip()
            if r and r in remove_set:
                try:
                    doc.remove(row)
                except Exception:
                    continue
                removed.append(r)

    if created:
        doc.insert(ignore_permissions=True)
    else:
        if added or removed:
            doc.save(ignore_permissions=True)

    return {"status": "ok", "created": created, "added": added, "removed": removed, "name": doc.name}
