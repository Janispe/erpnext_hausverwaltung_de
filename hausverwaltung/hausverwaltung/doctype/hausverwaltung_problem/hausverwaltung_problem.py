from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

OPEN_STATUSES = {"Offen", "In Bearbeitung"}


class HausverwaltungProblem(Document):
	def validate(self) -> None:
		if not self.problemtyp_code:
			self.problemtyp_code = _fallback_problem_type_code(self.quelle, self.problemtyp)
		if self.status == "Behoben" and not self.behoben_am:
			self.behoben_am = now_datetime()
		elif self.status in OPEN_STATUSES:
			self.behoben_am = None


def _problem_key(source: str, stable_key: str) -> str:
	payload = f"{source}\0{stable_key}".encode()
	return f"HVP-{hashlib.sha256(payload).hexdigest()[:32]}"


def _fallback_problem_type_code(source: str, problem_type: str) -> str:
	payload = f"{source}\0{problem_type}".encode()
	return f"generic.{hashlib.sha256(payload).hexdigest()[:16]}"


def sync_detected_problems(source: str, findings: list[dict[str, Any]]) -> dict[str, int]:
	"""Idempotently synchronize all current findings of one problem source."""
	if not source:
		raise ValueError("Eine Problemquelle ist erforderlich.")

	now = now_datetime()
	detected_keys: set[str] = set()
	created = 0
	reopened = 0
	updated = 0
	for finding in findings:
		stable_key = str(finding.get("key") or "").strip()
		if not stable_key:
			raise ValueError("Jeder Problembefund benötigt einen stabilen Schlüssel.")
		problem_key = _problem_key(source, stable_key)
		detected_keys.add(problem_key)
		values = {
			"titel": str(finding.get("title") or stable_key)[:140],
			"schweregrad": str(finding.get("severity") or "Warnung"),
			"problemtyp": str(finding.get("problem_type") or "Allgemein")[:140],
			"problemtyp_code": str(
				finding.get("problem_code")
				or _fallback_problem_type_code(
					source, str(finding.get("problem_type") or "Allgemein")
				)
			)[:140],
			"quelle": source[:140],
			"zuletzt_erkannt_am": now,
			"bezug_doctype": str(finding.get("reference_doctype") or ""),
			"bezug_name": str(finding.get("reference_name") or ""),
			"weiterer_bezug_doctype": str(finding.get("secondary_doctype") or ""),
			"weiterer_bezug_name": str(finding.get("secondary_name") or ""),
			"beschreibung": str(finding.get("description") or finding.get("title") or stable_key),
			"details_json": json.dumps(
				finding.get("details") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
			),
		}
		existing_name = frappe.db.get_value(
			"Hausverwaltung Problem", {"problem_schluessel": problem_key}, "name"
		)
		if not existing_name:
			frappe.get_doc(
				{
					"doctype": "Hausverwaltung Problem",
					"problem_schluessel": problem_key,
					"status": "Offen",
					"erkannt_am": now,
					**values,
				}
			).insert(ignore_permissions=True)
			created += 1
			continue

		status = frappe.db.get_value("Hausverwaltung Problem", existing_name, "status")
		if status == "Behoben":
			values.update({"status": "Offen", "behoben_am": None, "loesung": ""})
			reopened += 1
		frappe.db.set_value("Hausverwaltung Problem", existing_name, values, update_modified=False)
		updated += 1

	resolved = 0
	open_rows = frappe.get_all(
		"Hausverwaltung Problem",
		filters={"quelle": source, "status": ["in", sorted(OPEN_STATUSES)]},
		fields=["name", "problem_schluessel"],
		limit_page_length=0,
	)
	for row in open_rows:
		if row.problem_schluessel in detected_keys:
			continue
		frappe.db.set_value(
			"Hausverwaltung Problem",
			row.name,
			{
				"status": "Behoben",
				"behoben_am": now,
				"loesung": _(
					"Automatisch behoben: Der Befund ist bei der letzten Prüfung nicht mehr aufgetreten."
				),
			},
			update_modified=False,
		)
		resolved += 1

	return {
		"detected": len(findings),
		"created": created,
		"updated": updated,
		"reopened": reopened,
		"resolved": resolved,
	}


@frappe.whitelist()
def run_problem_checks() -> dict[str, Any]:
	frappe.only_for(("System Manager", "Hausverwalter"))
	results: dict[str, Any] = {}
	for checker_path in frappe.get_hooks("hausverwaltung_problem_checks"):
		results[checker_path] = frappe.get_attr(checker_path)()
	return results
