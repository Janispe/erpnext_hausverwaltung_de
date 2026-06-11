from __future__ import annotations

import json
import importlib
import os
import re
import time
import uuid
from decimal import Decimal
from io import BytesIO
from typing import Any, Dict, List

import frappe
from bs4 import BeautifulSoup
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from jinja2 import TemplateError, Undefined, UndefinedError
from markupsafe import Markup
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document
from frappe.utils import cint, cstr, format_date, now_datetime, today
from frappe.utils.jinja import get_jenv

from hausverwaltung.hausverwaltung.utils.pdf_engine import render_pdf as get_pdf
from hausverwaltung.hausverwaltung.utils.serienbrief_fonts import (
	get_serienbrief_font_face_css,
	serienbrief_font_family,
)

from hausverwaltung.hausverwaltung.utils.jinja_source_sanitizer import sanitize_richtext_jinja_source
from hausverwaltung.hausverwaltung.utils.brand_print import apply_print_saving_brand_assets
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import read_file_url_bytes
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import render_pdf_bytes_as_html_fragment
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import render_pdf_form_block


class _IterationEmpfaengerRow:
	def __init__(self, data: dict[str, Any]):
		object.__setattr__(self, "_data", dict(data))

	def __getattr__(self, key: str):
		return self._data.get(key)

	def __setattr__(self, key: str, value):
		if key.startswith("_"):
			object.__setattr__(self, key, value)
		else:
			self._data[key] = value

	def as_dict(self) -> dict[str, Any]:
		return dict(self._data)


_NONE_ATTR_RE = re.compile(r"^'None' has no attribute '([^']+)'$")
_OBJ_ATTR_RE = re.compile(r"^'([^']+) object' has no attribute '([^']+)'$")
_VAR_UNDEFINED_RE = re.compile(r"^'([^']+)' is undefined$")


# Bis zu so vielen Empfängern wird beim Draft-Save synchron gerendert (alte UX).
# Größere Läufe laufen nur über den Hintergrund-Job (kein Save-Timeout).
AUTO_RENDER_LIMIT = 25


def _humanize_jinja_error(raw: str) -> str:
	"""Übersetzt häufige Jinja-Fehlerarten in für Hausverwalter lesbare Hinweise.

	Strict-Rendering-Fehler bestehen meist aus einer kurzen englischen
	Phrase (``'None' has no attribute 'first_name'``). Wir mappen die
	bekannten Muster auf eine Diagnose plus Hinweis, wo das Datum fehlt —
	damit klar ist, welcher Datensatz gepflegt werden muss.
	"""
	raw = raw.strip()
	m = _NONE_ATTR_RE.match(raw)
	if m:
		field = m.group(1)
		return _(
			"Feld <code>{0}</code> kann nicht gelesen werden — der vorgelagerte "
			"Datensatz ist leer. Bitte prüfen, ob z.B. <strong>Mieter</strong>, "
			"<strong>Eigentümer</strong>, <strong>Wohnung</strong> oder "
			"<strong>Mietvertrag</strong> korrekt verknüpft sind."
		).format(field)
	m = _OBJ_ATTR_RE.match(raw)
	if m:
		obj_path, field = m.group(1), m.group(2)
		# Doctype-Klassenname aus dem Modul-Pfad extrahieren
		doctype = obj_path.rsplit(".", 1)[-1] if "." in obj_path else obj_path
		# Spezialfall: ``DocType str`` heißt der Pfad ist auf einem
		# Link-Feld-String steckengeblieben — in Jinja wird ein Link-Feld
		# als Name (String) zurückgegeben, nicht als Sub-Doc. Lösung:
		# Platzhalter-Notation ``{{$ ... $}}`` nutzen, dann löst der
		# Resolver Link-Felder automatisch zu Sub-Docs auf.
		if doctype == "str":
			return _(
				"Im Vorlagen-Body wird ein Pfad geschrieben, der ein Link-Feld "
				"durchläuft (z.B. <code>objekt.wohnung.{0}</code>). Jinja kann "
				"diese Link-Felder nicht automatisch auflösen — der Wert kommt "
				"als Text-Name zurück. Lösung: den Token in Platzhalter-Notation "
				"umschreiben (<code>{{$ objekt.wohnung.{0} $}}</code>), oder "
				"das Feld als Variable mit Pfad in der Vorlage deklarieren."
			).format(field)
		return _(
			"Feld <code>{0}</code> existiert nicht im DocType "
			"<strong>{1}</strong>. Vorlage referenziert ein nicht vorhandenes "
			"Feld — bitte Vorlage korrigieren."
		).format(field, doctype)
	m = _VAR_UNDEFINED_RE.match(raw)
	if m:
		var = m.group(1)
		return _(
			"Variable <code>{0}</code> ist nicht definiert. Die Vorlage "
			"erwartet einen Wert, der vom System nicht bereitgestellt wird "
			"(Mapping-Lücke oder Tippfehler in der Vorlage)."
		).format(var)
	if raw == "Wert ist None":
		# Aus _strict_finalize: ein {{ ... }}-Ausdruck hat None zurueckgegeben.
		# Jinja gibt uns hier den Ausdruck-Text nicht — Aufrufer rendert die
		# Kandidaten-Liste aus der Fehler-Zeile dazu (siehe _render_serienbrief_template).
		return _(
			"Ein Ausdruck (<code>{{ … }}</code>) hat den Wert <code>None</code> zurückgegeben "
			"und würde sonst als Literal-Text \"None\" ins PDF rutschen. "
			"Typische Ursachen:<ul>"
			"<li>Pfad zeigt auf ein leeres DocType-Feld (z.B. <code>kunde.first_name</code> "
			"ohne Vornamen) → entweder das Feld pflegen oder den Ausdruck in "
			"<code>{% if x %}…{% endif %}</code> wrappen.</li>"
			"<li><code>baustein(\"…\")</code> findet den Baustein nicht / liefert leeres "
			"Ergebnis → Baustein-Name pruefen.</li>"
			"<li>Filter-Kette ergibt <code>None</code> (z.B. <code>x | irgendwas</code> "
			"auf einem Wert, den der Filter nicht versteht).</li>"
			"</ul>"
		)
	return frappe.utils.escape_html(raw)


_OUTPUT_EXPR_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}", re.DOTALL)


def _extract_output_expressions_on_line(source: str, lineno: int) -> list[str]:
	"""Liefert die {{ ... }}-Ausdrücke der angegebenen Zeile. Wird im
	"Wert ist None"-Pfad genutzt, damit der Autor die Kandidaten sieht, die
	den None-Wert geliefert haben könnten — Jinja gibt uns die konkrete
	Expression nicht.
	"""
	if not source or lineno < 1:
		return []
	lines = source.splitlines()
	if lineno > len(lines):
		return []
	line = lines[lineno - 1]
	# Dedupe in Reihenfolge des Vorkommens.
	seen: list[str] = []
	for match in _OUTPUT_EXPR_RE.finditer(line):
		expr = match.group(1).strip()
		if expr and expr not in seen:
			seen.append(expr)
	return seen


def _strict_finalize(value):
	"""Jinja ``finalize``-Hook: wirft, wenn ein Expression-Wert ``None`` ist.

	``StrictUndefined`` fängt nur *undefined* Variablen ab — ein DocType-Feld
	mit Wert ``None`` (z.B. ``mieter.first_name`` auf einem Customer ohne
	First-Name) ist *defined* und würde sonst als Literal ``"None"`` ins PDF
	rendern. Hier prüfen wir den finalen Output-Wert; conditional-Pfade
	(``{% if x %}``) sind nicht betroffen, weil Jinja ``finalize`` nur auf
	Expression-Outputs anwendet.
	"""
	if value is None:
		raise UndefinedError("Wert ist None")
	formatted = _format_serienbrief_number(value)
	if formatted is not None:
		return formatted
	return value


def _format_serienbrief_number(value: Any) -> str | None:
	"""Format real decimal values for German letters.

	Only floats/Decimals are formatted. Integers often represent counters, stages
	or years in templates and must remain untouched.
	"""
	if isinstance(value, bool) or not isinstance(value, (float, Decimal)):
		return None
	if isinstance(value, float) and value != value:
		return cstr(value)
	if isinstance(value, Decimal) and not value.is_finite():
		return cstr(value)
	text = f"{value:,.2f}"
	return text.replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")


def _extract_template_lineno(exc: BaseException) -> int | None:
	"""Sucht im Traceback nach Jinja's ``<template>``-Frame (``rewrite_traceback_stack``)
	und gibt die Zeilen-Nummer im gerenderten Source zurück. ``None``, wenn kein
	Template-Frame im Traceback steckt (z.B. Fehler vor dem eigentlichen Render).
	"""
	tb = exc.__traceback__
	lineno: int | None = None
	while tb is not None:
		if tb.tb_frame.f_code.co_filename == "<template>":
			lineno = tb.tb_lineno
		tb = tb.tb_next
	return lineno


def _template_snippet(source: str, lineno: int, *, context_lines: int = 2, max_line_len: int = 220) -> str:
	"""Baut ein HTML-Snippet aus ``source`` rund um ``lineno`` (1-basiert).
	Fehler-Zeile wird mit ``>>>`` markiert; Zeilen länger als ``max_line_len``
	werden gekürzt, damit lange ``<p style="...">``-Zeilen nicht das Modal sprengen.
	"""
	from frappe.utils import escape_html

	if not source or lineno < 1:
		return ""
	lines = source.splitlines()
	if lineno > len(lines):
		return ""
	start = max(0, lineno - 1 - context_lines)
	end = min(len(lines), lineno + context_lines)
	parts: list[str] = []
	for i in range(start, end):
		line_no = i + 1
		text = lines[i]
		if len(text) > max_line_len:
			text = text[: max_line_len - 1] + "…"
		marker = ">>> " if line_no == lineno else "    "
		parts.append(f"{marker}Z{line_no:>3}: {escape_html(text)}")
	return "\n".join(parts)


# Spezial-Notation für Platzhalter, die durch den Pfad-Resolver vor dem
# Jinja-Rendering aufgelöst werden: ``{{$ objekt.wohnung.immobilie.name $}}``.
# Eindeutig getrennt von Jinja-Tokens (``{{ ... }}``), die Logik, Filter und
# Variable-Referenzen enthalten — kein Heuristik-Raten mehr.
_PLACEHOLDER_TOKEN_RE = re.compile(
	r"\{\{\s*\$\s*([a-zA-Z_][\w]*(?:\[\d+\])?(?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)*)\s*\$\s*\}\}"
)
PATH_OVERRIDE_PREFIX = "__path__:"


# Einzige Quelle für die Serienbrief-PDF-Ränder — Versand (_default_pdf_options) UND
# Vorschau (serienbrief_vorlage._preview_pdf_options) nutzen diese, damit sie nicht mehr
# auseinanderlaufen können. margin-top/left bestimmen die Adressfenster-Position
# (Fensterkuvert) — nicht ohne Grund ändern. 16mm bottom: der Page-Footer
# (Bankverbindung + Pfad) ist nur ~12mm hoch, 16mm lässt 4mm Luft. Früher 25mm ->
# das reservierte ~13mm tote Reserve am Seitenende und drückte z.B. die Signatur
# unnötig auf eine zweite Seite. Sollte mit der @page-Regel in install.py konsistent
# bleiben.
SERIENBRIEF_PDF_OPTIONS: Dict[str, str] = {
	"page-size": "A4",
	"margin-top": "20mm",
	"margin-right": "20mm",
	"margin-bottom": "16mm",
	"margin-left": "25mm",
}


def get_serienbrief_pdf_options() -> Dict[str, str]:
	"""Liefert die Chrome-PDF-Optionen für den Serienbrief-Render.

	Werte stammen aus ``Serienbrief Einstellungen`` (Single) — wir lesen sie hier
	dynamisch pro Aufruf, damit Konfigurationsänderungen sofort greifen (sonst würde
	man auf einen Worker-Restart warten müssen, weil das Modul-Level-Dict einmal beim
	Import eingefroren wäre). Bei jeder Art von Fehler (DocType existiert noch nicht,
	Single noch nie gespeichert, Feld leer) fällt es auf die SERIENBRIEF_PDF_OPTIONS-
	Defaults zurück.

	Muss konsistent bleiben mit der ``@page``-CSS-Regel im Print Format (siehe
	``hausverwaltung.install._ensure_serienbrief_dokument_print_format``) — beide
	lesen dieselben Felder aus dem Single.
	"""
	opts = dict(SERIENBRIEF_PDF_OPTIONS)
	try:
		from hausverwaltung.install import get_serienbrief_margins

		m = get_serienbrief_margins()
		opts["margin-top"] = f"{m['margin_top']}mm"
		opts["margin-right"] = f"{m['margin_right']}mm"
		opts["margin-bottom"] = f"{m['margin_bottom']}mm"
		opts["margin-left"] = f"{m['margin_left']}mm"
	except Exception:
		pass
	return opts


def _preprocess_simple_paths(
	template: str,
	context: Dict[str, Any],
	*,
	on_unresolvable: "callable | None" = None,
) -> str:
	"""Löst Platzhalter-Tokens ``{{$ pfad $}}`` via :func:`_resolve_value_path`
	vor dem Jinja-Rendering auf und ersetzt sie durch den Wert.

	Damit kann der Vorlagen-Autor zwischen zwei Notationen wählen:

	* ``{{$ objekt.wohnung.immobilie.name $}}`` — **Platzhalter**, wird
	  mechanisch durch den Resolver aufgelöst; Iterationsobjekt + Variablen
	  als Roots, Link-Felder navigieren automatisch.
	* ``{{ wohnung.einheit }}`` — **Jinja**, normale Variable / Logik /
	  Filter / Conditionals; läuft durch das Jinja-Render-Environment.

	``on_unresolvable``: optionaler Fallback-Callback ``(path, exc) -> str``,
	der bei Resolver-Exception oder None statt ``frappe.throw`` aufgerufen
	wird. Im Live-Preview-Pfad wird das genutzt, um Tokens mit fehlenden
	Mock-Daten durch Beispielwerte zu ersetzen, statt die Vorschau abzubrechen.
	"""
	if not template or "$" not in template:
		return template

	def _replace(match: "re.Match[str]") -> str:
		path = match.group(1)
		override = _get_value_override(context, _path_override_key(path))
		if override is not None:
			return cstr(_display_value(override))
		try:
			value = _resolve_value_path(path, context)
		except Exception as exc:
			if on_unresolvable is not None:
				return on_unresolvable(path, exc)
			# Resolver-Exceptions (z.B. „Feld X existiert nicht im DocType str")
			# propagieren — das sind klare Pfad-Fehler, die der User sehen soll.
			raise
		if value is None:
			if on_unresolvable is not None:
				return on_unresolvable(path, None)
			frappe.throw(
				_("Platzhalter <code>{{$ {0} $}}</code> konnte nicht aufgelöst werden: der Pfad liefert <strong>None</strong>. Bitte Daten prüfen oder den Pfad korrigieren.").format(path),
				title=_("Serienbrief Fehler"),
			)
		if isinstance(value, Undefined) and on_unresolvable is not None:
			return on_unresolvable(path, None)
		# Document/Dict-ähnliches → Doc-Name (analog Frappe-Default).
		if hasattr(value, "doctype") and getattr(value, "name", None):
			return cstr(value.name)
		return cstr(_display_value(value))

	return _PLACEHOLDER_TOKEN_RE.sub(_replace, template)


def _render_serienbrief_template(template: str, context: Dict[str, Any]) -> str:
	"""Render templates for Serienbrief with clearer errors for missing fields.

	Verwendet ``StrictUndefined`` statt Frappes Default ``ChainableUndefined``,
	damit fehlende Variablen sofort als Fehler erscheinen — sonst landet
	``{{ no such element: ... }}`` als Literal-Text im gerenderten PDF.
	Zusätzlich wirft ``_strict_finalize`` bei ``None``-Werten, damit kein
	wörtliches "None" ins PDF rutscht.

	Vor dem Jinja-Rendering werden simple Pfad-Tokens via
	:func:`_preprocess_simple_paths` aufgelöst — damit funktionieren tiefe
	Pfade ohne deklarierte Variable.
	"""
	from jinja2 import StrictUndefined

	if not template:
		return ""
	if ".__" in template:
		frappe.throw(_("Illegal template"))
	# Pfad-Pre-Processing: simple {{ x.y.z }}-Tokens via Resolver auflösen.
	template = _preprocess_simple_paths(template, context)
	# Frappes get_jenv() liefert eine Environment mit ChainableUndefined.
	# Wir clonen sie + überschreiben undefined → StrictUndefined.
	jenv = get_jenv().overlay(undefined=StrictUndefined, finalize=_strict_finalize)
	try:
		return jenv.from_string(template).render(context)
	except UndefinedError as exc:
		raw = str(exc) or _("Ein benötigtes Feld fehlt.")
		human = _humanize_jinja_error(raw)
		msg = _("Fehlendes Feld im Serienbrief: {0}").format(human)
		# Vorlagen-Zeile + Snippet aus Jinja-Traceback anhängen, damit der Autor
		# sieht, welche Stelle den ``None``-Wert produziert. Jinja's
		# ``rewrite_traceback_stack`` schreibt einen Frame mit
		# ``filename='<template>'`` und ``lineno`` = Zeile im (vorverarbeiteten)
		# Source.
		lineno = _extract_template_lineno(exc)
		if lineno is not None:
			snippet = _template_snippet(template, lineno)
			if snippet:
				msg += (
					"<br/><br/>"
					+ _("Vorlagen-Zeile {0}:").format(lineno)
					+ f"<br/><pre style='white-space: pre-wrap; font-size: 0.85em; background: #f6f6f6; padding: 6px; border-radius: 3px'>{snippet}</pre>"
				)
			# Bei "Wert ist None" zusätzlich alle {{ ... }}-Ausdrücke der Fehler-Zeile
			# auflisten — Jinja gibt uns nicht, welche Expression genau None lieferte,
			# aber der Autor kann die Kandidaten dann gezielt durchgehen.
			if raw == "Wert ist None":
				candidates = _extract_output_expressions_on_line(template, lineno)
				if candidates:
					from frappe.utils import escape_html

					items = "".join(f"<li><code>{escape_html(c)}</code></li>" for c in candidates)
					msg += (
						"<br/>"
						+ _("Kandidaten in dieser Zeile (einer davon liefert None):")
						+ f"<ul style='margin-top: 4px'>{items}</ul>"
					)
		frappe.throw(title=_("Serienbrief Fehler"), msg=msg)
	except TemplateError:
		frappe.throw(
			title="Jinja Template Error",
			msg=f"<pre>{template}</pre><pre>{frappe.get_traceback()}</pre>",
		)


def _get_template_template_source(template_doc) -> str:
	content_type = (getattr(template_doc, "content_type", "") or "").strip() or "Textbaustein (Rich Text)"
	if content_type == "HTML + Jinja":
		parts = [
			cstr(getattr(template_doc, "jinja_content", "") or ""),
			cstr(getattr(template_doc, "html_content", "") or ""),
		]
		return "\n".join([p for p in parts if p.strip()])

	return sanitize_richtext_jinja_source(cstr(getattr(template_doc, "content", "")).strip())


