from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from hausverwaltung.hausverwaltung.processes.engine import get_process_runtime_config
from hausverwaltung.hausverwaltung.processes.task_registry import (
	TASK_TYPE_MANUAL_CHECK,
	dump_task_config,
	extract_task_config,
)


def _ensure_runtime_registered(runtime_doctype: str):
	if get_process_runtime_config(runtime_doctype):
		return
	if runtime_doctype == "Mieterwechsel":
		from hausverwaltung.hausverwaltung.processes.definitions.mieterwechsel import get_mieterwechsel_runtime

		get_mieterwechsel_runtime()


_LOCKED_SCALAR_FIELDS = (
	"version_key",      # autoname-Field, Umbenennung einer aktiven Version waere katastrophal
	"runtime_doctype",  # Re-Targeting auf anderen Doctype = stiller Identitaetswechsel
	"titel",
	"beschreibung",
	"gueltig_ab",
	"gueltig_bis",
)


class ProzessVersion(Document):
	def validate(self) -> None:
		# Active-Lock zuerst: bei aktiven Versionen soll die schreibgeschuetzt-Botschaft
		# Vorrang haben vor anderen Validierungs-Fehlern (z.B. unregistriertem Runtime-
		# Doctype), denn dem User soll die zentrale Aussage "diese Version ist locked"
		# sofort sichtbar werden, statt einer technischen Sekundaer-Fehlermeldung.
		self._enforce_active_immutability()
		self._validate_runtime_doctype()
		self._normalize_rows()
		self._validate_active_uniqueness()

	def _enforce_active_immutability(self) -> None:
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		was_active = bool(before.get("is_active"))
		is_active_now = bool(self.is_active)
		diffs = self._compute_content_diffs(before)

		# Fall 1: Aktivierungs-Uebergang (0 -> 1) muss separat von Content-Edits sein
		if not was_active and is_active_now:
			if diffs:
				frappe.throw(
					_(
						"Aktivierung muss separat erfolgen: bitte erst die Aenderungen "
						"[{0}] speichern, dann in einem zweiten Save aktivieren."
					).format(", ".join(diffs))
				)
			return

		# Fall 2: Deaktivierungs-Uebergang (1 -> 0) muss separat von Content-Edits sein.
		# Sonst koennte man eine aktive Version mutieren und gleichzeitig deaktivieren,
		# was die History/Audit-Aussage "diese Form war einmal aktiv" verfaelscht.
		if was_active and not is_active_now:
			if diffs:
				frappe.throw(
					_(
						"Deaktivierung muss separat erfolgen: bitte zuerst diese Aenderungen "
						"rueckgaengig machen [{0}], dann in einem zweiten Save deaktivieren."
					).format(", ".join(diffs))
				)
			return

		# Fall 3: bleibt inaktiv (0 -> 0)
		if not was_active and not is_active_now:
			return

		# Fall 4: bleibt aktiv (1 -> 1) Content-Lock greift
		if not diffs:
			return
		frappe.throw(
			_(
				"Aktive Prozess-Versionen sind schreibgeschuetzt. "
				"Aenderungen an [{0}] sind nur via 'Bearbeiten als neue Version' moeglich."
			).format(", ".join(diffs))
		)

	def _compute_content_diffs(self, before) -> list[str]:
		diffs: list[str] = []
		for field in _LOCKED_SCALAR_FIELDS:
			if (before.get(field) or "") != (self.get(field) or ""):
				diffs.append(field)
		if self._schritte_fingerprint(before) != self._schritte_fingerprint(self):
			diffs.append("schritte")
		if self._kanten_fingerprint(before) != self._kanten_fingerprint(self):
			diffs.append("schritt_kanten")
		return diffs

	@staticmethod
	def _schritte_fingerprint(doc) -> tuple:
		"""Fingerprint nimmt RAW-Source-Felder, NICHT das von _normalize_rows
		abgeleitete config_json. Begruendung: _enforce_active_immutability laeuft
		VOR _normalize_rows, config_json ist daher im aktuellen Save noch stale.
		Wenn ein neues Source-Feld auf Prozess Schritt ergaenzt wird, muss es hier mit."""
		rows = []
		for s in doc.get("schritte") or []:
			rows.append(
				(
					(s.get("step_key") or "").strip(),
					(s.get("titel") or "").strip(),
					(s.get("task_type") or "").strip(),
					(s.get("handler_key") or "").strip(),
					int(s.get("pflicht") or 0),
					(s.get("sichtbar_fuer_prozess_typ") or "").strip(),
					(s.get("dokument_typ_tag") or "").strip(),
					(s.get("print_format") or "").strip(),
					(s.get("mapping_flag") or "").strip(),
					(s.get("standard_verantwortlich_rolle") or "").strip(),
					int(s.get("default_faelligkeit_tage") or 0),
					int(s.get("reihenfolge") or 0),
					(s.get("konfig_json") or "").strip(),
					(s.get("sichtbar_wenn") or "").strip(),
					(s.get("freigabe_wenn") or "").strip(),
					# Deprecated, aber Engine liest es weiterhin als dual-read Fallback.
					# Solange dual-read aktiv ist, muss es im Fingerprint gesperrt sein.
					(s.get("parent_step_key") or "").strip(),
				)
			)
		return tuple(sorted(rows))

	@staticmethod
	def _kanten_fingerprint(doc) -> tuple:
		rows = []
		for k in doc.get("schritt_kanten") or []:
			rows.append(
				(
					(k.get("step_key") or "").strip(),
					(k.get("depends_on_step_key") or "").strip(),
				)
			)
		return tuple(sorted(rows))

	def _validate_runtime_doctype(self):
		runtime_doctype = (self.runtime_doctype or "").strip()
		if not runtime_doctype:
			frappe.throw(_("Runtime Doctype ist erforderlich."))
		_ensure_runtime_registered(runtime_doctype)
		if not get_process_runtime_config(runtime_doctype):
			frappe.throw(_("Kein Process Runtime fuer Doctype registriert: {0}").format(runtime_doctype))

	def _get_runtime_config(self):
		runtime_doctype = (self.runtime_doctype or "").strip()
		_ensure_runtime_registered(runtime_doctype)
		config = get_process_runtime_config(runtime_doctype)
		if not config:
			frappe.throw(_("Kein Process Runtime fuer Doctype registriert: {0}").format(runtime_doctype))
		return config

	def _normalize_rows(self) -> None:
		import graphlib

		runtime_config = self._get_runtime_config()
		seen_keys: set[str] = set()
		for idx, row in enumerate(self.get("schritte") or [], start=1):
			if not row.reihenfolge:
				row.reihenfolge = idx
			if not (row.step_key or "").strip():
				row.step_key = f"step_{idx:02d}"
			if not (row.task_type or "").strip():
				row.task_type = TASK_TYPE_MANUAL_CHECK
			row.config_json = dump_task_config(extract_task_config(row))
			row.konfig_json = row.config_json
			step_key = (row.step_key or "").strip()
			if step_key in seen_keys:
				frappe.throw(_("Step Key ist doppelt: {0}").format(step_key))
			seen_keys.add(step_key)
		for row in self.get("schritte") or []:
			parent_step_key = (row.parent_step_key or "").strip()
			if parent_step_key and parent_step_key not in seen_keys:
				frappe.throw(_("Parent Step Key existiert nicht: {0}").format(parent_step_key))
			handler = runtime_config.task_handler_registry.get_handler(
				handler_key=(row.handler_key or "").strip(),
				task_type=row.task_type,
				context=runtime_config.task_handler_context,
			)
			handler.validate_config(row)

		# Edge-Validierung (DAG-Kanten in schritt_kanten)
		seen_edges: set[tuple[str, str]] = set()
		for edge in self.get("schritt_kanten") or []:
			sk = (edge.step_key or "").strip()
			dep = (edge.depends_on_step_key or "").strip()
			if not sk or not dep:
				frappe.throw(_("Kante braucht step_key UND depends_on_step_key."))
			if sk not in seen_keys:
				frappe.throw(_("Kante referenziert unbekannten Schritt: {0}").format(sk))
			if dep not in seen_keys:
				frappe.throw(_("Kante referenziert unbekannten Vorgaenger-Schritt: {0}").format(dep))
			if sk == dep:
				frappe.throw(_("Schritt kann nicht von sich selbst abhaengen: {0}").format(sk))
			edge_key = (sk, dep)
			if edge_key in seen_edges:
				frappe.throw(_("Doppelte Kante: {0} haengt mehrfach von {1} ab.").format(sk, dep))
			seen_edges.add(edge_key)

		# Cycle-Detection ueber kombinierten Edge-Set (neue Kanten + legacy parent_step_key)
		edges_combined: dict[str, list[str]] = {}
		for edge in self.get("schritt_kanten") or []:
			sk = (edge.step_key or "").strip()
			dep = (edge.depends_on_step_key or "").strip()
			if sk and dep:
				edges_combined.setdefault(sk, []).append(dep)
		for row in self.get("schritte") or []:
			sk = (row.step_key or "").strip()
			legacy = (row.parent_step_key or "").strip()
			if sk and legacy and legacy not in edges_combined.get(sk, []):
				edges_combined.setdefault(sk, []).append(legacy)
		ts = graphlib.TopologicalSorter()
		for sk in seen_keys:
			ts.add(sk, *edges_combined.get(sk, []))
		try:
			ts.prepare()
		except graphlib.CycleError as e:
			cycle_path = " -> ".join(e.args[1]) if len(e.args) > 1 else str(e)
			frappe.throw(_("Zyklus in Schritt-Abhaengigkeiten: {0}").format(cycle_path))

		if self.get("schritte"):
			self.set("schritte", sorted(self.get("schritte"), key=lambda r: int(r.reihenfolge or 0)))

	def _validate_active_uniqueness(self) -> None:
		if not self.is_active:
			return
		filters = {
			"name": ("!=", self.name or ""),
			"is_active": 1,
			"runtime_doctype": (self.runtime_doctype or "").strip(),
		}
		if frappe.db.exists("Prozess Version", filters):
			frappe.throw(
				_("Es darf nur eine aktive Prozessversion fuer {0} geben.").format(self.runtime_doctype)
			)


