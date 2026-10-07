"""Sample identity regressions against a connected, disposable Frappe test site."""

import uuid
from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.data_import.sample import sample_data


class TestSampleDocumentIdentity(TestCase):
    def setUp(self):
        self.savepoint = "sample_naming_" + uuid.uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.addCleanup(frappe.db.rollback, save_point=self.savepoint)
        commit_patch = patch.object(frappe.db, "commit")
        commit_patch.start()
        self.addCleanup(commit_patch.stop)
        enqueue_patch = patch.object(frappe, "enqueue")
        enqueue_patch.start()
        self.addCleanup(enqueue_patch.stop)
        self.suffix = uuid.uuid4().hex[:10]
        self.import_number = int(uuid.uuid4().hex[:7], 16) + 10000000

    def _address(self, label):
        return frappe.get_doc({
            "doctype": "Address",
            "address_title": label,
            "address_line1": "Teststr. 1",
            "city": "Berlin",
            "country": "Germany",
            "address_type": "Other",
        }).insert(ignore_permissions=True)

    def _property(self, *, number=None, legacy_name=None):
        label = f"_Sample Naming {self.suffix} {uuid.uuid4().hex[:4]}"
        address = self._address(label)
        doc = frappe.get_doc({
            "doctype": "Immobilie",
            "bezeichnung": label,
            "immobilien_id": self.import_number if number is None else number,
            "adresse": address.name,
        })
        if legacy_name:
            with patch(
                "hausverwaltung.hausverwaltung.doctype.immobilie.immobilie.make_document_name",
                return_value=legacy_name,
            ):
                return doc.insert(ignore_permissions=True)
        return doc.insert(ignore_permissions=True)

    def _ensure_property(self, doc, **overrides):
        arguments = {
            "label": doc.bezeichnung,
            "import_id": doc.immobilien_id,
            "address": doc.adresse,
        }
        arguments.update(overrides)
        return sample_data._get_or_create_sample_immobilie(**arguments)

    def _apartment(self, property_doc, *, number=1, location="EG links", legacy_name=None):
        doc = frappe.get_doc({
            "doctype": "Wohnung",
            "immobilie": property_doc.name,
            "id": number,
            "name__lage_in_der_immobilie": location,
        })
        if legacy_name:
            with patch(
                "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.make_document_name",
                return_value=legacy_name,
            ):
                return doc.insert(ignore_permissions=True)
        return doc.insert(ignore_permissions=True)

    def _snapshot(self, doctype, name):
        fields = ["name", "creation", "modified", "docstatus", "bezeichnung"]
        fields += ["adresse", "immobilien_id"] if doctype == "Immobilie" else ["immobilie", "id"]
        return frappe.db.get_value(doctype, name, fields, as_dict=True)

    def test_new_sample_records_have_short_ids_and_repeat_without_changes(self):
        label = f"_Sample Naming {self.suffix}"
        address = self._address(label)
        arguments = {"label": label, "import_id": self.import_number, "address": address.name}
        property_name, property_created = sample_data._get_or_create_sample_immobilie(**arguments)
        apartment_arguments = {"immobilie": property_name, "import_id": 41, "lage": "EG links"}
        apartment_name, apartment_created = sample_data._get_or_create_sample_wohnung(**apartment_arguments)

        self.assertTrue(property_created)
        self.assertTrue(apartment_created)
        self.assertRegex(property_name, r"^IMM-\d+$")
        self.assertRegex(apartment_name, r"^WHG-\d+$")
        self.assertEqual(frappe.db.get_value("Immobilie", property_name, "bezeichnung"), label)
        self.assertEqual(frappe.db.get_value("Immobilie", property_name, "immobilien_id"), self.import_number)
        self.assertEqual(frappe.db.get_value("Wohnung", apartment_name, "immobilie"), property_name)
        self.assertEqual(frappe.db.get_value("Wohnung", apartment_name, "id"), 41)
        property_before = self._snapshot("Immobilie", property_name)
        apartment_before = self._snapshot("Wohnung", apartment_name)

        self.assertEqual(sample_data._get_or_create_sample_immobilie(**arguments), (property_name, False))
        self.assertEqual(sample_data._get_or_create_sample_wohnung(**apartment_arguments), (apartment_name, False))
        self.assertEqual(self._snapshot("Immobilie", property_name), property_before)
        self.assertEqual(self._snapshot("Wohnung", apartment_name), apartment_before)
        self.assertEqual(frappe.db.count("Immobilie", {"immobilien_id": self.import_number}), 1)
        self.assertEqual(frappe.db.count("Wohnung", {"immobilie": property_name, "id": 41}), 1)

    def test_existing_legacy_ids_and_apartment_links_are_preserved(self):
        property_doc = self._property(legacy_name=f"Sample Legacy Property {self.suffix}")
        apartment_doc = self._apartment(
            property_doc, legacy_name=f"Sample Legacy Apartment {self.suffix} | EG links"
        )
        property_before = self._snapshot("Immobilie", property_doc.name)
        apartment_before = self._snapshot("Wohnung", apartment_doc.name)

        self.assertEqual(self._ensure_property(property_doc), (property_doc.name, False))
        self.assertEqual(
            sample_data._get_or_create_sample_wohnung(
                immobilie=property_doc.name, import_id=1, lage="EG links"
            ),
            (apartment_doc.name, False),
        )
        self.assertEqual(self._snapshot("Immobilie", property_doc.name), property_before)
        self.assertEqual(self._snapshot("Wohnung", apartment_doc.name), apartment_before)

    def test_changed_property_label_does_not_change_identity(self):
        property_doc = self._property()
        original_label = property_doc.bezeichnung
        frappe.db.set_value(
            "Immobilie", property_doc.name, "bezeichnung", original_label + " umbenannt", update_modified=False
        )
        before = self._snapshot("Immobilie", property_doc.name)

        self.assertEqual(self._ensure_property(property_doc), (property_doc.name, False))
        self.assertEqual(self._snapshot("Immobilie", property_doc.name), before)
        self.assertEqual(frappe.db.count("Immobilie", {"immobilien_id": self.import_number}), 1)

    def test_multiple_properties_with_same_import_number_are_rejected(self):
        first = self._property()
        self._property()

        with self.assertRaisesRegex(frappe.ValidationError, "Mehrere Immobilien"):
            self._ensure_property(first)

        self.assertEqual(frappe.db.count("Immobilie", {"immobilien_id": self.import_number}), 2)

    def test_conflicting_property_label_and_number_are_rejected(self):
        first = self._property()
        second = self._property(number=self.import_number + 1)

        with self.assertRaisesRegex(frappe.ValidationError, "Mehrere Immobilien"):
            self._ensure_property(first, label=second.bezeichnung)

        self.assertEqual(frappe.db.count("Immobilie", {"immobilien_id": self.import_number}), 1)
        self.assertEqual(frappe.db.count("Immobilie", {"immobilien_id": self.import_number + 1}), 1)

    def test_single_property_with_conflicting_number_or_address_is_rejected(self):
        property_doc = self._property()
        other_address = self._address(f"_Sample Naming Other Address {self.suffix}")
        before = self._snapshot("Immobilie", property_doc.name)

        for overrides in (
            {"import_id": self.import_number + 1},
            {"address": other_address.name},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(frappe.ValidationError, "passt nicht"):
                    self._ensure_property(property_doc, **overrides)

        self.assertEqual(self._snapshot("Immobilie", property_doc.name), before)
        self.assertEqual(frappe.db.count("Immobilie", {"immobilien_id": self.import_number}), 1)

    def test_multiple_apartments_with_same_property_and_import_number_are_rejected(self):
        property_doc = self._property()
        self._apartment(property_doc)
        self._apartment(property_doc, location="OG rechts")

        with self.assertRaisesRegex(frappe.ValidationError, "Mehrere Sample-Wohnungen"):
            sample_data._get_or_create_sample_wohnung(
                immobilie=property_doc.name, import_id=1, lage="EG links"
            )

        self.assertEqual(frappe.db.count("Wohnung", {"immobilie": property_doc.name, "id": 1}), 2)

    def test_apartment_import_number_is_scoped_to_actual_property_id(self):
        first = self._property()
        second = self._property(number=self.import_number + 1)
        first_name, _ = sample_data._get_or_create_sample_wohnung(
            immobilie=first.name, import_id=1, lage="EG links"
        )
        second_name, _ = sample_data._get_or_create_sample_wohnung(
            immobilie=second.name, import_id=1, lage="EG links"
        )

        self.assertNotEqual(first_name, second_name)
        self.assertEqual(frappe.db.get_value("Wohnung", first_name, "immobilie"), first.name)
        self.assertEqual(frappe.db.get_value("Wohnung", second_name, "immobilie"), second.name)
        self.assertEqual(
            sample_data._get_or_create_sample_wohnung(immobilie=first.name, import_id=1, lage="EG links"),
            (first_name, False),
        )