class SerienbriefDurchlauf(Document):
	def on_update(self) -> None:
		# Draft: kleine Läufe beim Save sofort rendern (snappy, alte UX). Große Läufe
		# NICHT synchron rendern — das würde den Save minutenlang blockieren; dafür gibt
		# es jetzt den Hintergrund-Job (start_durchlauf_run / React-Viewer „Lauf starten").
		if int(getattr(self, "docstatus", 0) or 0) != 0:
			return
		# Läuft gerade ein Job? Dann nicht dazwischenfunken.
		if cstr(getattr(self, "status", "") or "") == "Läuft":
			return
		rows = getattr(self, "iteration_objekte", None) or []
		if not self.vorlage or not rows:
			return
		if len(rows) > AUTO_RENDER_LIMIT:
			return
		# strict_variables=False: der User darf noch Werte setzen, ohne beim Save zu werfen.
		self._ensure_dokumente(recreate=True, submit=False, strict_variables=False)

	def on_submit(self) -> None:
		# Finaler Snapshot: Dokumente neu erzeugen und submitten.
		self._ensure_dokumente(recreate=True, submit=True, strict_variables=True)

	def on_cancel(self) -> None:
		# Beim Cancel: verknüpfte Serienbrief Dokumente mit canceln und löschen,
		# damit sie nicht als Waisen stehen bleiben.
		self._remove_linked_dokumente()

	def on_trash(self) -> None:
		# Beim Löschen: verknüpfte Serienbrief Dokumente mit entfernen.
		self._remove_linked_dokumente()

	def _remove_linked_dokumente(
		self, only_active: bool = False, raise_on_failure: bool = False
	) -> list[str]:
		"""Entfernt verknüpfte Serienbrief Dokumente. Submitted Docs werden
		zuerst gecanceled. Gibt die Liste der Doc-Namen zurück, die NICHT
		entfernt werden konnten (Cancel-Fehler bei submitted Docs).

		``raise_on_failure``: für den Cutover-Pfad (Bug 1.11) — wenn auch nur
		EIN altes Doc nicht entfernbar ist, Exception werfen, damit der Caller
		die pending-neuen nicht aktiviert und parallele aktive Docs entstehen.
		Default ``False`` für on_cancel/on_trash (kein Datenverlust durch
		harten Abbruch, eher Doc behalten).
		"""
		filters: dict = {"durchlauf": self.name}
		if only_active:
			# Recreate-Cutover (Bug 1.11): während Recreate die pending-NEUEN
			# in Ruhe lassen — wir wollen nur die alten aktiven austauschen.
			filters["recreate_pending"] = 0
		dokumente = frappe.get_all(
			"Serienbrief Dokument",
			filters=filters,
			fields=["name", "docstatus"],
		)
		failed: list[str] = []
		for row in dokumente:
			docname = row["name"]
			if int(row.get("docstatus") or 0) == 1:
				try:
					frappe.get_doc("Serienbrief Dokument", docname).cancel()
				except Exception:
					# Cancel scheitert z.B. wenn referenzierte Buchungen submitted
					# sind. Frueher: silent pass + dann delete_doc — Datenverlust.
					# Jetzt: Log und Doc behalten, damit der User nachschauen kann.
					frappe.log_error(
						frappe.get_traceback(),
						f"_remove_linked_dokumente: Cancel von {docname!r} fehlgeschlagen — "
						"Doc wird nicht geloescht, damit nichts verloren geht.",
					)
					failed.append(docname)
					continue
			frappe.delete_doc(
				"Serienbrief Dokument",
				docname,
				force=1,
				ignore_permissions=True,
				delete_permanently=True,
			)
		if failed and raise_on_failure:
			frappe.throw(
				_(
					"{0} alte(s) Serienbrief Dokument(e) konnten nicht entfernt werden "
					"(Cancel fehlgeschlagen): {1}. Recreate abgebrochen, damit keine "
					"doppelten aktiven Dokumente entstehen."
				).format(len(failed), ", ".join(failed))
			)
		return failed

	def _cleanup_pending_dokumente(self) -> None:
		"""Räumt nur die mit recreate_pending=1 markierten NEUEN Docs des
		Recreate-Versuchs (Bug 1.11). Aktive Docs bleiben unberührt. Wird im
		Crash-Pfad und beim manuellen Reset (mark_durchlauf_failed) genutzt.
		"""
		pending = frappe.get_all(
			"Serienbrief Dokument",
			filters={"durchlauf": self.name, "recreate_pending": 1},
			fields=["name", "docstatus"],
		)
		for row in pending:
			docname = row["name"]
			if int(row.get("docstatus") or 0) == 1:
				try:
					frappe.get_doc("Serienbrief Dokument", docname).cancel()
				except Exception:
					frappe.log_error(
						frappe.get_traceback(),
						f"_cleanup_pending_dokumente: Cancel von {docname!r} fehlgeschlagen — "
						"pending-Doc bleibt liegen.",
					)
					continue
			frappe.delete_doc(
				"Serienbrief Dokument",
				docname,
				force=1,
				ignore_permissions=True,
				delete_permanently=True,
			)

	def generate_pdf_file(
		self,
		print_format: str | None = None,
		recreate_documents: bool = False,
		druck_schwarz_weiss: bool = False,
	) -> str:
		self._druck_schwarz_weiss = bool(druck_schwarz_weiss)
		submit_docs = bool(int(getattr(self, "docstatus", 0) or 0))
		# Drafts: immer neu rendern, sonst werden Variablen-Änderungen aus dem
		# Formular nicht berücksichtigt und ein veralteter gespeicherter PDF-Cache
		# der Serienbrief Dokumente landet im Merge.
		recreate = bool(recreate_documents) or not submit_docs
		dokumente = self._ensure_dokumente(
			recreate=recreate,
			submit=submit_docs,
			strict_variables=True,
		)
		pdf_bytes = self._build_merged_pdf(dokumente, print_format=print_format)
		return self._store_pdf(pdf_bytes)

	def generate_html_file(self) -> str:
		# Für Debug/Entwicklung weiterhin das gesamte HTML (alle Seiten) erzeugen.
		full_html = self._render_full_html()
		return self._store_html(full_html)

	def _ensure_dokumente(
		self,
		recreate: bool = False,
		submit: bool = False,
		strict_variables: bool = True,
		progress_cb=None,
	) -> list[str]:
		# Nur aktive (recreate_pending=0) Docs zählen für den Existing-Check.
		# pending-Docs sind unsichtbare Reste eines abgebrochenen Recreate-Versuchs
		# und werden hier wegputzt, bevor neu gestartet wird.
		existing = frappe.get_all(
			"Serienbrief Dokument",
			filters={"durchlauf": self.name, "recreate_pending": 0},
			order_by="creation asc",
			pluck="name",
		)
		if existing and not recreate:
			# Defensiver Cleanup-Pfad (Finding 4 zu Bug 1.11): pending-Reste eines
			# abgebrochenen früheren Recreate-Versuchs entsorgen, aber NUR wenn der
			# Durchlauf nicht aktiv läuft (sonst killen wir den parallelen Job).
			current_status = cstr(frappe.db.get_value("Serienbrief Durchlauf", self.name, "status") or "")
			if current_status != "Läuft":
				try:
					self._cleanup_pending_dokumente()
				except Exception:
					frappe.log_error(
						frappe.get_traceback(),
						f"_ensure_dokumente: defensiver pending-Cleanup für {self.name!r} fehlgeschlagen.",
					)
			return list(existing)

		if not recreate:
			# Keine existing, frischer Lauf — direkt erzeugen.
			self._cleanup_pending_dokumente()
			return self._create_dokumente(
				submit=submit, strict_variables=strict_variables, progress_cb=progress_cb, pending=False
			)

		# Recreate-Cutover (Bug 1.11): zuerst evtl. liegen gebliebene pending wegputzen,
		# dann NEUE Docs als pending erzeugen, damit alte aktive sichtbar bleiben bis
		# alles erfolgreich ist. Bei Crash bleibt der Durchlauf konsistent: alte
		# weiterhin sichtbar, neue unsichtbar (per Reset wegputzbar).
		self._cleanup_pending_dokumente()
		try:
			neu = self._create_dokumente(
				submit=submit, strict_variables=strict_variables, progress_cb=progress_cb, pending=True
			)
		except Exception:
			# Crash mitten in Erzeugung: angefangene pending-neue wegputzen.
			# Alte aktive sind unverändert sichtbar.
			try:
				self._cleanup_pending_dokumente()
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"_ensure_dokumente: Cleanup nach Recreate-Crash fehlgeschlagen ({self.name})",
				)
			raise

		# Erfolg: alte aktive sauber raus (Cancel-vor-Delete für submitted Docs).
		# raise_on_failure=True: wenn auch nur EIN altes Doc nicht entfernt werden
		# kann, brechen wir HIER ab und aktivieren die pending-neuen NICHT, sonst
		# entstehen parallele aktive Docs (Finding 1 zu Bug 1.11).
		try:
			self._remove_linked_dokumente(only_active=True, raise_on_failure=True)
		except Exception:
			# Pending-neue bleiben in der DB stehen (unsichtbar) — können per
			# manuellem Reset weggeputzt werden.
			raise
		# Pending-neue aktivieren.
		for name in neu:
			frappe.db.set_value(
				"Serienbrief Dokument", name, "recreate_pending", 0, update_modified=False
			)
		frappe.db.commit()
		return neu

	def _create_dokumente(
		self, *, submit: bool, strict_variables: bool = True, progress_cb=None, pending: bool = False
	) -> list[str]:
		if not self.vorlage:
			frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

		template = frappe.get_cached_doc("Serienbrief Vorlage", self.vorlage)
		iteration_doctype = self.iteration_doctype or template.get("haupt_verteil_objekt")
		if not iteration_doctype:
			frappe.throw(_("Bitte wählen Sie einen Iterations-Doctype."))
		if not self.iteration_doctype:
			self.iteration_doctype = iteration_doctype

		template_requirements = _collect_template_requirements(template, iteration_doctype)
		empfaenger_rows = self._get_empfaenger_rows()
		if not empfaenger_rows:
			frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

		has_blocks = bool(template.get("textbausteine"))
		has_content = bool(_get_template_template_source(template).strip())
		if not has_blocks and not has_content:
			frappe.throw(_("Die gewählte Vorlage enthält keinen Inhalt."))

		created: list[str] = []
		counts = {"generated": 0, "skipped": 0, "error": 0}
		total = len(empfaenger_rows)
		for idx, row in enumerate(empfaenger_rows, start=1):
			objekt = getattr(row, "iteration_objekt", None) or getattr(row, "objekt", None) or ""
			title = getattr(row, "anzeigename", None) or objekt or ""
			effective_variablen_werte = _merge_variable_values(
				self.variablen_werte, getattr(row, "_iteration_variablen_werte", None)
			)
			recipient_email = self._resolve_recipient_email(row)

			# Pro Empfänger fehlertolerant: ein Render-Fehler markiert NUR diesen
			# Empfänger als "Fehler" und bricht den Lauf nicht ab. So bekommt jedes
			# Iterations-Objekt ein Ergebnis-Dokument (Generiert/Übersprungen/Fehler).
			status = "Generiert"
			error_msg = ""
			skip_reason = ""
			pages = 0
			render_ms = 0
			page_html = ""
			pdf_bytes = None

			try:
				context = self._build_context(
					row, idx, template_requirements, template,
					total=total, strict_variables=strict_variables,
				)
				segments = self._render_template_content(template, context)
				if not segments:
					status = "Übersprungen"
					skip_reason = _("Kein Inhalt für diesen Empfänger.")
				else:
					t0 = time.monotonic()
					preview_pages = self._render_segments_preview_pages(segments)
					pdf_bytes = self._render_segments_pdf_bytes(segments)
					render_ms = int((time.monotonic() - t0) * 1000)
					if not preview_pages and not pdf_bytes:
						status = "Übersprungen"
						skip_reason = _("Render ohne Ergebnis.")
						pdf_bytes = None
					else:
						pages = len(preview_pages)
						page_html = self._wrap_html_fragment(
							"\n".join(f'<div class="serienbrief-page">{page}</div>' for page in preview_pages)
						)
			except Exception as exc:
				status = "Fehler"
				error_msg = (_humanize_jinja_error(str(exc)) or str(exc))[:1000]
				pdf_bytes = None

			doc = frappe.get_doc(
				{
					"doctype": "Serienbrief Dokument",
					"durchlauf": self.name,
					"vorlage": self.vorlage,
					"kategorie": self.kategorie,
					"iteration_doctype": iteration_doctype,
					"objekt": objekt,
					"title": title,
					"date": self.date,
					"html": page_html,
					"variablen_werte": effective_variablen_werte,
					"status": status,
					"error_msg": error_msg,
					"skip_reason": skip_reason,
					"render_ms": render_ms,
					"pages": pages,
					"recipient_email": recipient_email or "",
					# Cutover-Marker (Bug 1.11): vor dem Insert setzen, damit auch
					# submitted Docs ihre pending-Flagge tragen, ohne nachträgliches
					# Audit-relevantes set_value auf submitted Records.
					"recreate_pending": 1 if pending else 0,
				}
			)
			doc.insert(ignore_permissions=True)
			if pdf_bytes:
				file_url = self._store_document_pdf(doc, pdf_bytes)
				doc.db_set("generated_pdf_file", file_url, update_modified=False)
			# Nur erfolgreiche Dokumente submitten; Fehler/Übersprungen bleiben Draft-Historie.
			if submit and status == "Generiert" and int(getattr(doc, "docstatus", 0) or 0) == 0:
				try:
					doc.submit()
				except Exception:
					# Bewusst kein Hard-Fail des Laufs (z.B. fehlende Submit-Permission
					# soll nicht die ganze Generierung kippen). Aber: bisher silent —
					# User sah "Generiert" obwohl Brief Draft blieb. Jetzt im Error Log
					# nachvollziehbar.
					frappe.log_error(
						frappe.get_traceback(),
						f"Serienbrief Durchlauf: Submit von {doc.name!r} fehlgeschlagen — bleibt Draft.",
					)

			created.append(doc.name)
			counts[{"Generiert": "generated", "Übersprungen": "skipped", "Fehler": "error"}[status]] += 1

			if progress_cb:
				try:
					progress_cb(idx, total, counts)
				except Exception:
					pass

		# Zusammenfassung für den aufrufenden (Job-)Code; kein throw bei leerem Lauf.
		self._last_run_counts = {"total": total, **counts}
		return created

	def _build_merged_pdf(self, dokumente: list[str], print_format: str | None = None) -> bytes:
		if not dokumente:
			frappe.throw(_("Keine Serienbrief Dokumente zum Drucken."))

		format_name = cstr(print_format or "Serienbrief Dokument").strip() or "Serienbrief Dokument"
		use_print_format = frappe.db.exists("Print Format", format_name)

		merger = PdfMerger()
		appended = 0
		try:
			for docname in dokumente:
				doc = frappe.get_doc("Serienbrief Dokument", docname)
				# Fehler-/Übersprungen-Dokumente (kein Inhalt) nicht ins Sammel-PDF mergen.
				if cstr(getattr(doc, "status", "") or "") in ("Fehler", "Übersprungen"):
					continue
				has_pdf = cstr(getattr(doc, "generated_pdf_file", None) or "").strip()
				if not use_print_format and not has_pdf and not cstr(getattr(doc, "html", "") or "").strip():
					continue
				if use_print_format:
					pdf_bytes = self._render_dokument_with_print_format(doc, format_name)
				elif has_pdf:
					pdf_bytes = read_file_url_bytes(doc.generated_pdf_file)
				else:
					pdf_bytes = get_pdf(self._wrap_html(doc.html or ""), options=self._default_pdf_options())

				merger.append(BytesIO(pdf_bytes))
				appended += 1

			if not appended:
				frappe.throw(_("Keine erfolgreich generierten Dokumente zum Drucken."))

			out = BytesIO()
			merger.write(out)
			return out.getvalue()
		finally:
			try:
				merger.close()
			except Exception:
				pass

	def _render_dokument_with_print_format(self, doc, format_name: str) -> bytes:
		# Inner-Closure liefert die PDF-Bytes aus dem jeweils greifenden Render-Pfad
		# (Hybrid → Disk-Cache → frisches frappe.get_print); Post-Processing
		# (Seitenzahlen-Overlay bei multipage) passiert dann einheitlich danach,
		# damit der Versand dieselbe „Seite X von Y"-Anzeige hat wie die Editor-
		# Vorschau (vorher nur dort applied → Inkonsistenz Vorschau/Versand).
		def _raw_pdf() -> bytes:
			hybrid_pdf = self._render_dokument_hybrid_print_pdf(doc, format_name)
			if hybrid_pdf:
				return hybrid_pdf
			if (
				cstr(getattr(doc, "generated_pdf_file", None) or "").strip()
				and "hv-pdf-inline-fragment" in cstr(getattr(doc, "html", None) or "")
			):
				return read_file_url_bytes(doc.generated_pdf_file)
			return frappe.get_print(
				"Serienbrief Dokument",
				doc.name,
				print_format=format_name,
				as_pdf=True,
				pdf_options=self._default_pdf_options(),
			)

		pdf_bytes = _raw_pdf()
		from hausverwaltung.hausverwaltung.utils.pdf_page_numbers import (
			add_page_numbers_if_multipage,
		)
		# Defensiv: bei 1-Seiten-PDFs ist das ein No-Op, bei fehlenden Dependencies
		# ebenfalls — kein Render-Crash.
		return add_page_numbers_if_multipage(pdf_bytes)

	def _render_dokument_hybrid_print_pdf(self, doc, format_name: str) -> bytes | None:
		html = cstr(getattr(doc, "html", None) or "").strip()
		if not html or "hv-pdf-inline-fragment" not in html:
			return None

		snapshot_url = cstr(getattr(doc, "generated_pdf_file", None) or "").strip()
		if not snapshot_url:
			return None

		page_html_list = self._split_preview_pages_from_document_html(html)
		if not page_html_list:
			return None

		try:
			snapshot_reader = PdfReader(BytesIO(read_file_url_bytes(snapshot_url)))
		except Exception:
			return None

		total_snapshot_pages = len(snapshot_reader.pages or [])
		if total_snapshot_pages <= 0:
			return None

		page_cursor = 0
		chunks: list[bytes] = []
		base_doc = doc.as_dict()

		for page_html in page_html_list:
			if "hv-pdf-inline-fragment" in page_html:
				pdf_page_count = self._count_inline_pdf_fragment_pages(page_html)
				if page_cursor + pdf_page_count > total_snapshot_pages:
					return None
				chunks.append(
					self._extract_pdf_pages_from_reader(
						snapshot_reader,
						start_index=page_cursor,
						page_count=pdf_page_count,
					)
				)
				page_cursor += pdf_page_count
				continue

			if page_cursor >= total_snapshot_pages:
				return None

			page_doc_data = dict(base_doc)
			page_doc_data["html"] = self._wrap_html_fragment(f'<div class="serienbrief-page">{page_html}</div>')
			page_doc = frappe.get_doc(page_doc_data)
			chunks.append(
				frappe.get_print(
					"Serienbrief Dokument",
					doc.name,
					print_format=format_name,
					as_pdf=True,
					doc=page_doc,
					pdf_options=self._default_pdf_options(),
				)
			)
			page_cursor += 1

		if not chunks:
			return None
		if page_cursor != total_snapshot_pages:
			return None

		return self._merge_pdf_chunks(chunks)

	def _split_preview_pages_from_document_html(self, html: str) -> list[str]:
		source = cstr(html or "").strip()
		if not source:
			return []

		try:
			soup = BeautifulSoup(source, "html.parser")
			pages = []
			for node in soup.select(".serienbrief-root > .serienbrief-page"):
				page_inner = "".join(str(child) for child in node.contents).strip()
				if page_inner:
					pages.append(page_inner)
			if pages:
				return pages
		except Exception:
			pass

		return [source]

	def _count_inline_pdf_fragment_pages(self, page_html: str) -> int:
		try:
			soup = BeautifulSoup(cstr(page_html or ""), "html.parser")
			# Each .hv-pdf-page-image div corresponds to exactly one PDF page.
			pages = soup.select(".hv-pdf-inline-fragment .hv-pdf-page-image")
			if pages:
				return len(pages)
		except Exception:
			pass
		return 1

	def _extract_pdf_pages_from_reader(
		self,
		reader: PdfReader,
		start_index: int,
		page_count: int,
	) -> bytes:
		writer = PdfWriter()
		for page_no in range(start_index, start_index + max(0, page_count)):
			writer.add_page(reader.pages[page_no])

		out = BytesIO()
		writer.write(out)
		return out.getvalue()

	def _render_full_html(self) -> str:
		"""Render the Serienbrief for all recipients and return the full HTML."""

		if not self.vorlage:
			frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

		template = frappe.get_cached_doc("Serienbrief Vorlage", self.vorlage)
		iteration_doctype = self.iteration_doctype or template.get("haupt_verteil_objekt")
		if not iteration_doctype:
			frappe.throw(_("Bitte wählen Sie einen Iterations-Doctype."))
		if not self.iteration_doctype:
			self.iteration_doctype = iteration_doctype

		template_requirements = _collect_template_requirements(template, iteration_doctype)
		empfaenger_rows = self._get_empfaenger_rows()

		if not empfaenger_rows:
			frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

		has_blocks = bool(template.get("textbausteine"))
		has_content = bool(_get_template_template_source(template).strip())
		if not has_blocks and not has_content:
			frappe.throw(_("Die gewählte Vorlage enthält keinen Inhalt."))

		pages: list[str] = []
		total = len(empfaenger_rows)
		for idx, row in enumerate(empfaenger_rows, start=1):
			context = self._build_context(
				row,
				idx,
				template_requirements,
				template,
				total=total,
				strict_variables=False,
			)
			segments = self._render_template_content(template, context)
			if not segments:
				frappe.throw(
					_(
						"Die gewählte Vorlage liefert keinen renderbaren Inhalt. "
						"Bitte prüfen Sie die Textbausteine."
					)
				)
			for page in self._render_segments_preview_pages(segments):
				pages.append(f'<div class="serienbrief-page">{page}</div>')

		# paged_polyfill=True aktiviert paged.js in der Browser-Vorschau.
		# Damit paginiert die Vorschau real nach @page-Regeln (statt als eine
		# lange HTML-Scroll-Seite zu rendern) und stimmt mit dem späteren PDF
		# in Seitenzahl + Page-Breaks überein.
		return self._wrap_html("\n".join(pages), paged_polyfill=True)

	def _store_document_pdf(self, dokument_doc, content: bytes) -> str:
		safe_title = _scrub_value(dokument_doc.title or dokument_doc.name or "serienbrief-dokument")
		filename = f"{safe_title}-{dokument_doc.name}.pdf"
		file_path = frappe.get_site_path("public", "files", filename)
		os.makedirs(os.path.dirname(file_path), exist_ok=True)
		with open(file_path, "wb") as target:
			target.write(content)

		file_url = f"/files/{filename}"
		existing_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Serienbrief Dokument",
				"attached_to_name": dokument_doc.name,
				"file_url": file_url,
			},
			pluck="name",
		)
		for file_name in existing_files:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Serienbrief Dokument",
				"attached_to_name": dokument_doc.name,
			}
		).insert(ignore_permissions=True)

		return file_url

	def before_validate(self):
		if not getattr(self, "iteration_doctype", None):
			return

		for row in getattr(self, "iteration_objekte", []) or []:
			if not getattr(row, "iteration_doctype", None):
				row.iteration_doctype = self.iteration_doctype

	def _build_context(
		self,
		row,
		index: int,
		requirements: Dict[str, Any] | None = None,
		template=None,
		total: int | None = None,
		strict_variables: bool = True,
	) -> Dict[str, Any]:
		letter_date = self.date or today()

		iteration_doc = getattr(row, "_iteration_doc", None)
		# Virtuelle Felder über onload triggern (z.B. BK Mieter.differenz). Idempotent.
		if iteration_doc is not None:
			try:
				iteration_doc.run_method("onload")
			except Exception:
				pass
		if not getattr(row, "wohnung", None) and getattr(iteration_doc, "doctype", "") == "Wohnung":
			row.wohnung = iteration_doc.name

		wohnungs_doc = self._load_doc("Wohnung", row.wohnung)
		immobilie_doc = self._load_doc("Immobilie", getattr(wohnungs_doc, "immobilie", None))

		mieter_doc = self._load_mieter(row)
		mieter_address = self._extract_address(self._get_mieter_doctype(), row.mieter)
		immobilie_address = self._extract_immobilie_address(immobilie_doc)

		# Mieter wohnt in der gemieteten Wohnung — wenn keine eigene Adresse am
		# Customer/Mieter hinterlegt ist, ist die Wohnungs-(Immobilien-)Adresse die
		# Postanschrift. Dadurch funktioniert der Briefkopf für Mahnungen und alles
		# andere ohne Pflege einer separaten Address-Verknüpfung am Customer.
		if not mieter_address and immobilie_address:
			mieter_address = immobilie_address

		mieter_name = row.anzeigename or self._guess_person_name(mieter_doc)
		empfaenger_data = row.as_dict() if hasattr(row, "as_dict") else {}

		# Aktiven Mietvertrag als Kontext-Wurzel exponieren. Bei Mietvertrag-Iteration
		# ist das ``objekt`` selbst; bei anderen Iterations-Objekten (z.B. Dunning)
		# der via Empfänger-Auflösung gefundene Mietvertrag (row.mietvertrag). So
		# können Bausteine ``mietvertrag.mieter`` / ``mietvertrag.kunde`` /
		# ``mietvertrag.wohnung.immobilie`` auflösen, auch wenn ``objekt`` kein
		# Mietvertrag ist.
		mietvertrag_doc = (
			iteration_doc
			if getattr(iteration_doc, "doctype", "") == "Mietvertrag"
			else self._load_doc("Mietvertrag", getattr(row, "mietvertrag", None))
		)

		context = frappe._dict(
			objekt=iteration_doc,
			mietvertrag=mietvertrag_doc,
			datum=format_date(letter_date),
			datum_iso=letter_date,
			druck_schwarz_weiss=bool(getattr(self, "_druck_schwarz_weiss", False)),
			empfaenger=frappe._dict(
				empfaenger_data,
				name=getattr(row, "iteration_objekt", None) or getattr(row, "objekt", None) or "",
				anzeigename=row.anzeigename,
				mieter_name=mieter_name or "",
				strasse=mieter_address.get("street", ""),
				plz=mieter_address.get("zip", ""),
				ort=mieter_address.get("city", ""),
				plz_ort=mieter_address.get("plz_ort", ""),
				adresse=mieter_address.get("display", ""),
			),
			serienbrief=frappe._dict(
				titel=self.title,
				title=self.title,
				name=self.name,
				index=index,
				count=total if total is not None else 0,
				durchlauf_name=self.name,
				werte=frappe._dict(),
			),
			outputs=frappe._dict(),
		)

		if template:
			context["_serienbrief_value_overrides"] = _build_value_override_mapping(template, self, row)
			self._apply_template_variables(context, template)
			self._apply_serienbrief_template_variables(context, template, row)
			if strict_variables:
				self._verify_template_variables_resolved(context, template)
		return context

	def _render_template_content(self, template, context: Dict[str, Any]) -> list[Dict[str, Any]]:
		"""Render die Vorlage in Segmenten: html und pdf."""

		standard_text = _get_template_template_source(template).strip()
		content_position = cstr(getattr(template, "content_position", "")).strip() or "Nach Bausteinen"
		inline_mode = bool(
			standard_text and ("baustein(" in standard_text or "textbaustein(" in standard_text)
		)
		inline_pdf_segments: dict[str, Dict[str, Any]] = {}
		inline_re = re.compile(r"__HV_PDF_BLOCK_([A-Za-z0-9_\\-]+)__")
		block_counts: dict[str, int] = {}

		def _render_inline_textbaustein(block_name: str | None = None) -> Markup:
			name = cstr(block_name).strip()
			if not name:
				return Markup("")

			try:
				block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", name)
			except frappe.DoesNotExistError:
				return Markup("")

			block_row = next(
				(
					row
					for row in (template.get("textbausteine") or [])
					if cstr(getattr(row, "baustein", "")).strip() == block_doc.name
				),
				None,
			)
			block_key = self._get_block_key(block_doc, block_row, block_counts)
			block_context = self._build_block_context(context, block_doc, block_row, block_key)

			segment = self._render_block_segment(block_doc, block_context, wrap_html=False)
			self._publish_block_outputs(context, block_context, block_doc, block_key)
			if not segment:
				return Markup("")
			if segment.get("type") == "html":
				return Markup(segment.get("html") or "")

			token = f"__HV_PDF_BLOCK_{uuid.uuid4().hex}__"
			inline_pdf_segments[token] = segment
			return Markup(token)

		context["baustein"] = _render_inline_textbaustein
		context["textbaustein"] = _render_inline_textbaustein

		segments: list[Dict[str, Any]] = []
		def render_standard() -> None:
			if not standard_text:
				return
			rendered_standard = _render_serienbrief_template(standard_text, context)
			if inline_mode:
				last = 0
				for match in inline_re.finditer(rendered_standard):
					before = rendered_standard[last : match.start()]
					if before.strip():
						segments.append(
							{
								"type": "html",
								"html": f'<div class="serienbrief-block serienbrief-content">{before}</div>',
							}
						)
					token = match.group(0)
					pdf_segment = inline_pdf_segments.get(token)
					if pdf_segment:
						segments.append(pdf_segment)
					last = match.end()
				after = rendered_standard[last:]
				if after.strip():
					segments.append(
						{
							"type": "html",
							"html": f'<div class="serienbrief-block serienbrief-content">{after}</div>',
						}
					)
			else:
				segments.append(
					{
						"type": "html",
						"html": f'<div class="serienbrief-block serienbrief-content">{rendered_standard}</div>',
						}
					)

		if inline_mode:
			render_standard()
			return segments

		if content_position == "Vor Bausteinen":
			render_standard()

		for block_row in template.get("textbausteine") or []:
			if not getattr(block_row, "baustein", None):
				continue

			try:
				block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_row.baustein)
			except frappe.DoesNotExistError:
				frappe.throw(_("Der Textbaustein {0} existiert nicht mehr.").format(block_row.baustein))

			block_key = self._get_block_key(block_doc, block_row, block_counts)
			block_context = self._build_block_context(context, block_doc, block_row, block_key)
			segment = self._render_block_segment(block_doc, block_context)
			self._publish_block_outputs(context, block_context, block_doc, block_key)
			if segment:
				segments.append(segment)

		if content_position != "Vor Bausteinen":
			render_standard()

		return segments

	def _get_block_key(self, block_doc, block_row=None, counts: dict[str, int] | None = None) -> str:
		explicit = cstr(getattr(block_row, "baustein_key", None) or "").strip() if block_row else ""
		base = frappe.scrub(explicit or getattr(block_doc, "name", None) or "baustein") or "baustein"
		if counts is None:
			return base
		counts[base] = counts.get(base, 0) + 1
		return base if counts[base] == 1 else f"{base}_{counts[base]}"

	def _build_block_context(self, base_context: Dict[str, Any], block_doc, block_row, block_key: str) -> frappe._dict:
		# Block-Context ist strict: nur globale Werte + deklarierte Variablen.
		# ``objekt`` wird bewusst NICHT vererbt — Bausteine müssen ihre Daten
		# über Variablen + Standardpfade deklarieren. So bleibt der Body sauber
		# (``{{ kunde.X }}``, ``{{ immobilie.Y }}``) und es gibt keine versteckte
		# Magic über mehrstufige Link-Field-Pfade in Jinja.
		block_context = frappe._dict(
			datum=base_context.get("datum"),
			datum_iso=base_context.get("datum_iso"),
			druck_schwarz_weiss=bool(base_context.get("druck_schwarz_weiss")),
			empfaenger=base_context.get("empfaenger"),
			serienbrief=base_context.get("serienbrief"),
			outputs=base_context.get("outputs") or frappe._dict(),
			baustein=frappe._dict(key=block_key, name=getattr(block_doc, "name", None), title=getattr(block_doc, "title", None)),
		)
		self._apply_block_variables(block_context, base_context, block_doc, block_row)
		return block_context

	def _publish_block_outputs(
		self,
		base_context: Dict[str, Any],
		block_context: Dict[str, Any],
		block_doc,
		block_key: str,
	) -> None:
		output_defs = getattr(block_doc, "outputs", None) or block_doc.get("outputs") or []
		if not output_defs:
			return

		outputs = base_context.get("outputs")
		if outputs is None:
			outputs = frappe._dict()
			base_context["outputs"] = outputs
		if block_key not in outputs or outputs.get(block_key) is None:
			outputs[block_key] = frappe._dict()

		for output in output_defs:
			raw_key = cstr(getattr(output, "output_name", None) or getattr(output, "label", None) or "").strip()
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue
			value = self._resolve_block_output_value(output, block_context)
			if value is None:
				continue
			outputs[block_key][key] = value

	def _resolve_block_output_value(self, output, block_context: Dict[str, Any]) -> Any:
		provider = cstr(getattr(output, "provider", None) or "").strip()
		if provider:
			module_name, _, func_name = provider.rpartition(".")
			if not module_name or not func_name:
				frappe.throw(_("Ungültiger Output-Provider {0}.").format(frappe.bold(provider)))
			try:
				func = getattr(importlib.import_module(module_name), func_name)
				return func(block_context, output)
			except Exception:
				frappe.throw(
					_("Output-Provider {0} konnte nicht ausgeführt werden:<br>{1}").format(
						frappe.bold(provider), frappe.utils.escape_html(frappe.get_traceback())
					)
				)

		path = cstr(getattr(output, "value_path", None) or "").strip()
		if not path:
			return None
		return _resolve_value_path(path, block_context)

	def _render_segments_preview_html(self, segments: list[Dict[str, Any]]) -> str:
		html_parts: list[str] = []
		for segment in segments or []:
			rendered = self._render_preview_segment_html(segment)
			if rendered:
				html_parts.append(rendered)
		return "\n".join(html_parts)

	def _render_segments_preview_pages(self, segments: list[Dict[str, Any]]) -> list[str]:
		pages: list[str] = []
		html_buffer: list[str] = []

		def flush_html_buffer():
			if not html_buffer:
				return
			joined = "\n".join(html_buffer).strip()
			html_buffer.clear()
			if joined:
				pages.append(joined)

		for segment in segments or []:
			if segment.get("type") == "html":
				value = cstr(segment.get("html") or "").strip()
				if value:
					html_buffer.append(value)
				continue

			flush_html_buffer()
			rendered = self._render_preview_segment_html(segment)
			if rendered:
				pages.append(rendered)

		flush_html_buffer()
		return pages

	def _render_preview_segment_html(self, segment: Dict[str, Any]) -> str:
		if segment.get("type") == "html":
			return apply_print_saving_brand_assets(
				cstr(segment.get("html") or "").strip(),
				bool(getattr(self, "_druck_schwarz_weiss", False)),
			)

		inline_html = cstr(segment.get("preview_html") or "").strip()
		if inline_html:
			return apply_print_saving_brand_assets(
				inline_html,
				bool(getattr(self, "_druck_schwarz_weiss", False)),
			)

		title = cstr(segment.get("title") or segment.get("block") or _("PDF-Formular")).strip()
		pages = cstr(segment.get("pages_label") or "").strip()
		page_hint = f" ({pages})" if pages else ""
		return (
			f'<div class="serienbrief-pdf-placeholder" data-block="{cstr(segment.get("block") or "")}">'
			f'{_("PDF-Formular")}: {frappe.utils.escape_html(title)}{frappe.utils.escape_html(page_hint)}</div>'
		)

	def _render_segments_pdf_bytes(self, segments: list[Dict[str, Any]]) -> bytes:
		pdf_chunks: list[bytes] = []
		html_buffer: list[str] = []

		def flush_html_buffer():
			if not html_buffer:
				return
			joined = "\n".join(html_buffer).strip()
			html_buffer.clear()
			if not joined:
				return
			page_html = self._wrap_html(f'<div class="serienbrief-page">{joined}</div>')
			pdf_chunks.append(get_pdf(page_html, options=self._default_pdf_options()))

		for segment in segments or []:
			if segment.get("type") == "html":
				value = apply_print_saving_brand_assets(
					cstr(segment.get("html") or "").strip(),
					bool(getattr(self, "_druck_schwarz_weiss", False)),
				)
				if value:
					html_buffer.append(value)
				continue

			pdf_bytes = segment.get("pdf_bytes")
			if not pdf_bytes:
				continue
			flush_html_buffer()
			pdf_chunks.append(pdf_bytes)

		flush_html_buffer()
		return self._merge_pdf_chunks(pdf_chunks)

	def _merge_pdf_chunks(self, chunks: list[bytes]) -> bytes:
		if not chunks:
			return b""
		merger = PdfMerger()
		try:
			for chunk in chunks:
				if not chunk:
					continue
				merger.append(BytesIO(chunk))
			out = BytesIO()
			merger.write(out)
			return out.getvalue()
		finally:
			try:
				merger.close()
			except Exception:
				pass

	def _render_block_segment(
		self,
		block_doc,
		context: Dict[str, Any],
		*,
		wrap_html: bool = True,
	) -> Dict[str, Any] | None:
		content_type = cstr(getattr(block_doc, "content_type", None) or "").strip() or "Textbaustein (Rich Text)"
		if content_type == "PDF Formular":
			pdf_bytes = render_pdf_form_block(block_doc, context, _resolve_value_path)
			preview_html = render_pdf_bytes_as_html_fragment(pdf_bytes)
			return {
				"type": "pdf",
				"block": cstr(getattr(block_doc, "name", None) or ""),
				"title": cstr(getattr(block_doc, "title", None) or getattr(block_doc, "name", None) or ""),
				"pages_label": cstr(getattr(block_doc, "pdf_pages", None) or _("alle Seiten")),
				"pdf_bytes": pdf_bytes,
				"preview_html": preview_html,
			}

		rendered = self._render_block_html(block_doc, context)
		if not rendered:
			return None
		html = (
			f'<div class="serienbrief-block" data-block="{cstr(block_doc.name)}">{rendered}</div>'
			if wrap_html
			else rendered
		)
		return {
			"type": "html",
			"block": cstr(getattr(block_doc, "name", None) or ""),
			"title": cstr(getattr(block_doc, "title", None) or getattr(block_doc, "name", None) or ""),
			"html": html,
		}

	def _render_block_html(self, block_doc, context: Dict[str, Any]) -> str:
		template_source = sanitize_richtext_jinja_source(self._get_block_template_source(block_doc).strip())
		if not template_source:
			return ""

		try:
			return _render_serienbrief_template(template_source, context)
		except Exception as exc:
			block_title = getattr(block_doc, "title", None) or getattr(block_doc, "name", None) or _("Textbaustein")
			message = _("Fehler beim Rendern des Textbausteins {0}: {1}").format(
				frappe.bold(block_title),
				frappe.utils.escape_html(str(exc)),
			)
			if "not iterable" in str(exc):
				message += "<br><br>" + _(
					"Hinweis: Im Jinja-Template wird vermutlich über ein einzelnes Dokument iteriert "
					"(z.B. `{% for x in kontakt %}`), obwohl `kontakt` nur ein einzelnes Doc ist."
				)
			frappe.throw(message)

	def _get_block_template_source(self, block_doc) -> str:
		content_type = (block_doc.content_type or "").strip() or "Textbaustein (Rich Text)"
		if content_type == "PDF Formular":
			return ""
		if content_type == "HTML + Jinja":
			parts = [
				block_doc.jinja_content or "",
				block_doc.html_content or "",
			]
			return "\n".join([p for p in parts if p and p.strip()])

		return block_doc.text_content or ""

	def _get_inline_baustein_pfade(self) -> dict:
		"""Pro-Baustein Input-Pfad-Overrides der Vorlage (vom Serienbrief-Editor gesetzt),
		gecached. Greift für inline eingefügte Bausteine, die keine Listen-Zeile haben."""
		cached = getattr(self, "_inline_bp_cache", None)
		if cached is not None:
			return cached
		data: dict = {}
		if getattr(self, "vorlage", None):
			try:
				tpl = frappe.get_cached_doc("Serienbrief Vorlage", self.vorlage)
				parsed = frappe.parse_json(tpl.get("inline_baustein_pfade") or "{}")
				if isinstance(parsed, dict):
					data = parsed
			except Exception:
				data = {}
		self._inline_bp_cache = data
		return data

	def _get_inline_baustein_werte(self) -> dict:
		"""Pro-Baustein Werte (Text / Bool) der Vorlage, gecached. Spiegel zu
		_get_inline_baustein_pfade — selbes Storage-Schema ({Baustein: {Variable: Wert}}),
		aber für nicht-Doctype-Variablen."""
		cached = getattr(self, "_inline_bv_cache", None)
		if cached is not None:
			return cached
		data: dict = {}
		if getattr(self, "vorlage", None):
			try:
				tpl = frappe.get_cached_doc("Serienbrief Vorlage", self.vorlage)
				parsed = frappe.parse_json(tpl.get("inline_baustein_werte") or "{}")
				if isinstance(parsed, dict):
					data = parsed
			except Exception:
				data = {}
		self._inline_bv_cache = data
		return data

	def _apply_block_variables(self, context: Dict[str, Any], base_context: Dict[str, Any], block_doc, block_row) -> None:
		variable_defs = block_doc.get("variables") or []
		if not variable_defs:
			return

		block_title = block_doc.title or block_doc.name
		value_mapping = _parse_variable_values(getattr(block_row, "variablen_werte", None))
		# Listen-Zeilen-Override (falls vorhanden) + inline-Override aus der Vorlage (Editor).
		# Inline-Override gewinnt, da der neue Editor inline arbeitet.
		inline_override = self._get_inline_baustein_pfade().get(getattr(block_doc, "name", "")) or {}
		path_mapping = {
			**_parse_mapping(getattr(block_row, "pfad_zuordnung", None)),
			**(inline_override if isinstance(inline_override, dict) else {}),
		}
		# Werte (Text/Bool) für inline-Bausteine — vom Editor pro Baustein-Vorkommen
		# gepflegt. Wird unten als Override für ``value`` benutzt; greift, wenn keine
		# Werte über die alte block_row.variablen_werte-Tabelle gepflegt sind.
		inline_value_override = self._get_inline_baustein_werte().get(
			getattr(block_doc, "name", ""),
		) or {}
		if not isinstance(inline_value_override, dict):
			inline_value_override = {}
		# Default-Pfade aus ``block_doc.standardpfade`` für den aktuellen
		# Iterations-Doctype. Damit kann ein Baustein einmal pro Iterations-
		# Doctype einen Standard hinterlegen, statt dass jede einbettende
		# Vorlage ihn manuell setzen muss.
		iteration_doctype = cstr(getattr(self, "iteration_doctype", None) or "").strip()
		default_paths: dict[str, str] = (
			_get_block_default_path_map(block_doc, iteration_doctype) if iteration_doctype else {}
		)
		missing: list[str] = []

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			entry = value_mapping.get(key) or {}
			path = cstr(entry.get("path") or "").strip()
			value = entry.get("value")
			# Inline-Override aus dem Editor schlägt block_row.variablen_werte. Auch
			# falsy-Werte (False, 0, "") sind hier gültige Überschreibungen, daher kein
			# truthiness-Check, sondern explizit „Key vorhanden".
			if key in inline_value_override:
				value = inline_value_override[key]
			elif raw_key in inline_value_override:
				value = inline_value_override[raw_key]
			if variable_type not in ("Text", "Bool"):
				path = (
					cstr(path_mapping.get(key) or "").strip()
					or cstr(path_mapping.get(raw_key) or "").strip()
					or cstr(path_mapping.get(getattr(variable, "reference_doctype", None)) or "").strip()
					or cstr(default_paths.get(key) or "").strip()
					or cstr(default_paths.get(raw_key) or "").strip()
					or cstr(default_paths.get(getattr(variable, "reference_doctype", None)) or "").strip()
					or ("__self__" if iteration_doctype == cstr(getattr(variable, "reference_doctype", None) or "").strip() else key)
				)

			resolved = None
			path_was_set = bool(path)
			if path:
				# Pfade werden gegen den Parent-Context (mit ``objekt``)
				# aufgelöst, nicht gegen den strict Block-Context.
				resolved = _resolve_value_path(path, base_context)
			# Bewusst gesetzter Leer-String ("") ist ein gültiger Wert (optionale
			# Baustein-Variable, vom User absichtlich leer gelassen). Nur echtes
			# ``None`` (= Key überhaupt nicht im Override) zählt als „fehlt".
			# Inline-/Listen-``value`` ist der Fallback, wenn der Pfad nichts liefert.
			if resolved is None and value is not None:
				resolved = value

			resolved = _coerce_bool_if_needed(resolved, variable_type)

			# Optional-Flag auf der Variable: kein Vorlagenfehler bei fehlendem Wert.
			# Stattdessen wird leerer String ins Context gesetzt, sodass Jinja
			# StrictUndefined nicht crasht und die Vorlage `{% if X %}` ohne
			# Wert sauber den else-Branch nimmt.
			is_optional = bool(int(getattr(variable, "optional", 0) or 0))

			if resolved is None:
				if context.get(key) is None:
					if is_optional:
						context[key] = ""
						continue
					# Pfad war gesetzt aber resolved=None UND kein value-Fallback:
					# präzise Pfad-Meldung statt generische missing-Liste.
					if path_was_set:
						frappe.throw(
							_("Pfad {0} für Variable {1} im Baustein {2} konnte nicht aufgelöst werden.").format(
								frappe.bold(path), frappe.bold(raw_key or key), frappe.bold(block_title)
							)
						)
					label = getattr(variable, "label", None) or raw_key or key
					missing.append(f"{label} (<code>{{{{ {key} }}}}</code>)")
				continue

			context[key] = resolved

			if "inputs" not in context["baustein"]:
				context["baustein"]["inputs"] = {}
			context["baustein"]["inputs"][key] = resolved

		if missing:
			frappe.throw(
				_(
					"Im Baustein {0} fehlen Werte für folgende Variablen:<br>{1}<br><br>"
					"Hinweis: Im Vorlagen-Formular unter „Feldpfade & Variablen“ den Baustein auswählen "
					"und pro Variable einen Festwert oder Pfad hinterlegen, oder eine gleichnamige "
					"Vorlagen-Variable mit Wert setzen."
				).format(frappe.bold(block_title), "<br>".join(missing))
			)

	def _apply_template_variables(self, context: Dict[str, Any], template) -> None:
		variable_defs = template.get("variables") or []
		if not variable_defs:
			return

		template_title = template.title or template.name
		mapping = _parse_variable_values(getattr(template, "variablen_werte", None))
		path_mapping = _parse_mapping(getattr(template, "pfad_zuordnung", None))

		iteration_doctype = cstr(getattr(self, "iteration_doctype", None) or "").strip()

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			is_text_like = variable_type in {"String", "Zahl", "Bool", "Datum", "Text"}

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			entry = mapping.get(key) or {}
			path = cstr(entry.get("path") or "").strip()
			value = entry.get("value")
			if not is_text_like:
				# Doctype / Doctype Liste: Pfad analog zu Bausteinen
				path = (
					cstr(path_mapping.get(key) or "").strip()
					or cstr(path_mapping.get(raw_key) or "").strip()
					or cstr(path_mapping.get(getattr(variable, "reference_doctype", None)) or "").strip()
					or ("__self__" if iteration_doctype == cstr(getattr(variable, "reference_doctype", None) or "").strip() else "")
				)

			resolved = None
			if path:
				resolved = _resolve_value_path(path, context)
				if resolved is None:
					frappe.throw(
						_("Pfad {0} für Variable {1} in der Vorlage {2} konnte nicht aufgelöst werden.").format(
							frappe.bold(path), frappe.bold(raw_key or key), frappe.bold(template_title)
						)
					)
			# Bewusst gesetzter Leer-String ist gültiger Wert; nur echtes ``None`` zählt als fehlend.
			if resolved is None and value is not None:
				resolved = value

			resolved = _coerce_bool_if_needed(resolved, variable_type)

			if resolved is None:
				# Optional + nicht resolved: leeren String ablegen, damit
				# StrictUndefined in ``{% if X %}`` nicht crasht. Wichtig auch im
				# strict_variables=False-Pfad (Editor-Live-Preview mit Empfaenger),
				# wo _verify_template_variables_resolved nicht laeuft.
				# Ein nachfolgender _apply_serienbrief_template_variables-Lauf
				# kann das "" jederzeit mit einem echten Wert ueberschreiben.
				is_optional = bool(int(getattr(variable, "optional", 0) or 0))
				if is_optional and context.get(key) is None:
					context[key] = ""
				# Sonst: Variable bleibt unresolved; verify (sofern aktiv) wirft strict.
				continue

			# Alle Vorlagen-Variablen top-level — passt zur Editor-Konvention
			# (Sidebar fügt bare ``{{ key }}`` ein), keine getrennten Namespaces.
			context[key] = resolved

	def _apply_serienbrief_template_variables(
		self, context: Dict[str, Any], template, row=None
	) -> None:
		variable_defs = template.get("variables") or []
		if not variable_defs:
			return

		durchlauf_mapping = _parse_variable_values(getattr(self, "variablen_werte", None))
		row_mapping = _parse_variable_values(getattr(row, "_iteration_variablen_werte", None))
		if not durchlauf_mapping and not row_mapping:
			return

		for variable in variable_defs:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			is_text_like = variable_type in {"String", "Zahl", "Bool", "Datum", "Text"}

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			# Row-Override hat Vorrang vor dem Durchlauf-Default.
			entry = row_mapping.get(key) or durchlauf_mapping.get(key) or {}
			path = cstr(entry.get("path") or "").strip()
			value = entry.get("value")

			resolved = None
			if path:
				resolved = _resolve_value_path(path, context)
				if resolved is None:
					frappe.throw(
						_("Pfad {0} für Variable {1} im Serienbrief konnte nicht aufgelöst werden.").format(
							frappe.bold(path), frappe.bold(raw_key or key)
						)
					)
			# Bewusst gesetzter Leer-String ist gültiger Wert; nur echtes ``None`` zählt als fehlend.
			if resolved is None and value is not None:
				resolved = value

			resolved = _coerce_bool_if_needed(resolved, variable_type)

			if resolved is None:
				continue

			context[key] = resolved

	def _verify_template_variables_resolved(self, context: Dict[str, Any], template) -> None:
		variable_defs = template.get("variables") or []
		if not variable_defs:
			return

		template_title = template.title or template.name
		missing: list[str] = []

		for variable in variable_defs:
			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			# Alle Vorlagen-Variablen liegen jetzt top-level — Editor schreibt
			# bare ``{{ key }}``-Tokens, also einheitlich dort lesen.
			if context.get(key) is not None:
				continue

			# Optional-Flag: leerer String ins Context, damit StrictUndefined
			# nicht crasht und ``{% if x %}`` sauber den else-Branch nimmt.
			is_optional = bool(int(getattr(variable, "optional", 0) or 0))
			if is_optional:
				context[key] = ""
				continue

			label = getattr(variable, "label", None) or raw_key or key
			missing.append(f"{label} (<code>{{{{ {key} }}}}</code>)")

		if missing:
			frappe.throw(
				_(
					"In der Vorlage {0} fehlen Werte für folgende Variablen:<br>{1}<br><br>"
					"Hinweis: Im Vorlagen-Formular unter „Feldpfade & Variablen“ → „Vorlage“ pro "
					"Variable einen Festwert oder Pfad hinterlegen, oder im Serienbrief Durchlauf "
					"unter „Variablen“ einen Wert setzen."
				).format(frappe.bold(template_title), "<br>".join(missing))
			)

	def _default_css(self) -> str:
		custom_css = (get_serienbrief_font_face_css() + """
			@page {
				size: A4;
				/* Synchron mit install.py und _default_pdf_options. */
				margin: 20mm 20mm 16mm 25mm;
			}
			body,
			.serienbrief-root,
			.print-format,
			.print-format .serienbrief-root {
				font-family: __HV_SERIENBRIEF_FONT_FAMILY__;
				color: #222;
				font-size: 11pt !important;
				line-height: 1.35;
			}
			/* Serienbrief: Briefkopf-Layout (Inhalt liefert nur Klassen; Layout kommt aus CSS) */
			.sb-letterhead {
				margin-top: 0.7cm;
			}
			.sb-address-window {
				float: left;
				width: 60%;
				padding-top: 3.2cm;
				font-size: 10pt;
				box-sizing: border-box;
			}
			.sb-return-address {
				font-size: 7pt;
				text-decoration: underline;
				margin-bottom: 0.15cm;
			}
			.sb-sender {
				float: right;
				width: 40%;
				text-align: right;
				font-size: 9pt;
				box-sizing: border-box;
			}
			.sb-office-hours {
				font-size: 7.5pt;
				margin-top: 0.15cm;
			}
			.sb-letterhead:after {
				content: "";
				display: block;
				clear: both;
			}
			.sb-date {
				margin-top: 0.5cm;
				text-align: right;
			}
			.print-format {
				margin: 0 !important;
				padding: 0 !important;
				width: 100% !important;
				max-width: 100% !important;
				box-sizing: border-box;
			}
			.serienbrief-page {
				page-break-after: always;
				padding: 0;
			}
			.serienbrief-page:last-child {
				page-break-after: auto;
			}
			.serienbrief-page p {
				/* Kein Default-margin — siehe install.py (gleiches Stylesheet
				   wird beim ensure_serienbrief_print_format auch in der DB
				   gespeichert). Direkt aufeinanderfolgende <p> rendern kompakt;
				   Leerzeilen kommen durch <p>&nbsp;</p> zustande (line-height). */
				margin: 0;
				line-height: 1.35;
			}
			.serienbrief-block {
				margin-bottom: 12px;
			}
			.serienbrief-block:last-child {
				margin-bottom: 0;
			}
			.serienbrief-pdf-placeholder {
				border: 1px dashed #999;
				background: #f6f6f6;
				color: #444;
				padding: 8px 10px;
				margin: 10px 0;
				font-size: 9.5pt;
			}
		""").replace("__HV_SERIENBRIEF_FONT_FAMILY__", serienbrief_font_family())
		return custom_css

	def _default_pdf_options(self) -> dict[str, str]:
		# EINE gemeinsame Quelle für Versand UND Vorschau, damit beide nicht
		# auseinanderlaufen. Werte stammen jetzt aus ``Serienbrief Einstellungen``
		# (Single) — siehe ``get_serienbrief_pdf_options``. Fallback bei Fehler
		# auf die SERIENBRIEF_PDF_OPTIONS-Hardcodes.
		return get_serienbrief_pdf_options()

	def _wrap_html_fragment(self, body_html: str) -> str:
		return f'<div class="serienbrief-root">{body_html}</div>'

	def _wrap_html(self, body_html: str, paged_polyfill: bool = False) -> str:
		# paged_polyfill: nur in Browser-Previews aktivieren, NICHT in der
		# Chrome-PDF-Pipeline — Chrome paginiert nativ via @page, paged.js
		# würde dort doppelt paginieren oder das Layout durcheinanderbringen.
		paged_script = (
			'<script src="/assets/hausverwaltung/js/lib/paged.polyfill.js" defer></script>'
			if paged_polyfill
			else ""
		)
		return f"""<!DOCTYPE html>
<html>
	<head>
		<meta charset="utf-8">
		<style>{self._default_css()}</style>
		{paged_script}
	</head>
	<body>
		{body_html}
	</body>
</html>"""

	def _store_pdf(self, content: bytes) -> str:
		safe_title = _scrub_value(self.title or "serienbrief")
		filename = f"{safe_title}-{self.name}.pdf"
		file_path = frappe.get_site_path("public", "files", filename)
		os.makedirs(os.path.dirname(file_path), exist_ok=True)

		with open(file_path, "wb") as target:
			target.write(content)

		file_url = f"/files/{filename}"
		existing_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
				"file_url": file_url,
			},
			pluck="name",
		)
		for file_name in existing_files:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
			}
		).insert(ignore_permissions=True)

		return file_url

	def _store_html(self, content: str) -> str:
		safe_title = _scrub_value(self.title or "serienbrief")
		filename = f"{safe_title}-{self.name}.html"
		file_path = frappe.get_site_path("public", "files", filename)
		os.makedirs(os.path.dirname(file_path), exist_ok=True)

		with open(file_path, "w", encoding="utf-8") as target:
			target.write(content)

		file_url = f"/files/{filename}"
		existing_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
				"file_url": file_url,
			},
			pluck="name",
		)
		for file_name in existing_files:
			frappe.delete_doc("File", file_name, force=1, ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Serienbrief Durchlauf",
				"attached_to_name": self.name,
			}
		).insert(ignore_permissions=True)

		return file_url

	def _get_empfaenger_rows(self) -> list[Any]:
		rows: list[Any] = []
		for iteration_row in getattr(self, "iteration_objekte", []) or []:
			row = self._build_empfaenger_row_from_iteration(iteration_row)
			if row:
				rows.append(row)

		return rows

	def _build_empfaenger_row_from_iteration(self, iteration_row):
		iteration_doctype = getattr(iteration_row, "iteration_doctype", None) or self.iteration_doctype
		if not iteration_doctype or not getattr(iteration_row, "objekt", None):
			return None

		iteration_doc = self._load_doc(iteration_doctype, iteration_row.objekt)
		if not iteration_doc:
			return None

		iteration_meta = frappe.get_meta(iteration_doctype)
		link_fields = [df for df in iteration_meta.fields if df.fieldtype == "Link" and df.options]
		link_map = self._get_iteration_link_field_map(iteration_doctype)

		row_data: dict[str, Any] = {
			"iteration_doctype": iteration_doctype,
			"iteration_objekt": iteration_doc.name,
		}

		target_field = link_map.get(iteration_doctype)
		if target_field:
			row_data[target_field] = iteration_doc.name

		# Fallback: wenn Iterations-Objekt direkt eine Wohnung ist
		if iteration_doctype == "Wohnung" and not row_data.get("wohnung"):
			row_data["wohnung"] = iteration_doc.name

		for df in link_fields:
			value = getattr(iteration_doc, df.fieldname, None)
			if value:
				row_data.setdefault(df.fieldname, value)

		# Mietvertrag-Name merken, damit wir die Mieter-Tabelle (Vertragspartner →
		# Contact) für den Anzeigenamen heranziehen können.
		mietvertrag_name: str | None = None
		if iteration_doctype == "Mietvertrag":
			mietvertrag_name = iteration_doc.name

		# When the iteration doc only knows about a Customer (e.g. Dunning) but
		# not the Mieter/Wohnung directly, derive both via the active Mietvertrag.
		# Without this, mieter/immobilie context vars stay empty and any letterhead
		# block that wants to show the recipient address renders blank.
		if not row_data.get("mieter") or not row_data.get("wohnung"):
			customer_name = (
				getattr(iteration_doc, "kunde", None)
				or getattr(iteration_doc, "customer", None)
				or getattr(iteration_doc, "debitor", None)
			)
			if customer_name and frappe.db.exists("DocType", "Mietvertrag"):
				try:
					mv = frappe.db.sql(
						"""
						SELECT name, wohnung FROM `tabMietvertrag`
						WHERE kunde = %(kunde)s
						  AND (von IS NULL OR von <= CURDATE())
						  AND (bis IS NULL OR bis >= CURDATE())
						ORDER BY COALESCE(von, '1900-01-01') DESC
						LIMIT 1
						""",
						{"kunde": customer_name},
						as_dict=True,
					)
					if not mv:
						# Schluss-Mahnung: Mieter bereits ausgezogen (bis < CURDATE).
						# Fallback auf zuletzt gueltigen MV des Kunden, dessen von
						# schon erreicht war (zukuenftige Vertraege ausgeschlossen).
						mv = frappe.db.sql(
							"""
							SELECT name, wohnung FROM `tabMietvertrag`
							WHERE kunde = %(kunde)s
							  AND (von IS NULL OR von <= CURDATE())
							ORDER BY COALESCE(bis, '9999-12-31') DESC,
							         COALESCE(von, '1900-01-01') DESC
							LIMIT 1
							""",
							{"kunde": customer_name},
							as_dict=True,
						)
				except Exception:
					mv = []
				if mv:
					row_data.setdefault("wohnung", mv[0].get("wohnung"))
					if not mietvertrag_name:
						mietvertrag_name = mv[0].get("name")
				row_data.setdefault("mieter", customer_name)

		# Bevorzugter Anzeigename: aus der Mieter-Tabelle des Mietvertrags
		# (Vertragspartner → Contact). Nur wenn die leer ist, fällt es auf die
		# Doc-Felder bzw. den technischen Mietvertrag-Namen zurück.
		display_name = self._resolve_mieter_names_from_vertrag(mietvertrag_name)
		if not display_name:
			display_name = (
				getattr(iteration_doc, "anzeigename", None)
				or getattr(iteration_doc, "title", None)
				or getattr(iteration_doc, "customer_name", None)
				or getattr(iteration_doc, "kunden_name", None)
				or getattr(iteration_doc, "name", None)
			)
		if display_name:
			row_data["anzeigename"] = display_name

		# Aktiven Mietvertrag am Row festhalten, damit _build_context ihn als
		# Kontext-Wurzel ``mietvertrag`` bereitstellen kann. Nötig für Iterationen
		# über Objekte ohne direkten Mieter-/Wohnungsbezug (z.B. Dunning): die
		# Bausteine (Briefkopf, Anrede, Bankverbindung) lösen ihre Daten dann über
		# ``mietvertrag.…`` statt ``objekt.…`` auf.
		if mietvertrag_name:
			row_data["mietvertrag"] = mietvertrag_name

		row = _IterationEmpfaengerRow(row_data)
		row._iteration_doc = iteration_doc
		row._iteration_rowname = getattr(iteration_row, "name", None)
		row._iteration_variablen_werte = getattr(iteration_row, "variablen_werte", None)

		# Dunning-getriebene Durchläufe: die pro Mahnstufe am Dunning Type
		# gepflegten Variablenwerte als Basis in den Pro-Empfänger-Override mergen.
		# Explizite Pro-Objekt-Overrides am Durchlauf gewinnen weiterhin. Nicht in
		# der Vorlage deklarierte Keys werden vom Variablen-Resolver ignoriert,
		# brechen also alte Vorlagen nicht.
		if getattr(iteration_doc, "doctype", None) == "Dunning":
			from hausverwaltung.hausverwaltung.doctype.dunning import collect_serienbrief_werte

			auto_werte = _collect_dunning_auto_values(iteration_doc)
			type_werte = collect_serienbrief_werte(iteration_doc)
			base_werte = _merge_variable_values(
				json.dumps(auto_werte) if auto_werte else None,
				json.dumps(type_werte) if type_werte else None,
			)
			if base_werte:
				row._iteration_variablen_werte = _merge_variable_values(
					base_werte, row._iteration_variablen_werte
				)

		return row

	def _get_iteration_link_field_map(self, iteration_doctype: str | None = None) -> Dict[str, str]:
		if iteration_doctype and hasattr(self, "_iteration_link_field_map_cache"):
			cache = getattr(self, "_iteration_link_field_map_cache")  # type: ignore[attr-defined]
			if cache.get("_doctype") == iteration_doctype:
				return cache.get("mapping", {})

		if not iteration_doctype:
			iteration_doctype = self.iteration_doctype
		if not iteration_doctype:
			return {}

		meta = frappe.get_meta(iteration_doctype)
		mapping = {cstr(df.options): df.fieldname for df in meta.fields if df.fieldtype == "Link" and df.options}
		self._iteration_link_field_map_cache = {"_doctype": iteration_doctype, "mapping": mapping}  # type: ignore[attr-defined]
		return mapping

	def _load_mieter(self, row):
		if not row.mieter:
			return None

		mieter_doctype = self._get_mieter_doctype()
		# `frappe.get_doc` ruft bei DoesNotExist intern `frappe.throw` →
		# `msgprint` auf, was eine Toast-Nachricht in die Response einfügt
		# (auch wenn die Exception danach gefangen wird). Daher Existenz vorher
		# explizit prüfen, damit kein "X Y nicht gefunden"-Popup leakt.
		if not frappe.db.exists(mieter_doctype, row.mieter):
			return None
		try:
			return frappe.get_doc(mieter_doctype, row.mieter)
		except frappe.DoesNotExistError:
			return None

	def _resolve_recipient_email(self, row) -> str:
		"""Best-effort Empfänger-E-Mail (in Phase 1 nur Anzeige/„hat E-Mail"). Versucht
		den Mieter-Doc und einen über den Kunden verknüpften Contact; '' wenn nichts da."""
		try:
			mieter = self._load_mieter(row)
			if mieter:
				for field in ("email_id", "email", "e_mail", "email_address"):
					val = cstr(getattr(mieter, field, "") or "").strip()
					if val:
						return val
			doc = getattr(row, "_iteration_doc", None)
			customer = cstr(
				(getattr(doc, "kunde", None) or getattr(doc, "customer", None) or "") if doc else ""
			).strip()
			if customer and frappe.db.exists("DocType", "Contact"):
				email = frappe.db.sql(
					"""
					select coalesce(c.email_id, '') from `tabContact` c
					join `tabDynamic Link` dl on dl.parent = c.name and dl.parenttype = 'Contact'
					where dl.link_doctype = 'Customer' and dl.link_name = %s
					  and coalesce(c.email_id, '') != ''
					limit 1
					""",
					(customer,),
				)
				if email:
					return cstr(email[0][0] or "").strip()
		except Exception:
			pass
		return ""

	def _format_recipient_address(self, row) -> str:
		"""Kurze Adress-/Objekt-Zeile für die Empfängerliste (best-effort, '' bei Fehlern)."""
		try:
			wohnung = cstr(getattr(row, "wohnung", "") or "").strip()
			if wohnung and frappe.db.exists("Wohnung", wohnung):
				bez = cstr(frappe.db.get_value("Wohnung", wohnung, "bezeichnung") or wohnung)
				imm = frappe.db.get_value("Wohnung", wohnung, "immobilie")
				imm_bez = cstr(frappe.db.get_value("Immobilie", imm, "bezeichnung") or "") if imm else ""
				return " · ".join([p for p in (bez, imm_bez) if p])
		except Exception:
			pass
		return ""

	def _load_doc(self, doctype: str, name: str | None):
		if not name:
			return None
		# Existenz-Check vor get_doc, sonst leakt frappe.throw eine msgprint-
		# Toast in die Response (siehe Kommentar in _load_mieter).
		if not frappe.db.exists(doctype, name):
			return None
		try:
			doc = frappe.get_doc(doctype, name)
		except frappe.DoesNotExistError:
			return None
		# ``onload`` füllt virtuelle Felder (z.B. ``Betriebskostenabrechnung
		# Mieter.differenz``) — Frappe's get_doc ruft onload nur in UI-Pfaden
		# auf, deswegen hier explizit triggern, sonst fehlen die berechneten
		# Werte beim Render.
		try:
			doc.run_method("onload")
		except Exception:
			pass
		return doc

	def _get_mieter_doctype(self) -> str:
		if hasattr(self, "_mieter_doctype_cache"):
			return self._mieter_doctype_cache  # type: ignore[attr-defined]

		target = ""
		if self.iteration_doctype:
			try:
				meta = frappe.get_meta(self.iteration_doctype)
				field = meta.get_field("mieter")
				if field and field.options:
					# Tabellen-Feld (z.B. Mietvertrag.mieter → Vertragspartner) ist
					# NICHT der Doctype, der in row.mieter landet — dort steht der
					# Customer-Docname (siehe row_data.setdefault("mieter", customer_name)
					# in _build_iteration_empfaenger_row). Daher bei Tabellen-Feldern
					# auf den Customer/Mieter-Doctype zurückfallen.
					if field.fieldtype == "Link":
						target = field.options
			except Exception:
				pass

		# Fallback: bei Iteration-Doctypes ohne direktes Link-Feld `mieter`
		# (Mietvertrag, Dunning, Sales Invoice, …) ist der Empfänger der
		# Customer/Debitor — wir bevorzugen das Legacy-DocType "Mieter" wenn
		# installiert, sonst "Customer".
		if not target:
			if frappe.db.exists("DocType", "Mieter"):
				target = "Mieter"
			else:
				target = "Customer"

		self._mieter_doctype_cache = target  # type: ignore[attr-defined]
		return self._mieter_doctype_cache  # type: ignore[attr-defined]

	def _extract_address(self, link_doctype: str | None, link_name: str | None) -> Dict[str, str]:
		if not link_doctype or not link_name:
			return {}

		address_name = get_default_address(link_doctype, link_name)
		if not address_name:
			return {}

		return self._address_dict_from_name(address_name)

	def _extract_immobilie_address(self, immobilie_doc) -> Dict[str, str]:
		if not immobilie_doc:
			return {}

		linked_address = cstr(immobilie_doc.get("adresse")).strip()
		if linked_address:
			address_data = self._address_dict_from_name(linked_address)
			if address_data:
				return address_data

		address_from_link = self._extract_address("Immobilie", immobilie_doc.name)
		if address_from_link:
			return address_from_link

		street = (
			cstr(immobilie_doc.get("adresse__name"))
			or cstr(immobilie_doc.get("stra\u00dfe"))
			or cstr(immobilie_doc.get("strasse"))
		).strip()
		zip_code = cstr(immobilie_doc.get("plz")).strip()
		city = cstr(immobilie_doc.get("ort")).strip()
		plz_ort = self._format_plz_ort(zip_code, city)

		return {
			"street": street,
			"zip": zip_code,
			"city": city,
			"plz_ort": plz_ort,
		}

	def _address_dict_from_name(self, address_name: str | None) -> Dict[str, str]:
		if not address_name:
			return {}
		try:
			address = frappe.get_doc("Address", address_name)
		except frappe.DoesNotExistError:
			return {}

		street = ", ".join(filter(None, [cstr(address.address_line1).strip(), cstr(address.address_line2).strip()]))
		zip_code = cstr(getattr(address, "pincode", None) or getattr(address, "zip", None)).strip()
		city = cstr(address.city).strip()
		plz_ort = self._format_plz_ort(zip_code, city)

		return {
			"street": street,
			"zip": zip_code,
			"city": city,
			"plz_ort": plz_ort,
			"display": "\n".join(filter(None, [street, plz_ort])),
			"title": cstr(address.address_title).strip(),
			"name": cstr(address.name).strip(),
		}

	def _guess_person_name(self, doc) -> str:
		if not doc:
			return ""

		first = cstr(getattr(doc, "first_name", "")).strip()
		last = cstr(getattr(doc, "last_name", "")).strip()
		full = " ".join(filter(None, [first, last]))
		if full:
			return full

		for field in ("customer_name", "full_name", "name1", "vorname", "nachname", "company_name", "subject", "name"):
			value = cstr(getattr(doc, field, "")).strip()
			if value:
				return value

		return cstr(getattr(doc, "title", "")).strip()

	def _resolve_mieter_names_from_vertrag(self, mietvertrag_name: str | None) -> str:
		"""Personen-Anzeigename der Hauptmieter aus der ``mieter``-Tabelle eines
		Mietvertrags (Vertragspartner → Contact). Frauen werden zuerst genannt,
		innerhalb der Gruppen folgt die Reihenfolge der Mietvertrag-Tabelle.
		"""
		if not mietvertrag_name:
			return ""
		try:
			rows = frappe.db.sql(
				"""
				SELECT vp.mieter
				FROM `tabVertragspartner` vp
				WHERE vp.parent = %(mv)s
				  AND vp.parenttype = 'Mietvertrag'
				  AND vp.parentfield = 'mieter'
				  AND COALESCE(vp.rolle, '') = 'Hauptmieter'
				ORDER BY vp.idx
				""",
				{"mv": mietvertrag_name},
				as_dict=True,
			)
		except Exception:
			return ""
		contacts = []
		for row in rows:
			contact_name = cstr(row.get("mieter")).strip()
			if not contact_name:
				continue
			contact_doc = self._load_doc("Contact", contact_name)
			if contact_doc:
				contacts.append(contact_doc)

		contacts.sort(key=lambda doc: 0 if cstr(getattr(doc, "salutation", "")).strip() == "Frau" else 1)

		names: list[str] = []
		for contact_doc in contacts:
			person = self._guess_person_name(contact_doc)
			if person and person not in names:
				names.append(person)
		return " und ".join(names)

	def _format_plz_ort(self, plz: str, ort: str) -> str:
		parts = [plz, ort]
		return " ".join([p for p in parts if p]).strip()

