from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import os

import frappe


def _ensure_default_role_profile() -> dict[str, Any]:
    try:
        from hausverwaltung.hausverwaltung.utils.role_profiles import ensure_role_profile
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    try:
        return ensure_role_profile(
            role_profile="Hausverwaltung",
            roles=("Hausverwalter", "Hausverwalter (Buchung)", "Accounts User", "Sales User", "Purchase User"),
            remove_roles=("System Manager",),
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _is_effectively_unset(current: Any, default_values: tuple[Any, ...]) -> bool:
    if current in (None, "", 0, False):
        return True
    return current in default_values


def _env_bool(key: str, default: bool) -> bool:
    val = (os.environ.get(key) or "").strip().lower()
    if not val:
        return default
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _abbr_from_name(name: str) -> str:
    parts = [p[0] for p in str(name).split() if p]
    abbr = "".join(parts).upper()
    return (abbr or str(name)[:3].upper()).strip()


def _set_single_value(*, doctype: str, fieldname: str, value: Any, force: bool) -> bool:
    try:
        current = frappe.db.get_single_value(doctype, fieldname)
    except Exception:
        current = None

    if not force and not _is_effectively_unset(current, ()):
        return False

    try:
        frappe.db.set_single_value(doctype, fieldname, value)
        return True
    except Exception:
        return False


def _set_single_value_unset_or_default(
    *,
    doctype: str,
    fieldname: str,
    value: Any,
    force: bool,
    default_values: tuple[Any, ...],
) -> bool:
    try:
        current = frappe.db.get_single_value(doctype, fieldname)
    except Exception:
        current = None

    if not force and not _is_effectively_unset(current, default_values):
        return False

    try:
        frappe.db.set_single_value(doctype, fieldname, value)
        return True
    except Exception:
        return False


def _ensure_company(
    *,
    company_name: str,
    country: str,
    currency: str,
    force: bool,
) -> dict:
    if not company_name:
        return {"company": None, "created": False, "updated": False}

    created = False
    updated = False

    if not frappe.db.exists("Company", company_name):
        doc = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": company_name,
                "abbr": _abbr_from_name(company_name),
                "country": country,
                "default_currency": currency,
            }
        ).insert(ignore_permissions=True)
        created = True
        return {"company": doc.name, "created": created, "updated": updated}

    doc = frappe.get_doc("Company", company_name)
    if force or not getattr(doc, "abbr", None):
        doc.abbr = getattr(doc, "abbr", None) or _abbr_from_name(company_name)
        updated = True
    if force or not getattr(doc, "country", None):
        doc.country = getattr(doc, "country", None) or country
        updated = True
    if force or not getattr(doc, "default_currency", None):
        doc.default_currency = getattr(doc, "default_currency", None) or currency
        updated = True

    if updated:
        doc.save(ignore_permissions=True)

    return {"company": doc.name, "created": created, "updated": updated}


def _ensure_round_off_account(*, company: str) -> dict:
    """Ensure 'Round Off' account exists and is set on Company.

    ERPNext setup-wizard creates this normally; without it, Sales/Purchase Invoice submit
    fails with 'Please mention Round Off Account in Company' for any rounding diff.
    """
    if not company:
        return {"created": False, "set_default": False}

    abbr = frappe.db.get_value("Company", company, "abbr") or _abbr_from_name(company)
    account_name = f"Round Off - {abbr}"

    created = False
    if not frappe.db.exists("Account", account_name):
        # Find an Expense group as parent (any of: Expenses, Indirect Expenses, root Expense)
        parent = frappe.db.get_value(
            "Account",
            filters={"company": company, "is_group": 1, "root_type": "Expense"},
            fieldname="name",
            order_by="lft asc",
        )
        if not parent:
            return {"created": False, "set_default": False, "error": "no expense parent"}
        try:
            frappe.get_doc({
                "doctype": "Account",
                "account_name": "Round Off",
                "parent_account": parent,
                "company": company,
                "is_group": 0,
                "root_type": "Expense",
                "account_type": "Round Off",
            }).insert(ignore_permissions=True)
            created = True
        except Exception as exc:
            return {"created": False, "set_default": False, "error": str(exc)}

    set_default = False
    current = frappe.db.get_value("Company", company, "round_off_account")
    if current != account_name:
        frappe.db.set_value("Company", company, "round_off_account", account_name)
        set_default = True

    return {"created": created, "set_default": set_default}


