// Sample data for the Serienbrief Browser prototype
// Folders (Kategorien) as a tree; templates with rich metadata (favorite, recent, missing paths)

export const BROWSER_FOLDERS = [
  { id: "mahnungen", title: "Mahnungen", parent: null, count: 8, color: "#b54545" },
  { id: "betriebskosten", title: "Betriebskostenabrechnung", parent: null, count: 6, color: "#8a4a10" },
  { id: "mietvertrag", title: "Mietvertrag", parent: null, count: 11, color: "#1859a0" },
  { id: "mv-kuendigungen", title: "Kündigungen", parent: "mietvertrag", count: 3 },
  { id: "mv-erhoehungen", title: "Mieterhöhungen", parent: "mietvertrag", count: 2 },
  { id: "eigentuemer", title: "Eigentümer / WEG", parent: null, count: 4, color: "#5b3a99" },
  { id: "allgemein", title: "Allgemein", parent: null, count: 5, color: "#2e6f5e" },
  { id: "import", title: "Dokumentvorlagen Import", parent: null, count: 412, color: "#7a7670" },
];

// Each template gets: id, title, folder, modified (ISO date), modified_by, favorite,
// missing_paths (count of bausteine that lack a path mapping for this template's haupt_verteil_objekt),
// last_used (most recent durchlauf), haupt_verteil_objekt, description.
export const BROWSER_TEMPLATES = [
  {
    id: "TPL-MAHN-001", title: "1. Mahnung", folder: "mahnungen",
    modified: "2026-05-21T14:32:00", modified_by: "j.peters@example.de",
    favorite: true, missing_paths: 0, last_used: "2026-05-23T09:14:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Erstmahnung mit Saldo-Anzeige und Zahlungsfrist.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Unterschrift Verwalter"], variables: 3,
    content: "Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},\n\nauf dem Mietkonto Ihrer Wohnung {{ wohnung.bezeichnung }} in der {{ immobilie.bezeichnung }} besteht aktuell ein offener Saldo in Höhe von {{ saldo }}.\n\nWir bitten Sie höflich, den fälligen Betrag bis spätestens {{ stichtag }} (Frist: {{ frist_tage }} Tage) auf unser Konto zu überweisen.\n\nSollten Sie den Betrag bereits überwiesen haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.\n\nMit freundlichen Grüßen\nPeters Hausverwaltung GmbH",
  },
  {
    id: "TPL-MAHN-002", title: "2. Mahnung", folder: "mahnungen",
    modified: "2026-05-19T11:08:00", modified_by: "j.peters@example.de",
    favorite: true, missing_paths: 1, last_used: "2026-05-22T15:30:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Mahnung mit Mahngebührenklausel und § 286 BGB-Hinweis.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Mahngebühren-Klausel", "Unterschrift Verwalter"], variables: 4,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

trotz unserer freundlichen Zahlungserinnerung vom {{ erste_mahnung_datum }} ist der offene Betrag in Höhe von {{ saldo }} noch nicht auf unserem Konto eingegangen.

Hinweis nach § 286 BGB: Mit Ablauf der oben genannten Frist befinden Sie sich in Verzug. Wir behalten uns vor, Verzugszinsen sowie eine angemessene Mahngebühr in Höhe von 5,00 € geltend zu machen.

Wir bitten Sie nun letztmalig, den Betrag bis {{ stichtag }} zu begleichen.

