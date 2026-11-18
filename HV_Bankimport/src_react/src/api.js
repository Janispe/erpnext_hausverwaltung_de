// High-level Daten-API für die Bankimport-UI. Eingebettet (im Frappe-iframe)
// gehen die Aufrufe über die postMessage-Bridge an echte Backend-Methoden;
// standalone (npm run dev) fallen sie auf die Mock-Daten aus data.js zurück.
//
// Die kurzen Aktions-Namen ("overview", "reconcile", …) sind in der Host-Page
// (bankimport_v2.js) auf voll qualifizierte, whitelisted Server-Methoden gemappt
// — fast alle direkt auf die bestehende bankauszug_import.py-API.

import { rpc, isEmbedded, getImportFromUrl, getRowFromUrl } from "./bridge.js";
import {
	MOCK_OVERVIEW,
	KI_MOCK_IMPORT,
	createKiMockOverview,
	MOCK_OPEN_INVOICES,
	MOCK_PARTIES,
	MOCK_ACCOUNTS,
	MOCK_IMPORTS,
	MOCK_BANKIMPORT_RULES,
} from "./data.js";

export const embedded = isEmbedded();
export const importName = getImportFromUrl();
export const linkedRow = getRowFromUrl();

export function docHref(doctype, docname) {
	const slug = String(doctype || "").trim().toLowerCase().replace(/\s+/g, "-");
	return `/app/${encodeURIComponent(slug)}/${encodeURIComponent(docname || "")}`;
}

export function isMissingRowError(errorOrMessage) {
	const msg = String(errorOrMessage?.message || errorOrMessage || "");
	return /Zeile\s+\S+\s+wurde im Dokument\s+\S+\s+nicht gefunden/i.test(msg);
}

// ---- Übersicht / Import-Auswahl ------------------------------------------

// Liste verfügbarer Importe (für den Picker, wenn ?import= fehlt).
export async function listImports() {
	if (!embedded) return { items: MOCK_IMPORTS, mock: true };
	return await rpc("list_imports", {});
}

export async function listBankAccounts(txt = "") {
	if (!embedded) {
		return {
			items: [
				{ value: "Demo Bankkonto - Postbank", label: "Demo Bankkonto (1812)", description: "DE00 0000 0000 0000 0000 00" },
			],
			mock: true,
		};
	}
	return await rpc("list_bank_accounts", { txt });
}

export async function suggestBankAccount({ filename, fileData }) {
	if (!embedded) {
		return {
			status: "matched",
			bank_account: "Demo Bankkonto - Postbank",
			detected_iban: "DE00000000000000000000",
			match_basis: "iban",
			message: "Bankkonto anhand der CSV eindeutig erkannt.",
			mock: true,
		};
	}
	return await rpc("suggest_bank_account", { filename, file_data: fileData });
}

export async function createImport({ bankAccount, filename, fileData }) {
	if (!embedded) return { name: "BAI-DEMO-0001", title: "Demo Bankimport", mock: true };
	return await rpc("create_import", {
		bank_account: bankAccount,
		filename,
		file_data: fileData,
	});
}

export async function deleteImport(name) {
	if (!embedded) return { ok: true, name, mock: true };
	return await rpc("delete_import", { import_name: name, cascade: 1 });
}

export async function getDeleteImpact(name) {
	if (!embedded) {
		return {
			import: name,
			rows: MOCK_OVERVIEW.rows.length,
			vouchers: [],
			bankTransactionsToReverse: [],
			bankTransactionsKept: [],
			counts: { vouchers: 0, paymentEntries: 0, journalEntries: 0, bankTransactionsToReverse: 0, bankTransactionsKept: 0 },
			requiresCascade: false,
			mock: true,
		};
	}
	return await rpc("get_delete_impact", { import_name: name });
}

// ---- Regelkonfiguration ---------------------------------------------------

export async function listBankimportRules() {
	if (!embedded) return { ...MOCK_BANKIMPORT_RULES, mock: true };
	return await rpc("list_bankimport_rules", {});
}

export async function setBankimportRuleEnabled(doctype, name, enabled) {
	if (!embedded) return { ok: true, doctype, name, enabled: enabled ? 1 : 0, mock: true };
	return await rpc("set_bankimport_rule_enabled", { doctype, name, enabled: enabled ? 1 : 0 });
}

export async function saveBankimportRule(doctype, values) {
	if (!embedded) return { ok: true, rule: { ...values, doctype, name: values.name || values.ruleKey }, mock: true };
	return await rpc("save_bankimport_rule", { doctype, values });
}

