import hashlib
import json
from io import BytesIO
from typing import Callable, Dict, List, Optional, Set

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, cstr
from frappe.utils import now_datetime

from hausverwaltung.hausverwaltung.utils.pdf_engine import render_pdf as get_pdf
from hausverwaltung.hausverwaltung.utils.serienbrief_print import normalize_print_format_name
from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_for_print_format
from hausverwaltung.hausverwaltung.utils.serienbrief_print import render_serienbrief_pdf_for_print_format
from hausverwaltung.hausverwaltung.utils.serienbrief_print import scrub_value as hv_scrub

SERIENBRIEF_PRINT_FORMAT_FIELDNAME = "hv_serienbrief_vorlage"
PRINT_BUNDLE_CSS_PATH = "/assets/frappe/css/print.bundle.css"
DRAFT_EMAIL_SEND_AFTER = "2099-01-01 00:00:00"
SUMMARY_TABLE_FIELDS = ("kosten_pro_art", "zaehler_summen")
BK_BUNDLE_PDF_PROGRESS_TTL = 60 * 60


def _row_value(row, key: str):
	getter = getattr(row, "get", None)
	return getter(key) if callable(getter) else getattr(row, key, None)


def _get_exact_zaehlerstand(zaehler: str, datum) -> float | None:
	value = frappe.db.get_value(
		"Zaehlerstand",
		{"parent": zaehler, "datum": cstr(datum)},
		"zaehlerstand",
	)
	if value in (None, ""):
		return None
	try:
		return float(value)
	except Exception:
		return None


def _calculate_zaehler_summen(immobilie: str | None, von, bis) -> Dict[str, float]:
	"""Berechnet Verbrauch je Zählerart streng aus exakten Ständen am Periodenrand."""
	if not (immobilie and von and bis):
		return {}

	wohnungen = frappe.get_all("Wohnung", filters={"immobilie": immobilie}, pluck="name")
	if not wohnungen:
		return {}

	period_start = cstr(von)
	period_end = cstr(bis)
	period_end_excl = cstr(add_days(bis, 1))
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
	for row in zuordnungen or []:
		# Overlap check with [period_start, period_end_excl)
		if _row_value(row, "bis") and cstr(_row_value(row, "bis")) <= period_start:
			continue
		zaehler = _row_value(row, "zaehler")
		if zaehler and zaehler not in seen:
			seen.add(zaehler)
			zaehler_names.append(zaehler)

	if not zaehler_names:
		return {}

	sums: Dict[str, float] = {}
	zaehler_rows = frappe.get_all(
		"Zaehler",
		filters={"name": ("in", zaehler_names)},
		fields=["name", "zaehlerart"],
	)
	for zaehler in zaehler_rows or []:
		name = _row_value(zaehler, "name")
		if not name:
			continue
		art = _row_value(zaehler, "zaehlerart") or _("Unbekannt")
		start = _get_exact_zaehlerstand(name, period_start)
		end = _get_exact_zaehlerstand(name, period_end)
		if start is None:
			frappe.throw(f"Zählerstand für Zähler {name} ({art}) am {period_start} fehlt.")
		if end is None:
			frappe.throw(f"Zählerstand für Zähler {name} ({art}) am {period_end} fehlt.")
		sums[art] = sums.get(art, 0.0) + (end - start)
	return sums


