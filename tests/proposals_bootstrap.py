"""Legt auf einer frischen Wegwerf-Site die Testkonten für die Vorschlags-Tests an.

Nur für scripts/hv_tests.sh. Läuft im sites-Ordner der Test-Bench, liest die
Wegwerf-Passwörter als JSON von stdin und gibt keines davon aus.
"""

import argparse
import json
import sys

import frappe
from frappe.utils.password import update_password

ACCOUNTS = {
	"agent": ["HV Proposal Agent"],
	"reviewer": ["HV Proposal Reviewer"],
	# Das gesperrte Konto teilt das Agentenpasswort, siehe proposals_http_contracts.py.
	"blocked": ["HV Proposal Agent"],
}


def ensure_account(account, roles, password):
	email = f"{account}@hv4.invalid"
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
	user.first_name = f"Synthetisch {account}"
	user.enabled = 1
	user.send_welcome_email = 0
	user.set("roles", [{"role": role} for role in roles])
	user.save(ignore_permissions=True)
	update_password(email, password, logout_all_sessions=True)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--site", required=True)
	args = parser.parse_args()
	auth = json.load(sys.stdin)
	if auth.get("purpose") != "hv-proposals-disposable-testauth":
		parser.error("Markierte Wegwerf-Zugangsdaten erforderlich")
	frappe.init(site=args.site, sites_path=".")
	frappe.connect()
	try:
		if not (frappe.conf.get("allow_tests") and frappe.conf.get("hv_disposable_test_site")):
			parser.error("Nur auf einer als Wegwerf-Testsite markierten Site")
		for account, roles in ACCOUNTS.items():
			ensure_account(account, roles, auth["agent" if account == "blocked" else account])
		frappe.db.commit()
	finally:
		frappe.destroy()
	print("Testkonten angelegt:", ", ".join(f"{account}@hv4.invalid" for account in ACCOUNTS))


if __name__ == "__main__":
	main()
