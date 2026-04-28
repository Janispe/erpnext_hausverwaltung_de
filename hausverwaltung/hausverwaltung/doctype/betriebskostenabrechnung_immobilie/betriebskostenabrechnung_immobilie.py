import hashlib
import json
from typing import Dict, List, Optional, Set

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, cstr
from frappe.utils.pdf import get_pdf

from hausverwaltung.hausverwaltung.utils.serienbrief_print import normalize_print_format_name
from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_for_print_format

SERIENBRIEF_PRINT_FORMAT_FIELDNAME = "hv_serienbrief_vorlage"
PRINT_BUNDLE_CSS_PATH = "/assets/frappe/css/print.bundle.css"
DRAFT_EMAIL_SEND_AFTER = "2099-01-01 00:00:00"


class BetriebskostenabrechnungImmobilie(Document):
	@property
	def mieter_abrechnungen(self) -> List[Dict[str, object]]:
		"""Virtuelle Tabellenzeilen für die Formular-Übersicht."""
		if not self.name:
			return []
		return get_mieter_abrechnungen(self.name)

	def _cleanup_mieter_abrechnungen(self, *, allow_delete: bool = True) -> None:
		"""Storniert/loescht verknuepfte Mieter-Abrechnungen."""
		children = frappe.get_all(
			"Betriebskostenabrechnung Mieter",
			filters={"immobilien_abrechnung": self.name},
			fields=["name", "docstatus"],
		)
		for row in children or []:
			nm = row.get("name")
			if not nm:
				continue
			try:
				doc = frappe.get_doc("Betriebskostenabrechnung Mieter", nm)
				doc.flags.allow_cancel_via_head = True
				doc.flags.ignore_permissions = True
				if doc.docstatus == 1:
					doc.cancel()
					if allow_delete:
						frappe.delete_doc("Betriebskostenabrechnung Mieter", nm, ignore_permissions=True, force=1)
				elif doc.docstatus == 0 and allow_delete:
					frappe.delete_doc("Betriebskostenabrechnung Mieter", nm, ignore_permissions=True, force=1)
			except Exception as e:
				frappe.throw(f"Mieter-Abrechnung konnte nicht storniert/gelöscht werden ({nm}): {e}")

	def after_insert(self):
		"""Beim Anlegen automatisch alle Mieter‑Abrechnungen als Entwurf erzeugen."""
		if not (self.immobilie and self.von and self.bis):
			frappe.throw("Bitte Immobilie, Von und Bis ausfüllen.")
		stichtag = self.stichtag or self.bis
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import create_bk_abrechnungen_immobilie
		res = create_bk_abrechnungen_immobilie(
			von=cstr(self.von),
			bis=cstr(self.bis),
			immobilie=self.immobilie,
			submit=False,
			stichtag=cstr(stichtag),
			head=self.name,
			split_by_mietvertrag=True,
		)
		# Nach Erzeugung: Zusammenfassungen berechnen
		self._populate_summary()
		self.save(ignore_permissions=True)
	def on_submit(self):
		"""Beim Submit: alle verknüpften Mieter-Abrechnungen einreichen und erst dann Ausgleichsbelege erzeugen."""
		children = frappe.get_all(
			"Betriebskostenabrechnung Mieter",
			filters={"immobilien_abrechnung": self.name},
			pluck="name",
		)
		for nm in children:
			# Submit, falls noch Entwurf
			doc = frappe.get_doc("Betriebskostenabrechnung Mieter", nm)
			if doc.docstatus == 0:
				doc.flags.skip_auto_settle = True  # Settlement kommt nach Submit durch Header
				doc.submit()
		# Nach Submit aller: Ausgleichsbelege erzeugen
		for nm in children:
			from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import create_bk_settlement_documents
			create_bk_settlement_documents(nm, consolidate_unpaid=True)

	def before_cancel(self):
		"""Beim Storno: zuerst alle Mieter-Abrechnungen inkl. Ausgleichsbelege stornieren/löschen.

		Das verhindert, dass der Header durch verknüpfte, eingereichte Kinder am Storno gehindert wird.
		"""
		self._cleanup_mieter_abrechnungen(allow_delete=True)
		# Backlink-Check bei Cancel ueberspringen, nachdem Kinder bereinigt wurden
		self.flags.ignore_links = True

	def on_trash(self):
		"""Beim Loeschen: verknuepfte Mieter-Abrechnungen zuerst entfernen."""
		self._cleanup_mieter_abrechnungen(allow_delete=True)

	def _populate_summary(self):
		"""Füllt Summen und die Detailaufschlüsselung der Verteilung."""
		# Kosten pro Art über Allocation ermitteln
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
			allocate_kosten_auf_wohnungen,
		)
		alloc = allocate_kosten_auf_wohnungen(von=cstr(self.von), bis=cstr(self.bis), immobilie=self.immobilie, stichtag=cstr(self.stichtag or self.bis))
		matrix = alloc.get("matrix") or {}
		# Summe je Art aggregieren
		per_art = {}
		for whg, arts in matrix.items():
			for art, betrag in (arts or {}).items():
				per_art[art] = per_art.get(art, 0.0) + float(betrag or 0)
		# Tabelle setzen
		self.set("kosten_pro_art", [])
		total_costs = 0.0
		for art, betrag in sorted(per_art.items()):
			amount = round(float(betrag or 0), 2)
			total_costs += amount
			self.append("kosten_pro_art", {"betriebskostenart": art, "betrag": amount})
		self.gesamtkosten = round(total_costs, 2)

		# Vorauszahlungen aggregieren aus Mieter-Abrechnungen
		children = frappe.get_all(
			"Betriebskostenabrechnung Mieter",
			filters={"immobilien_abrechnung": self.name},
			fields=["name", "vorrauszahlungen"],
		)
		total_pre = 0.0
		for r in children or []:
			try:
				total_pre += float(r.get("vorrauszahlungen") or 0)
			except Exception:
				continue
		self.gesamt_vorauszahlungen = round(total_pre, 2)
		self.gesamt_differenz = round(self.gesamtkosten - self.gesamt_vorauszahlungen, 2)

		# Zähler-Summen: Summe letzter - erster Stand je ZählerTyp über alle Zähler in den Wohnungen der Immobilie
		self.set("zaehler_summen", [])
		wohnungen = frappe.get_all("Wohnung", filters={"immobilie": self.immobilie}, pluck="name")
		sums = {}
		if wohnungen and self.von and self.bis:
			period_start = cstr(self.von)
			period_end_excl = cstr(add_days(self.bis, 1))
			zuordnungen = frappe.get_all(
				"Zaehler Zuordnung",
				filters={
					"bezugsobjekt_typ": "Wohnung",
					"bezugsobjekt": ("in", wohnungen),
					"von": ("<", period_end_excl),
				},
				fields=["zaehler", "von", "bis"],
			)
			zaehler_names = []
			seen = set()
			for r in zuordnungen or []:
				# Overlap check with [period_start, period_end_excl)
				if r.get("bis") and cstr(r.get("bis")) <= period_start:
					continue
				zname = r.get("zaehler")
				if zname and zname not in seen:
					seen.add(zname)
					zaehler_names.append(zname)

			zaehler = (
				frappe.get_all(
					"Zaehler",
					filters={"name": ("in", zaehler_names)},
					fields=["name", "zaehlerart"],
				)
				if zaehler_names
				else []
			)
			for z in zaehler or []:
				st = frappe.get_all(
					"Zaehlerstand",
					filters={"parent": z["name"]},
					fields=["datum", "zaehlerstand"],
					order_by="datum asc",
				)
				if st:
					try:
						start = float(st[0]["zaehlerstand"] or 0)
						end = float(st[-1]["zaehlerstand"] or 0)
						diff = end - start
						art = z.get("zaehlerart") or _("Unbekannt")
						sums[art] = sums.get(art, 0.0) + diff
					except Exception:
						pass
		for art, s in sorted(sums.items()):
			self.append("zaehler_summen", {"zaehlerart": art, "summe": round(float(s or 0), 3)})


