import { apiPost, benchExecute, fixtures, dialog, expect, openForm, test, visiblePage } from "./frappe.js";

const doctype = "Betriebskostenabrechnung Immobilie";
const api = "hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie";

test("Betriebskostenabrechnung öffnet neu und zeigt für gebuchte Abrechnungen den Versanddialog", async ({ desk }) => {
	await openForm(desk, doctype);
	await expect(desk.locator(".error-message:visible")).toHaveCount(0);
	const { name } = benchExecute(`${fixtures}.seed_e2e_betriebskostenabrechnung`);
	await openForm(desk, doctype, name);
	await visiblePage(desk).getByRole("button", { name: "Abrechnungen versenden" }).click();
	const modal = dialog(desk);
	await expect(modal.locator('select[data-fieldname="mode"]')).toBeVisible();
	await expect(modal.locator('.frappe-control[data-fieldname="serienbrief_vorlage"]')).toHaveCount(1);
});

test("Abrechnungsentwurf öffnet Bereitschaftsprüfung und Vorjahresvergleich", async ({ desk }) => {
	const { name } = benchExecute(`${fixtures}.seed_e2e_betriebskostenabrechnung`, [], { submit: false });
	await openForm(desk, doctype, name);
	const form = visiblePage(desk);
	const readiness = form.getByRole("button", { name: "Abrechnungsbereitschaft prüfen", exact: true });
	const comparison = form.getByRole("button", { name: "Vorjahresvergleich", exact: true });
	await expect(readiness).toBeVisible();
	await expect(comparison).toBeVisible();

	await readiness.click();
	await expect(dialog(desk).locator(".modal-title")).toHaveText("Abrechnungsbereitschaft prüfen");
	await desk.keyboard.press("Escape");
	await expect(dialog(desk)).toHaveCount(0);

	await comparison.click();
	await expect(dialog(desk).locator(".modal-title")).toHaveText("Vorjahresvergleich");
	await expect(dialog(desk).getByRole("columnheader", { name: "Vorjahreswert" })).toBeVisible();
});

test("Betriebskosten-API lehnt unbekannte Abrechnungen ab", async ({ desk }) => {
	for (const method of ["get_mieter_abrechnungen", "get_verteilungsbasis", "dispatch_mieter_abrechnungen", "download_batch_print_html"]) {
		const args = method === "download_batch_print_html"
			? { doctype: "Betriebskostenabrechnung Mieter", names: ["NONEXISTENT-BKM-999"] }
			: { name: "NONEXISTENT-BKI-999" };
		const response = await apiPost(desk, `${api}.${method}`, args);
		expect([403, 404, 417], method).toContain(response.status());
	}
});
