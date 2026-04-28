import frappe

def generate_flat_view_for_doctype(doctype: str, view_name: str):
    """Erzeuge eine flache SQL-View für einen Doctype:
    - Basis: tab{Doctype} als 't'
    - Alle "normalen" Felder direkt
    - Alle Link-Felder mit LEFT JOIN und *_name-Spalte
    """

    meta = frappe.get_meta(doctype)
    base_table = f"`tab{doctype}`"
    base_alias = "t"

    select_parts = []
    join_parts = []

    # Basis-ID immer mit reinnehmen
    select_parts.append(f"{base_alias}.name AS {doctype.lower()}_name")

    for df in meta.fields:
        # Dinge, die wir in der View ignorieren wollen
        if df.fieldtype in (
            "Table",
            "Table MultiSelect",
            "HTML",
            "Section Break",
            "Column Break",
            "Fold",
            "Button",
            "Image",
            "Attach",
            "Attach Image",
        ):
            continue

        # Link-Felder: Join + sprechende Spalte
        if df.fieldtype == "Link" and df.options:
            if not frappe.db.has_column(doctype, df.fieldname):
                continue
            link_doctype = df.options
            link_table = f"`tab{link_doctype}`"
            join_alias = f"{df.fieldname}_link"

            # Join anbauen
            join_parts.append(
                f"LEFT JOIN {link_table} {join_alias} "
                f"ON {join_alias}.name = {base_alias}.{df.fieldname}"
            )

            # In der View die Name-Spalte des verlinkten Doctypes ausgeben
            # z.B. mietvertrag_link_name
            select_parts.append(
                f"{join_alias}.name AS {df.fieldname}_name"
            )

            # Optional: wenn es in verlinktem Doctype ein Feld 'title' gibt,
            # könntest du das später noch ergänzen, aber das erfordert extra Meta-Lookup.
            continue

        # Alle "normalen" Felder direkt übernehmen
        fieldname = df.fieldname
        if not fieldname:
            continue

        # Überspringe virtuelle/berechnete Felder ohne physische DB-Spalte
        if not frappe.db.has_column(doctype, fieldname):
            continue

        # Eindeutige Aliasnamen
        select_parts.append(f"{base_alias}.{fieldname} AS {fieldname}")

    select_sql = ",\n        ".join(select_parts)
    join_sql = ""
    if join_parts:
        join_sql = "\n    " + "\n    ".join(join_parts)

    view_sql = f"""
    CREATE OR REPLACE VIEW `{view_name}` AS
    SELECT
        {select_sql}
    FROM {base_table} {base_alias}{join_sql};
    """

    frappe.db.sql(view_sql)


def execute():
    """Patch-Einstieg: hier definierst du, welche Doctypes eine View bekommen sollen."""

    # 👇 HIER passt du deine Doctypes und View-Namen an
    view_specs = [
        # (Doctype-Name, View-Name)     # Beispiel: ERPNext Tenant
        ("Wohnung", "hv_wohnung"),       # Beispiel: Immobilie
        ("Immobilie", "hv_immobilie"),     # Beispiel: Wohnung
        ("Mietvertrag", "hv_mietvertrag"),             # Beispiel: Mietvertrag
        # oder deine eigenen:
        # ("Mieter", "hv_mieter"),
        # ("Wohnung", "hv_wohnung"),
        # ("Immobilie", "hv_immobilie"),
    ]

    for doctype, view_name in view_specs:
        generate_flat_view_for_doctype(doctype, view_name)



