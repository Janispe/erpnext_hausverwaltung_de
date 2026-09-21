"""Run before hausverwaltung is installed; bench execute requires an installed app."""

import os

import frappe

os.chdir("/home/frappe/frappe-bench/sites")
frappe.init(site="fac.localhost")
frappe.connect()
try:
	frappe.set_user("Administrator")
	from hausverwaltung.hausverwaltung.services.fac_test_setup import prepare_mail_merge

	prepare_mail_merge()
finally:
	frappe.destroy()
