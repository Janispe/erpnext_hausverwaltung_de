from __future__ import annotations


def execute() -> None:
	from hausverwaltung.hausverwaltung.utils.bank_account_naming import (
		sync_all_immobilie_gl_cash_account_names,
	)

	sync_all_immobilie_gl_cash_account_names()
