// Mock-Daten für den Standalone-Dev-Modus (npm run dev, ohne Frappe-Host).
// Spiegeln die Shapes, die der Backend-Adapter get_overview / get_open_invoices_for_row
// liefert, damit das UI ohne Backend entwickelbar bleibt.

export const MOCK_OVERVIEW = {
	import: {
		name: "BAI-1812-DEMO-0001",
		title: "Wilhelmshavener (1812) · 01.04.–30.04.2026 · 6 Buchungen",
		bankAccount: "Wilhelmshavener (1812)",
		bankAccountName: "Wilhelmshavener - Postbank",
		iban: "DE89100100100123456789",
		csvFile: "/files/kontoauszug_april.csv",
		saldoLautBank: 12450.32,
		saldoLautERP: 11900.32,
		saldoDifferenz: 550.0,
		saldoStichtag: "2026-04-30",
		status: "Phase 3: 4/6 Belege zugeordnet — 2 offen",
		offeneBuchungen: 2,
	},
	rows: [
		{
			id: "r1", buchungstag: "2026-04-03", betrag: 720.0, richtung: "Eingang",
			iban: "DE12500105170648489890", auftraggeber: "Max Mustermann",
			verwendungszweck: "Miete April Whg 3 OG SINV-2026-0041", partyTyp: "Customer",
			party: "Max Mustermann", bankTransaction: "BT-2026-0101", paymentEntry: "",
			journalEntry: "", rowStatus: "phase3-open", phase: 3, autoMatchMessage: "",
		},
		{
			id: "r2", buchungstag: "2026-04-05", betrag: -89.9, richtung: "Ausgang",
			iban: "DE44500105175407324931", auftraggeber: "Stadtwerke Beispielstadt",
			verwendungszweck: "Abschlag Strom Objekt Hauptstr. 5", partyTyp: "Supplier",
			party: "Stadtwerke Beispielstadt", bankTransaction: "BT-2026-0102", paymentEntry: "",
			journalEntry: "", rowStatus: "phase3-open", phase: 3, autoMatchMessage: "",
		},
		{
			id: "r3", buchungstag: "2026-04-07", betrag: -12.5, richtung: "Ausgang",
			iban: "", auftraggeber: "Postbank", verwendungszweck: "Kontoführungsgebühr",
			partyTyp: "", party: "", bankTransaction: "BT-2026-0103", paymentEntry: "",
			journalEntry: "", rowStatus: "phase3-open", phase: 3, autoMatchMessage: "",
		},
		{
			id: "r4", buchungstag: "2026-04-10", betrag: 540.0, richtung: "Eingang",
			iban: "DE77100100100999888777", auftraggeber: "Erika Beispiel",
			verwendungszweck: "Ueberweisung", partyTyp: "", party: "",
			bankTransaction: "", paymentEntry: "", journalEntry: "",
			rowStatus: "phase1-no-party", phase: 1, autoMatchMessage: "",
		},
		{
			id: "r5", buchungstag: "2026-04-15", betrag: 720.0, richtung: "Eingang",
			iban: "DE12500105170648489890", auftraggeber: "Max Mustermann",
			verwendungszweck: "Miete Mai", partyTyp: "Customer", party: "Max Mustermann",
			bankTransaction: "", paymentEntry: "", journalEntry: "",
			rowStatus: "phase3-open", phase: 3, autoMatchMessage: "",
		},
		{
			id: "r6", buchungstag: "2026-04-28", betrag: 720.0, richtung: "Eingang",
			iban: "DE12500105170648489890", auftraggeber: "Max Mustermann",
			verwendungszweck: "Miete Maerz SINV-2026-0033", partyTyp: "Customer",
			party: "Max Mustermann", bankTransaction: "BT-2026-0106",
			paymentEntry: "PE-2026-0050", journalEntry: "", rowStatus: "done", phase: 4,
			autoMatchMessage: "Auto-Match: 1 Rechnung, 720.00 €",
		},
	],
	phaseCounts: { 1: 1, 3: 4, 4: 1 },
};