export async function deleteBankimportRule(doctype, name) {
	if (!embedded) return { ok: true, doctype, name, mock: true };
	return await rpc("delete_bankimport_rule", { doctype, name });
}

export async function reorderBankimportRule(doctype, name, direction) {
	if (!embedded) return { ok: true, changed: true, mock: true };
	return await rpc("reorder_bankimport_rule", { doctype, name, direction });
}

export async function previewBankimportRuleHits(doctype, parametersJson, currentImport = importName, name = "") {
	if (!embedded) return { ok: true, hits: 0, rows: [], mock: true };
	return await rpc("preview_bankimport_rule_hits", {
		doctype,
		parameters_json: parametersJson || {},
		import_name: currentImport || "",
		name: name || "",
	});
}

export async function searchRuleDoctypes(txt = "") {
	if (!embedded) {
		const items = [
			{ value: "Bank Account", label: "Bank Account", description: "ERPNext" },
			{ value: "Customer", label: "Customer", description: "ERPNext" },
			{ value: "Supplier", label: "Supplier", description: "ERPNext" },
		];
		const q = txt.toLowerCase();
		return { items: items.filter((item) => item.label.toLowerCase().includes(q)), mock: true };
	}
	return await rpc("search_rule_doctypes", { txt });
}

export async function getRuleDoctypeFields(doctype) {
	if (!embedded) {
		const common = [
			{ value: "name", label: "Name", fieldtype: "Data" },
			{ value: "party_type", label: "Party Type", fieldtype: "Select" },
			{ value: "party", label: "Party", fieldtype: "Dynamic Link" },
			{ value: "iban", label: "IBAN", fieldtype: "Data" },
			{ value: "disabled", label: "Disabled", fieldtype: "Check" },
		];
		return { doctype, items: common, mock: true };
	}
	return await rpc("get_rule_doctype_fields", { doctype });
}

// Komplett-Übersicht: { import, rows, phaseCounts }.
export async function loadOverview(name) {
	if (!embedded) return name === KI_MOCK_IMPORT ? kiMockOverview() : { ...MOCK_OVERVIEW, mock: true };
	return await rpc("overview", { import_name: name });
}

// ---- Globale Aktionen (doc-level) ----------------------------------------

export async function parseCsv(name) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("parse_csv", { docname: name });
}

export async function refreshSaldo(name) {
	if (!embedded) return { saldo_differenz: MOCK_OVERVIEW.import.saldoDifferenz, mock: true };
	return await rpc("refresh_saldo", { docname: name });
}

export async function createBankTransactionForRow(name, rowName, allowMissingParty = false) {
	if (!embedded) return { created: ["BT-DEMO"], errors: [], mock: true };
	return await rpc("create_bank_transaction_for_row", {
		docname: name,
		row_name: rowName,
		allow_missing_party: allowMissingParty ? 1 : 0,
	});
}

export async function confirmDistinctPayment(name, rowName, bankTransaction) {
	if (!embedded) return { ok: true, bank_transaction: "BT-DEMO-DISTINCT", mock: true };
	return await rpc("confirm_distinct_payment", {
		docname: name, row_name: rowName, existing_bank_transaction: bankTransaction,
	});
}

export async function retryAutoMatch(name, rowName = "") {
	if (!embedded) return { processed: 0, matched: [], unmatched: [], errors: [], mock: true };
	return await rpc("retry_auto_match", { docname: name, row_name: rowName || "" });
}

export async function relinkAllParties(name, overwrite = true) {
	if (!embedded) return { processed: 0, updated: 0, mock: true };
	return await rpc("relink_all_parties", { docname: name, overwrite: overwrite ? 1 : 0 });
}

export async function resetRowBooking(name, rowName) {
	if (!embedded) return { ok: true, reset: false, mock: true };
	return await rpc("reset_row_booking", { docname: name, row_name: rowName });
}

export async function resetRowProcessing(name, rowName) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("reset_row_processing", { docname: name, row_name: rowName });
}

// ---- Phase 1: Party zuordnen ---------------------------------------------

// Such-Endpoint für Customer/Supplier (Phase-1-Zuordnung).
export async function searchParties(partyType, txt) {
	if (!embedded) {
		const q = (txt || "").toLowerCase();
		return { items: MOCK_PARTIES.filter((p) => p.label.toLowerCase().includes(q)) };
	}
	return await rpc("search_parties", { party_type: partyType, txt: txt || "" });
}

