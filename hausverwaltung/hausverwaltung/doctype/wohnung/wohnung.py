import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate
from datetime import date
from frappe.utils import get_first_day
from re import sub
from urllib.parse import urlencode

from hausverwaltung.hausverwaltung.integrations.paperless import (
	PaperlessConfig,
	_create_tag,
	_fetch_tags,
	_normalize_key,
	_resolve_tag_id,
)
from hausverwaltung.hausverwaltung.utils.gebaeudeteil import (
	normalize_gebaeudeteil_to_standard,
	split_lage_gebaeudeteil,
)

STATUS_VERMIETET = "Vermietet"
STATUS_LEERSTEHEND = "Leerstehend"
STATUS_INAKTIV = "Inaktiv(z.b Zusammengelegt)"


def _normalize_gebaeudeteil(value: str | None) -> str | None:
	val = (value or "").strip()
	if not val:
		return None

	standard = normalize_gebaeudeteil_to_standard(val)
	return standard or val.upper()


def _split_lage(lage: str | None) -> tuple[str | None, str]:
	teil, rest = split_lage_gebaeudeteil(lage)
	return teil, rest


def _get_immobilie_initial(immobilie: str | None) -> str:
	name = (immobilie or "").strip()
	if not name:
		return "?"

	label = ""
	try:
		label = (frappe.db.get_value("Immobilie", name, "adresse_titel") or "").strip()
	except Exception:
		label = ""

	base = (label or name).strip()
	for ch in base:
		if ch.isalnum():
			return ch.upper()
	return base[:1].upper() if base else "?"


def build_wohnung_name(
	*,
	immobilie: str | None,
	gebaeudeteil: str | None,
	lage_in_der_immobilie: str | None,
	fallback_id: int | None = None,
) -> str:
	initial = _get_immobilie_initial(immobilie)
	teil = _normalize_gebaeudeteil(gebaeudeteil)

	lage_raw = (lage_in_der_immobilie or "").strip()
	teil_from_lage, lage_rest = _split_lage(lage_raw)
	if not teil:
		teil = teil_from_lage
	lage = lage_rest or lage_raw

	teil = (teil or "-").strip()
	lage = (lage or "").replace("|", "/").strip()
	return f"{initial} | {teil} | {lage}".strip()


class Wohnung(Document):
	def autoname(self):
		base = build_wohnung_name(
			immobilie=getattr(self, "immobilie", None),
			gebaeudeteil=getattr(self, "gebaeudeteil", None),
			lage_in_der_immobilie=getattr(self, "name__lage_in_der_immobilie", None),
			fallback_id=getattr(self, "id", None),
		)

		candidate = base
		if not frappe.db.exists("Wohnung", candidate):
			self.name = candidate
			return

		if getattr(self, "id", None):
			with_id = f"{base} ({self.id})"
			if not frappe.db.exists("Wohnung", with_id):
				self.name = with_id
				return

		i = 2
		while True:
			candidate = f"{base} ({i})"
			if not frappe.db.exists("Wohnung", candidate):
				self.name = candidate
				return
			i += 1

	@property
	def aktueller_mietvertrag(self):
		query = """
            SELECT name FROM `tabMietvertrag`
            WHERE
                wohnung = %s
				AND docstatus < 2
                AND von <= CURDATE()
                AND (bis >= CURDATE() OR bis IS NULL)
            ORDER BY von DESC
            LIMIT 1
        """
		result = frappe.db.sql(query, (self.name,), as_dict=True)
		return result[0]["name"] if result else None

	@property
	def aktueller_zustand(self):
		z = frappe.get_all(
			"Wohnungszustand",
			filters={"wohnung": self.name, "ab": ("<=", nowdate()), "docstatus": ("!=", 2)},
			fields=["name"],
			order_by="ab desc",
			limit=1,
		)
		return z[0].name if z else None

	@property
	def betriebskostenabrechnung_durch_vermieter(self) -> int:
		z = self.aktueller_zustand
		if not z:
			return 0
		try:
			val = frappe.db.get_value(
				"Wohnungszustand", z, "betriebskostenabrechnung_durch_vermieter"
			)
			return 1 if val else 0
		except Exception:
			return 0

	@property
	def heizkostenabrechnung_durch_vermieter(self) -> int:
		z = self.aktueller_zustand
		if not z:
			return 0
		try:
			val = frappe.db.get_value("Wohnungszustand", z, "heizkostenabrechnung_durch_vermieter")
			return 1 if val else 0
		except Exception:
			return 0

	@property
	def aktive_betriebskostenverteilung(self):
		# Environment may not have the DocType installed; skip gracefully
		try:
			if not frappe.db.table_exists("Betriebskostenverteilung"):
				return None
		except Exception:
			return None

		query = """
			SELECT name FROM `tabBetriebskostenverteilung`
			WHERE
				wohnung = %s
				AND gilt_ab <= CURDATE()
			ORDER BY gilt_ab DESC
			LIMIT 1
		"""
		result = frappe.db.sql(query, (self.name,), as_dict=True)
		if result:
			return result[0]["name"]

		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenverteilung",
				"wohnung": self.name,
				"gilt_ab": nowdate(),
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name


	@property
	def bk_vorauszahlung_ytd_bezahlt(self) -> float:
		"""YTD gezahlte Betriebskostenvorauszahlung für den aktuellen Mietvertrag."""
		try:
			mv = self.aktueller_mietvertrag
			if not mv:
				return 0.0
			from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
				calc_bk_vorauszahlungen,
			)
			heute = date.today()
			jahr = heute.year
			von = str(get_first_day(f"{jahr}-01-01"))
			bis = str(heute)
			res = calc_bk_vorauszahlungen(mv, von, bis)
			return float(res.get("actual_total", 0.0) or 0.0)
		except Exception:
			return 0.0

	@property
	def mietvertraege_alle(self) -> list[dict]:
		"""Alle nicht stornierten Mietverträge für die Formular-Übersicht."""
		if not self.name:
			return []
		return _get_mietvertraege_fuer_wohnung(self.name)

	def before_submit(self):
		"""Ensure a Wohnungszustand exists before allowing submission."""
		zustand_exists = frappe.db.exists("Wohnungszustand", {"wohnung": self.name})
		if not zustand_exists:
			frappe.throw(
				_("Es muss mindestens ein Wohnungszustand existieren, bevor die Wohnung eingereicht werden kann."),
				title=_("Zustand erforderlich"),
			)

	def validate(self):
		status = compute_wohnung_status(self.name) if self.name else None
		if status:
			self.status = status