def _ensure_default_price_lists(*, currency: str) -> dict:
    """Create the default 'Standard Selling' / 'Standard Buying' Price Lists if missing.

    ERPNext usually creates these via the setup-wizard. Since we skip the wizard,
    Sales/Purchase Invoice creation fails with `Could not find Price List: Standard Selling`.
    """
    if not frappe.db.exists("DocType", "Price List"):
        return {"created": []}
    created: list[str] = []
    for name, buying, selling in (
        ("Standard Selling", 0, 1),
        ("Standard Buying", 1, 0),
    ):
        if frappe.db.exists("Price List", name):
            continue
        try:
            frappe.get_doc({
                "doctype": "Price List",
                "price_list_name": name,
                "currency": currency or "EUR",
                "buying": buying,
                "selling": selling,
                "enabled": 1,
            }).insert(ignore_permissions=True)
            created.append(name)
        except Exception:
            continue
    return {"created": created}


_HV_PARTY_TYPES: tuple[tuple[str, str], ...] = (
    ("Customer", "Receivable"),
    ("Supplier", "Payable"),
)
_HV_PARTY_TYPES_REMOVED: tuple[str, ...] = ("Employee", "Shareholder")


def _ensure_default_party_types() -> dict:
    """Ensure ERPNext-standard Party Types exist (Customer, Supplier).

    Required by Payment Entry / Payment Reconciliation Tool to filter parties.
    Without these only custom Party Types (e.g. Eigentuemer) are selectable.

    `Employee` and `Shareholder` are intentionally removed: the Hausverwaltung
    workflow uses only Kunde (Customer), Lieferant (Supplier) and Eigentuemer
    in the Zahlungsabgleich. Records for the removed types are deleted, but only
    if they're not in use anywhere — otherwise we leave them and just log.
    """
    if not frappe.db.exists("DocType", "Party Type"):
        return {"created": [], "deleted": []}

    created: list[str] = []
    for party_type, account_type in _HV_PARTY_TYPES:
        if frappe.db.exists("Party Type", party_type):
            continue
        try:
            frappe.get_doc({
                "doctype": "Party Type",
                "party_type": party_type,
                "account_type": account_type,
            }).insert(ignore_permissions=True)
            created.append(party_type)
        except Exception:
            continue

    deleted: list[str] = []
    skipped: list[dict] = []
    for party_type in _HV_PARTY_TYPES_REMOVED:
        if not frappe.db.exists("Party Type", party_type):
            continue
        usage = 0
        for dt, fld in (
            ("Payment Entry", "party_type"),
            ("Journal Entry Account", "party_type"),
            ("GL Entry", "party_type"),
            ("Payment Ledger Entry", "party_type"),
        ):
            try:
                if frappe.db.exists("DocType", dt):
                    usage += frappe.db.count(dt, {fld: party_type})
            except Exception:
                continue
        if usage:
            skipped.append({"party_type": party_type, "usage": usage})
            continue
        try:
            frappe.delete_doc("Party Type", party_type, force=1, ignore_permissions=True)
            deleted.append(party_type)
        except Exception as exc:
            skipped.append({"party_type": party_type, "error": str(exc)})

    return {"created": created, "deleted": deleted, "skipped": skipped}


