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

export const KI_MOCK_IMPORT = "BAI-KI-DEMO-0001";
const mockTime = "2026-04-30 09:12:00";
const mockDecision = { by: "M. Krüger", at: mockTime, reason: "Der Beleg gehört zu einer anderen Zahlung.", category: "wrong_document" };
const bank = "1812 - Bank Wilhelmshavener - HV";

const source = (doctype, name) => ({ label: name, doctype, name });

function proposal(id, kind, kindLabel, target, amount, level, score, detail) {
	const { doctype, name = target, sub, prefill, account, label = account, effect, rationale,
		title = kindLabel, summary = target, revision = 1, sources, postings } = detail;
	const total = Math.abs(amount);
	return {
		state: "proposal", status: "Pending", kind, kindLabel, summary,
		confidence: { level, score },
		steps: [{
			proposal: id, revision, hash: `mock-${id}-${revision}`, status: "Pending",
			kind, title, target, targetRef: doctype ? { doctype, name } : null,
			sub, amount: total, prefill: { mode: kind, ...prefill },
		}],
		postings: postings || [
			{ account: bank, label: "Bank Wilhelmshavener (1812)", debit: amount > 0 ? total : 0, credit: amount < 0 ? total : 0 },
			{ account, label, debit: amount < 0 ? total : 0, credit: amount > 0 ? total : 0 },
		],
		effect, rationale, sources: sources || (doctype ? [source(doctype, name)] : []),
		decision: null, staleText: null, result: null,
	};
}

const aprilInvoice = proposal("HVP-0412", "invoice", "Rechnung zuordnen", "SINV-2026-0041", 720, "hoch", .97, {
	doctype: "Sales Invoice", title: "Rechnung", sub: "Miete April 2026 · offen 720,00 €",
	sources: [source("Sales Invoice", "SINV-2026-0041"), source("Mietvertrag", "MV-0182")],
	prefill: { invoices: [{ name: "SINV-2026-0041", allocated: 720 }] },
	account: "1400 - Forderungen - HV", label: "Forderungen · Max Mustermann", effect: "Zahlung wird angelegt und gebucht. SINV-2026-0041 ist danach ausgeglichen.",
	rationale: "Rechnungsnummer im Verwendungszweck, Betrag exakt, IBAN ist MV-0182 zugeordnet.",
});
const chain = proposal("HVP-0414", "invoice", "Partei und Rechnung · 2 Schritte", "SINV-2026-0052", 540, "mittel", .74, {
	doctype: "Sales Invoice", title: "Rechnung", sub: "Miete April 2026 · offen 540,00 €",
	summary: "Erika Beispiel → SINV-2026-0052",
	sources: [source("Mietvertrag", "MV-0191"), source("Sales Invoice", "SINV-2026-0052")],
	prefill: { invoices: [{ name: "SINV-2026-0052", allocated: 540 }] },
	account: "1400 - Forderungen - HV", label: "Forderungen · Erika Beispiel",
	effect: "Erst Partei zuordnen, dann Zahlung buchen. Schlägt Schritt 1 fehl, wird nichts gebucht.",
	rationale: "Name des Auftraggebers entspricht der Mieterin von MV-0191, diese IBAN ist dort noch nicht hinterlegt. Einzige offene Rechnung über 540,00 €.",
});
chain.steps.unshift({
	proposal: "HVP-0413", revision: 1, hash: "mock-HVP-0413-1", status: "Pending",
	kind: "party", title: "Partei", target: "Erika Beispiel",
	targetRef: { doctype: "Customer", name: "Erika Beispiel" }, sub: "Mieterin · MV-0191 · Bank-Tx wird angelegt",
	amount: null, prefill: { mode: "party", partyType: "Customer", party: "Erika Beispiel" },
});

