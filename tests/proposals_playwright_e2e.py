"""Explicit real Desk E2E on a newly bootstrapped synthetic loopback site.

Use the existing Chromium executable and a separately staged, pinned Playwright
wheel target. No browser downloads, global installs, traces or password captures.
Errors intentionally report phase/type/frame metadata only, never login values.
"""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import traceback
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


API = "/api/method/hausverwaltung.proposals.frappe_service."


def main(args):
	from playwright.sync_api import sync_playwright, expect

	auth = json.loads(Path(args.auth_file).read_text())
	assert auth.get("purpose") == "hv-proposals-disposable-testauth"
	output = Path(args.output_dir)
	output.mkdir(parents=True, exist_ok=True)
	target = "SYN-PW-" + uuid4().hex[:12]
	package = "pw-" + uuid4().hex[:12]
	proof = {"success": False, "phase": "launch", "target": target, "package": package}
	origin = urlsplit(args.base_url)

	def record(phase):
		proof["phase"] = phase
		(output / "desk-e2e.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2))

	try:
		with sync_playwright() as playwright:
			browser = playwright.chromium.launch(executable_path=args.chromium, headless=True,
				args=["--disable-dev-shm-usage", "--disable-background-networking", "--disable-sync", "--no-first-run"])
			proof["browser_version"] = browser.version

			def context():
				ctx = browser.new_context(viewport={"width": 1400, "height": 1000}, locale="de-DE")
				def isolated(route):
					url = urlsplit(route.request.url)
					if url.scheme in ("data", "blob") or (url.scheme, url.netloc) == (origin.scheme, origin.netloc): route.continue_()
					else: route.abort()
				ctx.route("**/*", isolated)
				return ctx

			def login(ctx, account):
				page = ctx.new_page()
				page.goto(args.base_url + "/login", wait_until="domcontentloaded")
				page.locator("#login_email:visible").fill(account + "@hv4.invalid")
				page.locator("#login_password:visible").fill(auth[account])
				with page.expect_response(lambda r: r.url.endswith("/api/method/login")) as response:
					page.locator(".for-login button[type=submit]:visible").click()
				assert response.value.status == 200
				page.goto(args.base_url + "/desk/hv-proposals", wait_until="domcontentloaded")
				page.get_by_role("button", name="Vorschlag einreichen", exact=True).wait_for()
				return page

			agent = context()
			record("agent_normal_ui_login")
			agent_page = login(agent, "agent")
			expect(agent_page.get_by_role("button", name="Diese Revision freigeben", exact=True)).to_have_count(0)
			csrf = agent_page.evaluate("frappe.csrf_token")
			headers = {"X-Frappe-CSRF-Token": csrf, "Content-Type": "application/json"}
			note_url = args.base_url + "/api/resource/HV%20Synthetic%20Note"
			created = agent.request.post(note_url, headers=headers,
				data=json.dumps({"synthetic_id": target, "label": "Bezeichnung vorher"}))
			assert created.status == 200
			initial = created.json()["data"]
			proof["before"] = {key: initial[key] for key in ("label", "generation", "modified")}
			agent_page.get_by_label("Synthetische Notiz", exact=True).fill(target)
			agent_page.get_by_label("Synthetische Notiz", exact=True).press("Tab")
			agent_page.get_by_label("Neue Bezeichnung", exact=True).fill("Bezeichnung nach Freigabe")
			agent_page.get_by_label("Paket", exact=True).fill(package)
			record("agent_desk_submit")
			with agent_page.expect_response(lambda r: r.url.endswith(API + "submit")) as submitted:
				agent_page.get_by_role("button", name="Vorschlag einreichen", exact=True).click()
			assert submitted.value.status == 200
			proposal = submitted.value.json()["message"]
			binding = {key: proposal[key] for key in ("id", "revision", "hash")}
			proof["binding"] = binding
			expect(agent_page.locator("p[role=status]")).to_contain_text("Prüfung offen")
			expect(agent_page.locator('[aria-label="Vorher"]')).to_have_text("Bezeichnung vorher")
			expect(agent_page.locator('[aria-label="Nachher"]')).to_have_text("Bezeichnung nach Freigabe")
			actual = agent.request.get(note_url + "/" + target).json()["data"]
			assert {key: actual[key] for key in proof["before"]} == proof["before"]
			proof["preview_without_business_save_including_modified"] = True
			agent_page.locator("p[role=status]").scroll_into_view_if_needed()
			agent_page.screenshot(path=str(output / "01-agent-preview.png"))

			reviewer = context()
			record("separate_reviewer_normal_ui_login")
			reviewer_page = login(reviewer, "reviewer")
			row = reviewer_page.locator('[aria-label="Vorschlagsliste"] > div').filter(has_text=target)
			record("reviewer_load_exact_proposal")
			with reviewer_page.expect_response(lambda r: r.url.endswith(API + "view")) as viewed:
				row.get_by_role("button", name="Ansehen", exact=True).click()
			assert viewed.value.status == 200
			expect(reviewer_page.locator("p[role=status]")).to_contain_text(proposal["id"])
			expect(reviewer_page.locator("p[role=status]")).to_contain_text("Revision 1")
			record("reviewer_exact_revision_approval")
			with reviewer_page.expect_response(lambda r: r.url.endswith(API + "review")) as reviewed:
				reviewer_page.get_by_role("button", name="Diese Revision freigeben", exact=True).click()
			assert reviewed.value.status == 200
			request = reviewed.value.request
			data = parse_qs(request.post_data or "")
			if "binding" in data: actual_binding = json.loads(data["binding"][0])
			else:
				data = request.post_data_json
				actual_binding = json.loads(data["binding"]) if isinstance(data["binding"], str) else data["binding"]
			assert actual_binding == binding
			proof["actual_review_request_binding_matches"] = True
			expect(reviewer_page.locator("p[role=status]")).to_contain_text("Freigegeben")
			reviewer_page.locator("p[role=status]").scroll_into_view_if_needed()
			reviewer_page.screenshot(path=str(output / "02-reviewer-approved.png"))

			record("reviewer_normal_save_execute")
			with reviewer_page.expect_response(lambda r: r.url.endswith(API + "execute")) as executed:
				reviewer_page.get_by_role("button", name="Genehmigte Revision ausführen", exact=True).click()
			assert executed.value.status == 200
			result = executed.value.json()["message"]
			assert result["status"] == "Succeeded"
			proof["result"] = result["result"]
			expect(reviewer_page.locator("p[role=status]")).to_contain_text("Ausgeführt")
			expect(reviewer_page.locator('[aria-label="Ausführungsergebnis"]')).to_contain_text(target)
			expect(reviewer_page.locator('[aria-label="Audit"]')).to_contain_text("Revision freigegeben")
			expect(reviewer_page.locator('[aria-label="Audit"]')).to_contain_text("Änderung ausgeführt")
			actual = agent.request.get(note_url + "/" + target).json()["data"]
			assert actual["label"] == "Bezeichnung nach Freigabe" and actual["generation"] == 1
			assert actual["modified"] != proof["before"]["modified"]
			proof["after"] = {key: actual[key] for key in ("label", "generation", "modified")}
			proof["visible_audit"] = reviewer_page.locator('[aria-label="Audit"]').inner_text()
			reviewer_page.locator("p[role=status]").scroll_into_view_if_needed()
			reviewer_page.screenshot(path=str(output / "03-reviewer-executed.png"))
			proof["success"] = True
			record("complete")
			browser.close()
		return True
	except BaseException as failure:
		proof["error_type"] = type(failure).__name__
		proof["frames"] = [{"file": f.filename, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(failure.__traceback__)]
		(output / "desk-e2e.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2))
		return False


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--synthetic", action="store_true", required=True)
	parser.add_argument("--base-url", required=True)
	parser.add_argument("--auth-file", required=True)
	parser.add_argument("--dependencies", required=True)
	parser.add_argument("--chromium", default="/usr/bin/chromium")
	parser.add_argument("--output-dir", required=True)
	args = parser.parse_args()
	url = urlsplit(args.base_url)
	if url.scheme != "http" or url.hostname != "127.0.0.1": parser.error("Own synthetic loopback site only")
	sys.path.insert(0, args.dependencies)
	with open("/dev/null", "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
		ok = main(args)
	raise SystemExit(0 if ok else 1)
