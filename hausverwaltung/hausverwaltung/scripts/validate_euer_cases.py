from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import flt

from hausverwaltung.hausverwaltung.report.euer import euer as euer_report


DEFAULT_CASES_ROOT = (
    Path(__file__).resolve().parents[3] / "import" / "test" / "ea_cases_10000_2015_2024"
)
APP_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class CaseExpectation:
    path: Path
    onr: int
    start_date: str
    end_date: str
    income_adjusted: float
    expense_total: float
    expense_umlagefaehig: float
    expense_nicht_umlagefaehig: float
    net_result: float


def _as_float(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    text = text.replace(".", "").replace(",", ".") if "," in text and "." in text else text.replace(",", ".")
    return flt(text)


def _load_case_expectation(path: Path) -> CaseExpectation:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError(f"CSV ist leer: {path}")

    totals_row = next((row for row in rows if (row.get("kind") or "").strip() == "ea_new_totals"), None)
    if not totals_row:
        raise ValueError(f"ea_new_totals fehlt: {path}")

    return CaseExpectation(
        path=path,
        onr=int(str(totals_row.get("onr") or "").strip()),
        start_date=str(totals_row.get("start_date") or "").strip(),
        end_date=str(totals_row.get("end_date") or "").strip(),
        income_adjusted=_as_float(totals_row.get("einnahmen_bereinigt")),
        expense_total=_as_float(totals_row.get("ausgaben")),
        expense_umlagefaehig=_as_float(totals_row.get("ausgaben_umlagefaehig")),
        expense_nicht_umlagefaehig=_as_float(totals_row.get("ausgaben_nicht_umlagefaehig")),
        net_result=_as_float(totals_row.get("saldo_bereinigt")),
    )


def _resolve_company(company: str | None) -> str:
    if company:
        return company

    companies = frappe.get_all("Company", pluck="name", limit_page_length=1)
    if not companies:
        raise ValueError("Keine Company gefunden. Bitte `company` explizit uebergeben.")
    return companies[0]


def _resolve_path(value: str, *, default_base: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidate = (default_base / path).resolve()
    if candidate.exists():
        return candidate
    return path.resolve()


def _resolve_immobilie(onr: int) -> str:
    immobilie = frappe.db.get_value("Immobilie", {"immobilien_id": onr}, "name")
    if not immobilie:
        raise ValueError(f"Keine Immobilie mit immobilien_id={onr} gefunden.")
    return str(immobilie)


def _find_balance(rows: list[dict[str, Any]], account_label: str) -> float | None:
    for row in rows:
        if (row.get("account") or "").strip() != account_label:
            continue
        if row.get("balance") is not None:
            return flt(row.get("balance"))
        income = flt(row.get("income"))
        expense = flt(row.get("expense"))
        if income or expense:
            return flt(income - expense)
        return 0.0
    return None


def _compare_value(
    *,
    case_name: str,
    label: str,
    actual: float | None,
    expected: float | None,
    tolerance: float,
    failures: list[str],
) -> None:
    if expected is None:
        return
    if actual is None:
        failures.append(f"{case_name}: {label} fehlt im Report, erwartet {expected:.2f}")
        return
    delta = flt(actual - expected)
    if abs(delta) > tolerance:
        failures.append(
            f"{case_name}: {label} weicht ab (ist {actual:.2f}, erwartet {expected:.2f}, delta {delta:.2f})"
        )


def _run_single_case(
    expectation: CaseExpectation,
    *,
    company: str,
    tolerance: float,
    cases_root: Path,
) -> dict[str, Any]:
    try:
        case_name = expectation.path.relative_to(cases_root).as_posix()
    except ValueError:
        case_name = str(expectation.path)

    try:
        immobilie = _resolve_immobilie(expectation.onr)
    except ValueError as exc:
        return {
            "case": case_name,
            "ok": False,
            "skipped": True,
            "skip_reason": str(exc),
            "message": None,
            "failures": [],
            "report_rows": 0,
        }

    _, rows, message, _, _ = euer_report.execute(
        {
            "company": company,
            "immobilie": immobilie,
            "from_date": expectation.start_date,
            "to_date": expectation.end_date,
            "show_bank_check": 1,
        }
    )

    failures: list[str] = []

    _compare_value(
        case_name=case_name,
        label="Summe Einnahmen",
        actual=_find_balance(rows, "Summe Einnahmen"),
        expected=expectation.income_adjusted,
        tolerance=tolerance,
        failures=failures,
    )
    _compare_value(
        case_name=case_name,
        label="Summe Umlagefaehige Ausgaben",
        actual=abs(_find_balance(rows, "Summe Umlagefähige Ausgaben") or 0.0),
        expected=expectation.expense_umlagefaehig,
        tolerance=tolerance,
        failures=failures,
    )
    _compare_value(
        case_name=case_name,
        label="Summe Nicht umlagefaehige Ausgaben",
        actual=abs(_find_balance(rows, "Summe Nicht umlagefähige Ausgaben") or 0.0),
        expected=expectation.expense_nicht_umlagefaehig,
        tolerance=tolerance,
        failures=failures,
    )
    _compare_value(
        case_name=case_name,
        label="Summe Ausgaben",
        actual=abs(_find_balance(rows, "Summe Ausgaben") or 0.0),
        expected=expectation.expense_total,
        tolerance=tolerance,
        failures=failures,
    )
    _compare_value(
        case_name=case_name,
        label="Ueberschuss/Verlust",
        actual=_find_balance(rows, "Überschuss/Verlust"),
        expected=expectation.net_result,
        tolerance=tolerance,
        failures=failures,
    )

    return {
        "case": case_name,
        "ok": not failures,
        "skipped": False,
        "skip_reason": None,
        "message": message,
        "failures": failures,
        "report_rows": len(rows),
    }


def run(
    cases_root: str | None = None,
    case_file: str | None = None,
    company: str | None = None,
    onr: int | None = None,
    limit: int | None = None,
    tolerance: float = 0.05,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """Vergleicht Legacy-EUER-CSVs aus import/test gegen den aktuellen EÜR-Report.

    Beispiel:
        bench --site frontend execute hausverwaltung.hausverwaltung.scripts.validate_euer_cases.run
        bench --site frontend execute hausverwaltung.hausverwaltung.scripts.validate_euer_cases.run --kwargs "{'onr': 6, 'limit': 5}"
        bench --site frontend execute hausverwaltung.hausverwaltung.scripts.validate_euer_cases.run --kwargs "{'case_file': 'import/test/ea_cases_10000_2015_2024/onr_6/00001_ea_new_onr_6_2022-03-27_2022-11-20.csv'}"
    """

    root = _resolve_path(cases_root, default_base=APP_ROOT) if cases_root else DEFAULT_CASES_ROOT
    selected_company = _resolve_company(company)

    if case_file:
        case_paths = [_resolve_path(case_file, default_base=APP_ROOT)]
    else:
        pattern = f"onr_{int(onr)}/*.csv" if onr is not None else "onr_*/*.csv"
        case_paths = sorted(root.glob(pattern))

    if limit is not None:
        case_paths = case_paths[: int(limit)]

    if not case_paths:
        raise ValueError(f"Keine Testfaelle gefunden unter {root}")

    failures: list[str] = []
    checked = 0
    passed = 0
    skipped = 0
    per_case: list[dict[str, Any]] = []

    for case_path in case_paths:
        expectation = _load_case_expectation(case_path)
        result = _run_single_case(
            expectation,
            company=selected_company,
            tolerance=flt(tolerance),
            cases_root=root,
        )
        per_case.append(result)
        checked += 1

        if result.get("skipped"):
            skipped += 1
            print(f"SKIP {result['case']}: {result['skip_reason']}")
            continue

        if result["ok"]:
            passed += 1
            print(f"OK   {result['case']}")
            continue

        for failure in result["failures"]:
            print(f"FAIL {failure}")
            failures.append(failure)
        if fail_fast:
            break

    summary = {
        "cases_root": str(root),
        "company": selected_company,
        "checked": checked,
        "passed": passed,
        "skipped": skipped,
        "failed": checked - passed - skipped,
        "failures": failures,
        "cases": per_case,
    }

    print(
        f"Geprueft: {checked}, OK: {passed}, Uebersprungen: {skipped}, Fehler: {summary['failed']}"
    )
    return summary
