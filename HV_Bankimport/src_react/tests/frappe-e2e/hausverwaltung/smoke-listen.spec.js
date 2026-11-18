import { expect, openList, test } from "./frappe.js";

for (const doctype of [
	"Immobilie", "Mietvertrag", "Eigentuemer", "Mietrechnungen Durchlauf",
	"Betriebskostenabrechnung Immobilie", "Betriebskostenabrechnung Mieter", "Bankauszug Import",
]) {
	test(`Liste ${doctype} öffnet`, async ({ desk }) => {
		await openList(desk, doctype);
		await expect(desk.locator(".error-message:visible")).toHaveCount(0);
	});
}

test("Serienbrief Vorlage öffnet den Vorlagen-Browser", async ({ desk }) => {
	await desk.goto("/app/serienbrief-vorlage");
	await expect(desk).toHaveURL(/serienbrief_browser/);
	await expect(desk.locator('iframe.mail-merge-browser-frame[title="Serienbrief Vorlagen-Browser"]')).toBeVisible();
});
