import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, today

from hausverwaltung.hausverwaltung.utils.gebaeudeteil import split_lage_gebaeudeteil


GEBAEUDETEIL_ORDER = {"VH": 0, "SF": 1, "HH": 2}

GERMAN_MONTHS = {
	1: "Januar",
	2: "Februar",
	3: "März",
	4: "April",
	5: "Mai",
	6: "Juni",
	7: "Juli",
	8: "August",
	9: "September",
	10: "Oktober",
	11: "November",
	12: "Dezember",
}


class Telefonnummernauszug(Document):
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
			return f"Telefonliste {monat_jahr} – {self.immobilie}"
		return f"Telefonliste {monat_jahr}"

	def get_grouped_eintraege(self) -> list[dict]:
		"""Einträge nach Wohnung gruppieren — eine Druckzeile pro Wohnung."""
		# Wohnungs-IDs einmal pro Wohnungs-Name nachladen, da das Child-DocType
		# die ID selbst nicht speichert.
		wohnungs_namen = {row.wohnung for row in (self.eintraege or []) if row.wohnung}
		wohnung_id_map: dict[str, int | None] = {}
		if wohnungs_namen:
			id_rows = frappe.get_all(
				"Wohnung",
				filters={"name": ("in", list(wohnungs_namen))},
				fields=["name", "id"],
			)
			for r in id_rows:
				wohnung_id_map[r["name"]] = r.get("id")

		groups: list[dict] = []
		current_key = None
		for row in self.eintraege or []:
			key = (
				row.immobilie or "",
				(row.gebaeudeteil or "").strip(),
				row.wohnung or "",
			)
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
					"telefon": row.telefon or "",
					"mobil": row.mobil or "",
				}
			)

		def _sort_key(g):
			wid = g.get("wohnung_id")
			try:
				wohnung_key = (int(wid) if wid is not None else 999999, g.get("wohnung") or "")
			except (TypeError, ValueError):
				wohnung_key = (999999, g.get("wohnung") or "")

			if cint(getattr(self, "nach_hauptmieter_nachname_sortieren", 0)):
				return (_first_hauptmieter_name(g.get("mieter") or []), *wohnung_key)
			return wohnung_key

		groups.sort(key=_sort_key)
		return groups


