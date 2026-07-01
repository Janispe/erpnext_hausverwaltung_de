"""Ensure Briefkopf uses declared variables for the address window."""

from __future__ import annotations

from hausverwaltung.hausverwaltung.patches.post_model_sync.fix_briefkopf_address_from_standard_paths import (
	execute as sync_briefkopf_address_from_standard_paths,
)


def execute() -> None:
	sync_briefkopf_address_from_standard_paths()
