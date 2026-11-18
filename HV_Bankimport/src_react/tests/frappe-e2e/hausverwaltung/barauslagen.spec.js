import { randomUUID } from "node:crypto";
import { actionResponse, benchExecute, call, dialog, expect, fixtures, test } from "./frappe.js";
import { setDialog } from "./cockpit.js";

const pilot = "hausverwaltung.hausverwaltung.services.receipt_pilot";
const engine = "hausverwaltung.proposals.receipt_action";

for (const [source, accountKey, person] of [
	["Objektkasse", "cash", ""],
	["Privat vorgestreckt", "clearing", "A. Test"],
]) {
	test(`Buchungs-Inbox gibt einen Bon für ${source} frei und bucht einmal`, async ({ desk }) => {
		const seed = benchExecute(`${fixtures}.seed_e2e_receipts`);
		const batchId = randomUUID();
		const filename = `bon-${batchId}.png`;
		const original = Buffer.from(seed.original, "base64");
		const upload = await desk.request.post(`/api/method/${pilot}.upload_receipt`, {
			headers: { "X-Frappe-CSRF-Token": await desk.evaluate(() => frappe.csrf_token) },
			multipart: {
				batch_id: batchId,
				context: JSON.stringify({
					kostenstelle: seed.costCenter, zahlungsquelle: source, zahlungskonto: seed[accountKey], person,
				}),
				file: { name: filename, mimeType: "image/png", buffer: original },
			},
		});
		expect(upload.ok(), await upload.text()).toBe(true);
		const { message: { name } } = await upload.json();
		benchExecute(`${fixtures}.prepare_e2e_receipt`, [name, seed.supplier, seed.nonBk.name]);

		await desk.evaluate(() => frappe.set_route("buchungs_inbox"));
		await desk.locator(".hv-inbox-list-row").filter({ hasText: filename }).click();
		await expect(desk.locator(".hv-inbox-pdf img")).toBeVisible();
		const url = await desk.locator(".hv-inbox-pdf img").getAttribute("src");
		const downloaded = await desk.request.get(url);
		expect(await downloaded.body()).toEqual(original);
		await desk.getByRole("button", { name: "Bon prüfen", exact: true }).click();
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