Mit freundlichen Grüßen`,
  },
  {
    id: "TPL-MAHN-003", title: "3. Mahnung (letzte Mahnung)", folder: "mahnungen",
    modified: "2026-05-14T16:55:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-05-20T10:22:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Letzte Mahnung vor gerichtlichem Verfahren.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Mahngebühren-Klausel", "Unterschrift Verwalter"], variables: 5,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

leider mussten wir feststellen, dass trotz unserer 1. und 2. Mahnung der ausstehende Betrag in Höhe von {{ saldo }} weiterhin nicht beglichen wurde.

Wir weisen Sie darauf hin, dass wir nach Ablauf der Frist am {{ stichtag }} ein gerichtliches Mahnverfahren einleiten und gegebenenfalls ein Inkasso-Unternehmen mit der Durchsetzung unserer Forderung beauftragen werden. Die dadurch entstehenden Kosten haben Sie zu tragen.

Mit freundlichen Grüßen`,
  },
  {
    id: "TPL-MAHN-004", title: "Zahlungserinnerung freundlich", folder: "mahnungen",
    modified: "2026-05-01T08:10:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-05-08T14:01:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Freundliche Erinnerung vor der ersten Mahnung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 2,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

bei der Überprüfung Ihres Mietkontos ist uns aufgefallen, dass die Miete für {{ monat }} noch nicht eingegangen ist. Möglicherweise handelt es sich um ein Versehen.

Wir bitten Sie höflich, den Betrag in Höhe von {{ saldo }} zeitnah auf unser Konto zu überweisen.

Mit freundlichen Grüßen`,
  },
  {
    id: "TPL-MAHN-005", title: "Mahnung Heizkosten-Vorauszahlung", folder: "mahnungen",
    modified: "2026-04-22T09:45:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 2, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Mahnung speziell für ausstehende Heizkosten-Vorauszahlungen.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Unterschrift Verwalter"], variables: 3,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

laut unseren Unterlagen sind die Heizkosten-Vorauszahlungen für die Monate {{ monate_offen }} noch offen. Der Gesamtbetrag beläuft sich auf {{ saldo }}.

Wir bitten Sie, diesen Betrag bis {{ stichtag }} auf unser Konto zu überweisen.`,
  },
  {
    id: "TPL-MAHN-006", title: "Außergerichtliche Mahnung", folder: "mahnungen",
    modified: "2026-03-30T13:22:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-04-12T11:00:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Letzte außergerichtliche Mahnung vor Inkasso.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Mahngebühren-Klausel"], variables: 4,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

dies ist unsere letzte außergerichtliche Mahnung. Sollte der Betrag von {{ saldo }} bis zum {{ stichtag }} nicht auf unserem Konto eingegangen sein, sehen wir uns gezwungen, gerichtliche Schritte einzuleiten.`,
  },
  {
    id: "TPL-MAHN-007", title: "Inkasso-Ankündigung", folder: "mahnungen",
    modified: "2026-02-18T15:30:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Ankündigung der Übergabe an ein Inkasso-Unternehmen.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 2,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

da Sie auf unsere Mahnungen nicht reagiert haben, übergeben wir die Angelegenheit am {{ stichtag }} an unser Inkasso-Unternehmen. Die dadurch entstehenden Kosten gehen zu Ihren Lasten.`,
  },
  {
    id: "TPL-MAHN-008", title: "Mahnung mit Ratenangebot", folder: "mahnungen",
    modified: "2026-01-10T10:05:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 1, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Mahnung mit Vorschlag einer Ratenzahlung.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Unterschrift Verwalter"], variables: 5,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

falls die sofortige Begleichung des offenen Betrags von {{ saldo }} eine Belastung darstellt, können wir Ihnen eine Ratenzahlung in Höhe von {{ rate }} monatlich anbieten.

Bitte teilen Sie uns bis {{ stichtag }} mit, ob Sie dieses Angebot annehmen möchten.`,
  },
  {
    id: "TPL-BK-001", title: "BK-Abrechnung Anschreiben", folder: "betriebskosten",
    modified: "2026-05-15T13:45:00", modified_by: "j.peters@example.de",
    favorite: true, missing_paths: 0, last_used: "2026-05-15T13:50:00",
    haupt_verteil_objekt: "BK Mieter", description: "Anschreiben für die jährliche Betriebskostenabrechnung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 3,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

anbei erhalten Sie die Betriebskostenabrechnung für das Jahr {{ abrechnungsjahr }}. Die Abrechnung ist nach den Bestimmungen Ihres Mietvertrags und der Heizkostenverordnung erstellt worden.

Bitte prüfen Sie die Aufstellung und melden Sie sich bei Rückfragen.`,
  },
  {
    id: "TPL-BK-002", title: "BK-Nachzahlungs-Anforderung", folder: "betriebskosten",
    modified: "2026-05-08T11:20:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-05-12T09:30:00",
    haupt_verteil_objekt: "BK Mieter", description: "Aufforderung zur Nachzahlung nach BK-Abrechnung.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Unterschrift Verwalter"], variables: 4,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

