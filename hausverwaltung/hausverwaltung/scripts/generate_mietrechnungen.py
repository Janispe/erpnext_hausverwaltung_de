import frappe
from frappe import _
from frappe.utils import add_days, get_first_day, get_last_day, add_months, now_datetime
from datetime import datetime, date, timedelta


def _parse_monat_jahr(monat: str | int | None, jahr: str | int | None) -> date:
    """Ermittle das Ziel-Datum als erster Tag im Monat."""
    heute = datetime.today()
    m = int(monat) if monat else int(heute.strftime("%m"))
    j = int(jahr) if jahr else int(heute.strftime("%Y"))
    return date(j, m, 1)


def _staffelbetrag(mv_name: str, parentfield: str, zum: date) -> float:
    """Hole den Betrag aus der Staffeltabelle (miete|betriebskosten|heizkosten), der am Datum gilt.

    Hinweis: Für Miete wird in dieser Datei eine spezielle Monatsberechnung verwendet.
    Diese generische Funktion bleibt für BK/Heizkosten erhalten (kein Pro‑Rata).
    """
    betrag = frappe.db.get_value(
        "Staffelmiete",
        {
            "parent": mv_name,
            "parenttype": "Mietvertrag",
            "parentfield": parentfield,
            "von": ("<=", zum),
        },
        "miete",
        order_by="von desc",
    )
    try:
        return float(betrag) if betrag else 0.0
    except Exception:
        return 0.0


def _month_window(anchor: date) -> tuple[date, date, int]:
    start = get_first_day(anchor)
    end_excl = add_months(start, 1)
    days = (end_excl - start).days
    return start, end_excl, days


def _overlap(a_start: date, a_end_excl: date, b_start: date, b_end_excl: date) -> tuple[date, date, int]:
    s = max(a_start, b_start)
    e = min(a_end_excl, b_end_excl)
    days = max((e - s).days, 0)
    return s, e, days


