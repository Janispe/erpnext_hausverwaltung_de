import frappe
from frappe.utils import now_datetime


def bump_cache_version() -> None:
	"""Bump the cache bust token to invalidate client-side placeholder caches."""
	frappe.cache().set_value("hv_placeholder_cache_bust", now_datetime().isoformat())


def extend_bootinfo(bootinfo: dict) -> None:
	"""Expose cache bust token to the client via bootinfo."""
	bootinfo["hv_placeholder_cache_bust"] = frappe.cache().get_value("hv_placeholder_cache_bust") or ""
