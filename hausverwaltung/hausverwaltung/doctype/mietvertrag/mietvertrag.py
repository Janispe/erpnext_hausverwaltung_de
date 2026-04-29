# import frappe
import frappe
import re
from frappe import _
from frappe.model.document import Document
from frappe.model.rename_doc import rename_doc
from frappe.utils import getdate, today, get_first_day
from urllib.parse import urlencode

from datetime import date

from hausverwaltung.hausverwaltung.utils import customer as customer_utils
from hausverwaltung.hausverwaltung.doctype.wohnung.wohnung import (
	_build_paperless_tag_name as _build_wohnung_paperless_tag_name,
	_ensure_paperless_tag,
)
from hausverwaltung.hausverwaltung.integrations.paperless import PaperlessConfig
from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_hauptmieter_display_name,
	get_hauptmieter_last_names,
)


class Mietvertrag(Document):
	"""DocType controller for Mietvertrag."""

	def _sort_staffel_table_by_von(self, fieldname: str) -> None:
		"""Sort a Staffelmiete child table by `von` ascending and fix `idx`."""
		table = getattr(self, fieldname, None)
		if not table or len(table) < 2:
			return

		def key(row) -> tuple[int, date]:
			von = getattr(row, "von", None)
			if not von:
				return (1, date.max)
			try:
				return (0, getdate(von))
			except Exception:
				return (1, date.max)

		table.sort(key=key)
		for idx, row in enumerate(table, start=1):
			row.idx = idx

	def autoname(self) -> None:
		"""Name contracts as: Haus-Code | VH/HH/SF | Lage | ab: <von> - Nachnamen.

		Important: The "Haus-Code" includes the Immobilie-ID (if present) to avoid
		collisions across multiple buildings that share the same initial letter.
		"""
		if getattr(self, "amended_from", None):
			# Keep Frappe's default "Amended from" naming behavior.
			return

		base_name = _build_mietvertrag_base_name(self)
		if not base_name:
			# Fall back to DocType autoname ("format:...") if required fields are missing.
			return

		self.name = _unique_docname("Mietvertrag", _with_hauptmieter_suffix(base_name, self.mieter))

	def _staffelbetrag_am(self, staffeln: list, stichtag) -> float:
		"""Return last applicable `miete` value from a Staffelmiete table for a given date."""
		if not staffeln:
			return 0.0

		try:
			stichtag_dt = getdate(stichtag)
		except Exception:
			stichtag_dt = getdate(today())

		best_von = None
		best_value = 0.0
		for row in staffeln:
			if not getattr(row, "von", None):
				continue
			try:
				row_von = getdate(row.von)
			except Exception:
				continue
			if row_von <= stichtag_dt and (best_von is None or row_von > best_von):
				best_von = row_von
				try:
					best_value = float(getattr(row, "miete", 0.0) or 0.0)
				except Exception:
					best_value = 0.0
		return float(best_value or 0.0)

	def _bruttomiete_stichtag(self):
		"""Pick a stable reference date for current amounts (today, bounded by contract start/end)."""
		stichtag = getdate(today())
		if self.von:
			try:
				von = getdate(self.von)
				if von > stichtag:
					stichtag = von
			except Exception:
				pass
		if self.bis:
			try:
				bis = getdate(self.bis)
				if bis < stichtag:
					stichtag = bis
			except Exception:
				pass
		return stichtag

	def compute_status(self) -> str:
		"""Berechne den Status basierend auf Vertragsdaten."""
		return _compute_status_value(self.von, self.bis)

	def onload(self) -> None:
		"""Status beim Öffnen aktualisieren (auch bei Submitted)."""
		try:
			new_status = self.compute_status()
		except Exception:
			return
		current_status = (self.status or "").strip()
		if new_status and new_status != current_status and self.name and not self.is_new():
			try:
				self.db_set("status", new_status, update_modified=False)
			except Exception:
				# Fallback: zumindest im Response anzeigen
				pass
			self.status = new_status

	def after_insert(self) -> None:
		"""Create a Customer automatically after inserting the contract."""
		if self.kunde:
			self._sync_customer_name()
		else:
			cust_id = _build_customer_docname(self)
			display_name = get_hauptmieter_display_name(self.mieter) or self.name
			customer = customer_utils.get_or_create_customer(
				cust_id, customer_name=display_name
			)
			self.db_set("kunde", customer, update_modified=False)

		if not (self.mieterwechsel or "").strip() and _is_system_manager():
			self.add_comment(
				"Info",
				_("Direkte Mietvertrag-Anlage ohne Mieterwechsel-Prozess durch System Manager ({0}).").format(
					frappe.session.user
				),
			)

	def on_update(self) -> None:
		"""Keep Mietvertrag and linked Customer names aligned with Wohnung + Hauptmieter."""
		if getattr(self.flags, "hv_syncing_names", False):
			return
		self.flags.hv_syncing_names = True
		try:
			self._sync_customer_name()
			self._sync_mietvertrag_name()
		finally:
			self.flags.hv_syncing_names = False

	def _sync_customer_name(self) -> str | None:
		"""Rename/create the linked Customer to the current expected tenant name."""
		target = _build_customer_docname(self)
		display_name = get_hauptmieter_display_name(self.mieter) or target
		if not target:
			return None

		current = (self.kunde or "").strip()
		if not current:
			customer = customer_utils.get_or_create_customer(target, customer_name=display_name)
			self.db_set("kunde", customer, update_modified=False)
			self.kunde = customer
			return customer

		if not frappe.db.exists("Customer", current):
			customer = customer_utils.get_or_create_customer(target, customer_name=display_name)
			self.db_set("kunde", customer, update_modified=False)
			self.kunde = customer
			return customer

		final_target = _unique_docname("Customer", target, current_name=current)
		if final_target != current:
			final_target = rename_doc(
				"Customer",
				current,
				final_target,
				force=True,
				merge=False,
				show_alert=False,
				ignore_permissions=True,
			)
			self.kunde = final_target

		if frappe.db.get_value("Customer", final_target, "customer_name") != display_name:
			frappe.db.set_value("Customer", final_target, "customer_name", display_name, update_modified=False)
		return final_target

	def _sync_mietvertrag_name(self) -> str | None:
		"""Rename this contract if Wohnung/date/Hauptmieter changed after creation."""
		base_name = _build_mietvertrag_base_name(self)
		if not base_name:
			return None

		current = (self.name or "").strip()
		target = _unique_docname("Mietvertrag", _with_hauptmieter_suffix(base_name, self.mieter), current_name=current)
		if not target or target == current:
			return current

		new_name = rename_doc(
			"Mietvertrag",
			current,
			target,
			force=True,
			merge=False,
			show_alert=False,
			ignore_permissions=True,
		)
		self.name = new_name
		return new_name

	def validate(self) -> None:
		"""Ensure that contacts are valid and validate 'Gesamter Zeitraum' in staffelmiete."""
		self._validate_creation_via_process()
		self.status = self.compute_status()
		self.immobilie = _get_wohnung_immobilie(self.wohnung)
		for fieldname in ("miete", "betriebskosten", "heizkosten", "untermietzuschlag", "kaution"):
			self._sort_staffel_table_by_von(fieldname)

		allowed = {row.mieter for row in self.mieter}
		for row in self.kontoverbindungen:
			if row.kontakt and row.kontakt not in allowed:
				frappe.throw(_(f"Kontakt {row.kontakt} ist kein Vertragspartner."))

		# Validate Staffelmiete 'Gesamter Zeitraum': must fit in a single month.
		# End is determined by next row's 'von' - 1 day, or contract end if last.
		from frappe.utils import add_days
		rows = sorted(self.miete or [], key=lambda r: getdate(r.von))
		for idx, r in enumerate(rows):
			if (r.art or "Monatlich").strip() != "Gesamter Zeitraum":
				continue
			start = getdate(r.von)
			# determine period end (inclusive)
			if idx + 1 < len(rows):
				next_start = getdate(rows[idx + 1].von)
				end_incl = add_days(next_start, -1)
			else:
				# last: use contract end if set, otherwise treat as same month boundary
				if self.bis:
					end_incl = getdate(self.bis)
				else:
					# open ended: we enforce same-month by using month end as effective end
					from frappe.utils import get_last_day
					end_incl = get_last_day(start)

			if end_incl < start:
				frappe.throw(_(f"Ungültiger Zeitraum in Staffelmiete (Gesamter Zeitraum) ab {start}: Ende vor Start."))
			# must lie within a single month
			if start.year != end_incl.year or start.month != end_incl.month:
				frappe.throw(
					_(
						f"Staffelmiete (Gesamter Zeitraum) ab {start} muss innerhalb eines Monats liegen (ermitteltes Ende: {end_incl})."
					)
				)

	def _validate_creation_via_process(self) -> None:
		is_new_doc = bool(self.is_new())
		mieterwechsel_name = (self.mieterwechsel or "").strip()

		# TEMPORÄR DEAKTIVIERT: Manuelle Mietvertrags-Anlage durch Hausverwalter
		# wieder erlaubt (auf Nutzerwunsch). Zum Reaktivieren der Mieterwechsel-
		# Pflicht: den nachfolgenden Block einkommentieren.
		# if is_new_doc and not mieterwechsel_name and not _is_system_manager():
		# 	frappe.throw(
		# 		_(
		# 			"Neue Mietvertraege duerfen nur ueber einen Mieterwechsel-Prozess (Mieterwechsel/Erstvermietung) angelegt werden. "
		# 			"Bitte den Prozess starten und den Vertrag darueber erzeugen."
		# 		)
		# 	)

		if not mieterwechsel_name:
			return

		mw = frappe.db.get_value(
			"Mieterwechsel",
			mieterwechsel_name,
			["name", "wohnung", "prozess_typ", "einzugsdatum", "neuer_mietvertrag"],
			as_dict=True,
		)
		if not mw:
			frappe.throw(_("Der referenzierte Mieterwechsel '{0}' existiert nicht.").format(mieterwechsel_name))

		prozess_typ = (mw.get("prozess_typ") or "").strip()
		if prozess_typ not in {"Mieterwechsel", "Erstvermietung"}:
			frappe.throw(_("Der referenzierte Mieterwechsel '{0}' ist kein Mieterwechsel/Erstvermietung.").format(mieterwechsel_name))

		if (mw.get("wohnung") or "").strip() != (self.wohnung or "").strip():
			frappe.throw(_("Mietvertrag und Mieterwechsel muessen auf dieselbe Wohnung verweisen."))

		einzugsdatum = mw.get("einzugsdatum")
		if self.von and einzugsdatum and getdate(self.von) != getdate(einzugsdatum):
			frappe.throw(
				_(
					"Vertragsbeginn ({0}) muss dem Einzugsdatum des Mieterwechsels ({1}) entsprechen."
				).format(self.von, einzugsdatum)
			)

		linked_new = (mw.get("neuer_mietvertrag") or "").strip()
		if linked_new and linked_new != (self.name or "").strip():
			frappe.throw(
				_(
					"Der Mieterwechsel verweist bereits auf einen anderen neuen Mietvertrag ({0})."
				).format(linked_new)
			)

	@property
	def bruttomiete(self) -> float:
		"""Aktuelle Bruttomiete (Nettokaltmiete + BK + HK + Untermietzuschlag)."""
		stichtag = self._bruttomiete_stichtag()
		return float(
			(self._staffelbetrag_am(self.miete, stichtag) or 0.0)
			+ (self._staffelbetrag_am(self.betriebskosten, stichtag) or 0.0)
			+ (self._staffelbetrag_am(self.heizkosten, stichtag) or 0.0)
			+ (self._staffelbetrag_am(self.untermietzuschlag, stichtag) or 0.0)
		)

	@property
	def miete_pro_qm(self) -> float | None:
		"""Aktuelle Nettokaltmiete pro Quadratmeter."""
		if not self.wohnung:
			return None

		flaeche = frappe.db.get_value(
			"Wohnungszustand",
			{"wohnung": self.wohnung, "ab": ("<=", today())},
			"größe",
			order_by="ab desc",
		)
		miete = frappe.db.get_value(
			"Staffelmiete",
			{
				"parent": self.name,
				"parenttype": "Mietvertrag",
				"parentfield": "miete",
				"von": ("<=", today()),
			},
			"miete",
			order_by="von desc",
		)
		if flaeche and miete:
			try:
				return round(float(miete) / float(flaeche), 2)
			except Exception:
				return None
		return None

	@property
	def bk_vorauszahlung_ytd_bezahlt(self) -> float:
		"""Summe der in diesem Kalenderjahr gezahlten Betriebskostenvorauszahlungen (YTD).

		Nutzt das bestehende Utility `calc_bk_vorauszahlungen` und summiert `actual_total`
		für den Zeitraum 01.01. bis heute, zugeschnitten auf die Vertragslaufzeit.
		"""
		try:
			from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
				calc_bk_vorauszahlungen,
			)

			heute = date.today()
			jahr = heute.year
			von = str(get_first_day(f"{jahr}-01-01"))
			bis = str(heute)
			res = calc_bk_vorauszahlungen(self.name, von, bis)
			return float(res.get("actual_total", 0.0) or 0.0)
		except Exception:
			# Keine harten Fehler im Formular anzeigen
			return 0.0


