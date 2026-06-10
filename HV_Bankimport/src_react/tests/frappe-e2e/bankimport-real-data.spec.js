import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

const FRAPPE_USER = process.env.FRAPPE_USER || "Administrator";
const FRAPPE_PASSWORD = process.env.FRAPPE_PASSWORD || "admin";
const FRAPPE_SITE = process.env.FRAPPE_SITE || "frontend";
const FRAPPE_BACKEND_CONTAINER = process.env.FRAPPE_BACKEND_CONTAINER || "hausverwaltung_peters-backend-1";
const FRAPPE_BENCH_DIR = process.env.FRAPPE_BENCH_DIR || "/home/frappe/frappe-bench";

async function login(page) {
	await page.goto("/desk/bankimport_v2");
	if (!page.url().includes("/login")) return;

	await page.getByRole("textbox", { name: "Email" }).fill(FRAPPE_USER);
	await page.getByRole("textbox", { name: "Password" }).fill(FRAPPE_PASSWORD);
	await page.getByRole("button", { name: "Login" }).click();
	await expect(page).toHaveURL(/\/desk\/bankimport_v2/);
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

async function createImportThroughUi(frame, runId) {
	await frame.getByRole("button", { name: "Neuer Import" }).click();
	await expect(frame.getByRole("heading", { name: "Neuer Bankimport" })).toBeVisible();
	await uploadCsvInDialog(frame, {
		filename: `hv-ui-realdata-${runId.id}.csv`,
		content: csvForRun(runId),
	});

	await expect(frame.getByText("Bankauszug importiert.")).toBeVisible();
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
