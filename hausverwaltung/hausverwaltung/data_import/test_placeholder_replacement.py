"""
Test-Script um die Platzhalter-Ersetzung zu testen.

Verwendung:
    python3 test_placeholder_replacement.py
"""

import os
import sys

# Füge den Pfad hinzu damit wir das Modul importieren können
sys.path.insert(0, os.path.dirname(__file__))

from placeholder_mapping import replace_placeholders


def test_placeholder_replacement():
    """Testet die Platzhalter-Ersetzung mit Beispielen."""

    test_texts = [
        # Test 1: Einfache Platzhalter
        """«Verw.-Name» , «Verw.-Straße» , «Verw.-PLZ_Ort»
«B-Anrede1» «B-Titel1» «B-Vorname1» «B-Name1» «B-Strasse»
«B-PLZ-Ort»

München, «Systemdatum»

1. Mahnung

«B-Brief_Anrede1» «B-Name1»,
Ihr Mietkonto zeigt per heute einen Rückstand in Höhe von «B-Saldo».""",

        # Test 2: Mit Encoding-Fehlern
        """Â«Verw-NameÂ» , Â«Verw-StraÃeÂ» , Â«Verw-PLZ_OrtÂ»
Â«B-Anrede1Â» Â«B-Vorname1Â» Â«B-Name1Â» Â«B-StrasseÂ»
Â«B-PLZ-OrtÂ»

München, Â«SystemdatumÂ»""",

        # Test 3: Eigentümer
        """«E-Anrede1» «E-Titel1» «E-Vorname1» «E-Name1» «E-Strasse»
«E-PLZ-Ort»

Ihr Saldo beträgt: «E-Saldo»""",

        # Test 4: Wohnung
        """Wohnung: «Whg-Bez»
Art: «Whg-Art»
Nummer: «Whg-Nr»""",
    ]

    print("=" * 70)
    print("PLATZHALTER-ERSETZUNG TEST")
    print("=" * 70)
    print()

    for i, text in enumerate(test_texts, 1):
        print(f"\n{'='*70}")
        print(f"TEST {i}")
        print(f"{'='*70}")
        print("\n--- VORHER ---")
        print(text)
        print("\n--- NACHHER ---")
        replaced = replace_placeholders(text)
        print(replaced)
        print()

    # Statistik
    print("\n" + "=" * 70)
    print("MAPPING-STATISTIK")
    print("=" * 70)

    from placeholder_mapping import PLACEHOLDER_MAPPING
    print(f"\nAnzahl gemappter Platzhalter: {len(PLACEHOLDER_MAPPING)}")
    print("\nBeispiele:")
    for i, (old, new) in enumerate(list(PLACEHOLDER_MAPPING.items())[:10], 1):
        print(f"{i}. {old:30} -> {new[:50]}...")


if __name__ == "__main__":
    test_placeholder_replacement()
