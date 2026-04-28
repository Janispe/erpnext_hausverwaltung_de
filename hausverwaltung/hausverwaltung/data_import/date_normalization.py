import re
from datetime import date, datetime
from typing import Any

_ISO_DATE_RE = re.compile(r"^(?P<year>\d{1,4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$")
_DE_DATE_RE = re.compile(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{2,4})$")


def normalize_import_date(value: Any, *, min_year: int = 1900, max_year: int = 2099) -> Any:
    """Normalize typical broken export date formats.

    We have seen exports where a YYYY-MM-DD date loses the leading "20" century,
    e.g. "0205-01-30" instead of "2005-01-30" or "1015-12-10" instead of "2015-12-10".
    ERPNext/Frappe will parse these dates fine, but posting them fails due to missing Fiscal Years.

    Rules:
    - If year < min_year: assume 2000 + (year % 100), but only if the resulting year is <= max_year.
    - Keeps the original type where practical (string stays string, date stays date).
    """
    if value is None:
        return value

    if isinstance(value, datetime):
        d = value.date()
        fixed = normalize_import_date(d, min_year=min_year, max_year=max_year)
        if fixed is d:
            return value
        if isinstance(fixed, date):
            return datetime.combine(fixed, value.time(), value.tzinfo)
        return value

    if isinstance(value, date) and not isinstance(value, datetime):
        if value.year >= min_year:
            return value
        candidate_year = 2000 + (value.year % 100)
        if candidate_year > max_year:
            return value
        return date(candidate_year, value.month, value.day)

    if not isinstance(value, str):
        return value

    s = value.strip()
    if not s:
        return value

    m = _ISO_DATE_RE.match(s)
    if m:
        year = int(m.group("year"))
        month = int(m.group("month"))
        day = int(m.group("day"))
        if year >= min_year:
            return value
        candidate_year = 2000 + (year % 100)
        if candidate_year > max_year:
            return value
        return f"{candidate_year:04d}-{month:02d}-{day:02d}"

    m = _DE_DATE_RE.match(s)
    if m:
        day = int(m.group("day"))
        month = int(m.group("month"))
        year_s = m.group("year")
        year = int(year_s)

        if len(year_s) == 2:
            candidate_year = 2000 + year
            if candidate_year > max_year:
                return value
            return f"{day:02d}.{month:02d}.{candidate_year:04d}"

        if year >= min_year:
            return value

        candidate_year = 2000 + (year % 100)
        if candidate_year > max_year:
            return value
        return f"{day:02d}.{month:02d}.{candidate_year:04d}"

    return value
