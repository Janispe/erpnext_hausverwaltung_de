import { actionResponse, dialog, expect, formDoc, openForm, setFormValues, test, visiblePage } from "./frappe.js";

const previewMethod = "hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.vorschau_teilmonatsmiete";
const prorated = "Automatisch anteilig";
const fixed = "Festbetrag";
const firstPeriod = { von: "2027-01-16", bis: "2027-01-31" };
const input = (page, name) => dialog(page).locator(`[data-fieldname="${name}"] input`);
const select = (page, name, value) => dialog(page).locator(`[data-fieldname="${name}"] select`).selectOption(value);
const draftRules = async (page) => (await formDoc(page)).miete_teilmonate || [];

async function prepare(page) {
	await openForm(page, "Mietvertrag");
	await setFormValues(page, { von: firstPeriod.von, bis: "2027-03-15" });
	await page.evaluate(() => {
		cur_frm.clear_table("miete");
		cur_frm.add_child("miete", { von: "2027-01-16", art: "Monatlich", miete: 620 });
		cur_frm.refresh_field("miete");
		return cur_frm.script_manager.trigger("refresh");
	});
	await visiblePage(page).locator(".form-tabs .nav-link").getByText("Miete und Betriebskosten").click();
}

async function preview(page, action, amount) {
	const response = await actionResponse(page, previewMethod, action);
	expect(response.ok(), await response.text()).toBe(true);
	if (amount !== undefined) expect((await response.json()).message.amount).toBe(amount);
}

const openButton = (page) => visiblePage(page).locator('[data-fieldname="teilmonatsmiete_festlegen"] button');

async function openPartMonth(page, amount = 320) {
	await preview(page, () => openButton(page).click(), amount);
	await expect(dialog(page)).toContainText("Teilmonat festlegen");
	await page.waitForFunction(() => window.cur_dialog?.display === true);
}

const adoptButton = (page) => dialog(page).getByRole("button", { name: "In Mietvertrag übernehmen" });

async function adopt(page) {
	await preview(page, () => adoptButton(page).click());
	await expect(dialog(page)).toHaveCount(0);
}

async function fillAmount(page, amount) {
	await input(page, "betrag").fill(String(amount));
	await input(page, "betrag").blur();
}

async function expectDate(page, field, isoDate) {
	const formatted = await page.evaluate((date) => frappe.datetime.str_to_user(date), isoDate);
	await expect(input(page, field)).toHaveValue(formatted);
}

async function calendarDay(page, day) {
	await input(page, "bis").click();
	await page.locator(`.datepicker.active .datepicker--cell-day[data-date="${day}"][data-month="0"][data-year="2027"]:visible`).click();
}

test("Monatsmiete und Gültigkeitsbeginn bleiben sichtbar, Einzug wird kalendertäglich berechnet", async ({ desk }) => {
	const invoiceRequests = [];
	desk.on("request", (request) => {
		if (request.method() === "POST" && request.url().includes(".generate_mietrechnungen.")) invoiceRequests.push(request);
	});
	await prepare(desk);
	const fields = await desk.evaluate(() => {
		const field = (table, name) => cur_frm.get_field(table).grid.docfields.find((df) => df.fieldname === name);
		return {
			rent: field("miete", "miete").label,
			validFrom: field("miete", "von").label,
			rentTypeHidden: field("miete", "art").hidden,
			deposit: field("kaution", "miete").label,
			bkTypeHidden: field("betriebskosten", "art").hidden || 0,
		};
	});
	expect(fields).toEqual({
		rent: "Monatsmiete", validFrom: "Gültig ab", rentTypeHidden: 1, deposit: "Betrag", bkTypeHidden: 0,
	});
	await openPartMonth(desk);
	await expectDate(desk, "von", "2027-01-16");
	await expectDate(desk, "bis", "2027-01-31");
	await adopt(desk);
	expect(await draftRules(desk)).toMatchObject([{ ...firstPeriod, berechnung: prorated, betrag: 0 }]);
	expect(invoiceRequests).toHaveLength(0);
});

for (const amount of [300, 0]) {
	test(`Festbetrag ${amount} wird übernommen`, async ({ desk }) => {
		await prepare(desk);
		await openPartMonth(desk);
		await select(desk, "berechnung", fixed);
		await expect(input(desk, "betrag")).toHaveValue("");
		if (amount === 300) {
			await adoptButton(desk).click();
			await expect(dialog(desk)).toContainText("Bitte den vereinbarten Betrag eingeben");
			expect(await draftRules(desk)).toHaveLength(0);
		}
		await preview(desk, () => fillAmount(desk, amount), amount);
		await adopt(desk);
		expect(await draftRules(desk)).toMatchObject([{ ...firstPeriod, berechnung: fixed, betrag: amount }]);
		expect((await formDoc(desk)).miete[0].miete).toBe(620);
		if (amount === 0) {
			await openPartMonth(desk, 0);
			await preview(desk, () => select(desk, "berechnung", prorated), 320);
			await adopt(desk);
			expect(await draftRules(desk)).toMatchObject([{ ...firstPeriod, berechnung: prorated }]);
		}
	});
}

