from __future__ import annotations

from frappe.utils import add_days, add_months, date_diff, getdate, month_diff


# Frappes Auto Repeat setzt nur Date-Felder mit `reqd=1` auf das neue
# Schedule-Datum (siehe frappe/automation/doctype/auto_repeat/auto_repeat.py).
# Alle anderen Date-Felder werden vom Master-Dokument 1:1 kopiert und kleben
# am ursprünglichen Datum. Bei wiederkehrenden Eingangsrechnungen
# (Personalzahlungen, Wartungsverträge etc.) sollen aber auch Felder wie
# `bill_date`, `due_date` und das Custom-Feld `custom_wertstellungsdatum`
# (= Leistungszeitraum) mit dem Schedule mitwandern.
_DATE_FIELDS_TO_SHIFT = (
	"bill_date",
	"due_date",
	"custom_wertstellungsdatum",
)


def shift_dates_for_recurring(doc, method=None, reference_doc=None, auto_repeat_doc=None):
	"""``on_recurring``-Handler: verschiebt nicht-pflichtige Date-Felder um den
	gleichen Zeit-Offset wie ``posting_date``.

	Bei monatlichen/quartalsweisen/jährlichen Frequenzen wird per Kalendermonat
	verschoben (``add_months``), damit z.B. der 31.01. → 28.02. → 31.03. sauber
	wandert. Bei Daily/Weekly wird Tag-genau verschoben.
	"""
	if not reference_doc:
		return

	ref_posting = getdate(getattr(reference_doc, "posting_date", None))
	new_posting = getdate(getattr(doc, "posting_date", None))
	if not ref_posting or not new_posting or ref_posting == new_posting:
		return

	months = month_diff(new_posting, ref_posting)
	use_months = months and months != 0

	for fieldname in _DATE_FIELDS_TO_SHIFT:
		original = reference_doc.get(fieldname) if hasattr(reference_doc, "get") else getattr(reference_doc, fieldname, None)
		if not original:
			continue
		try:
			if use_months:
				doc.set(fieldname, add_months(original, months))
			else:
				doc.set(fieldname, add_days(original, date_diff(new_posting, ref_posting)))
		except Exception:
			# Defensiv: ein einzelnes Feld soll den ganzen Auto-Repeat-Lauf nicht
			# zum Stehen bringen. Fehlende Custom-Felder etc. werden geschluckt.
			continue
