import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.mietvertrag import mietvertrag


class TestMietvertrag(unittest.TestCase):
	def test_sanitize_name_part_removes_control_separators(self):
		value = mietvertrag._sanitize_name_part("G1\t| VH\t| EG links")

		self.assertNotIn("\t", value)
		self.assertEqual(value, "G1 / VH / EG links")

	def test_hauptmieter_suffix_is_url_friendly(self):
		with patch.object(mietvertrag, "get_hauptmieter_last_names", return_value=["Bega\tnovic|Test"]):
			value = mietvertrag._with_hauptmieter_suffix("G1 | VH | EG links | ab: 2008-03-01", [])

		self.assertNotIn("\t", value)
		self.assertEqual(value, "G1 | VH | EG links | ab: 2008-03-01 - Bega novic/Test")

	def test_compute_status_value_handles_future_running_and_past_contracts(self):
		with patch.object(mietvertrag, "today", return_value="2026-06-10"):
			self.assertEqual(mietvertrag._compute_status_value("2026-07-01", None), "Zukunft")
			self.assertEqual(mietvertrag._compute_status_value("2026-01-01", None), "Läuft")
			self.assertEqual(mietvertrag._compute_status_value("2025-01-01", "2026-06-09"), "Vergangenheit")
			self.assertEqual(mietvertrag._compute_status_value(None, "kein-datum"), "Läuft")

	def test_build_mietvertrag_base_name_normalizes_wohnung_and_immobilie_parts(self):
		def get_value(doctype, name, fields, as_dict=False):
			if doctype == "Wohnung":
				return frappe._dict({
					"immobilie": "IMM-1",
					"gebaeudeteil": "Vorderhaus",
					"name__lage_in_der_immobilie": "Vorderhaus, EG links",
				})
			if doctype == "Immobilie":
				return frappe._dict({
					"objekt": "Haus A",
					"adresse_titel": "",
					"name": "IMM-1",
					"immobilien_id": 17,
				})
			return None

		doc = frappe._dict(wohnung="WHG-1", von="2026-03-01")
		with patch("frappe.db.get_value", side_effect=get_value):
			value = mietvertrag._build_mietvertrag_base_name(doc)

		self.assertEqual(value, "A17 | VH | EG links | ab: 2026-03-01")

	def test_unique_docname_keeps_current_name_and_adds_suffix_on_collision(self):
		def exists(doctype, name, cache=False):
			return name in {"Basis", "Basis (2)"}

		def get_value(doctype, name, fieldname, cache=False):
			return "CURRENT" if name == "Basis" else None

		with patch("frappe.db.exists", side_effect=exists), \
			 patch("frappe.db.get_value", side_effect=get_value):
			self.assertEqual(
				mietvertrag._unique_docname("Mietvertrag", "Basis", current_name="CURRENT"),
				"CURRENT",
			)
			self.assertEqual(mietvertrag._unique_docname("Mietvertrag", "Basis"), "Basis (3)")

	def test_sort_staffel_table_orders_valid_dates_and_moves_empty_dates_last(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"miete": [
				{"von": None, "miete": 999},
				{"von": "2026-05-01", "miete": 650},
				{"von": "2026-01-01", "miete": 600},
			],
		})

		doc._sort_staffel_table_by_von("miete")

		self.assertEqual([row.von for row in doc.miete], ["2026-01-01", "2026-05-01", None])
		self.assertEqual([row.idx for row in doc.miete], [1, 2, 3])

	def test_bruttomiete_uses_last_applicable_staffels_at_bounded_stichtag(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"miete": [
				{"von": "2026-01-01", "miete": 500},
				{"von": "2026-07-01", "miete": 700},
			],
			"betriebskosten": [{"von": "2026-01-01", "miete": 120}],
			"heizkosten": [
				{"von": "2025-01-01", "miete": 80},
				{"von": "2026-06-01", "miete": 90},
			],
			"untermietzuschlag": [{"von": "2026-01-01", "miete": 25}],
		})

		with patch.object(mietvertrag, "today", return_value="2026-06-10"):
			self.assertEqual(doc.aktuelle_nettokaltmiete, 500.0)
			self.assertEqual(doc.aktuelle_heizkosten, 90.0)
			self.assertEqual(doc.bruttomiete, 735.0)

	def test_validate_rejects_bank_account_contact_that_is_not_contract_partner(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"mieter": [{"mieter": "CONTACT-ALLOWED", "rolle": "Hauptmieter"}],
			"kontoverbindungen": [{"kontakt": "CONTACT-OTHER"}],
		})

		with patch.object(doc, "is_new", return_value=False), \
			 patch.object(mietvertrag, "_get_wohnung_immobilie", return_value="IMM-1"), \
			 self.assertRaisesRegex(frappe.ValidationError, "kein Vertragspartner"):
			doc.validate()

	def test_validate_rejects_gesamter_zeitraum_staffel_that_spans_multiple_months(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-15",
			"bis": "2026-02-14",
			"miete": [{"von": "2026-01-15", "miete": 500, "art": "Gesamter Zeitraum"}],
		})

		with patch.object(doc, "is_new", return_value=False), \
			 patch.object(mietvertrag, "_get_wohnung_immobilie", return_value="IMM-1"), \
			 self.assertRaisesRegex(frappe.ValidationError, "muss innerhalb eines Monats liegen"):
			doc.validate()

	def test_validate_allows_gesamter_zeitraum_staffel_within_single_month(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"bis": "2026-01-31",
			"miete": [{"von": "2026-01-01", "miete": 500, "art": "Gesamter Zeitraum"}],
		})

		with patch.object(doc, "is_new", return_value=False), \
			 patch.object(mietvertrag, "_get_wohnung_immobilie", return_value="IMM-1"):
			doc.validate()

		self.assertEqual(doc.status, mietvertrag._compute_status_value("2026-01-01", "2026-01-31"))
		self.assertEqual(doc.immobilie, "IMM-1")

	def test_validate_creation_via_process_rejects_wrong_process_type(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"mieterwechsel": "PI-1",
		})
		process = frappe._dict(name="PI-1", prozess_typ="reparatur", payload_json="{}")

		with patch("frappe.db.exists", return_value=True), \
			 patch("frappe.db.get_value", return_value=process), \
			 self.assertRaisesRegex(frappe.ValidationError, "kein Mieterwechsel-Prozess"):
			doc._validate_creation_via_process()

	def test_validate_creation_via_process_rejects_payload_mismatch(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"name": "MV-NEW",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"mieterwechsel": "PI-1",
		})
		process = frappe._dict(
			name="PI-1",
			prozess_typ="mieterwechsel",
			payload_json='{"wohnung": "WHG-2", "einzugsdatum": "2026-01-01"}',
		)

		with patch("frappe.db.exists", return_value=True), \
			 patch("frappe.db.get_value", return_value=process), \
			 self.assertRaisesRegex(frappe.ValidationError, "dieselbe Wohnung"):
			doc._validate_creation_via_process()

	def test_paperless_tag_name_uses_wohnung_context_and_contract_start(self):
		value = mietvertrag._build_mietvertrag_tag_name(
			"IMM-1",
			"Vorderhaus, EG links",
			"WHG-1",
			"2026-01-01",
			"MV-1",
		)

		self.assertIn("Mietvertrag 2026-01-01", value)
		self.assertIn("EG links", value)

	def test_onload_persists_changed_status_without_touching_modified(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"name": "MV-STATUS",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"bis": "2026-06-09",
			"status": "Läuft",
		})

		with patch.object(doc, "is_new", return_value=False), \
			 patch.object(mietvertrag, "today", return_value="2026-06-10"), \
			 patch.object(doc, "db_set") as db_set:
			doc.onload()

		db_set.assert_called_once_with("status", "Vergangenheit", update_modified=False)
		self.assertEqual(doc.status, "Vergangenheit")

	def test_on_update_guards_against_recursive_name_sync(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"name": "MV-RECURSIVE",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
		})
		doc.flags.hv_syncing_names = True

		with patch.object(doc, "_sync_customer_name") as sync_customer, \
			 patch.object(doc, "_sync_mietvertrag_name") as sync_contract:
			doc.on_update()

		sync_customer.assert_not_called()
		sync_contract.assert_not_called()

	def test_sync_customer_name_creates_missing_linked_customer_and_updates_doc(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"name": "MV-CUSTOMER",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"mieter": [{"mieter": "CONTACT-1", "rolle": "Hauptmieter"}],
		})

		with patch.object(mietvertrag, "get_hauptmieter_last_names", return_value=["Mustermann"]), \
			 patch.object(mietvertrag, "get_hauptmieter_display_name", return_value="Mustermann Max"), \
			 patch("frappe.db.exists", return_value=False), \
			 patch("hausverwaltung.hausverwaltung.utils.customer.get_or_create_customer", return_value="Mustermann - WHG-1") as get_or_create, \
			 patch.object(doc, "db_set") as db_set:
			result = doc._sync_customer_name()

		get_or_create.assert_called_once_with("Mustermann - WHG-1", customer_name="Mustermann Max")
		db_set.assert_called_once_with("kunde", "Mustermann - WHG-1", update_modified=False)
		self.assertEqual(result, "Mustermann - WHG-1")
		self.assertEqual(doc.kunde, "Mustermann - WHG-1")

	def test_sync_customer_name_renames_existing_customer_and_updates_display_name(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"name": "MV-CUSTOMER",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"kunde": "Alter Kunde",
			"mieter": [{"mieter": "CONTACT-1", "rolle": "Hauptmieter"}],
		})

		def exists(doctype, name, cache=False):
			return doctype == "Customer" and name == "Alter Kunde"

		def get_value(doctype, name, fieldname, cache=False):
			if doctype == "Customer" and name == "Neuer Name - WHG-1" and fieldname == "name":
				return None
			if doctype == "Customer" and name == "Neuer Name - WHG-1" and fieldname == "customer_name":
				return "Alter Anzeigename"
			return None

		with patch.object(mietvertrag, "get_hauptmieter_last_names", return_value=["Neuer Name"]), \
			 patch.object(mietvertrag, "get_hauptmieter_display_name", return_value="Neuer Name Nora"), \
			 patch("frappe.db.exists", side_effect=exists), \
			 patch("frappe.db.get_value", side_effect=get_value), \
			 patch.object(mietvertrag, "rename_doc", return_value="Neuer Name - WHG-1") as rename, \
			 patch("frappe.db.set_value") as set_value:
			result = doc._sync_customer_name()

		rename.assert_called_once_with(
			"Customer",
			"Alter Kunde",
			"Neuer Name - WHG-1",
			force=True,
			merge=False,
			show_alert=False,
			ignore_permissions=True,
		)
		set_value.assert_called_once_with(
			"Customer",
			"Neuer Name - WHG-1",
			"customer_name",
			"Neuer Name Nora",
			update_modified=False,
		)
		self.assertEqual(result, "Neuer Name - WHG-1")
		self.assertEqual(doc.kunde, "Neuer Name - WHG-1")

	def test_sync_mietvertrag_name_renames_contract_to_expected_target(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"name": "Alter MV",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
		})

		with patch.object(mietvertrag, "_build_mietvertrag_base_name", return_value="A1 | VH | EG | ab: 2026-01-01"), \
			 patch.object(mietvertrag, "get_hauptmieter_last_names", return_value=["Muster"]), \
			 patch.object(mietvertrag, "_unique_docname", return_value="A1 | VH | EG | ab: 2026-01-01 - Muster"), \
			 patch.object(mietvertrag, "rename_doc", return_value="A1 | VH | EG | ab: 2026-01-01 - Muster") as rename:
			result = doc._sync_mietvertrag_name()

		rename.assert_called_once_with(
			"Mietvertrag",
			"Alter MV",
			"A1 | VH | EG | ab: 2026-01-01 - Muster",
			force=True,
			merge=False,
			show_alert=False,
			ignore_permissions=True,
		)
		self.assertEqual(result, "A1 | VH | EG | ab: 2026-01-01 - Muster")
		self.assertEqual(doc.name, "A1 | VH | EG | ab: 2026-01-01 - Muster")

	def test_vorauszahlung_slots_filters_by_date_sorts_by_idx_and_pads_missing_slots(self):
		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": "WHG-1",
			"von": "2026-01-01",
			"festbetraege": [
				{"idx": 3, "betrag": 30, "gueltig_von": "2026-01-01", "gueltig_bis": "2026-12-31"},
				{"idx": 1, "betrag": 10, "gueltig_von": "2026-01-01", "gueltig_bis": "2026-12-31"},
				{"idx": 2, "betrag": 20, "gueltig_von": "2026-07-01", "gueltig_bis": None},
				{"idx": 4, "betrag": 40, "gueltig_von": "2025-01-01", "gueltig_bis": "2025-12-31"},
			],
		})

		with patch.object(mietvertrag, "today", return_value="2026-06-10"):
			slots = doc.vorauszahlung_slots

		self.assertIsNone(slots[0])
		self.assertEqual(slots[1], "10.00 €")
		self.assertEqual(slots[2], "30.00 €")
		self.assertEqual(slots[3], "")
		self.assertEqual(slots[4], "")

	def test_update_statuses_for_list_updates_status_and_immobilie_only_when_needed(self):
		rows = [
			frappe._dict(name="MV-1", wohnung="WHG-1", von="2026-01-01", bis=None, status="Zukunft", immobilie=None),
			frappe._dict(name="MV-2", wohnung="WHG-2", von="2026-07-01", bis=None, status="Zukunft", immobilie="IMM-2"),
			frappe._dict(name="MV-3", wohnung="WHG-3", von="2025-01-01", bis="2026-01-31", status="Vergangenheit", immobilie="IMM-3"),
		]

		def get_value(doctype, name, fieldname):
			if doctype == "Wohnung":
				return {"WHG-1": "IMM-1", "WHG-2": "IMM-2", "WHG-3": "IMM-3"}[name]
			return None

		with patch("frappe.db.has_column", return_value=True), \
			 patch("frappe.get_all", return_value=rows), \
			 patch("frappe.db.get_value", side_effect=get_value), \
			 patch("frappe.db.set_value") as set_value, \
			 patch.object(mietvertrag, "today", return_value="2026-06-10"):
			result = mietvertrag.update_statuses_for_list()

		self.assertEqual(result, {"updated": 1})
		set_value.assert_called_once_with(
			"Mietvertrag",
			"MV-1",
			{"status": "Läuft", "immobilie": "IMM-1"},
			update_modified=False,
		)

	def test_sync_names_for_contact_updates_all_linked_contracts_and_logs_per_row_errors(self):
		contact = frappe._dict(name="CONTACT-1")
		rows = [frappe._dict(parent="MV-1"), frappe._dict(parent="MV-MISSING"), frappe._dict(parent="MV-FAIL")]
		mv_ok = frappe._dict()
		mv_ok._sync_customer_name = unittest.mock.Mock()
		mv_ok._sync_mietvertrag_name = unittest.mock.Mock()
		mv_fail = frappe._dict()
		mv_fail._sync_customer_name = unittest.mock.Mock(side_effect=Exception("rename failed"))
		mv_fail._sync_mietvertrag_name = unittest.mock.Mock()

		def exists(doctype, name):
			return name in {"MV-1", "MV-FAIL"}

		def get_doc(doctype, name):
			return {"MV-1": mv_ok, "MV-FAIL": mv_fail}[name]

		with patch("frappe.get_all", return_value=rows), \
			 patch("frappe.db.exists", side_effect=exists), \
			 patch("frappe.get_doc", side_effect=get_doc), \
			 patch("frappe.log_error") as log_error:
			mietvertrag.sync_names_for_contact(contact)

		mv_ok._sync_customer_name.assert_called_once()
		mv_ok._sync_mietvertrag_name.assert_called_once()
		mv_fail._sync_customer_name.assert_called_once()
		mv_fail._sync_mietvertrag_name.assert_not_called()
		log_error.assert_called_once()

	def test_get_mietvertrag_paperless_link_builds_query_and_ensures_tags(self):
		config = frappe._dict(url="http://internal-paperless", token="secret")
		conf = {
			"paperless_ngx_public_url": "https://paperless.example.test/",
			"paperless_ngx_url": "http://internal-paperless",
		}
		mv = frappe._dict(wohnung="WHG-1", von="2026-01-01", name="MV-1")
		wohnung = frappe._dict(
			paperless_tag="",
			immobilie="IMM-1",
			name__lage_in_der_immobilie="Vorderhaus, EG links",
			name="WHG-1",
		)

		def get_value(doctype, name, fields, as_dict=False):
			if doctype == "Mietvertrag":
				return mv
			if doctype == "Wohnung":
				return wohnung
			return None

		ensured_tags = []

		def ensure_tag(config_arg, tag_name, parent_tag_id=None):
			ensured_tags.append((tag_name, parent_tag_id))
			return 99 if tag_name == "Mietvertrag" else 17

		with patch.object(frappe, "conf", conf), \
			 patch.object(mietvertrag.PaperlessConfig, "from_conf", return_value=config), \
			 patch("frappe.db.get_value", side_effect=get_value), \
			 patch("frappe.db.has_column", return_value=True), \
			 patch.object(mietvertrag, "_ensure_paperless_tag", side_effect=ensure_tag):
			url = mietvertrag.get_mietvertrag_paperless_link("MV-1")

		self.assertTrue(url.startswith("https://paperless.example.test/documents/?"))
		self.assertIn("query=", url)
		self.assertIn(("Mietvertrag", None), ensured_tags)
		self.assertTrue(any(tag.endswith("Mietvertrag 2026-01-01") and parent == 99 for tag, parent in ensured_tags))


