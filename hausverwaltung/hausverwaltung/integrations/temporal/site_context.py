from __future__ import annotations

import os
from contextlib import contextmanager

import frappe



def get_default_site() -> str:
	return (
		(os.environ.get("HV_TEMPORAL_SITE") or "").strip()
		or (os.environ.get("SITE_NAME") or "").strip()
		or "frontend"
	)


@contextmanager
def activate_site(site: str | None = None):
	site_name = (site or "").strip() or get_default_site()
	frappe.init(site=site_name)
	frappe.connect()
	try:
		yield site_name
		try:
			frappe.db.commit()
		except Exception:
			pass
	finally:
		try:
			frappe.destroy()
		except Exception:
			pass
