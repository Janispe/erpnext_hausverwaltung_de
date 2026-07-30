"""Legacy-BK-Rechnungen ohne vollständige Wohnungsdimension protokollieren.

Gebuchte Sales Invoices dürfen nicht per Header-SQL scheinbar "repariert"
werden: Positionen und GL Entries würden dabei unverändert bleiben. Eine
solche Teilkorrektur macht die sichtbaren Stammdaten plausibel, während das
Ledger weiterhin eine andere Wahrheit enthält. Deshalb ist dieser Patch für
eingereichte Belege bewusst read-only; die eigentliche Bereinigung muss über
einen kontrollierten Repost erfolgen.
"""

from __future__ import annotations

import json

import frappe

_SAMPLE_LIMIT = 200


def _structured_contract_sql(alias: str = "si") -> str:
	return f"""
		CASE
			WHEN INSTR(COALESCE({alias}.mietabrechnung_id, ''), '|') > 0
			THEN LEFT(
				{alias}.mietabrechnung_id,
				CHAR_LENGTH({alias}.mietabrechnung_id)
				- CHAR_LENGTH(SUBSTRING_INDEX({alias}.mietabrechnung_id, '|', -1))
				- 1
			)
			ELSE NULL
		END
	"""


def _candidate_select_sql() -> str:
	"""Return the complete read-only candidate set without ordering or limits."""
	contract_expr = _structured_contract_sql("si")
	return f"""
		SELECT
			si.name,
			si.customer,
			si.posting_date,
			si.mietabrechnung_id,
			mv.wohnung AS contract_wohnung,
			CASE
				WHEN mv.name IS NOT NULL
				 AND mv.kunde = si.customer
				 AND COALESCE(mv.wohnung, '') != ''
				THEN 'controlled_repost_required'
				ELSE 'identity_ambiguous'
			END AS reason
		FROM `tabSales Invoice` si
		LEFT JOIN `tabMietvertrag` mv
		  ON mv.name = {contract_expr}
		WHERE si.docstatus = 1
		  AND COALESCE(si.wohnung, '') = ''
		  AND EXISTS (
				SELECT 1
				FROM `tabSales Invoice Item` sii
				WHERE sii.parent = si.name
				  AND sii.item_code IN (
					'Miete',
					'Betriebskosten',
					'Heizkosten',
					'Untermietzuschlag'
				  )
		  )
	"""


def execute() -> None:
	if not (
		frappe.db.has_column("Sales Invoice", "wohnung")
		and frappe.db.has_column("Sales Invoice", "mietabrechnung_id")
	):
		return

	# Auch exakt auflösbare Fälle werden nur protokolliert. Header, Items und
	# aktive GL Entries müssen später gemeinsam/repostend korrigiert werden.
	candidate_sql = _candidate_select_sql()
	counts = frappe.db.sql(
		f"""
		SELECT candidates.reason, COUNT(*) AS total
		FROM ({candidate_sql}) candidates
		GROUP BY candidates.reason
		ORDER BY candidates.reason
		""",
		as_dict=True,
	)
	total = sum(int(row.get("total") or 0) for row in counts or [])
	if total:
		samples = frappe.db.sql(
			f"""
			{candidate_sql}
			ORDER BY si.name
			LIMIT %(sample_limit)s
			""",
			{"sample_limit": _SAMPLE_LIMIT},
			as_dict=True,
		) or []
		payload = {
			"read_only": True,
			"total": total,
			"counts_by_reason": {
				row.get("reason"): int(row.get("total") or 0)
				for row in counts or []
			},
			"sample_limit": _SAMPLE_LIMIT,
			"sample_count": len(samples),
			"truncated": total > len(samples),
			"samples": [dict(row) for row in samples],
		}
		frappe.log_error(
			title="Mietrechnungen benötigen kontrollierten Wohnungs-Repost",
			message=json.dumps(
				payload,
				default=str,
				ensure_ascii=False,
				indent=2,
			),
		)