def _miete_betrag_fuer_monat(mv_row: frappe._dict, anchor: date) -> float:
    """Berechnet den Mietbetrag für den Anker‑Monat:
    - Art 'Monatlich': anteilig nach Tagen im Monat (inkl. Staffelwechsel innerhalb des Monats)
    - Art 'Gesamter Zeitraum': voller Betrag, wenn Zeitraum in diesem Monat liegt
    Berücksichtigt Vertragslaufzeit (nur überlappende Tage).
    """
    mv_name = mv_row.name
    month_start, month_end_excl, days_in_month = _month_window(anchor)

    # Vertragsfenster (exklusive Ende)
    contract_start = mv_row.von or date(1900, 1, 1)
    contract_end_excl = (mv_row.bis + timedelta(days=1)) if mv_row.bis else date(9999, 12, 31)

    # Monat × Vertrag überlappen?
    ov_start, ov_end_excl, ov_days = _overlap(month_start, month_end_excl, contract_start, contract_end_excl)
    if ov_days == 0:
        return 0.0

    total = 0.0

    # 1) Monatlich (pro‑rata)
    monatlich_rows = frappe.get_all(
        "Staffelmiete",
        filters={
            "parent": mv_name,
            "parenttype": "Mietvertrag",
            "parentfield": "miete",
            "art": "Monatlich",
            # Relevanz: alle mit 'von' < Monatsende
            "von": ("<", month_end_excl),
        },
        fields=["von", "miete"],
        order_by="von asc",
    )

    # Aktiver Satz zu ov_start finden (letzter mit von <= ov_start)
    current_rate = 0.0
    for r in monatlich_rows:
        if r.von <= ov_start:
            current_rate = float(r.miete or 0)  # Kandidat
        else:
            break

    # Zeitscheiben: Wechselpunkte innerhalb [ov_start, ov_end_excl)
    change_points = [r.von for r in monatlich_rows if ov_start < r.von < ov_end_excl]
    segment_starts = [ov_start] + sorted(change_points)
    segment_ends = segment_starts[1:] + [ov_end_excl]

    # Rate laufend aktualisieren, wenn wir an einen Wechsel kommen
    # Dazu benötigen wir ein Iterator über alle Rows ab ov_start
    rows_iter = iter([r for r in monatlich_rows if r.von >= ov_start])
    next_row = next(rows_iter, None)

    for seg_start, seg_end in zip(segment_starts, segment_ends):
        # Falls ein Wechsel exakt zu seg_start vorliegt → Rate aktualisieren
        while next_row and next_row.von == seg_start:
            current_rate = float(next_row.miete or 0)
            next_row = next(rows_iter, None)
        days = (seg_end - seg_start).days
        if days > 0 and current_rate > 0:
            total += current_rate * (days / days_in_month)

    # 2) Gesamter Zeitraum (voller Betrag, nur wenn Zeitraum innerhalb eines Monats liegt)
    ges_rows = frappe.get_all(
        "Staffelmiete",
        filters={
            "parent": mv_name,
            "parenttype": "Mietvertrag",
            "parentfield": "miete",
            "art": "Gesamter Zeitraum",
            # nur Startpunkte dieses Monats betrachten
            "von": ("between", [month_start, add_days(month_end_excl, -1)]),
        },
        fields=["name", "von", "miete"],
        order_by="von asc",
    )

    if ges_rows:
        # Um das Ende zu bestimmen, brauchen wir alle 'Gesamter Zeitraum'-Zeilen im Vertrag
        alle_ges = frappe.get_all(
            "Staffelmiete",
            filters={
                "parent": mv_name,
                "parenttype": "Mietvertrag",
                "parentfield": "miete",
                "art": "Gesamter Zeitraum",
            },
            fields=["name", "von", "miete"],
            order_by="von asc",
        )
        # Map name -> index
        index_by_name = {row.name: i for i, row in enumerate(alle_ges)}
        for r in ges_rows:
            i = index_by_name.get(r.name)
            if i is None:
                continue
            r_start = r.von
            # Ende ist Vortag des nächsten Starts, oder Vertragsende, oder Monatsende (falls offen)
            if i + 1 < len(alle_ges):
                next_start = alle_ges[i + 1].von
                r_end_excl = next_start
            else:
                # letztes Intervall: Vertragsende nutzen, sonst Monatsende dieses Starts
                if mv_row.bis:
                    r_end_excl = mv_row.bis + timedelta(days=1)
                else:
                    # auf Monatsende clippen
                    r_end_excl = add_months(get_first_day(r_start), 1)
            # Nur wenn Start und (inklusive) Ende im selben Monat liegen, gilt der volle Betrag
            end_incl = r_end_excl - timedelta(days=1)
            if r_start.year == end_incl.year and r_start.month == end_incl.month:
                # und der Zeitraum muss den Vertrag schneiden
                _, _, cut_days = _overlap(r_start, r_end_excl, contract_start, contract_end_excl)
                if cut_days > 0:
                    total += float(r.miete or 0)

    return round(float(total), 2)


def _cost_center_via_wohnung(wohnung: str | None) -> str | None:
    if not wohnung:
        return None
    immobilie = frappe.db.get_value("Wohnung", wohnung, "immobilie")
    if not immobilie:
        return None
    return frappe.db.get_value("Immobilie", immobilie, "kostenstelle")


def _third_working_day(month_anchor: date, company: str | None) -> date:
    """Berechne den 3. Werktag (Mo–Fr) des Monats.
    Berücksichtigt optional die Holiday List der Company (wenn gesetzt).
    """
    start = date(month_anchor.year, month_anchor.month, 1)
    # Feiertage des Monats sammeln
    holidays: set[date] = set()
    try:
        if company:
            holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
            if holiday_list:
                hols = frappe.get_all(
                    "Holiday",
                    filters={
                        "parent": holiday_list,
                        "holiday_date": ("between", [get_first_day(start), get_last_day(start)]),
                    },
                    pluck="holiday_date",
                )
                holidays = set(hols or [])
    except Exception:
        # Fallback ohne Holiday-Handling
        holidays = set()

    d = start
    count = 0
    for _ in range(31):  # max. Tage im Monat
        if d.weekday() < 5 and d not in holidays:  # Mo–Fr und kein Feiertag
            count += 1
            if count == 3:
                return d
        d = d + timedelta(days=1)
    # Fallback: notfalls 5 Tage nach Start
    return start + timedelta(days=5)


def _kunde_des_vertrags(mv_row: frappe._dict) -> str | None:
    # Bevorzugt das im Vertrag gepflegte Mieterfeld
    if getattr(mv_row, "kunde", None):
        return mv_row.kunde
    # Fallback: Ersten Vertragspartner nehmen -> zu Customer auflösen (falls vorhanden)
    partner = frappe.db.get_value(
        "Vertragspartner",
        {"parent": mv_row.name, "parenttype": "Mietvertrag"},
        "mieter",
        order_by="idx asc",
    )
    # Ohne Mapping zum Customer nicht nutzbar -> None
    return None


