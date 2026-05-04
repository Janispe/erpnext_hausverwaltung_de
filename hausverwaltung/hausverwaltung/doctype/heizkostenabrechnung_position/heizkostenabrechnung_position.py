"""Child-DocType: Eine Mieter-Position innerhalb einer
``Heizkostenabrechnung Immobilie``.

Reine Datenklasse — die Geschäftslogik (Hydrierung beim Onload + Sync zurück
in HK-Mieter-Doc beim Save) liegt im Parent-Doctype.
"""
from __future__ import annotations

from frappe.model.document import Document


class HeizkostenabrechnungPosition(Document):
	pass