def _scrub_value(value: str) -> str:
	value = (value or "").lower()
	value = re.sub(r"[^a-z0-9]+", "-", value)
	value = value.strip("-")
	return value or "serienbrief"


def _coerce_bool_if_needed(value, variable_type: str):
	# Bool-Werte aus inline_baustein_werte / variablen_werte koennen als String
	# "false"/"true" persistiert sein (alte Editor-States, JSON-Roundtrips).
	# Jinja sieht jeden nicht-leeren String als truthy, daher vor Context-
	# Uebergabe in echtes Boolean konvertieren.
	if variable_type != "Bool" or value is None:
		return value
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in ("true", "1", "yes", "on", "ja")
	return bool(value)


def _parse_mapping(raw: str | None) -> dict:
	if not raw:
		return {}
	try:
		data = json.loads(raw)
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _parse_variable_values(raw: str | None) -> dict[str, dict[str, Any]]:
	data = _parse_mapping(raw)
	if not isinstance(data, dict):
		return {}

	parsed: dict[str, dict[str, Any]] = {}
	for key, value in data.items():
		key = cstr(key or "").strip()
		if not key:
			continue
		if isinstance(value, dict):
			parsed[key] = {"value": value.get("value"), "path": value.get("path")}
		else:
			parsed[key] = {"value": value, "path": None}

	return parsed