@frappe.whitelist()
def get_mieter_abrechnungen(name: str) -> List[Dict[str, object]]:
	"""Liefert zugeordnete Mieter-Abrechnungen für die Anzeige im Header."""
	if not name:
		return []
	doc = frappe.get_doc("Betriebskostenabrechnung Immobilie", name)
	doc.check_permission("read")
	rows = frappe.get_all(
		"Betriebskostenabrechnung Mieter",
		filters={"immobilien_abrechnung": name},
		fields=["name", "wohnung", "docstatus", "vorrauszahlungen"],
		order_by="wohnung asc",
	)
	parent_names = [r.get("name") for r in rows if r.get("name")]
	anteil_map: Dict[str, float] = {}
	if parent_names:
		result = frappe.db.sql(
			"""
			SELECT parent, SUM(betrag) AS total
			FROM `tabAbrechnungsposten`
			WHERE parenttype = 'Betriebskostenabrechnung Mieter'
			  AND parent IN %(parents)s
			GROUP BY parent
			""",
			{"parents": tuple(parent_names)},
			as_dict=True,
		)
		for r in result or []:
			try:
				anteil_map[r.get("parent")] = round(float(r.get("total") or 0), 2)
			except Exception:
				anteil_map[r.get("parent")] = 0.0
	status_labels = {
		0: _("Entwurf"),
		1: _("Eingereicht"),
		2: _("Storniert"),
	}
	result: List[Dict[str, object]] = []
	for row in rows:
		name = row.get("name")
		anteil = anteil_map.get(name, 0.0)
		try:
			vorauszahlung = round(float(row.get("vorrauszahlungen") or 0), 2)
		except Exception:
			vorauszahlung = 0.0
		try:
			guthaben_nachzahlung = round(float(anteil) - float(vorauszahlung), 2)
		except Exception:
			guthaben_nachzahlung = 0.0
		result.append(
			{
				"name": name,
				"wohnung": row.get("wohnung"),
				"docstatus": row.get("docstatus"),
				"status_label": status_labels.get(row.get("docstatus")),
				"vorauszahlung": vorauszahlung,
				"anteil": anteil,
				"guthaben_nachzahlung": guthaben_nachzahlung,
			}
		)
	return result


