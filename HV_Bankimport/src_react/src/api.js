// High-level Daten-API für die Bankimport-UI. Eingebettet (im Frappe-iframe)
// gehen die Aufrufe über die postMessage-Bridge an echte Backend-Methoden;
// standalone (npm run dev) fallen sie auf die Mock-Daten aus data.js zurück.
//
// Die kurzen Aktions-Namen ("overview", "reconcile", …) sind in der Host-Page
// (bankimport_v2.js) auf voll qualifizierte, whitelisted Server-Methoden gemappt
// — fast alle direkt auf die bestehende bankauszug_import.py-API.

import { rpc, isEmbedded, getImportFromUrl } from "./bridge.js";
import {
	MOCK_OVERVIEW,
	MOCK_OPEN_INVOICES,
	MOCK_PARTIES,
	MOCK_ACCOUNTS,
	MOCK_IMPORTS,
	MOCK_BANKIMPORT_RULES,
} from "./data.js";

export const embedded = isEmbedded();
export const importName = getImportFromUrl();

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

// Komplett-Übersicht: { import, rows, phaseCounts }.
export async function loadOverview(name) {
	if (!embedded) return { ...MOCK_OVERVIEW, mock: true };
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

export async function createBankTransactions(name, allowMissingParty = false) {
	if (!embedded) return { created: [], errors: [], mock: true };
	return await rpc("create_bank_transactions", {
		docname: name,
		allow_missing_party: allowMissingParty ? 1 : 0,
	});
}

export async function createBankTransactionForRow(name, rowName, allowMissingParty = false) {
	if (!embedded) return { created: ["BT-DEMO"], errors: [], mock: true };
	return await rpc("create_bank_transaction_for_row", {
		docname: name,
		row_name: rowName,
		allow_missing_party: allowMissingParty ? 1 : 0,
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
	if (!embedded) return { row_party_type: partyType, row_party: party, mock: true };
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
	if (!embedded) return { ...MOCK_OPEN_INVOICES, mock: true };
	const r = await rpc("open_invoices", { docname: name, row_name: rowName });
	return {
		invoiceDoctype: r.invoice_doctype,
		invoices: r.invoices || [],
		targetAmount: r.target_amount,
	};
}

// invoices: [{ name, allocated_amount }]
export async function reconcileInvoices(name, rowName, invoices, leftoverAsAdvance = false) {
	if (!embedded) return { ok: true, payment_entry: "PE-DEMO", mock: true };
	return await rpc("reconcile", {
		docname: name,
		row_name: rowName,
		invoice_names: JSON.stringify(invoices),
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

export async function getExpectedCostCenter(name, rowName) {
	if (!embedded) return { cost_center: null, mock: true };
	return await rpc("expected_cost_center", { docname: name, row_name: rowName });
}

export async function searchAccounts(txt) {
	if (!embedded) {
		const q = (txt || "").toLowerCase();
		return { items: MOCK_ACCOUNTS.filter((a) => a.value.toLowerCase().includes(q)) };
	}
	return await rpc("search_accounts", { txt: txt || "" });
}

// splits: optional [{ account, cost_center?, amount }]
export async function createJournalEntry(name, rowName, { account, costCenter, remarks, splits } = {}) {
	if (!embedded) return { ok: true, journal_entry: "JE-DEMO", mock: true };
	const params = { docname: name, row_name: rowName };
	if (account) params.account = account;
	if (costCenter) params.cost_center = costCenter;
	if (remarks) params.remarks = remarks;
	if (splits && splits.length) params.splits = JSON.stringify(splits);
	return await rpc("journal_entry", params);
}

// ---- Phase 3: Abschlagsplan (Supplier-Ausgang) ----------------------------

export async function getAbschlagsplanCandidates(name, rowName) {
	if (!embedded) return { candidates: [], mock: true };
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
	if (!embedded) return { candidates: [], can_create_from_statement: false, mock: true };
	return await rpc("kreditraten", { docname: name, row_name: rowName });
}

export async function assignKreditrate(name, rowName, kreditvertrag, rateName) {
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
