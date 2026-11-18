import { dialog, expect } from "./frappe.js";

export const cockpitApi = "hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit";

export async function openCockpit(page, kind) {
	await page.waitForFunction((name) => typeof window.hausverwaltung?.buchen_cockpit?.[name] === "function",
		`open_${kind}_dialog`);
	await page.evaluate((name) => {
		window.hausverwaltung.buchen_cockpit[name]();
	}, `open_${kind}_dialog`);
	await expect(dialog(page)).toBeVisible();
	await page.waitForFunction(() => window.cur_dialog?.fields_dict?.positionen);
}

export function setDialog(page, values, rows) {
	return page.evaluate(async ({ values, rows }) => {
		const dlg = cur_dialog;
		for (const [field, value] of Object.entries(values)) await dlg.set_value(field, value);
		if (rows !== undefined) {
			const grid = dlg.fields_dict.positionen.grid;
			grid.df.data = rows;
			grid.refresh();
		}
	}, { values, rows });
}

export const cockpitFields = (page, fields) => page.evaluate((fields) => {
	const dlg = cur_dialog;
	const values = Object.fromEntries(fields.map((field) => [field, dlg.get_value(field)]));
	const rows = (dlg.fields_dict.positionen.grid.df.data || []).filter((row) => row && !row.__islocal_empty);
	const costLabel = dlg.fields_dict.positionen.grid.docfields.find((field) => field.fieldname === "kostenart")?.label;
	return { ...values, rows, costLabel };
}, fields);