@frappe.whitelist()
def get_verteilungsbasis(name: str) -> Dict[str, List[Dict[str, object]]]:
	"""Liefert Wohnflächen und Festbeträge zum Stichtag für die Verteilungsbasis."""
	if not name:
		return {"qm_rows": [], "festbetrag_rows": []}
	doc = frappe.get_doc("Betriebskostenabrechnung Immobilie", name)
	doc.check_permission("read")

	from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
		_prorated_festbetrag_rows,
		_wohnungen_in_haus,
		_flaeche_qm,
	)

	stichtag = cstr(doc.stichtag or doc.bis)
	wohnungen = sorted(_wohnungen_in_haus(immobilie=doc.immobilie))
	qm_rows: List[Dict[str, object]] = []
	for wohnung in wohnungen:
		qm_rows.append(
			{
				"wohnung": wohnung,
				"qm": round(float(_flaeche_qm(wohnung, stichtag) or 0), 2),
			}
		)

	festbetrag_rows = _prorated_festbetrag_rows(
		immobilie=doc.immobilie,
		von=cstr(doc.von),
		bis=cstr(doc.bis),
	) if wohnungen else []

	festbetrag_by_key: Dict[tuple[str, str], float] = {}
	for row in festbetrag_rows or []:
		wohnung = cstr(row.get("wohnung") or "").strip()
		kostenart = cstr(row.get("kostenart") or "").strip()
		if not (wohnung and kostenart):
			continue
		key = (wohnung, kostenart)
		festbetrag_by_key[key] = round(
			float(festbetrag_by_key.get(key, 0.0)) + float(row.get("betrag") or 0),
			2,
		)

	return {
		"qm_rows": qm_rows,
		"festbetrag_rows": [
			{
				"wohnung": wohnung,
				"kostenart": kostenart,
				"betrag": betrag,
			}
			for (wohnung, kostenart), betrag in sorted(
				festbetrag_by_key.items(),
				key=lambda item: (item[0][1], item[0][0]),
			)
		],
	}


