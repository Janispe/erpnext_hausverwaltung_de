import { actionResponse, benchExecute, fixtures, call, dialog, expect, openList, test, visiblePage } from "./frappe.js";
import { cockpitApi, cockpitFields, openCockpit, setDialog } from "./cockpit.js";

function seedPurchase() {
	return benchExecute(`${fixtures}.seed_e2e_purchase_cockpit`);
}

async function applyTemplate(page, name) {
	await setDialog(page, { aus_vorlage: name });
}

test("Kostenartenvorlage erscheint in der Liste und übernimmt nach Bestätigung beide Kostenarten", async ({ desk }) => {
	const { tag, supplier, costCenter, bk, nonBk } = seedPurchase();
	const rows = [
		{ typ: "umlegbar", kostenart: bk.name, kostenstelle: costCenter, betrag: 99.5 },
		{ typ: "nicht umlegbar", kostenart: nonBk.name, kostenstelle: costCenter, betrag: 50 },
	];
	const { name } = await call(desk, `${cockpitApi}.save_vorlage_from_cockpit`, {
		titel: tag, lieferant: supplier, eingabemodus: "Kostenart", remarks: tag, positionen: rows,
	});
	await openList(desk, "Eingangsrechnung Vorlage");
	await expect(visiblePage(desk).locator(".list-row").filter({ hasText: tag })).toBeVisible();
	await openCockpit(desk, "eingangsrechnung");
	await setDialog(desk, { lieferant: supplier, remarks: "Vorhandene Anmerkung" });
	await applyTemplate(desk, name);
	await expect(dialog(desk)).toContainText("überschrieben");
	await dialog(desk).getByRole("button", { name: /^(Yes|Ja)$/ }).click();
	await expect.poll(() => cockpitFields(desk, ["lieferant", "eingabemodus", "remarks"])).toMatchObject({
		lieferant: supplier, eingabemodus: "Kostenart", remarks: tag,
		rows: [{ ...rows[0], betriebskostenart: bk.name }, { ...rows[1], kostenart_nicht_ul: nonBk.name }],
	});
	await expect(dialog(desk).locator('.grid-body [data-fieldname="kostenart"]').first()).toBeVisible();
});

