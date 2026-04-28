from __future__ import annotations

from hausverwaltung.hausverwaltung.patches.post_model_sync.create_mieterwechsel_process_versions_v2 import (
	execute as seed_mieterwechsel_process_versions_v2,
)


def execute() -> None:
	seed_mieterwechsel_process_versions_v2()
