import json

import frappe
from frappe.tests import IntegrationTestCase
from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import set_run_variables

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as api


class TestMailMergeDrafts(IntegrationTestCase):
	"""Das Modell bereitet einen Entwurf vor, der Nutzer korrigiert ihn, erst dann entstehen PDFs."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		if not frappe.db.exists("Serienbrief Kategorie", "Entwurfstest"):
			frappe.get_doc({"doctype": "Serienbrief Kategorie", "title": "Entwurfstest"}).insert(
				ignore_permissions=True
			)
		self.template = frappe.get_doc(
			{
				"doctype": "Serienbrief Vorlage",
				"title": f"Mahnung {self.suffix}",
				"kategorie": "Entwurfstest",
				"haupt_verteil_objekt": "User",
				"content_type": "Textbaustein (Rich Text)",
				"content": "<p>Offener Betrag alt: {{ betrag }} Euro</p>",
				"variables": [
					{"variable": "betrag", "variable_type": "Zahl", "label": "Betrag"},
					{"variable": "hinweis", "variable_type": "Text", "label": "Hinweis", "optional": 1},
				],
			}
		).insert(ignore_permissions=True)
		self.old_version = frappe.get_all(
			"Serienbrief Vorlagenversion", filters={"vorlage": self.template.name}, pluck="name"
		)[0]

	def _ok(self, result):
		self.assertTrue(result["ok"], result.get("error"))
		return result["data"]

	def _revision(self):
		return self._ok(api.get_template(self.template.name))["revision"]

	def _draft(self, **values):
		return self._ok(
			api.save_draft(
				self.template.name,
				["Administrator"],
				revision=self._revision(),
				values=values or None,
				letter_date="2030-01-15",
				title=f"Entwurf {self.suffix}",
			)
		)

	def test_save_draft_stores_inputs_without_rendering_and_reports_missing_inputs(self):
		state = self._draft(hinweis="Bitte zahlen")

		run = frappe.get_doc("Serienbrief Durchlauf", state["draft"])
		self.assertEqual(run.status, "Entwurf")
		self.assertTrue(run.ohne_auto_render)
		self.assertEqual(state["rendered"], "nicht_gerendert")
		self.assertEqual(state["documents"], 0)
		self.assertEqual(state["values"], {"hinweis": "Bitte zahlen"})
		self.assertEqual(state["missing_inputs"], [{"recipient": "Administrator", "fields": ["betrag"]}])
		self.assertTrue(
			frappe.db.exists(
				"Comment", {"reference_doctype": "Serienbrief Durchlauf", "reference_name": run.name}
			)
		)

	def test_update_requires_the_last_seen_fingerprint(self):
		state = self._draft(betrag=120)

		stale = api.update_draft(state["draft"], "veraltet", values={"betrag": 99})
		self.assertFalse(stale["ok"])
		self.assertEqual(stale["error"]["code"], "DRAFT_CHANGED")
		self.assertEqual(stale["error"]["current"]["values"], {"betrag": 120})

		updated = self._ok(
			api.update_draft(state["draft"], state["fingerprint"], values={"betrag": 102, "hinweis": "x"})
		)
		self.assertEqual(updated["values"], {"betrag": 102, "hinweis": "x"})
		removed = self._ok(api.update_draft(state["draft"], updated["fingerprint"], values={"hinweis": None}))
		self.assertEqual(removed["values"], {"betrag": 102})

	def test_user_correction_is_tracked_and_blocks_blind_overwrite(self):
		state = self._draft(betrag=120)

		# So korrigiert der Durchlauf-Viewer; Werte kommen dort als Text.
		set_run_variables(state["draft"], variables={"betrag": "102"})

		versions = frappe.get_all(
			"Version", filters={"ref_doctype": "Serienbrief Durchlauf", "docname": state["draft"]}, pluck="data"
		)
		self.assertTrue(any("variablen_werte" in data for data in versions))
		result = api.update_draft(state["draft"], state["fingerprint"], values={"betrag": 150})
		self.assertEqual(result["error"]["code"], "DRAFT_CHANGED")
		self.assertEqual(result["error"]["current"]["values"], {"betrag": 102})

	def test_prepare_and_execute_render_into_the_same_draft(self):
		state = self._draft(betrag=120)
		set_run_variables(state["draft"], variables={"betrag": "102"})

		prepared = self._ok(api.prepare(draft=state["draft"]))
		self.assertTrue(prepared["ready"], prepared)
		self.assertIn("102", prepared["previews"][0]["text"])
		executed = self._ok(api.execute(prepared["preparation_token"]))

		self.assertEqual(executed["run"], state["draft"])
		self.assertEqual(len(executed["documents"]), 1)
		self.assertEqual(self._ok(api.get_draft(state["draft"]))["rendered"], "aktuell")
		self.assertTrue(self._ok(api.execute(prepared["preparation_token"]))["reused"])

		current = self._ok(api.get_draft(state["draft"]))
		self._ok(api.update_draft(state["draft"], current["fingerprint"], values={"betrag": 1}))
		self.assertEqual(self._ok(api.get_draft(state["draft"]))["rendered"], "veraltet")

	def test_execute_refuses_a_draft_changed_after_preview(self):
		state = self._draft(betrag=120)
		prepared = self._ok(api.prepare(draft=state["draft"]))
		set_run_variables(state["draft"], variables={"betrag": "5"})

		result = api.execute(prepared["preparation_token"])
		self.assertEqual(result["error"]["code"], "DRAFT_CHANGED")
		self.assertEqual(frappe.db.count("Serienbrief Dokument", {"durchlauf": state["draft"]}), 0)

	def test_execute_never_replaces_submitted_documents(self):
		state = self._draft(betrag=120)
		prepared = self._ok(api.prepare(draft=state["draft"]))
		self._ok(api.execute(prepared["preparation_token"]))
		frappe.get_doc(
			"Serienbrief Dokument", frappe.get_all("Serienbrief Dokument", {"durchlauf": state["draft"]}, pluck="name")[0]
		).submit()
		# execute ist eine eigene Transaktionsgrenze und rollt bei Fehlern zurueck.
		frappe.db.commit()

		prepared = self._ok(api.prepare(draft=state["draft"]))
		result = api.execute(prepared["preparation_token"])
		self.assertEqual(result["error"]["code"], "DRAFT_LOCKED")
		self.assertEqual(
			frappe.db.count("Serienbrief Dokument", {"durchlauf": state["draft"], "docstatus": 1}), 1
		)

	def test_draft_can_use_an_older_template_version(self):
		self.template.reload()
		self.template.content = "<p>Offener Betrag neu: {{ betrag }} Euro</p>"
		self.template.flags.force_template_version = True
		self.template.save(ignore_permissions=True)

		state = self._ok(
			api.save_draft(
				self.template.name,
				["Administrator"],
				values={"betrag": 7},
				vorlagenversion=self.old_version,
			)
		)
		self.assertEqual(state["vorlagenversion"], self.old_version)
		prepared = self._ok(api.prepare(draft=state["draft"]))
		self.assertIn("alt", prepared["previews"][0]["text"])
		self.assertNotIn("neu", prepared["previews"][0]["text"])

	def test_prepare_with_draft_takes_no_other_inputs(self):
		state = self._draft(betrag=1)
		result = api.prepare(draft=state["draft"], values={"betrag": 2})
		self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

	def test_draft_values_reject_markup_like_previews(self):
		result = api.save_draft(
			self.template.name,
			["Administrator"],
			revision=self._revision(),
			values={"betrag": 1, "hinweis": "<b>fett</b>"},
		)
		self.assertEqual(result["error"]["code"], "INVALID_INPUT")
		self.assertEqual(json.dumps(result["error"]["issues"][0]["field"]), '"hinweis"')
