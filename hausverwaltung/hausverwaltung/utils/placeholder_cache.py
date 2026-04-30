import frappe
from frappe.utils import now_datetime


def bump_cache_version() -> None:
	"""Bump the cache bust token to invalidate client-side placeholder caches."""
	frappe.cache().set_value("hv_placeholder_cache_bust", now_datetime().isoformat())


def extend_bootinfo(bootinfo: dict) -> None:
	"""Expose cache bust token + UI settings to the client via bootinfo."""
	bootinfo["hv_placeholder_cache_bust"] = frappe.cache().get_value("hv_placeholder_cache_bust") or ""

	# UI-Einstellungen für JS-Code (Picker-Modal-Breite, PDF-Defaults etc.)
	try:
		settings = frappe.get_cached_doc("Hausverwaltung Einstellungen")
		picker_vw = getattr(settings, "picker_modal_width_vw", None)
		skip_dialog = getattr(settings, "serienbrief_pdf_skip_dialog", None)
		default_format = getattr(settings, "serienbrief_pdf_default_format", None)
	except Exception:
		picker_vw = skip_dialog = default_format = None
	bootinfo["hv_ui"] = {
		"picker_modal_width_vw": int(picker_vw) if picker_vw else 0,
		"serienbrief_pdf_skip_dialog": int(skip_dialog or 0),
		"serienbrief_pdf_default_format": default_format or "Serienbrief Dokument",
	}