def _query_eintraege(
	stichtag: str, immobilie: str | None, nach_hauptmieter_nachname_sortieren: bool = False
) -> list[dict]:
	contact_phone_expr = "NULLIF(c.phone, '')"
	try:
		if frappe.db.table_exists("Contact Phone"):
			contact_phone_expr = """COALESCE(
				NULLIF(c.phone, ''),
				NULLIF((
					SELECT cp.phone
					FROM `tabContact Phone` cp
					WHERE cp.parent = c.name
					ORDER BY COALESCE(cp.is_primary_phone, 0) DESC, cp.idx ASC
					LIMIT 1
				), '')
			)"""
	except Exception:
		pass

	conditions = [
		"(mv.von IS NULL OR mv.von <= %(stichtag)s)",
		"(mv.bis IS NULL OR mv.bis >= %(stichtag)s)",
		"(vp.eingezogen IS NULL OR vp.eingezogen <= %(stichtag)s)",
		"(vp.ausgezogen IS NULL OR vp.ausgezogen >= %(stichtag)s)",
		"COALESCE(vp.rolle, '') != 'Ausgezogen'",
	]
	values: dict = {"stichtag": stichtag}

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
			NULLIF(TRIM({contact_phone_expr}), '') AS telefon,
			NULLIF(TRIM(c.mobile_no), '') AS mobil,
			vp.idx AS mieter_idx
		FROM
			`tabMietvertrag` mv
		JOIN
			`tabWohnung` w ON w.name = mv.wohnung
		JOIN
			`tabVertragspartner` vp ON vp.parent = mv.name
				AND vp.parenttype = 'Mietvertrag'
				AND vp.parentfield = 'mieter'
		LEFT JOIN
			`tabContact` c ON c.name = vp.mieter
		WHERE
			{" AND ".join(conditions)}
		ORDER BY
			w.id,
			mv.wohnung,
			vp.idx
		""",
		values=values,
		as_dict=True,
	)

	for row in rows:
		teil = (row.get("gebaeudeteil") or "").strip()
		if not teil:
			teil_from_lage, _rest = split_lage_gebaeudeteil(row.get("lage_in_der_immobilie"))
			if teil_from_lage:
				row["gebaeudeteil"] = teil_from_lage
		# Wenn telefon und mobil identisch sind: mobil leeren, damit nicht doppelt erscheint.
		if row.get("telefon") and row.get("mobil") and row["telefon"] == row["mobil"]:
			row["mobil"] = None

	wohnung_sort_map = _hauptmieter_sort_map(rows) if nach_hauptmieter_nachname_sortieren else {}

	def _sort_key(r):
		wid = r.get("wohnung_id")
		try:
			wid_int = int(wid) if wid is not None else 999999
		except (TypeError, ValueError):
			wid_int = 999999
		wohnung_key = (wid_int, (r.get("wohnung") or ""))
		if nach_hauptmieter_nachname_sortieren:
			key = _wohnung_key(r)
			return (
				wohnung_sort_map.get(key) or _normalize_sort_value(r.get("mieter_nachname") or r.get("mieter_name")),
				*wohnung_key,
				int(r.get("mieter_idx") or 0),
			)
		return (*wohnung_key, int(r.get("mieter_idx") or 0))

	rows.sort(key=_sort_key)
	return rows


def _wohnung_key(row: dict) -> tuple[str, str, str]:
	return (
		row.get("immobilie") or "",
		(row.get("gebaeudeteil") or "").strip(),
		row.get("wohnung") or "",
	)


def _normalize_sort_value(value: str | None) -> str:
	return (value or "").strip().casefold() or "\uffff"


def _hauptmieter_sort_map(rows: list[dict]) -> dict[tuple[str, str, str], str]:
	sort_map: dict[tuple[str, str, str], tuple[int, str]] = {}
	for row in rows:
		if (row.get("rolle") or "").strip() != "Hauptmieter":
			continue
		key = _wohnung_key(row)
		sort_value = _normalize_sort_value(row.get("mieter_nachname") or row.get("mieter_name"))
		idx = int(row.get("mieter_idx") or 0)
		current = sort_map.get(key)
		if current is None or idx < current[0]:
			sort_map[key] = (idx, sort_value)
	return {key: value for key, (_idx, value) in sort_map.items()}


def _first_hauptmieter_name(mieter: list[dict]) -> str:
	for row in mieter:
		if (row.get("rolle") or "").strip() == "Hauptmieter":
			return _normalize_sort_value(row.get("name"))
	return _normalize_sort_value(mieter[0].get("name") if mieter else None)


@frappe.whitelist()
def erstelle_und_lade(
	stichtag: str, immobilie: str | None = None, nach_hauptmieter_nachname_sortieren: int = 0
) -> dict:
	"""Legt einen neuen Telefonnummernauszug an und lädt die Einträge sofort."""
	doc = frappe.new_doc("Telefonnummernauszug")
	doc.stichtag = getdate(stichtag).isoformat()
	if immobilie:
		doc.immobilie = immobilie
	doc.nach_hauptmieter_nachname_sortieren = cint(nach_hauptmieter_nachname_sortieren)
	doc.insert()

	rows = _query_eintraege(
		doc.stichtag, doc.immobilie or None, cint(doc.nach_hauptmieter_nachname_sortieren)
	)
	for row in rows:
		doc.append(
			"eintraege",
			{
				"immobilie": row.get("immobilie"),
				"gebaeudeteil": row.get("gebaeudeteil"),
				"wohnung": row.get("wohnung"),
				"mieter_name": row.get("mieter_name"),
				"rolle": row.get("rolle"),
				"telefon": row.get("telefon"),
				"mobil": row.get("mobil"),
			},
		)
	doc.anzahl_eintraege = len(doc.eintraege or [])
	doc.save()
	return {"name": doc.name, "anzahl": len(rows)}


@frappe.whitelist()
def lade_eintraege(name: str) -> dict:
	doc = frappe.get_doc("Telefonnummernauszug", name)
	stichtag = getdate(doc.stichtag or today()).isoformat()
	rows = _query_eintraege(
		stichtag, doc.immobilie or None, cint(doc.nach_hauptmieter_nachname_sortieren)
	)

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
				"telefon": row.get("telefon"),
				"mobil": row.get("mobil"),
			},
		)
	doc.anzahl_eintraege = len(doc.eintraege or [])
	doc.save()
	return {"anzahl": len(rows)}
