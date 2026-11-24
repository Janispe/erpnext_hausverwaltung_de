from urllib.parse import urlencode

import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		redirect = frappe.request.path
		if frappe.request.query_string:
			redirect += "?" + frappe.request.query_string.decode("ascii", errors="ignore")
		frappe.local.flags.redirect_location = "/login?" + urlencode({"redirect-to": redirect})
		raise frappe.Redirect
	context.csrf_token = get_csrf_token()
