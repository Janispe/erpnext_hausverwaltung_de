from __future__ import annotations

from frappe.utils import getdate


def default_wertstellungsdatum_from_posting_date(doc, method=None):
	"""Default Journal Entry value date to posting date when no explicit value exists."""
	if not _has_field(doc, "custom_wertstellungsdatum"):
		return
	if doc.get("custom_wertstellungsdatum") or not doc.get("posting_date"):
		return

	doc.set("custom_wertstellungsdatum", getdate(doc.get("posting_date")))


def _has_field(doc, fieldname: str) -> bool:
	meta = getattr(doc, "meta", None)
	if not meta or not hasattr(meta, "get_field"):
		return False
	return bool(meta.get_field(fieldname))