def _path_override_key(path: str) -> str:
	return f"{PATH_OVERRIDE_PREFIX}{cstr(path or '').strip()}"


def _entry_has_explicit_value(entry: dict[str, Any] | None) -> bool:
	if not isinstance(entry, dict):
		return False
	value = entry.get("value")
	if value is None:
		return False
	if isinstance(value, str) and not value.strip():
		return False
	return True


def _get_value_override(context: Dict[str, Any], key: str) -> Any:
	mapping = context.get("_serienbrief_value_overrides") if isinstance(context, dict) else None
	if not isinstance(mapping, dict):
		return None
	entry = mapping.get(key)
	if _entry_has_explicit_value(entry):
		return entry.get("value")
	return None


def _display_value(value: Any) -> Any:
	if hasattr(value, "doctype") and getattr(value, "name", None):
		return value.name
	formatted = _format_serienbrief_number(value)
	if formatted is not None:
		return formatted
	return value


def _merge_variable_values(base_raw: str | None, override_raw: str | None) -> str | None:
	base = _parse_variable_values(base_raw)
	override = _parse_variable_values(override_raw)
	if not base and not override:
		return None
	merged: dict[str, dict[str, Any]] = {}
	merged.update(base)
	merged.update(override)
	return json.dumps(merged) if merged else None


