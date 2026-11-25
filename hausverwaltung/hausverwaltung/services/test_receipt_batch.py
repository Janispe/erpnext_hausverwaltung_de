"""Isolated ERPNext tests with generated receipt media and controlled providers."""

import base64
import hashlib
import hmac
import io
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.client import get as read_doc
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.tests import IntegrationTestCase
from PIL import Image, ImageDraw

from hausverwaltung.hausverwaltung.agent_tools import accounting_evidence
from hausverwaltung.hausverwaltung.services import bulk_extraction
from hausverwaltung.hausverwaltung.services import receipt_batch as batch
from hausverwaltung.hausverwaltung.services import receipt_evidence
from hausverwaltung.proposals import receipt_action


class TestReceiptBatch(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.flags = {
			"hv_receipt_pilot": 1, "hv_receipt_batch": 1,
			"hv_receipt_webhook_url": "https://paperclip.invalid/fire",
			"hv_receipt_webhook_secret": "synthetic-webhook-key",
		}
		settings = patch.dict(frappe.conf, self.flags)
		settings.start()
		self.addCleanup(settings.stop)

	def fixture(self, is_pdf=False):
		pages = [Image.new("RGB", (300, 180), "white") for _ in range(3 if is_pdf else 1)]
		for index, page in enumerate(pages):
			draw = ImageDraw.Draw(page)
			if is_pdf:
				draw.text((15, 20), ["TESTMARKT Teil 1", "TESTMARKT Teil 2: EUR 15,50", "TESTKASSE: EUR 24,10"][index], fill="black")
			else:
				for column, value in enumerate(["15,50", "24,10", "31,70"]):
					x = column * 100 + 10
					draw.rectangle((x, 10, x + 80, 160), outline="black")
					draw.text((x + 2, 40), f"EUR {value}", fill="black")
		stream = io.BytesIO()
		if is_pdf:
			pages[0].save(stream, format="PDF", save_all=True, append_images=pages[1:])
		else:
			pages[0].save(stream, format="PNG")
		return stream.getvalue()

	def upload(self, content, request_id=None, note="Synthetisch vorgestreckt", is_pdf=False, context=None):
		filename = "test.pdf" if is_pdf else "test.png"
		upload = SimpleNamespace(stream=io.BytesIO(content), filename=filename)
		with patch.object(frappe.local, "request", SimpleNamespace(files={"file": upload}), create=True):
			return batch.upload(request_id or str(uuid.uuid4()), note=note, context=context)["name"]

	def raw_analysis(self, amount):
		return {
			"haendler": "TESTMARKT", "datum": "2026-10-08", "waehrung": "EUR", "gesamtbetrag": amount,
			"positionen": [{"beschreibung": "Testposition", "betrag": amount, "kostenart": "1"}],
		}

	def scope(self, name):
		# The run lookup itself has a separate provider-bound test below.
		scope = {"issue_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}
		return patch.object(batch, "_agent_job", side_effect=lambda: (frappe.get_doc(batch.JOB, name), scope))

	def submit(self, task, raw, forged=False, shortlist=None):
		if task["step"] == 0:
			return batch.submit_step(0, result=raw)
		crops = []
		for page, left, top, right, bottom in task["regions"]:
			with Image.open(io.BytesIO(base64.b64decode(task["pages"][page]))) as image:
				w, h = image.size
				crop = image.crop((left*w//1000, top*h//1000, (right*w+999)//1000, (bottom*h+999)//1000))
				if forged:
					crop.paste("magenta", box=(0, 0, crop.width, crop.height))
				payload = io.BytesIO()
				crop.convert("RGB").save(payload, format="PNG")
				crops.append(base64.b64encode(payload.getvalue()).decode("ascii"))
		step = task["step"]
		attempt = receipt_evidence.start(step, raw.get("haendler"))["attempt"]
		checked = receipt_evidence.tools(step, "tools/call", {
			"name": "verify_shortlist", "arguments": {"shortlist": shortlist or []},
		}, attempt)["structuredContent"]
		payload = {"result": raw, "crops": crops, "evidence_digest": checked["digest"], "evidence_attempt": attempt}
		if forged:
			return batch.submit_step(step, **payload)

		def show_failure(_job, exc):
			raise AssertionError("Valid receipt step failed") from exc

		with patch.object(batch, "_step_error", side_effect=show_failure):
			return batch.submit_step(step, **payload)

	def test_photo_retry_resume_and_revision_preserve_other_receipts(self):
		raw = self.fixture()
		name = self.upload(raw)
		self.assertEqual(name, self.upload(raw, request_id=name))
		with self.assertRaises(frappe.ValidationError):
			self.upload(raw, request_id=name, note="Anderer Upload")
		other = self.upload(raw)
		self.assertNotEqual(name, other)
		upload = frappe.get_doc(batch.UPLOAD, name)
		self.assertEqual(raw, batch.private_attachment(upload, upload.file_url, upload.receipt_digest)[1])

		regions = [[1, 0, 0, 320, 1000], [1, 335, 0, 660, 1000], [1, 675, 0, 1000, 1000]]
		inventory = {"bons": [{"ausschnitte": [r], "frage": ""} for r in regions], "leere_seiten": []}
		with self.scope(name):
			task = batch.next_step()["task"]
			self.assertEqual(task["context"]["upload_notiz"], "Synthetisch vorgestreckt")
			self.assertEqual(set(task["pages"]), {1})
			self.submit(task, inventory)
			first_step = batch.next_step()["task"]
			self.assertEqual(self.submit(first_step, self.raw_analysis(15.50))["status"], "Running")
			first = frappe.get_doc(batch.JOB, name)
			self.assertEqual(batch._progress(first)["processed"], 1)
			first_bon = json.loads(first.results)[0]["proposal"]
		# A distinct Paperclip run after interruption resumes at the next receipt.
		with self.scope(name):
			batch.submit_step(first_step["step"])
			self.assertEqual(frappe.db.count(batch.pilot.PROPOSAL, {"receipt_upload": name}), 1)
			second = batch.next_step()["task"]
			self.assertEqual(second["step"], 2)
			self.assertEqual(self.submit(second, self.raw_analysis(24.10), forged=True)["status"], "AnalysisError")
			self.assertEqual(frappe.db.count(batch.pilot.PROPOSAL, {"receipt_upload": name}), 1)
			self.submit(batch.next_step()["task"], self.raw_analysis(24.10))
			self.submit(batch.next_step()["task"], self.raw_analysis(31.70))
			self.assertEqual(batch.next_step()["status"], "Questions")
		done = frappe.get_doc(batch.JOB, name)
		self.assertEqual(batch._progress(done)["processed"], 3)
		results = json.loads(done.results)
		self.assertEqual([r["data"]["belegsumme"] for r in results], [15.5, 24.1, 31.7])
		self.assertEqual(len({r["proposal"] for r in results}), 3)
		self.assertEqual(frappe.db.count(batch.pilot.PROPOSAL, {"receipt_upload": other}), 0)

		proposal = frappe.get_doc(batch.pilot.PROPOSAL, first_bon)
		source = receipt_action._source(proposal)
		prior_crop = proposal.file_url
		revision = str(uuid.uuid4())
		self.assertEqual(batch.revise(first_bon, revision, name, "Rand korrigieren")["name"], revision)
		self.assertEqual(batch.revise(first_bon, revision, name, "Rand korrigieren")["name"], revision)
		with self.scope(revision):
			old_task = batch.next_step()["task"]
		newer = str(uuid.uuid4())
		batch.revise(first_bon, newer, revision, "Weiter links")
		with self.scope(revision):
			self.assertEqual(self.submit(old_task, inventory)["status"], "Superseded")
		proposal.reload()
		self.assertNotEqual(source, receipt_action._source(proposal))
		with self.assertRaises(frappe.ValidationError):
			batch.require_bookable(proposal)

		with self.scope(newer):
			self.submit(batch.next_step()["task"], {"bons": [{"ausschnitte": [[1, 0, 0, 310, 1000]]}], "leere_seiten": []})
			self.assertEqual(self.submit(batch.next_step()["task"], self.raw_analysis(16.25))["status"], "Questions")
		proposal.reload()
		current, previous = batch.inbox_detail(proposal)["revisions"]
		self.assertEqual((current["belegsumme"], previous["belegsumme"]), (16.25, 15.50))
		self.assertEqual(current["analysis"]["previous_job"], name)
		self.assertEqual(previous["analysis"]["crop_url"], prior_crop)
		self.assertEqual(current["analysis"]["revision_note"], "Weiter links")
		attachment, _ = batch.verified_crop(proposal)
		self.assertEqual(attachment.is_private, 1)
		for other_receipt in results[1:]:
			stored = frappe.get_doc(batch.pilot.PROPOSAL, other_receipt["proposal"])
			self.assertEqual(json.loads(stored.extracted_data), other_receipt["data"])
		self.assertFalse(proposal.linked_purchase_invoice)

	def test_private_file_download_ignores_old_analysis_user_ownership(self):
		name = self.upload(self.fixture())
		upload = frappe.get_doc(batch.UPLOAD, name)
		with self.scope(name):
			self.submit(batch.next_step()["task"], {
				"bons": [{"ausschnitte": [[1, 0, 0, 1000, 1000]]}], "leere_seiten": [],
			})
			self.submit(batch.next_step()["task"], self.raw_analysis(15.50))
		proposal = frappe.get_doc(batch.pilot.PROPOSAL, {"receipt_upload": name})
		original = find_file_by_url(upload.file_url)
		crop = find_file_by_url(proposal.file_url)
		self.assertEqual(frappe.db.count("File", {"file_url": upload.file_url}), 1)
		duplicate = original.create_attachment_copy(proposal.doctype, proposal.name, ignore_permissions=True)
		user = f"receipt-analysis-{uuid.uuid4().hex}@example.invalid"
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "Analyse", "send_welcome_email": 0}).insert()
		for file in (original, duplicate, crop):
			file.db_set("owner", user)
		frappe.set_user(user)
		try:
			for file in (original, duplicate, crop):
				self.assertIsNone(find_file_by_url(file.file_url))
				self.assertIsNone(find_file_by_url(file.file_url, name=file.name))
				self.assertFalse(frappe.has_permission("File", "read", doc=file.name))
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(find_file_by_url(upload.file_url))
		self.assertTrue(find_file_by_url(proposal.file_url))

	def test_codex_next_step_receives_only_assigned_original(self):
		content = self.fixture(is_pdf=True)
		name = self.upload(content, is_pdf=True)
		with self.scope(name):
			with self.assertRaises(frappe.PermissionError):
				batch.codex_next_step()
			with patch.dict(frappe.conf, {"hv_receipt_codex": 1}):
				task = batch.codex_next_step()["task"]
				self.assertEqual(task["step"], 0)
				self.assertEqual(task["original"]["extension"], "pdf")
				self.assertEqual(base64.b64decode(task["original"]["content"]), content)
				self.assertNotIn("pages", task)
				with self.assertRaises(frappe.PermissionError):
					batch.next_step()

	def test_pdf_pages_and_overlaps_are_checked(self):
		name = self.upload(self.fixture(is_pdf=True), is_pdf=True)
		cases = {"bons": [
			{"ausschnitte": [[1, 0, 0, 1000, 1000], [2, 0, 0, 1000, 1000]]},
			{"ausschnitte": [[3, 0, 0, 1000, 1000]], "frage": "Endbetrag am unteren Rand unlesbar."},
		], "leere_seiten": []}
		with self.scope(name):
			overview = batch.next_step()["task"]
			self.assertEqual(set(overview["pages"]), {1, 2, 3})
			self.assertEqual(overview["context"]["upload_notiz"], "Synthetisch vorgestreckt")
			self.submit(overview, cases)
			first_task = batch.next_step()["task"]
			self.assertEqual(set(first_task["pages"]), {1, 2})
			self.submit(first_task, self.raw_analysis(15.50))
			second_task = batch.next_step()["task"]
			self.assertEqual(set(second_task["pages"]), {3})
			self.assertEqual(self.submit(second_task, self.raw_analysis(24.10))["status"], "Questions")
		first, second = json.loads(frappe.get_doc(batch.JOB, name).results)
		proposal = frappe.get_doc(batch.pilot.PROPOSAL, first["proposal"])
		_, generated = batch.verified_crop(proposal)
		self.assertEqual(len(batch.invoice_extraction._render_pdf_pages_png(generated, page_limit=2)), 2)
		self.assertIn("unlesbar", second["data"]["analysis"]["question"])
		with self.assertRaises(frappe.ValidationError):
			batch.require_bookable(frappe.get_doc(batch.pilot.PROPOSAL, second["proposal"]))
		overlap = batch._inventory({
			"bons": [{"ausschnitte": [[1, 0, 0, 550, 1000]]}, {"ausschnitte": [[1, 500, 0, 1000, 1000]]}],
			"leere_seiten": [],
		}, 1, None)
		self.assertTrue(all("überlappen" in case["question"] for case in overlap))
		with self.assertRaises(ValueError):
			batch._inventory(cases, 4, None)

	def test_account_comparison_verifies_sources_and_company(self):
		suffix = uuid.uuid4().hex[:10]
		company = frappe.get_all("Company", pluck="name", limit=1)[0]
		currency = frappe.db.get_value("Company", company, "default_currency")
		merchant = f"Bon-Vergleich {suffix}"

		def insert(doctype, name, **fields):
			row = frappe.get_doc({"doctype": doctype, "name": name, **fields})
			row.db_insert()
			return row.name

		supplier_id = insert("Supplier", f"Interne Lieferanten-ID {suffix}", supplier_name=merchant, disabled=0)
		other_supplier = insert("Supplier", f"Fremd {suffix}", supplier_name=f"Fremd {suffix}", disabled=0)
		account = insert("Account", f"Bon Aufwand {suffix}", account_name=f"Bon Aufwand {suffix}", company=company,
			account_currency=currency, root_type="Expense", is_group=0, disabled=0)
		insert("Kostenart nicht umlagefaehig", f"Bonart {suffix}", konto=account, artikel="Synthetischer Artikel")
		center = insert("Cost Center", f"Bonobjekt {suffix}", cost_center_name=f"Bonobjekt {suffix}", company=company,
			is_group=0, disabled=0)
		correct = f"Gleicher Lieferant {suffix}"
		for invoice, supplier, line, cost_center in [
			(correct, supplier_id, "correct", center),
			(f"Fremdbeleg {suffix}", other_supplier, "foreign", center),
			(f"Fremdes Objekt {suffix}", supplier_id, "foreign-object", "Andere Kostenstelle"),
		]:
			insert("Purchase Invoice", invoice, supplier=supplier, company=company, docstatus=1,
				posting_date="2026-01-01", is_return=0)
			insert("Purchase Invoice Item", f"{line}-{suffix}", parent=invoice, parenttype="Purchase Invoice",
				parentfield="items", item_name="Synthetischer Artikel", expense_account=account, cost_center=cost_center, idx=1)

		access = accounting_evidence.AccountingAccess("Administrator", company, center, True)
		self.assertEqual(accounting_evidence.supplier(access, merchant)["match"]["name"], supplier_id)
		self.assertIn(account, {row["account"] for row in accounting_evidence.allowed_accounts(access)["accounts"]})
		history = accounting_evidence.prior_receipts(access, merchant)
		self.assertEqual([row["receipt"] for row in history["positions"]], [correct])
		verified = accounting_evidence.verify(access, merchant, [{"account": account, "positions": [f"correct-{suffix}"]}])
		self.assertEqual(verified["candidates"][0]["sources"][0]["receipt"], correct)
		self.assertTrue(verified["candidates"][0]["sources"][0]["same_object"])
		self.assertFalse(verified["questions"])
		for foreign in ("foreign", "foreign-object"):
			with self.assertRaises(frappe.ValidationError):
				accounting_evidence.verify(access, merchant, [{"account": account, "positions": [f"{foreign}-{suffix}"]}])
		self.assertFalse(accounting_evidence.prior_receipts(
			accounting_evidence.AccountingAccess("Administrator", None, None), merchant,
		)["positions"])

		upload = self.upload(self.fixture(), context={"kostenstelle": center})
		inventory = {"bons": [{"ausschnitte": [[1, 0, 0, 1000, 1000]]}], "leere_seiten": []}
		with (
			self.scope(upload),
			patch.object(receipt_evidence, "_access", return_value=access),
			patch.object(batch.pilot, "review_context", return_value={"fragen": []}),
		):
			self.submit(batch.next_step()["task"], inventory)
			completed = self.submit(batch.next_step()["task"], self.raw_analysis(18) | {"haendler": merchant},
				shortlist=[{"account": account, "positions": [f"correct-{suffix}"]}])
			self.assertEqual(completed["status"], "Done")
		record = json.loads(frappe.get_doc(batch.JOB, upload).results)[0]
		proposal = record["proposal"]
		stored = read_doc(batch.pilot.PROPOSAL, proposal).extracted_data
		self.assertNotIn(correct, stored)
		self.assertNotIn(supplier_id, stored)
		full = bulk_extraction.get_vorschlag_full(proposal)
		self.assertEqual(full["data"]["fields"]["lieferant"], supplier_id)
		detail = full["receipt_batch"]
		self.assertEqual(detail["revisions"][0]["fields"]["lieferant"], supplier_id)
		self.assertEqual(detail["account_comparison"]["candidates"][0]["sources"][0]["receipt"], correct)
		self.assertFalse(detail["comparison_stale"])

		role = frappe.get_doc({"doctype": "Role", "role_name": f"Bon Leser {suffix}"}).insert()
		for doctype in (batch.pilot.PROPOSAL, batch.UPLOAD, "Account"):
			frappe.get_doc({
				"doctype": "Custom DocPerm", "parent": doctype, "role": role.name, "permlevel": 0, "read": 1,
			}).insert()
			frappe.clear_cache(doctype=doctype)
			self.addCleanup(frappe.clear_cache, doctype=doctype)
		reader = frappe.get_doc({
			"doctype": "User", "email": f"{suffix}@bon-test.invalid", "first_name": "Bon Leser",
			"send_welcome_email": 0, "user_type": "System User", "roles": [{"role": role.name}],
		}).insert()
		try:
			frappe.set_user(reader.name)
			self.assertTrue(frappe.has_permission("Account", "read", doc=account))
			self.assertFalse(frappe.has_permission("Purchase Invoice", "read", doc=correct))
			self.assertFalse(frappe.has_permission("Supplier", "read", doc=supplier_id))
			restricted = bulk_extraction.get_vorschlag_full(proposal)
			self.assertNotIn(correct, json.dumps(restricted, default=str))
			self.assertNotIn(supplier_id, json.dumps(restricted, default=str))
			self.assertEqual(restricted["data"]["llm_lieferant"], merchant)
			self.assertEqual(restricted["receipt_batch"]["account_comparison"]["candidates"], [])
			self.assertNotIn(correct, read_doc(batch.pilot.PROPOSAL, proposal).extracted_data)
			self.assertNotIn(supplier_id, read_doc(batch.pilot.PROPOSAL, proposal).extracted_data)
			with self.assertRaises(frappe.PermissionError):
				read_doc(batch.JOB, upload)
		finally:
			frappe.set_user("Administrator")

		batch.pilot.update_context(proposal, {"kostenstelle": "Andere Kostenstelle"})
		history = bulk_extraction.get_vorschlag_full(proposal)["receipt_batch"]
		self.assertTrue(history["comparison_stale"])
		self.assertIsNone(history["account_comparison"])
		self.assertEqual(history["revisions"][0]["account_comparison"]["candidates"][0]["sources"][0]["receipt"], correct)
		self.assertTrue(history["revisions"][0]["comparison_stale"])
		new_job = batch.revise(proposal, str(uuid.uuid4()), history["source"], "Neue Kostenstelle abgleichen")
		self.assertNotEqual(new_job["name"], upload)

	def test_evidence_retry_replaces_ocr_merchant_and_rejects_old_attempt(self):
		upload = self.upload(self.fixture())
		inventory = {"bons": [{"ausschnitte": [[1, 0, 0, 1000, 1000]]}], "leere_seiten": []}
		with self.scope(upload):
			self.submit(batch.next_step()["task"], inventory)
			batch.next_step()
			old = receipt_evidence.start(1, "Händler zuerst unsicher")["attempt"]
			self.assertEqual(batch.submit_step(1, failed=True, evidence_attempt=old)["status"], "AnalysisError")
		with self.scope(upload):
			batch.next_step()
			current = receipt_evidence.start(1, "Korrigierter Händler")["attempt"]
			self.assertNotEqual(old, current)
			with self.assertRaises(frappe.PermissionError):
				receipt_evidence.tools(1, "tools/list", {}, old)
			with self.assertRaises(frappe.PermissionError):
				batch.submit_step(1, evidence_attempt=old)
			with self.assertRaises(frappe.PermissionError):
				batch.submit_step(1, failed=True, evidence_attempt=old)
			self.assertEqual(frappe.get_doc(batch.JOB, upload).evidence_merchant, "Korrigierter Händler")
			self.assertEqual(frappe.get_doc(batch.JOB, upload).status, "Running")
			task = batch.next_step()["task"]
			result = self.submit(task, self.raw_analysis(18) | {"haendler": "Korrigierter Händler"})
			self.assertEqual(result["status"], "Questions")


	def test_issue_links_from_confirmed_assignment_only(self):
		issue = str(uuid.uuid4())
		flags = {"hv_receipt_paperclip_web_url": "https://paperclip.invalid", "hv_receipt_paperclip_company_prefix": "HVTEST"}
		with patch.dict(frappe.conf, flags):
			self.assertIsNone(batch._issue_link(None))
			self.assertEqual(batch._issue_link(issue), f"https://paperclip.invalid/HVTEST/issues/{issue}")
		with patch.dict(frappe.conf, flags | {"hv_receipt_paperclip_web_url": "https://paperclip.invalid/?token=private"}):
			self.assertIsNone(batch._issue_link(issue))

	def test_webhook_reuses_body_idempotency_and_signature_after_timeout(self):
		upload = self.upload(self.fixture())
		job = frappe.get_doc(batch.JOB, upload)
		issue = str(uuid.uuid4())
		response = SimpleNamespace(status_code=202, json=lambda: {"status": "issue_created", "linkedIssueId": issue})
		with patch.object(batch.requests, "post", side_effect=[batch.requests.Timeout, response]) as post:
			with self.assertRaises(batch.requests.Timeout):
				batch._webhook(job)
			self.assertEqual(batch._webhook(job), issue)
		self.assertEqual(post.call_args_list[0], post.call_args_list[1])
		payload = post.call_args.kwargs["data"]
		headers = post.call_args.kwargs["headers"]
		self.assertEqual(headers["Idempotency-Key"], upload)
		self.assertEqual(json.loads(payload), {"upload_id": upload, "job_id": upload})
		self.assertEqual(headers["X-Hub-Signature-256"],
			"sha256=" + hmac.new(self.flags["hv_receipt_webhook_secret"].encode(), payload, hashlib.sha256).hexdigest())

	def test_run_scope_uses_own_paperclip_run_and_assigned_issue(self):
		agent, company, run, issue = (str(uuid.uuid4()) for _ in range(4))
		claims = {"sub": agent, "company_id": company, "run_id": run}
		token = "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"
		identity = {"id": agent, "companyId": company}
		record = {"agentId": agent, "companyId": company, "status": "running", "contextSnapshot": {"issueId": issue}}
		with (
			patch.dict(frappe.conf, {"hv_receipt_paperclip_agent": agent}),
			patch.object(batch, "_paperclip_get", side_effect=[identity, record]) as api,
		):
			self.assertEqual(batch._run_scope(token), (issue, run))
			self.assertEqual(api.call_args_list[1].args, (f"/api/heartbeat-runs/{run}", token))
		with (
			patch.dict(frappe.conf, {"hv_receipt_paperclip_agent": agent}),
			patch.object(batch, "_paperclip_get", side_effect=[identity, record | {"agentId": str(uuid.uuid4())}]),
			self.assertRaises(frappe.PermissionError),
		):
			batch._run_scope(token)
