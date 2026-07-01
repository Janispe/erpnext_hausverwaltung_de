"""Show the Briefkopf right-note only for Verwaltung-addressed letters."""

from __future__ import annotations

import frappe


BRIEFKOPF_HTML = """<!-- Peters Briefkopf -->
<div class="sb-letterhead sb-letterhead-peters" style="position: relative; min-height: 4.1cm;">
  {% if not (an_verwaltung | int) %}
  <div style="position:absolute; left:0; top:0; line-height:1;">
    <img src="/files/{% if druck_schwarz_weiss is defined and (druck_schwarz_weiss | int) %}peters-siegel-sw.svg{% else %}peters-lockup.svg{% endif %}" alt="Peters Hausverwaltung" style="height:{% if druck_schwarz_weiss is defined and (druck_schwarz_weiss | int) %}1.15cm{% else %}1.42cm{% endif %};width:auto;" />
  </div>
  {% endif %}

  <div class="sb-address-window">
    <div class="sb-return-address">
      Hausverwaltung, Inga Peters, Tristanstr. 4, 14109 Berlin
    </div>
    <div class="sb-recipient">
      {% if (an_verwaltung | int) %}
      Hausverwaltung<br/>
      Inga Peters<br/>
      Tristanstr. 4<br/>
      14109 Berlin
      {% else %}
      {{ address.address_line1 if address else "" }}<br/>
      {{ address.pincode if address else "" }} {{ address.city if address else "" }}
      {% endif %}
    </div>
  </div>

  {% if (an_verwaltung | int) and kopf_rechts is defined and kopf_rechts %}
  <div class="sb-sender">
    <div style="font-weight: bold; margin-bottom: 10px;">
      {{ (kopf_rechts | string).replace('\\\\n', '<br/>').replace('\\n', '<br/>') | safe }}
    </div>
  </div>
  {% endif %}

  {% if not (an_verwaltung | int) %}
  <div class="sb-sender">
    <div style="line-height:1.25;">
      Hausverwaltung<br/>
      Inga Peters<br/>
      Tristanstr. 4<br/>
      14109 Berlin<br/>
      Tel.: 030/319 536-20<br/>
      Fax: 030/319 536-19<br/>
      <div class="sb-office-hours">
        Sprechzeiten: Mo + Do<br/>
        9.30 &ndash; 13.00 Uhr<br/>
        verwaltung@haus-peters.de
      </div>
    </div>
  </div>
  {% endif %}
</div>

<div class="sb-date">
  Berlin, den {{ brief_datum }}
</div>"""


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return
	if not frappe.db.exists("Serienbrief Textbaustein", "Briefkopf"):
		return

	doc = frappe.get_doc("Serienbrief Textbaustein", "Briefkopf")
	changed = False
	if doc.html_content != BRIEFKOPF_HTML:
		doc.html_content = BRIEFKOPF_HTML
		changed = True

	for row in doc.get("variables") or []:
		if getattr(row, "variable", None) == "kopf_rechts":
			description = (
				"Optionaler Text oben rechts ueber dem Briefkopf, nur wenn "
				"'An Verwaltung adressieren' = 1 ist. Zeilenumbrueche als echte "
				"Umbrueche oder \\n."
			)
			if getattr(row, "beschreibung", None) != description:
				row.beschreibung = description
				changed = True

	if changed:
		doc.save(ignore_permissions=True)