export const MOCK_OPEN_INVOICES = {
	invoiceDoctype: "Sales Invoice",
	targetAmount: 720.0,
	invoices: [
		{ name: "SINV-2026-0041", outstanding_amount: 720.0, posting_date: "2026-04-01", remarks: "Miete April Whg 3", grand_total: 720.0 },
		{ name: "SINV-2026-0038", outstanding_amount: 360.0, posting_date: "2026-03-15", remarks: "Nebenkosten Q1", grand_total: 360.0 },
		{ name: "SINV-2026-0029", outstanding_amount: 360.0, posting_date: "2026-02-28", remarks: "Restbetrag", grand_total: 360.0 },
	],
};

export const MOCK_PARTIES = [
	{ value: "Max Mustermann", label: "Max Mustermann" },
	{ value: "Erika Beispiel", label: "Erika Beispiel" },
	{ value: "Stadtwerke Beispielstadt", label: "Stadtwerke Beispielstadt" },
];

export const MOCK_ACCOUNTS = [
	{ value: "4970 Bankgebühren - HV", description: "nicht umlegbar – Bankgebühren" },
	{ value: "4360 Versicherungen - HV", description: "umlegbar – Versicherung" },
];

export const MOCK_IMPORTS = [
	{ name: "BAI-1812-DEMO-0001", title: MOCK_OVERVIEW.import.title, status: MOCK_OVERVIEW.import.status, offene_buchungen: 2, total_rows: 6, modified: "2026-05-01" },
	{ name: "BAI-1804-DEMO-0007", title: "Sparkasse (1804) · 03.2026 · 14 Buchungen", status: "Abgeschlossen: 14 Zeilen verbucht", offene_buchungen: 0, total_rows: 14, modified: "2026-04-02" },
];

export const MOCK_BANKIMPORT_RULES = {
	groups: {
		party: {
			doctype: "Bankimport Party Regel",
			label: "Party Matching",
			counts: { total: 2, enabled: 2, disabled: 0 },
			items: [
				{
					doctype: "Bankimport Party Regel",
					name: "party.unique_iban_to_party",
					ruleKey: "party.unique_iban_to_party",
					enabled: true,
					priority: 10,
					hasRuleCode: true,
					ruleCodeLines: 12,
					stopOnMatch: true,
					requiresReview: false,
					description: "Eindeutige IBAN aus Bank Account auf Party abbilden.",
					scopeCount: 1,
					scope: [{ mode: "Sperren", scopeType: "IBAN", iban: "DE99887766554433221100" }],
				},
				{
					doctype: "Bankimport Party Regel",
					name: "party.row_party",
					ruleKey: "party.row_party",
					enabled: true,
					priority: 100,
					hasRuleCode: true,
					ruleCodeLines: 11,
					stopOnMatch: true,
					requiresReview: false,
					description: "Bereits gesetzte Partei der Bankimport-Zeile uebernehmen.",
					scopeCount: 0,
					scope: [],
				},
			],
		},
		booking: {
			doctype: "Bankimport Buchungsregel",
			label: "Buchungs-Matching",
			counts: { total: 4, enabled: 4, disabled: 0 },
			items: [
				{
					doctype: "Bankimport Buchungsregel",
					name: "booking.invoice_auto_match",
					ruleKey: "booking.invoice_auto_match",
					enabled: true,
					priority: 100,
					hasRuleCode: true,
					ruleCodeLines: 1,
					autoApply: true,
					stopOnMatch: true,
					requiresReview: false,
					description: "Offene Sales/Purchase Invoice konservativ automatisch zuordnen.",
					scopeCount: 0,
					scope: [],
				},
				{
					doctype: "Bankimport Buchungsregel",
					name: "booking.kreditrate_auto_match",
					ruleKey: "booking.kreditrate_auto_match",
					enabled: true,
					priority: 200,
					hasRuleCode: true,
					ruleCodeLines: 1,
					autoApply: true,
					stopOnMatch: true,
					requiresReview: false,
					description: "Ausgang eindeutig gegen Kreditrate buchen.",
					scopeCount: 0,
					scope: [],
				},
			],
		},
	},
};
