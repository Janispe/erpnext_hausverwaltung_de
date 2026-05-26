// Sample data for Serienbrief Editor prototype
// Realistic Hausverwaltung context

export const SAMPLE_RECIPIENTS = [
  {
    id: "MV-2024-0142",
    label: "Müller, Andreas — Tristanstr. 4, WE 03",
    doctype: "Mietvertrag",
    values: {
      "mieter.anrede": "Herr",
      "mieter.brief_anrede": "Herr",
      "mieter.vorname": "Andreas",
      "mieter.nachname": "Müller",
      "mieter.vollname": "Andreas Müller",
      "mieter.strasse": "Tristanstr. 4",
      "mieter.plz_ort": "80637 München",
      "verwalter.name": "Peters Hausverwaltung GmbH",
      "verwalter.strasse": "Leopoldstr. 112",
      "verwalter.plz_ort": "80802 München",
      "wohnung.bezeichnung": "WE 03 (3-Zi., 78,5 m²)",
      "wohnung.qm": "78,50",
      "immobilie.bezeichnung": "Tristanstr. 4, 80637 München",
      "saldo": "–847,32 €",
      "saldo_betrag": "847,32",
      "mietvertrag.von": "01.04.2022",
      "mietvertrag.bis": "unbefristet",
      "kaltmiete": "1.245,00 €",
      "nebenkosten": "285,00 €",
      "warmmiete": "1.530,00 €",
      "datum": "21. Mai 2026",
      "datum_iso": "2026-05-21",
      "stichtag": "31. Mai 2026",
      "frist_tage": "14",
      "mahnstufe": "1",
      "bankkonto.iban": "DE89 3704 0044 0532 0130 00",
      "bankkonto.bic": "COBADEFFXXX",
      "bankkonto.bank": "Commerzbank München",
    },
  },
  {
    id: "MV-2023-0098",
    label: "Schäfer, Marlene — Tristanstr. 4, WE 07",
    doctype: "Mietvertrag",
    values: {
      "mieter.anrede": "Frau",
      "mieter.brief_anrede": "Frau",
      "mieter.vorname": "Marlene",
      "mieter.nachname": "Schäfer",
      "mieter.vollname": "Marlene Schäfer",
      "mieter.strasse": "Tristanstr. 4",
      "mieter.plz_ort": "80637 München",
      "verwalter.name": "Peters Hausverwaltung GmbH",
      "verwalter.strasse": "Leopoldstr. 112",
      "verwalter.plz_ort": "80802 München",
      "wohnung.bezeichnung": "WE 07 (2-Zi., 54,2 m²)",
      "wohnung.qm": "54,20",
      "immobilie.bezeichnung": "Tristanstr. 4, 80637 München",
      "saldo": "0,00 €",
      "saldo_betrag": "0,00",
      "mietvertrag.von": "15.08.2023",
      "mietvertrag.bis": "unbefristet",
      "kaltmiete": "920,00 €",
      "nebenkosten": "210,00 €",
      "warmmiete": "1.130,00 €",
      "datum": "21. Mai 2026",
      "datum_iso": "2026-05-21",
      "stichtag": "31. Mai 2026",
      "frist_tage": "14",
      "mahnstufe": "1",
      "bankkonto.iban": "DE89 3704 0044 0532 0130 00",
      "bankkonto.bic": "COBADEFFXXX",
      "bankkonto.bank": "Commerzbank München",
    },
  },
  {
    id: "MV-2021-0034",
    label: "Bauer, Reinhold — Leopoldstr. 88, WE 12",
    doctype: "Mietvertrag",
    values: {
      "mieter.anrede": "Herr",
      "mieter.brief_anrede": "Herr",
      "mieter.vorname": "Reinhold",
      "mieter.nachname": "Bauer",
      "mieter.vollname": "Reinhold Bauer",
      "mieter.strasse": "Leopoldstr. 88",
      "mieter.plz_ort": "80802 München",
      "verwalter.name": "Peters Hausverwaltung GmbH",
      "verwalter.strasse": "Leopoldstr. 112",
      "verwalter.plz_ort": "80802 München",
      "wohnung.bezeichnung": "WE 12 (4-Zi., 102,8 m²)",
      "wohnung.qm": "102,80",
      "immobilie.bezeichnung": "Leopoldstr. 88, 80802 München",
      "saldo": "–2.412,55 €",
      "saldo_betrag": "2.412,55",
      "mietvertrag.von": "01.09.2021",
      "mietvertrag.bis": "unbefristet",
      "kaltmiete": "1.820,00 €",
      "nebenkosten": "395,00 €",
      "warmmiete": "2.215,00 €",
      "datum": "21. Mai 2026",
      "datum_iso": "2026-05-21",
      "stichtag": "31. Mai 2026",
      "frist_tage": "14",
      "mahnstufe": "2",
      "bankkonto.iban": "DE89 3704 0044 0532 0130 00",
      "bankkonto.bic": "COBADEFFXXX",
      "bankkonto.bank": "Commerzbank München",
    },
  },
];

