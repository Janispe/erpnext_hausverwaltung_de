"""Optional sample entry to import a Chart of Accounts via ERPNext importer.

This is intentionally disabled by default to avoid destructive changes during
``run_all``. Enable explicitly via ``enabled=True`` or by calling this import
function directly. If ``path`` is not provided, it attempts to use
``private/files/coa_importer_template.xlsx`` when present.

Usage (bench console):
    from hausverwaltung.hausverwaltung.data_import.sample import run_all
    # dry validation only
    run_all(company="Demo Hausverwaltung", include=["chart_of_accounts.create_sample_coa"],
            validate_only=True, enabled=True,
            path=frappe.get_site_path("private","files","coa_importer_template.xlsx"))

    # actual import (DESTRUCTIVE for company accounts)
    run_all(company="Demo Hausverwaltung", include=["chart_of_accounts.create_sample_coa"],
            validate_only=False, enabled=True,
            path=frappe.get_site_path("private","files","coa_importer_template.xlsx"))
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import frappe

from hausverwaltung.hausverwaltung.data_import.coa_importer import (
    import_chart_of_accounts,
)


def _default_coa_path() -> Optional[str]:
    try:
        p = frappe.get_site_path("private", "files", "coa_importer_template.xlsx")
        return p if os.path.exists(p) else None
    except Exception:
        return None


def create_sample_coa(
    *,
    company: str = "Demo Hausverwaltung",
    enabled: bool = False,
    validate_only: bool = True,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Importiert einen Kontenrahmen per ERPNext-CoA-Importer (optional).

    - Läuft standardmäßig NICHT (``enabled=False``), um versehentliche Löschung
      bestehender Konten zu vermeiden.
    - Wird nur ausgeführt, wenn ``enabled=True`` und eine Datei verfügbar ist.

    Args:
        company: Ziel-Firma
        enabled: Explizit aktivieren, sonst wird übersprungen
        validate_only: Nur prüfen, nicht importieren
        path: Pfad zur CoA-Datei (CSV/XLSX). Fallback: ``private/files/coa_importer_template.xlsx``
    """
    if not enabled:
        return {"skipped": True, "reason": "disabled", "company": company}

    file_path = path or _default_coa_path()
    if not file_path:
        return {"skipped": True, "reason": "file_missing", "company": company}

    # Be forgiving if a weird relative path was provided (e.g. './frontend/private/files/...')
    # Try to resolve to site private/public files by basename before invoking the importer.
    try:
        if not (os.path.exists(file_path) or str(file_path).startswith(("/private/files/", "/files/"))):
            base = os.path.basename(str(file_path))
            cand_priv = frappe.get_site_path("private", "files", base)
            cand_pub = frappe.get_site_path("public", "files", base)
            if os.path.exists(cand_priv):
                file_path = cand_priv
            elif os.path.exists(cand_pub):
                file_path = cand_pub
            else:
                return {"skipped": True, "reason": f"file_missing: {file_path}", "company": company}
    except Exception:
        # fall through to importer and let it raise/handle
        pass

    res = import_chart_of_accounts(path=file_path, company=company, validate_only=validate_only)
    return {"skipped": False, "result": res, "company": company}
