"""Versioned actions and the surfaces allowed to use them."""
from dataclasses import dataclass

from . import domain


@dataclass(frozen=True)
class Action:
	policy: str
	surface: str
	kind: str = ""
	label: str = ""
	method: str = ""
	parameters: tuple = ()


BANK_POLICY = "hv.bankimport.accounting-review/v1"
BANK_ACTIONS = {
	"assign_party": ("party", "Partei zuordnen", "apply_party_to_row_and_relink", ("party", "party_type")),
	"reconcile_invoices": ("invoice", "Rechnung zuordnen", "manually_reconcile_row", ("invoice_names", "leftover_as_advance")),
	"reconcile_split": ("split", "Aufteilen", "reconcile_split_row", ("invoice_allocations", "abschlag_rows", "leftover_as_advance")),
	"assign_abschlag": ("abschlag", "Abschlag zuordnen", "assign_abschlagsplan_row", ("plan_row_name", "plan_name", "remarks")),
	"assign_kreditrate": ("kredit", "Kreditrate zuordnen", "assign_kreditrate_to_bank_row", ("kreditvertrag", "rate_name", "from_statement")),
	"standalone_payment": ("payment", "Zahlung buchen", "create_standalone_payment_for_row", ("party_type", "party", "remarks")),
	"internal_transfer": ("transfer", "Umbuchung buchen", "create_internal_transfer_for_row", ("other_bank_account", "remarks")),
	"journal_entry": ("journal", "Journalbuchung", "create_journal_entry_for_row", ("account", "cost_center", "remarks", "splits", "wertstellungsdatum")),
}
ACTIONS = {
	domain.ACTION: Action(domain.POLICY, "synthetic"),
	"hv.cash_receipt.book/v1": Action("hv.cash_receipt.accounting-review/v1", "receipt"),
	**{action: Action(domain.DOC_POLICY, "doc") for action in domain.DOC_ACTIONS},
	**{f"hv.bankimport.{key}/v1": Action(BANK_POLICY, "bankimport", *spec)
		for key, spec in BANK_ACTIONS.items()},
}


def public(action):
	spec = ACTIONS.get(action)
	return spec is not None and spec.surface != "receipt"


BANK_ACTION_NAMES = tuple(key for key, action in ACTIONS.items() if action.surface == "bankimport")
PUBLIC_ACTIONS = tuple(action for action in ACTIONS if public(action))