def _get_mieter_recipients(abrechnung: "Document") -> List[str]:
	"""Ermittelt E-Mail-Empfänger aus den Vertragspartnern (Contact.email_id) der Mieterabrechnung."""
	recipients: Set[str] = set()
	for row in getattr(abrechnung, "mieter", []) or []:
		rolle = (row.get("rolle") or "").strip()
		if rolle == "Ausgezogen":
			continue
		contact = (row.get("mieter") or "").strip()
		if not contact:
			continue
		email = frappe.db.get_value("Contact", contact, "email_id")
		if email and isinstance(email, str) and email.strip():
			recipients.add(email.strip())
	return sorted(recipients)


def _render_abrechnung_pdf(name: str, print_format: Optional[str] = None) -> bytes:
	# Wichtig: `frappe.get_print` nutzt (bei direktem Python-Aufruf) nicht das Web-Printview-Override.
	# Damit Serienbrief-Vorlagen auch im E-Mail-Anhang funktionieren, rendern wir bei Bedarf
	# den Serienbrief direkt (wenn das Print Format auf eine Serienbrief Vorlage zeigt).
	print_format_name = (print_format or "").strip() or None
	serienbrief_html = render_serienbrief_for_print_format(
		print_format_name,
		docname=name,
		doctype="Betriebskostenabrechnung Mieter",
	)
	if serienbrief_html:
		return get_pdf(serienbrief_html)

	html = frappe.get_print(
		doctype="Betriebskostenabrechnung Mieter",
		name=name,
		print_format=normalize_print_format_name(print_format_name),
	)
	return get_pdf(html)


def _get_or_create_serienbrief_print_format(serienbrief_vorlage: str) -> str:
	"""Gibt einen Print Format-Namen zurück, der die Serienbrief Vorlage referenziert.

	Wir nutzen das bestehende Printview-Override (`hv_serienbrief_vorlage` auf Print Format),
	damit auch `download_multi_pdf` (via `frappe.get_print`) funktioniert.
	"""
	vorlage = (serienbrief_vorlage or "").strip()
	if not vorlage:
		frappe.throw(_("Bitte wählen Sie eine Serienbrief Vorlage."))

	if not frappe.db.exists("Serienbrief Vorlage", vorlage):
		frappe.throw(_("Serienbrief Vorlage '{0}' wurde nicht gefunden.").format(vorlage))

	if not frappe.db.has_column("Print Format", SERIENBRIEF_PRINT_FORMAT_FIELDNAME):
		frappe.throw(
			_(
				"Print Format unterstützt keine Serienbrief Vorlage (Custom Field '{0}' fehlt). "
				"Bitte Migration/Patches ausführen."
			).format(SERIENBRIEF_PRINT_FORMAT_FIELDNAME)
		)

	template_dt = (
		frappe.db.get_value("Serienbrief Vorlage", vorlage, "haupt_verteil_objekt") or ""
	).strip()
	if template_dt and template_dt != "Betriebskostenabrechnung Mieter":
		frappe.throw(
			_("Serienbrief Vorlage {0} erwartet Doctype {1}, benötigt wird aber {2}.").format(
				vorlage, template_dt, "Betriebskostenabrechnung Mieter"
			)
		)

	existing = frappe.get_all(
		"Print Format",
		filters={
			"doc_type": "Betriebskostenabrechnung Mieter",
			SERIENBRIEF_PRINT_FORMAT_FIELDNAME: vorlage,
		},
		pluck="name",
		order_by="modified desc",
		limit_page_length=1,
	)
	if existing:
		name = existing[0]
		try:
			disabled = frappe.db.get_value("Print Format", name, "disabled")
			if cint(disabled):
				frappe.db.set_value("Print Format", name, "disabled", 0, update_modified=False)
		except Exception:
			pass
		return name

	digest = hashlib.sha1(vorlage.encode("utf-8")).hexdigest()[:8]
	prefix = "Betriebskostenabrechnung Mieter - Serienbrief - "
	max_len = 140
	base_name = f"{prefix}{vorlage}"
	if len(base_name) > max_len:
		available = max_len - len(prefix) - 1 - len(digest)
		short = (vorlage[: max(0, available)]).rstrip()
		base_name = f"{prefix}{short}-{digest}".rstrip(" -")
	name = base_name
	if frappe.db.exists("Print Format", name):
		alt = f"{name}-{digest}"
		name = alt if len(alt) <= max_len else f"{name[: max_len - len(digest) - 1]}-{digest}"

	doc = frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": name,
			"doc_type": "Betriebskostenabrechnung Mieter",
			"standard": "No",
			"custom_format": 0,
			"disabled": 0,
			SERIENBRIEF_PRINT_FORMAT_FIELDNAME: vorlage,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _build_print_html_document(
	body: str,
	print_style: str = "",
	title: str = "Print",
	auto_print: bool = False,
) -> str:
	script = ""
	if auto_print:
		script = """
<script>
window.addEventListener("load", () => {
	try { window.focus(); } catch (e) {}
	try { window.print(); } catch (e) {}
});
</script>
""".strip()

	extra_css = """
.hv-print-break {
	break-after: page;
	page-break-after: always;
	height: 0;
}
""".strip()
	style_tag = ""
	if (print_style or "").strip() or extra_css:
		style_tag = f"<style>{print_style or ''}\n{extra_css}</style>"
	return f"""<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>{frappe.utils.escape_html(title or "Print")}</title>
	<link rel="stylesheet" href="{PRINT_BUNDLE_CSS_PATH}">
	{style_tag}
</head>
<body>
	{body}
	{script}
</body>
</html>"""