test("Letzter Mietmonat und übrige Tage eines verkürzten Festzeitraums", async ({ desk }) => {
	await prepare(desk);
	await openPartMonth(desk);
	await preview(desk, () => select(desk, "zeitraum", "Letzter Mietmonat"), 300);
	await expectDate(desk, "von", "2027-03-01");
	await expectDate(desk, "bis", "2027-03-15");
	await preview(desk, () => select(desk, "zeitraum", "Erster Mietmonat"), 320);
	await preview(desk, () => calendarDay(desk, 20));
	await expectDate(desk, "bis", "2027-01-20");
	await select(desk, "berechnung", fixed);
	await preview(desk, () => fillAmount(desk, 100), 320);
	await expect(dialog(desk).locator('[data-role="part-month-preview"] tbody tr')).toHaveCount(2);
	await adopt(desk);
	expect(await draftRules(desk)).toMatchObject([{ ...firstPeriod, bis: "2027-01-20", berechnung: fixed, betrag: 100 }]);
});

test("Betriebskosten und Miete behalten getrennte Teilmonatsregeln", async ({ desk }) => {
	await prepare(desk);
	await desk.evaluate(() => {
		cur_frm.add_child("betriebskosten", { von: "2027-01-16", miete: 105 });
		cur_frm.refresh_field("betriebskosten");
	});
	await openPartMonth(desk);
	await preview(desk, () => select(desk, "kostenart", "Betriebskosten"), 54.19);
	await select(desk, "berechnung", fixed);
	await preview(desk, () => fillAmount(desk, 55), 55);
	await adopt(desk);
	expect(await draftRules(desk)).toMatchObject([{ ...firstPeriod, kostenart: "Betriebskosten", berechnung: fixed, betrag: 55 }]);
	await openPartMonth(desk);
	await expect(dialog(desk).locator('[data-fieldname="berechnung"] select')).toHaveValue(prorated);
});

test("Verkürztes Vertragsende markiert alle Kostenarten zur Korrektur", async ({ desk }) => {
	await prepare(desk);
	const scopes = await desk.evaluate(async () => {
		const frm = cur_frm;
		const isNew = frm.is_new;
		frm.is_new = () => false;
		try {
			await frm.script_manager.trigger("onload");
			await frm.script_manager.trigger("before_save");
			const before = frm.__hv_sollstellung_korrektur_scope;
			frm.doc.bis = "2027-02-10";
			await frm.script_manager.trigger("before_save");
			return [before, frm.__hv_sollstellung_korrektur_scope];
		} finally {
			frm.is_new = isNew;
		}
	});
	expect(scopes).toEqual([{}, {
		Miete: "2027-02-01", Betriebskosten: "2027-02-01",
		Heizkosten: "2027-02-01", Untermietzuschlag: "2027-02-01",
	}]);
});

test("Ältere Feststaffel behält Betrag und sichtbare Art", async ({ desk }) => {
	await prepare(desk);
	const result = await desk.evaluate(async () => {
		const frm = cur_frm;
		Object.assign(frm.doc.miete[0], { art: "Gesamter Zeitraum", miete: 300 });
		await frm.script_manager.trigger("refresh");
		const rent = frm.get_field("miete");
		return { hidden: rent.grid.docfields.find((df) => df.fieldname === "art").hidden,
			description: rent.df.description, row: frm.doc.miete[0] };
	});
	expect(result).toMatchObject({ hidden: 0, row: { art: "Gesamter Zeitraum", miete: 300 } });
	expect(result.description).toContain("ältere Festbeträge");
});

test("Teilmonat ohne vereinbarte Monatsmiete wird abgelehnt", async ({ desk }) => {
	await prepare(desk);
	await desk.evaluate(() => {
		cur_frm.clear_table("miete");
		cur_frm.refresh_field("miete");
		return cur_frm.script_manager.trigger("refresh");
	});
	const response = await actionResponse(desk, previewMethod, () => openButton(desk).click());
	expect([417, 422]).toContain(response.status());
	await expect(dialog(desk)).toContainText("Monatsmiete");
	const error = dialog(desk);
	await error.locator(".btn-modal-close").click();
	await expect(dialog(desk)).toContainText("Teilmonat festlegen");
	const adoptResponse = await actionResponse(desk, previewMethod, () => adoptButton(desk).click());
	expect([417, 422]).toContain(adoptResponse.status());
	expect(await adoptResponse.text()).toContain("Monatsmiete");
	expect(await draftRules(desk)).toHaveLength(0);
	expect((await formDoc(desk)).__islocal).toBe(1);
});

test("Geänderter Festzeitraum überschreibt dieselbe Regel und behält andere Regeln", async ({ desk }) => {
	await prepare(desk);
	const existing = [
		{ ...firstPeriod, berechnung: fixed, betrag: 300 },
		{ von: "2027-03-01", bis: "2027-03-15", berechnung: fixed, betrag: 0 },
	];
	const names = await desk.evaluate((rules) => {
		const names = rules.map((rule) => cur_frm.add_child("miete_teilmonate", rule).name);
		cur_frm.refresh_field("miete_teilmonate");
		return names;
	}, existing);
	await openPartMonth(desk, 300);
	await preview(desk, () => calendarDay(desk, 25), 420);
	await adopt(desk);
	expect(await draftRules(desk)).toMatchObject([
		{ ...existing[0], name: names[0], bis: "2027-01-25" }, { ...existing[1], name: names[1] },
	]);
});

test("Teilmonatsdialog passt in ein schmales Browserfenster", async ({ desk }) => {
	await desk.setViewportSize({ width: 412, height: 915 });
	await prepare(desk);
	await openPartMonth(desk);
	await select(desk, "berechnung", fixed);
	await preview(desk, () => fillAmount(desk, 300), 300);
	const bounds = await dialog(desk).locator(".modal-dialog").boundingBox();
	expect(bounds.x).toBeGreaterThanOrEqual(0);
	expect(bounds.x + bounds.width).toBeLessThanOrEqual(412);
	await adopt(desk);
});