def _invoice_exists(customer: str, von: date, mv_name: str, typ: str) -> bool:
    # 1) Prüfen per Remark-Marker (neues Schema)
    existing = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "posting_date": ("between", [get_first_day(von), get_last_day(von)]),
            "docstatus": ("in", [0, 1]),
            "remarks": ("like", f"%[TYPE:{typ}] [MV:{mv_name}] {von.strftime('%m/%Y')}%"),
        },
        pluck="name",
        limit=1,
    )
    if existing:
        return True

    # 2) Fallback: Prüfen, ob in diesem Monat bereits eine Rechnung mit passendem Item existiert
    parent_names = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "posting_date": ("between", [get_first_day(von), get_last_day(von)]),
            "docstatus": ("in", [0, 1]),
        },
        pluck="name",
    )
    if not parent_names:
        return False
    item_code = "Miete" if typ == "Miete" else ("Betriebskosten" if typ == "Betriebskosten" else "Heizkosten")
    child = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": ("in", parent_names), "item_code": item_code},
        limit=1,
    )
    return bool(child)


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        meta = frappe.get_meta(doctype)
        return bool(meta.get_field(fieldname))
    except Exception:
        return False


def _resolve_company(company: str | None) -> str:
    """Ermittelt eine Company für die Rechnungserstellung.

    Reihenfolge:
    1) explizit übergebene Company
    2) User Default (Company)
    3) Global Default (company)
    4) falls genau eine aktive Company existiert, diese
    """
    if company:
        return company

    company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
    if company:
        return company

    try:
        companies = frappe.get_all("Company", filters={"disabled": 0}, pluck="name")
    except Exception:
        companies = frappe.get_all("Company", pluck="name")

    if len(companies) == 1:
        return companies[0]

    frappe.throw(_("Bitte eine Company auswählen oder eine Standard-Company setzen (User/Global Defaults)."))


def _create_invoice(
    customer: str,
    posting: date,
    item_code: str,
    beschreibung: str,
    betrag: float,
    income_account: str | None,
    cost_center: str | None,
    remark: str,
    wohnung: str | None,
    company: str,
) -> str:
    if betrag <= 0:
        return ""
    if not income_account:
        frappe.throw(_("Kein Erlöskonto für Mietrechnung hinterlegt. Bitte Hausverwaltung Einstellungen prüfen."))
    sinv = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": company,
            "customer": customer,
            "posting_date": posting,
            # Backdating sicher erlauben
            "set_posting_time": 1,
            # Fällig am 3. Werktag des Monats
            "due_date": _third_working_day(posting, company),
            "remarks": remark,
            "items": [
                {
                    "item_code": item_code,
                    "item_name": item_code,
                    "description": beschreibung,
                    "qty": 1,
                    "rate": betrag,
                    "income_account": income_account,
                    "cost_center": cost_center,
                }
            ],
        }
    )
    # Falls es ein Kostenstellen-Feld auf dem Beleg gibt (Accounting Dimension), auch auf Header setzen
    try:
        if cost_center and _has_field("Sales Invoice", "cost_center"):
            sinv.set("cost_center", cost_center)
    except Exception:
        # robust bleiben, Item-Kostenstelle existiert bereits
        pass
    if wohnung and not _has_field("Sales Invoice", "wohnung"):
        frappe.throw('Feld "wohnung" existiert nicht auf Sales Invoice (Accounting Dimension nicht zugewiesen). Admin bescheid sagen!!!')
    sinv.set("wohnung", wohnung)
    frappe.msgprint("Mietrechnung erfolgreich erstellt!")
    # Auch auf Positionsebene setzen, wenn Feld existiert
    try:
        if sinv.items and wohnung and _has_field("Sales Invoice Item", "wohnung"):
            for it in sinv.items:
                it.set("wohnung", wohnung)
    except Exception as e:
        frappe.log_error(str(e), "Generate Mietrechnung")
    sinv.insert()
    sinv.submit()
    return sinv.name