def _build_mietvertrag_base_name(doc: object) -> str:
	wohnung_name = (getattr(doc, "wohnung", None) or "").strip()
	von = getattr(doc, "von", None)
	if not wohnung_name or not von:
		return ""

	wohnung = frappe.db.get_value(
		"Wohnung",
		wohnung_name,
		["immobilie", "gebaeudeteil", "name__lage_in_der_immobilie"],
		as_dict=True,
	) or {}
	immobilie_name = (wohnung.get("immobilie") or "").strip()
	immobilie = (
		frappe.db.get_value(
			"Immobilie",
			immobilie_name,
			["objekt", "adresse_titel", "name", "immobilien_id"],
			as_dict=True,
		)
		if immobilie_name
		else {}
	) or {}

	haus_src = (immobilie.get("objekt") or immobilie.get("adresse_titel") or immobilie.get("name") or "").strip()
	haus_initial = _first_letter(haus_src)
	try:
		immobilien_id = int(immobilie.get("immobilien_id") or 0) or None
	except Exception:
		immobilien_id = None
	if immobilien_id:
		haus_initial = f"{haus_initial}{immobilien_id}" if haus_initial else str(immobilien_id)

	gebaeudeteil = _normalize_gebaeudeteil(
		(wohnung.get("gebaeudeteil") or "").strip() or (wohnung.get("name__lage_in_der_immobilie") or "").strip()
	)
	lage = _lage_ohne_gebaeudeteil((wohnung.get("name__lage_in_der_immobilie") or "").strip())

	try:
		von_str = getdate(von).strftime("%Y-%m-%d")
	except Exception:
		von_str = str(von)

	haus_initial = _sanitize_name_part(haus_initial)
	gebaeudeteil = _sanitize_name_part(gebaeudeteil)
	lage = _sanitize_name_part(lage)
	von_str = _sanitize_name_part(von_str)

	# Tab-aligned columns: pipes tend to land on consistent tab stops (useful in monospace/exports).
	return f"{haus_initial}\t| {gebaeudeteil}\t| {lage}\t| ab: {von_str}".strip()