// Bestehende Party einer Zeile zuordnen (+ Relink aller passenden Zeilen).
export async function assignParty(name, rowName, partyType, party, iban) {
	if (!embedded) {
		if (name === KI_MOCK_IMPORT) {
			kiMockOverview();
			const row = kiMock.rows.find((item) => item.id === rowName);
			if (!row) throw new Error("Importzeile nicht gefunden.");
			Object.assign(row, { party, partyTyp: partyType, phase: 3, rowStatus: "phase3-open",
				bankTransaction: row.bankTransaction || `BT-2026-MOCK-${row.id}` });
			if (["Pending", "Approved"].includes(row.ki.status)) {
				row.ki.status = "Stale";
				row.ki.steps.find((step) => step.status !== "Succeeded").status = "Stale";
				row.ki.staleText = "Die Partei wurde seit dem Vorschlag manuell zugeordnet.";
			}
		}
		return { row_party_type: partyType, row_party: party, mock: true };
	}
	return await rpc("assign_party", {
		docname: name, row_name: rowName, party_type: partyType, party, iban: iban || "",
	});
}

// Neue Party (+ Bank Account) aus der Zeile anlegen und zuordnen.
export async function createParty(name, rowName, partyType, partyName) {
	if (!embedded) return { party: partyName, party_created: true, mock: true };
	return await rpc("create_party", {
		docname: name, row_name: rowName, party_type: partyType, party_name: partyName || "",
	});
}

export async function changeRowParty(name, rowName, {
	partyType,
	party,
	clearParty = false,
	updateIbanMapping = false,
	propagateSameIban = false,
	createIfMissing = false,
} = {}) {
	if (!embedded) {
		return {
			ok: true,
			row_party_type: clearParty ? null : partyType,
			row_party: clearParty ? null : party,
			mock: true,
		};
	}
	return await rpc("change_row_party", {
		docname: name,
		row_name: rowName,
		party_type: partyType || "",
		party: party || "",
		clear_party: clearParty ? 1 : 0,
		update_iban_mapping: updateIbanMapping ? 1 : 0,
		propagate_same_iban: propagateSameIban ? 1 : 0,
		create_if_missing: createIfMissing ? 1 : 0,
	});
}

// ---- Phase 3: Beleg zuordnen / buchen -------------------------------------

export async function getOpenInvoices(name, rowName) {
	if (!embedded) {
		if (name === KI_MOCK_IMPORT && rowName === "r7") return {
			invoiceDoctype: "Purchase Invoice", targetAmount: 356, invoices: [
				{ name: "ACC-PINV-2026-0094", outstanding_amount: 356, posting_date: "2026-04-16", remarks: "Rechnung RE 2026-118 · Treppenhaus" },
				{ name: "ACC-PINV-2026-0081", outstanding_amount: 1120, posting_date: "2026-04-05", remarks: "Rechnung RE 2026-097" },
			],
		};
		if (name === KI_MOCK_IMPORT && rowName === "r2") return {
			invoiceDoctype: "Sales Invoice", targetAmount: 540,
			invoices: kiMock?.rows.find((row) => row.id === rowName)?.party === "Erika Beispiel"
				? [{ name: "SINV-2026-0052", outstanding_amount: 540, posting_date: "2026-04-02" }]
				: [],
		};
		return { ...MOCK_OPEN_INVOICES, mock: true };
	}
	const r = await rpc("open_invoices", { docname: name, row_name: rowName });
	return {
		invoiceDoctype: r.invoice_doctype,
		invoices: r.invoices || [],
		targetAmount: r.target_amount,
		allocationMode: r.allocation_mode || "invoice_payment",
	};
}

// invoices: [{ name, allocated_amount }]
export async function reconcileInvoices(name, rowName, invoices, leftoverAsAdvance = false, confirmedAfterContractEndInvoices = []) {
	if (!embedded) return { ok: true, payment_entry: "PE-DEMO", mock: true };
	return await rpc("reconcile", {
		docname: name,
		row_name: rowName,
		invoice_names: JSON.stringify(invoices),
		confirmed_after_contract_end_invoices: JSON.stringify(confirmedAfterContractEndInvoices),
		leftover_as_advance: leftoverAsAdvance ? 1 : 0,
	});
}

export async function getSplitOptions(name, rowName) {
	if (!embedded) return { invoiceDoctype: "Purchase Invoice", invoices: [], abschlaege: [], targetAmount: 0, mock: true };
	const r = await rpc("split_options", { docname: name, row_name: rowName });
	return {
		invoiceDoctype: r.invoice_doctype,
		invoices: r.invoices || [],
		abschlaege: r.abschlaege || [],
		targetAmount: r.target_amount,
	};
}

