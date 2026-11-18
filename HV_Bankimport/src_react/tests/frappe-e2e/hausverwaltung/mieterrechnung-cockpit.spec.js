import { actionResponse, apiPost, benchExecute, fixtures, call, dialog, expect, test } from "./frappe.js";
import { cockpitApi, cockpitFields, openCockpit, setDialog } from "./cockpit.js";

const create = `${cockpitApi}.create_sales_invoice`;
const day = { rechnungsdatum: "2026-05-06", faellig_am: "2026-05-27" };

function seedSales() {
	return benchExecute(`${fixtures}.seed_e2e_sales_cockpit`);
}

test("Mieterrechnung API speichert Beträge, Artikel, Erlöskonto, Wertstellung und Bemerkung", async ({ desk }) => {
	const { mietvertrag, kunde, account, item } = seedSales();
	const legacyRemark = `Erfasst über Buchungs-Cockpit | Mietvertrag: ${mietvertrag} | Referenz: `;
	const cases = [
		{ rows: [{ beschreibung: "Renovierungspauschale", betrag: 250, erloeskonto: account }],
			remarks: "Renovierungspauschale", inputRemark: legacyRemark, total: 250, itemCode: "Guthaben/Nachzahlungen" },
		{ rows: [{ beschreibung: "Erste Position", betrag: 12, artikel: item }, { beschreibung: "Zweite Position", betrag: 25 }],
			remarks: "Manuell erfasst", inputRemark: "Manuell erfasst", total: 37, itemCode: item },
		{ rows: [{ betrag: 7, erloeskonto: account }],
			remarks: "", inputRemark: legacyRemark, total: 7, itemCode: "Guthaben/Nachzahlungen" },
	];
	for (const { rows, remarks, inputRemark, total, itemCode } of cases) {
		const result = await call(desk, create, {
			...day, mietvertrag, submit_doc: 0, positionen: rows, bemerkung: inputRemark,
			wertstellungsdatum: "2026-04-30",
		});
		expect(result.submitted).toBe(false);
		const invoice = await call(desk, "frappe.client.get", { doctype: "Sales Invoice", name: result.name });
		expect(invoice).toMatchObject({ customer: kunde, docstatus: 0, custom_wertstellungsdatum: "2026-04-30",
			hv_eingabequelle: "Vereinfachte Mieterrechnung" });
		expect(invoice.remarks || "").toBe(remarks);
		expect(invoice.mietabrechnung_id || "").toBe("");
		expect(invoice.items).toHaveLength(rows.length);
		expect(invoice.items[0]).toMatchObject({ qty: 1, rate: rows[0].betrag, item_code: itemCode });
		if (rows[0].erloeskonto) expect(invoice.items[0].income_account).toBe(account);
		expect(invoice.grand_total).toBeCloseTo(total, 2);
	}
	expect(await call(desk, "frappe.client.get", { doctype: "Item", name: "Guthaben/Nachzahlungen" }))
		.toMatchObject({ is_stock_item: 0 });
});

test("Mieterrechnung API lehnt fehlenden Vertrag, leere Positionen und fehlenden Betrag ab", async ({ desk }) => {
	const { mietvertrag } = seedSales();
	for (const [data, error] of [
		[{ positionen: [{ betrag: 1 }] }, /Mietvertrag/i],
		[{ mietvertrag, positionen: [] }, /Position/i],
		[{ mietvertrag, positionen: [{ beschreibung: "ohne Betrag" }] }, /Betrag/i],
	]) {
		const response = await apiPost(desk, create, { ...day, submit_doc: 0, ...data });
		expect(response.status()).toBeGreaterThanOrEqual(400);
		expect(response.status()).toBeLessThan(500);
		expect(await response.text()).toMatch(error);
	}
});

for (const submitted of [false, true]) {
	test(submitted ? "Gebuchte Mieterrechnung erscheint im Mieterkonto" : "Cockpit speichert Mieterrechnung als Entwurf", async ({ desk }) => {
		const { mietvertrag, kunde, account, company } = seedSales();
		const beschreibung = "HV UI Nachzahlung";
		await openCockpit(desk, "mieterrechnung");
		await setDialog(desk, { mietvertrag, ...day }, [{ beschreibung, betrag: 44.44, erloeskonto: account }]);
		await expect.poll(() => cockpitFields(desk, ["kunde"])).toMatchObject({ kunde });
		const response = await actionResponse(desk, create, () => dialog(desk).getByRole("button", {
			name: submitted ? "Buchen" : "Als Entwurf speichern", exact: true,
		}).click());
		expect(response.ok(), await response.text()).toBe(true);
		const { message } = await response.json();
		await desk.waitForFunction((name) => window.cur_frm?.doc?.name === name, message.name);
		const invoice = await call(desk, "frappe.client.get", { doctype: "Sales Invoice", name: message.name });
		expect(invoice).toMatchObject({ customer: kunde, docstatus: Number(submitted),
			hv_eingabequelle: "Vereinfachte Mieterrechnung", items: [{ item_code: "Guthaben/Nachzahlungen", rate: 44.44 }] });
		if (submitted) {
			const { result } = await call(desk, "frappe.desk.query_report.run", {
				report_name: "Mieterkonto", ignore_prepared_report: 1,
				filters: { company, customer: kunde, from_date: "2026-01-01", to_date: "2026-12-31",
					show_kategorien: 1, gruppieren_pro_monat: 0 },
			});
			const row = result.find((row) => row.belegnummer === invoice.name || row.belegnummern?.includes(invoice.name));
			expect(row).toMatchObject({ beschreibung, art: "Forderung", betrag_guthaben_nachzahlungen: 44.44, betrag_summe: 44.44 });
		}
	});
}

test("Buchen ohne Position erzeugt keine Mieterrechnung", async ({ desk }) => {
	const { mietvertrag, kunde } = seedSales();
	await openCockpit(desk, "mieterrechnung");
	await setDialog(desk, { mietvertrag, ...day }, []);
	await expect.poll(() => cockpitFields(desk, ["kunde"])).toMatchObject({ kunde });
	await dialog(desk).getByRole("button", { name: "Buchen", exact: true }).click();
	await expect(dialog(desk)).toContainText(/keine Position|mindestens eine Position/i);
	expect(await call(desk, "frappe.client.get_list", {
		doctype: "Sales Invoice", filters: { customer: kunde }, fields: ["name"],
	})).toEqual([]);
});
