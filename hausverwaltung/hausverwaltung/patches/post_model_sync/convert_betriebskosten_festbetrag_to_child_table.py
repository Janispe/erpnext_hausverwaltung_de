"""Migrate `Betriebskosten Festbetrag` from standalone-DocType to Mietvertrag-Child-Table.

The DocType was switched to `istable: 1` (with `mietvertrag` and `wohnung` fields removed).
The DB table `tabBetriebskosten Festbetrag` keeps its rows; we just need to populate the
generic Frappe child-row columns (`parent`, `parenttype`, `parentfield`, `idx`) from the
old standalone `mietvertrag` column before Frappe's DocType-Sync drops it.

Runs in `pre_model_sync` so the legacy `mietvertrag` column is still present.
Because the standalone DocType never had `parent`/`parenttype`/`parentfield`/`idx` columns,
we add them manually here before the UPDATE.

Idempotent: skips when there's nothing to do.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Betriebskosten Festbetrag"):
        return

    columns = {row[0] for row in frappe.db.sql("DESCRIBE `tabBetriebskosten Festbetrag`")}
    if "mietvertrag" not in columns:
        return  # already migrated or DocType-Sync already dropped the column

    # Standalone DocTypes lack the child-row columns — add them manually so the UPDATE
    # below succeeds. DocType-Sync will recognize them as existing afterwards.
    if "parent" not in columns:
        frappe.db.sql(
            "ALTER TABLE `tabBetriebskosten Festbetrag` ADD COLUMN `parent` VARCHAR(140)"
        )
    if "parenttype" not in columns:
        frappe.db.sql(
            "ALTER TABLE `tabBetriebskosten Festbetrag` ADD COLUMN `parenttype` VARCHAR(140)"
        )
    if "parentfield" not in columns:
        frappe.db.sql(
            "ALTER TABLE `tabBetriebskosten Festbetrag` ADD COLUMN `parentfield` VARCHAR(140)"
        )
    if "idx" not in columns:
        frappe.db.sql(
            "ALTER TABLE `tabBetriebskosten Festbetrag` ADD COLUMN `idx` INT(8) NOT NULL DEFAULT 0"
        )

    rows = frappe.db.sql(
        """
        SELECT name, mietvertrag
        FROM `tabBetriebskosten Festbetrag`
        WHERE (parent IS NULL OR parent = '') AND mietvertrag IS NOT NULL AND mietvertrag != ''
        """,
        as_dict=True,
    )

    counters: dict[str, int] = {}
    migrated = 0
    for r in rows:
        mv = r["mietvertrag"]
        idx = counters.get(mv, 0) + 1
        counters[mv] = idx
        frappe.db.sql(
            """
            UPDATE `tabBetriebskosten Festbetrag`
            SET parent=%s, parenttype='Mietvertrag', parentfield='festbetraege', idx=%s
            WHERE name=%s
            """,
            (mv, idx, r["name"]),
        )
        migrated += 1

    frappe.db.commit()
    if migrated:
        print(f"convert_betriebskosten_festbetrag_to_child_table: {migrated} rows attached to Mietvertrag")
