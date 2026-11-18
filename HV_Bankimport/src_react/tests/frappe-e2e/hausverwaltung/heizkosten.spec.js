import { actionResponse, benchExecute, fixtures, dialog, expect, formDoc, openForm, saveMethod, test, visiblePage } from "./frappe.js";

const doctype = "Heizkostenabrechnung Immobilie";

function seedHeizkosten(mode) {
	return benchExecute(`${fixtures}.seed_e2e_heizkosten`, [mode]);
}

async function submit(page) {
	await visiblePage(page).locator(".primary-action:visible").click();
	await dialog(page).getByRole("button", { name: /^(Yes|Ja)$/ }).click();
}

function trackSaves(page) {
	const saves = [];
	page.on("request", (request) => {
		if (request.method() === "POST" && request.url().endsWith(saveMethod)) saves.push(request);
	});
	return saves;
}

test("Nullkosten bleiben ohne Bestätigung ungebucht", async ({ desk }) => {
	const { head } = seedHeizkosten("nullkosten");
	await openForm(desk, doctype, head);
	expect(await formDoc(desk)).toMatchObject({ docstatus: 0 });
	const saves = trackSaves(desk);
	const modal = dialog(desk);
	await submit(desk);
	await expect(modal).toContainText("Die erfassten Heizkosten betragen null Euro");
	await modal.getByRole("button", { name: /^(No|Nein)$/ }).click();
	await expect(modal).toHaveCount(0);
	expect(saves).toHaveLength(0);
	expect(await formDoc(desk)).toMatchObject({ docstatus: 0 });

	await submit(desk);
	await expect(modal).toContainText("Die erfassten Heizkosten betragen null Euro");
	const response = await actionResponse(desk, saveMethod, () =>
		modal.getByRole("button", { name: /^(Yes|Ja)$/ }).click());
	expect(response.ok(), await response.text()).toBe(true);
	await expect.poll(() => formDoc(desk)).toMatchObject({ docstatus: 1, nullkosten_bestaetigt: 1 });
});

test("Doppelbuchung wird verhindert, Admin kann einen Korrekturentwurf erstellen", async ({ desk }) => {
	const { head, duplicate } = seedHeizkosten("doppelbuchung");
	await openForm(desk, doctype, duplicate);
	const saves = trackSaves(desk);
	await submit(desk);
	await expect(dialog(desk)).toContainText("Doppelte Heizkostenabrechnung verhindert");
	expect(saves).toHaveLength(0);
	expect(await formDoc(desk)).toMatchObject({ docstatus: 0 });

	await desk.reload();
	await desk.waitForFunction(() => window.frappe?.set_route);
	await openForm(desk, doctype, head);
	expect(await formDoc(desk)).toMatchObject({ docstatus: 1 });
	await visiblePage(desk).getByRole("button", { name: "Korrekturentwurf erstellen" }).click();
	await expect(dialog(desk)).toContainText("Heizkostenabrechnung kontrolliert berichtigen");
	await dialog(desk).locator('[data-fieldname="reason"] textarea').fill("Wärmedienst korrigiert die Kosten");
	const response = await actionResponse(desk,
		"hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie.create_correction_draft",
		() => dialog(desk).getByRole("button", { name: "Stornieren und Entwurf erstellen" }).click());
	expect(response.ok(), await response.text()).toBe(true);
	const { message } = await response.json();
	expect(message.amended_from).toBe(head);
	await expect.poll(() => formDoc(desk)).toMatchObject({
		name: message.name, docstatus: 0, amended_from: head,
	});
	const { mieter_positionen } = await formDoc(desk);
	expect(mieter_positionen).toHaveLength(1);
	expect(mieter_positionen[0].kosten_gesamt).toBe(100);
});
