import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

const FRAPPE_USER = process.env.FRAPPE_USER || "Administrator";
const FRAPPE_PASSWORD = process.env.FRAPPE_PASSWORD || "admin";
const FRAPPE_SITE = process.env.FRAPPE_SITE || "frontend";
const FRAPPE_BACKEND_CONTAINER = process.env.FRAPPE_BACKEND_CONTAINER || "hausverwaltung_peters-backend-1";
const FRAPPE_BENCH_DIR = process.env.FRAPPE_BENCH_DIR || "/home/frappe/frappe-bench";

async function dismissDeskModals(page) {
	for (let i = 0; i < 3; i += 1) {
		const modal = page.locator(".modal.show").first();
		if (!(await modal.isVisible().catch(() => false))) return;
		const closeButton = modal.locator(".btn-close, .close, button").first();
		if (await closeButton.isVisible().catch(() => false)) {
			await closeButton.click();
		} else {
			await page.keyboard.press("Escape");
		}
		await expect(modal).toBeHidden({ timeout: 5000 }).catch(() => {});
	}
}

async function login(page) {
	await page.goto("/desk/bankimport_v2");
	if (!page.url().includes("/login")) {
		await dismissDeskModals(page);
		return;
	}

	await page.getByRole("textbox", { name: "Email" }).fill(FRAPPE_USER);
	await page.getByRole("textbox", { name: "Password" }).fill(FRAPPE_PASSWORD);
	await page.getByRole("button", { name: "Login" }).click();
	await expect(page).toHaveURL(/\/desk\/bankimport_v2/);
	await dismissDeskModals(page);
}

async function bankimportFrame(page) {
	const frame = page.frameLocator("iframe.hv-bankimport-frame");
	await expect(frame.getByRole("heading", { name: "Bankauszug-Import wählen" })).toBeVisible();
	return frame;
}

function csvForRun(runId) {
	return [
		"Buchungstag;Betrag;IBAN;Auftraggeber;Verwendungszweck;Währung",
		`10.06.2026;${runId.amount};DE89370400440532013000;HV UI Test ${runId.id};HV UI Realdaten ${runId.id};EUR`,
		"",
	].join("\n");
}

function overUnderCsvForRun({ runId, label, date, amount, iban }) {
	return [
		"Buchungstag;Betrag;IBAN;Auftraggeber;Verwendungszweck;Währung",
		`${date};${amount};${iban};HV UI OverUnder ${runId.id};HV UI OverUnder ${runId.id} ${label};EUR`,
		"",
	].join("\n");
}

function brokenCsvForRun(runId) {
	return [
		"Datum;Text",
		`10.06.2026;HV UI defekt ${runId.id}`,
		"",
	].join("\n");
}

function mixedCsvForRun(runId) {
	return [
		"Buchungstag;Betrag;IBAN;Auftraggeber;Verwendungszweck;Währung",
		`10.06.2026;${runId.amount};DE89370400440532013000;HV UI Test ${runId.id};HV UI Realdaten ${runId.id} valide;EUR`,
		`11.06.2026;;DE89370400440532013000;HV UI Test ${runId.id};HV UI Realdaten ${runId.id} betrag fehlt;EUR`,
		`12.06.2026;-3,21;DE89370400440532013000;HV UI Test ${runId.id};HV UI Realdaten ${runId.id} ausgang;EUR`,
		"",
	].join("\n");
}

function shellQuote(value) {
	return `'${String(value).replaceAll("'", "'\"'\"'")}'`;
}

function benchExecute(method, { args, kwargs } = {}) {
	const benchCmd = [
		`bench --site ${shellQuote(FRAPPE_SITE)} execute ${method}`,
		args ? `--args ${shellQuote(JSON.stringify(args))}` : "",
		kwargs ? `--kwargs ${shellQuote(JSON.stringify(kwargs))}` : "",
	].filter(Boolean).join(" ");
	const cmd = `cd ${shellQuote(FRAPPE_BENCH_DIR)} && ${benchCmd}`;
	const out = execFileSync("docker", ["exec", FRAPPE_BACKEND_CONTAINER, "sh", "-lc", cmd], {
		encoding: "utf8",
		stdio: ["ignore", "pipe", "pipe"],
	}).trim();
	if (!out) return null;
	try {
		return JSON.parse(out);
	} catch {
		return out;
	}
}

test.beforeAll(() => {
	benchExecute("hausverwaltung.cypress_fixtures.ensure_bankimport_bank_account");
});

