import copy
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import migrate_miete_teilmonate as migration
from hausverwaltung.hausverwaltung.utils.mietberechnung import calculate_monthly_rent


def rent(start, amount, kind="Monatlich", name=None):
	return {"name": name or f"RENT-{start}-{kind}", "von": start, "miete": amount, "art": kind}


def contract(start="2026-01-01", end="2026-12-31", name="MV-TEST"):
	return {"name": name, "von": start, "bis": end, "docstatus": 0, "owner": "Administrator"}


class TestMigrateMieteTeilmonate(unittest.TestCase):
	def test_fixed_section_ends_at_next_monthly_row_and_keeps_full_amount(self):
		rows = [rent("2026-01-16", 620), rent("2026-01-01", 300, migration.FIXED)]
		before = copy.deepcopy(rows)
		plan = migration.plan_contract(contract(), rows)
		self.assertEqual(
			plan,
			[
				{
					"source_name": rows[1]["name"],
					"von": date(2026, 1, 1),
					"bis": date(2026, 1, 15),
					"betrag": Decimal("300"),
				}
			],
		)
		self.assertEqual(rows, before)

	def test_last_fixed_section_uses_contract_end(self):
		plan = migration.plan_contract(
			contract(end="2026-01-31"), [rent("2026-01-01", 620), rent("2026-01-16", 310, migration.FIXED)]
		)
		self.assertEqual(plan[0]["bis"], date(2026, 1, 31))
		self.assertEqual(plan[0]["betrag"], Decimal(310))

	def test_open_contract_last_fixed_section_ends_at_month_end(self):
		plan = migration.plan_contract(contract(end=None), [rent("2026-01-16", 300, migration.FIXED)])
		self.assertEqual(plan[0]["bis"], date(2026, 1, 31))

	def test_zero_fixed_amount_is_preserved(self):
		plan = migration.plan_contract(contract(end=None), [rent("2026-01-16", 0, migration.FIXED)])
		self.assertEqual(plan[0]["betrag"], Decimal(0))

	def test_monthly_only_contract_is_not_changed(self):
		self.assertEqual(migration.plan_contract(contract(), [rent("2026-01-01", 620)]), [])

	def test_duplicate_start_of_different_types_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "nicht eindeutig"):
			migration.plan_contract(
				contract(), [rent("2026-01-01", 620), rent("2026-01-01", 300, migration.FIXED)]
			)

	def test_fixed_section_crossing_month_boundary_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Kalendermonat"):
			migration.plan_contract(contract(), [rent("2026-01-16", 300, migration.FIXED)])

	def test_next_row_after_contract_end_is_rejected_instead_of_clipped(self):
		with self.assertRaisesRegex(frappe.ValidationError, "außerhalb"):
			migration.plan_contract(
				contract(end="2026-01-20"),
				[rent("2026-01-16", 300, migration.FIXED), rent("2026-01-25", 620)],
			)

	def test_fixed_section_before_contract_start_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "außerhalb"):
			migration.plan_contract(
				contract(start="2026-01-16", end=None), [rent("2026-01-01", 300, migration.FIXED)]
			)

	def test_missing_contract_start_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Vertragsbeginn fehlt"):
			migration.plan_contract(
				contract(start=None, end=None), [rent("2026-01-16", 300, migration.FIXED)]
			)

	def test_reversed_contract_dates_are_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Vertragsende liegt vor"):
			migration.plan_contract(
				contract(start="2026-01-31", end="2026-01-01"), [rent("2026-01-16", 300, migration.FIXED)]
			)

	def test_missing_staffel_start_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Beginn einer Mietstaffel fehlt"):
			migration.plan_contract(contract(end=None), [rent(None, 300, migration.FIXED)])

	def test_invalid_amounts_are_rejected_without_rounding_or_defaulting(self):
		for amount in (None, "", -1, "12.345", "NaN", "Infinity", "kein Betrag"):
			with self.subTest(amount=amount), self.assertRaises(frappe.ValidationError):
				migration.plan_contract(contract(end=None), [rent("2026-01-16", amount, migration.FIXED)])

	def test_existing_fixed_or_automatic_rule_must_not_overlap(self):
		for mode in (migration.FIXED_RULE, migration.AUTOMATIC_RULE):
			with self.subTest(mode=mode), self.assertRaisesRegex(frappe.ValidationError, "überschneiden"):
				migration.plan_contract(
					contract(end=None),
					[rent("2026-01-16", 300, migration.FIXED)],
					[
						{
							"von": "2026-01-15",
							"bis": "2026-01-16",
							"berechnung": mode,
							"betrag": 20,
						}
					],
				)

	def test_exact_existing_rule_is_rejected_instead_of_silently_merged(self):
		with self.assertRaisesRegex(frappe.ValidationError, "überschneiden"):
			migration.plan_contract(
				contract(end=None),
				[rent("2026-01-16", 300, migration.FIXED)],
				[
					{
						"von": "2026-01-16",
						"bis": "2026-01-31",
						"berechnung": migration.FIXED_RULE,
						"betrag": 300,
					}
				],
			)

	def test_adjacent_existing_rule_is_allowed(self):
		plan = migration.plan_contract(
			contract(end=None),
			[rent("2026-01-01", 620), rent("2026-01-16", 300, migration.FIXED)],
			[
				{
					"von": "2026-01-01",
					"bis": "2026-01-15",
					"berechnung": migration.FIXED_RULE,
					"betrag": 20,
				}
			],
		)
		self.assertEqual(len(plan), 1)

	def test_existing_adjacent_rule_without_monthly_base_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "MV-TEST: .*reguläre Monatsmiete"):
			migration.plan_contract(
				contract(end=None),
				[rent("2026-01-16", 300, migration.FIXED)],
				[
					{
						"von": "2026-01-01",
						"bis": "2026-01-15",
						"berechnung": migration.FIXED_RULE,
						"betrag": 20,
					}
				],
			)

	def test_planned_configuration_rejects_invalid_existing_monthly_amount(self):
		with self.assertRaisesRegex(frappe.ValidationError, "MV-TEST: .*nicht negativer Betrag"):
			migration.plan_contract(
				contract(end=None),
				[rent("2026-01-01", -620), rent("2026-01-16", 300, migration.FIXED)],
			)

	def test_existing_rules_are_validated_before_conversion(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Ende .* vor Beginn"):
			migration.plan_contract(
				contract(end=None),
				[rent("2026-01-16", 300, migration.FIXED)],
				[
					{
						"von": "2026-01-10",
						"bis": "2026-01-09",
						"berechnung": migration.FIXED_RULE,
						"betrag": 20,
					}
				],
			)

	def test_unknown_staffel_type_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Unbekannte Berechnungsart"):
			migration.plan_contract(
				contract(end=None),
				[rent("2026-01-01", 620, "unbekannt"), rent("2026-01-16", 300, migration.FIXED)],
			)

	def test_zero_boundaries_preserve_current_and_future_months_for_mixed_sequences(self):
		cases = [
			(
				contract(),
				[rent("2026-01-01", 300, migration.FIXED), rent("2026-01-16", 620)],
				{"2026-01-01": 620, "2026-02-01": 620},
			),
			(
				contract(end="2026-01-31"),
				[rent("2026-01-01", 620), rent("2026-01-16", 310, migration.FIXED)],
				{"2026-01-01": 610, "2026-02-01": 0},
			),
			(
				contract(end=None),
				[rent("2026-01-01", 620), rent("2026-01-16", 310, migration.FIXED)],
				{"2026-01-01": 610, "2026-02-01": 0},
			),
			(
				contract(start="2026-01-16", end=None),
				[rent("2026-01-16", 0, migration.FIXED)],
				{"2026-01-01": 0, "2026-02-01": 0},
			),
			(
				contract(end=None),
				[rent("2026-01-01", 620), rent("2026-01-16", 310, migration.FIXED), rent("2026-02-01", 640)],
				{"2026-01-01": 610, "2026-02-01": 640, "2026-03-01": 640},
			),
		]
		for lease, rows, months in cases:
			plan = migration.plan_contract(lease, rows)
			converted = copy.deepcopy(rows)
			for row in converted:
				if row["art"] == migration.FIXED:
					row.update(art=migration.MONTHLY, miete=0)
			rules = [
				{
					"von": item["von"],
					"bis": item["bis"],
					"betrag": item["betrag"],
					"berechnung": migration.FIXED_RULE,
				}
				for item in plan
			]
			for month, expected in months.items():
				with self.subTest(rows=rows, month=month):
					old = calculate_monthly_rent(
						lease["von"], lease["bis"], month, rows, rounding_method="Banker's Rounding"
					)
					new = calculate_monthly_rent(
						lease["von"],
						lease["bis"],
						month,
						converted,
						rules,
						rounding_method="Banker's Rounding",
					)
					self.assertEqual(old["amount"], expected)
					self.assertEqual(new["amount"], expected)

	def _database(self, leases, rows, rules=None):
		stored_rules = copy.deepcopy(rules or [])
		inserted = []
		fake_db = SimpleNamespace(
			exists=Mock(return_value=True), savepoint=Mock(), rollback=Mock(), set_value=Mock(), commit=Mock()
		)

		def get_all(doctype, filters, fields, limit_page_length):
			self.assertEqual(limit_page_length, 0)
			if doctype == "Mietvertrag":
				return leases
			if doctype == "Staffelmiete":
				self.assertEqual(filters["parenttype"], "Mietvertrag")
				self.assertEqual(filters["parentfield"], "miete")
				if "art" in filters:
					return [{"parent": row["parent"]} for row in rows if row["art"] == filters["art"]]
				return [row for row in rows if row["parent"] == filters["parent"]]
			self.assertEqual(doctype, migration.CHILD_DOCTYPE)
			self.assertEqual(filters["parentfield"], migration.TABLE_FIELD)
			return [row for row in stored_rules if row["parent"] == filters["parent"]]

		def get_doc(values):
			self.assertEqual(values["doctype"], migration.CHILD_DOCTYPE)

			def insert():
				inserted.append(values.copy())
				stored_rules.append(values.copy())

			return SimpleNamespace(db_insert=Mock(side_effect=insert))

		def set_value(doctype, name, values, update_modified):
			self.assertEqual(doctype, "Staffelmiete")
			self.assertFalse(update_modified)
			next(row for row in rows if row["name"] == name).update(values)

		fake_db.set_value.side_effect = set_value
		return fake_db, get_all, get_doc, inserted

	def test_execute_is_idempotent_preserves_monthly_rows_and_writes_no_accounting_documents(self):
		lease = contract()
		monthly = {**rent("2026-01-16", 620, name="KEEP"), "parent": lease["name"]}
		before_monthly = monthly.copy()
		rows = [
			{**rent("2026-01-01", 300, migration.FIXED, name="CONVERT"), "parent": lease["name"]},
			monthly,
		]
		fake_db, get_all, get_doc, inserted = self._database([lease], rows)
		with (
			patch.object(migration.frappe, "db", fake_db),
			patch.object(migration.frappe, "get_all", side_effect=get_all),
			patch.object(migration.frappe, "get_doc", side_effect=get_doc),
		):
			migration.execute()
			migration.execute()
		self.assertEqual(len(inserted), 1)
		self.assertEqual(inserted[0]["betrag"], Decimal(300))
		self.assertEqual(inserted[0]["bis"], date(2026, 1, 15))
		self.assertEqual(rows[0]["miete"], 0)
		self.assertEqual(rows[0]["art"], migration.MONTHLY)
		self.assertEqual(monthly, before_monthly)
		fake_db.set_value.assert_called_once()
		fake_db.commit.assert_not_called()

	def test_all_contracts_are_validated_before_the_first_write(self):
		leases = [contract(name="MV-A"), contract(name="MV-B")]
		rows = [
			{**rent("2026-01-01", 300, migration.FIXED), "parent": "MV-A"},
			{**rent("2026-01-16", 620), "parent": "MV-A"},
			{**rent("2026-01-16", 300, migration.FIXED), "parent": "MV-B"},
		]
		fake_db, get_all, get_doc, inserted = self._database(leases, rows)
		with (
			patch.object(migration.frappe, "db", fake_db),
			patch.object(migration.frappe, "get_all", side_effect=get_all),
			patch.object(migration.frappe, "get_doc", side_effect=get_doc),
			self.assertRaisesRegex(frappe.ValidationError, "MV-B"),
		):
			migration.execute()
		self.assertEqual(inserted, [])
		fake_db.set_value.assert_not_called()
		fake_db.savepoint.assert_not_called()
		fake_db.commit.assert_not_called()

	def test_insert_error_rolls_back_the_local_savepoint(self):
		lease = contract(end=None)
		rows = [{**rent("2026-01-16", 300, migration.FIXED), "parent": lease["name"]}]
		fake_db, get_all, _, _ = self._database([lease], rows)
		with (
			patch.object(migration.frappe, "db", fake_db),
			patch.object(migration.frappe, "get_all", side_effect=get_all),
			patch.object(
				migration.frappe,
				"get_doc",
				return_value=SimpleNamespace(db_insert=Mock(side_effect=RuntimeError("insert failed"))),
			),
			self.assertRaisesRegex(RuntimeError, "insert failed"),
		):
			migration.execute()
		fake_db.rollback.assert_called_once_with(save_point="migrate_miete_teilmonate")
		fake_db.set_value.assert_not_called()
		fake_db.commit.assert_not_called()

	def test_no_legacy_rent_does_not_require_the_new_schema(self):
		fake_db = SimpleNamespace(exists=Mock(), set_value=Mock())
		with (
			patch.object(migration.frappe, "db", fake_db),
			patch.object(migration.frappe, "get_all", return_value=[]),
		):
			migration.execute()
		fake_db.exists.assert_not_called()
		fake_db.set_value.assert_not_called()

	def test_missing_schema_fails_before_writing(self):
		fake_db = SimpleNamespace(exists=Mock(return_value=False), set_value=Mock())
		with (
			patch.object(migration.frappe, "db", fake_db),
			patch.object(migration.frappe, "get_all", return_value=[{"parent": "MV-TEST"}]),
			self.assertRaisesRegex(frappe.ValidationError, "DocTypes synchronisieren"),
		):
			migration.execute()
		fake_db.set_value.assert_not_called()


class TestMigrateMieteTeilmonateDatabaseIntegration(unittest.TestCase):
	def test_real_conversion_preserves_identity_and_accounting_and_can_be_saved(self):
		suffix = frappe.generate_hash(length=8)
		savepoint = f"migrate_rent_real_{suffix}"
		frappe.db.savepoint(savepoint)
		try:
			wohnung = frappe.get_doc(
				{
					"doctype": "Wohnung",
					"name__lage_in_der_immobilie": f"HV Rent Migration {suffix}",
					"gebaeudeteil": "VH",
				}
			).insert(ignore_permissions=True)
			contact = frappe.get_doc(
				{"doctype": "Contact", "first_name": "Migration", "last_name": f"Test{suffix}"}
			).insert(ignore_permissions=True)
			lease = frappe.get_doc(
				{
					"doctype": "Mietvertrag",
					"wohnung": wohnung.name,
					"von": "2026-01-01",
					"mieter": [{"mieter": contact.name, "rolle": "Hauptmieter"}],
					"miete": [
						{"von": "2026-01-01", "miete": 620, "art": migration.MONTHLY},
						{"von": "2026-01-16", "miete": 310, "art": migration.FIXED},
					],
					"kaution": [{"von": "2026-01-01", "miete": 900, "art": migration.FIXED}],
				}
			).insert(ignore_permissions=True)
			lease.reload()
			original_customer = lease.kunde
			original_monthly = lease.miete[0].as_dict()
			original_kaution = lease.kaution[0].as_dict()
			counts = {
				doctype: frappe.db.count(doctype) for doctype in ("Customer", "Sales Invoice", "GL Entry")
			}
			get_all = frappe.get_all

			def own_candidates(doctype, *args, **kwargs):
				# Exercise real persistence while leaving unrelated site configuration alone.
				if doctype == "Staffelmiete" and kwargs.get("filters", {}).get("art") == migration.FIXED:
					kwargs["filters"] = {**kwargs["filters"], "parent": lease.name}
				return get_all(doctype, *args, **kwargs)

			with patch.object(migration.frappe, "get_all", side_effect=own_candidates):
				migration.execute()
				migration.execute()
			converted = frappe.get_doc("Mietvertrag", lease.name)
			self.assertEqual(converted.kunde, original_customer)
			self.assertEqual(converted.miete[0].as_dict(), original_monthly)
			self.assertEqual(converted.kaution[0].as_dict(), original_kaution)
			self.assertEqual(converted.miete[1].miete, 0)
			self.assertEqual(converted.miete[1].art, migration.MONTHLY)
			self.assertEqual(len(converted.miete_teilmonate), 1)
			rule = converted.miete_teilmonate[0]
			self.assertEqual(str(rule.von), "2026-01-16")
			self.assertEqual(str(rule.bis), "2026-01-31")
			self.assertEqual(rule.berechnung, migration.FIXED_RULE)
			self.assertEqual(rule.betrag, 310)
			self.assertEqual({doctype: frappe.db.count(doctype) for doctype in counts}, counts)
			for month, expected in (("2026-01-01", 610), ("2026-02-01", 0)):
				result = calculate_monthly_rent(
					converted.von,
					converted.bis,
					month,
					converted.miete,
					converted.miete_teilmonate,
					rounding_method="Banker's Rounding",
				)
				self.assertEqual(result["amount"], expected)
			converted.save(ignore_permissions=True)
			self.assertEqual(converted.kunde, original_customer)
		finally:
			frappe.db.rollback(save_point=savepoint)
