import frappe
from frappe.model.document import Document
from frappe.utils import cint, getdate, today

from hausverwaltung.hausverwaltung.doctype.telefonnummernauszug.telefonnummernauszug import (
	GERMAN_MONTHS,
	_first_hauptmieter_name,
	_gebaeudeteil_sort_index,
	_hauptmieter_sort_map,
	_normalize_sort_value,
	_wohnung_key,
)
from hausverwaltung.hausverwaltung.utils.gebaeudeteil import split_lage_gebaeudeteil


class Emailauszug(Document):
	def validate(self):
		if not self.stichtag:
			self.stichtag = today()
		if not self.titel:
			self.titel = self._build_titel()
		self.anzahl_eintraege = len(self.eintraege or [])

	def _build_titel(self) -> str:
		d = getdate(self.stichtag)
		monat_jahr = f"{GERMAN_MONTHS[d.month]} {d.year}"
		if self.immobilie:
			return f"E-Mail-Liste {monat_jahr} - {self.immobilie}"
		return f"E-Mail-Liste {monat_jahr}"

	def get_grouped_eintraege(self) -> list[dict]:
		"""Einträge nach Wohnung gruppieren — eine Druckzeile pro Wohnung."""
		wohnungs_namen = {row.wohnung for row in (self.eintraege or []) if row.wohnung}
		wohnung_id_map: dict[str, int | None] = {}
		if wohnungs_namen:
			for row in frappe.get_all(
				"Wohnung",
				filters={"name": ("in", list(wohnungs_namen))},
				fields=["name", "id"],
			):
				wohnung_id_map[row["name"]] = row.get("id")

		groups: list[dict] = []
		current_key = None
		for row in self.eintraege or []:
			key = (row.immobilie or "", (row.gebaeudeteil or "").strip(), row.wohnung or "")
			if key != current_key:
				groups.append(
					{
						"immobilie": row.immobilie or "",
						"gebaeudeteil": (row.gebaeudeteil or "").strip(),
						"wohnung": row.wohnung or "",
						"wohnung_id": wohnung_id_map.get(row.wohnung),
						"mieter": [],
					}
				)
				current_key = key
			groups[-1]["mieter"].append(
				{
					"name": row.mieter_name or "",
					"rolle": row.rolle or "",
					"email": (row.email or "").strip(),
				}
			)

		nach_gebaeudeteil = cint(getattr(self, "nach_gebaeudeteil_sortieren", 0))
		nach_nachname = cint(getattr(self, "nach_hauptmieter_nachname_sortieren", 0))

		def _sort_key(group):
			wid = group.get("wohnung_id")
			try:
				wohnung_key = (int(wid) if wid is not None else 999999, group.get("wohnung") or "")
			except (TypeError, ValueError):
				wohnung_key = (999999, group.get("wohnung") or "")

			parts: list = []
			if nach_gebaeudeteil:
				parts.append(_gebaeudeteil_sort_index(group.get("gebaeudeteil")))
			if nach_nachname:
				parts.append(_first_hauptmieter_name(group.get("mieter") or []))
			parts.extend(wohnung_key)
			return tuple(parts)

		groups.sort(key=_sort_key)
		return groups


