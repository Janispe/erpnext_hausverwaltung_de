import frappe


def _get_mieter_und_vertrag(wohnung: str) -> tuple[list[dict], str | None]:
	"""Return tenant infos and the current contract name for the given flat."""
	vertrag = frappe.db.sql(
		"""
        SELECT name FROM `tabMietvertrag`
        WHERE wohnung = %s
          AND von <= CURDATE()
          AND (bis >= CURDATE() OR bis IS NULL)
        ORDER BY von DESC
        LIMIT 1
        """,
		(wohnung,),
		as_dict=True,
	)
	if not vertrag:
		return [], None
	vertrag_name = vertrag[0]["name"]

	contact_phone_expr = ""
	try:
		if frappe.db.table_exists("Contact Phone"):
			contact_phone_expr = """
				, NULLIF((
					SELECT cp.phone
					FROM `tabContact Phone` cp
					WHERE cp.parent = c.name
					ORDER BY COALESCE(cp.is_primary_phone, 0) DESC, cp.idx ASC
					LIMIT 1
				), '')
			"""
	except Exception:
		# `table_exists` not always available; keep query minimal
		pass

	partner = frappe.db.sql(
		f"""
        SELECT
            c.name AS contact,
            c.first_name,
            c.last_name,
            COALESCE(
                NULLIF(c.phone, ''),
                NULLIF(c.mobile_no, '')
				{contact_phone_expr}
            ) AS telefon
        FROM `tabVertragspartner` vp
        JOIN `tabContact` c ON c.name = vp.mieter
        WHERE vp.parent = %s
          AND (COALESCE(vp.rolle, '') != 'Ausgezogen')
          AND (vp.eingezogen IS NULL OR vp.eingezogen <= CURDATE())
          AND (vp.ausgezogen IS NULL OR vp.ausgezogen >= CURDATE())
        ORDER BY vp.idx ASC
        """,
		(vertrag_name,),
		as_dict=True,
	)
	tenants: list[dict] = []
	for row in partner:
		first = row.get("first_name") or ""
		last = row.get("last_name") or ""
		label = f"{first} {last}".strip() or row.get("contact") or ""
		tenants.append(
			{
				"contact": row.get("contact"),
				"label": label,
				"telefon": row.get("telefon") or "—",
			}
		)
	return tenants, vertrag_name


def _gebaeudeteil_from_lage(lage: str | None) -> str | None:
	from hausverwaltung.hausverwaltung.utils.gebaeudeteil import normalize_gebaeudeteil_to_standard

	s = (lage or "").strip()
	if not s:
		return None

	head = s.split(",", 1)[0].strip()
	first_token = head.split(None, 1)[0].strip() if head else ""
	return normalize_gebaeudeteil_to_standard(first_token) or normalize_gebaeudeteil_to_standard(head)


@frappe.whitelist()
def get_tree_data(scope: str | None = None):
	scope = (scope or "top_level").strip().lower()
	filters = {}
	if scope != "all":
		# Standard: nur Top-Level-Immobilien abrufen (keine Kind-Knoten)
		filters["parent_immobilie"] = ["in", ["", None]]

	immobilien = frappe.get_all(
		"Immobilie",
		filters=filters,
		fields=["name", "adresse_titel", "parent_immobilie"],
		order_by="adresse_titel asc",
	)
	result = []

	# Für jede Immobilie: zugehörige Wohnungen laden
	for immo in immobilien:
		# 1) Knoten (Kinder im Immobilie-Baum)
		knoten = frappe.get_all(
			"Immobilie",
			filters={"parent_immobilie": immo.name},
			fields=["name", "adresse_titel"],
			order_by="adresse_titel asc",
		)
		# Nur unsere Standard-Knoten anzeigen (VH/SF/HH)
		allowed_suffixes = (" - VH", " - SF", " - HH")
		knoten = [
			k
			for k in knoten
			if ((k.get("adresse_titel") or "").strip().upper().endswith(allowed_suffixes))
		]

		teile_list: list[dict] = []
		for k in knoten:
			title = (k.get("adresse_titel") or k.name).strip()
			abbr = "Knoten"
			up = title.upper()
			if up.endswith(" - VH"):
				abbr = "VH"
			elif up.endswith(" - SF"):
				abbr = "SF"
			elif up.endswith(" - HH"):
				abbr = "HH"

			wohnungen_raw = frappe.get_all(
				"Wohnung",
				filters={"immobilie": immo.name, "immobilie_knoten": k.name},
				fields=["name", "name__lage_in_der_immobilie"],
				order_by="name asc",
			)
			wohnungen: list[dict] = []
			for whg in wohnungen_raw:
				tenants, vertrag_name = _get_mieter_und_vertrag(whg.name)
				label = (whg.get("name__lage_in_der_immobilie") or "").strip() or whg.name
				telefon = "\n".join([t.get("telefon") or "—" for t in tenants])
				wohnungen.append(
					{
						"name": whg.name,
						"label": label,
						"mieter": tenants,
						"telefon": telefon,
						"mietvertrag": vertrag_name,
					}
				)
			teile_list.append({"name": abbr, "node": k.name, "wohnungen": wohnungen})

		# 2) Fallback: Wohnungen ohne Knoten (oder alte Daten ohne Feld)
		wohnungen_raw = frappe.get_all(
			"Wohnung",
			filters={"immobilie": immo.name, "immobilie_knoten": ["in", ["", None]]},
			fields=["name", "gebaeudeteil", "name__lage_in_der_immobilie"],
			order_by="name asc",
		)
		if wohnungen_raw:
			teile_fallback: dict[str, list[dict]] = {}
			for whg in wohnungen_raw:
				teil = (whg.get("gebaeudeteil") or "").strip() or _gebaeudeteil_from_lage(
					whg.get("name__lage_in_der_immobilie")
				)
				teil_key = teil or "Ohne Zuordnung"
				tenants, vertrag_name = _get_mieter_und_vertrag(whg.name)
				label = (whg.get("name__lage_in_der_immobilie") or "").strip() or whg.name
				telefon = "\n".join([t.get("telefon") or "—" for t in tenants])
				teile_fallback.setdefault(teil_key, []).append(
					{
						"name": whg.name,
						"label": label,
						"mieter": tenants,
						"telefon": telefon,
						"mietvertrag": vertrag_name,
					}
				)
			def _sort_key(label: str) -> tuple[int, str]:
				clean = (label or "").strip().lower()
				is_eg = clean in {"eg", "erdgeschoss", "erdgeschoß"}
				return (0 if is_eg else 1, clean)

			for key, wohnungen in sorted(teile_fallback.items(), key=lambda kv: _sort_key(kv[0])):
				teile_list.append({"name": key, "wohnungen": wohnungen})

		result.append(
			{
				"name": immo.name,
				"label": immo.get("adresse_titel") or immo.name,
				"parent_immobilie": immo.get("parent_immobilie"),
				"teile": teile_list,
			}
		)

	return result