def _with_hauptmieter_suffix(base_name: str, rows: object) -> str:
	base = (base_name or "").strip()
	if not base:
		return ""

	last_names = get_hauptmieter_last_names(rows)
	if not last_names:
		return base
	return f"{base} - {', '.join(last_names)}"


def _build_customer_docname(doc: object) -> str:
	last_names = get_hauptmieter_last_names(getattr(doc, "mieter", None))
	nachname = ", ".join(last_names) or (getattr(doc, "name", None) or "")
	wohn = (getattr(doc, "wohnung", None) or "").strip()
	nm = (nachname or "").strip()
	if wohn and nm:
		return f"{wohn} Mieter: {nm}"
	if wohn:
		return f"{wohn} Mieter"
	if nm:
		return f"Mieter: {nm}"
	return ""


def _unique_docname(doctype: str, base_name: str, current_name: str | None = None) -> str:
	base = (base_name or "").strip()
	if not base:
		return ""

	current = (current_name or "").strip()
	if current and base == current:
		return current

	if not frappe.db.exists(doctype, base, cache=False):
		return base

	if current:
		try:
			existing = frappe.db.get_value(doctype, base, "name", cache=False)
		except TypeError:
			existing = frappe.db.get_value(doctype, base, "name")
		if existing == current:
			return current

	for n in range(2, 1000):
		candidate = f"{base} ({n})"
		if candidate == current:
			return current
		if not frappe.db.exists(doctype, candidate, cache=False):
			return candidate

	return f"{base} {frappe.generate_hash(length=6).upper()}"