export async function getCustomerSplitInvoices(name, rowName, customer) {
	if (!embedded) {
		return {
			customer, contract: `MV-${customer}`, wohnung: "Demo-Wohnung",
			invoices: [
				{ name: `BK-${customer}`, outstanding_amount: 1000, posting_date: "2026-01-01", remarks: "BK-Nachzahlung" },
				{ name: `GUTHABEN-${customer}`, outstanding_amount: -500, posting_date: "2026-01-01", remarks: "BK-Guthaben" },
			],
		};
	}
	return rpc("customer_split_invoices", { docname: name, row_name: rowName, customer });
}

export async function reconcileCustomerSplit(name, rowName, allocations, advanceCustomer = null, confirmedAfterContractEndInvoices = []) {
	if (!embedded) return { ok: true, mock: true };
	return rpc("reconcile_customer_split", {
		docname: name, row_name: rowName, allocations: JSON.stringify(allocations), advance_customer: advanceCustomer,
		confirmed_after_contract_end_invoices: JSON.stringify(confirmedAfterContractEndInvoices),
	});
}

export async function reconcileSplit(name, rowName, { invoices, abschlaege, leftoverAsAdvance } = {}) {
	if (!embedded) return { ok: true, payment_entry: "PE-DEMO", mock: true };
	return await rpc("reconcile_split", {
		docname: name,
		row_name: rowName,
		invoice_allocations: JSON.stringify(invoices || []),
		abschlag_rows: JSON.stringify(abschlaege || []),
		leftover_as_advance: leftoverAsAdvance ? 1 : 0,
	});
}

export async function createStandalonePayment(name, rowName, remarks) {
	if (!embedded) return { ok: true, payment_entry: "PE-DEMO", mock: true };
	return await rpc("standalone_payment", {
		docname: name, row_name: rowName, remarks: remarks || "",
	});
}

export async function createInternalTransfer(name, rowName, otherBankAccount, remarks) {
	if (!embedded) return { ok: true, payment_entry: "PE-DEMO-TRANSFER", mock: true };
	return await rpc("internal_transfer", {
		docname: name,
		row_name: rowName,
		other_bank_account: otherBankAccount,
		remarks: remarks || "",
	});
}

export async function getExpectedCostCenter(name, rowName) {
	if (!embedded) return { cost_center: null, mock: true };
	return await rpc("expected_cost_center", { docname: name, row_name: rowName });
}

export async function searchAccounts(txt, docname) {
	if (!embedded) {
		const q = (txt || "").toLowerCase();
		return { items: MOCK_ACCOUNTS.filter((a) => a.value.toLowerCase().includes(q)) };
	}
	return await rpc("search_accounts", { txt: txt || "", docname: docname || "" });
}

// splits: optional [{ account, cost_center?, amount }]
export async function createJournalEntry(name, rowName, { account, costCenter, remarks, splits, wertstellungsdatum } = {}) {
	if (!embedded) return { ok: true, journal_entry: "JE-DEMO", mock: true };
	const params = { docname: name, row_name: rowName };
	if (account) params.account = account;
	if (costCenter) params.cost_center = costCenter;
	if (remarks) params.remarks = remarks;
	if (wertstellungsdatum) params.wertstellungsdatum = wertstellungsdatum;
	if (splits && splits.length) params.splits = JSON.stringify(splits);
	return await rpc("journal_entry", params);
}

// ---- Phase 3: Abschlagsplan (Supplier-Ausgang) ----------------------------

export async function getAbschlagsplanCandidates(name, rowName) {
	if (!embedded) return { candidates: name === KI_MOCK_IMPORT && rowName === "r3" ? [
		{ row_name: "ZP-0007-APRIL", zahlungsplan: "ZP-0007", faelligkeitsdatum: "2026-04-01", betrag: 89.9 },
	] : [], mock: true };
	return await rpc("abschlag_candidates", { docname: name, row_name: rowName });
}

export async function assignAbschlagsplan(name, rowName, planRowName, remarks) {
	if (!embedded) return { ok: true, payment_entry: "PE-DEMO", mock: true };
	return await rpc("assign_abschlag", {
		docname: name, row_name: rowName, plan_row_name: planRowName, remarks: remarks || "",
	});
}

// ---- Phase 3: Kreditrate (Ausgang) ----------------------------------------