export const PLACEHOLDER_GROUPS = [
  {
    key: "mieter",
    label: "Mieter",
    icon: "user",
    items: [
      { token: "{{ mieter.anrede }}", label: "Anrede", desc: "Herr / Frau / Divers" },
      { token: "{{ mieter.brief_anrede }}", label: "Brief-Anrede", desc: "Für Anschriftfeld" },
      { token: "{{ mieter.vorname }}", label: "Vorname" },
      { token: "{{ mieter.nachname }}", label: "Nachname" },
      { token: "{{ mieter.vollname }}", label: "Vollname", desc: "Vorname + Nachname" },
      { token: "{{ mieter.strasse }}", label: "Straße" },
      { token: "{{ mieter.plz_ort }}", label: "PLZ + Ort" },
    ],
  },
  {
    key: "verwalter",
    label: "Verwalter",
    icon: "building",
    items: [
      { token: "{{ verwalter.name }}", label: "Verwalter-Name" },
      { token: "{{ verwalter.strasse }}", label: "Verwalter-Straße" },
      { token: "{{ verwalter.plz_ort }}", label: "Verwalter PLZ + Ort" },
    ],
  },
  {
    key: "wohnung",
    label: "Wohnung",
    icon: "door",
    items: [
      { token: "{{ wohnung.bezeichnung }}", label: "Wohnungs-Bezeichnung" },
      { token: "{{ wohnung.qm }}", label: "Wohnfläche (m²)" },
      { token: "{{ immobilie.bezeichnung }}", label: "Immobilie" },
    ],
  },
  {
    key: "vertrag",
    label: "Vertrag & Beträge",
    icon: "euro",
    items: [
      { token: "{{ saldo }}", label: "Saldo (formatiert)", desc: "Aktueller Kontostand" },
      { token: "{{ saldo_betrag }}", label: "Saldo (Betrag)", desc: "Nur Zahl, ohne €" },
      { token: "{{ kaltmiete }}", label: "Kaltmiete" },
      { token: "{{ nebenkosten }}", label: "Nebenkosten" },
      { token: "{{ warmmiete }}", label: "Warmmiete" },
      { token: "{{ mietvertrag.von }}", label: "Einzug" },
      { token: "{{ mietvertrag.bis }}", label: "Auszug / Vertragsende" },
      { token: "{{ mahnstufe }}", label: "Mahnstufe" },
    ],
  },
  {
    key: "datum",
    label: "Datum & Fristen",
    icon: "calendar",
    items: [
      { token: "{{ datum }}", label: "Heute (formatiert)", desc: "21. Mai 2026" },
      { token: "{{ datum_iso }}", label: "Heute (ISO)", desc: "2026-05-21" },
      { token: "{{ stichtag }}", label: "Stichtag" },
      { token: "{{ frist_tage }}", label: "Frist (Tage)" },
    ],
  },
  {
    key: "bank",
    label: "Bankverbindung",
    icon: "credit-card",
    items: [
      { token: "{{ bankkonto.iban }}", label: "IBAN" },
      { token: "{{ bankkonto.bic }}", label: "BIC" },
      { token: "{{ bankkonto.bank }}", label: "Bank-Name" },
    ],
  },
];

export const SNIPPETS = [
  {
    key: "if",
    label: "Bedingung (if / endif)",
    desc: "{% if … %} … {% endif %}",
    value: `{% if BEDINGUNG %}\n\n{% endif %}`,
  },
  {
    key: "if-else",
    label: "Bedingung mit Else",
    desc: "{% if … %} … {% else %} … {% endif %}",
    value: `{% if BEDINGUNG %}\n\n{% else %}\n\n{% endif %}`,
  },
  {
    key: "if-eq",
    label: "Bedingung mit Vergleich",
    desc: "{% if x == \"Wert\" %} …",
    value: `{% if FELD == "WERT" %}\n\n{% endif %}`,
  },
  {
    key: "for",
    label: "Schleife (for / endfor)",
    desc: "{% for item in liste %} … {% endfor %}",
    value: `{% for item in liste %}\n\n{% endfor %}`,
  },
  {
    key: "set",
    label: "Variable setzen (set)",
    desc: "{% set name = wert %} — z. B. {% set stufe = serienbrief.werte.stufe | int %}",
    value: `{% set VARIABLE = WERT %}`,
  },
];

