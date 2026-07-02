def execute():
	from hausverwaltung.hausverwaltung.utils.bankimport_rules import (
		ensure_default_bankimport_rules,
	)

	ensure_default_bankimport_rules()
