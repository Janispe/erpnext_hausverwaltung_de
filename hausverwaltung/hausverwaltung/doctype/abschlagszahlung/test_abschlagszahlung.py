import frappe


def test_importable():
	# Basic smoke test: module loads
	from hausverwaltung.hausverwaltung.doctype.abschlagszahlung.abschlagszahlung import Abschlagszahlung  # noqa: F401