def _ensure_default_cost_center(*, company: str) -> dict:
    """Ensure the company has a root + 'Main' Cost Center (mirrors ERPNext.create_default_cost_center).

    Re-creates them if they were deleted (e.g. by import-cleanup). Sets `Company.cost_center`,
    `round_off_cost_center` and `depreciation_cost_center`.
    """
    if not company:
        return {"created_root": False, "created_main": False, "set_default": False}

    abbr = frappe.db.get_value("Company", company, "abbr") or _abbr_from_name(company)
    root_name = f"{company} - {abbr}"
    main_name = f"Main - {abbr}"

    created_root = False
    if not frappe.db.exists("Cost Center", root_name):
        cc = frappe.get_doc({
            "doctype": "Cost Center",
            "cost_center_name": company,
            "company": company,
            "is_group": 1,
            "parent_cost_center": None,
        })
        cc.flags.ignore_permissions = True
        cc.flags.ignore_mandatory = True  # parent_cost_center is mandatory but root has none
        cc.insert()
        created_root = True

    created_main = False
    if not frappe.db.exists("Cost Center", main_name):
        cc = frappe.get_doc({
            "doctype": "Cost Center",
            "cost_center_name": "Main",
            "parent_cost_center": root_name,
            "company": company,
            "is_group": 0,
        })
        cc.flags.ignore_permissions = True
        cc.insert()
        created_main = True

    set_default = False
    if frappe.db.exists("Cost Center", main_name):
        for fieldname in ("cost_center", "round_off_cost_center", "depreciation_cost_center"):
            current = frappe.db.get_value("Company", company, fieldname)
            if current != main_name:
                frappe.db.set_value("Company", company, fieldname, main_name)
                set_default = True

    return {"created_root": created_root, "created_main": created_main, "set_default": set_default}


def _ensure_user_language(*, user: str, language: str, force: bool) -> bool:
    try:
        doc = frappe.get_doc("User", user)
    except Exception:
        return False

    current = (getattr(doc, "language", None) or "").strip()
    if not force and not _is_effectively_unset(current, ("en",)):
        return False

    doc.language = language
    doc.save(ignore_permissions=True)
    return True


def _ensure_user_time_zone(*, user: str, time_zone: str, force: bool) -> bool:
    try:
        doc = frappe.get_doc("User", user)
    except Exception:
        return False

    current = (getattr(doc, "time_zone", None) or "").strip()
    if not force and not _is_effectively_unset(current, ("Asia/Kolkata",)):
        return False

    doc.time_zone = time_zone
    doc.save(ignore_permissions=True)
    return True


def _ensure_global_default(
    *,
    key: str,
    value: Any,
    force: bool,
    default_values: tuple[Any, ...] = (),
) -> bool:
    try:
        current = frappe.defaults.get_global_default(key)
    except Exception:
        current = None

    if not force and not _is_effectively_unset(current, default_values):
        return False

    try:
        frappe.defaults.set_global_default(key, value)
        return True
    except Exception:
        return False


def _ensure_user_default(
    *,
    user: str,
    key: str,
    value: Any,
    force: bool,
    default_values: tuple[Any, ...] = (),
) -> bool:
    try:
        current = frappe.defaults.get_user_default(key, user=user)
    except Exception:
        current = None

    if not force and not _is_effectively_unset(current, default_values):
        return False

    try:
        frappe.defaults.set_user_default(key, value, user=user)
        return True
    except Exception:
        return False


def _ensure_chart_of_accounts(*, company: str, template: str) -> dict:
    if not company:
        return {"created": False, "error": "no-company"}

    try:
        account_count = int(frappe.db.count("Account", {"company": company}) or 0)
    except Exception:
        account_count = 0

    if account_count:
        return {"created": False, "skipped": True, "reason": "accounts-exist", "accounts": account_count}

    try:
        from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts

        create_charts(company, chart_template=template)
        return {"created": True, "template": template}
    except Exception as exc:
        return {"created": False, "error": str(exc)}


def _resolve_language_name(language: str) -> str:
    lang = (language or "").strip()
    if not lang:
        return "English"

    try:
        # Most sites use the language code as the docname (e.g. "de") with a language_name like "German"
        language_name = frappe.db.get_value("Language", lang, "language_name")
        if language_name:
            return str(language_name).strip()
    except Exception:
        pass

    return lang