export async function getOpenKreditraten(name, rowName) {
	if (!embedded) return { candidates: name === KI_MOCK_IMPORT && rowName === "r5" ? [
		{ row_name: "4711-APRIL", kreditvertrag: "Darlehen 4711", faelligkeitsdatum: "2026-04-10", betrag: 1240 },
	] : [], can_create_from_statement: false, mock: true };
	return await rpc("kreditraten", { docname: name, row_name: rowName });
}

export function getKreditrateRowName(candidate = {}) {
	return candidate.row_name || candidate.rate_name || candidate.name || "";
}

export async function assignKreditrate(name, rowName, kreditvertrag, rateName) {
	if (!rateName) throw new Error("Die ausgewählte Kreditrate hat keine Planzeilen-ID.");
	if (!embedded) return { ok: true, journal_entry: "JE-DEMO", mock: true };
	return await rpc("assign_kreditrate", {
		docname: name, row_name: rowName, kreditvertrag, rate_name: rateName,
	});
}

export async function bookKreditrateFromStatement(name, rowName) {
	if (!embedded) return { ok: false, message: "Standalone-Demo", mock: true };
	return await rpc("book_kreditrate_statement", { docname: name, row_name: rowName });
}

// ---- Navigation (öffnet Desk-Formulare in der Eltern-Page) ----------------

// Ein Desk-Dokument im Eltern-Desk öffnen (Bank Transaction, Payment Entry, …).
export async function openDoc(doctype, docname) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("open_doc", { doctype, docname });
}

export async function openList(doctype) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("open_list", { doctype });
}

export async function newDoc(doctype) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("new_doc", { doctype });
}

// Den Bankauszug-Import als klassisches Formular öffnen.
export async function openImportForm(name) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("open_import_form", { docname: name });
}

// Neuen Bankauszug Import anlegen (Desk-Formular).
export async function newImport() {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("new_import", {});
}

let kiMock;
const approver = "M. Krüger";
const mockVouchers = {
	r1: "PE-2026-0058", r2: "PE-2026-0059", r3: "PE-2026-0060",
	r4: "JV-2026-0044", r5: "JV-2026-0045", r6: "PE-2026-0061",
};

function kiMockOverview() {
	kiMock ??= createKiMockOverview(new URLSearchParams(window.location.search).get("ki"));
	const counts = { Pending: 0, Approved: 0, Stale: 0, Succeeded: 0, Rejected: 0, none: 0 };
	const confidence = { hoch: 0, mittel: 0, niedrig: 0 };
	const phaseCounts = { 1: 0, 3: 0, 4: 0 };
	for (const row of kiMock.rows) {
		phaseCounts[row.phase]++;
		const ki = row.ki;
		if (ki.state === "none") counts.none++;
		if (ki.state !== "proposal") continue;
		counts[ki.status]++;
		if (["Pending", "Approved"].includes(ki.status)) confidence[ki.confidence.level]++;
	}
	kiMock.import.offeneBuchungen = phaseCounts[1] + phaseCounts[3];
	Object.assign(kiMock.import.ki, { counts, confidence });
	return structuredClone({ ...kiMock, phaseCounts });
}

function mockKiRow(importName, rowId, requireReviewer = true) {
	const overview = kiMockOverview();
	const row = kiMock.rows.find((item) => item.id === rowId);
	if (importName !== KI_MOCK_IMPORT || !row || (requireReviewer && !overview.import.ki.canAccept)) {
		throw new Error("Der Vorschlag ist für diese Aktion nicht verfügbar.");
	}
	return row;
}

function sameBinding(step, binding) {
	return step.proposal === binding?.id && step.revision === binding.revision && step.hash === binding.hash;
}