def _compute_status_value(von: object, bis: object) -> str:
	current = getdate(today())
	if von:
		try:
			start = getdate(von)
			if start > current:
				return "Zukunft"
		except Exception:
			pass

	if bis:
		try:
			end = getdate(bis)
			if end < current:
				return "Vergangenheit"
		except Exception:
			pass

	return "Läuft"


def _get_wohnung_immobilie(wohnung: str | None) -> str | None:
	if not wohnung:
		return None
	return frappe.db.get_value("Wohnung", wohnung, "immobilie")


@frappe.whitelist()
def update_statuses_for_list() -> dict:
	updated = 0
	has_immobilie_column = frappe.db.has_column("Mietvertrag", "immobilie")
	fields = ["name", "wohnung", "von", "bis", "status", "docstatus"]
	if has_immobilie_column:
		fields.append("immobilie")
	rows = frappe.get_all(
		"Mietvertrag",
		fields=fields,
		filters={"docstatus": ["!=", 2]},
		limit=0,
	)
	for row in rows:
		values = {}
		new_status = _compute_status_value(row.get("von"), row.get("bis"))
		current_status = (row.get("status") or "").strip()
		if new_status and new_status != current_status:
			values["status"] = new_status
		if has_immobilie_column:
			immobilie = _get_wohnung_immobilie(row.get("wohnung"))
			if (immobilie or "") != (row.get("immobilie") or ""):
				values["immobilie"] = immobilie
		if values:
			frappe.db.set_value("Mietvertrag", row["name"], values, update_modified=False)
			updated += 1
	return {"updated": updated}


