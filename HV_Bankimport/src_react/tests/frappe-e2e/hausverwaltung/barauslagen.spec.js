import { randomUUID } from "node:crypto";
import { actionResponse, benchExecute, call, dialog, expect, fixtures, test } from "./frappe.js";
import { setDialog } from "./cockpit.js";

const pilot = "hausverwaltung.hausverwaltung.services.receipt_pilot";
const engine = "hausverwaltung.proposals.receipt_action";

const inbox = "hausverwaltung.hausverwaltung.services.bulk_extraction";

async function uploadReadyReceipt(page, source, accountKey, person) {
	const seed = benchExecute(`${fixtures}.seed_e2e_receipts`);
	const batchId = randomUUID();
	const filename = `bon-${batchId}.png`;
	const original = Buffer.from(seed.original, "base64");
	const context = {
		kostenstelle: seed.costCenter, zahlungsquelle: source, zahlungskonto: seed[accountKey], person,
	};
	const upload = await page.request.post(`/api/method/${pilot}.upload_receipt`, {
		headers: { "X-Frappe-CSRF-Token": await page.evaluate(() => frappe.csrf_token) },
		multipart: {
			batch_id: batchId, context: JSON.stringify(context),
			file: { name: filename, mimeType: "image/png", buffer: original },
		},
	});
	expect(upload.ok(), await upload.text()).toBe(true);
	const { message: { name } } = await upload.json();
	benchExecute(`${fixtures}.prepare_e2e_receipt`, [name, seed.supplier, seed.nonBk.name]);
	return { seed, filename, original, name, context };
}

async function openReceipt(page, filename) {
	await page.evaluate(() => frappe.set_route("buchungs_inbox"));
	await page.locator(".hv-inbox-list-row").filter({ hasText: filename }).click();
	await expect(page.locator(".hv-inbox-pdf img")).toBeVisible();
	await expect(page.getByRole("button", { name: "Bon prüfen", exact: true })).toBeEnabled();
}

for (const [source, accountKey, person] of [
	["Objektkasse", "cash", ""],
	["Privat vorgestreckt", "clearing", "A. Test"],
]) {
	test(`Buchungs-Inbox gibt einen Bon für ${source} frei und bucht einmal`, async ({ desk }) => {
		const { seed, filename, original, name } = await uploadReadyReceipt(desk, source, accountKey, person);
		await openReceipt(desk, filename);
		const url = await desk.locator(".hv-inbox-pdf img").getAttribute("src");
		const downloaded = await desk.request.get(url);
		expect(await downloaded.body()).toEqual(original);
		await desk.getByRole("button", { name: "Bon prüfen", exact: true }).click();
		await expect(dialog(desk)).toBeVisible();
		await desk.waitForFunction(() => window.cur_dialog?.fields_dict?.beleg_eur_bestaetigt);
		await setDialog(desk, { beleg_brutto_bestaetigt: 42.50, beleg_eur_bestaetigt: 1 });
		const execution = desk.waitForResponse((response) =>
			new URL(response.url()).pathname === `/api/method/${engine}.execute`);
		const approval = await actionResponse(desk, `${engine}.approve`, () =>
			dialog(desk).getByRole("button", { name: "Freigeben und buchen", exact: true }).click());
		expect(approval.ok(), await approval.text()).toBe(true);
		const { message: { binding, status } } = await approval.json();
		expect(status).toBe("Approved");
		const response = await execution;
		expect(response.ok(), await response.text()).toBe(true);
		const { message } = await response.json();
		expect(message.status).toBe("Succeeded");
		await expect(dialog(desk)).toHaveCount(0);

		const result = message.result;
		const [repeated, invoice, journal] = await Promise.all([
			call(desk, `${engine}.execute`, { name, binding }),
			call(desk, "frappe.client.get", { doctype: "Purchase Invoice", name: result.name }),
			call(desk, "frappe.client.get", { doctype: "Journal Entry", name: result.settlement_journal_entry }),
		]);
		expect(repeated.result).toEqual(result);
		expect(invoice).toMatchObject({
			docstatus: 1, bill_no: name, supplier: seed.supplier, grand_total: 42.5, outstanding_amount: 0,
			items: [expect.objectContaining({ expense_account: seed.nonBk.konto, cost_center: seed.costCenter })],
		});
		expect(journal.docstatus).toBe(1);
		expect(journal.accounts.filter((row) => row.credit_in_account_currency)).toMatchObject([
			{ account: seed[accountKey], credit_in_account_currency: 42.5 },
		]);
		if (person) expect(journal.user_remark).toContain(person);
	});
}

test("Inbox aktualisiert Bon-Angaben und Freigabe aus einer zweiten Buchhaltungssitzung", async ({ desk, browser, baseURL }) => {
	const { seed, filename, name, context } = await uploadReadyReceipt(desk, "Privat vorgestreckt", "clearing", "A. Test");
	await openReceipt(desk, filename);
	const secondSession = await browser.newContext({ baseURL });
	try {
		const login = await secondSession.request.post("/api/method/login", {
			form: { usr: "Administrator", pwd: process.env.FRAPPE_PASSWORD || "admin" },
		});
		expect(login.ok()).toBe(true);
		const other = await secondSession.newPage();
		await other.goto("/app");
		await other.waitForFunction(() => window.frappe?.csrf_token);
		const full = await call(other, `${inbox}.get_vorschlag_full`, { name });
		const approval = await call(other, `${engine}.approve`, {
			name, source: full.receipt_review.source,
			booking: {
				lieferant: seed.supplier, rechnungsdatum: "2026-10-04", rechnungsname: name,
				beleg_brutto_bestaetigt: 42.50, beleg_eur_bestaetigt: true,
				positionen: [{ betrag: 42.50, kostenart: seed.nonBk.name, umlagefaehig: "Kostenart nicht umlagefaehig" }],
			},
		});
		expect(approval.status).toBe("Approved");
		await expect(desk.getByRole("button", { name: "Buchung fortsetzen", exact: true })).toBeEnabled();

		await call(other, `${pilot}.update_context`, { name, context: { ...context, person: "B. Test" } });
		await desk.locator(".btn-refresh").click();
		await expect(desk.locator(".hv-inbox-values").getByText("B. Test", { exact: true })).toBeVisible();
		await expect(desk.getByText(/Freigabe ungültig/)).toBeVisible();
		await expect(desk.getByRole("button", { name: "Bon prüfen", exact: true })).toBeEnabled();
		const updated = await call(other, `${inbox}.get_vorschlag_full`, { name });
		expect(updated.status).toBe("Ready");
		expect(updated.receipt_review.status).toBe("Stale");
	} finally {
		await secondSession.close();
	}
});
