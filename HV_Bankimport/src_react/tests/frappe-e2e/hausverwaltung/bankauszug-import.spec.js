import { apiPost, benchExecute, expect, fixtures, openForm, test, visiblePage } from "./frappe.js";

const api = "hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import";

test("Bankauszug Import öffnet neu und zeigt beim gespeicherten Import seine Aktionen", async ({ desk }) => {
	await openForm(desk, "Bankauszug Import");
	await expect(desk.locator(".error-message:visible")).toHaveCount(0);
	const { name } = benchExecute(`${fixtures}.seed_e2e_bankauszug`);
	await openForm(desk, "Bankauszug Import", name);
	await expect.poll(() => desk.evaluate(() => cur_frm.__hv_phase)).toBe("empty");
	await expect(visiblePage(desk).getByRole("button", { name: "Aktionen" })).toBeVisible();
});

test("Bankauszug-API meldet fehlende Argumente und unbekannte Importe als Fehler", async ({ desk }) => {
	const docname = "NONEXISTENT-BAI-999";
	for (const [method, args] of [
		["parse_csv", {}],
		["manually_reconcile_row", { docname, row_idx: 0, invoice_allocations: [] }],
		["create_standalone_payment_for_row", { docname, row_idx: 0 }],
	]) {
		expect((await apiPost(desk, `${api}.${method}`, args)).status(), method).toBeGreaterThanOrEqual(400);
	}
});