@frappe.whitelist()
def download_batch_print_html(
	doctype: str,
	names: str,
	print_format: Optional[str] = None,
	serienbrief_vorlage: Optional[str] = None,
	trigger_print: int | str = 1,
	no_letterhead: int | str = 0,
	letterhead: Optional[str] = None,
) -> None:
	"""Gibt eine HTML-Seite zurück, die den Browser-Print-Dialog automatisch öffnet.

	- Bei `serienbrief_vorlage`: rendert einen Serienbrief über mehrere Iterationsobjekte.
	- Sonst: rendert Standard-Print-HTML pro Dokument und hängt es hintereinander.
	"""
	doctype = (doctype or "").strip()
	if not doctype:
		frappe.throw(_("Parameter 'doctype' fehlt."))

	try:
		doc_names = frappe.parse_json(names) if isinstance(names, str) else names
	except Exception:
		doc_names = None
	if not isinstance(doc_names, list) or not doc_names:
		frappe.throw(_("Parameter 'names' muss eine JSON-Liste sein."))

	auto_print = bool(cint(trigger_print))

	if (serienbrief_vorlage or "").strip():
		# Serienbrief: ein Dokument mit mehreren Seiten
		from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
			SerienbriefDurchlauf,
		)

		vorlage = (serienbrief_vorlage or "").strip()
		if doctype != "Betriebskostenabrechnung Mieter":
			frappe.throw(_("Serienbrief-Druck wird aktuell nur für Betriebskostenabrechnung Mieter unterstützt."))

		# Permission: read/print pro Dokument
		for nm in doc_names:
			doc = frappe.get_doc(doctype, nm)
			if not frappe.has_permission(doctype, "print", doc) and not frappe.has_permission(doctype, "read", doc):
				raise frappe.PermissionError

		serienbrief_doc: SerienbriefDurchlauf = frappe.get_doc(
			{
				"doctype": "Serienbrief Durchlauf",
				"title": _("Betriebskostenabrechnungen"),
				"vorlage": vorlage,
				"iteration_doctype": doctype,
				"iteration_objekte": [
					{"doctype": "Serienbrief Iterationsobjekt", "iteration_doctype": doctype, "objekt": nm}
					for nm in doc_names
				],
			}
		)
		serienbrief_doc.flags.ignore_mandatory = True
		serienbrief_doc.flags.ignore_permissions = True
		html = serienbrief_doc._render_full_html()
		if auto_print:
			# Script vor </body> einfügen (Serienbrief liefert vollständiges HTML)
			inject = """
<script>
window.addEventListener("load", () => {
	try { window.focus(); } catch (e) {}
	try { window.print(); } catch (e) {}
});
</script>
""".strip()
			if "</body>" in html:
				html = html.replace("</body>", f"{inject}\n</body>")
			else:
				html = html + "\n" + inject

		frappe.response["type"] = "download"
		frappe.response["filename"] = "betriebskostenabrechnungen.html"
		frappe.response["filecontent"] = html.encode("utf-8")
		frappe.response["content_type"] = "text/html; charset=utf-8"
		frappe.response["display_content_as"] = "inline"
		return

	# Standard-Print: get_html_and_style liefert "body html" + style
	from frappe.www import printview as core_printview

	combined_docs: List[str] = []
	style = ""
	title = _("Druck")
	for idx, nm in enumerate(doc_names):
		res = core_printview.get_html_and_style(
			doc=doctype,
			name=nm,
			print_format=print_format,
			no_letterhead=bool(cint(no_letterhead)),
			letterhead=letterhead,
			trigger_print=False,
			style=None,
			settings=json.dumps({}),
		)
		html = (res or {}).get("html") or ""
		if not html:
			continue
		if not style:
			style = (res or {}).get("style") or ""
		combined_docs.append(html)

	parts: List[str] = ['<div class="print-format-gutter"><div class="print-format">']
	for idx, html in enumerate(combined_docs):
		parts.append(html)
		if idx < len(combined_docs) - 1:
			parts.append('<div class="hv-print-break"></div>')
	parts.append("</div></div>")

	full_body = "\n".join(parts) or "<p>No content</p>"
	full_html = _build_print_html_document(body=full_body, print_style=style, title=title, auto_print=auto_print)

	frappe.response["type"] = "download"
	frappe.response["filename"] = "druck.html"
	frappe.response["filecontent"] = full_html.encode("utf-8")
	frappe.response["content_type"] = "text/html; charset=utf-8"
	frappe.response["display_content_as"] = "inline"