def _run_frappe_setup_wizard(*, language: str, country: str, time_zone: str, currency: str, force: bool) -> dict[str, Any]:
    """Run (or apply key parts of) Frappe's setup wizard.

    When the site is already marked setup-complete, Frappe will no-op the wizard; in that case we
    still apply the "global settings" stage to get date/number formats, scheduler defaults, etc.
    """

    try:
        from frappe.desk.page.setup_wizard import setup_wizard as sw
    except Exception as exc:
        return {"status": "error", "error": f"import-failed: {exc}"}

    args_in = {
        # Frappe wizard expects "timezone" (not "time_zone")
        "country": country,
        "timezone": time_zone,
        "currency": currency,
        # setup_wizard.get_language_code looks up by Language.language_name, so we pass that
        "language": _resolve_language_name(language),
        # update_global_settings references args.lang (bug/legacy), so include it too
        "lang": _resolve_language_name(language),
        # keep it quiet/deterministic for automated runs
        "enable_telemetry": 0,
        "allow_recording_first_session": 0,
    }

    try:
        already_complete = bool(frappe.is_setup_complete())
    except Exception:
        already_complete = False

    if not already_complete:
        try:
            return {"status": "ok", "mode": "setup_complete", "result": sw.setup_complete(args_in)}
        except Exception as exc:
            return {"status": "error", "mode": "setup_complete", "error": str(exc)}

    # If the wizard is already marked complete, re-apply the key global settings stage.
    try:
        args = sw.parse_args(args_in)
        sw.update_global_settings(args)
        sw.run_post_setup_complete(args)
        return {"status": "ok", "mode": "global_settings_only", "already_complete": True, "forced": bool(force)}
    except Exception as exc:
        return {"status": "error", "mode": "global_settings_only", "error": str(exc)}


def _mark_setup_complete(*, force: bool) -> dict[str, Any]:
    if not frappe.db.table_exists("Installed Application"):
        return {"updated": 0, "skipped": True, "reason": "missing-table"}

    try:
        apps = frappe.get_all(
            "Installed Application",
            filters={"has_setup_wizard": 1},
            fields=["name", "app_name", "is_setup_complete"],
        )
    except Exception as exc:
        return {"updated": 0, "error": str(exc)}

    updated = 0
    for app in apps:
        if not force and int(app.get("is_setup_complete") or 0) == 1:
            continue
        try:
            frappe.db.set_value("Installed Application", app.get("name"), "is_setup_complete", 1)
            updated += 1
        except Exception:
            continue

    try:
        frappe.db.set_single_value("System Settings", "setup_complete", 1)
    except Exception:
        pass

    # Frontend reads `frappe.boot.sysdefaults.setup_complete` from `tabDefaultValue` (scope=__default),
    # which is independent of System Settings. Without this, the desk JS triggers the setup-wizard
    # on every page load. Also remove any leftover `desktop:home_page=setup-wizard` default.
    try:
        frappe.defaults.set_global_default("setup_complete", 1)
    except Exception:
        pass
    try:
        frappe.db.delete("DefaultValue", {"defkey": "desktop:home_page", "defvalue": "setup-wizard"})
    except Exception:
        pass

    return {"updated": updated, "apps": [a.get("app_name") for a in apps]}


@dataclass(frozen=True)
class BootstrapConfig:
    company: str = ""
    language: str = "de"
    country: str = "Germany"
    time_zone: str = "Europe/Berlin"
    currency: str = "EUR"
    coa_template: str = "SKR03 mit Kontonummern"
    create_coa: bool = False
    run_setup_wizard: bool = False
    mark_setup_complete: bool = True
    force: bool = False


def config_from_env() -> BootstrapConfig:
    return BootstrapConfig(
        company=(os.environ.get("HV_COMPANY") or "").strip(),
        language=(os.environ.get("HV_LANGUAGE") or "de").strip(),
        country=(os.environ.get("HV_COUNTRY") or "Germany").strip(),
        time_zone=(os.environ.get("HV_TIME_ZONE") or "Europe/Berlin").strip(),
        currency=(os.environ.get("HV_CURRENCY") or "EUR").strip(),
        coa_template=(os.environ.get("HV_COA_TEMPLATE") or "SKR03 mit Kontonummern").strip(),
        create_coa=_env_bool("HV_BOOTSTRAP_CREATE_COA", False),
        run_setup_wizard=_env_bool("HV_BOOTSTRAP_RUN_SETUP_WIZARD", False),
        mark_setup_complete=_env_bool("HV_BOOTSTRAP_MARK_SETUP_COMPLETE", True),
        force=_env_bool("HV_BOOTSTRAP_FORCE", False),
    )


