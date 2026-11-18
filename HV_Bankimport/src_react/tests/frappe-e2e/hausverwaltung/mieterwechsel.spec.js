import { randomBytes } from "node:crypto";
import { benchExecute, fixtures, call, expect, formDoc, openForm, saveForm, setFormValues, test, visiblePage } from "./frappe.js";

const pad = (value) => String(value).padStart(2, "0");
const toDate = (year, monthIndex, day) => new Date(year, monthIndex, day);
const fmt = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const monthStart = (offsetMonths = 0) => {
	const now = new Date();
	return toDate(now.getFullYear(), now.getMonth() + offsetMonths, 1);
};
const monthEnd = (offsetMonths = 0) => {
	const now = new Date();
	return toDate(now.getFullYear(), now.getMonth() + offsetMonths + 1, 0);
};

const DATES = {
	zustandAb: fmt(monthStart(-18)),
	altAbschluss: fmt(monthStart(-19)),
	altVon: fmt(monthStart(-18)),
	altStaffel: fmt(monthStart(-6)),
	altBis: fmt(monthEnd(-1)),
	neuAbschluss: fmt(monthStart(-1)),
	neuVon: fmt(monthStart(0)),
	neuStaffel: fmt(monthStart(12)),
	neuBkStaffel: fmt(monthStart(7)),
};

async function createLease(page, { mieter, personen, miete, betriebskosten, heizkosten, kaution, ...values }) {
	await openForm(page, "Mietvertrag");
	await setFormValues(page, values);
	await page.evaluate((tables) => {
		for (const [field, rows] of Object.entries(tables)) {
			cur_frm.clear_table(field);
			for (const row of rows) cur_frm.add_child(field, row);
			cur_frm.refresh_field(field);
		}
	}, { mieter, personen, miete, betriebskosten, heizkosten, kaution });
	await saveForm(page);
	return formDoc(page);
}

test("Mieterwechsel erhält Altvertrag und Customer und zeigt den Neuvertrag an der Wohnung", async ({ desk }) => {
	const TEST_TAG = `MW ${randomBytes(4).toString("hex")}`;
	const { wohnung, altKontakt, neuKontaktA, neuKontaktB } = benchExecute(`${fixtures}.seed_e2e_mieterwechsel`, [TEST_TAG, DATES.zustandAb]);
	const altVertrag = await createLease(desk, {
		wohnung,
		vertragsabschluss_am: DATES.altAbschluss,
		von: DATES.altVon,
		bis: DATES.altBis,
		bevorzugter_versandweg: "Post",
		notizen: `Altvertrag endet wegen Mieterwechsel ${TEST_TAG}. Uebergabe im Vormonat.`,
		kaution_notizen: "Kaution nach Abnahme und Schlussabrechnung pruefen.",
		mieter: [
			{
				mieter: altKontakt,
				rolle: "Hauptmieter",
				eingezogen: DATES.altVon,
				ausgezogen: DATES.altBis,
			},
		],
		personen: [
			{ von: DATES.altVon, personen: 1 },
			{ von: DATES.altStaffel, personen: 2 },
		],
		miete: [
			{ von: DATES.altVon, miete: 700, art: "Monatlich" },
			{ von: DATES.altStaffel, miete: 735, art: "Monatlich" },
		],
		betriebskosten: [{ von: DATES.altVon, miete: 140, art: "Monatlich" }],
		heizkosten: [{ von: DATES.altVon, miete: 95, art: "Monatlich" }],
		kaution: [{ von: DATES.altVon, miete: 2100, art: "Gesamter Zeitraum" }],
	});

	const neuVertrag = await createLease(desk, {
		wohnung,
		vertragsabschluss_am: DATES.neuAbschluss,
		von: DATES.neuVon,
		bis: "",
		bevorzugter_versandweg: "Email",
		notizen: `Neuabschluss aus Mieterwechsel ${TEST_TAG}: Einzug, Zaehler, Kaution und Vorauszahlungen angelegt.`,
		kaution_notizen: "Drei Nettokaltmieten, Zahlung in zwei Raten vereinbart.",
		mieter: [
			{ mieter: neuKontaktA, rolle: "Hauptmieter", eingezogen: DATES.neuVon },
			{ mieter: neuKontaktB, rolle: "Hauptmieter", eingezogen: DATES.neuVon },
		],
		personen: [{ von: DATES.neuVon, personen: 2 }],
		miete: [
			{ von: DATES.neuVon, miete: 760, art: "Monatlich" },
			{ von: DATES.neuStaffel, miete: 790, art: "Monatlich" },
		],
		betriebskosten: [
			{ von: DATES.neuVon, miete: 150, art: "Monatlich" },
			{ von: DATES.neuBkStaffel, miete: 165, art: "Monatlich" },
		],
		heizkosten: [{ von: DATES.neuVon, miete: 105, art: "Monatlich" }],
		kaution: [{ von: DATES.neuVon, miete: 2280, art: "Gesamter Zeitraum" }],
	});

	expect(altVertrag.name).not.toBe(neuVertrag.name);
	expect(altVertrag.kunde).toBeTruthy();
	expect(neuVertrag.kunde).toBeTruthy();
	expect(altVertrag.kunde).not.toBe(neuVertrag.kunde);
	await openForm(desk, "Mietvertrag", altVertrag.name);
	const old = await formDoc(desk);
	expect(old).toMatchObject({ wohnung, status: "Vergangenheit", bis: DATES.altBis });
	expect(old.mieter).toHaveLength(1);
	expect(old.personen).toHaveLength(2);
	expect(Number(old.bruttomiete)).toBeCloseTo(970, 2);
	await expect(visiblePage(desk)).toContainText("Sollstellungen prüfen");

	await openForm(desk, "Mietvertrag", neuVertrag.name);
	const current = await formDoc(desk);
	expect(current).toMatchObject({ wohnung, status: "Läuft", bevorzugter_versandweg: "Email" });
	expect(current.mieter.map((row) => row.mieter)).toEqual([neuKontaktA, neuKontaktB]);
	expect(current.miete).toHaveLength(2);
	expect(current.betriebskosten).toHaveLength(2);
	expect(current.heizkosten).toHaveLength(1);
	expect(Number(current.bruttomiete)).toBeCloseTo(1015, 2);
	await expect(visiblePage(desk)).toContainText("Staffelmieten sortieren");

	await openForm(desk, "Wohnung", wohnung);
	const apartment = await formDoc(desk);
	expect(apartment).toMatchObject({ status: "Vermietet", aktueller_mietvertrag: neuVertrag.name });
	expect(apartment.mietvertraege_alle).toEqual(expect.arrayContaining([
		expect.objectContaining({ mietvertrag: altVertrag.name, status: "Vergangenheit" }),
		expect.objectContaining({ mietvertrag: neuVertrag.name, status: "Läuft" }),
	]));
	await expect(visiblePage(desk).locator('[data-fieldname="aktueller_mietvertrag"]:visible')).toContainText(TEST_TAG);
	await visiblePage(desk).locator(".form-tabs .nav-link").getByText("Mietverträge").click();
	const history = visiblePage(desk).locator('[data-fieldname="mietvertraege_alle"]:visible');
	await expect(history).toContainText("Vergangenheit");
	await expect(history).toContainText("Läuft");

	for (const { name, kunde } of [altVertrag, neuVertrag]) {
		const rows = await call(desk, "frappe.client.get_list", {
			doctype: "Mietvertrag", filters: { kunde }, fields: ["name", "wohnung"],
		});
		expect(rows).toEqual([{ name, wohnung }]);
	}
});