aus der beiliegenden Betriebskostenabrechnung für {{ abrechnungsjahr }} ergibt sich eine Nachzahlung in Höhe von {{ nachzahlung }}.

Bitte überweisen Sie den Betrag bis {{ stichtag }} auf unser Konto.`,
  },
  {
    id: "TPL-BK-003", title: "BK-Guthaben-Erstattung", folder: "betriebskosten",
    modified: "2026-05-08T11:25:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-05-12T09:35:00",
    haupt_verteil_objekt: "BK Mieter", description: "Benachrichtigung über BK-Guthaben und Erstattung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 3,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

aus der beiliegenden Betriebskostenabrechnung für {{ abrechnungsjahr }} ergibt sich ein Guthaben in Höhe von {{ guthaben }}.

Der Betrag wird in den nächsten Tagen auf Ihr Konto erstattet.`,
  },
  {
    id: "TPL-BK-004", title: "Vorauszahlungs-Anpassung", folder: "betriebskosten",
    modified: "2026-04-21T14:10:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "BK Mieter", description: "Mitteilung über Anpassung der monatlichen Vorauszahlung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 2,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

basierend auf der letzten Betriebskostenabrechnung passen wir Ihre monatliche Vorauszahlung ab {{ ab_datum }} auf {{ neuer_betrag }} an.`,
  },
  {
    id: "TPL-BK-005", title: "Widerspruch-Antwort BK", folder: "betriebskosten",
    modified: "2026-02-14T16:00:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 3, last_used: null,
    haupt_verteil_objekt: "BK Mieter", description: "Antwort auf einen Widerspruch gegen die BK-Abrechnung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 1,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

zu Ihrem Widerspruch gegen die Betriebskostenabrechnung {{ abrechnungsjahr }} möchten wir wie folgt Stellung nehmen: ...`,
  },
  {
    id: "TPL-BK-006", title: "BK-Erläuterung Mieter", folder: "betriebskosten",
    modified: "2025-11-08T10:30:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "BK Mieter", description: "Allgemeine Erläuterung der Position auf der BK-Abrechnung.",
    bausteine: ["Anrede formal"], variables: 1,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

gerne erläutern wir Ihnen die einzelnen Positionen Ihrer Betriebskostenabrechnung im Detail.`,
  },
  {
    id: "TPL-MV-001", title: "Mietvertrag Standard", folder: "mietvertrag",
    modified: "2026-04-12T09:00:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-05-02T10:15:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Standardvorlage für neue Mietverträge.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 8,
    content: `Mietvertrag

zwischen
{{ vermieter.name }}, {{ vermieter.adresse }} (Vermieter)
und
{{ mieter.vollname }}, {{ mieter.adresse }} (Mieter)

§ 1 Mietobjekt
Der Vermieter vermietet an den Mieter die Wohnung {{ wohnung.bezeichnung }} in {{ immobilie.bezeichnung }} mit einer Wohnfläche von {{ wohnung.qm }} m².

§ 2 Mietzeit
Das Mietverhältnis beginnt am {{ mietvertrag.von }} und läuft auf unbestimmte Zeit.`,
  },
  {
    id: "TPL-MV-002", title: "Mietvertrag Staffel", folder: "mietvertrag",
    modified: "2026-03-22T11:30:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 1, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Mietvertrag mit Staffelmietvereinbarung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 12,
    content: `Mietvertrag mit Staffelmietvereinbarung

zwischen
{{ vermieter.name }} (Vermieter)
und
{{ mieter.vollname }} (Mieter)

§ 5 Staffelmiete
Die Miete erhöht sich gemäß folgender Staffel:
- Ab {{ staffel_1_datum }}: {{ staffel_1_betrag }}
- Ab {{ staffel_2_datum }}: {{ staffel_2_betrag }}`,
  },
  {
    id: "TPL-KUEND-001", title: "Kündigung Mieter (Bestätigung)", folder: "mv-kuendigungen",
    modified: "2026-05-05T13:10:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: "2026-05-18T08:00:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Bestätigung einer Mieterkündigung mit Räumungstermin.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 4,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

wir bestätigen Ihnen den Erhalt Ihrer Kündigung vom {{ kuendigungsdatum }} für die Wohnung {{ wohnung.bezeichnung }}.

Das Mietverhältnis endet am {{ vertragsende }}. Die Wohnungsübergabe wird am {{ uebergabe_datum }} stattfinden.`,
  },
  {
    id: "TPL-KUEND-002", title: "Kündigung Vermieter (Eigenbedarf)", folder: "mv-kuendigungen",
    modified: "2026-03-15T15:50:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Kündigung wegen Eigenbedarfs nach § 573 BGB.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 6,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

hiermit kündigen wir das Mietverhältnis über die Wohnung {{ wohnung.bezeichnung }} aufgrund von Eigenbedarf nach § 573 Abs. 2 Nr. 2 BGB ordentlich zum {{ kuendigungstermin }}.

Begründung des Eigenbedarfs: {{ eigenbedarf_begruendung }}`,
  },
  {
    id: "TPL-KUEND-003", title: "Räumungsfrist-Vereinbarung", folder: "mv-kuendigungen",
    modified: "2026-01-22T14:20:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Vereinbarung über eine verlängerte Räumungsfrist.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 3,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

auf Ihren Antrag vereinbaren wir hiermit eine verlängerte Räumungsfrist bis zum {{ neue_raeumungsfrist }}.`,
  },
  {
    id: "TPL-MIETERH-001", title: "Mieterhöhung nach Mietspiegel", folder: "mv-erhoehungen",
    modified: "2026-05-12T10:00:00", modified_by: "j.peters@example.de",
    favorite: true, missing_paths: 0, last_used: "2026-05-22T14:00:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Mieterhöhungsverlangen mit Bezug auf den örtlichen Mietspiegel.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Unterschrift Verwalter"], variables: 6,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