export const TEXT_BAUSTEINE = [
  { name: "Anrede formal", desc: "Sehr geehrte/r …,", preview: "Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }}," },
  { name: "Unterschrift Verwalter", desc: "Standard-Unterschriftsblock · Seitenumbruch davor", preview: "Mit freundlichen Grüßen\n\n{{ verwalter.name }}\n\n_______________________________\n(i. A. Janis Peters)", pageBreakBefore: true },
  { name: "Fußzeile Bankverbindung", desc: "IBAN / BIC / Bank", preview: "Bankverbindung: {{ bankkonto.iban }} · BIC: {{ bankkonto.bic }} · {{ bankkonto.bank }}" },
  { name: "Hinweis Datenschutz", desc: "Standard DSGVO-Fußnote", preview: "Hinweis zum Datenschutz: Wir verarbeiten Ihre personenbezogenen Daten ausschließlich zur Durchführung des Mietverhältnisses und zur Erfüllung gesetzlicher Pflichten. Empfänger und Zwecke entnehmen Sie unserer Datenschutzerklärung. Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung sowie Widerspruch und Datenübertragbarkeit." },
  { name: "Mahngebühren-Klausel", desc: "§ 286 BGB-Hinweis", preview: "Hinweis nach § 286 BGB: Mit Ablauf der oben genannten Frist befinden Sie sich in Verzug. Wir behalten uns vor, Verzugszinsen in Höhe von 5 Prozentpunkten über dem Basiszinssatz sowie eine angemessene Mahnpauschale geltend zu machen. Sollte auch nach Ablauf einer weiteren Frist keine Zahlung erfolgen, sind wir gezwungen, ein gerichtliches Mahnverfahren einzuleiten und gegebenenfalls ein Inkasso-Unternehmen mit der Durchsetzung unserer Forderung zu beauftragen. Die dadurch entstehenden Kosten haben Sie zu tragen." },
];

export const TEMPLATE_VARIABLES = [
  { name: "frist_tage", type: "Zahl", default: "14", desc: "Zahlungsfrist in Tagen" },
  { name: "mahngebuehr", type: "Zahl", default: "5,00", desc: "Mahngebühr in Euro" },
  { name: "kontonummer", type: "String", default: "DE89 3704 0044 0532 0130 00", desc: "Empfänger-IBAN" },
];

export const TEMPLATE_TREE = [
  {
    key: "mahnungen",
    label: "Mahnungen",
    count: 8,
    pinned: true,
    templates: [
      { id: "t-001", title: "1. Mahnung", modified: "Vor 2 Tagen", current: true },
      { id: "t-002", title: "2. Mahnung", modified: "Vor 2 Tagen" },
      { id: "t-003", title: "3. Mahnung (letzte Mahnung)", modified: "Vor 1 Woche" },
      { id: "t-004", title: "Zahlungserinnerung freundlich", modified: "Vor 3 Wochen" },
      { id: "t-005", title: "Mahnung Heizkosten-Vorauszahlung", modified: "Vor 1 Monat" },
      { id: "t-006", title: "Außergerichtliche Mahnung", modified: "Vor 2 Monaten" },
      { id: "t-007", title: "Inkasso-Ankündigung", modified: "Vor 4 Monaten" },
      { id: "t-008", title: "Mahnung mit Ratenangebot", modified: "Vor 5 Monaten" },
    ],
  },
  {
    key: "betriebskosten",
    label: "Betriebskostenabrechnung",
    count: 6,
    templates: [
      { id: "t-101", title: "BK-Abrechnung Anschreiben", modified: "Vor 1 Woche" },
      { id: "t-102", title: "BK-Nachzahlungs-Anforderung", modified: "Vor 2 Wochen" },
      { id: "t-103", title: "BK-Guthaben-Erstattung", modified: "Vor 2 Wochen" },
      { id: "t-104", title: "Vorauszahlungs-Anpassung", modified: "Vor 1 Monat" },
      { id: "t-105", title: "Widerspruch-Antwort BK", modified: "Vor 3 Monaten" },
      { id: "t-106", title: "BK-Erläuterung Mieter", modified: "Vor 6 Monaten" },
    ],
  },
  {
    key: "mietvertrag",
    label: "Mietvertrag",
    count: 11,
    templates: [
      { id: "t-201", title: "Mietvertrag Standard", modified: "Vor 1 Monat" },
      { id: "t-202", title: "Mietvertrag Staffel", modified: "Vor 2 Monaten" },
      { id: "t-203", title: "Kündigung Mieter (Bestätigung)", modified: "Vor 3 Wochen" },
      { id: "t-204", title: "Kündigung Vermieter (Eigenbedarf)", modified: "Vor 2 Monaten" },
      { id: "t-205", title: "Mieterhöhung nach Mietspiegel", modified: "Vor 1 Woche" },
      { id: "t-206", title: "Mieterhöhung Modernisierung", modified: "Vor 2 Monaten" },
      { id: "t-207", title: "Wohnungs-Übergabeprotokoll", modified: "Vor 3 Wochen" },
    ],
  },
  {
    key: "eigentuemer",
    label: "Eigentümer / WEG",
    count: 4,
    templates: [
      { id: "t-301", title: "WEG-Einladung Versammlung", modified: "Vor 1 Woche" },
      { id: "t-302", title: "Hausgeld-Abrechnung", modified: "Vor 2 Wochen" },
      { id: "t-303", title: "Sonderumlage-Ankündigung", modified: "Vor 1 Monat" },
      { id: "t-304", title: "Beschlussfassung Protokoll", modified: "Vor 2 Monaten" },
    ],
  },
  {
    key: "allgemein",
    label: "Allgemein",
    count: 5,
    templates: [
      { id: "t-401", title: "Hausordnung Verteilung", modified: "Vor 3 Monaten" },
      { id: "t-402", title: "Reparatur-Ankündigung", modified: "Vor 1 Woche" },
      { id: "t-403", title: "Ablesung Heizkosten", modified: "Vor 2 Monaten" },
      { id: "t-404", title: "Schlüssel-Übergabe", modified: "Vor 1 Monat" },
      { id: "t-405", title: "Adress-Änderung Verwalter", modified: "Vor 4 Monaten" },
    ],
  },
  {
    key: "import",
    label: "Dokumentvorlagen Import",
    count: 412,
    templates: [
      { id: "t-901", title: "Altbestand: Anschreiben Mieter", modified: "Importiert" },
      { id: "t-902", title: "Altbestand: BK 2022 Vorlage", modified: "Importiert" },
    ],
  },
];

