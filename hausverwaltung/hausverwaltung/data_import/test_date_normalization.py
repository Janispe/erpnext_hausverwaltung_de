"""
Mini-Tests für normalize_import_date().

Verwendung:
    python3 test_date_normalization.py
"""

import os
import sys
from datetime import date

# Füge den Pfad hinzu damit wir das Modul importieren können
sys.path.insert(0, os.path.dirname(__file__))

from date_normalization import normalize_import_date


def test_normalize_import_date():
    assert normalize_import_date("2006-01-01") == "2006-01-01"

    # Broken exports: century missing / corrupted
    assert normalize_import_date("0205-01-30") == "2005-01-30"
    assert normalize_import_date("0215-05-21") == "2015-05-21"
    assert normalize_import_date("1015-12-10") == "2015-12-10"

    # German format (2-digit year)
    assert normalize_import_date("10.12.15") == "10.12.2015"

    # date objects
    assert normalize_import_date(date(205, 1, 30)) == date(2005, 1, 30)
    assert normalize_import_date(date(2015, 12, 10)) == date(2015, 12, 10)


if __name__ == "__main__":
    test_normalize_import_date()
    print("OK")