function rowsForRun(runId) {
	return benchExecute("frappe.get_all", {
		kwargs: {
			doctype: "Bankauszug Import Row",
			filters: { verwendungszweck: ["like", `HV UI Realdaten ${runId.id}%`] },
			fields: [
				"name",
				"parent",
				"verwendungszweck",
				"betrag",
				"richtung",
				"row_status",
				"error",
				"bank_transaction",
				"payment_entry",
				"journal_entry",
				"auto_match_message",
			],
			order_by: "idx asc",
			limit: 20,
		},
	}) || [];
}

function overUnderRowsForRun(runId, label = "%") {
	return benchExecute("frappe.get_all", {
		kwargs: {
			doctype: "Bankauszug Import Row",
			filters: { verwendungszweck: ["like", `HV UI OverUnder ${runId.id} ${label}`] },
			fields: [
				"name",
				"parent",
				"verwendungszweck",
				"betrag",
				"richtung",
				"party_type",
				"party",
				"row_status",
				"error",
				"bank_transaction",
				"payment_entry",
				"journal_entry",
				"auto_match_message",
			],
			order_by: "idx asc",
			limit: 20,
		},
	}) || [];
}

function importBankAccount(importName) {
	return benchExecute("frappe.db.get_value", {
		args: ["Bankauszug Import", importName, "bank_account"],
	});
}

function glAccountForBankAccount(bankAccount) {
	return benchExecute("frappe.db.get_value", {
		args: ["Bank Account", bankAccount, "account"],
	});
}

function accountBalance(account) {
	return Number(benchExecute("erpnext.accounts.utils.get_balance_on", {
		kwargs: { account, date: "2026-06-10" },
	}) || 0);
}

function docExists(doctype, name) {
	return Boolean(benchExecute("frappe.db.exists", {
		args: [doctype, name],
	}));
}

function docValue(doctype, name, fieldname) {
	return benchExecute("frappe.db.get_value", {
		args: [doctype, name, fieldname],
	});
}

function invoiceOutstanding(invoiceName) {
	return Number(docValue("Sales Invoice", invoiceName, "outstanding_amount") || 0);
}

function paymentEntryUnallocated(paymentEntryName) {
	return Number(docValue("Payment Entry", paymentEntryName, "unallocated_amount") || 0);
}

async function uploadCsvInDialog(frame, { filename, content }) {
	const bankAccount = frame.getByLabel("Bankkonto");
	await expect.poll(async () => bankAccount.locator("option").count()).toBeGreaterThan(1);
	await bankAccount.selectOption({ index: 1 });

	await frame.getByLabel("CSV-Datei").setInputFiles({
		name: filename,
		mimeType: "text/csv",
		buffer: Buffer.from(content, "utf8"),
	});
	await frame.getByRole("button", { name: /Importieren/ }).click();
}

async function createImportFromCsv(frame, { filename, content }) {
	await frame.getByRole("button", { name: "Neuer Import" }).click();
	await expect(frame.getByRole("heading", { name: "Neuer Bankimport" })).toBeVisible();
	await uploadCsvInDialog(frame, { filename, content });
	await expect(frame.getByText("Bankauszug importiert.")).toBeVisible();
}

async function ensureSelectedRowHasBankTransaction(frame) {
	const createButton = frame.getByRole("button", { name: /Diese Zeile erstellen/ });
	if (await createButton.isVisible({ timeout: 1500 }).catch(() => false)) {
		await createButton.click();
	}
	await expect(frame.locator(".sec-label", { hasText: "Beleg zuordnen" })).toBeVisible();
}

async function selectRowByPurpose(frame, text) {
	await frame.locator(".verwendung-cell", { hasText: text }).click();
}

async function createImportThroughUi(frame, runId) {
	await createImportFromCsv(frame, {
		filename: `hv-ui-realdata-${runId.id}.csv`,
		content: csvForRun(runId),
	});
}

async function deleteCurrentImportThroughUi(page, frame) {
	const dialogPromise = page.waitForEvent("dialog");
	await frame.getByRole("button", { name: /Löschen/ }).click();
	const dialog = await dialogPromise;
	expect(dialog.message()).toContain("wirklich löschen");
	await dialog.accept();
	await expect(frame.getByText("Bankimport gelöscht.")).toBeVisible();
	await expect(frame.getByRole("heading", { name: "Bankauszug-Import wählen" })).toBeVisible();
}

