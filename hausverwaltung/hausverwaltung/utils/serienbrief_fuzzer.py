from __future__ import annotations

import random
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import frappe


@dataclass
class _RunResult:
	index: int
	template: str
	iteration_doctype: str
	iteration_objects: list[str]
	mode: str
	ok: bool
	output: str | None = None
	error: str | None = None


def _pick_templates(template: str | None = None) -> list[str]:
	if template:
		name = str(template).strip()
		if not name:
			return []
		if not frappe.db.exists("Serienbrief Vorlage", name):
			return []
		return [name]

	return frappe.get_all("Serienbrief Vorlage", pluck="name")


def _template_iteration_doctype(template_doc, override_doctype: str | None) -> str | None:
	if override_doctype:
		return str(override_doctype).strip() or None
	return (template_doc.get("haupt_verteil_objekt") or "").strip() or None


def _candidate_names(doctype: str, limit: int) -> list[str]:
	limit = int(limit or 0) or 0
	limit = max(1, min(limit, 50_000))
	try:
		return frappe.get_all(doctype, order_by="modified desc", pluck="name", limit_page_length=limit)
	except Exception:
		# Some doctypes might not be queryable depending on permissions / broken meta.
		return []


def _cleanup_durchlauf(durchlauf_name: str) -> None:
	# Delete generated documents
	for docname in frappe.get_all(
		"Serienbrief Dokument",
		filters={"durchlauf": durchlauf_name},
		pluck="name",
	):
		try:
			frappe.delete_doc("Serienbrief Dokument", docname, force=1, ignore_permissions=True)
		except Exception:
			pass

	# Delete generated files
	for file_name in frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Serienbrief Durchlauf",
			"attached_to_name": durchlauf_name,
		},
		pluck="name",
	):
		try:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)
		except Exception:
			pass

	# Finally delete the run doc
	try:
		frappe.delete_doc("Serienbrief Durchlauf", durchlauf_name, force=1, ignore_permissions=True)
	except Exception:
		pass


def _run_mode(durchlauf_doc, mode: str) -> str | None:
	mode = (mode or "").strip().lower() or "dokumente"
	if mode in ("render", "html_render"):
		durchlauf_doc._render_full_html()
		return None
	if mode in ("dokumente", "docs", "documents"):
		durchlauf_doc._ensure_dokumente(recreate=True, submit=False)
		return None
	if mode == "html":
		return str(durchlauf_doc.generate_html_file() or "")
	if mode == "pdf":
		return str(durchlauf_doc.generate_pdf_file() or "")
	raise ValueError(f"Unknown mode: {mode}")


def random_serienbrief_runs(
	*,
	count: int | str = 10,
	recipients: int | str = 3,
	mode: str = "dokumente",
	template: str | None = None,
	iteration_doctype: str | None = None,
	candidate_limit: int | str = 2000,
	seed: int | str | None = None,
	keep: int | str = 0,
	max_attempts_per_run: int | str = 25,
	verbose: int | str = 1,
) -> Dict[str, Any]:
	"""Create random Serienbrief Durchlauf docs and generate output.

	Designed to be called via `bench execute ... --kwargs "{...}"`.

	Returns a JSON-serializable summary dict.
	"""

	count_i = max(0, int(count or 0))
	recipients_i = max(1, int(recipients or 1))
	keep_b = bool(int(keep or 0))
	attempts_i = max(1, int(max_attempts_per_run or 1))
	verbose_b = bool(int(verbose or 0))

	if seed is not None and str(seed).strip() != "":
		random.seed(int(seed))

	templates = _pick_templates(template)
	if not templates:
		return {
			"ok": False,
			"error": "No Serienbrief Vorlage found (or template does not exist).",
			"count": count_i,
		}

	results: list[_RunResult] = []
	success = 0
	failed = 0
	skipped = 0

	for run_index in range(1, count_i + 1):
		last_error: str | None = None
		ok = False
		chosen_template = ""
		chosen_doctype = ""
		chosen_objs: list[str] = []
		output: str | None = None

		for _attempt in range(attempts_i):
			chosen_template = random.choice(templates)
			template_doc = frappe.get_cached_doc("Serienbrief Vorlage", chosen_template)
			chosen_doctype = _template_iteration_doctype(template_doc, iteration_doctype) or ""
			if not chosen_doctype:
				last_error = "Template has no `haupt_verteil_objekt` and no iteration_doctype override was given."
				continue

			candidates = _candidate_names(chosen_doctype, int(candidate_limit or 2000))
			if not candidates:
				last_error = f"No candidate documents found for Iterations-Doctype: {chosen_doctype}"
				continue

			chosen_objs = (
				random.sample(candidates, k=min(recipients_i, len(candidates)))
				if len(candidates) > 1
				else [candidates[0]]
			)

			try:
				durchlauf = frappe.get_doc(
					{
						"doctype": "Serienbrief Durchlauf",
						"title": f"Random Run {run_index}",
						"vorlage": chosen_template,
						"kategorie": template_doc.get("kategorie"),
						"iteration_doctype": chosen_doctype,
						"iteration_objekte": [
							{
								"doctype": "Serienbrief Iterationsobjekt",
								"iteration_doctype": chosen_doctype,
								"objekt": name,
							}
							for name in chosen_objs
						],
					}
				)
				durchlauf.flags.ignore_mandatory = True
				durchlauf.flags.ignore_permissions = True
				durchlauf.insert(ignore_permissions=True)

				output = _run_mode(durchlauf, mode)
				ok = True

				if not keep_b:
					_cleanup_durchlauf(durchlauf.name)

				frappe.db.commit()
				break
			except Exception:
				frappe.db.rollback()
				last_error = traceback.format_exc(limit=50)

		if ok:
			success += 1
		else:
			# If we never got far enough to consider it a failure, count as skipped.
			if last_error and last_error.startswith("No candidate documents found for Iterations-Doctype"):
				skipped += 1
			else:
				failed += 1

		results.append(
			_RunResult(
				index=run_index,
				template=chosen_template,
				iteration_doctype=chosen_doctype,
				iteration_objects=chosen_objs,
				mode=(mode or "").strip() or "dokumente",
				ok=ok,
				output=output,
				error=None if ok else last_error,
			)
		)

	payload: dict[str, Any] = {
		"ok": failed == 0,
		"count": count_i,
		"success": success,
		"failed": failed,
		"skipped": skipped,
		"mode": (mode or "").strip() or "dokumente",
		"template": template,
		"iteration_doctype": iteration_doctype,
		"recipients": recipients_i,
		"candidate_limit": int(candidate_limit or 2000),
		"keep": int(keep_b),
	}

	if verbose_b:
		payload["runs"] = [
			{
				"index": r.index,
				"ok": r.ok,
				"template": r.template,
				"iteration_doctype": r.iteration_doctype,
				"iteration_objects": r.iteration_objects,
				"output": r.output,
				"error": r.error,
			}
			for r in results
		]

	return payload