def sync_names_for_contact(doc, method: str | None = None) -> None:
	"""Refresh linked Mietvertrag/Customer names when a tenant Contact changes."""
	_ = method
	contact = (getattr(doc, "name", None) or "").strip()
	if not contact:
		return

	rows = frappe.get_all(
		"Vertragspartner",
		filters={
			"parenttype": "Mietvertrag",
			"mieter": contact,
		},
		fields=["parent"],
		limit=0,
	)
	for row in rows:
		parent = (row.get("parent") or "").strip()
		if not parent or not frappe.db.exists("Mietvertrag", parent):
			continue
		try:
			mv = frappe.get_doc("Mietvertrag", parent)
			mv._sync_customer_name()
			mv._sync_mietvertrag_name()
		except Exception:
			frappe.log_error(
				title="Mietvertrag Naming Sync fehlgeschlagen",
				message=frappe.get_traceback(),
			)


@frappe.whitelist()
def get_mietvertrag_paperless_link(mietvertrag: str) -> str | None:
	"""Return a Paperless NGX URL for this Mietvertrag (contract-specific tag + Wohnungstag)."""
	if not mietvertrag:
		frappe.throw(_("Parameter 'mietvertrag' fehlt."))

	conf = getattr(frappe, "conf", {}) or {}
	config = PaperlessConfig.from_conf()

	link_base_url = (
		conf.get("paperless_ngx_public_url")
		or conf.get("paperless_ngx_url")
		or (config.url if config else "")
		or ""
	).rstrip("/")
	if not link_base_url:
		frappe.throw(_("Paperless NGX ist nicht konfiguriert (paperless_ngx_public_url oder paperless_ngx_url)."))

	mv = frappe.db.get_value("Mietvertrag", mietvertrag, ["wohnung", "von", "name"], as_dict=True)
	if not mv:
		frappe.throw(_("Mietvertrag '{0}' wurde nicht gefunden.").format(mietvertrag))
	if not mv.wohnung:
		frappe.throw(_("Dem Mietvertrag ist keine Wohnung zugeordnet."))

	has_paperless_column = frappe.db.has_column("Wohnung", "paperless_tag")
	whg_fields = ["immobilie", "name__lage_in_der_immobilie", "name"]
	if has_paperless_column:
		whg_fields.insert(0, "paperless_tag")
	wohnung = frappe.db.get_value("Wohnung", mv.wohnung, whg_fields, as_dict=True)
	if not wohnung:
		frappe.throw(_("Wohnung '{0}' wurde nicht gefunden.").format(mv.wohnung))

	if not config:
		frappe.throw(_("Paperless NGX ist nicht vollständig konfiguriert (URL + Token) – Tag konnte nicht abgefragt oder angelegt werden."))

	wohnung_tag = (wohnung.get("paperless_tag") or "").strip() if has_paperless_column else ""
	if not wohnung_tag:
		wohnung_tag = _build_wohnung_paperless_tag_name(
			wohnung.get("immobilie"),
			wohnung.get("name__lage_in_der_immobilie"),
			wohnung.get("name"),
		)
		_ensure_paperless_tag(config, wohnung_tag)

	parent_tag_id = _ensure_paperless_tag(config, "Mietvertrag")
	mietvertrag_tag = _build_mietvertrag_tag_name(
		wohnung.get("immobilie"),
		wohnung.get("name__lage_in_der_immobilie"),
		wohnung.get("name"),
		mv.get("von"),
		mv.get("name"),
	)
	_ensure_paperless_tag(config, mietvertrag_tag, parent_tag_id=parent_tag_id)

	query_parts = [f'tag:"{mietvertrag_tag}"']
	if wohnung_tag:
		query_parts.append(f'tag:"{wohnung_tag}"')
	query = " AND ".join(query_parts)
	return f"{link_base_url}/documents/?{urlencode({'query': query})}"