@frappe.whitelist()
def get_or_create_initial_zustand(wohnung: str) -> str:
	"""Return the latest Wohnungszustand for the given Wohnung or create an initial one.

	If no Zustand exists yet, create a draft with today's date and link it to the Wohnung.
	Returns the name of the Wohnungszustand document.
	"""
	if not wohnung:
		frappe.throw(_("Parameter 'wohnung' fehlt."))

	# Try to get the most recent Zustand (by 'ab' descending)
	existing = frappe.get_all(
		"Wohnungszustand",
		filters={"wohnung": wohnung},
		fields=["name"],
		order_by="ab desc",
		limit=1,
	)
	if existing:
		return existing[0]["name"]

	# Create initial Zustand
	zustand = frappe.get_doc({
		"doctype": "Wohnungszustand",
		"wohnung": wohnung,
		"ab": nowdate(),
		"betriebskostenabrechnung_durch_vermieter": 1,
		"heizkostenabrechnung_durch_vermieter": 1,
	})
	zustand.insert()
	frappe.db.commit()
	return zustand.name


@frappe.whitelist()
def get_mietvertraege_fuer_wohnung(wohnung: str) -> list[dict]:
	"""Return all non-cancelled contracts for a Wohnung (active + history + future)."""
	if not wohnung:
		frappe.throw(_("Parameter 'wohnung' fehlt."))

	frappe.get_doc("Wohnung", wohnung).check_permission("read")
	return _get_mietvertraege_fuer_wohnung(wohnung)


def _get_mietvertraege_fuer_wohnung(wohnung: str) -> list[dict]:
	if not wohnung:
		return []

	rows = frappe.db.sql(
		"""
		SELECT
			name AS mietvertrag,
			von,
			bis,
			status,
			kunde
		FROM `tabMietvertrag`
		WHERE
			wohnung = %s
			AND docstatus < 2
		ORDER BY von DESC, name DESC
		""",
		(wohnung,),
		as_dict=True,
	)
	return rows or []


def _get_current_zustand_activity(wohnung: str, *, exclude: str | None = None) -> bool | None:
	filters = {"wohnung": wohnung, "ab": ("<=", nowdate()), "docstatus": ("!=", 2)}
	if exclude:
		filters["name"] = ("!=", exclude)
	zustand = frappe.get_all(
		"Wohnungszustand",
		filters=filters,
		fields=["wohnung_aktiv_genutzt"],
		order_by="ab desc",
		limit=1,
	)
	if not zustand:
		return None
	return bool(zustand[0].get("wohnung_aktiv_genutzt"))


def _has_active_mietvertrag(wohnung: str, *, exclude: str | None = None) -> bool:
	query = """
		SELECT name FROM `tabMietvertrag`
		WHERE
			wohnung = %s
			{exclude_clause}
			AND docstatus < 2
			AND von <= CURDATE()
			AND (bis >= CURDATE() OR bis IS NULL)
		ORDER BY von DESC
		LIMIT 1
	"""
	exclude_clause = "AND name != %s" if exclude else ""
	query = query.format(exclude_clause=exclude_clause)
	params = (wohnung, exclude) if exclude else (wohnung,)
	result = frappe.db.sql(query, params, as_dict=True)
	return bool(result)


def compute_wohnung_status(
	wohnung: str,
	*,
	exclude_mietvertrag: str | None = None,
	exclude_zustand: str | None = None,
) -> str | None:
	if not wohnung:
		return None

	aktiv_genutzt = _get_current_zustand_activity(wohnung, exclude=exclude_zustand)
	if aktiv_genutzt is False:
		return STATUS_INAKTIV
	if _has_active_mietvertrag(wohnung, exclude=exclude_mietvertrag):
		return STATUS_VERMIETET
	return STATUS_LEERSTEHEND


