import { apiPost, benchExecute, fixtures, dialog, expect, openList, test } from "./frappe.js";

const brief = "mail_merge.mail_merge.doctype.serienbrief_vorlage.serienbrief_vorlage";
const run = "mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf";

test("Serienbrief-Durchlauf: Liste, Vorlagendaten und breiter Empfänger-Picker", async ({ desk }) => {
	const template = benchExecute(`${fixtures}.seed_e2e_serienbrief`);
	await openList(desk, "Serienbrief Durchlauf");
	await desk.evaluate((name) => {
		window.mail_merge.serienbrief.open_new_durchlauf_dialog({ vorlage: name });
	}, template.vorlage);
	await expect(dialog(desk)).toBeVisible();
	const fields = ["vorlage", "iteration_doctype", "title", "kategorie"];
	await expect.poll(() => desk.evaluate((fields) =>
		Object.fromEntries(fields.map((field) => [field, window.cur_dialog?.get_value(field)])), fields))
		.toEqual({ ...template, iteration_doctype: "Mietvertrag" });
	await dialog(desk).locator('[data-fieldname="pick_objects_btn"] button').click();
	await expect(desk.locator(".modal:visible")).toHaveCount(2);
	const picker = dialog(desk);
	await expect(picker.getByRole("button", { name: /Filter hinzufügen|Add Filter/i })).toBeVisible();
	const target = await desk.evaluate(() => innerWidth * frappe.boot.hv_ui.picker_modal_width_vw / 100);
	expect(target).toBeGreaterThan(0);
	await expect.poll(async () => (await picker.locator(".modal-dialog").boundingBox())?.width ?? 0)
		.toBeGreaterThan(target * 0.95);
});

test("Wohnungs-Picker bietet Status- und Immobilienfilter ohne Statusvorgabe", async ({ desk }) => {
	await desk.evaluate(() => {
		new frappe.ui.form.MultiSelectDialog({
			doctype: "Wohnung", setters: { status: "", immobilie: "" },
			add_filters_group: 1, action() {},
		});
	});
	const picker = dialog(desk);
	await expect(picker.locator('[data-fieldname="immobilie"]').first()).toBeVisible();
	await expect(picker.locator('[data-fieldname="status"] select, [data-fieldname="status"] input').first()).toHaveValue("");
});

test("Serienbrief-API sucht Vorlagen und lehnt unbekannte Vorlagen und Durchläufe ab", async ({ desk }) => {
	expect((await apiPost(desk, `${brief}.search_serienbrief_vorlagen`, { query: "" })).ok()).toBe(true);
	for (const [path, data] of [
		[`${brief}.render_template_preview_pdf`, { docname: "NONEXISTENT-SBV-999" }],
		[`${brief}.render_template_preview_html`, { docname: "NONEXISTENT-SBV-999" }],
		[`${brief}.copy_serienbrief_vorlage`, { source_name: "NONEXISTENT-SBV-999" }],
		[`${run}.generate_pdf`, { docname: "NONEXISTENT-SBD-999" }],
		[`${run}.generate_html`, { docname: "NONEXISTENT-SBD-999" }],
	]) {
		const response = await apiPost(desk, path, data);
		expect(response.status(), path).toBeGreaterThanOrEqual(400);
		expect(response.status(), path).toBeLessThan(500);
	}
});