// Demo-Vorlage "1. Mahnung" im DB-Format (rohe Jinja-Tokens) – nur für Standalone-Dev
// (npm run dev). Dogfoodt: Ausrichtung, Marks, Baustein, Platzhalter, Tabellen-Loop, if-Block.
export const CURRENT_TEMPLATE = {
  id: "t-001",
  title: "1. Mahnung",
  kategorie: "Mahnungen",
  haupt_verteil_objekt: "Mietvertrag",
  content_type: "Textbaustein (Rich Text)",
  content_position: "Nach Bausteinen",
  modified: "21.05.2026 14:32",
  modified_by: "j.peters@example.de",
  canWrite: true,
  htmlContent: `<p style="text-align: right">M\u00fcnchen, {{ datum }}</p>
<p>{{ mieter.anrede }} {{ mieter.vorname }} {{ mieter.nachname }}</p>
<p>{{ mieter.strasse }}</p>
<p>{{ mieter.plz_ort }}</p>
<h2>Zahlungserinnerung \u2014 Mietvertrag {{ wohnung.bezeichnung }}</h2>
<div>{{ baustein("Anrede formal") }}</div>
<p>auf dem Mietkonto Ihrer Wohnung {{ wohnung.bezeichnung }} in der {{ immobilie.bezeichnung }} ist aktuell ein offener Saldo in H\u00f6he von <strong>{{ saldo }}</strong> ausgewiesen.</p>
<p>Die offenen Posten im Einzelnen:</p>
<table><thead><tr><th>Rechnung</th><th>F\u00e4llig</th><th style="text-align: right">Offen</th></tr></thead><tbody>
{% for row in payments %}
<tr><td>{{ row.sales_invoice }}</td><td>{{ row.due_date }}</td><td style="text-align: right">{{ row.outstanding }}</td></tr>
{% endfor %}
</tbody></table>
<p>Wir bitten Sie h\u00f6flich, den f\u00e4lligen Betrag bis sp\u00e4testens {{ stichtag }} (Frist: {{ frist_tage }} Tage) zu \u00fcberweisen.</p>
{% if mahnstufe == "2" %}
<p>Da es sich um die zweite Mahnung handelt, erheben wir eine Mahngeb\u00fchr in H\u00f6he von 5,00 \u20ac.</p>
{% endif %}
<p>Sollten Sie den Betrag bereits \u00fcberwiesen haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.</p>
<div>{{ baustein("Unterschrift Verwalter") }}</div>`,
};