def run(config: Optional[BootstrapConfig] = None) -> dict:
    """Idempotent baseline setup for fresh ERPNext sites.

    Intended to be safe to run multiple times (e.g. after_migrate).
    """

    cfg = config or config_from_env()

    changed: list[dict] = []

    setup_wizard_res: dict[str, Any] = {"status": "skipped", "reason": "disabled"}
    if cfg.run_setup_wizard:
        setup_wizard_res = _run_frappe_setup_wizard(
            language=cfg.language,
            country=cfg.country,
            time_zone=cfg.time_zone,
            currency=cfg.currency,
            force=cfg.force,
        )

    # System / locale
    if _set_single_value_unset_or_default(
        doctype="System Settings",
        fieldname="language",
        value=cfg.language,
        force=cfg.force,
        default_values=("en",),
    ):
        changed.append({"doctype": "System Settings", "field": "language", "value": cfg.language})
    if _set_single_value_unset_or_default(
        doctype="System Settings",
        fieldname="time_zone",
        value=cfg.time_zone,
        force=cfg.force,
        default_values=("Asia/Kolkata",),
    ):
        changed.append({"doctype": "System Settings", "field": "time_zone", "value": cfg.time_zone})
    if _set_single_value_unset_or_default(
        doctype="System Settings",
        fieldname="country",
        value=cfg.country,
        force=cfg.force,
        default_values=("India",),
    ):
        changed.append({"doctype": "System Settings", "field": "country", "value": cfg.country})

    # Company + global defaults
    company_res = {}
    try:
        company_res = _ensure_company(
            company_name=cfg.company,
            country=cfg.country,
            currency=cfg.currency,
            force=cfg.force,
        )
    except Exception as exc:
        company_res = {"company": cfg.company, "created": False, "updated": False, "error": str(exc)}

    if company_res.get("created") or company_res.get("updated"):
        changed.append({"doctype": "Company", "name": company_res.get("company"), **company_res})

    company_name = company_res.get("company") or cfg.company

    if company_name:
        try:
            cc_res = _ensure_default_cost_center(company=company_name)
            if cc_res.get("created_root") or cc_res.get("created_main") or cc_res.get("set_default"):
                changed.append({"doctype": "Cost Center", "company": company_name, **cc_res})
        except Exception as exc:
            changed.append({"doctype": "Cost Center", "company": company_name, "error": str(exc)})

        try:
            ro_res = _ensure_round_off_account(company=company_name)
            if ro_res.get("created") or ro_res.get("set_default"):
                changed.append({"doctype": "Account", "company": company_name, "account_type": "Round Off", **ro_res})
        except Exception as exc:
            changed.append({"doctype": "Account", "company": company_name, "account_type": "Round Off", "error": str(exc)})

    try:
        pl_res = _ensure_default_price_lists(currency=cfg.currency)
        if pl_res.get("created"):
            changed.append({"doctype": "Price List", **pl_res})
    except Exception as exc:
        changed.append({"doctype": "Price List", "error": str(exc)})

    try:
        pt_res = _ensure_default_party_types()
        if pt_res.get("created"):
            changed.append({"doctype": "Party Type", **pt_res})
    except Exception as exc:
        changed.append({"doctype": "Party Type", "error": str(exc)})

    force_defaults = cfg.force or bool(company_res.get("created"))

    if _set_single_value(
        doctype="Global Defaults",
        fieldname="default_company",
        value=company_name,
        force=force_defaults,
    ):
        changed.append({"doctype": "Global Defaults", "field": "default_company", "value": cfg.company})

    # Also set via Frappe defaults API because many code paths rely on key-based defaults (e.g. "company").
    if _ensure_global_default(key="company", value=company_name, force=force_defaults):
        changed.append({"doctype": "DefaultValue", "scope": "global", "key": "company", "value": company_name})
    if _ensure_user_default(user="Administrator", key="company", value=company_name, force=force_defaults):
        changed.append({"doctype": "DefaultValue", "scope": "user", "user": "Administrator", "key": "company", "value": company_name})

    if _set_single_value_unset_or_default(
        doctype="Global Defaults",
        fieldname="default_currency",
        value=cfg.currency,
        force=cfg.force,
        default_values=("INR",),
    ):
        changed.append({"doctype": "Global Defaults", "field": "default_currency", "value": cfg.currency})

    if _set_single_value_unset_or_default(
        doctype="Global Defaults",
        fieldname="country",
        value=cfg.country,
        force=cfg.force,
        default_values=("India",),
    ):
        changed.append({"doctype": "Global Defaults", "field": "country", "value": cfg.country})

    user_changed = False
    try:
        user_changed = _ensure_user_language(user="Administrator", language=cfg.language, force=cfg.force)
    except Exception:
        user_changed = False
    if user_changed:
        changed.append({"doctype": "User", "name": "Administrator", "field": "language", "value": cfg.language})

    user_tz_changed = False
    try:
        user_tz_changed = _ensure_user_time_zone(user="Administrator", time_zone=cfg.time_zone, force=cfg.force)
    except Exception:
        user_tz_changed = False
    if user_tz_changed:
        changed.append({"doctype": "User", "name": "Administrator", "field": "time_zone", "value": cfg.time_zone})

    coa_res: dict[str, Any] = {"created": False, "skipped": True, "reason": "disabled"}
    if cfg.create_coa:
        try:
            coa_res = _ensure_chart_of_accounts(company=company_res.get("company") or cfg.company, template=cfg.coa_template)
        except Exception as exc:
            coa_res = {"created": False, "error": str(exc)}

    setup_complete_res: dict[str, Any] = {"updated": 0, "skipped": True, "reason": "disabled"}
    if cfg.mark_setup_complete:
        try:
            setup_complete_res = _mark_setup_complete(force=cfg.force)
        except Exception as exc:
            setup_complete_res = {"updated": 0, "error": str(exc)}

    role_profile_res: dict[str, Any] = {"status": "skipped"}
    try:
        role_profile_res = _ensure_default_role_profile()
    except Exception as exc:
        role_profile_res = {"status": "error", "error": str(exc)}

    # Final defensive currency fix. Runs as the very last step of the bootstrap,
    # so anything earlier (including ERPNext install or migrate hooks that left
    # System Settings.currency = None or INR) gets overridden. Without this the
    # fallback currency for fresh Sales/Purchase Invoices stays INR and they
    # fail validation against EUR-currency accounts (e.g. 1300 Mieterforderungen).
    currency_fix_res: dict[str, Any] = _force_default_currency(cfg.currency or "EUR")

    try:
        frappe.db.commit()
    except Exception:
        pass

    return {
        "config": cfg.__dict__,
        "changed": changed,
        "chart_of_accounts": coa_res,
        "setup_wizard": setup_wizard_res,
        "setup_complete": setup_complete_res,
        "role_profile": role_profile_res,
        "currency_fix": currency_fix_res,
    }


