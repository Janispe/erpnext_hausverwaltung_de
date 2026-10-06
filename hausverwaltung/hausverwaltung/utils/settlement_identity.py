"""Safe ownership tokens without changing persisted accounting document names."""

from hashlib import sha256

import frappe
from frappe.utils import cstr


def hk_marker_owner(name: str) -> str:
	name = cstr(name or "").strip()
	if not name:
		frappe.throw("Die HK-Abrechnung hat keinen eindeutigen Namen; es wurde nichts gebucht.")
	if name.startswith("HK-ID:") or any(char in name for char in "[]\r\n"):
		return "HK-ID:" + sha256(name.encode("utf-8")).hexdigest()
	return name