@frappe.whitelist()
def generate_miet_und_bk_rechnungen(
    monat: str | int | None = None,
    jahr: str | int | None = None,
    company: str | None = None,
) -> dict:
    """Erzeugt pro aktivem Mietvertrag drei Rechnungen (Miete, BK-VZ, Heiz-VZ) für den Monat.

    Rückgabe: Zusammenfassung mit Zählwerten und ggf. Hinweisen.
    """
    datum = _parse_monat_jahr(monat, jahr)
    company = _resolve_company(company)

    from hausverwaltung.hausverwaltung.utils.income_accounts import get_hv_income_accounts
    from hausverwaltung.hausverwaltung.utils.rent_items import ensure_rent_items

    income_accounts = get_hv_income_accounts(company)
    ensure_rent_items(company=company)

    created = {"Miete": 0, "Betriebskosten": 0, "Heizkosten": 0}
    skipped = []
    skipped_details = []

    durchlauf_doc = None
    try:
        durchlauf_doc = frappe.get_doc(
            {
                "doctype": "Mietrechnungen Durchlauf",
                "company": company,
                "monat": str(datum.month),
                "jahr": datum.year,
                "started_at": now_datetime(),
                "status": "Running",
                "user": frappe.session.user,
            }
        )
        durchlauf_doc.flags.ignore_permissions = True
        durchlauf_doc.insert(ignore_permissions=True)
    except Exception:
        durchlauf_doc = None

    def add_skip(
        *,
        reason: str,
        mietvertrag: str | None,
        wohnung: str | None,
        typ: str | None,
        betrag: float | None,
        message: str,
    ) -> None:
        skipped.append(message)
        skipped_details.append(
            {
                "reason": reason,
                "mietvertrag": mietvertrag,
                "wohnung": wohnung,
                "typ": typ,
                "betrag": betrag,
                "message": message,
            }
        )
        if durchlauf_doc:
            durchlauf_doc.append(
                "skips",
                {
                    "doctype": "Mietrechnungen Durchlauf Skip",
                    "reason": reason,
                    "mietvertrag": mietvertrag,
                    "wohnung": wohnung,
                    "typ": typ,
                    "betrag": betrag,
                    "message": message,
                },
            )

    def add_created(
        *,
        sales_invoice: str,
        typ: str,
        mietvertrag: str | None,
        wohnung: str | None,
        kunde: str | None,
        betrag: float,
        posting_date: date,
    ) -> None:
        if not durchlauf_doc:
            return
        durchlauf_doc.append(
            "rechnungen",
            {
                "doctype": "Mietrechnungen Durchlauf Rechnung",
                "sales_invoice": sales_invoice,
                "typ": typ,
                "mietvertrag": mietvertrag,
                "wohnung": wohnung,
                "kunde": kunde,
                "betrag": betrag,
                "posting_date": posting_date,
            },
        )

    vertrage = frappe.get_all(
        "Mietvertrag",
        filters={},
        fields=["name", "kunde", "wohnung", "von", "bis"],
    )

    try:
        for v in vertrage:
            # Prüfe, ob der Monat den Vertrag schneidet (auch bei Teilmonaten zulassen)
            month_start, month_end_excl, _ = _month_window(datum)
            c_start = v.von or date(1900, 1, 1)
            c_end_excl = (v.bis + timedelta(days=1)) if v.bis else date(9999, 12, 31)
            _, _, ov_days = _overlap(month_start, month_end_excl, c_start, c_end_excl)
            if ov_days == 0:
                continue

            kunde = _kunde_des_vertrags(v)
            if not kunde:
                add_skip(
                    reason="kein_kunde",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ=None,
                    betrag=None,
                    message=f"{v.name}: kein Mieter",
                )
                continue

            kst = _cost_center_via_wohnung(v.wohnung)

            # Beträge je Staffeltabelle holen
            # Miete: neue Logik (Monatlich pro‑rata, Gesamter Zeitraum voll)
            betrag_miete = _miete_betrag_fuer_monat(v, datum)
            betrag_bk = _staffelbetrag(v.name, "betriebskosten", datum)
            betrag_heiz = _staffelbetrag(v.name, "heizkosten", datum)

            monat_str = datum.strftime("%m/%Y")

            # Miete
            if betrag_miete <= 0:
                add_skip(
                    reason="betrag_0",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Miete",
                    betrag=0.0,
                    message=f"{v.name}: Miete Betrag 0",
                )
            elif _invoice_exists(kunde, datum, v.name, "Miete"):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Miete",
                    betrag=betrag_miete,
                    message=f"{v.name}: Miete bereits vorhanden",
                )
            else:
                remark = f"[TYPE:Miete] [MV:{v.name}] {monat_str}"
                desc = f"Nettokaltmiete {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Miete",
                    desc,
                    betrag_miete,
                    income_accounts.get("Miete"),
                    kst,
                    remark,
                    v.wohnung,
                    company,
                )
                if sinv_name:
                    created["Miete"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Miete",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_miete,
                        posting_date=datum,
                    )

            # Betriebskosten-Vorauszahlung
            if betrag_bk <= 0:
                add_skip(
                    reason="betrag_0",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Betriebskosten",
                    betrag=0.0,
                    message=f"{v.name}: Betriebskosten Betrag 0",
                )
            elif _invoice_exists(kunde, datum, v.name, "Betriebskosten"):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Betriebskosten",
                    betrag=betrag_bk,
                    message=f"{v.name}: Betriebskosten bereits vorhanden",
                )
            else:
                remark = f"[TYPE:Betriebskosten] [MV:{v.name}] {monat_str}"
                desc = f"Betriebskosten-Vorauszahlung {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Betriebskosten",
                    desc,
                    betrag_bk,
                    income_accounts.get("Betriebskosten"),
                    kst,
                    remark,
                    v.wohnung,
                    company,
                )
                if sinv_name:
                    created["Betriebskosten"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Betriebskosten",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_bk,
                        posting_date=datum,
                    )

            # Heizkosten-Vorauszahlung (nur wenn Staffeleintrag vorhanden)
            if betrag_heiz <= 0:
                add_skip(
                    reason="betrag_0",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Heizkosten",
                    betrag=0.0,
                    message=f"{v.name}: Heizkosten Betrag 0",
                )
            elif _invoice_exists(kunde, datum, v.name, "Heizkosten"):
                add_skip(
                    reason="rechnung_existiert",
                    mietvertrag=v.name,
                    wohnung=v.wohnung,
                    typ="Heizkosten",
                    betrag=betrag_heiz,
                    message=f"{v.name}: Heizkosten bereits vorhanden",
                )
            else:
                remark = f"[TYPE:Heizkosten] [MV:{v.name}] {monat_str}"
                desc = f"Heizkosten-Vorauszahlung {monat_str} Wohnung {v.wohnung}"
                sinv_name = _create_invoice(
                    kunde,
                    datum,
                    "Heizkosten",
                    desc,
                    betrag_heiz,
                    income_accounts.get("Heizkosten"),
                    kst,
                    remark,
                    v.wohnung,
                    company,
                )
                if sinv_name:
                    created["Heizkosten"] += 1
                    add_created(
                        sales_invoice=sinv_name,
                        typ="Heizkosten",
                        mietvertrag=v.name,
                        wohnung=v.wohnung,
                        kunde=kunde,
                        betrag=betrag_heiz,
                        posting_date=datum,
                    )
    except Exception:
        if durchlauf_doc:
            durchlauf_doc.status = "Failed"
            durchlauf_doc.finished_at = now_datetime()
            durchlauf_doc.save(ignore_permissions=True)
        raise

    if durchlauf_doc:
        durchlauf_doc.status = "Completed"
        durchlauf_doc.finished_at = now_datetime()
        durchlauf_doc.created_miete = created.get("Miete", 0)
        durchlauf_doc.created_bk = created.get("Betriebskosten", 0)
        durchlauf_doc.created_heiz = created.get("Heizkosten", 0)
        durchlauf_doc.created_total = sum(created.values())
        durchlauf_doc.skipped_count = len(skipped_details)
        durchlauf_doc.save(ignore_permissions=True)

    return {
        "created": created,
        "skipped": skipped,
        "skipped_details": skipped_details,
        "skipped_count": len(skipped_details),
        "month": datum.strftime("%Y-%m"),
        "durchlauf": durchlauf_doc.name if durchlauf_doc else None,
    }


# Alias, falls der Workspace-Button einen anderen Namen erwartet
@frappe.whitelist()
def generate_mietrechnungen(monat: str | int | None = None, jahr: str | int | None = None, company: str | None = None) -> dict:
    return generate_miet_und_bk_rechnungen(monat=monat, jahr=jahr, company=company)
