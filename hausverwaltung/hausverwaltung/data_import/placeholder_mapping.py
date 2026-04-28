"""
Mapping der alten Platzhalter zu neuen Jinja-Variablen.

Die alten Dokumentvorlagen verwenden Platzhalter wie «B-Name1», «Verw.-Name» etc.
Diese müssen auf die neuen Frappe/Jinja-Variablen gemappt werden.
"""

import re

# Präfixe:
# B- = Bewohner (Mieter)
# E- = Eigentümer
# Verw- = Verwalter
# Whg- = Wohnung
# H- = Haus/Immobilie

PLACEHOLDER_MAPPING = {
    # === BEWOHNER / MIETER ===
    # Serienbrief-Kontext: `mieter` ist i.d.R. ein einzelnes Doc (oder None).
    # Für alte Vorlagen mit Zweit-Mieter (…2) mappen wir bewusst auf leer, damit keine Jinja-Fehler entstehen.
    "B-Name1": "{{ mieter.last_name }}",
    "B-Name2": "",
    "B-Vorname1": "{{ mieter.first_name }}",
    "B-Vorname2": "",
    "B-Titel1": "{{ (mieter.salutation or mieter.anrede or '') }}",
    "B-Anrede1": "{{ (mieter.salutation or mieter.anrede or '') }}",
    "B-Anrede2": "",
    "B-Brief_Anrede1": "{{ (mieter.salutation or mieter.anrede or '') }}",
    "B_Brief_Anrede2": "",
    "B-Briefanrede+Name": "{{ ((mieter.salutation or mieter.anrede or '') ~ ' ' ~ (mieter.last_name or '')) }}",
    # Alle Vertragspartner im Mietvertrag (z.B. für Adresse/Anredezeile)
    # Hinweis: `baustein()` wird beim Serienbrief-Rendern in den Jinja-Kontext injiziert.
    "B-Briefanrede+NameAlle": '{{ baustein("MieterAnredeNameAlle") }}',
    "B-Strasse": "{{ mieter_strasse }}",
    "B-PLZ-Ort": "{{ mieter_plz_ort }}",

    # Mietvertrag
    "B-Einzug": "{{ mietvertrag.von }}",
    "B-Auszug": "{{ mietvertrag.bis }}",
    "B-Vertr_Abschl": "{{ mietvertrag.creation }}",
    "B-Anteil1": "{{ mietvertrag.anteil }}",

    # Vorauszahlungen / Saldo
    "B-VZ1": "{{ vorauszahlung_1 }}",
    "B-VZ2": "{{ vorauszahlung_2 }}",
    "B-VZ3": "{{ vorauszahlung_3 }}",
    "B-VZ4": "{{ vorauszahlung_4 }}",
    # In den alten Vorlagen wird `B-SUMVZ` oft als "neue Gesamtmiete" genutzt.
    # Im Mietvertrag ist das i.d.R. die `bruttomiete` (Currency).
    "B-SUMVZ": "{{ mietvertrag.bruttomiete }}",
    "B-Saldo": "{{ saldo }}",
    "B-Saldo+1.Mahng.": "{{ (saldo|float + mahngebuehr_1|float)|round(2) }}",

    # Anschriftfeld
    "«B-Anschriftfeld (4-zeilig)»": """{{ mieter_name }}<br/>
{{ '' }}<br/>
{{ mieter_strasse }}<br/>
{{ mieter_plz_ort }}""",

    # === EIGENTÜMER ===
    "E-Name1": "{{ eigentuemer.last_name }}",
    "E-Vorname1": "{{ eigentuemer.first_name }}",
    "E-Titel1": "{{ eigentuemer.salutation }}",
    "E-Anrede1": "{{ eigentuemer.salutation }}",
    "E-Brief_Anrede1": "{{ eigentuemer.salutation }}",
    "E-Briefanrede+Name": "{{ eigentuemer.salutation + ' ' + eigentuemer.last_name }}",
    "E-Strasse": "{{ eigentuemer_address.address_line1 }}",
    "E-PLZ-Ort": "{{ (eigentuemer_address.pincode or '') + ' ' + (eigentuemer_address.city or '') }}",
    "E-Saldo": "{{ eigentuemer_saldo }}",

    "«E-Anschriftfeld (4-zeilig)»": """{{ eigentuemer.first_name + ' ' + eigentuemer.last_name }}<br/>
{{ eigentuemer_address.address_line1 }}<br/>
{{ (eigentuemer_address.pincode or '') + ' ' + (eigentuemer_address.city or '') }}""",

    # === VERWALTER ===
    "Verw-Name": "{{ verwalter.name if verwalter is defined and verwalter else '' }}",
    "VerwName": "{{ verwalter.name if verwalter is defined and verwalter else '' }}",
    "Verw.-Name": "{{ verwalter.name if verwalter is defined and verwalter else '' }}",
    "Verw-Straße": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",
    "Verw-Straße": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",
    "Verw.-Straße": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",
    "Verw-Straße": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",
    "Verw.-Straße": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",
    "Verw-StraÃe": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",  # Encoding issue
    "Verw.-StraÃe": "{{ verwalter.address_line1 if verwalter is defined and verwalter else '' }}",  # Encoding issue
    "Verw-PLZ_Ort": "{{ verwalter.plz_ort if verwalter is defined and verwalter else '' }}",
    "Verw.-PLZ_Ort": "{{ verwalter.plz_ort if verwalter is defined and verwalter else '' }}",
    "Verw-Zusatz": "{{ verwalter.zusatz if verwalter is defined and verwalter else '' }}",
    "Verw.-Zusatz": "{{ verwalter.zusatz if verwalter is defined and verwalter else '' }}",

    # === WOHNUNG ===
    "Whg-Bez": "{{ wohnung.name }}",
    "Whg-Art": "{{ wohnung.art }}",
    "Whg-Nr": "{{ wohnung.nummer }}",

    # === HAUS / IMMOBILIE ===
    "H-Bezeichnung": "{{ immobilie.name }}",
    "H-Nummer": "{{ immobilie.nummer }}",
    "H-Strasse": "{{ immobilie.address_line1 }}",
    "H-PLZ_Ort": "{{ (immobilie.pincode or '') + ' ' + (immobilie.city or '') }}",
    "H-Bank_(1)": "{{ immobilie.bank }}",

    # === SYSTEM ===
    "Systemdatum": "{{ frappe.utils.formatdate(frappe.utils.nowdate(), 'dd.MM.yyyy') }}",
}


