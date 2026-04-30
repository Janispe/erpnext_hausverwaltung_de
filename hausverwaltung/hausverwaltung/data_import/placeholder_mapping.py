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
    "B-Brief_Anrede2": "",
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
    # `B-Anteil1` ist die Wohnungsgröße in m² — kommt aus dem aktuellen
    # Wohnungszustand (``wohnung.aktueller_zustand → Wohnungszustand.größe``).
    # Wird im Render-Context als ``wohnung_groesse`` aufgelöst.
    "B-Anteil1": "{{ wohnung_groesse }}",

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
    # Hinweis: Das `Wohnung`-Doctype hat kein Feld `art` oder `nummer`. Wir
    # rendern stattdessen die sprechende Bezeichnung (`name__lage_in_der_immobilie`,
    # mit Fallback auf den Doc-Namen) und unterdrücken `Whg-Art`/`Whg-Nr` —
    # WinCASA-Mandanten haben in Mama's Bestand ausschließlich Wohnungen.
    "Whg-Bez": "{{ wohnung.name__lage_in_der_immobilie or wohnung.name }}",
    "Whg-Art": "",
    "Whg-Nr": "{{ wohnung.name }}",

    # === HAUS / IMMOBILIE ===
    # Adress-Felder kommen aus dem Serienbrief-Render-Context
    # (siehe ``_build_context`` in serienbrief_durchlauf.py).
    "H-Bezeichnung": "{{ immobilie.name }}",
    "H-Bez": "{{ immobilie.name }}",
    "H-Nummer": "{{ immobilie.name }}",
    "H-Strasse": "{{ immobilie_strasse }}",
    "H-PLZ_Ort": "{{ immobilie_plz_ort }}",
    # Bank-Felder werden im Render-Context aus
    # ``immobilie.bankkonten[Hauptkonto] → Account → Bank Account``
    # vorab als ``bank_*``-Keys aufgelöst (siehe ``_resolve_bank_info``).
    "H-Bank_(1)": "{{ bank_name }}",
    "H-IBAN_(1)": "{{ bank_iban }}",
    "H-BIC_(1)": "{{ bank_bic }}",
    "H-BLZ_(1)": "{{ bank_blz }}",
    "H-Konto_(1)": "{{ bank_konto }}",
    "H-Kto_Inhaber_(1)": "{{ bank_kto_inhaber }}",

    # === VORAUSZAHLUNGEN — Suffix-Varianten (Word liefert teils «B-VZ1_Netto») ===
    "B-VZ1_Netto": "{{ vorauszahlung_1_netto }}",
    "B-VZ2_Netto": "{{ vorauszahlung_2_netto }}",
    "B-VZ3_Netto": "{{ vorauszahlung_3_netto }}",
    "B-VZ4_Netto": "{{ vorauszahlung_4_netto }}",

    # === SYSTEM ===
    "Systemdatum": "{{ frappe.utils.formatdate(frappe.utils.nowdate(), 'dd.MM.yyyy') }}",
}


def get_mapping():
    """Gibt das Platzhalter-Mapping zurück."""
    return PLACEHOLDER_MAPPING


_TOKEN_HTML_TAG_RE = re.compile(r"<[^>]+>")
_GUILLEMET_TOKEN_RE = re.compile(r"«([^»]*?)»", re.DOTALL)
_MOJIBAKE_TOKEN_RE = re.compile(r"Â«([^»]*?)Â»", re.DOTALL)


def _normalize_word_tokens(html: str) -> str:
	"""Entfernt HTML-Tags innerhalb von ``«…»``-Token-Sequenzen.

	Word-HTML splittet Mergefield-Tokens oft über mehrere ``<span>``-Tags
	auf — z.B. ``«<span>Whg</span>-Art»`` statt ``«Whg-Art»``. Damit das
	folgende ``str.replace()``-Mapping greift, packen wir den Token-Inhalt
	wieder zu einem zusammenhängenden Plain-Text zusammen.
	"""
	if not html:
		return html

	def _strip(m):
		inner = _TOKEN_HTML_TAG_RE.sub("", m.group(1))
		return f"«{inner}»"

	def _strip_mojibake(m):
		inner = _TOKEN_HTML_TAG_RE.sub("", m.group(1))
		return f"Â«{inner}Â»"

	out = _GUILLEMET_TOKEN_RE.sub(_strip, html)
	out = _MOJIBAKE_TOKEN_RE.sub(_strip_mojibake, out)
	return out


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

    # Schritt 1: HTML-Tags innerhalb von Tokens zusammenfassen, sodass
    # `«<span>Whg</span>-Art»` als `«Whg-Art»` matchbar wird.
    result = _normalize_word_tokens(text)

    # Schritt 2: Längere Tokens zuerst ersetzen (sonst frisst z.B. "B-VZ1"
    # den Anfang von "B-VZ1_Netto" auf und zurück bleibt "{{ … }}_Netto").
    sorted_items = sorted(mapping.items(), key=lambda kv: -len(kv[0]))

    for old_placeholder, new_jinja in sorted_items:
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