def _default_email_subject(child: Dict[str, object], head: "Document") -> str:
	von = cstr(head.get("von") or "").strip()
	bis = cstr(head.get("bis") or "").strip()
	wohnung = cstr(child.get("wohnung") or "").strip()
	if wohnung:
		return _("Betriebskostenabrechnung {0} bis {1} – {2}").format(von or "?", bis or "?", wohnung)
	return _("Betriebskostenabrechnung {0} bis {1}").format(von or "?", bis or "?")


def _default_email_message() -> str:
	return _("Guten Tag,\n\nanbei erhalten Sie Ihre Betriebskostenabrechnung als PDF.\n\nMit freundlichen Grüßen")


@frappe.whitelist()
def dispatch_mieter_abrechnungen(
	name: str,
	mode: str = "auto",
	serienbrief_vorlage: Optional[str] = None,
	print_format: Optional[str] = None,
	email_subject: Optional[str] = None,
	email_message: Optional[str] = None,
	also_print_emailed: int = 0,
) -> Dict[str, object]:
	"""Versendet/erstellt Druck-PDFs für alle Mieterabrechnungen eines Kopfes.

	mode:
	  - "auto": Versandweg aus Mietvertrag (Email -> Mail, sonst Druck)
	  - "print_all": alle drucken (keine E-Mails)
	"""
	if not name:
		frappe.throw(_("Parameter 'name' fehlt."))

	head = frappe.get_doc("Betriebskostenabrechnung Immobilie", name)
	head.check_permission("write")
	if head.docstatus != 1:
		frappe.throw(_("Bitte zuerst die Betriebskostenabrechnung Immobilie einreichen (Submit)."))

	children = frappe.get_all(
		"Betriebskostenabrechnung Mieter",
		filters={"immobilien_abrechnung": name},
		fields=["name", "mietvertrag", "wohnung", "docstatus"],
		order_by="wohnung asc",
	)

	mode = (mode or "auto").strip()
	also_print_emailed = cint(also_print_emailed)
	subject_override = (email_subject or "").strip() or None
	message = (email_message or "").strip() or _default_email_message()
	effective_print_format = (print_format or "").strip() or None
	if (serienbrief_vorlage or "").strip():
		effective_print_format = _get_or_create_serienbrief_print_format(serienbrief_vorlage)

	emailed: List[str] = []
	queued: List[Dict[str, str]] = []
	print_names: List[str] = []
	warnings: List[str] = []
	errors: List[str] = []

	for child in children or []:
		child_name = child.get("name")
		if not child_name:
			continue

		if cint(child.get("docstatus")) != 1:
			warnings.append(_("{0}: nicht eingereicht (übersprungen)").format(child_name))
			continue

		if mode == "print_all":
			print_names.append(child_name)
			continue

		versandweg = "Post"
		mietvertrag = (child.get("mietvertrag") or "").strip()
		if mietvertrag:
			versandweg = (
				frappe.db.get_value("Mietvertrag", mietvertrag, "bevorzugter_versandweg") or "Post"
			)
		else:
			warnings.append(_("{0}: kein Mietvertrag (als Post behandelt)").format(child_name))

		versandweg_norm = (cstr(versandweg) or "").strip().lower()

		if versandweg_norm == "email":
			doc = frappe.get_doc("Betriebskostenabrechnung Mieter", child_name)
			doc.check_permission("read")
			recipients = _get_mieter_recipients(doc)
			if not recipients:
				warnings.append(_("{0}: Versandweg Email, aber keine E-Mail-Adresse (als Post behandelt)").format(child_name))
				print_names.append(child_name)
				continue

			try:
				pdf = _render_abrechnung_pdf(child_name, print_format=effective_print_format)
				subject = subject_override or _default_email_subject(child, head)
				queue_doc = frappe.sendmail(
					recipients=recipients,
					subject=subject,
					message=message,
					attachments=[
						{
							"fname": f"Betriebskostenabrechnung-{child_name}.pdf",
							"fcontent": pdf,
						}
					],
					reference_doctype="Betriebskostenabrechnung Mieter",
					reference_name=child_name,
					delayed=True,
					send_after=DRAFT_EMAIL_SEND_AFTER,
				)
				emailed.append(child_name)  # historischer key im response (jetzt "queued")
				if queue_doc and getattr(queue_doc, "name", None):
					queued.append({"mieter_abrechnung": child_name, "email_queue": queue_doc.name})
				if also_print_emailed:
					print_names.append(child_name)
			except Exception as exc:
				tb = frappe.get_traceback(with_context=True)
				try:
					err = frappe.log_error(
						title=f"E-Mail-Queue Erstellung fehlgeschlagen: {child_name}",
						message=tb,
						reference_doctype="Betriebskostenabrechnung Mieter",
						reference_name=child_name,
					)
					err_name = getattr(err, "name", None)
				except Exception:
					err_name = None

				detail = (str(exc) or "").strip()
				msg = _("{0}: E-Mail-Versand/Entwurf fehlgeschlagen (als Post behandelt)").format(child_name)
				if detail:
					msg += _(" – {0}").format(detail)
				if err_name:
					msg += _(" (siehe Error Log: {0})").format(err_name)
				errors.append(msg)
				print_names.append(child_name)
		else:
			print_names.append(child_name)

	# Für Papierfälle als "verschickt" markieren (Versandaktion); ggf. später über UI zurücksetzbar.
	for nm in print_names:
		try:
			frappe.db.set_value("Betriebskostenabrechnung Mieter", nm, "verschickt", 1, update_modified=False)
		except Exception:
			# Nicht blockieren, falls Berechtigung/Validierung in einzelnen Fällen scheitert.
			pass

	return {
		"emailed": emailed,
		"queued": queued,
		"print_names": print_names,
		"print_format": effective_print_format,
		"warnings": warnings,
		"errors": errors,
	}
