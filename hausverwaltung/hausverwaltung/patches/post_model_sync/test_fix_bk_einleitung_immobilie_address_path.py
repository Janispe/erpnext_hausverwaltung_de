import unittest

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	fix_bk_einleitung_immobilie_address_path as module,
)


class TestFixBkEinleitungImmobilieAddressPath(unittest.TestCase):
	def test_replaces_address_magic_with_immobilie_address_link(self):
		value = "in der {{$ wohnung.immobilie.address.adresse $}} im Zeitraum"

		self.assertEqual(
			module.replace_address_path(value),
			"in der {{$ wohnung.immobilie.adresse.adresse $}} im Zeitraum",
		)

	def test_replacement_is_idempotent(self):
		value = "{{$ wohnung.immobilie.adresse.adresse $}}"

		self.assertEqual(module.replace_address_path(value), value)