def _force_default_currency(currency: str) -> dict[str, Any]:
    """Set System Settings.currency and the default-value fallback to `currency`.

    Always saves the System Settings doc so `on_update` propagates the value to
    `tabDefaultValue.__default.currency` in one go. Unlike the silent helpers
    elsewhere, this returns a structured result and logs failures explicitly so
    we can see what's happening in `bench execute …bootstrap_site.run` output.
    """

    result: dict[str, Any] = {"target": currency, "ss_before": None, "ss_after": None,
                              "default_before": None, "default_after": None, "errors": []}

    try:
        result["ss_before"] = frappe.db.get_single_value("System Settings", "currency")
    except Exception as exc:
        result["errors"].append(f"read ss: {exc}")

    try:
        result["default_before"] = frappe.db.get_default("currency")
    except Exception as exc:
        result["errors"].append(f"read default: {exc}")

    try:
        ss = frappe.get_single("System Settings")
        if ss.currency != currency:
            ss.currency = currency
            ss.flags.ignore_permissions = True
            ss.save()
    except Exception as exc:
        result["errors"].append(f"save ss: {exc}")
        try:
            frappe.log_error(frappe.get_traceback(), "bootstrap_site _force_default_currency save")
        except Exception:
            pass

    try:
        if (frappe.db.get_default("currency") or "") != currency:
            frappe.db.set_default("currency", currency)
    except Exception as exc:
        result["errors"].append(f"set default: {exc}")

    try:
        frappe.db.commit()
    except Exception:
        pass

    try:
        result["ss_after"] = frappe.db.get_single_value("System Settings", "currency")
        result["default_after"] = frappe.db.get_default("currency")
    except Exception:
        pass

    try:
        frappe.logger("hausverwaltung").info("bootstrap_site _force_default_currency: %s", result)
    except Exception:
        pass

    return result
