"""Drive the Bankimport and proposals Desk pages against the live test backend."""
import json
from pathlib import Path
import sys
from urllib.parse import urlencode


def run(base_url, auth_file, fixture_file, dependencies, chromium):
	sys.path.insert(0, dependencies)
	from playwright.sync_api import expect, sync_playwright

	auth = json.loads(Path(auth_file).read_text())
	assert auth["purpose"] == "hv-proposals-disposable-testauth"
	data = json.loads(Path(fixture_file).read_text())
	package = data["package"] + "-NEXT"
	with sync_playwright() as playwright:
		browser = playwright.chromium.launch(executable_path=chromium, headless=True,
			args=["--disable-dev-shm-usage"])
		page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="de-DE")
		page.goto(base_url + "/login")
		page.locator("#login_email:visible").fill("bank-reviewer@hv4.invalid")
		page.locator("#login_password:visible").fill(auth["reviewer"])
		page.locator(".for-login button[type=submit]:visible").click()
		page.wait_for_url("**/desk*")
		page.goto(base_url + "/desk/hv-proposals")
		page.get_by_role("combobox", name="Art", exact=True).select_option("booking")
		page.locator(f'[data-package="{package}"]').click()
		page.get_by_role("button", name="Liste", exact=True).click()
		page.get_by_role("row").filter(has_text="Wiesenpark GmbH").click()
		expect(page.get_by_role("heading", name="Buchung (Vorschau)")).to_be_visible()
		expect(page.get_by_text("hoch", exact=True)).to_be_visible()
		detail_link = page.locator('.hv-prop-detail a[href*="bankimport_v2"]').first
		expect(detail_link).to_have_attribute("href", "/app/bankimport_v2?" + urlencode(
			{"import": data["import_name"], "row": data["lanes"][1]["row"]}))
		detail_link.click()
		bank = page.frame_locator("iframe.hv-bankimport-frame")
		expect(bank.get_by_text(package, exact=False)).to_be_visible()
		bank.get_by_role("button", name="Ablehnen …", exact=True).click()
		bank.get_by_label("Begründung (Pflicht)").fill("Synthetische Ablehnung")
		bank.get_by_role("button", name="Ablehnen", exact=True).click()
		expect(bank.get_by_text("Synthetische Ablehnung", exact=False)).to_be_visible()
		bank.get_by_role("button", name="Vorschläge übernehmen …", exact=False).click()
		dialog = bank.get_by_role("dialog", name="Vorschläge übernehmen", exact=False)
		expect(dialog).to_be_visible()
		dialog.press("Escape")
		page.goto(base_url + "/desk/bankimport_v2?" + urlencode(
			{"import": data["import_name"], "row": data["lanes"][7]["row"]}))
		bank.get_by_role("button", name="Übernehmen & buchen", exact=True).click()
		expect(bank.get_by_text("Buchungssatz gebucht", exact=False)).to_be_visible()
		browser.close()
	print("Bankimport und Vorschläge-Seite: Browser-Verträge bestanden.")


if __name__ == "__main__":
	run(*sys.argv[1:])
