"""Refresh dependent titles for upgrades that already ran document naming."""

from hausverwaltung.hausverwaltung.utils.document_title_sync import refresh_all_titles


def execute() -> None:
	refresh_all_titles()