class TestMietvertragDatabaseIntegration(unittest.TestCase):
	def test_real_insert_sets_status_customer_and_sorts_staffels(self):
		suffix = frappe.generate_hash(length=8)
		wohnung = frappe.get_doc({
			"doctype": "Wohnung",
			"name__lage_in_der_immobilie": f"HV Mietvertrag Test {suffix}",
			"gebaeudeteil": "VH",
		}).insert(ignore_permissions=True)
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": "Max",
			"last_name": f"Miettest{suffix}",
		}).insert(ignore_permissions=True)

		doc = frappe.get_doc({
			"doctype": "Mietvertrag",
			"wohnung": wohnung.name,
			"von": "2026-01-01",
			"mieter": [{"mieter": contact.name, "rolle": "Hauptmieter"}],
			"miete": [
				{"von": "2026-05-01", "miete": 650},
				{"von": "2026-01-01", "miete": 600},
			],
		}).insert(ignore_permissions=True)

		self.assertTrue(doc.kunde)
		self.assertTrue(frappe.db.exists("Customer", doc.kunde))
		self.assertIn(f"Miettest{suffix}", doc.kunde)
		self.assertIn(wohnung.name, doc.kunde)
		self.assertEqual([row.von for row in doc.miete], ["2026-01-01", "2026-05-01"])
		self.assertEqual(doc.status, mietvertrag._compute_status_value("2026-01-01", None))