function mockAccept(importName, rowId, bindings) {
	const row = mockKiRow(importName, rowId);
	const { ki } = row;
	if (ki.status === "Stale" || (rowId === "r6" && new URLSearchParams(window.location.search).get("ki") === "stale" && ki.status === "Pending")) {
		ki.status = "Stale";
		ki.steps[0].status = "Stale";
		ki.staleText ||= "Die Ausgangsdaten der Zeile haben sich seit dem Vorschlag geändert.";
		return { ok: false, status: "Stale", results: [{ id: bindings[0]?.id, ok: false, status: "Stale" }] };
	}
	const steps = ki.steps?.filter((step) => step.status !== "Succeeded") || [];
	if (!["Pending", "Approved"].includes(ki.status) || steps.length !== bindings.length ||
		!steps.every((step, index) => sameBinding(step, bindings[index]))) {
		throw Object.assign(new Error("Die Vorschlagsbindung hat sich geändert."), { status: 409 });
	}
	const results = [];
	const decision = { by: approver, at: new Date().toISOString() };
	for (const step of steps) {
		if (step.kind === "party") {
			Object.assign(row, { party: step.prefill.party, partyTyp: step.prefill.partyType,
				phase: 3, rowStatus: "phase3-open", bankTransaction: "BT-2026-0102" });
			step.status = "Succeeded";
			results.push({ id: step.proposal, ok: true, status: "Succeeded" });
			continue;
		}
		if (rowId === "r2" && step.status === "Pending") {
			step.status = ki.status = "Approved";
			ki.decision = decision;
			results.push({ id: step.proposal, ok: false, status: "Approved", error: "Die Buchung konnte vorübergehend nicht erstellt werden." });
			return { ok: false, status: "Approved", results };
		}
		const journal = ["journal", "kredit"].includes(step.kind);
		const result = { ...decision, doctype: journal ? "Journal Entry" : "Payment Entry",
			name: mockVouchers[rowId] };
		row[journal ? "journalEntry" : "paymentEntry"] = result.name;
		row.phase = 4;
		row.rowStatus = "done";
		step.status = "Succeeded";
		ki.result = result;
		results.push({ id: step.proposal, ok: true, status: "Succeeded", result });
	}
	ki.status = "Succeeded";
	return { ok: true, status: ki.status, results };
}

export async function kiAccept(import_name, row, bindings) {
	return embedded ? rpc("ki_accept", { import_name, row, bindings }) : mockAccept(import_name, row, bindings);
}

export async function kiAcceptMany(import_name, items) {
	if (items.reduce((total, item) => total + item.bindings.length, 0) > 128) {
		throw new Error("Pro Lauf sind höchstens 128 Vorschlagsbindungen erlaubt.");
	}
	if (embedded) return rpc("ki_accept_many", { import_name, items });
	const results = [];
	let stopped = false;
	for (const item of [...items].sort((a, b) => {
		const date = (id) => kiMock?.rows.find((row) => row.id === id)?.buchungstag || "";
		return date(a.row).localeCompare(date(b.row));
	})) {
		if (stopped) {
			results.push({ row: item.row, ok: false, status: "Skipped", skipped_reason: "Lauf nach einem Fehler gestoppt." });
			continue;
		}
		try {
			const { ok, status, results: steps } = mockAccept(import_name, item.row, item.bindings);
			results.push({ row: item.row, ok, status, result: steps.at(-1)?.result,
				error: steps.at(-1)?.error || (status === "Stale" ? "Vorschlag ist veraltet." : undefined) });
			stopped = !ok;
		} catch (error) {
			results.push({ row: item.row, ok: false, status: "Error", error: error.message });
			stopped = true;
		}
	}
	return { results };
}

export async function kiReject(import_name, row, binding, category, reason) {
	if (embedded) return rpc("ki_reject", { import_name, row, binding, category, reason });
	const { ki } = mockKiRow(import_name, row);
	const step = ki.steps?.find((item) => item.status === "Pending");
	if (ki.status !== "Pending" || !step || !sameBinding(step, binding) || !reason?.trim() || reason.length > 1000) {
		throw new Error("Ablehnung konnte nicht gespeichert werden.");
	}
	ki.status = "Rejected";
	step.status = "Rejected";
	ki.decision = { by: approver, at: new Date().toISOString(), reason, category };
	return { ok: true, status: "Rejected" };
}

export async function kiRequestRevision(import_name, row, binding, note = "") {
	if (embedded) return rpc("ki_request_revision", { import_name, row, ...(binding && { binding }), note });
	const entry = mockKiRow(import_name, row, binding != null);
	const valid = binding == null ? entry.ki.state === "none"
		: entry.ki.status === "Stale" && sameBinding(entry.ki.steps[0], binding);
	if (!valid) {
		throw new Error("Keine Revision für diese Bindung verfügbar.");
	}
	entry.ki = { state: "running" };
	kiMock.import.ki.running = true;
	kiMock.import.ki.progress = { done: kiMock.rows.filter((item) => item.ki.state !== "running").length, total: kiMock.rows.length };
	return { ok: true, state: "running" };
}

export async function openProposals(packageName, proposal) {
	if (!embedded) return { ok: true, mock: true };
	return rpc("open_proposals", { package: packageName, proposal });
}
