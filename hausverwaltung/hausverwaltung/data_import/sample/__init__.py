"""Sample data import runner for the Hausverwaltung app.

Provides discovery and execution of sample/seed import functions contained in
this package. Any module in this folder that exposes a function starting with
``create_sample`` will be discovered and can be executed via ``run_all``.

Usage from bench console:
    from hausverwaltung.hausverwaltung.data_import.sample import run_all, list_imports
    list_imports()  # to see what would run
    run_all(company="Demo Hausverwaltung", with_zustand=True, with_invoices=False, with_payments=False)

Usage via bench execute:
    bench execute hausverwaltung.hausverwaltung.data_import.sample.run_all \
      --kwargs "{\"company\": \"Demo Hausverwaltung\", \"with_invoices\": false, \"with_payments\": false}"

To add more sample imports, create a new ``.py`` module in this directory and
expose one or more functions whose names start with ``create_sample``. The
runner introspects function signatures and only passes supported keyword args
like ``company``, ``with_zustand``, etc.

Special: Chart of Accounts (destructive!)
- Module: ``sample.chart_of_accounts`` provides ``create_sample_coa`` which
  uses the official ERPNext importer. It is disabled by default to avoid
  wiping accounts. Enable explicitly:

    from hausverwaltung.hausverwaltung.data_import.sample import run_all
    run_all(company="Demo Hausverwaltung",
            include=["chart_of_accounts.create_sample_coa"],
            enabled=True,
            validate_only=False,
            path=frappe.get_site_path("private","files","coa_importer_template.xlsx"))
"""

from __future__ import annotations

import inspect
import importlib
import pkgutil
from typing import Any, Callable, Dict, List, Tuple

# Type alias for registry entries
RegistryEntry = Tuple[str, str, Callable[..., Any]]  # (module, func_name, callable)

try:
    import frappe  # type: ignore
except Exception:  # pragma: no cover - allow import-time in non-Frappe contexts
    frappe = None  # type: ignore


def _iter_submodules() -> List[str]:
    """Return a list of submodule names within this package (without package prefix)."""
    names: List[str] = []
    for m in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        name = m.name
        if name.startswith("_"):
            continue
        names.append(name)
    names.sort()
    return names


def _discover_functions() -> List[RegistryEntry]:
    """Discover functions starting with ``create_sample`` in submodules.

    Returns a list of registry entries: (module, function_name, callable).
    """
    entries: List[RegistryEntry] = []
    for modname in _iter_submodules():
        module = importlib.import_module(f"{__name__}.{modname}")
        for attr_name, obj in vars(module).items():
            if not callable(obj):
                continue
            if not attr_name.startswith("create_sample"):
                continue
            entries.append((modname, attr_name, obj))
    # deterministic order: by module then function name
    entries.sort(key=lambda x: (x[0], x[1]))
    # Prefer importing Chart of Accounts before others (so Accounts exist)
    # Move chart_of_accounts.* to the front while keeping their internal order
    chart = [e for e in entries if e[0] == "chart_of_accounts"]
    others = [e for e in entries if e[0] != "chart_of_accounts"]
    entries = chart + others
    return entries


def list_imports() -> List[Dict[str, str]]:
    """List discovered sample import functions with brief info.

    Returns a list of dicts: {"key", "module", "function", "doc"}
    """
    info: List[Dict[str, str]] = []
    for modname, func_name, fn in _discover_functions():
        key = f"{modname}.{func_name}"
        doc = (inspect.getdoc(fn) or "").splitlines()[0] if inspect.getdoc(fn) else ""
        info.append({
            "key": key,
            "module": modname,
            "function": func_name,
            "doc": doc,
        })
    return info


def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Return only kwargs supported by the callable ``fn`` based on its signature."""
    try:
        sig = inspect.signature(fn)
        accepted = {p.name for p in sig.parameters.values() if p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD)}
        return {k: v for k, v in kwargs.items() if k in accepted}
    except Exception:
        # be conservative on failure
        return {}


def run_all(
    *,
    company: str | None = None,
    include: List[str] | None = None,
    exclude: List[str] | None = None,
    verbose: bool = True,
    **common_kwargs: Any,
) -> Dict[str, Any]:
    """Run all discovered sample import functions.

    - Auto-discovers functions named ``create_sample*`` under this package.
    - Filters kwargs per function to avoid signature mismatches.
    - Supports ``include``/``exclude`` lists using keys like ``module.func`` or just ``func``.

    Args:
        company: Optional company name to pass to imports that support it.
        include: Whitelist of keys to run (e.g., ["sample_data.create_sample_data"]). If set, only these run.
        exclude: Blacklist of keys to skip.
        verbose: Print progress to stdout.
        **common_kwargs: Extra keyword args (e.g., with_zustand=True) passed to imports that accept them.

    Returns:
        Dict mapping each import key to either the return value or an error message.
    """
    results: Dict[str, Any] = {}

    # Ensure basic site defaults are set in reset/dev environments.
    # (e.g. System Settings.language can be empty -> num2words crashes)
    if frappe and company:
        try:
            ss = frappe.get_single("System Settings")
            if hasattr(ss, "language") and not getattr(ss, "language", None):
                ss.language = "de"
                ss.save(ignore_permissions=True)
        except Exception:
            pass
        try:
            frappe.defaults.set_global_default("lang", "de")
        except Exception:
            pass
        try:
            frappe.defaults.set_user_default("lang", "de")
        except Exception:
            pass
        try:
            if getattr(frappe.local, "lang", None) is None:
                frappe.local.lang = "de"
        except Exception:
            pass

    # Build candidate kwargs shared across imports
    base_kwargs: Dict[str, Any] = {}
    if company is not None:
        base_kwargs["company"] = company
    base_kwargs.update(common_kwargs)
    # Convenience: if invoices requested but payments not specified, enable payments
    try:
        if base_kwargs.get("with_invoices") and "with_payments" not in base_kwargs:
            base_kwargs["with_payments"] = True
    except Exception:
        pass

    entries = _discover_functions()
    for modname, func_name, fn in entries:
        key = f"{modname}.{func_name}"

        # include/exclude filtering
        if include and not any(key == inc or func_name == inc or modname == inc for inc in include):
            continue
        if exclude and any(key == exc or func_name == exc or modname == exc for exc in exclude):
            continue

        kwargs = _filter_kwargs_for_callable(fn, base_kwargs)

        if verbose:
            print(f"▶️  Running {key} with kwargs={kwargs}")
        try:
            results[key] = fn(**kwargs)
            if verbose:
                print(f"✅  Done: {key}")
        except Exception as exc:
            results[key] = {"error": str(exc)}
            if verbose:
                print(f"❌  Failed: {key} -> {exc}")

    return results