const staleInvoice = proposal("HVP-0419", "invoice", "Rechnung zuordnen", "ACC-PINV-2026-0090", -356, "mittel", .8, {
	doctype: "Purchase Invoice", account: "1600 - Verbindlichkeiten - HV",
	rationale: "Rechnungsreferenz und Betrag stimmen überein.", effect: "Die Rechnung wird ausgeglichen.",
});
const marchInvoice = proposal("HVP-0401", "invoice", "Rechnung zuordnen", "SINV-2026-0033", 720, "hoch", .98, {
	doctype: "Sales Invoice", account: "1400 - Forderungen - HV",
	rationale: "Rechnungsnummer und Betrag stimmen überein.", effect: "SINV-2026-0033 wurde ausgeglichen.",
});

const kiRows = [
	{ ...MOCK_OVERVIEW.rows[0], buchungstag: "2026-04-01", ki: aprilInvoice },
	{ ...MOCK_OVERVIEW.rows[3], buchungstag: "2026-04-02", ki: chain },
	{ ...MOCK_OVERVIEW.rows[1], buchungstag: "2026-04-03", ki: proposal("HVP-0415", "abschlag", "Abschlag zuordnen", "ZP-0007 · Strom Hauptstr. 5", -89.9, "hoch", .92, {
		doctype: "Zahlungsplan", name: "ZP-0007", title: "Abschlag", summary: "ZP-0007 · April", sub: "Rate April · fällig 01.04.2026",
		prefill: { row_name: "ZP-0007-APRIL" }, account: "Verbindlichkeiten · Stadtwerke",
		effect: "Zahlung wird gegen die April-Rate des Abschlagsplans gebucht.", rationale: "Betrag und Fälligkeit passen zur April-Rate von ZP-0007, Verwendungszweck nennt das Objekt.",
	}) },
	{ ...MOCK_OVERVIEW.rows[2], ki: proposal("HVP-0416", "journal", "Buchungssatz", "Nebenkosten des Geldverkehrs", -12.5, "hoch", .95, {
		doctype: "Account", name: "4970 Bankgebühren - HV", title: "Gegenkonto", sub: "Kostenstelle Hauptstr. 5",
		summary: "Nebenkosten Geldverkehr",
		sources: [source("Journal Entry", "JV-2026-0031"), source("Journal Entry", "JV-2026-0019")],
		prefill: { account: "4970 Bankgebühren - HV", costCenter: "Hauptstr. 5 - HV" }, account: "4970 Bankgebühren - HV", label: "Nebenkosten des Geldverkehrs",
		effect: "Buchungssatz (Journal Entry) wird angelegt und gebucht.", rationale: "Dieselbe Gebühr wurde in den letzten 6 Monaten jedes Mal so gebucht.",
	}) },
	{ buchungstag: "2026-04-10", betrag: -1240, bankTransaction: "BT-2026-0104", iban: "DE02120300000000202051", auftraggeber: "Hausbank Beispiel", verwendungszweck: "Annuität Darlehen 4711 April",
		ki: proposal("HVP-0417", "kredit", "Kreditrate zuordnen", "Darlehen 4711 · Rate April", -1240, "mittel", .81, {
			doctype: "Kreditvertrag", name: "Darlehen 4711", title: "Kreditrate", revision: 2,
			summary: "Darlehen 4711 · April", sub: "Zins 412,30 € · Tilgung 827,70 €",
			postings: [
				{ account: "Zinsaufwand Darlehen", label: "Zinsaufwand Darlehen", debit: 412.3, credit: 0 },
				{ account: "Darlehen 4711", label: "Darlehen 4711", debit: 827.7, credit: 0 },
				{ account: bank, label: "Bank Wilhelmshavener (1812)", debit: 0, credit: 1240 },
			],
			prefill: { kreditvertrag: "Darlehen 4711", rate_name: "4711-APRIL" }, account: "Darlehen 4711",
			effect: "Rate wird nach Tilgungsplan in Zins und Tilgung aufgeteilt.",
			rationale: "Rate entspricht dem Tilgungsplan. Zinsanteil laut Plan 412,70 €, Bank weicht um 0,40 € ab.",
		}) },
	{ ...MOCK_OVERVIEW.rows[4], bankTransaction: "BT-2026-0105", ki: proposal("HVP-0418", "payment", "Vorauszahlung", "Max Mustermann", 720, "niedrig", .48, {
		doctype: "Customer", name: "Max Mustermann", sub: "ohne Rechnung · Mai noch nicht gestellt",
		summary: "Vorauszahlung", account: "Erhaltene Anzahlungen", label: "Erhaltene Anzahlungen · Mustermann",
		sources: [source("Mietvertrag", "MV-0182")],
		effect: "Zahlung ohne Rechnungsbezug, später mit der Mai-Rechnung verrechenbar.", rationale: "Für Mai gibt es noch keine Rechnung. Möglich ist auch eine doppelte April-Zahlung.",
	}) },
	{ buchungstag: "2026-04-18", betrag: -356, bankTransaction: "BT-2026-0106", iban: "DE89370400440532013000", party: "Malerbetrieb Muster", partyTyp: "Supplier", verwendungszweck: "RE 2026-118",
		ki: { ...staleInvoice, status: "Stale", steps: staleInvoice.steps.map((step) => ({ ...step, status: "Stale" })),
			staleText: "Die vorgeschlagene Rechnung ACC-PINV-2026-0090 wurde am 17.04. mit PE-2026-0052 ausgeglichen." } },
	{ buchungstag: "2026-04-22", betrag: 60, bankTransaction: "", verwendungszweck: "Gutschrift", phase: 1, rowStatus: "phase1-no-party",
		ki: { state: "none", note: "Ohne Auftraggeber und eindeutigen Verwendungszweck kann ich die Gutschrift keinem Mietvertrag zuordnen." } },
	{ ...MOCK_OVERVIEW.rows[5], bankTransaction: "BT-2026-0107", ki: { ...marchInvoice, status: "Succeeded",
		steps: marchInvoice.steps.map((step) => ({ ...step, status: "Succeeded" })),
		result: { doctype: "Payment Entry", name: "PE-2026-0050", at: "2026-04-28 09:14:00", by: mockDecision.by } } },
].map((row, index) => ({
	phase: 3, rowStatus: "phase3-open", bankTransaction: `BT-2026-01${String(index + 1).padStart(2, "0")}`,
	...row, id: `r${index + 1}`, richtung: row.betrag < 0 ? "Ausgang" : "Eingang",
}));