@frappe.whitelist()
def duplicate_version(name: str, new_version_key: str | None = None, new_titel: str | None = None) -> str:
	src = frappe.get_doc("Prozess Version", name)
	src.check_permission("read")
	new_doc = frappe.copy_doc(src)
	new_doc.is_active = 0
	new_doc.gueltig_ab = None
	new_doc.gueltig_bis = None
	new_doc.version_key = (new_version_key or "").strip() or f"{src.version_key}-copy"
	new_doc.titel = (new_titel or "").strip() or f"{src.titel} (Kopie)"
	new_doc.insert(ignore_permissions=False)
	return new_doc.name


@frappe.whitelist()
def get_activation_preview(name: str) -> dict:
	doc = frappe.get_doc("Prozess Version", name)
	doc.check_permission("read")
	currently_active = frappe.get_all(
		"Prozess Version",
		filters={
			"is_active": 1,
			"runtime_doctype": (doc.runtime_doctype or "").strip(),
			"name": ("!=", doc.name),
		},
		fields=["name", "titel", "version_key"],
		limit=1,
	)
	return {
		"version_name": doc.name,
		"version_titel": doc.titel,
		"version_key": doc.version_key,
		"schritt_count": len(doc.schritte or []),
		"kanten_count": len(doc.schritt_kanten or []),
		"runtime_doctype": doc.runtime_doctype,
		"currently_active": currently_active[0] if currently_active else None,
	}


@frappe.whitelist()
def activate_version(name: str) -> str:
	doc = frappe.get_doc("Prozess Version", name)
	doc.check_permission("write")
	others = frappe.get_all(
		"Prozess Version",
		filters={
			"is_active": 1,
			"runtime_doctype": (doc.runtime_doctype or "").strip(),
			"name": ("!=", doc.name),
		},
		pluck="name",
	)
	for nm in others:
		frappe.db.set_value("Prozess Version", nm, "is_active", 0, update_modified=False)
	if not doc.is_active:
		doc.db_set("is_active", 1, update_modified=False)
	return doc.name