class BetriebskostenabrechnungImmobilie(Document):
	@property
	def mieter_abrechnungen(self) -> List[Dict[str, object]]:
		"""Virtuelles Desk-Feld; die echten Zeilen lädt das Formular per API."""
		return []

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

	def _persist_summary_after_insert(self) -> None:
		"""Persistiert automatisch berechnete Summen ohne zweiten vollen Save.

		Ein normales `save()` innerhalb von `after_insert` aktualisiert den Datensatz
		noch einmal, während der ursprüngliche Client-Speichervorgang noch läuft. Das
		kann im Desk zu einem geänderten Dokumentstand direkt nach dem Anlegen führen.
		"""
		self.set_parent_in_children()
		self.set_name_in_children()
		self.db_update()
		for fieldname in SUMMARY_TABLE_FIELDS:
			self.update_child_table(fieldname)

	def after_insert(self):
		"""Beim Anlegen automatisch alle Mieter‑Abrechnungen als Entwurf erzeugen."""
		if not (self.immobilie and self.von and self.bis):
			frappe.throw("Bitte Immobilie, Von und Bis ausfüllen.")
		# Idempotenz: wenn bereits Child-Abrechnungen verknuepft sind (Retry,
		# doppelter Trigger), nicht erneut erzeugen. Summary + Persistenz laufen
		# trotzdem, damit ein abgebrochener Vorlauf konsistent fertig wird.
		children_exist = frappe.db.exists(
			"Betriebskostenabrechnung Mieter",
			{"immobilien_abrechnung": self.name},
		)
		if not children_exist:
			stichtag = self.stichtag or self.bis
			from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import create_bk_abrechnungen_immobilie
			create_bk_abrechnungen_immobilie(
				von=cstr(self.von),
				bis=cstr(self.bis),
				immobilie=self.immobilie,
				submit=False,
				stichtag=cstr(stichtag),
				head=self.name,
				split_by_mietvertrag=True,
			)
		# Nach Erzeugung (oder Skip): Zusammenfassungen berechnen + persistieren.
		self._populate_summary()
		self._persist_summary_after_insert()

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
		# Tabelle setzen — gruppierte Reihenfolge (Wasser, Heizung, …) statt
		# rein alphabetisch, damit Mieter-Abrechnungen lesbarer werden.
		from hausverwaltung.hausverwaltung.utils.bk_sort import sort_key

		self.set("kosten_pro_art", [])
		total_costs = 0.0
		for art, betrag in sorted(per_art.items(), key=lambda item: sort_key(item[0])):
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

		# Zähler-Summen: periodengenauer Verbrauch je ZählerTyp.
		self.set("zaehler_summen", [])
		sums = _calculate_zaehler_summen(self.immobilie, self.von, self.bis)
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
	serienbrief_pdf = render_serienbrief_pdf_for_print_format(
		print_format_name,
		docname=name,
		doctype="Betriebskostenabrechnung Mieter",
	)
	if serienbrief_pdf:
		return serienbrief_pdf

	html = frappe.get_print(
		doctype="Betriebskostenabrechnung Mieter",
		name=name,
		print_format=normalize_print_format_name(print_format_name),
	)
	return get_pdf(html)


def _apply_draft_watermark(pdf: bytes) -> bytes:
	if not pdf:
		return pdf

	try:
		from PyPDF2 import PdfReader, PdfWriter
	except ImportError:
		from pypdf import PdfReader, PdfWriter
	from reportlab.pdfgen import canvas

	reader = PdfReader(BytesIO(pdf))
	writer = PdfWriter()

	for page in reader.pages:
		width = float(page.mediabox.width)
		height = float(page.mediabox.height)
		font_size = max(64, min(width, height) * 0.18)

		watermark_pdf = BytesIO()
		c = canvas.Canvas(watermark_pdf, pagesize=(width, height))
		c.saveState()
		try:
			c.setFillAlpha(0.16)
		except Exception:
			pass
		c.setFillColorRGB(1, 0, 0)
		c.setFont("Helvetica-Bold", font_size)
		c.translate(width / 2, height / 2)
		c.rotate(35)
		c.drawCentredString(0, -font_size / 3, "DRAFT")
		c.restoreState()
		c.save()
		watermark_pdf.seek(0)

		watermark_page = PdfReader(watermark_pdf).pages[0]
		page.merge_page(watermark_page)
		writer.add_page(page)

	out = BytesIO()
	writer.write(out)
	return out.getvalue()


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


def _validate_bk_mieter_print_format(print_format: Optional[str]) -> Optional[str]:
	name = (print_format or "").strip()
	if not name or name.lower() == "standard":
		return None
	if not frappe.db.exists("Print Format", name):
		frappe.throw(_("Print Format '{0}' wurde nicht gefunden.").format(name))

	pf_doc = frappe.get_cached_doc("Print Format", name)
	doc_type = (pf_doc.get("doc_type") or "").strip()
	if doc_type and doc_type != "Betriebskostenabrechnung Mieter":
		frappe.throw(
			_("Print Format {0} gehört zu {1}, benötigt wird aber {2}.").format(
				name, doc_type, "Betriebskostenabrechnung Mieter"
			)
		)
	if cint(pf_doc.get("disabled")):
		frappe.throw(_("Print Format '{0}' ist deaktiviert.").format(name))
	return name


