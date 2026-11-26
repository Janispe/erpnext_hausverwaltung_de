import { randomUUID } from "node:crypto";
import { actionResponse, apiPost, benchExecute, call, dialog, expect, fixtures, test } from "./frappe.js";
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

test("Bon-Uploads verlinken zwei getrennte Paperclip-Aufträge im neuen Tab", async ({ desk }) => {
	const batch = "hausverwaltung.hausverwaltung.services.receipt_batch";
	const seed = benchExecute(`${fixtures}.seed_e2e_receipts`);
	const csrf = await desk.evaluate(() => frappe.csrf_token);
	const uploads = await Promise.all(["erst", "zweiter"].map(async (label) => {
		const filename = `mehrbons-${label}-${randomUUID()}.png`;
		const response = await desk.request.post(`/api/method/${batch}.upload`, {
			headers: { "X-Frappe-CSRF-Token": csrf },
			multipart: {
				request_id: randomUUID(), note: `Synthetischer Stapel ${label}`,
				file: { name: filename, mimeType: "image/png", buffer: Buffer.from(seed.original, "base64") },
			},
		});
		expect(response.ok(), await response.text()).toBe(true);
		const { message } = await response.json();
		return { filename, name: message.name, issueId: randomUUID() };
	}));
	await desk.evaluate(() => frappe.set_route("buchungs_inbox"));
	const uploadList = desk.locator(".hv-receipt-batch-list");
	await uploadList.locator("summary").click();
	for (const upload of uploads) {
		const row = uploadList.locator("p").filter({ hasText: upload.filename });
		await expect(row.getByText("Paperclip-Verknüpfung ausstehend")).toBeVisible();
		benchExecute(`${fixtures}.bind_e2e_receipt_issue`, [upload.name, upload.issueId]);
	}
	await desk.locator(".btn-refresh").click();
	for (const upload of uploads) {
		const expectedUrl = `https://paperclip.invalid/HVTEST/issues/${upload.issueId}`;
		const row = uploadList.locator("p").filter({ hasText: upload.filename });
		const link = row.getByRole("link", { name: "Paperclip öffnen" });
		await expect(link).toHaveAttribute("href", expectedUrl);
		await expect(link).toHaveAttribute("target", "_blank");
	}
	const secondUrl = `https://paperclip.invalid/HVTEST/issues/${uploads[1].issueId}`;
	await desk.context().route(secondUrl, (route) => route.fulfill({
		status: 200, contentType: "text/html; charset=utf-8", body: "<h1>Synthetisches zweites Gespräch</h1>",
	}));
	const popup = desk.waitForEvent("popup");
	await uploadList.locator("p").filter({ hasText: uploads[1].filename }).getByRole("link", { name: "Paperclip öffnen" }).click();
	const conversation = await popup;
	await expect(conversation).toHaveURL(secondUrl);
	await expect(conversation.getByRole("heading", { name: "Synthetisches zweites Gespräch" })).toBeVisible();
});

test("Drei Bons trotz offener Punkte einzeln prüfen", async ({ desk }) => {
	const batch = "hausverwaltung.hausverwaltung.services.receipt_batch";
	const seed = benchExecute(`${fixtures}.seed_e2e_receipts`);
	const context = { kostenstelle: seed.costCenter, zahlungsquelle: "Objektkasse", zahlungskonto: seed.cash };
	const filename = `manuelle-pruefung-${randomUUID()}.png`;
	const upload = await desk.request.post(`/api/method/${batch}.upload`, {
		headers: { "X-Frappe-CSRF-Token": await desk.evaluate(() => frappe.csrf_token) },
		multipart: {
			request_id: randomUUID(), context: JSON.stringify(context),
			file: { name: filename, mimeType: "image/png", buffer: Buffer.from(seed.original, "base64") },
		},
	});
	expect(upload.ok(), await upload.text()).toBe(true);
	const { message } = await upload.json();
	const [first, second] = benchExecute(`${fixtures}.prepare_e2e_receipt_manual_batch`,
		[message.name, seed.supplier, seed.nonBk.name]);
	const reviewBon = async (index) => {
		await openReceipt(desk, `Bon ${index} · ${filename}`);
		await desk.getByRole("button", { name: "Bon prüfen", exact: true }).click();
		await expect(dialog(desk)).toBeVisible();
	};

	await reviewBon(1);
	await expect(dialog(desk).getByText("Kontierung bitte mit dem Bon abgleichen.")).toBeVisible();
	await dialog(desk).getByRole("button", { name: "Hinweise überspringen und manuell prüfen" }).click();
	await expect(dialog(desk).getByText("Kontierung bitte mit dem Bon abgleichen.")).toBeHidden();
	await expect(dialog(desk).locator('[data-fieldname="lieferant"] input')).toBeVisible();
	await dialog(desk).locator(".btn-modal-close").click();
	await expect(dialog(desk)).toHaveCount(0);
	const firstBon = await call(desk, `${inbox}.get_vorschlag_full`, { name: first });
	expect(firstBon.receipt_batch.revisions[0].warnings)
		.toContain("Kontierung bitte mit dem Bon abgleichen.");
	expect(firstBon.receipt_review.status).toBe("Pending");

	await reviewBon(3);
	await expect(dialog(desk).getByText("Bitte den Zuschnitt oder die Aufteilung des Bons zuerst klären.")).toBeVisible();
	await expect(dialog(desk).getByRole("button", { name: "Freigeben und buchen" })).toBeDisabled();
	await dialog(desk).locator(".btn-modal-close").click();
	await expect(dialog(desk)).toHaveCount(0);

	await reviewBon(2);
	await expect(dialog(desk).getByText("Pflichtangaben klären")).toBeVisible();
	const secondBon = await call(desk, `${inbox}.get_vorschlag_full`, { name: second });
	const denied = await apiPost(desk, `${engine}.approve`, {
		name: second, source: secondBon.receipt_review.source,
		booking: {
			lieferant: seed.supplier, rechnungsdatum: "2026-10-04", rechnungsname: second,
			beleg_brutto_bestaetigt: 42.50, beleg_eur_bestaetigt: true,
			positionen: [{ betrag: 42.50, kostenart: seed.nonBk.name, umlagefaehig: "Kostenart nicht umlagefaehig" }],
		},
	});
	expect(denied.ok()).toBe(false);
	expect(await denied.text()).toContain("Welche Kostenstelle ist diesem Gebäude eindeutig zugeordnet?");
	await dialog(desk).locator('.frappe-control[data-fieldname="kostenstelle"] input').fill(context.kostenstelle);
	await dialog(desk).locator('.frappe-control[data-fieldname="zahlungsquelle"] select').selectOption(context.zahlungsquelle);
	await dialog(desk).locator('.frappe-control[data-fieldname="zahlungskonto"] input').fill(context.zahlungskonto);
	await dialog(desk).locator('.frappe-control[data-fieldname="beleg_brutto_bestaetigt"] input').fill("42.50");
	await dialog(desk).getByRole("checkbox", { name: "Der Originalbeleg ist in EUR ausgestellt" }).check();
	const booking = desk.waitForResponse((response) => new URL(response.url()).pathname === `/api/method/${engine}.execute`);
	const approved = await actionResponse(desk, `${engine}.approve`, () =>
		dialog(desk).getByRole("button", { name: "Freigeben und buchen" }).click());
	expect(approved.ok(), await approved.text()).toBe(true);
	const executed = await booking;
	expect(executed.ok(), await executed.text()).toBe(true);
	expect((await executed.json()).message.status).toBe("Succeeded");
});