def _as_variable_values(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
	return {key: {"value": value} for key, value in data.items() if key and value is not None}


def _money_without_currency(value: float, currency: str = "EUR") -> str:
	return (frappe.utils.fmt_money(value, currency=currency) or "").replace("€", "").strip()


def _dunning_stage_from_type(dunning_type: str | None) -> int:
	dunning_type = cstr(dunning_type or "")
	if dunning_type.startswith("Zahlungserinnerung"):
		return 0
	if dunning_type.startswith("1. Mahnung"):
		return 1
	if dunning_type.startswith("2. Mahnung"):
		return 2
	return 3


def _collect_dunning_auto_values(dunning) -> dict[str, dict[str, Any]]:
	if not dunning or getattr(dunning, "doctype", None) != "Dunning":
		return {}

	payments = list(getattr(dunning, "overdue_payments", None) or [])
	currency = cstr(getattr(dunning, "currency", None) or "EUR")
	outstanding = getattr(dunning, "total_outstanding", None)
	if outstanding is None:
		outstanding = getattr(dunning, "outstanding_amount", None)
	if outstanding is None:
		outstanding = sum(frappe.utils.flt(row.get("outstanding") or row.get("outstanding_amount") or row.get("amount") or 0) for row in payments)
	outstanding = frappe.utils.flt(outstanding)
	fee = frappe.utils.flt(getattr(dunning, "dunning_fee", 0) or 0)
	grand_total = getattr(dunning, "grand_total", None)
	if grand_total is None:
		grand_total = outstanding + fee
	grand_total = frappe.utils.flt(grand_total)

	paid = 0.0
	months: list[str] = []
	for row in payments:
		row_outstanding = frappe.utils.flt(row.get("outstanding") or row.get("outstanding_amount") or row.get("amount") or 0)
		sales_invoice = row.get("sales_invoice")
		if sales_invoice:
			invoice_total = frappe.utils.flt(frappe.db.get_value("Sales Invoice", sales_invoice, "grand_total") or 0)
			paid += max(invoice_total - row_outstanding, 0)
		if row.get("due_date"):
			month = frappe.utils.formatdate(row.get("due_date"), "MM/yyyy")
			if month and month not in months:
				months.append(month)

	if len(months) == 1:
		month_value = months[0]
	elif len(months) > 1:
		month_value = f"{months[0]} bis {months[-1]}"
	else:
		month_value = frappe.utils.formatdate(getattr(dunning, "posting_date", None) or today(), "MM/yyyy")

	return _as_variable_values(
		{
			"stufe": _dunning_stage_from_type(getattr(dunning, "dunning_type", None)),
			"monat": month_value,
			"rueckstand": _money_without_currency(grand_total, currency),
			"fehlbetrag": _money_without_currency(outstanding, currency),
			"gezahlt": _money_without_currency(paid, currency),
			"fehlbetrag_text": "ein Betrag",
		}
	)


DUNNING_AUTO_VALUE_FIELD_META = {
	"stufe": {"label": "Mahnstufe", "description": "Automatisch aus der Mahnregel berechnet."},
	"monat": {"label": "Monat", "description": "Automatisch aus den zu mahnenden Rechnungen berechnet."},
	"rueckstand": {"label": "Rückstand", "description": "Automatisch aus offenen Rechnungen plus Mahngebühr berechnet."},
	"fehlbetrag": {"label": "Fehlbetrag", "description": "Automatisch aus den offenen Rechnungen berechnet."},
	"gezahlt": {"label": "Gezahlt", "description": "Automatisch aus Rechnungsbetrag minus offenem Betrag berechnet."},
	"fehlbetrag_text": {"label": "Fehlbetrag-Text", "description": "Automatisch berechneter Textbaustein zum Fehlbetrag."},
}


def _collect_auto_variable_values(context: Dict[str, Any]) -> dict[str, dict[str, Any]]:
	objekt = context.get("objekt") if isinstance(context, dict) else None
	if getattr(objekt, "doctype", None) == "Dunning":
		return _collect_dunning_auto_values(objekt)
	return {}


def _get_textbaustein_template_source(block_doc) -> str:
	content_type = (getattr(block_doc, "content_type", "") or "").strip() or "Textbaustein (Rich Text)"
	if content_type == "HTML + Jinja":
		return "\n".join(
			part for part in [
				cstr(getattr(block_doc, "jinja_content", "") or ""),
				cstr(getattr(block_doc, "html_content", "") or ""),
			] if part.strip()
		)
	return sanitize_richtext_jinja_source(cstr(getattr(block_doc, "text_content", "") or "").strip())


def _collect_template_path_tokens(template) -> list[str]:
	seen: set[str] = set()
	paths: list[str] = []

	def add_from_source(source: str | None) -> None:
		for match in _PLACEHOLDER_TOKEN_RE.finditer(source or ""):
			path = cstr(match.group(1) or "").strip()
			if path and path not in seen:
				seen.add(path)
				paths.append(path)

	add_from_source(_get_template_template_source(template))
	for row in template.get("textbausteine") or []:
		if not getattr(row, "baustein", None):
			continue
		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", row.baustein)
		except Exception:
			continue
		add_from_source(_get_textbaustein_template_source(block_doc))

	return paths


def _template_supports_druck_schwarz_weiss(template) -> bool:
	if not template:
		return False
	sources = [_get_template_template_source(template)]
	for row in template.get("textbausteine") or []:
		if not getattr(row, "baustein", None):
			continue
		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", row.baustein)
		except Exception:
			continue
		sources.append(_get_textbaustein_template_source(block_doc))
	return any("druck_schwarz_weiss" in cstr(source or "") for source in sources)


def _build_value_override_mapping(template, durchlauf=None, row=None) -> dict[str, dict[str, Any]]:
	merged: dict[str, dict[str, Any]] = {}
	if template is not None:
		merged.update(_parse_variable_values(getattr(template, "variablen_werte", None)))
	if durchlauf is not None:
		merged.update(_parse_variable_values(getattr(durchlauf, "variablen_werte", None)))
	if row is not None:
		merged.update(_parse_variable_values(getattr(row, "_iteration_variablen_werte", None)))
	return merged


def _serialize_overview_value(value: Any, max_items: int = 5) -> dict[str, Any]:
	if value is None:
		return {"display": "", "is_empty": True}

	if isinstance(value, (list, tuple)):
		items = [_serialize_overview_value(item, max_items=max_items) for item in value[:max_items]]
		labels = [item.get("display") or "" for item in items if item.get("display")]
		display = f"{len(value)} " + _("Einträge")
		if labels:
			display = f"{display}: {', '.join(labels)}"
		return {"display": display, "is_list": True, "count": len(value), "items": items}

	if _is_document_like(value):
		doctype = getattr(value, "doctype", None) or (value.get("doctype") if isinstance(value, dict) else "")
		name = getattr(value, "name", None) or (value.get("name") if isinstance(value, dict) else "")
		title = getattr(value, "title", None) or (value.get("title") if isinstance(value, dict) else "")
		if title and name and title != name:
			display = f"{title} ({name})"
		else:
			display = title or name or cstr(value)
		return {
			"display": display,
			"doctype": doctype or "",
			"name": name or "",
			"title": title or "",
		}

	return {"display": cstr(value)}


class _LinkResolvingRow:
	"""Lazy-Wrapper, der bei jedem Attribut-Zugriff Link-Felder automatisch zu
	Sub-Docs auflöst — analog zur Logik im :func:`_resolve_value_path`-Resolver,
	nur on-demand bei Jinja-``getattr`` statt eager beim String-Pfad-Splitting.

	Der Wrapper wird bewusst für aufgelöste Listen-Inputs aus ``[]``-Mapping-
	Pfaden verwendet. Tiefe Datenpfade im Body laufen offiziell über
	``{{$ objekt.wohnung.immobilie.name $}}`` und damit über
	:func:`_resolve_value_path`; Root-``objekt`` wird nicht pauschal als
	``_LinkResolvingRow`` in den Jinja-Kontext gelegt. Sub-Docs werden rekursiv
	weiter gewrappt; Child-Tables liefern eine Liste gewrappter Zeilen;
	``.address`` an einem Dynamic-Link-Doctype liefert das Default-Address-Doc
	(analog zur Resolver-Address-Magic).

	String-Vergleiche bleiben funktional, weil ``__str__``/``__eq__`` an den
	Doc-Namen delegieren — ``{{ wohnung == "WHN-007" }}`` liefert weiter True.
	"""

	__slots__ = ("_source", "_meta")

	def __init__(self, source: Any):
		object.__setattr__(self, "_source", source)
		meta = None
		try:
			doctype = getattr(source, "doctype", None) or (source.get("doctype") if isinstance(source, dict) else None)
			if doctype:
				meta = frappe.get_meta(doctype)
		except Exception:
			meta = None
		object.__setattr__(self, "_meta", meta)

	def __getattr__(self, key: str):
		source = object.__getattribute__(self, "_source")
		meta = object.__getattribute__(self, "_meta")

		# Address-Magic: ``.address`` an einem Adress-fähigen DocType lädt das
		# Default-Address-Doc (Frappe Dynamic-Link).
		if (
			key == "address"
			and getattr(source, "doctype", None) in _ADDRESS_TARGET_DOCTYPES
			and getattr(source, "name", None)
		):
			addr_name = get_default_address(source.doctype, source.name)
			if addr_name:
				try:
					return _LinkResolvingRow(frappe.get_cached_doc("Address", addr_name))
				except frappe.DoesNotExistError:
					return None
			return None

		value = _dig_attr(source, key)

		if meta:
			df = meta.get_field(key)
			if df and df.fieldtype == "Link" and df.options and isinstance(value, str) and value:
				try:
					return _LinkResolvingRow(frappe.get_cached_doc(df.options, value))
				except Exception:
					return value
			if df and df.fieldtype == "Table" and isinstance(value, (list, tuple)):
				return [_LinkResolvingRow(row) if _is_document_like(row) else row for row in value]

		# Sub-Docs/Dicts auch wrappen, damit Properties die Sub-Docs liefern
		# (z.B. ``Mietvertrag.mieter`` als Vertragspartner-Liste) auch noch
		# tiefer aufgelöst werden können.
		if _is_document_like(value):
			return _LinkResolvingRow(value)
		return value

	def __getitem__(self, key: Any):
		# String-Key: wie Attribut-Lookup. Int: Index in Source (wenn iterable).
		if isinstance(key, int):
			source = object.__getattribute__(self, "_source")
			if isinstance(source, (list, tuple)):
				return source[key]
		return self.__getattr__(str(key))

	def __iter__(self):
		source = object.__getattribute__(self, "_source")
		if isinstance(source, (list, tuple)):
			for item in source:
				yield _LinkResolvingRow(item) if _is_document_like(item) else item
		else:
			# Für Doc-Wrapper Iteration über Felder geben — wie Frappe Document.
			yield from iter(source)

	def get(self, key: str, default: Any = None) -> Any:
		# ``.get(key)`` wie auf einem Dict — manche Bausteine schreiben
		# ``mietvertrag.get("größe")`` für Felder mit Sonderzeichen.
		try:
			value = self.__getattr__(key)
		except AttributeError:
			return default
		return default if value is None else value

	def as_dict(self):
		source = object.__getattribute__(self, "_source")
		if hasattr(source, "as_dict"):
			try:
				return source.as_dict()
			except Exception:
				return {}
		if isinstance(source, dict):
			return dict(source)
		return {}

	def __str__(self):
		# String-Vergleiche und f-strings sollen weiter den Doc-Namen liefern
		# (so dass z.B. ``{{ wohnung == "WHN-007" }}`` und
		# ``{{ "/" ~ wohnung }}`` weiter wie auf einem Frappe-Doc funktionieren).
		source = object.__getattribute__(self, "_source")
		return str(getattr(source, "name", source) or "")

	def __eq__(self, other):
		if isinstance(other, _LinkResolvingRow):
			other = object.__getattribute__(other, "_source")
		return str(self) == str(other) if isinstance(other, str) else (
			object.__getattribute__(self, "_source") == other
		)

	def __hash__(self):
		return hash(str(self))

	def __bool__(self):
		# Doc-Wrapper truthy, leere Listen/Dicts via Source-Verhalten.
		source = object.__getattribute__(self, "_source")
		return bool(source)

	def __repr__(self):
		source = object.__getattribute__(self, "_source")
		return f"<LinkResolvingRow {source!r}>"


def _is_document_like(value: Any) -> bool:
	if getattr(value, "doctype", None):
		return True
	return isinstance(value, dict) and bool(value.get("doctype"))


def _wrap_preserved_list(values: list[Any] | tuple[Any, ...]) -> list[Any]:
	"""Stellt sicher, dass Listen aus Pfaden mit [] Link-Felder als Dokumente liefern."""
	wrapped: list[Any] = []
	for item in values:
		if _is_document_like(item):
			wrapped.append(_LinkResolvingRow(item))
		else:
			wrapped.append(item)
	return wrapped


def _dig_attr(source: Any, key: str) -> Any:
	if source is None:
		return None

	if isinstance(source, dict):
		return source.get(key)

	if isinstance(source, (list, tuple)) and key.isdigit():
		idx = int(key)
		if 0 <= idx < len(source):
			return source[idx]
		return None

	return getattr(source, key, None)


_BRACKET_INDEX_RE = re.compile(r"^([^\[\]]+)((?:\[\d+\])+)$")
_BRACKET_INDEX_PARTS_RE = re.compile(r"\[(\d+)\]")

# DocTypes mit Frappe-Dynamic-Link-Adressen: ``address`` als Resolver-
# Pfad-Schritt wird automatisch zum Default-Address-Doc aufgelöst, sodass
# Datenplatzhalter ``{{$ objekt.kunde.address.address_line1 $}}`` schreiben
# können statt ``frappe.get_doc("Address", get_default_address(...))``.
_ADDRESS_TARGET_DOCTYPES = {"Customer", "Immobilie", "Wohnung", "Contact", "Supplier"}


def _resolve_value_path(path: str, context: Dict[str, Any]) -> Any:
	raw_segments = [seg.strip() for seg in cstr(path).split(".") if seg.strip()]
	if not raw_segments:
		return None

	# Bracket-Indices als separate Pfad-Schritte expandieren —
	# ``vorauszahlung_slots[1]`` wird ``["vorauszahlung_slots", "1"]``.
	# Mehrfach-Indices (``foo[0][1]``) werden flach gelegt.
	expanded: list[str] = []
	for seg in raw_segments:
		match = _BRACKET_INDEX_RE.match(seg)
		if match:
			expanded.append(match.group(1))
			expanded.extend(_BRACKET_INDEX_PARTS_RE.findall(match.group(2)))
		else:
			expanded.append(seg)
	raw_segments = expanded

	preserve_list = False
	if raw_segments and raw_segments[-1].endswith("[]"):
		raw_segments[-1] = raw_segments[-1][:-2].strip()
		preserve_list = True
		if not raw_segments[-1]:
			return None

	if raw_segments[0] == "__self__":
		raw_segments[0] = "objekt"

	allowed_roots = {"objekt", "empfaenger", "serienbrief", "outputs", "datum", "datum_iso"}
	has_explicit_root = raw_segments[0] in allowed_roots or (
		isinstance(context, dict) and raw_segments[0] in context
	)
	root_name = raw_segments[0] if has_explicit_root else "objekt"
	segments = raw_segments[1:] if has_explicit_root else raw_segments
	if not segments:
		return context.get(root_name) if isinstance(context, dict) else None

	def pick_child_row(child_list: list[Any], lookahead: str | None = None) -> tuple[Any | None, bool]:
		"""Pick a child row from a child table. Returns (row, consumed_numeric)."""
		if not child_list:
			return None, False

		if lookahead is not None and lookahead.isdigit():
			idx = int(lookahead)
			if 0 <= idx < len(child_list):
				return child_list[idx], True

		if lookahead:
			for item in child_list:
				if getattr(item, lookahead, None):
					return item, False

		return child_list[0], False

	def resolve_from_root(root: Any) -> Any:
		# Wrapper auspacken — der String-Pfad-Resolver arbeitet intern mit
		# rohen Frappe-Docs. Der Wrapper ist nur für Jinja-``getattr`` da.
		if isinstance(root, _LinkResolvingRow):
			root = object.__getattribute__(root, "_source")
		current: Any = root
		idx = 0
		while idx < len(segments):
			segment = segments[idx]

			if isinstance(current, _LinkResolvingRow):
				current = object.__getattribute__(current, "_source")

			if isinstance(current, dict):
				current = current.get(segment)
				if current is None:
					return None
				if preserve_list and idx == len(segments) - 1 and isinstance(current, (list, tuple)):
					return current
				idx += 1
				continue

			if isinstance(current, (list, tuple)):
				# Numerischer Step direkt als Index — relevant für Properties
				# wie ``Mietvertrag.vorauszahlung_slots[1]``, wo das Property
				# eine Python-Liste statt einer DocType-Tabelle liefert.
				if segment.isdigit():
					i = int(segment)
					current = current[i] if 0 <= i < len(current) else None
					if current is None:
						return None
					idx += 1
					continue

				if preserve_list and idx == len(segments) - 1:
					return current
				lookahead = segments[idx + 1] if idx + 1 < len(segments) else None
				row, consumed_numeric = pick_child_row(list(current), lookahead)
				if row is None:
					return None
				current = row
				idx += 1
				if consumed_numeric:
					idx += 1
				continue

			# Adress-Magic: ``address`` als Pfad-Schritt an einem Adress-fähigen
			# DocType lädt transparent das Default-Address-Doc via Frappe-
			# Dynamic-Link-Resolver. Damit funktioniert
			# ``{{ objekt.kunde.address.address_line1 }}`` ohne dass jeder
			# DocType ein Custom-Adress-Feld bekommt.
			if (
				segment == "address"
				and getattr(current, "doctype", None) in _ADDRESS_TARGET_DOCTYPES
				and getattr(current, "name", None)
			):
				addr_name = get_default_address(current.doctype, current.name)
				current = frappe.get_cached_doc("Address", addr_name) if addr_name else None
				if current is None:
					return None
				idx += 1
				continue

			# Follow Link/Table fields using DocType meta so Pfade aus dem Wizard funktionieren.
			doctype = getattr(current, "doctype", None)
			meta = None
			if doctype:
				try:
					meta = frappe.get_meta(doctype)
				except Exception:
					meta = None

			if meta:
				df = meta.get_field(segment)
				if df:
					if df.fieldtype == "Link" and df.options:
						link_value = getattr(current, segment, None)
						if not link_value:
							return None
						# Wenn der Wert bereits ein Doc-Stand-In ist (eigene
						# Properties wie ``Mietvertrag.kunde`` als Doc, oder
						# Live-Preview-Mock wie ``SplitPreviewWohnung``),
						# direkt durchreichen statt nochmal nachzuladen.
						if not isinstance(link_value, str) and getattr(link_value, "doctype", None):
							current = link_value
							idx += 1
							continue
						try:
							current = frappe.get_cached_doc(df.options, link_value)
						except Exception:
							return None
						idx += 1
						continue

					if df.fieldtype == "Table" and df.options:
						child_list = getattr(current, segment, None) or []
						if preserve_list and idx == len(segments) - 1:
							return list(child_list)
						lookahead = segments[idx + 1] if idx + 1 < len(segments) else None
						child_row, consumed_numeric = pick_child_row(child_list, lookahead)
						if not child_row:
							return None
						current = child_row
						idx += 1
						if consumed_numeric:
							idx += 1
						continue

			current = _dig_attr(current, segment)
			if current is None:
				return None
			if preserve_list and idx == len(segments) - 1 and isinstance(current, (list, tuple)):
				return current
			idx += 1

		return current

	root = context.get(root_name) if isinstance(context, dict) else None
	primary = resolve_from_root(root)
	if preserve_list and isinstance(primary, (list, tuple)):
		return _wrap_preserved_list(list(primary))
	if primary is not None:
		return primary

	return None


def _collect_template_requirements(template, base_doctype: str | None = None) -> Dict[str, Any]:
	base_doctype = base_doctype or template.get("haupt_verteil_objekt")
	if not base_doctype:
		frappe.throw(_("Bitte hinterlegen Sie ein Haupt-Verteil-Objekt in der Vorlage."))

	template_variables = _collect_template_variables(template)
	template_variable_defaults = _parse_variable_values(getattr(template, "variablen_werte", None))
	block_variables = _collect_block_variables(template)
	pdf_block_mappings = _collect_pdf_block_mappings(template)

	return {
		"required_fields": [],
		"auto_fields": [],
		"missing_fields": [],
		"block_requirements": _collect_block_input_requirements(template, base_doctype),
		"template_requirements": [],
		"template_variables": template_variables,
		"template_variable_defaults": template_variable_defaults,
		"block_variables": block_variables,
		"pdf_block_mappings": pdf_block_mappings,
		"haupt_verteil_objekt": template.get("haupt_verteil_objekt"),
		"empfaenger_links": [],
	}



def _collect_block_input_requirements(template, base_doctype: str | None = None) -> list[Dict[str, Any]]:
	block_requirements: list[Dict[str, Any]] = []
	link_fields_by_doctype, table_fields_by_doctype, table_fields = _get_mapping_meta(base_doctype)

	for row in template.get("textbausteine") or []:
		if not getattr(row, "baustein", None):
			continue

		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", row.baustein)
		except frappe.DoesNotExistError:
			continue

		mapping = _parse_mapping(row.get("pfad_zuordnung"))
		default_mapping = _get_block_default_path_map(block_doc, base_doctype)
		block_refs: list[Dict[str, Any]] = []

		for variable in block_doc.get("variables") or []:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type not in {"Doctype", "Doctype Liste"}:
				continue

			ref_doctype = cstr(getattr(variable, "reference_doctype", None) or "").strip()
			if not ref_doctype:
				continue

			context_variable = cstr(
				getattr(variable, "variable", None)
				or getattr(variable, "label", None)
				or ref_doctype
				or ""
			).strip()
			fieldname = frappe.scrub(context_variable or ref_doctype)
			if not fieldname:
				continue

			rowname = cstr(getattr(variable, "name", None) or "").strip()
			req_key = rowname if rowname and not rowname.startswith("new") else ref_doctype or fieldname
			is_list = variable_type == "Doctype Liste"
			row_fieldname, row_field_label, has_direct_link = _resolve_direct_input_field(
				ref_doctype,
				fieldname,
				base_doctype,
				link_fields_by_doctype,
				table_fields_by_doctype,
				table_fields,
				is_list=is_list,
			)

			direct_path = row_fieldname if has_direct_link else None
			if base_doctype and ref_doctype == base_doctype:
				direct_path = "__self__"

			spec = {
				"reference_doctype": ref_doctype,
				"context_variable": context_variable,
				"fieldname": fieldname,
			}
			path_from_template = _pick_mapping_value(mapping, req_key, spec)
			path_from_default = _pick_mapping_value(default_mapping, req_key, spec) if default_mapping else None
			path_from_direct = None if (path_from_template or path_from_default) else direct_path
			path = path_from_template or path_from_default or path_from_direct
			path_source = (
				"template"
				if path_from_template
				else "default"
				if path_from_default
				else "direct"
				if path_from_direct
				else ""
			)

			block_refs.append(
				{
					"fieldname": fieldname,
					"row_fieldname": row_fieldname,
					"field_label": row_field_label,
					"doctype": ref_doctype,
					"source": block_doc.title or block_doc.name,
					"label": getattr(variable, "label", None) or row_field_label or ref_doctype,
					"block": block_doc.name,
					"block_title": block_doc.title or block_doc.name,
					"block_rowname": row.name,
					"req_key": req_key,
					"is_list": is_list,
					"resolved_in_template": bool(path),
					"resolved_via_default": path_source in {"default", "direct"},
					"path_source": path_source,
					"path": path,
				}
			)

		if block_refs:
			block_requirements.append(
				{
					"block": block_doc.name,
					"block_title": block_doc.title or block_doc.name,
					"rowname": row.name,
					"requirements": block_refs,
				}
			)

	return block_requirements


def _get_mapping_meta(base_doctype: str | None = None):
	link_fields_by_doctype: dict[str, Any] = {}
	table_fields_by_doctype: dict[str, Any] = {}
	table_fields: list[Any] = []

	if not base_doctype:
		return link_fields_by_doctype, table_fields_by_doctype, table_fields

	try:
		meta = frappe.get_meta(base_doctype)
	except Exception:
		return link_fields_by_doctype, table_fields_by_doctype, table_fields

	link_fields_by_doctype = {cstr(df.options): df for df in meta.fields if df.fieldtype == "Link" and df.options}
	for df in meta.fields:
		if df.fieldtype == "Table" and df.options and cstr(df.options):
			table_fields_by_doctype.setdefault(cstr(df.options), df)
			table_fields.append(df)

	return link_fields_by_doctype, table_fields_by_doctype, table_fields


def _resolve_direct_input_field(
	ref_doctype: str,
	fieldname: str,
	base_doctype: str | None,
	link_fields_by_doctype: dict[str, Any],
	table_fields_by_doctype: dict[str, Any],
	table_fields: list[Any],
	*,
	is_list: bool = False,
) -> tuple[str, str | None, bool]:
	link_df = link_fields_by_doctype.get(ref_doctype)
	if link_df:
		return link_df.fieldname, link_df.label, True

	if base_doctype and ref_doctype == base_doctype:
		return fieldname, None, True

	if is_list:
		table_df = table_fields_by_doctype.get(ref_doctype)
		if table_df and getattr(table_df, "fieldname", None):
			return table_df.fieldname, getattr(table_df, "label", None), True

		for candidate in table_fields:
			child_dt = cstr(getattr(candidate, "options", None) or "").strip()
			if not child_dt:
				continue
			try:
				child_meta = frappe.get_meta(child_dt)
			except Exception:
				continue

			match = next(
				(
					df
					for df in child_meta.fields
					if df.fieldtype == "Link"
					and cstr(getattr(df, "options", None) or "").strip() == ref_doctype
				),
				None,
			)
			if match:
				return candidate.fieldname, getattr(candidate, "label", None), True

	return fieldname, None, False


def _pick_mapping_value(mapping: dict[str, Any] | None, req_key: str, reference=None):
	if not mapping:
		return None

	keys = [
		req_key,
		cstr(reference.get("reference_doctype") if isinstance(reference, dict) else getattr(reference, "reference_doctype", None) or ""),
		cstr(reference.get("context_variable") if isinstance(reference, dict) else getattr(reference, "context_variable", None) or ""),
		cstr(reference.get("fieldname") if isinstance(reference, dict) else ""),
	]

	for key in keys:
		if not key:
			continue
		value = mapping.get(key)
		if value not in (None, ""):
			return value

	return None


def _get_block_default_path_map(block_doc, base_doctype: str | None = None) -> dict[str, str]:
	"""Return default path mapping for a Textbaustein for the given start DocType."""

	rows = getattr(block_doc, "standardpfade", None) or []
	if not rows and isinstance(block_doc, dict):
		rows = block_doc.get("standardpfade") or []

	if not rows:
		return {}

	fallback: dict[str, str] | None = None
	for row in rows:
		startobjekt = cstr(
			getattr(row, "startobjekt", None)
			or (row.get("startobjekt") if isinstance(row, dict) else None)
			or ""
		)
		mapping = _parse_mapping(
			getattr(row, "pfad_zuordnung", None) if not isinstance(row, dict) else row.get("pfad_zuordnung")
		)
		if startobjekt and base_doctype and startobjekt == base_doctype and isinstance(mapping, dict):
			return mapping

		if not startobjekt and isinstance(mapping, dict) and mapping:
			fallback = mapping

	if fallback and isinstance(fallback, dict):
		return fallback

	return {}


def _collect_block_variables(template) -> list[Dict[str, Any]]:
	results: list[Dict[str, Any]] = []

	for row in template.get("textbausteine") or []:
		if not getattr(row, "baustein", None):
			continue

		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", row.baustein)
		except frappe.DoesNotExistError:
			continue

		variables: list[Dict[str, Any]] = []
		for variable in block_doc.get("variables") or []:
			variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
			if variable_type != "Text":
				continue

			raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
			key = frappe.scrub(raw_key) if raw_key else ""
			if not key:
				continue

			variables.append(
				{
					"key": key,
					"variable": raw_key,
					"label": getattr(variable, "label", None) or raw_key,
					"description": getattr(variable, "beschreibung", None) or "",
				}
			)

		if not variables:
			continue

		results.append(
			{
				"block": block_doc.name,
				"block_title": block_doc.title or block_doc.name,
				"rowname": row.name,
				"variables": variables,
				"values": _parse_variable_values(getattr(row, "variablen_werte", None)),
			}
		)

	return results


def _collect_pdf_block_mappings(template) -> list[Dict[str, Any]]:
	results: list[Dict[str, Any]] = []
	for row in template.get("textbausteine") or []:
		block_name = cstr(getattr(row, "baustein", None) or "").strip()
		if not block_name:
			continue
		try:
			block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_name)
		except frappe.DoesNotExistError:
			continue

		content_type = cstr(getattr(block_doc, "content_type", None) or "").strip() or "Textbaustein (Rich Text)"
		if content_type != "PDF Formular":
			continue

		fields: list[Dict[str, Any]] = []
		for mapping in getattr(block_doc, "pdf_field_mappings", []) or []:
			field_name = cstr(getattr(mapping, "pdf_field_name", None) or "").strip()
			if not field_name:
				continue
			path = cstr(getattr(mapping, "value_path", None) or "").strip()
			fields.append(
				{
					"pdf_field_name": field_name,
					"value_path": path,
					"fallback_value": getattr(mapping, "fallback_value", None),
					"required": bool(int(getattr(mapping, "required", 0) or 0)),
					"value_type": cstr(getattr(mapping, "value_type", None) or "String").strip() or "String",
				}
			)
		if not fields:
			continue
		results.append(
			{
				"block": block_doc.name,
				"block_title": block_doc.title or block_doc.name,
				"rowname": row.name,
				"fields": fields,
			}
		)
	return results