def _get_serienbrief_vorlage_from_print_format(print_format: Optional[str]) -> Optional[str]:
	name = (print_format or "").strip()
	if not name:
		return None
	try:
		pf_doc = frappe.get_cached_doc("Print Format", name)
	except frappe.DoesNotExistError:
		return None
	return (pf_doc.get(SERIENBRIEF_PRINT_FORMAT_FIELDNAME) or "").strip() or None


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


def _get_mieter_abrechnung_names_for_head(name: str) -> List[str]:
	if not name:
		frappe.throw(_("Parameter 'name' fehlt."))

	head = frappe.get_doc("Betriebskostenabrechnung Immobilie", name)
	if not frappe.has_permission(head.doctype, "print", head) and not frappe.has_permission(
		head.doctype, "read", head
	):
		raise frappe.PermissionError

	children = frappe.get_all(
		"Betriebskostenabrechnung Mieter",
		filters={"immobilien_abrechnung": name},
		fields=["name"],
		order_by="wohnung asc",
	)
	return [row.get("name") for row in children or [] if row.get("name")]


def _is_bk_head_draft(name: str) -> bool:
	return cint(frappe.db.get_value("Betriebskostenabrechnung Immobilie", name, "docstatus") or 0) == 0


def _bk_bundle_pdf_progress_key(job_id: str) -> str:
	return f"hv_bk_bundle_pdf_progress:{job_id}"


def _set_bk_bundle_pdf_progress(job_id: str, **values) -> None:
	current = _get_bk_bundle_pdf_progress(job_id, check_permission=False) if job_id else {}
	current.update(values)
	current["updated_at"] = now_datetime().isoformat()
	frappe.cache.set_value(
		_bk_bundle_pdf_progress_key(job_id),
		frappe.as_json(current),
		expires_in_sec=BK_BUNDLE_PDF_PROGRESS_TTL,
	)


def _get_bk_bundle_pdf_progress(job_id: str, *, check_permission: bool = True) -> Dict[str, object]:
	if not job_id:
		return {}
	raw = frappe.cache.get_value(_bk_bundle_pdf_progress_key(job_id))
	if not raw:
		return {}
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8", errors="replace")
	try:
		data = json.loads(raw) if isinstance(raw, str) else raw
	except Exception:
		data = {}
	if not isinstance(data, dict):
		return {}
	if check_permission:
		docname = cstr(data.get("name") or "").strip()
		if docname:
			head = frappe.get_doc("Betriebskostenabrechnung Immobilie", docname)
			if not frappe.has_permission(head.doctype, "print", head) and not frappe.has_permission(
				head.doctype, "read", head
			):
				raise frappe.PermissionError
	return data


def _get_child_print_format_for_sammeldruck(print_format: Optional[str]) -> Optional[str]:
	print_format_name = (print_format or "").strip()
	if not print_format_name or print_format_name.lower() == "standard":
		return _get_default_bk_mieter_print_format()

	if frappe.db.exists("Print Format", print_format_name):
		pf_doc = frappe.get_cached_doc("Print Format", print_format_name)
		if (pf_doc.get("doc_type") or "").strip() != "Betriebskostenabrechnung Mieter":
			return _get_default_bk_mieter_print_format()

	return _validate_bk_mieter_print_format(print_format_name)


def _get_default_bk_mieter_print_format() -> Optional[str]:
	try:
		default_format = (frappe.get_meta("Betriebskostenabrechnung Mieter").default_print_format or "").strip()
	except frappe.DoesNotExistError:
		default_format = ""
	if default_format:
		return _validate_bk_mieter_print_format(default_format)

	if frappe.db.has_column("Print Format", SERIENBRIEF_PRINT_FORMAT_FIELDNAME):
		serienbrief_formats = frappe.get_all(
			"Print Format",
			filters={
				"doc_type": "Betriebskostenabrechnung Mieter",
				"disabled": 0,
				SERIENBRIEF_PRINT_FORMAT_FIELDNAME: ("is", "set"),
			},
			pluck="name",
			order_by="modified desc",
			limit_page_length=1,
		)
		if serienbrief_formats:
			return _validate_bk_mieter_print_format(serienbrief_formats[0])

	print_formats = frappe.get_all(
		"Print Format",
		filters={"doc_type": "Betriebskostenabrechnung Mieter", "disabled": 0},
		pluck="name",
		order_by="modified desc",
		limit_page_length=1,
	)
	if print_formats:
		return _validate_bk_mieter_print_format(print_formats[0])

	return None