test("zeigt CSV-Strukturfehler im UI und legt keine Importzeilen an", async ({ page }) => {
	const runId = { id: `${Date.now()}` };

	await login(page);
	const frame = await bankimportFrame(page);

	await frame.getByRole("button", { name: "Neuer Import" }).click();
	await expect(frame.getByRole("heading", { name: "Neuer Bankimport" })).toBeVisible();
	await uploadCsvInDialog(frame, {
		filename: `hv-ui-broken-${runId.id}.csv`,
		content: brokenCsvForRun(runId),
	});

	await expect(
		frame.getByText(/CSV muss mindestens eine Betrags-Spalte/)
			.or(page.getByText(/CSV muss mindestens eine Betrags-Spalte/))
	).toBeVisible();
	expect(rowsForRun(runId)).toHaveLength(0);
});

test("Löschdialog-Abbruch lässt echten Import und Rows unverändert", async ({ page }) => {
	const runId = {
		id: `${Date.now()}`,
		amount: `2${String(Date.now()).slice(-2)},19`,
	};

	await login(page);
	const frame = await bankimportFrame(page);
	let created = false;
	let deleted = false;

	try {
		await createImportThroughUi(frame, runId);
		created = true;

		const rowsBefore = rowsForRun(runId);
		expect(rowsBefore).toHaveLength(1);
		await expect(frame.locator(".verwendung-cell", { hasText: `HV UI Realdaten ${runId.id}` })).toBeVisible();

		const dialogPromise = page.waitForEvent("dialog");
		await frame.getByRole("button", { name: /Löschen/ }).click();
		const dialog = await dialogPromise;
		expect(dialog.message()).toContain("wirklich löschen");
		await dialog.dismiss();

		await expect(frame.locator(".verwendung-cell", { hasText: `HV UI Realdaten ${runId.id}` })).toBeVisible();
		const rowsAfterDismiss = rowsForRun(runId);
		expect(rowsAfterDismiss).toHaveLength(1);
		expect(rowsAfterDismiss[0].parent).toBe(rowsBefore[0].parent);

		await deleteCurrentImportThroughUi(page, frame);
		deleted = true;
		expect(rowsForRun(runId)).toHaveLength(0);
	} finally {
		if (created && !deleted) {
			await deleteCurrentImportThroughUi(page, frame).catch(() => {});
		}
	}
});

test("erstellt echten CSV-Import, erzeugt echte Bank Transaction und löscht per UI-Cascade", async ({ page }) => {
	const runId = {
		id: `${Date.now()}`,
		amount: `1${String(Date.now()).slice(-2)},37`,
	};

	await login(page);
	const frame = await bankimportFrame(page);
	let created = false;
	let deleted = false;

	try {
		await createImportThroughUi(frame, runId);
		created = true;
		await expect(frame.locator(".verwendung-cell", { hasText: `HV UI Realdaten ${runId.id}` })).toBeVisible();
		await expect(frame.locator(".tx-table").getByText("Partei fehlt").first()).toBeVisible();

		const rowsAfterImport = rowsForRun(runId);
		expect(rowsAfterImport).toHaveLength(1);
		const importName = rowsAfterImport[0].parent;
		const bankAccount = importBankAccount(importName);
		const glAccount = glAccountForBankAccount(bankAccount);
		expect(glAccount).toBeTruthy();
		const balanceBefore = accountBalance(glAccount);

		await frame.getByRole("row", { name: new RegExp(`HV UI Realdaten ${runId.id}`) }).click();
		await expect(frame.getByText("Partei zuordnen")).toBeVisible();

		await frame.getByRole("button", { name: /Ohne Partei als Bank-Transaktion anlegen/ }).click();
		await expect(frame.getByText("Bank-Transaktion ohne Partei erstellt.")).toBeVisible();
		await expect(frame.locator(".tx-table").getByText("Beleg zuordnen")).toBeVisible();
		await expect(frame.getByRole("button", { name: /ACC-BTN-2026-/ }).first()).toBeVisible();

		const rowsAfterBt = rowsForRun(runId);
		expect(rowsAfterBt).toHaveLength(1);
		const bankTransaction = rowsAfterBt[0].bank_transaction;
		expect(bankTransaction).toMatch(/^ACC-BTN-2026-/);
		expect(docExists("Bank Transaction", bankTransaction)).toBe(true);
		expect(accountBalance(glAccount)).toBe(balanceBefore);

		await deleteCurrentImportThroughUi(page, frame);
		deleted = true;
		expect(rowsForRun(runId)).toHaveLength(0);
		expect(docExists("Bankauszug Import", importName)).toBe(false);
		if (docExists("Bank Transaction", bankTransaction)) {
			expect(Number(docValue("Bank Transaction", bankTransaction, "docstatus"))).toBe(2);
		}
		expect(accountBalance(glAccount)).toBe(balanceBefore);
	} finally {
		if (created && !deleted) {
			await deleteCurrentImportThroughUi(page, frame).catch(() => {});
		}
	}
});