export function createKiMockOverview(variant) {
	const data = structuredClone({
		import: {
			...MOCK_OVERVIEW.import, name: KI_MOCK_IMPORT,
			title: "Wilhelmshavener (1812) · 01.04.–30.04.2026 · 9 Buchungen",
			status: "Kontoauszug April 2026",
			ki: { package: "HVP-PKG-0031", agent: "Buchhaltungs-Agent", submittedAt: mockTime,
				running: false, canAccept: variant !== "readonly" },
		},
		rows: kiRows,
	});
	if (variant === "states") {
		for (const [index, status] of [[0, "Approved"], [3, "Rejected"]]) {
			const ki = data.rows[index].ki;
			ki.status = status;
			ki.steps[0].status = status;
			ki.decision = { ...mockDecision };
		}
		const voucher = { doctype: "Payment Entry", name: "PE-2026-0063", summary: "SINV-2026-0047 · Miete Mai 2026 · 720,00 €" };
		const adjusted = structuredClone(data.rows[0]);
		Object.assign(adjusted, {
			id: "r10", buchungstag: "2026-04-29", bankTransaction: "BT-2026-0108",
			verwendungszweck: "Miete Mai", paymentEntry: voucher.name, phase: 4, rowStatus: "done",
		});
		adjusted.ki.status = "Rejected";
		Object.assign(adjusted.ki.steps[0], { status: "Rejected", proposal: "HVP-0421" });
		adjusted.ki.decision = { ...mockDecision, category: "adjusted_booked", reason: `Angepasst gebucht: ${voucher.name}`, voucher };
		data.rows.push(adjusted);
		data.import.title = data.import.title.replace("9 Buchungen", "10 Buchungen");
	}
	if (variant === "running") {
		data.rows[7].ki = { state: "running" };
		data.import.ki.running = true;
		data.import.ki.progress = { done: 8, total: 9 };
	}
	return data;
}