def update_wohnung_status(
	wohnung: str,
	*,
	update_modified: bool = False,
	exclude_mietvertrag: str | None = None,
	exclude_zustand: str | None = None,
) -> str | None:
	status = compute_wohnung_status(
		wohnung,
		exclude_mietvertrag=exclude_mietvertrag,
		exclude_zustand=exclude_zustand,
	)
	if not status:
		return None

	current = frappe.db.get_value("Wohnung", wohnung, "status")
	if (current or "").strip() == status:
		return status

	frappe.db.set_value("Wohnung", wohnung, "status", status, update_modified=update_modified)
	return status


def update_wohnung_status_from_mietvertrag(doc, method=None) -> None:
	wohnung = getattr(doc, "wohnung", None)
	if not wohnung:
		return
	exclude = doc.name if method == "on_trash" else None
	update_wohnung_status(wohnung, update_modified=False, exclude_mietvertrag=exclude)


def update_wohnung_status_from_zustand(doc, method=None) -> None:
	wohnung = getattr(doc, "wohnung", None)
	if not wohnung:
		return
	exclude = doc.name if method == "on_trash" else None
	update_wohnung_status(wohnung, update_modified=False, exclude_zustand=exclude)


def update_statuses_for_list() -> dict:
	rows = frappe.get_all("Wohnung", fields=["name", "status"])
	updated = 0
	for row in rows:
		new_status = compute_wohnung_status(row["name"])
		current_status = (row.get("status") or "").strip()
		if new_status and new_status != current_status:
			frappe.db.set_value("Wohnung", row["name"], "status", new_status, update_modified=False)
			updated += 1
	return {"status": "ok", "updated": updated, "count": len(rows)}


@frappe.whitelist()
def get_paperless_link(wohnung: str) -> str | None:
	"""Return a Paperless NGX URL that filters documents by the Wohnung tag."""
	if not wohnung:
		frappe.throw(_("Parameter 'wohnung' fehlt."))

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

	fields = ["immobilie", "name__lage_in_der_immobilie", "name"]
	has_paperless_column = frappe.db.has_column("Wohnung", "paperless_tag")
	if has_paperless_column:
		fields.insert(0, "paperless_tag")

	values = frappe.db.get_value("Wohnung", wohnung, fields, as_dict=True)
	if not values:
		frappe.throw(_("Wohnung '{0}' wurde nicht gefunden.").format(wohnung))

	tag = (values.get("paperless_tag") or "").strip() if has_paperless_column else ""
	needs_lookup = not has_paperless_column or not tag

	if needs_lookup:
		tag = _build_paperless_tag_name(
			values.get("immobilie"),
			values.get("name__lage_in_der_immobilie"),
			values.get("name"),
		)
		if not config:
			frappe.throw(_("Paperless NGX ist nicht vollständig konfiguriert (URL + Token) – Tag konnte nicht abgefragt oder angelegt werden."))
		try:
			_ensure_paperless_tag(config, tag)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				_("Paperless-Tag konnte nicht abgefragt oder angelegt werden ({0}).").format(wohnung),
			)
			frappe.throw(_("Paperless-Tag konnte nicht abgefragt oder angelegt werden – siehe Error Log."))
	elif not tag:
		frappe.throw(_("Kein Paperless-Tag für die Wohnung gefunden."))

	query = urlencode({"query": f'tag:"{tag}"'})
	return f"{link_base_url}/documents/?{query}"


def _build_paperless_tag_name(immobilie: str | None, lage: str | None, wohnung_name: str | None) -> str:
	prefix_parts = _get_immobilie_path(immobilie)
	prefix = " / ".join(prefix_parts) if prefix_parts else (immobilie or "")
	suffix = (lage or wohnung_name or "").strip()
	if prefix and suffix:
		return f"{prefix} - {suffix}"
	return prefix or suffix or (wohnung_name or "")


def _get_immobilie_path(immobilie: str | None) -> list[str]:
	"""Return ancestor path (root→leaf) for the Immobilie tree."""
	if not immobilie:
		return []

	path: list[str] = []
	seen: set[str] = set()
	current = immobilie
	while current and current not in seen:
		path.append(current)
		seen.add(current)
		current = frappe.db.get_value("Immobilie", current, "parent_immobilie")

	return list(reversed(path)) if path else []


def _ensure_paperless_tag(config: PaperlessConfig, tag_name: str, parent_tag_id: int | None = None) -> int | None:
	"""Ensure the tag exists in Paperless; return its ID."""
	tags = _fetch_tags(config)
	tag_id = _resolve_tag_id(tags, tag_name, parent_id=parent_tag_id)
	if tag_id:
		return tag_id
	slug = _make_slug(tag_name)
	return _create_tag(config, tag_name, slug, parent_id=parent_tag_id)


def _make_slug(tag_name: str) -> str:
	normalized = _normalize_key(tag_name)
	slug = sub(r"[^a-z0-9]+", "-", normalized).strip("-")
	return slug or "wohnung"
