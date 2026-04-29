__version__ = "0.0.1"


# Workaround für einen Frappe-Bug, der den Chromium-PDF-Renderer crashen lässt,
# wenn ein Print Format ein ``<div id="footer-html">`` enthält. Frappe setzt
# dabei fälschlich den Body-``marginBottom`` auf der Footer-Page, was Chrome
# mit ``invalid print parameters: content area is empty`` ablehnt.
# Der Patch ist idempotent und läuft beim ersten Import dieses Moduls.
try:
	from hausverwaltung.hausverwaltung.utils.frappe_chrome_footer_patch import (
		apply as _apply_chrome_footer_patch,
	)

	_apply_chrome_footer_patch()
except Exception:
	# Defensiv: falls der Import beim allerersten Setup (vor Migrate) fehlschlägt,
	# nicht den ganzen App-Boot sprengen. Beim nächsten Boot greift er.
	pass
