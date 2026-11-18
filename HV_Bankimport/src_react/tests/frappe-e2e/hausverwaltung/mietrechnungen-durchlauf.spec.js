import { dialog, expect, openForm, test } from "./frappe.js";

test("Neuer Mietrechnungen-Durchlauf öffnet den Dialog und schließt ohne Buchung", async ({ desk }) => {
	const generation = [];
	desk.on("request", (request) => {
		if (request.method() === "POST" && request.url().endsWith(".generate_miet_und_bk_rechnungen")) {
			generation.push(request);
		}
	});

	await openForm(desk, "Mietrechnungen Durchlauf");
	const modal = dialog(desk);
	await expect(modal).toContainText("Mietrechnungen erstellen");
	for (const field of ["company", "monat", "jahr"]) {
		await expect(modal.locator(`.frappe-control[data-fieldname="${field}"]`)).toBeVisible();
	}
	await desk.waitForFunction(() => window.cur_dialog?.display === true);
	await modal.locator(".btn-modal-close").click();
	await expect(modal).toHaveCount(0);
	await expect(desk.locator(".modal-backdrop:visible")).toHaveCount(0);
	await desk.evaluate(() => cur_frm.refresh());
	await expect(modal).toHaveCount(0);
	expect(generation).toHaveLength(0);
});
