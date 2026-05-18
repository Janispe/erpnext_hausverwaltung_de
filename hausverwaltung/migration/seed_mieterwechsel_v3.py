"""Standalone-Helper: Seed v3-mieterwechsel manuell auf einer Site, ohne den
Migration-Patch zu triggern (z.B. zum Re-Seed nach manueller Loeschung).

Der Patch unter `hausverwaltung/patches/post_model_sync/create_mieterwechsel_process_version_v3.py`
ist der primaere Deploy-Weg — laeuft idempotent bei `bench migrate`. Dieses
Skript hier ist nur fuer Debug / Re-Seed gedacht.

Usage:
    docker exec -w /home/frappe/frappe-bench/sites hausverwaltung_peters-backend-1 \\
        ../env/bin/python /pfad/zu/seed_mieterwechsel_v3.py
"""
from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.create_mieterwechsel_process_version_v3 import (
	execute as _patch_execute,
)


def main():
	frappe.init(site="frontend")
	frappe.connect()
	frappe.set_user("Administrator")
	# Idempotent: laeuft als no-op wenn v3 schon da
	if frappe.db.exists("Prozess Version", "v3-mieterwechsel"):
		print("[INFO] v3-mieterwechsel existiert bereits. Loeschen vor Re-Seed:")
		print("    frappe.delete_doc('Prozess Version', 'v3-mieterwechsel', force=True)")
		return
	_patch_execute()
	frappe.db.commit()
	print("[OK] v3-mieterwechsel angelegt + aktiviert. v2 deaktiviert.")


if __name__ == "__main__":
	main()
