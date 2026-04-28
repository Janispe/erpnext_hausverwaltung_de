"""Programmatic wrapper for ERPNext's Chart of Accounts Importer.

Allows importing a Chart of Accounts from a local CSV/XLSX file by
leveraging ERPNext's builtin importer logic. Supports a validate-only
mode that runs the same validations UI uses without making changes.

Usage (bench execute):
    bench execute hausverwaltung.hausverwaltung.data_import.coa_importer.import_chart_of_accounts \
      --kwargs '{"path": "/path/to/coa.xlsx", "company": "Your Company"}'

Or from bench console / server-side code:
    from hausverwaltung.hausverwaltung.data_import.coa_importer import import_chart_of_accounts
    import_chart_of_accounts(path="/home/frappe/frappe-bench/sites/site1.local/private/files/coa.csv",
                             company="Your Company")
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import frappe

from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    get_coa,
    import_coa,
)


def _create_file_doc_from_path(path: str) -> frappe.model.document.Document:
    """Create a File doctype from a local path and return the inserted doc.

    The importer expects a File record and uses its ``file_url`` to read the
    content, so we store the file in Frappe's file system.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    # Read bytes and save into File doctype
    with open(path, "rb") as f:
        content = f.read()

    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": os.path.basename(path),
            "content": content,
            "is_private": 1,
        }
    )
    file_doc.insert(ignore_permissions=True)
    return file_doc


@frappe.whitelist()
def import_chart_of_accounts(
    *, path: str, company: str, validate_only: int | bool = 0, keep_file: int | bool = 0
) -> Dict[str, Any]:
    """Import a Chart of Accounts from ``path`` for ``company`` using ERPNext importer.

    Args:
        path: Local filesystem path to CSV/XLSX/XLS file.
        company: Target company name.
        validate_only: If truthy, run validations only; do not import.
        keep_file: If truthy, keep the created File record; otherwise delete it.

    Returns:
        Dict with details such as ``file_url`` and ``validated`` flags.

    Notes:
        The underlying importer is destructive: it clears existing accounts for
        the company before creating the new chart. Use ``validate_only=1`` to
        check the file first.
    """
    validate_only = bool(int(validate_only)) if isinstance(validate_only, (int, str)) else bool(validate_only)
    keep_file = bool(int(keep_file)) if isinstance(keep_file, (int, str)) else bool(keep_file)

    # Allow both local filesystem paths and existing site file URLs
    # - If ``path`` looks like a Frappe file URL ("/private/files/..." or "/files/..."),
    #   use it directly without creating a new File doc.
    # - Else, if it exists on the local filesystem, create a File doc from it.
    # - Else, try resolving site-relative paths like "private/files/<name>".

    file_doc: Optional[frappe.model.document.Document] = None
    file_url: str

    def _is_file_url(p: str) -> bool:
        return isinstance(p, str) and (p.startswith("/private/files/") or p.startswith("/files/"))

    # Strategy: Always create a new File doc from a concrete filesystem path when possible,
    # so we import exactly the given file and not a previously uploaded one.
    resolved_fs_path: Optional[str] = None
    if os.path.exists(path):
        resolved_fs_path = path
    elif _is_file_url(path):
        # Resolve site-relative URL to absolute path by basename
        base = os.path.basename(path)
        cand_priv = frappe.get_site_path("private", "files", base)
        cand_pub = frappe.get_site_path("public", "files", base)
        if os.path.exists(cand_priv):
            resolved_fs_path = cand_priv
        elif os.path.exists(cand_pub):
            resolved_fs_path = cand_pub
        else:
            # Fall back to use URL directly (importer can read it), but this may reuse existing file
            resolved_fs_path = None
    else:
        # Try site-relative resolution by basename
        base = os.path.basename(path)
        cand_priv = frappe.get_site_path("private", "files", base)
        cand_pub = frappe.get_site_path("public", "files", base)
        if os.path.exists(cand_priv):
            resolved_fs_path = cand_priv
        elif os.path.exists(cand_pub):
            resolved_fs_path = cand_pub

    if resolved_fs_path and os.path.exists(resolved_fs_path):
        file_doc = _create_file_doc_from_path(resolved_fs_path)
        file_url = file_doc.file_url
    else:
        if _is_file_url(path):
            file_url = path
        else:
            raise FileNotFoundError(f"File not found: {path}")

    result: Dict[str, Any] = {"file_url": file_url, "validated": False, "imported": False, "source_path": path}

    try:
        # First perform validation like the UI does
        get_coa("Chart of Accounts Importer", "All Accounts", file_name=file_url, for_validate=1)
        result["validated"] = True

        if not validate_only:
            # Run the actual import. This will clear existing accounts for the company.
            import_coa(file_url, company)
            result["imported"] = True

        frappe.db.commit()
    finally:
        # Only clean up File if we created it here
        if file_doc and not keep_file:
            try:
                frappe.delete_doc("File", file_doc.name, force=1, ignore_permissions=True)
            except Exception:
                # Keep going even if cleanup fails
                pass

    return result