def _query_eintraege(
	stichtag: str,
	immobilie: str | None,
	nach_hauptmieter_nachname_sortieren: bool = False,
	nach_gebaeudeteil_sortieren: bool = False,
) -> list[dict]:
	# Contact.email_id ist die primäre Adresse. Bei älteren Datensätzen kann
	# stattdessen nur ein Eintrag in der Contact-Email-Kindtabelle vorhanden sein.
	contact_email_expr = "NULLIF(TRIM(c.email_id), '')"
	if frappe.db.table_exists("Contact Email"):
		contact_email_expr = """COALESCE(
			NULLIF(TRIM(c.email_id), ''),
			NULLIF(TRIM((
				SELECT ce.email_id
				FROM `tabContact Email` ce
				WHERE ce.parent = c.name AND ce.parenttype = 'Contact'
				ORDER BY COALESCE(ce.is_primary, 0) DESC, ce.idx ASC
				LIMIT 1
			)), '')
		)"""

	conditions = [
		"(mv.von IS NULL OR mv.von <= %(stichtag)s)",
		"(mv.bis IS NULL OR mv.bis >= %(stichtag)s)",
		"(vp.eingezogen IS NULL OR vp.eingezogen <= %(stichtag)s)",
		"(vp.ausgezogen IS NULL OR vp.ausgezogen >= %(stichtag)s)",
		"COALESCE(vp.rolle, '') != 'Ausgezogen'",
	]
	values = {"stichtag": stichtag}
	if immobilie:
		conditions.append("w.immobilie = %(immobilie)s")
		values["immobilie"] = immobilie

	rows = frappe.db.sql(
		f"""
		SELECT
			mv.wohnung AS wohnung,
			w.id AS wohnung_id,
			w.immobilie AS immobilie,
			w.gebaeudeteil AS gebaeudeteil,
			w.name__lage_in_der_immobilie AS lage_in_der_immobilie,
			COALESCE(
				NULLIF(TRIM(CONCAT_WS(', ', c.last_name, c.first_name)), ''),
				vp.mieter
			) AS mieter_name,
			NULLIF(TRIM(c.last_name), '') AS mieter_nachname,
			vp.rolle AS rolle,
			{contact_email_expr} AS email,
			vp.idx AS mieter_idx
		FROM `tabMietvertrag` mv
		JOIN `tabWohnung` w ON w.name = mv.wohnung
		JOIN `tabVertragspartner` vp ON vp.parent = mv.name
			AND vp.parenttype = 'Mietvertrag'
			AND vp.parentfield = 'mieter'
		LEFT JOIN `tabContact` c ON c.name = vp.mieter
		WHERE {" AND ".join(conditions)}
		ORDER BY w.id, mv.wohnung, vp.idx
		""",
		values=values,
		as_dict=True,
	)

	for row in rows:
		if not (row.get("gebaeudeteil") or "").strip():
			teil, _rest = split_lage_gebaeudeteil(row.get("lage_in_der_immobilie"))
			if teil:
				row["gebaeudeteil"] = teil

	wohnung_sort_map = _hauptmieter_sort_map(rows) if nach_hauptmieter_nachname_sortieren else {}

	def _sort_key(row):
		wid = row.get("wohnung_id")
		try:
			wid_int = int(wid) if wid is not None else 999999
		except (TypeError, ValueError):
			wid_int = 999999
		parts: list = []
		if nach_gebaeudeteil_sortieren:
			parts.append(_gebaeudeteil_sort_index(row.get("gebaeudeteil")))
		if nach_hauptmieter_nachname_sortieren:
			parts.append(
				wohnung_sort_map.get(_wohnung_key(row))
				or _normalize_sort_value(row.get("mieter_nachname") or row.get("mieter_name"))
			)
		parts.extend((wid_int, row.get("wohnung") or "", int(row.get("mieter_idx") or 0)))
		return tuple(parts)

	rows.sort(key=_sort_key)
	return rows


def _fill_eintraege(doc, rows: list[dict]) -> None:
	doc.set("eintraege", [])
	for row in rows:
		doc.append(
			"eintraege",
			{
				"immobilie": row.get("immobilie"),
				"gebaeudeteil": row.get("gebaeudeteil"),
				"wohnung": row.get("wohnung"),
				"mieter_name": row.get("mieter_name"),
				"rolle": row.get("rolle"),
				"email": (row.get("email") or "").strip(),
			},
		)
	doc.anzahl_eintraege = len(doc.eintraege or [])


@frappe.whitelist()
def erstelle_und_lade(
	stichtag: str,
	immobilie: str | None = None,
	nach_hauptmieter_nachname_sortieren: int = 0,
	nach_gebaeudeteil_sortieren: int = 0,
) -> dict:
	"""Legt einen E-Mail-Auszug an und lädt seine Einträge."""
	frappe.has_permission("Emailauszug", "create", throw=True)
	doc = frappe.new_doc("Emailauszug")
	doc.stichtag = getdate(stichtag).isoformat()
	if immobilie:
		doc.immobilie = immobilie
	doc.nach_hauptmieter_nachname_sortieren = cint(nach_hauptmieter_nachname_sortieren)
	doc.nach_gebaeudeteil_sortieren = cint(nach_gebaeudeteil_sortieren)
	rows = _query_eintraege(
		doc.stichtag,
		doc.immobilie or None,
		cint(doc.nach_hauptmieter_nachname_sortieren),
		cint(doc.nach_gebaeudeteil_sortieren),
	)
	_fill_eintraege(doc, rows)
	doc.insert()
	return {"name": doc.name, "anzahl": len(rows)}


@frappe.whitelist()
def lade_eintraege(name: str) -> dict:
	doc = frappe.get_doc("Emailauszug", name)
	doc.check_permission("write")
	rows = _query_eintraege(
		getdate(doc.stichtag or today()).isoformat(),
		doc.immobilie or None,
		cint(doc.nach_hauptmieter_nachname_sortieren),
		cint(doc.nach_gebaeudeteil_sortieren),
	)
	_fill_eintraege(doc, rows)
	doc.save()
	return {"anzahl": len(rows)}
