from unittest.mock import patch

import unittest

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