def _render_mieter_abrechnungen_serienbrief_html(child_names: List[str], vorlage: str) -> str:
	from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
		SerienbriefDurchlauf,
	)

	serienbrief_doc: SerienbriefDurchlauf = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"title": _("Betriebskostenabrechnungen"),
			"vorlage": vorlage,
			"iteration_doctype": "Betriebskostenabrechnung Mieter",
			"iteration_objekte": [
				{
					"doctype": "Serienbrief Iterationsobjekt",
					"iteration_doctype": "Betriebskostenabrechnung Mieter",
					"objekt": child_name,
				}
				for child_name in child_names
			],
		}
	)
	serienbrief_doc.flags.ignore_mandatory = True
	serienbrief_doc.flags.ignore_permissions = True
	return serienbrief_doc._render_full_html()


class _UnsupportedBatchSerienbriefPDF(Exception):
	pass


def _render_mieter_abrechnungen_serienbrief_pdf_batch(
	child_names: List[str],
	vorlage: str,
	progress_cb: Optional[Callable[[int, int, Optional[str]], None]] = None,
) -> bytes:
	from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
		_collect_template_requirements,
	)
	from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
		SerienbriefDurchlauf,
	)
	from hausverwaltung.hausverwaltung.utils.brand_print import apply_print_saving_brand_assets

	template = frappe.get_cached_doc("Serienbrief Vorlage", vorlage)
	serienbrief_doc: SerienbriefDurchlauf = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"title": _("Betriebskostenabrechnungen"),
			"vorlage": vorlage,
			"iteration_doctype": "Betriebskostenabrechnung Mieter",
			"iteration_objekte": [
				{
					"doctype": "Serienbrief Iterationsobjekt",
					"iteration_doctype": "Betriebskostenabrechnung Mieter",
					"objekt": child_name,
				}
				for child_name in child_names
			],
		}
	)
	serienbrief_doc.flags.ignore_mandatory = True
	serienbrief_doc.flags.ignore_permissions = True

	template_requirements = _collect_template_requirements(template, "Betriebskostenabrechnung Mieter")
	empfaenger_rows = serienbrief_doc._get_empfaenger_rows()
	if not empfaenger_rows:
		frappe.throw(_("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."))

	pages: List[str] = []
	total = len(empfaenger_rows)
	for idx, row in enumerate(empfaenger_rows, start=1):
		current = _row_value(row, "iteration_objekt")
		context_data = serienbrief_doc._build_context(
			row, idx, template_requirements, template, total=total
		)
		segments = serienbrief_doc._render_template_content(template, context_data)
		if not segments:
			frappe.throw(
				_(
					"Die gewählte Vorlage liefert keinen renderbaren Inhalt. "
					"Bitte prüfen Sie die Textbausteine."
				)
			)

		html_parts: List[str] = []
		for segment in segments:
			if segment.get("type") != "html":
				raise _UnsupportedBatchSerienbriefPDF
			value = apply_print_saving_brand_assets(
				cstr(segment.get("html") or "").strip(),
				bool(getattr(serienbrief_doc, "_druck_schwarz_weiss", False)),
			)
			if value:
				html_parts.append(value)
		if not html_parts:
			raise _UnsupportedBatchSerienbriefPDF

		page_body = "\n".join(html_parts)
		pages.append(f'<div class="serienbrief-page">{page_body}</div>')
		if progress_cb:
			progress_cb(idx, total, current)

	page_html = serienbrief_doc._wrap_html("\n".join(pages))
	return get_pdf(page_html, options=serienbrief_doc._default_pdf_options())


