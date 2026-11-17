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
			# Reopening must replace the entire editor, including only the DIRECT
			# immutable dependencies, and must discard unrelated draft selection.
			record("dependent_editor_reopen")
			target_a, target_b = "SYN-PW-A-"+uuid4().hex[:10], "SYN-PW-B-"+uuid4().hex[:10]
			dag_package = "pw-dag-"+uuid4().hex[:10]
			for name in (target_a,target_b):
				r = agent.request.post(note_url,headers=headers,data=json.dumps({"synthetic_id":name,"label":"unverändert"}))
				assert r.status == 200
			agent_page.get_by_label("Synthetische Notiz",exact=True).fill(target_a)
			agent_page.get_by_label("Synthetische Notiz",exact=True).press("Tab")
			agent_page.get_by_label("Neue Bezeichnung",exact=True).fill("Vorgänger A")
			agent_page.get_by_label("Paket",exact=True).fill(dag_package)
			with agent_page.expect_response(lambda r:r.url.endswith(API+"submit")) as submitted_a:
				agent_page.get_by_role("button",name="Vorschlag einreichen",exact=True).click()
			assert submitted_a.value.status == 200
			proposal_a = submitted_a.value.json()["message"]
			ref_a = {k:proposal_a[k] for k in ("id","revision","hash")}
			row_a = agent_page.locator('[aria-label="Vorschlagsliste"] > div').filter(has_text=target_a)
			row_a.get_by_role("button",name="Als Vorgänger auswählen",exact=True).click()
			agent_page.get_by_label("Synthetische Notiz",exact=True).fill(target_b)
			agent_page.get_by_label("Synthetische Notiz",exact=True).press("Tab")
			agent_page.get_by_label("Neue Bezeichnung",exact=True).fill("Nachfolger B")
			with agent_page.expect_response(lambda r:r.url.endswith(API+"submit")) as submitted_b:
				agent_page.get_by_role("button",name="Vorschlag einreichen",exact=True).click()
			assert submitted_b.value.status == 200
			proposal_b = submitted_b.value.json()["message"]
			assert proposal_b["dependencies"] == [ref_a]
			agent_page.reload(wait_until="domcontentloaded")
			row_b = agent_page.locator('[aria-label="Vorschlagsliste"] > div').filter(has_text=target_b)
			with agent_page.expect_response(lambda r:r.url.endswith(API+"view")):
				row_b.get_by_role("button",name="Ansehen",exact=True).click()
			expect(agent_page.get_by_label("Paket",exact=True)).to_have_value(dag_package)
			deps = agent_page.locator('[aria-label="Explizite Vorgänger"]')
			assert json.loads(deps.inner_text()) == [ref_a]
			# Select a proposal from another package as draft, then reopen B.
			agent_page.locator('[aria-label="Vorschlagsliste"] > div').filter(has_text=target).get_by_role("button",name="Als Vorgänger auswählen",exact=True).click()
			assert any(x["id"]==proposal["id"] for x in json.loads(deps.inner_text()))
			with agent_page.expect_response(lambda r:r.url.endswith(API+"view")):
				row_b.get_by_role("button",name="Ansehen",exact=True).click()
			assert json.loads(deps.inner_text()) == [ref_a]
			agent_page.get_by_label("Neue Bezeichnung",exact=True).fill("B nur Bezeichnung geändert")
			with agent_page.expect_response(lambda r:r.url.endswith(API+"revise")) as revised_b:
				agent_page.get_by_role("button",name="Neue Revision mit Preview",exact=True).click()
			assert revised_b.value.status == 200
			proposal_b = revised_b.value.json()["message"]
			assert proposal_b["revision"]==2 and proposal_b["dependencies"]==[ref_a]
			agent_page.locator("p[role=status]").scroll_into_view_if_needed()
			agent_page.screenshot(path=str(output/"04-dependent-editor.png"))
			before_b = agent.request.get(note_url+"/"+target_b).json()["data"]
			reviewer_page.reload(wait_until="domcontentloaded")
			with reviewer_page.expect_response(lambda r:r.url.endswith(API+"view")):
				reviewer_page.locator('[aria-label="Vorschlagsliste"] > div').filter(has_text=target_b).get_by_role("button",name="Ansehen",exact=True).click()
			expect(reviewer_page.locator("p[role=status]")).to_contain_text("Revision 2")
			with reviewer_page.expect_response(lambda r:r.url.endswith(API+"review")) as review_b:
				reviewer_page.get_by_role("button",name="Diese Revision freigeben",exact=True).click()
			assert review_b.value.status == 200
			with reviewer_page.expect_response(lambda r:r.url.endswith(API+"execute")) as blocked_b:
				reviewer_page.get_by_role("button",name="Genehmigte Revision ausführen",exact=True).click()
			assert blocked_b.value.status != 200
			after_b = agent.request.get(note_url+"/"+target_b).json()["data"]
			assert all(before_b[k]==after_b[k] for k in ("label","generation","modified"))
			proof["dependent_editor"]={"reopened_direct_binding":ref_a,"revised_child":{k:proposal_b[k] for k in ("id","revision","hash")},"unrelated_draft_discarded":True,"label_only_revision_preserved_direct_binding":True,"execute_before_predecessor_status":blocked_b.value.status,"business_record_unchanged":True}
			# A descriptive package created through the API must also accept
			# further normal Desk submissions without metadata mutation.
			record("existing_descriptive_package_desk_submit")
			descriptive_package="pw-descriptive-"+uuid4().hex[:10]
			package_meta={"title":"Synthetik · beschreibender Titel","reason":"Synthetischer Anlass für den Pilot","lane_label":"Synthetische Zeilen"}
			seed_target,new_target=["SYN-PW-META-"+uuid4().hex[:10] for _ in range(2)]
			for name in (seed_target,new_target):
				r=agent.request.post(note_url,headers=headers,data=json.dumps({"synthetic_id":name,"label":"vorher"}))
				assert r.status==200
			seed=agent.request.post(args.base_url+API+"submit",headers=headers,data=json.dumps({"key":uuid4().hex,"package":descriptive_package,"package_meta":package_meta,"payload":{"target":seed_target,"label":"Seed"},"metadata":{"title":"Seed","summary":"Synthetischer Start"}}))
			assert seed.status==200
			before_new=agent.request.get(note_url+"/"+new_target).json()["data"]
			agent_page.get_by_role("button",name="Vorgängerauswahl leeren",exact=True).click()
			agent_page.get_by_label("Synthetische Notiz",exact=True).fill(new_target)
			agent_page.get_by_label("Synthetische Notiz",exact=True).press("Tab")
			agent_page.get_by_label("Neue Bezeichnung",exact=True).fill("Weitere synthetische Vorschau")
			agent_page.get_by_label("Paket",exact=True).fill(descriptive_package)
			with agent_page.expect_response(lambda r:r.url.endswith(API+"submit")) as submitted_existing:
				agent_page.get_by_role("button",name="Vorschlag einreichen",exact=True).click()
			assert submitted_existing.value.status==200
			posted=parse_qs(submitted_existing.value.request.post_data or "")
			if not posted:posted=submitted_existing.value.request.post_data_json
			assert "package_meta" not in posted
			new_proposal=submitted_existing.value.json()["message"]
			expect(agent_page.locator("p[role=status]")).to_contain_text(new_proposal["id"])
			after_new=agent.request.get(note_url+"/"+new_target).json()["data"]
			assert all(before_new[k]==after_new[k] for k in ("label","generation","modified"))
			graph=agent.request.post(args.base_url+API+"package_graph",headers=headers,data=json.dumps({"package":descriptive_package})).json()["message"]
			assert graph["package"]["total"]==2
			assert all(graph["package"][key]==value for key,value in package_meta.items())
			proof["existing_descriptive_package"]={"package":descriptive_package,"metadata":package_meta,"submit_omitted_package_meta":True,"metadata_unchanged":True,"business_record_unchanged":True,"proposal":{k:new_proposal[k] for k in ("id","revision","hash")}}
			agent_page.locator("p[role=status]").scroll_into_view_if_needed()
			agent_page.screenshot(path=str(output/"05-existing-descriptive-package.png"))

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
