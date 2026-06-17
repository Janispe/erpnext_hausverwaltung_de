import unittest

from hausverwaltung.hausverwaltung.utils.brand_print import apply_print_saving_brand_assets


class TestBrandPrint(unittest.TestCase):
	def test_hides_peters_lockup_when_configured(self):
		html = '<div><img src="/files/peters-lockup.svg" style="height:2cm;">Text</div>'

		rendered = apply_print_saving_brand_assets(html, enabled=False, hide_peters_logo=True)

		self.assertEqual(rendered, "<div>Text</div>")

	def test_hides_peters_seal_when_configured(self):
		html = '<div><img alt="Logo" src="/files/peters-siegel-sw.svg">Text</div>'

		rendered = apply_print_saving_brand_assets(html, enabled=False, hide_peters_logo=True)

		self.assertEqual(rendered, "<div>Text</div>")

	def test_keeps_and_switches_lockup_when_hide_disabled(self):
		html = '<img src="/files/peters-lockup.svg" style="height:2cm;">'

		rendered = apply_print_saving_brand_assets(html, enabled=True, hide_peters_logo=False)

		self.assertIn('/files/peters-siegel-sw.svg', rendered)
		self.assertIn("height:1.15cm;", rendered)
