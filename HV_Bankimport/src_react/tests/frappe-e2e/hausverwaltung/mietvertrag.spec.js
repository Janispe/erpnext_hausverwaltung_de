import { apiPost, benchExecute, fixtures, expect, formDoc, openForm, test, visiblePage } from "./frappe.js";

const controller = "hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag";

test("Neuer Mietvertrag öffnet ohne Fehler", async ({ desk }) => {
	await openForm(desk, "Mietvertrag");
	await expect(desk.locator(".error-message:visible")).toHaveCount(0);
});

test("Bestehender Mietvertrag zeigt Aktionen und hat einen eigenen Buchhaltungskunden", async ({ desk }) => {
	const { lease, leases } = benchExecute(`${fixtures}.seed_e2e_lease`);
	expect(leases).toEqual([{ name: lease.name, wohnung: lease.wohnung }]);
	await openForm(desk, "Mietvertrag", lease.name);
	expect(await formDoc(desk)).toMatchObject(lease);
	const form = visiblePage(desk);
	await expect(form).toContainText("Staffelmieten sortieren");
	await expect(form).toContainText("Sollstellungen prüfen");
	await form.locator(".inner-group-button").getByRole("button", { name: /Accounting|Buchhaltung/ }).click();
	await expect(form.locator(".dropdown-menu:visible")).toContainText("Mieterkonto");
});

test("Mietvertrags-API aktualisiert Status und behandelt unbekannte Paperless-Links", async ({ desk }) => {
	expect((await apiPost(desk, `${controller}.update_statuses_for_list`)).ok()).toBe(true);
	const response = await apiPost(desk, `${controller}.get_mietvertrag_paperless_link`, {
		mietvertrag: "NONEXISTENT-MV-999",
	});
	expect(response.status()).toBeLessThan(500);
});