test("verarbeitet Mehrzeilen-Import mit Fehlerzeile und kontrolliert DB-Zustaende", async ({ page }) => {
	const runId = {
		id: `${Date.now()}`,
		amount: `4${String(Date.now()).slice(-2)},42`,
	};

	await login(page);
	const frame = await bankimportFrame(page);
	let created = false;
	let deleted = false;

	try {
		await frame.getByRole("button", { name: "Neuer Import" }).click();
		await expect(frame.getByRole("heading", { name: "Neuer Bankimport" })).toBeVisible();
		await uploadCsvInDialog(frame, {
			filename: `hv-ui-mixed-${runId.id}.csv`,
			content: mixedCsvForRun(runId),
		});
		created = true;

		await expect(frame.getByText("Bankauszug importiert.")).toBeVisible();
		await expect(frame.locator(".tx-table tbody tr")).toHaveCount(3);
		await expect(frame.locator(".verwendung-cell", { hasText: `HV UI Realdaten ${runId.id} valide` })).toBeVisible();
		await expect(frame.locator(".verwendung-cell", { hasText: `HV UI Realdaten ${runId.id} betrag fehlt` })).toBeVisible();
		await expect(frame.locator(".verwendung-cell", { hasText: `HV UI Realdaten ${runId.id} ausgang` })).toBeVisible();
		await expect(frame.locator(".tx-table").getByText("Fehler")).toBeVisible();

		const rowsAfterImport = rowsForRun(runId);
		expect(rowsAfterImport).toHaveLength(3);
		const importName = rowsAfterImport[0].parent;
		expect(new Set(rowsAfterImport.map((row) => row.parent)).size).toBe(1);

		const validRow = rowsAfterImport.find((row) => row.verwendungszweck.endsWith("valide"));
		const failedRow = rowsAfterImport.find((row) => row.verwendungszweck.endsWith("betrag fehlt"));
		const outgoingRow = rowsAfterImport.find((row) => row.verwendungszweck.endsWith("ausgang"));
		expect(validRow.row_status).toBeFalsy();
		expect(validRow.richtung).toBe("Eingang");
		expect(Number(validRow.betrag)).toBeGreaterThan(0);
		expect(failedRow.row_status).toBeFalsy();
		expect(failedRow.error).toContain("Betrag fehlt");
		expect(outgoingRow.richtung).toBe("Ausgang");
		expect(Number(outgoingRow.betrag)).toBeGreaterThan(0);

		const bankAccount = importBankAccount(importName);
		const glAccount = glAccountForBankAccount(bankAccount);
		const balanceBefore = accountBalance(glAccount);

		await frame.getByRole("row", { name: new RegExp(`HV UI Realdaten ${runId.id} valide`) }).click();
		await expect(frame.getByText("Partei zuordnen")).toBeVisible();
		await frame.getByRole("button", { name: /Ohne Partei als Bank-Transaktion anlegen/ }).click();
		await expect(frame.getByText("Bank-Transaktion ohne Partei erstellt.")).toBeVisible();

		const rowsAfterBt = rowsForRun(runId);
		const validAfterBt = rowsAfterBt.find((row) => row.verwendungszweck.endsWith("valide"));
		const failedAfterBt = rowsAfterBt.find((row) => row.verwendungszweck.endsWith("betrag fehlt"));
		const outgoingAfterBt = rowsAfterBt.find((row) => row.verwendungszweck.endsWith("ausgang"));
		expect(validAfterBt.row_status).toBe("success");
		expect(validAfterBt.bank_transaction).toMatch(/^ACC-BTN-2026-/);
		expect(failedAfterBt.row_status).toBeFalsy();
		expect(failedAfterBt.error).toContain("Betrag fehlt");
		expect(failedAfterBt.bank_transaction).toBeFalsy();
		expect(outgoingAfterBt.row_status).toBeFalsy();
		expect(outgoingAfterBt.bank_transaction).toBeFalsy();
		expect(docExists("Bank Transaction", validAfterBt.bank_transaction)).toBe(true);
		expect(accountBalance(glAccount)).toBe(balanceBefore);

		await expect(frame.locator(".tx-table").getByText("Beleg zuordnen")).toBeVisible();
		await expect(frame.locator(".tx-table").getByText("Partei fehlt").first()).toBeVisible();
		await expect(frame.locator(".tx-table").getByText("Fehler")).toBeVisible();

		await deleteCurrentImportThroughUi(page, frame);
		deleted = true;
		expect(rowsForRun(runId)).toHaveLength(0);
		expect(docExists("Bankauszug Import", importName)).toBe(false);
		if (docExists("Bank Transaction", validAfterBt.bank_transaction)) {
			expect(Number(docValue("Bank Transaction", validAfterBt.bank_transaction, "docstatus"))).toBe(2);
		}
		expect(accountBalance(glAccount)).toBe(balanceBefore);
	} finally {
		if (created && !deleted) {
			await deleteCurrentImportThroughUi(page, frame).catch(() => {});
		}
	}
});