hiermit verlangen wir die Zustimmung zu einer Mieterhöhung auf {{ neue_miete }} ab dem {{ ab_datum }}. Die Erhöhung erfolgt unter Bezugnahme auf den Mietspiegel der Stadt {{ stadt }} vom {{ mietspiegel_datum }}.`,
  },
  {
    id: "TPL-MIETERH-002", title: "Mieterhöhung Modernisierung", folder: "mv-erhoehungen",
    modified: "2026-03-08T11:15:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 2, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Mieterhöhung nach Modernisierungsmaßnahmen.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 8,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

nach Abschluss der Modernisierungsmaßnahmen erhöht sich die Miete gemäß § 559 BGB um {{ erhoehung }} auf {{ neue_miete }} ab dem {{ ab_datum }}.`,
  },
  {
    id: "TPL-WEG-001", title: "WEG-Einladung Versammlung", folder: "eigentuemer",
    modified: "2026-05-18T09:30:00", modified_by: "m.schmidt@example.de",
    favorite: true, missing_paths: 0, last_used: "2026-05-21T11:00:00",
    haupt_verteil_objekt: "Eigentümer", description: "Einladung zur jährlichen Eigentümerversammlung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 5,
    content: `Sehr geehrte/r {{ eigentuemer.brief_anrede }} {{ eigentuemer.nachname }},

hiermit lade ich Sie zur ordentlichen Eigentümerversammlung am {{ versammlungstermin }} um {{ versammlungszeit }} in {{ versammlungsort }} ein.

Tagesordnung:
1. Begrüßung
2. Bericht des Verwalters
3. Vorlage der Jahresabrechnung {{ abrechnungsjahr }}`,
  },
  {
    id: "TPL-WEG-002", title: "Hausgeld-Abrechnung", folder: "eigentuemer",
    modified: "2026-05-10T13:00:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 1, last_used: "2026-05-14T15:30:00",
    haupt_verteil_objekt: "Eigentümer", description: "Jährliche Hausgeld-Abrechnung für Eigentümer.",
    bausteine: ["Anrede formal", "Saldo-Berechnung", "Unterschrift Verwalter"], variables: 7,
    content: `Sehr geehrte/r {{ eigentuemer.brief_anrede }} {{ eigentuemer.nachname }},

anbei erhalten Sie die Hausgeld-Abrechnung für das Wirtschaftsjahr {{ abrechnungsjahr }}.`,
  },
  {
    id: "TPL-WEG-003", title: "Sonderumlage-Ankündigung", folder: "eigentuemer",
    modified: "2026-04-02T10:45:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Eigentümer", description: "Ankündigung einer Sonderumlage für anstehende Reparaturen.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 4,
    content: `Sehr geehrte/r {{ eigentuemer.brief_anrede }} {{ eigentuemer.nachname }},

aufgrund der anstehenden {{ massnahme }} ist eine Sonderumlage in Höhe von {{ sonderumlage_betrag }} erforderlich.`,
  },
  {
    id: "TPL-WEG-004", title: "Beschlussfassung Protokoll", folder: "eigentuemer",
    modified: "2026-02-28T16:20:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Eigentümer", description: "Protokoll der Beschlussfassung der WEG-Versammlung.",
    bausteine: ["Unterschrift Verwalter"], variables: 3,
    content: `Protokoll der Eigentümerversammlung vom {{ versammlungsdatum }}.

Beschluss Nr. {{ beschluss_nummer }}: {{ beschluss_text }}

Abstimmungsergebnis: {{ ja_stimmen }} Ja, {{ nein_stimmen }} Nein, {{ enthaltungen }} Enthaltungen.`,
  },
  {
    id: "TPL-ALLG-001", title: "Hausordnung Verteilung", folder: "allgemein",
    modified: "2026-02-10T12:30:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Verteilung der aktualisierten Hausordnung an alle Mieter.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 1,
    content: `Sehr geehrte Mieterinnen und Mieter,

im Anhang finden Sie die aktualisierte Hausordnung, die ab dem {{ ab_datum }} gültig ist. Bitte beachten Sie die neuen Regelungen zu Ruhezeiten und Müllentsorgung.`,
  },
  {
    id: "TPL-ALLG-002", title: "Reparatur-Ankündigung", folder: "allgemein",
    modified: "2026-05-19T10:00:00", modified_by: "m.schmidt@example.de",
    favorite: true, missing_paths: 0, last_used: "2026-05-20T08:00:00",
    haupt_verteil_objekt: "Mietvertrag", description: "Ankündigung von geplanten Reparaturarbeiten im Haus.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 4,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

am {{ termin }} werden in unserem Haus {{ arbeit_beschreibung }} durchgeführt. Wir bitten Sie um Verständnis für eventuelle Lärmbelästigung.`,
  },
  {
    id: "TPL-ALLG-003", title: "Ablesung Heizkosten", folder: "allgemein",
    modified: "2026-03-22T14:00:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Terminankündigung der jährlichen Heizkostenablesung.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 3,
    content: `Sehr geehrte/r {{ mieter.brief_anrede }} {{ mieter.nachname }},

die jährliche Heizkostenablesung findet am {{ ablese_termin }} zwischen {{ ablese_zeit_von }} und {{ ablese_zeit_bis }} statt. Bitte sorgen Sie für Zugang zu allen Heizkörpern.`,
  },
  {
    id: "TPL-ALLG-004", title: "Schlüssel-Übergabe", folder: "allgemein",
    modified: "2026-04-15T11:30:00", modified_by: "m.schmidt@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Protokoll der Schlüsselübergabe bei Mieterwechsel.",
    bausteine: ["Anrede formal", "Unterschrift Verwalter"], variables: 5,
    content: `Übergabeprotokoll Schlüssel

Mieter: {{ mieter.vollname }}
Wohnung: {{ wohnung.bezeichnung }}
Datum der Übergabe: {{ uebergabe_datum }}

Übergebene Schlüssel: {{ schluessel_anzahl }} Stück`,
  },
  {
    id: "TPL-ALLG-005", title: "Adress-Änderung Verwalter", folder: "allgemein",
    modified: "2026-01-05T09:00:00", modified_by: "j.peters@example.de",
    favorite: false, missing_paths: 0, last_used: null,
    haupt_verteil_objekt: "Mietvertrag", description: "Mitteilung über neue Adresse der Hausverwaltung.",
    bausteine: ["Unterschrift Verwalter"], variables: 2,
    content: `Sehr geehrte Mieterinnen und Mieter,

wir möchten Sie informieren, dass die Hausverwaltung ab dem {{ ab_datum }} unter folgender neuer Adresse erreichbar ist:

{{ neue_adresse }}`,
  },
];