test("Cockpit restauriert Entwurf, wechselt auf Konto und speichert einen Purchase-Invoice-Entwurf", async ({ desk }) => {
	const { supplier, costCenter, bk, nonBk, tag } = seedPurchase();
	const initialRow = { typ: "umlegbar", kostenart: bk.name, betriebskostenart: bk.name, kostenstelle: costCenter, betrag: 12.34 };
	await desk.evaluate((data) => {
		localStorage.setItem("hv_buchen_cockpit_draft_pi_v1", JSON.stringify({ ts: Date.now(), data }));
	}, { lieferant: supplier, eingabemodus: "Kostenart", remarks: tag, positionen: [initialRow] });
	await openCockpit(desk, "eingangsrechnung");
	await desk.locator(".hv-cockpit-draft-banner .hv-draft-restore").click();
	await expect.poll(() => cockpitFields(desk, ["lieferant", "remarks", "eingabemodus"])).toMatchObject({
		lieferant: supplier, remarks: tag, eingabemodus: "Kostenart", rows: [initialRow],
	});
	await desk.waitForFunction(() => !cur_dialog._hv_suppress_kostenart_clear);
	await setDialog(desk, { eingabemodus: "Konto" });
	await expect.poll(async () => {
		const { costLabel, rows } = await cockpitFields(desk, []);
		return { costLabel, cost: rows[0]?.kostenart || "" };
	}).toEqual({ costLabel: "Konto", cost: "" });
	const rows = [
		{ typ: "umlegbar", kostenart: bk.konto, kostenstelle: costCenter, betrag: 80.12 },
		{ typ: "nicht umlegbar", kostenart: nonBk.konto, kostenstelle: costCenter, betrag: 19.88 },
	];
	await setDialog(desk, {}, rows);
	await dialog(desk).getByRole("button", { name: "Als Vorlage speichern" }).click();
	await dialog(desk).locator('[data-fieldname="titel"] input').fill(tag);
	const response = await actionResponse(desk, `${cockpitApi}.save_vorlage_from_cockpit`, () =>
		dialog(desk).getByRole("button", { name: "Speichern", exact: true }).click());
	expect(response.ok(), await response.text()).toBe(true);
	const { message: { name } } = await response.json();
	await expect(dialog(desk).locator('[data-fieldname="positionen"]')).toBeVisible();
	const template = await call(desk, "frappe.client.get", { doctype: "Eingangsrechnung Vorlage", name });
	expect(template).toMatchObject({ eingabemodus: "Konto", lieferant: supplier });
	await dialog(desk).locator(".btn-modal-close").click();
	await expect(dialog(desk)).toHaveCount(0);
	await openCockpit(desk, "eingangsrechnung");
	await setDialog(desk, { lieferant: supplier, remarks: "behalten" });
	await applyTemplate(desk, name);
	const confirmation = desk.locator(".modal:visible").filter({ hasText: "überschrieben" });
	await confirmation.getByRole("button", { name: /^(No|Nein)$/ }).click();
	await expect(confirmation).toBeHidden();
	await expect.poll(() => cockpitFields(desk, ["remarks"])).toMatchObject({ remarks: "behalten" });
	await applyTemplate(desk, name);
	await confirmation.getByRole("button", { name: /^(Yes|Ja)$/ }).click();
	await expect(confirmation).toBeHidden();
	await expect.poll(() => cockpitFields(desk, ["eingabemodus"])).toMatchObject({
		eingabemodus: "Konto", costLabel: "Konto",
		rows: [{ ...rows[0], betriebskostenart: bk.name }, { ...rows[1], kostenart_nicht_ul: nonBk.name }],
	});
	await setDialog(desk, { rechnungsdatum: "2026-05-06", wertstellungsdatum: "2026-04-30", rechnungsname: tag });
	const creation = await actionResponse(desk, `${cockpitApi}.create_purchase_invoice`, () =>
		dialog(desk).getByRole("button", { name: "Als Entwurf speichern" }).click());
	expect(creation.ok(), await creation.text()).toBe(true);
	const { message } = await creation.json();
	const invoice = await call(desk, "frappe.client.get", { doctype: "Purchase Invoice", name: message.name });
	expect(invoice).toMatchObject({
		docstatus: 0, bill_no: tag, supplier, custom_wertstellungsdatum: "2026-04-30",
		hv_eingabequelle: "Vereinfachte Buchung",
		items: [
			{ expense_account: bk.konto, hv_umlagefaehig: "Betriebskostenart", hv_kostenart: bk.name, rate: 80.12 },
			{ expense_account: nonBk.konto, hv_umlagefaehig: "Kostenart nicht umlagefaehig", hv_kostenart: nonBk.name, rate: 19.88 },
		],
	});
	expect(invoice.grand_total).toBeCloseTo(100, 2);
});

test("Eingangsrechnung mit unvollständiger Position erzeugt keinen Beleg", async ({ desk }) => {
	const { supplier, costCenter, bk, tag } = seedPurchase();
	await openCockpit(desk, "eingangsrechnung");
	await setDialog(desk, { lieferant: supplier, rechnungsdatum: "2026-05-06", rechnungsname: tag, eingabemodus: "Konto" }, [
		{ typ: "umlegbar", kostenart: bk.konto, kostenstelle: costCenter },
	]);
	await dialog(desk).getByRole("button", { name: "Als Entwurf speichern" }).click();
	await expect(dialog(desk)).toContainText("Betrag fehlt");
	expect(await call(desk, "frappe.client.get_list", {
		doctype: "Purchase Invoice", filters: { supplier, bill_no: tag }, fields: ["name"],
	})).toEqual([]);
});