test("verrechnet Ueberzahlung nicht automatisch mit Unterzahlung im Folgemonat", async ({ page }) => {
	const runId = { id: `${Date.now()}` };
	let fixture = null;

	try {
		fixture = benchExecute("hausverwaltung.cypress_fixtures.seed_bankimport_over_under", {
			kwargs: { run_id: runId.id },
		});

		await login(page);
		const frame = await bankimportFrame(page);

		await createImportFromCsv(frame, {
			filename: `hv-ui-overunder-april-${runId.id}.csv`,
			content: overUnderCsvForRun({
				runId,
				label: "April",
				date: "15.04.2026",
				amount: "115,00",
				iban: fixture.iban,
			}),
		});
		await dismissDeskModals(page);
		await selectRowByPurpose(frame, `HV UI OverUnder ${runId.id} April`);
		await expect(frame.getByText(fixture.customer).first()).toBeVisible();
		await ensureSelectedRowHasBankTransaction(frame);

		let aprilRows = overUnderRowsForRun(runId, "April");
		expect(aprilRows).toHaveLength(1);
		expect(aprilRows[0].payment_entry).toBeFalsy();
		expect(invoiceOutstanding(fixture.april_invoice)).toBeCloseTo(100, 2);
		expect(invoiceOutstanding(fixture.may_invoice)).toBeCloseTo(100, 2);

		await frame.getByRole("button", { name: "Rechnung", exact: true }).click();
		const aprilCard = frame.locator(".invoice-card", { hasText: fixture.april_invoice });
		await expect(aprilCard).toBeVisible();
		await aprilCard.getByRole("checkbox").check();
		await frame.locator("label.advance-toggle", { hasText: "Restbetrag" }).getByRole("checkbox").check();
		await frame.getByRole("button", { name: /Zuordnen & buchen/ }).click();
		await expect(frame.getByText("Zahlung gebucht und Bank Transaction abgeglichen.")).toBeVisible();

		aprilRows = overUnderRowsForRun(runId, "April");
		expect(aprilRows).toHaveLength(1);
		expect(aprilRows[0].payment_entry).toBeTruthy();
		expect(invoiceOutstanding(fixture.april_invoice)).toBeCloseTo(0, 2);
		expect(invoiceOutstanding(fixture.may_invoice)).toBeCloseTo(100, 2);
		expect(paymentEntryUnallocated(aprilRows[0].payment_entry)).toBeCloseTo(15, 2);

		await createImportFromCsv(frame, {
			filename: `hv-ui-overunder-mai-${runId.id}.csv`,
			content: overUnderCsvForRun({
				runId,
				label: "Mai",
				date: "15.05.2026",
				amount: "85,00",
				iban: fixture.iban,
			}),
		});
		await dismissDeskModals(page);
		await selectRowByPurpose(frame, `HV UI OverUnder ${runId.id} Mai`);
		await expect(frame.getByText(fixture.customer).first()).toBeVisible();
		await ensureSelectedRowHasBankTransaction(frame);

		const mayRows = overUnderRowsForRun(runId, "Mai");
		expect(mayRows).toHaveLength(1);
		expect(mayRows[0].bank_transaction).toMatch(/^ACC-BTN-2026-/);
		expect(mayRows[0].payment_entry).toBeFalsy();
		expect(mayRows[0].auto_match_message).toContain("≠ 85.00");
		expect(invoiceOutstanding(fixture.may_invoice)).toBeCloseTo(100, 2);
		expect(paymentEntryUnallocated(aprilRows[0].payment_entry)).toBeCloseTo(15, 2);
	} finally {
		if (fixture) {
			benchExecute("hausverwaltung.cypress_fixtures.cleanup_bankimport_over_under", {
				kwargs: {
					run_id: runId.id,
					customer: fixture.customer,
					party_bank_account: fixture.party_bank_account,
					april_invoice: fixture.april_invoice,
					may_invoice: fixture.may_invoice,
				},
			});
		}
	}
});