def _collect_template_variables(template) -> list[Dict[str, Any]]:
	results: list[Dict[str, Any]] = []

	for variable in template.get("variables") or []:
		variable_type = cstr(getattr(variable, "variable_type", None) or "").strip() or "Text"
		if variable_type not in {"String", "Zahl", "Bool", "Datum", "Text"}:
			continue

		raw_key = cstr(getattr(variable, "variable", None) or getattr(variable, "label", None) or "")
		key = frappe.scrub(raw_key) if raw_key else ""
		if not key:
			continue

		results.append(
			{
				"key": key,
				"variable": raw_key,
				"label": getattr(variable, "label", None) or raw_key,
				"description": getattr(variable, "beschreibung", None) or "",
				"variable_type": variable_type,
			}
		)

	return results


@frappe.whitelist()
def get_template_requirements(template: str | None = None, template_doc: Dict[str, Any] | None = None) -> Dict[str, Any]:
	if isinstance(template_doc, str):
		try:
			template_doc = json.loads(template_doc)
		except Exception:
			template_doc = None

	if template_doc:
		doc = frappe.get_doc(template_doc)
	elif template:
		doc = frappe.get_cached_doc("Serienbrief Vorlage", template)
	else:
		frappe.throw(_("Bitte wählen Sie eine Vorlage."))

	return _collect_template_requirements(doc, getattr(doc, "haupt_verteil_objekt", None))


