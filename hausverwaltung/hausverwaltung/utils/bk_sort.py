"""Gruppierte Sortier-Reihenfolge für Betriebskostenart-Listen.

Statt rein alphabetisch werden zusammengehörige Positionen (Wasser-Familie,
Heizung/Schornstein, Hauswart/Reinigung, Müll, Versicherung, Steuern/sonst.)
gruppiert dargestellt. Das Mapping unten ist auf die in der DB vorhandenen
~40 Betriebskostenart-Namen abgestimmt; unbekannte Namen landen alphabetisch
in einer Sammelgruppe am Ende.

Bewusst KEIN Custom-Field auf ``Betriebskostenart`` — das Mapping ist im Repo
versionskontrolliert und reproduzierbar, neue Arten brauchen einen 2-Zeilen-
Commit statt UI-Pflege.
"""

from __future__ import annotations


# (Gruppen-Sort-Schlüssel, Index innerhalb der Gruppe)
BK_SORT_GROUPS: dict[str, tuple[str, int]] = {
	# 10_wasser
	"Bewässerung": ("10_wasser", 1),
	"Bewässerung Gewerbe": ("10_wasser", 2),
	"Bewässerung Mieter": ("10_wasser", 3),
	"Entwässerung": ("10_wasser", 4),
	"Entwässerung Gewerbe": ("10_wasser", 5),
	"Entwässerung Mieter": ("10_wasser", 6),
	"Niederschlagswasser": ("10_wasser", 7),
	"Kanal-Gebühren": ("10_wasser", 8),
	# 20_heizung_schornstein
	"Heizungs-Wartung": ("20_heizung", 1),
	"Thermenwartung": ("20_heizung", 2),
	"Wartung Rauchabzugsanlage": ("20_heizung", 3),
	"Schornsteinfeger": ("20_heizung", 4),
	"Zusatzgebühr Schornsteinf.": ("20_heizung", 5),
	"Zusätzliche Abgasmessung": ("20_heizung", 6),
	"Kamin/Ofen": ("20_heizung", 7),
	"Rauchwarnmelder": ("20_heizung", 8),
	"Zusatzg. RWM": ("20_heizung", 9),
	"Zusatzgeb. RWM": ("20_heizung", 10),
	# 30_hauswart_reinigung
	"Hausmeister-Vergütung": ("30_hauswart", 1),
	"Hauswart/Hausreinigung": ("30_hauswart", 2),
	"Hausreinigung": ("30_hauswart", 3),
	"Gartenarbeiten": ("30_hauswart", 4),
	"Dachrinnenreinigung": ("30_hauswart", 5),
	"Regenrinnenreinigung": ("30_hauswart", 6),
	"Winterdienst": ("30_hauswart", 7),
	"Straßenreinigung": ("30_hauswart", 8),
	"Ungezieferbekämpfung": ("30_hauswart", 9),
	# 40_muell
	"Müllbeseitigung": ("40_muell", 1),
	"Müllbeseit. + Straßenrei.": ("40_muell", 2),
	"Sperrmüll Mieter": ("40_muell", 3),
	"Sperrmüllents. nur Mieter": ("40_muell", 4),
	"Sperrmüllentsorgung als BK": ("40_muell", 5),
	"Papierentsorgung": ("40_muell", 6),
	"Papierentsorgung Mieter": ("40_muell", 7),
	# 50_versicherung
	"Versicherung Gebäude": ("50_versicherung", 1),
	"Versicherung Haftpflicht": ("50_versicherung", 2),
	"Versicherung Glasbruch": ("50_versicherung", 3),
	"Versicherung Gewässer": ("50_versicherung", 4),
	# 60_sonstiges (Steuern/Gebühren/Strom)
	"Grundsteuer": ("60_sonstiges", 1),
	"Allgemeinstrom": ("60_sonstiges", 2),
	"Kabelgebühren": ("60_sonstiges", 3),
}

_DEFAULT_GROUP = ("99_unsortiert", 0)


def sort_key(art_name: str) -> tuple[str, int, str]:
	"""Sortier-Schlüssel für eine Betriebskostenart.

	Verwendung: ``sorted(items, key=lambda r: sort_key(r["betriebskostenart"]))``.
	Innerhalb einer Gruppe gilt der hand-gepflegte Index; unbekannte Arten
	landen alphabetisch in der Sammelgruppe ``99_unsortiert``.
	"""
	clean = (art_name or "").strip()
	group, idx = BK_SORT_GROUPS.get(clean, _DEFAULT_GROUP)
	return (group, idx, clean.lower())


# Whitelisted-Helper für Frontend: liefert das Mapping als JSON-friendly Dict,
# damit JS-Forms (z.B. Mieter-BK-Kostenuebersicht) die gleiche
# Sortierreihenfolge anwenden können wie Python-Reports.
import frappe  # noqa: E402


@frappe.whitelist()
def get_sort_keys() -> dict[str, list]:
	"""Gibt das Sort-Group-Mapping als plain-JSON zurück (Tuples → Lists)."""
	return {name: [group, idx] for name, (group, idx) in BK_SORT_GROUPS.items()}