def _build_mietvertrag_tag_name(
	immobilie: str | None, lage: str | None, wohnung_name: str | None, von: str | None, vertrag_name: str | None
) -> str:
	"""Compose a Paperless tag for a Mietvertrag based on Immobilie path, Wohnung and Vertragsbeginn/Name."""
	base = _build_wohnung_paperless_tag_name(immobilie, lage, wohnung_name)
	von_str = ""
	if von:
		try:
			# Handle date/datetime objects
			von_str = getattr(von, "isoformat", lambda: str(von))()
		except Exception:
			von_str = str(von)
	suffix = (von_str or "").strip() or (vertrag_name or "").strip()
	if base and suffix:
		return f"{base} - Mietvertrag {suffix}"
	if base:
		return f"{base} - Mietvertrag"
	return f"Mietvertrag {suffix}" if suffix else "Mietvertrag"


def _first_letter(value: str | None) -> str:
	"""Return the first house identifier letter (uppercased) from the given value."""
	s = (value or "").strip()
	if not s:
		return ""
	# Prefer patterns like "Haus A" -> "A" (avoid returning "H").
	m = re.search(r"\bhaus\s*([A-Za-zÄÖÜäöü])\b", s, flags=re.IGNORECASE)
	if m:
		return m.group(1).upper()
	m = re.search(r"[A-Za-zÄÖÜäöü]", s)
	return (m.group(0) if m else "").upper()


def _normalize_gebaeudeteil(value: str | None) -> str:
	"""Map inputs like 'Vorderhaus' to 'VH' (also supports 'HH'/'SF')."""
	from hausverwaltung.hausverwaltung.utils.gebaeudeteil import normalize_gebaeudeteil_to_standard

	raw = (value or "").strip()
	if not raw:
		return ""

	# Prefer first part (comma format) and fall back to prefix token.
	head = raw.split(",", 1)[0].strip()
	first_token = head.split(None, 1)[0].strip() if head else ""
	return normalize_gebaeudeteil_to_standard(first_token) or normalize_gebaeudeteil_to_standard(head) or ""


def _lage_ohne_gebaeudeteil(lage: str | None) -> str:
	"""Return 'EG links' from 'Vorderhaus, EG links' (fallback to original)."""
	from hausverwaltung.hausverwaltung.utils.gebaeudeteil import split_lage_gebaeudeteil

	s = (lage or "").strip()
	if not s:
		return ""

	teil, rest = split_lage_gebaeudeteil(s)
	if teil and rest:
		return rest
	if "," in s:
		tail = s.split(",", 1)[1].strip()
		return tail or s
	return s


def _sanitize_name_part(value: str | None) -> str:
	"""Prevent separators from leaking into the DocName parts."""
	s = (value or "").strip()
	if not s:
		return ""
	s = s.replace("\t", " ").replace("|", "/")
	# Collapse spaces (but don't introduce tabs here).
	s = re.sub(r" +", " ", s)
	return s.strip()


def _is_system_manager() -> bool:
	roles = set(frappe.get_roles(frappe.session.user) or [])
	return "System Manager" in roles