def _parse_value_fields_context(context: str | dict | None) -> dict[str, Any]:
	if isinstance(context, str):
		try:
			context = json.loads(context or "{}")
		except Exception:
			context = {}
	return context if isinstance(context, dict) else {}


def _context_overrides(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
	raw = context.get("overrides") or context.get("values") or context.get("variablen_werte") or {}
	if isinstance(raw, str):
		return _parse_variable_values(raw)
	if isinstance(raw, dict):
		return _parse_variable_values(json.dumps(raw))
	return {}


def _parse_context_list(value) -> list[str]:
	if isinstance(value, str):
		try:
			value = json.loads(value or "[]")
		except Exception:
			value = [value]
	return [cstr(item or "").strip() for item in (value or []) if cstr(item or "").strip()]


def _mock_dunning_from_context(context_data: dict[str, Any]):
	invoice_names = _parse_context_list(
		context_data.get("sales_invoices") or context_data.get("salesInvoices")
	)
	if not invoice_names:
		return None

	payments = []
	outstanding = 0.0
	currency = "EUR"
	for name in invoice_names:
		if not frappe.db.exists("Sales Invoice", name):
			continue
		si = frappe.get_cached_doc("Sales Invoice", name)
		currency = getattr(si, "currency", None) or currency
		amount = frappe.utils.flt(getattr(si, "outstanding_amount", 0))
		outstanding += amount
		payments.append(
			frappe._dict(
				sales_invoice=si.name,
				due_date=getattr(si, "due_date", None),
				outstanding=amount,
				outstanding_amount=amount,
				amount=amount,
			)
		)

	if not payments:
		return None

	fee = frappe.utils.flt(context_data.get("mahngebuehr") or context_data.get("dunning_fee") or 0)
	return frappe._dict(
		doctype="Dunning",
		name=None,
		dunning_type=context_data.get("dunning_type"),
		currency=currency,
		dunning_fee=fee,
		total_outstanding=outstanding,
		outstanding_amount=outstanding,
		grand_total=outstanding + fee,
		posting_date=today(),
		overdue_payments=payments,
	)


def _resolve_mapping_entry_value(entry: dict[str, Any] | None, context: Dict[str, Any]) -> Any:
	if not isinstance(entry, dict):
		return None
	path = cstr(entry.get("path") or "").strip()
	if path:
		try:
			return _resolve_value_path(path, context)
		except Exception:
			return None
	if _entry_has_explicit_value(entry):
		return entry.get("value")
	return None


def _field_source_and_value(
	key: str,
	*,
	defaults: dict[str, dict[str, Any]],
	auto_values: dict[str, dict[str, Any]],
	overrides: dict[str, dict[str, Any]],
	context: Dict[str, Any],
) -> tuple[Any, Any, str]:
	override = overrides.get(key)
	if _entry_has_explicit_value(override):
		auto = _resolve_mapping_entry_value(auto_values.get(key), context)
		return override.get("value"), auto, "override"

	auto = _resolve_mapping_entry_value(auto_values.get(key), context)
	if auto is not None:
		return auto, auto, "auto"

	default = _resolve_mapping_entry_value(defaults.get(key), context)
	if default is not None:
		return default, None, "default"

	return None, None, "empty"


def _load_value_fields_context(template, iteration_doctype: str | None, iteration_objekt: str | None, context_data: dict[str, Any]):
	iteration_doctype = cstr(iteration_doctype or template.get("haupt_verteil_objekt") or "").strip()
	iteration_objekt = cstr(iteration_objekt or "").strip()
	if iteration_doctype and iteration_objekt:
		serienbrief = frappe.new_doc("Serienbrief Durchlauf")
		serienbrief.title = "Serienbrief Wertvorschau"
		serienbrief.date = today()
		serienbrief.vorlage = template.name
		serienbrief.iteration_doctype = iteration_doctype
		row = serienbrief.append(
			"iteration_objekte",
			{
				"iteration_doctype": iteration_doctype,
				"objekt": iteration_objekt,
			},
		)
		overrides = _context_overrides(context_data)
		if overrides:
			row.variablen_werte = json.dumps(overrides)
		requirements = _collect_template_requirements(template, iteration_doctype)
		rows = serienbrief._get_empfaenger_rows()
		if rows:
			return serienbrief._build_context(
				rows[0],
				1,
				requirements,
				template,
				total=1,
				strict_variables=False,
			)

	overrides = _context_overrides(context_data)
	mock_dunning = _mock_dunning_from_context(context_data) if iteration_doctype == "Dunning" else None
	return frappe._dict(
		objekt=mock_dunning,
		mietvertrag=None,
		empfaenger=frappe._dict(),
		serienbrief=frappe._dict(werte=frappe._dict()),
		outputs=frappe._dict(),
		_serienbrief_value_overrides=overrides,
	)


def _get_serienbrief_value_fields_for_doc(
	template,
	iteration_doctype: str | None = None,
	iteration_objekt: str | None = None,
	context: str | dict | None = None,
) -> dict[str, Any]:
	context_data = _parse_value_fields_context(context)
	render_context = _load_value_fields_context(template, iteration_doctype, iteration_objekt, context_data)
	defaults = _parse_variable_values(getattr(template, "variablen_werte", None))
	auto_values = _collect_auto_variable_values(render_context)
	overrides = render_context.get("_serienbrief_value_overrides") or {}
	if not isinstance(overrides, dict):
		overrides = {}

	fields: list[dict[str, Any]] = []
	seen: set[str] = set()

	for row in template.get("variables") or []:
		raw_key = cstr(getattr(row, "variable", None) or getattr(row, "label", None) or "").strip()
		key = frappe.scrub(raw_key) if raw_key else ""
		if not key or key in seen:
			continue
		seen.add(key)
		value, auto_value, source = _field_source_and_value(
			key,
			defaults=defaults,
			auto_values=auto_values,
			overrides=overrides,
			context=render_context,
		)
		fields.append(
			{
				"key": key,
				"kind": "variable",
				"label": getattr(row, "label", None) or raw_key or key,
				"token": f"{{{{ {key} }}}}",
				"value": _display_value(value),
				"auto_value": _display_value(auto_value),
				"overridable": True,
				"source": source,
				"variable": raw_key,
				"variable_type": cstr(getattr(row, "variable_type", None) or "String"),
				"optional": cint(getattr(row, "optional", 0)),
				"description": getattr(row, "beschreibung", None) or "",
			}
		)

	if (iteration_doctype or template.get("haupt_verteil_objekt")) == "Dunning":
		for key, meta in DUNNING_AUTO_VALUE_FIELD_META.items():
			if key in seen or key not in auto_values:
				continue
			seen.add(key)
			value, auto_value, source = _field_source_and_value(
				key,
				defaults=defaults,
				auto_values=auto_values,
				overrides=overrides,
				context=render_context,
			)
			fields.append(
				{
					"key": key,
					"kind": "variable",
					"label": meta["label"],
					"token": f"{{{{ {key} }}}}",
					"value": _display_value(value),
					"auto_value": _display_value(auto_value),
					"overridable": True,
					"source": source,
					"variable": key,
					"variable_type": "String",
					"optional": 1,
					"description": meta["description"],
				}
			)

	for path in _collect_template_path_tokens(template):
		key = _path_override_key(path)
		if key in seen:
			continue
		seen.add(key)
		override = overrides.get(key)
		auto_value = None
		try:
			auto_value = _resolve_value_path(path, render_context)
		except Exception:
			auto_value = None
		if _entry_has_explicit_value(override):
			value = override.get("value")
			source = "override"
		elif auto_value is not None:
			value = auto_value
			source = "auto"
		else:
			value = None
			source = "empty"
		fields.append(
			{
				"key": key,
				"kind": "path",
				"label": path,
				"token": "{{" + f"$ {path} $" + "}}",
				"value": _display_value(value),
				"auto_value": _display_value(auto_value),
				"overridable": True,
				"source": source,
			}
		)

	return {
		"template": template.name,
		"iteration_doctype": iteration_doctype or template.get("haupt_verteil_objekt"),
		"iteration_objekt": iteration_objekt,
		"fields": fields,
	}


@frappe.whitelist()
def get_serienbrief_value_fields(
	template: str | None = None,
	iteration_doctype: str | None = None,
	iteration_objekt: str | None = None,
	context: str | dict | None = None,
) -> dict[str, Any]:
	if not template:
		return {"template": None, "fields": []}
	if not frappe.has_permission("Serienbrief Vorlage", "read"):
		frappe.throw(_("Keine Berechtigung."), frappe.PermissionError)
	template_doc = frappe.get_cached_doc("Serienbrief Vorlage", template)
	return _get_serienbrief_value_fields_for_doc(
		template_doc,
		iteration_doctype=iteration_doctype,
		iteration_objekt=iteration_objekt,
		context=context,
	)


@frappe.whitelist()
def get_serienbrief_assignments(
	doc: str | dict | None = None, docname: str | None = None
) -> Dict[str, Any]:
	if isinstance(doc, str):
		try:
			doc = json.loads(doc)
		except Exception:
			doc = None

	if doc:
		serienbrief = frappe.get_doc(doc)
	elif docname:
		serienbrief = frappe.get_doc("Serienbrief Durchlauf", docname)
	else:
		frappe.throw(_("Bitte übergebe einen Serienbrief."))

	if not serienbrief.vorlage:
		frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

	template = frappe.get_cached_doc("Serienbrief Vorlage", serienbrief.vorlage)
	iteration_doctype = serienbrief.iteration_doctype or template.get("haupt_verteil_objekt")
	if not iteration_doctype:
		frappe.throw(_("Bitte wählen Sie einen Iterations-Doctype."))

	requirements = _collect_template_requirements(template, iteration_doctype)
	empfaenger_rows = serienbrief._get_empfaenger_rows()

	def collect_requirement_entries(reqs: list[Dict[str, Any]], context: Dict[str, Any], is_auto: bool = False):
		entries: list[Dict[str, Any]] = []
		for req in reqs or []:
			fieldname = cstr(req.get("fieldname") or "").strip()
			value = context.get(fieldname) if fieldname else None
			entries.append(
				{
					"label": req.get("label") or fieldname,
					"fieldname": fieldname,
					"doctype": req.get("doctype"),
					"path": req.get("path"),
					"source": req.get("source"),
					"resolved_via_default": req.get("resolved_via_default"),
					"is_list": bool(req.get("is_list")),
					"is_auto": is_auto,
					"value": _serialize_overview_value(value),
				}
			)
		return entries

	template_variable_defs = requirements.get("template_variables") or []
	template_blocks = list(template.get("textbausteine") or [])
	block_requirement_map = {
		entry.get("rowname"): entry for entry in requirements.get("block_requirements") or []
	}
	block_variable_map = {
		entry.get("rowname"): entry for entry in requirements.get("block_variables") or []
	}
	pdf_block_map = {entry.get("rowname"): entry for entry in requirements.get("pdf_block_mappings") or []}

	rows_payload: list[Dict[str, Any]] = []
	total = len(empfaenger_rows)
	for idx, row in enumerate(empfaenger_rows, start=1):
		context = serienbrief._build_context(
			row, idx, requirements, template, total=total, strict_variables=False
		)
		label = (
			getattr(row, "anzeigename", None)
			or getattr(row, "iteration_objekt", None)
			or getattr(row, "objekt", None)
			or cstr(getattr(row, "name", "") or "")
		)

		template_fields = []
		template_fields.extend(collect_requirement_entries(requirements.get("required_fields"), context))
		template_fields.extend(
			collect_requirement_entries(requirements.get("auto_fields"), context, is_auto=True)
		)

		template_variables: list[Dict[str, Any]] = []
		for variable in template_variable_defs:
			key = (
				variable.get("key")
				or frappe.scrub(cstr(variable.get("variable") or variable.get("label") or ""))
			)
			if not key:
				continue
			value = context.get(key)
			template_variables.append(
				{
					"key": key,
					"label": variable.get("label") or variable.get("variable") or key,
					"value": _serialize_overview_value(value),
				}
			)

		blocks_payload: list[Dict[str, Any]] = []
		for block_row in template_blocks:
			rowname = getattr(block_row, "name", None)
			block_name = getattr(block_row, "baustein", None)
			block_title = block_name or rowname
			requirement_entry = block_requirement_map.get(rowname) or {}
			variable_entry = block_variable_map.get(rowname) or {}
			pdf_entry = pdf_block_map.get(rowname) or {}

			block_context = frappe._dict(context)
			if block_name:
				try:
					block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", block_name)
					serienbrief._apply_block_variables(block_context, context, block_doc, block_row)
				except Exception:
					pass

			block_variables: list[Dict[str, Any]] = []
			for variable in variable_entry.get("variables") or []:
				key = (
					variable.get("key")
					or frappe.scrub(cstr(variable.get("variable") or variable.get("label") or ""))
				)
				if not key:
					continue
				value = block_context.get(key)
				block_variables.append(
					{
						"key": key,
						"label": variable.get("label") or variable.get("variable") or key,
						"value": _serialize_overview_value(value),
					}
				)

			pdf_fields: list[Dict[str, Any]] = []
			for mapping in pdf_entry.get("fields") or []:
				path = cstr(mapping.get("value_path") or "").strip()
				value = _resolve_value_path(path, block_context) if path else None
				if value in (None, ""):
					value = mapping.get("fallback_value")
				pdf_fields.append(
					{
						"pdf_field_name": mapping.get("pdf_field_name"),
						"value_path": path,
						"required": bool(mapping.get("required")),
						"value_type": mapping.get("value_type"),
						"value": _serialize_overview_value(value),
					}
				)

			blocks_payload.append(
				{
					"rowname": rowname,
					"block": block_name,
					"block_title": block_title,
					"requirements": collect_requirement_entries(
						requirement_entry.get("requirements") or [], context
					),
					"variables": block_variables,
					"pdf_fields": pdf_fields,
				}
			)

		rows_payload.append(
			{
				"index": idx,
				"label": label,
				"iteration": {
					"doctype": getattr(row, "iteration_doctype", None),
					"name": getattr(row, "iteration_objekt", None),
				},
				"template_fields": template_fields,
				"template_variables": template_variables,
				"blocks": blocks_payload,
			}
		)

	return {
		"vorlage": serienbrief.vorlage,
		"iteration_doctype": iteration_doctype,
		"rows": rows_payload,
	}


@frappe.whitelist()
def generate_pdf(
	docname: str,
	print_format: str | None = None,
	recreate_documents: int | str = 0,
	druck_schwarz_weiss: int | str = 0,
) -> str:
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError
	recreate_flag = bool(int(recreate_documents or 0))
	return doc.generate_pdf_file(
		print_format=print_format,
		recreate_documents=recreate_flag,
		druck_schwarz_weiss=bool(cint(druck_schwarz_weiss or 0)),
	)


@frappe.whitelist()
def generate_html(docname: str) -> str:
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError
	return doc.generate_html_file()


@frappe.whitelist()
def regenerate_dokumente(docname: str, submit_documents: int | str = 0) -> list[str]:
	durchlauf = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", durchlauf):
		raise frappe.PermissionError

	submit_flag = bool(int(submit_documents or 0))
	return durchlauf._ensure_dokumente(recreate=True, submit=submit_flag)


@frappe.whitelist()
def render_preview(doc: str | dict | None = None, docname: str | None = None) -> Dict[str, str]:
	"""Render Serienbrief HTML für den Editor, ohne Dateien zu speichern."""

	doc_data: dict[str, Any] | None = None
	if isinstance(doc, str):
		try:
			doc_data = json.loads(doc)
		except Exception:
			doc_data = None
	elif isinstance(doc, dict):
		doc_data = doc

	if doc_data:
		serienbrief = frappe.get_doc(doc_data)
	elif docname:
		serienbrief = frappe.get_doc("Serienbrief Durchlauf", docname)
	else:
		frappe.throw(_("Bitte übergebe einen Serienbrief."))

	html = serienbrief._render_full_html()
	return {"html": html}


# ---------------------------------------------------------------------------
# Serienbrief Durchlauf — React-Ausführungs-Viewer (Phase 1)
#
# Eigenständige React-UI, eingebettet als iframe ins Durchlauf-Formular
# (serienbrief_durchlauf.js) über die gemeinsame postMessage-Bridge. Diese Methoden
# liefern die Lauf-Daten, starten den Lauf als Hintergrund-Job und verwalten
# Empfänger/Variablen. E-Mail-Versand = Phase 2.
# ---------------------------------------------------------------------------

_RUN_COUNT_KEYS = {"Generiert": "generated", "Übersprungen": "skipped", "Fehler": "error"}


def _run_durchlauf_job(docname: str, druck_schwarz_weiss: int | str = 0) -> None:
	"""Enqueued: rendert alle Empfänger, schreibt Pro-Empfänger-Status + Fortschritt,
	setzt den Lauf-Status. Fehler einzelner Empfänger brechen den Lauf NICHT ab
	(das macht _create_dokumente); nur ein unerwarteter Infra-Fehler → Fehlgeschlagen."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	doc._druck_schwarz_weiss = bool(cint(druck_schwarz_weiss or 0))
	total = len(doc.get("iteration_objekte") or [])

	def progress_cb(idx, tot, counts):
		# Fortschritt in Batches persistieren (DB schonen); die UI pollt get_run_progress.
		if idx == tot or idx % 5 == 0:
			frappe.db.set_value("Serienbrief Durchlauf", docname, "progress", f"{idx}/{tot}", update_modified=False)
			frappe.db.commit()

	try:
		doc._ensure_dokumente(recreate=True, submit=False, strict_variables=False, progress_cb=progress_cb)
		counts = getattr(doc, "_last_run_counts", {"total": total, "generated": 0, "skipped": 0, "error": 0})
		done = counts.get("total", total)
		frappe.db.set_value(
			"Serienbrief Durchlauf",
			docname,
			{
				"status": "Generiert",
				"progress": f"{done}/{done}",
				"run_summary": json.dumps(counts),
				"last_run_on": now_datetime(),
			},
			update_modified=False,
		)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value("Serienbrief Durchlauf", docname, "status", "Fehlgeschlagen", update_modified=False)
		frappe.db.commit()
		frappe.log_error(frappe.get_traceback(), f"Serienbrief Durchlauf fehlgeschlagen: {docname}")
		raise


@frappe.whitelist()
def start_durchlauf_run(
	docname: str,
	regenerate: int | str = 1,
	druck_schwarz_weiss: int | str = 0,
) -> Dict[str, Any]:
	"""Startet den Lauf als Hintergrund-Job. Gibt sofort zurück; UI pollt get_run_progress."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", doc):
		raise frappe.PermissionError
	if int(getattr(doc, "docstatus", 0) or 0) != 0:
		frappe.throw(_("Der Durchlauf ist bereits abgeschlossen (eingereicht)."))
	if cstr(doc.get("status") or "") == "Läuft":
		return {"status": "Läuft", "already_running": True}

	total = len(doc.get("iteration_objekte") or [])
	if not doc.vorlage or not total:
		frappe.throw(_("Bitte wähle eine Vorlage und mindestens ein Iterations-Objekt."))

	frappe.db.set_value(
		"Serienbrief Durchlauf", docname, {"status": "Läuft", "progress": f"0/{total}"}, update_modified=False
	)
	frappe.db.commit()
	frappe.enqueue(
		"hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf._run_durchlauf_job",
		queue="long",
		timeout=3600,
		docname=docname,
		druck_schwarz_weiss=cint(druck_schwarz_weiss or 0),
		enqueue_after_commit=True,
	)
	return {"status": "Läuft", "total": total}


