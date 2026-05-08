"""Body des Bausteins ``Bankverbindung Immobilie`` auf einen Marker setzen
— die Bankverbindung wird ab jetzt vom Page-Footer gerendert, nicht im
Brief-Hauptteil.

Idempotent: nur wenn der Body noch den alten ``<p>Bankverbindung: …</p>``-
Inhalt hat. Vorlagen, die den Baustein referenzieren, bekommen die
Bankverbindung automatisch im Footer (siehe
``hausverwaltung/utils/serienbrief_footer.py``).
"""

from __future__ import annotations

import frappe


_MARKER_BODY = "<!-- Bankverbindung wird im Page-Footer gerendert -->"


def execute() -> None:
	if not frappe.db.exists("Serienbrief Textbaustein", "Bankverbindung Immobilie"):
		return

	doc = frappe.get_doc("Serienbrief Textbaustein", "Bankverbindung Immobilie")
	current = (doc.html_content or "").strip()
	# Nur überschreiben, wenn der Body wirklich noch Bankverbindungs-Render-
	# Code enthält. Schon migrierte Bodies (Marker-Kommentar) bleiben in Ruhe.
	if not current or "Bankverbindung im Page-Footer" in current:
		return
	if "immobilie.bank_konto" not in current and "frappe.throw" not in current:
		# Body wurde schon manuell auf was anderes gesetzt — nicht überschreiben.
		return

	doc.html_content = _MARKER_BODY
	doc.jinja_content = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()