def get_mapping():
    """Gibt das Platzhalter-Mapping zurück."""
    return PLACEHOLDER_MAPPING


def replace_placeholders(text: str, mapping: dict = None) -> str:
    """
    Ersetzt alte Platzhalter durch neue Jinja-Variablen.

    Args:
        text: Text mit alten Platzhaltern
        mapping: Optional custom mapping (default: PLACEHOLDER_MAPPING)

    Returns:
        Text mit neuen Jinja-Variablen
    """
    if mapping is None:
        mapping = PLACEHOLDER_MAPPING

    result = text

    for old_placeholder, new_jinja in mapping.items():
        # Varianten mit verschiedenen Encodings
        patterns = [
            f"«{old_placeholder}»",  # Normal
            f"Â«{old_placeholder}Â»",  # Mit encoding issues
            old_placeholder,  # Falls Guillemets fehlen
        ]

        for pattern in patterns:
            result = result.replace(pattern, new_jinja)

    # Legacy combo: replace Anrede+Vorname+Nachname with Anrede-Block.
    salutation_expr = r"\{\{\s*\(mieter\.salutation\s+or\s+mieter\.anrede\s+or\s*''\)\s*\}\}"
    first_expr = r"\{\{\s*mieter\.first_name\s*\}\}"
    last_expr = r"\{\{\s*mieter\.last_name\s*\}\}"
    sep = r"[\s,]*"
    comma_expr = r"(?:\\s*,)?"

    anrede_patterns = [
        rf"{salutation_expr}(?:{sep}{salutation_expr})?{sep}{first_expr}{sep}{last_expr}{comma_expr}",
        rf"{salutation_expr}(?:{sep}{salutation_expr})?{sep}{last_expr}{sep}{first_expr}{comma_expr}",
        rf"{salutation_expr}(?:{sep}{salutation_expr})?{sep}{last_expr}{comma_expr}",
        rf"{salutation_expr}(?:{sep}{salutation_expr})?{comma_expr}",
    ]
    for pattern in anrede_patterns:
        result = re.sub(pattern, '{{ baustein("MieterAnredeNameAlle") }}', result)

    return result
