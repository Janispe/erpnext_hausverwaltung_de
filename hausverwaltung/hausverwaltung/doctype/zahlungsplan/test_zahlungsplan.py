import frappe


def test_importable():
	# Basic smoke test: module loads
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import Zahlungsplan  # noqa: F401
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan_zeile.zahlungsplan_zeile import ZahlungsplanZeile  # noqa: F401
