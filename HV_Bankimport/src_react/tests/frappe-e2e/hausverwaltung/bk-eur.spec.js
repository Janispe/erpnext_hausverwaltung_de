import { benchExecute, expect, fixtures, formDoc, openForm, saveForm, setFormValues, test } from "./frappe.js";

test("EÜR speichert Einnahmen, Ausgaben und Überschuss aus gebuchten Sachkonten", async ({ desk }) => {
	const env = benchExecute(`${fixtures}.seed_e2e_eur`);
	const expected = benchExecute(`${fixtures}.get_expected_eur_totals`, [], env);
	expect(expected).toMatchObject({ einnahmen: 123.45, ausgaben: 40, ueberschuss: 83.45 });
	const doctype = "Einnahmen Ueberschuss Rechnung";
	await openForm(desk, doctype);
	await setFormValues(desk, { ...env, umlage_method: "Kontenstruktur", include_non_euer_accounts: 1 });
	await saveForm(desk);
	const { name } = await formDoc(desk);
	await desk.reload();
	await desk.waitForFunction((name) => window.cur_frm?.doc?.name === name, name);
	const doc = await formDoc(desk);
	expect(Number(doc.summe_einnahmen)).toBeCloseTo(expected.einnahmen, 2);
	expect(Number(doc.summe_ausgaben)).toBeCloseTo(expected.ausgaben, 2);
	expect(Number(doc.ueberschuss)).toBeCloseTo(expected.ueberschuss, 2);
	expect(doc.positionen.length).toBeGreaterThan(0);
});