@frappe.whitelist()
def mark_durchlauf_failed(docname: str, note: str | None = None) -> Dict[str, Any]:
	"""Manueller Reset für hängende „Läuft"-Durchläufe (Worker-Crash, Timeout).
	Setzt Status auf „Fehlgeschlagen", merged einen ``manual_reset``-Eintrag
	in ``run_summary`` (ohne bestehende Zähler zu verlieren) und räumt
	verwaiste pending-neue Dokumente eines abgebrochenen Recreate-Versuchs.

	Server-side Guard: nur Drafts (``docstatus=0``) im Status ``Läuft`` dürfen
	zurückgesetzt werden — Frontend-Visibility allein reicht nicht, weil der
	RPC direkt aufrufbar ist und sonst auch ``Entwurf``/``Generiert``/submitted
	Durchläufe zerstört werden könnten.
	"""
	if not frappe.has_permission("Serienbrief Durchlauf", "write", doc=docname):
		raise frappe.PermissionError

	current = frappe.db.get_value(
		"Serienbrief Durchlauf", docname, ["status", "docstatus"], as_dict=True
	) or {}
	if int(current.get("docstatus") or 0) != 0:
		frappe.throw(_("Der Durchlauf ist bereits abgeschlossen (eingereicht) und kann nicht zurückgesetzt werden."))
	if cstr(current.get("status") or "") != "Läuft":
		frappe.throw(
			_("Nur Durchläufe im Status „Läuft\" können manuell als fehlgeschlagen markiert werden (aktuell: {0}).").format(
				current.get("status") or _("unbekannt")
			)
		)

	summary: Dict[str, Any] = {}
	raw = frappe.db.get_value("Serienbrief Durchlauf", docname, "run_summary")
	if raw:
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, dict):
				summary = parsed
			else:
				summary = {"prev_run_summary_raw": raw}
		except Exception:
			summary = {"prev_run_summary_raw": raw}
	summary["manual_reset"] = {
		"by": frappe.session.user,
		"at": now_datetime().isoformat(),
		"note": cstr(note or "").strip() or None,
	}

	frappe.db.set_value(
		"Serienbrief Durchlauf",
		docname,
		{"status": "Fehlgeschlagen", "run_summary": json.dumps(summary)},
		update_modified=False,
	)
	# Pending-neue Docs aus abgebrochenem Recreate-Versuch wegputzen (Bug 1.11).
	# Aktive Docs bleiben unberührt — der User soll sehen was vor dem Reset stand.
	try:
		doc = frappe.get_doc("Serienbrief Durchlauf", docname)
		doc._cleanup_pending_dokumente()
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"mark_durchlauf_failed: pending-Cleanup für {docname!r} fehlgeschlagen.",
		)
	frappe.db.commit()
	return {"status": "Fehlgeschlagen"}


@frappe.whitelist()
def get_run_progress(docname: str) -> Dict[str, Any]:
	"""Lauf-Status + Fortschritt + Zähler — für UI-Polling."""
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc=docname):
		raise frappe.PermissionError
	vals = frappe.db.get_value(
		"Serienbrief Durchlauf", docname, ["status", "progress", "run_summary"], as_dict=True
	) or {}
	counts: Dict[str, Any] = {}
	try:
		counts = json.loads(vals.get("run_summary") or "{}")
	except Exception:
		counts = {}
	return {"status": vals.get("status"), "progress": vals.get("progress"), "counts": counts}


@frappe.whitelist()
def get_durchlauf_data(docname: str) -> Dict[str, Any]:
	"""Header + Variablen + Empfängerliste (iteration_objekte ⋈ erzeugte Dokumente)."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError

	iteration_doctype = doc.iteration_doctype or (
		frappe.db.get_value("Serienbrief Vorlage", doc.vorlage, "haupt_verteil_objekt") if doc.vorlage else ""
	)

	# Erzeugte Dokumente nach Objekt gruppieren (jüngstes gewinnt). recreate_pending=1
	# sind unsichtbare Cutover-Reste (Bug 1.11) und gehören nicht in die Anzeige.
	dok_by_objekt: Dict[str, Any] = {}
	for d in frappe.get_all(
		"Serienbrief Dokument",
		filters={"durchlauf": docname, "recreate_pending": 0},
		fields=[
			"name", "objekt", "title", "status", "render_ms", "pages", "error_msg",
			"skip_reason", "warning", "recipient_email", "generated_on", "generated_pdf_file",
		],
		order_by="creation asc",
	):
		dok_by_objekt[d.objekt] = d

	recipients: List[Dict[str, Any]] = []
	overrides_out: Dict[str, Dict[str, Any]] = {}
	for it in doc.get("iteration_objekte") or []:
		objekt = cstr(getattr(it, "objekt", "") or "")
		if not objekt:
			continue
		name = None
		address = ""
		try:
			row = doc._build_empfaenger_row_from_iteration(it)
			if row:
				name = getattr(row, "anzeigename", None)
				address = doc._format_recipient_address(row)
		except Exception:
			pass
		d = dok_by_objekt.get(objekt)
		# Alt-Dokumente (vor Status-Feld) haben "Ausstehend", aber ein PDF → als
		# "Generiert" anzeigen, damit bestehende Durchläufe korrekt aussehen.
		rec_status = (d.status if d else "Ausstehend") or "Ausstehend"
		if d and rec_status == "Ausstehend" and cstr(getattr(d, "generated_pdf_file", "") or "").strip():
			rec_status = "Generiert"
		recipients.append(
			{
				"id": objekt,
				"name": (d.title if d else None) or name or objekt,
				"address": address,
				"recipient_email": (d.recipient_email if d else "") or "",
				"has_email": bool(d.recipient_email) if d else False,
				"status": rec_status,
				"pages": (d.pages if d else 0) or 0,
				"render_ms": (d.render_ms if d else 0) or 0,
				"error_msg": (d.error_msg if d else "") or "",
				"skip_reason": (d.skip_reason if d else "") or "",
				"warning": (d.warning if d else "") or "",
				"generated_on": cstr(d.generated_on) if (d and d.generated_on) else None,
				"has_pdf": bool(d and d.generated_pdf_file),
				"pdf_url": (d.generated_pdf_file if d else None) or None,
				"dokument": (d.name if d else None),
			}
		)
		ovw = _parse_variable_values(getattr(it, "variablen_werte", None))
		if ovw:
			overrides_out[objekt] = {
				k: (e.get("value") if e.get("value") is not None else "") for k, e in ovw.items()
			}

	# Variablen: Definition (Vorlage) + Default (Vorlage) + aktueller Durchlauf-Wert.
	variables_out: List[Dict[str, Any]] = []
	supports_druck_schwarz_weiss = False
	if doc.vorlage:
		template_doc = frappe.get_cached_doc("Serienbrief Vorlage", doc.vorlage)
		supports_druck_schwarz_weiss = _template_supports_druck_schwarz_weiss(template_doc)
		global_values = _parse_variable_values(doc.variablen_werte)
		vorlage_defaults = _parse_variable_values(getattr(template_doc, "variablen_werte", None))
		for v in _collect_template_variables(template_doc):
			key = v["key"]
			dv = vorlage_defaults.get(key, {})
			gv = global_values.get(key, {})
			variables_out.append(
				{
					"name": key,
					"label": v["label"],
					"type": v["variable_type"],
					"desc": v["description"],
					"default": dv.get("value") if dv.get("value") is not None else "",
					"value": gv.get("value") if gv.get("value") is not None else "",
				}
			)

	counts: Dict[str, Any] = {}
	try:
		counts = json.loads(doc.run_summary or "{}")
	except Exception:
		counts = {}

	return {
		"docname": docname,
		"title": doc.title,
		"status": doc.status or "Entwurf",
		"progress": doc.progress or "",
		"created_by": doc.owner,
		"vorlage": doc.vorlage,
		"vorlage_title": frappe.db.get_value("Serienbrief Vorlage", doc.vorlage, "title") if doc.vorlage else "",
		"kategorie": doc.kategorie,
		"iteration_doctype": iteration_doctype,
		"date": cstr(doc.date) if doc.date else None,
		"docstatus": int(getattr(doc, "docstatus", 0) or 0),
		"supports_druck_schwarz_weiss": supports_druck_schwarz_weiss,
		"can_write": bool(frappe.has_permission("Serienbrief Durchlauf", "write", doc))
		and int(getattr(doc, "docstatus", 0) or 0) == 0,
		"variables": variables_out,
		"per_recipient_overrides": overrides_out,
		"recipients": recipients,
		"counts": counts,
	}


@frappe.whitelist()
def set_run_variables(
	docname: str, variables: str | list | dict | None = None, per_recipient_overrides: str | dict | None = None
) -> Dict[str, Any]:
	"""Globale Variablenwerte + Pro-Empfänger-Overrides speichern (Format passend zu
	_parse_variable_values: {key: {"value": …}})."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", doc):
		raise frappe.PermissionError
	if int(getattr(doc, "docstatus", 0) or 0) != 0:
		frappe.throw(_("Der Durchlauf ist bereits abgeschlossen (eingereicht)."))

	if variables is not None:
		if isinstance(variables, str):
			variables = json.loads(variables or "[]")
		items = variables.items() if isinstance(variables, dict) else [
			(v.get("name"), v.get("value")) for v in variables
		]
		vw = {cstr(k): {"value": val} for k, val in items if k and val not in (None, "")}
		frappe.db.set_value(
			"Serienbrief Durchlauf", docname, "variablen_werte", json.dumps(vw) if vw else "", update_modified=False
		)

	if per_recipient_overrides is not None:
		if isinstance(per_recipient_overrides, str):
			per_recipient_overrides = json.loads(per_recipient_overrides or "{}")
		for it in doc.get("iteration_objekte") or []:
			objekt = cstr(getattr(it, "objekt", "") or "")
			ov = (per_recipient_overrides or {}).get(objekt) or {}
			ovw = {cstr(k): {"value": val} for k, val in ov.items() if val not in (None, "")}
			frappe.db.set_value(
				"Serienbrief Iterationsobjekt", it.name,
				"variablen_werte", json.dumps(ovw) if ovw else "", update_modified=False,
			)

	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def add_recipients(docname: str, objekte: str | list | None = None) -> Dict[str, Any]:
	"""Iterations-Objekte zum Durchlauf hinzufügen (Duplikate werden ignoriert).

	Sicherheit: nur existierende UND für den User lesbare Objekte werden aufgenommen —
	sonst könnte ein User mit Schreibrecht auf den Durchlauf nicht-lesbare Ziel-Dokumente
	rendern lassen und deren Daten über die erzeugten PDFs einsehen."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", doc):
		raise frappe.PermissionError
	if int(getattr(doc, "docstatus", 0) or 0) != 0:
		frappe.throw(_("Der Durchlauf ist bereits abgeschlossen (eingereicht)."))
	if isinstance(objekte, str):
		objekte = json.loads(objekte or "[]")

	dt = cstr(doc.iteration_doctype or "").strip() or cstr(
		frappe.db.get_value("Serienbrief Vorlage", doc.vorlage, "haupt_verteil_objekt") if doc.vorlage else ""
	).strip()
	if not dt or not frappe.db.exists("DocType", dt):
		frappe.throw(_("Bitte zuerst eine Vorlage mit gültigem Iterations-Doctype wählen."))

	existing = {cstr(getattr(it, "objekt", "") or "") for it in doc.get("iteration_objekte") or []}
	rejected: list[str] = []
	added = 0
	for objekt in objekte or []:
		objekt = cstr(objekt or "").strip()
		if not objekt or objekt in existing:
			continue
		if not frappe.db.exists(dt, objekt) or not frappe.has_permission(dt, "read", doc=objekt):
			rejected.append(objekt)
			continue
		doc.append("iteration_objekte", {"iteration_doctype": dt, "objekt": objekt})
		existing.add(objekt)
		added += 1

	if rejected:
		# Atomar: nichts speichern, wenn ein Objekt nicht zulässig ist (klare Rückmeldung).
		frappe.throw(
			_("Diese Objekte können nicht hinzugefügt werden (nicht vorhanden oder keine Leseberechtigung): {0}").format(
				", ".join(rejected)
			),
			frappe.PermissionError,
		)
	if added:
		doc.save(ignore_permissions=True)
	return {"added": added}


@frappe.whitelist()
def remove_recipients(docname: str, objekte: str | list | None = None) -> Dict[str, Any]:
	"""Iterations-Objekte aus dem Durchlauf entfernen."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", doc):
		raise frappe.PermissionError
	if int(getattr(doc, "docstatus", 0) or 0) != 0:
		frappe.throw(_("Der Durchlauf ist bereits abgeschlossen (eingereicht)."))
	if isinstance(objekte, str):
		objekte = json.loads(objekte or "[]")
	remove = {cstr(o or "").strip() for o in (objekte or [])}
	kept = [it for it in (doc.get("iteration_objekte") or []) if cstr(getattr(it, "objekt", "") or "") not in remove]
	if len(kept) != len(doc.get("iteration_objekte") or []):
		doc.set("iteration_objekte", kept)
		doc.save(ignore_permissions=True)
	return {"removed": True}


@frappe.whitelist()
def get_available_recipients(docname: str, query: str | None = None, limit: int = 25) -> Dict[str, Any]:
	"""Iterations-Objekte, die noch nicht im Durchlauf sind (für „Empfänger hinzufügen")."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError
	dt = cstr(doc.iteration_doctype or "").strip() or cstr(
		frappe.db.get_value("Serienbrief Vorlage", doc.vorlage, "haupt_verteil_objekt") if doc.vorlage else ""
	).strip()
	if not dt or not frappe.db.exists("DocType", dt) or not frappe.has_permission(dt, "read"):
		return {"items": [], "doctype": dt}

	already = {cstr(getattr(it, "objekt", "") or "") for it in doc.get("iteration_objekte") or []}
	meta = frappe.get_meta(dt)
	title_field = meta.get_title_field()
	fields = ["name"] + ([title_field] if title_field and title_field != "name" else [])
	q = cstr(query or "").strip()
	or_filters = None
	if q:
		or_filters = [["name", "like", f"%{q}%"]]
		if title_field and title_field != "name":
			or_filters.append([title_field, "like", f"%{q}%"])
	rows = frappe.get_list(dt, fields=fields, or_filters=or_filters, limit=cint(limit) or 25, order_by="modified desc")
	items = [
		{"id": r["name"], "label": (r.get(title_field) if title_field and title_field != "name" else None) or r["name"]}
		for r in rows
		if r["name"] not in already
	]
	return {"items": items, "doctype": dt}


@frappe.whitelist()
def get_merged_pdf(docname: str, druck_schwarz_weiss: int | str = 0) -> Dict[str, str]:
	"""Sammel-PDF im gewählten Druckmodus erzeugen."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "read", doc):
		raise frappe.PermissionError
	file_url = doc.generate_pdf_file(
		print_format="Serienbrief Dokument",
		recreate_documents=True,
		druck_schwarz_weiss=bool(cint(druck_schwarz_weiss or 0)),
	)
	return {"file_url": file_url}


@frappe.whitelist()
def create_durchlauf(
	title: str | None = None, vorlage: str | None = None, kategorie: str | None = None
) -> Dict[str, Any]:
	"""Neuen Durchlauf-Entwurf aus einer Vorlage anlegen (Vollbild-UI „Neuer Durchlauf").
	Kategorie/Iterations-Doctype werden aus der Vorlage übernommen."""
	if not frappe.has_permission("Serienbrief Durchlauf", "create"):
		raise frappe.PermissionError
	vorlage = cstr(vorlage or "").strip()
	if not vorlage or not frappe.db.exists("Serienbrief Vorlage", vorlage):
		frappe.throw(_("Bitte eine gültige Vorlage wählen."))
	if not frappe.has_permission("Serienbrief Vorlage", "read", doc=vorlage):
		raise frappe.PermissionError

	v = frappe.db.get_value(
		"Serienbrief Vorlage", vorlage, ["kategorie", "haupt_verteil_objekt", "title"], as_dict=True
	) or frappe._dict()
	doc = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"title": cstr(title or "").strip() or cstr(v.get("title") or vorlage),
			"vorlage": vorlage,
			"kategorie": cstr(kategorie or "").strip() or v.get("kategorie"),
			"iteration_doctype": v.get("haupt_verteil_objekt") or "",
			"date": today(),
			"status": "Entwurf",
		}
	)
	doc.insert()
	return {"docname": doc.name}


@frappe.whitelist()
def update_durchlauf(docname: str, title: str | None = None) -> Dict[str, Any]:
	"""Kopfdaten eines Durchlauf-Entwurfs ändern (aktuell nur Titel)."""
	doc = frappe.get_doc("Serienbrief Durchlauf", docname)
	if not frappe.has_permission("Serienbrief Durchlauf", "write", doc):
		raise frappe.PermissionError
	if int(getattr(doc, "docstatus", 0) or 0) != 0:
		frappe.throw(_("Der Durchlauf ist bereits abgeschlossen (eingereicht)."))
	if title is not None:
		new_title = cstr(title).strip()
		if new_title:
			frappe.db.set_value("Serienbrief Durchlauf", docname, "title", new_title)
	return {"ok": True}


@frappe.whitelist()
def list_vorlagen(
	query: str | None = None,
	limit: int = 50,
	pinned_id: str | None = None,
) -> Dict[str, Any]:
	"""Vorlagen für den „Neuer Durchlauf"-Picker (berechtigungsgefiltert).

	``pinned_id``: Wenn gesetzt, wird diese Vorlage IMMER ans Anfang der
	Ergebnisse gestellt — auch wenn sie ausserhalb der ersten ``limit``
	Treffer oder ausserhalb des Such-Filters laege. Wird vom Browser
	"Durchlauf starten" genutzt, damit die vorausgewaehlte Vorlage in der
	Picker-Liste sichtbar markiert ist (sonst wirkt der Picker leer-
	ausgewaehlt, obwohl ``sel`` technisch gesetzt ist).
	"""
	if not frappe.has_permission("Serienbrief Vorlage", "read"):
		raise frappe.PermissionError
	q = cstr(query or "").strip()
	or_filters = None
	if q:
		or_filters = [["title", "like", f"%{q}%"], ["name", "like", f"%{q}%"]]
	rows = frappe.get_list(
		"Serienbrief Vorlage",
		filters={"docstatus": ["<", 2]},
		or_filters=or_filters,
		fields=["name", "title", "kategorie", "haupt_verteil_objekt"],
		order_by="title asc",
		limit_page_length=cint(limit) or 50,
	)

	# Pinned-ID einmalig prepend, wenn nicht schon in den Ergebnissen.
	pinned = cstr(pinned_id or "").strip()
	if pinned and not any(r.name == pinned for r in rows):
		extra = frappe.get_list(
			"Serienbrief Vorlage",
			filters={"name": pinned, "docstatus": ["<", 2]},
			fields=["name", "title", "kategorie", "haupt_verteil_objekt"],
			limit_page_length=1,
		)
		if extra:
			rows = list(extra) + list(rows)

	return {
		"items": [
			{
				"id": r.name,
				"title": r.title or r.name,
				"kategorie": r.kategorie or "",
				"haupt_verteil_objekt": r.haupt_verteil_objekt or "",
			}
			for r in rows
		]
	}