def get_mieter_abrechnungen_print_html_and_style(
	name: str,
	print_format: Optional[str] = None,
	no_letterhead: int | str = 0,
	letterhead: Optional[str] = None,
) -> Dict[str, str]:
	"""Rendert alle Mieterabrechnungen eines Kopfes als Sammeldruck."""
	child_names = _get_mieter_abrechnung_names_for_head(name)
	if not child_names:
		return {
			"html": "<p>{0}</p>".format(frappe.utils.escape_html(_("Keine Mieterabrechnungen vorhanden."))),
			"style": "",
		}

	child_print_format = _get_child_print_format_for_sammeldruck(print_format)
	effective_serienbrief_vorlage = _get_serienbrief_vorlage_from_print_format(child_print_format)

	if effective_serienbrief_vorlage:
		return {
			"html": _render_mieter_abrechnungen_serienbrief_html(child_names, effective_serienbrief_vorlage),
			"style": "",
		}

	from frappe.www import printview as core_printview

	combined_docs: List[str] = []
	style = ""
	for child_name in child_names:
		res = core_printview.get_html_and_style(
			doc="Betriebskostenabrechnung Mieter",
			name=child_name,
			print_format=child_print_format,
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

	parts: List[str] = []
	for idx, html in enumerate(combined_docs):
		parts.append(html)
		if idx < len(combined_docs) - 1:
			parts.append('<div class="hv-print-break"></div>')

	if not parts:
		parts.append("<p>{0}</p>".format(frappe.utils.escape_html(_("Keine Druckinhalte vorhanden."))))

	style = "\n".join(
		filter(
			None,
			[
				style,
				".hv-print-break { break-after: page; page-break-after: always; height: 0; }",
			],
		)
	)
	return {"html": "\n".join(parts), "style": style}


def get_mieter_abrechnungen_print_pdf(name: str, print_format: Optional[str] = None) -> bytes:
	"""Rendert alle Mieterabrechnungen eines Kopfes als zusammengeführtes PDF."""
	child_names = _get_mieter_abrechnung_names_for_head(name)
	if not child_names:
		frappe.throw(_("Keine Mieterabrechnungen vorhanden."))

	child_print_format = _get_child_print_format_for_sammeldruck(print_format)
	effective_serienbrief_vorlage = _get_serienbrief_vorlage_from_print_format(child_print_format)
	if effective_serienbrief_vorlage:
		try:
			content = _render_mieter_abrechnungen_serienbrief_pdf_batch(
				child_names,
				effective_serienbrief_vorlage,
			)
			return _apply_draft_watermark(content) if _is_bk_head_draft(name) else content
		except _UnsupportedBatchSerienbriefPDF:
			pass

	try:
		from PyPDF2 import PdfMerger
	except ImportError:
		from pypdf import PdfMerger

	merger = PdfMerger()
	try:
		for child_name in child_names:
			pdf = _render_abrechnung_pdf(child_name, print_format=child_print_format)
			if pdf:
				merger.append(BytesIO(pdf))
		out = BytesIO()
		merger.write(out)
		content = out.getvalue()
		return _apply_draft_watermark(content) if _is_bk_head_draft(name) else content
	finally:
		try:
			merger.close()
		except Exception:
			pass


def _run_mieter_abrechnungen_pdf_job(
	progress_id: str,
	name: str,
	print_format: Optional[str] = None,
	user: Optional[str] = None,
) -> None:
	merger = None
	try:
		if user:
			frappe.set_user(user)

		child_names = _get_mieter_abrechnung_names_for_head(name)
		child_print_format = _get_child_print_format_for_sammeldruck(print_format)
		total = len(child_names)
		is_draft = _is_bk_head_draft(name)
		effective_serienbrief_vorlage = _get_serienbrief_vorlage_from_print_format(child_print_format)
		_set_bk_bundle_pdf_progress(
			progress_id,
			status="running",
			done=0,
			total=total,
			current=None,
			is_draft=is_draft,
		)

		content = None
		if effective_serienbrief_vorlage:
			try:
				def progress_cb(done: int, progress_total: int, current: Optional[str]) -> None:
					_set_bk_bundle_pdf_progress(
						progress_id,
						status="running",
						done=done,
						total=progress_total,
						current=current,
						is_draft=is_draft,
					)

				content = _render_mieter_abrechnungen_serienbrief_pdf_batch(
					child_names,
					effective_serienbrief_vorlage,
					progress_cb=progress_cb,
				)
			except _UnsupportedBatchSerienbriefPDF:
				content = None

		if content is None:
			try:
				from PyPDF2 import PdfMerger
			except ImportError:
				from pypdf import PdfMerger

			merger = PdfMerger()
			for idx, child_name in enumerate(child_names, start=1):
				_set_bk_bundle_pdf_progress(
					progress_id,
					status="running",
					done=idx - 1,
					total=total,
					current=child_name,
				)
				pdf = _render_abrechnung_pdf(child_name, print_format=child_print_format)
				if pdf:
					merger.append(BytesIO(pdf))
				_set_bk_bundle_pdf_progress(
					progress_id,
					status="running",
					done=idx,
					total=total,
					current=child_name,
				)

			out = BytesIO()
			merger.write(out)
			content = out.getvalue()
		if not content:
			frappe.throw(_("PDF konnte nicht erzeugt werden."))
		if is_draft:
			_set_bk_bundle_pdf_progress(
				progress_id,
				status="running",
				done=total,
				total=total,
				current=_("DRAFT-Wasserzeichen"),
				is_draft=is_draft,
			)
			content = _apply_draft_watermark(content)

		from frappe.utils.file_manager import save_file

		filename_prefix = "Betriebskostenabrechnungen-Entwurf" if is_draft else "Betriebskostenabrechnungen"
		filename = f"{filename_prefix}-{hv_scrub(name or '')}.pdf"
		file_doc = save_file(
			filename,
			content,
			"Betriebskostenabrechnung Immobilie",
			name,
			is_private=1,
		)
		frappe.db.commit()
		_set_bk_bundle_pdf_progress(
			progress_id,
			status="finished",
			done=total,
			total=total,
			current=None,
			file_url=file_doc.file_url,
			file_name=file_doc.file_name,
		)
	except Exception as exc:
		frappe.db.rollback()
		_set_bk_bundle_pdf_progress(
			progress_id,
			status="failed",
			error=cstr(exc) or _("Unbekannter Fehler"),
		)
		frappe.log_error(frappe.get_traceback(), f"Betriebskostenabrechnung Sammel-PDF fehlgeschlagen: {name}")
		raise
	finally:
		if merger:
			try:
				merger.close()
			except Exception:
				pass


@frappe.whitelist()
def start_mieter_abrechnungen_pdf_job(name: str, print_format: Optional[str] = None) -> Dict[str, object]:
	child_names = _get_mieter_abrechnung_names_for_head(name)
	if not child_names:
		frappe.throw(_("Keine Mieterabrechnungen vorhanden."))

	job_id = frappe.generate_hash(length=16)
	is_draft = _is_bk_head_draft(name)
	_set_bk_bundle_pdf_progress(
		job_id,
		status="queued",
		name=name,
		done=0,
		total=len(child_names),
		current=None,
		file_url=None,
		error=None,
		is_draft=is_draft,
	)
	frappe.enqueue(
		"hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie._run_mieter_abrechnungen_pdf_job",
		queue="long",
		timeout=3600,
		job_id=job_id,
		progress_id=job_id,
		name=name,
		print_format=print_format,
		user=frappe.session.user,
		enqueue_after_commit=True,
	)
	return {"job_id": job_id, "status": "queued", "total": len(child_names), "is_draft": is_draft}


@frappe.whitelist()
def get_mieter_abrechnungen_pdf_progress(job_id: str) -> Dict[str, object]:
	progress = _get_bk_bundle_pdf_progress(job_id)
	if not progress:
		return {"status": "missing", "done": 0, "total": 0}
	return progress


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

	print_format_name = (print_format or "").strip() or None
	if doctype == "Betriebskostenabrechnung Mieter":
		print_format_name = _validate_bk_mieter_print_format(print_format_name)

	effective_serienbrief_vorlage = (serienbrief_vorlage or "").strip()
	if not effective_serienbrief_vorlage and print_format_name:
		effective_serienbrief_vorlage = _get_serienbrief_vorlage_from_print_format(print_format_name) or ""

	if effective_serienbrief_vorlage:
		# Serienbrief: ein Dokument mit mehreren Seiten
		from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
			SerienbriefDurchlauf,
		)

		vorlage = effective_serienbrief_vorlage
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
			print_format=print_format_name,
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
	effective_print_format = _validate_bk_mieter_print_format(print_format)
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
