import { expect, test } from "@playwright/test";

const demo = "/?import=BAI-KI-DEMO-0001";
const suggestion = (page) => page.getByRole("region", { name: "KI-Vorschlag" });
const table = (page) => page.locator(".tx-table");
const openBulk = async (page) => {
	await page.getByRole("button", { name: /Vorschläge übernehmen/ }).click();
	return page.getByRole("dialog", { name: /Vorschläge übernehmen/ });
};

test("übernimmt und bucht den Vorschlag, dann springt die Auswahl weiter", async ({ page }) => {
	await page.goto(demo);
	await table(page).locator("tbody tr").first().click();
	await suggestion(page).getByRole("button", { name: /Übernehmen & buchen/ }).click();
	await expect(page.getByText("Zahlung gebucht · SINV-2026-0041 ausgeglichen")).toBeVisible();
	await expect(table(page).locator(".selected")).toContainText("Erika Beispiel");
	await page.getByRole("button", { name: /^Alle 9$/ }).click();
	await expect(table(page).locator("tbody tr").first()).toContainText("Gebucht");
});

test("hält nach Inline-Ablehnung im KI-Filter dieselbe Zeile und öffnet die manuelle Zuordnung", async ({ page }) => {
	await page.goto(demo);
	await page.getByRole("button", { name: /KI Vorschlag 6/ }).click();
	await table(page).locator("tbody tr").nth(3).click();
	await suggestion(page).getByRole("button", { name: /Ablehnen …/ }).click();
	const submit = suggestion(page).getByRole("button", { name: "Ablehnen", exact: true });
	await expect(submit).toBeDisabled();
	await suggestion(page).getByRole("radio", { name: "Falscher Beleg" }).check();
	await suggestion(page).getByLabel("Begründung (Pflicht)").fill("Der Beleg gehört zu einer anderen Zahlung.");
	await submit.click();
	await expect(suggestion(page)).toContainText("Abgelehnt von M. Krüger");
	await expect(page.getByText("Selbst zuordnen", { exact: true })).toBeVisible();
	await expect(page.locator(".match-body").getByText("Beleg zuordnen", { exact: true })).toBeVisible();
	await expect(table(page).locator(".selected")).toContainText("Postbank");
});

test("Anpassen öffnet den Rechnungsmodus mit vorausgewählter Rechnung", async ({ page }) => {
	await page.goto(demo);
	await expect(page.getByRole("button", { name: /Selbst zuordnen/ })).toHaveAttribute("aria-expanded", "false");
	await suggestion(page).getByRole("button", { name: "Anpassen" }).click();
	await expect(page.getByRole("button", { name: /Selbst zuordnen/ })).toHaveAttribute("aria-expanded", "true");
	await expect(page.locator(".match-body .seg-btn.active")).toHaveText("Rechnung");
	await expect(page.locator(".match-body .invoice-card").filter({ hasText: "SINV-2026-0041" }).getByRole("checkbox")).toBeChecked();
	await expect(page.locator(".reco-card")).toHaveCount(0);
	await expect(page.getByText(/Vom KI-Vorschlag vorausgefüllt.*Angepasst gebucht: Beleg/)).toBeVisible();
});

test("Sammelauswahl startet leer und übernimmt drei hohe Vorschläge", async ({ page }) => {
	await page.goto(demo);
	const dialog = await openBulk(page);
	await expect(dialog.getByText(/0 ausgewählt/)).toBeVisible();
	await expect(dialog.getByRole("button", { name: "0 übernehmen und buchen" })).toBeDisabled();
	await expect(dialog.getByRole("checkbox")).toHaveCount(6);
	await dialog.getByRole("button", { name: "Hohe Sicherheit" }).click();
	await expect(dialog.getByText(/3 ausgewählt · Eingang [^\d]*720,00\s*€ · Ausgang [^\d]*102,40\s*€/)).toBeVisible();
	await dialog.getByRole("button", { name: "3 übernehmen und buchen" }).click();
	await expect(dialog.getByText("3 gebucht · 0 übersprungen")).toBeVisible();
	await expect(dialog.getByRole("listitem")).toHaveCount(3);
	await dialog.getByRole("button", { name: "Schließen", exact: true }).click();
	await expect(page.getByText(/3 Vorschläge offen/)).toBeVisible();
});

test("Filter zeigt Pending und Approved, ohne veraltete oder abgelehnte Vorschläge", async ({ page }) => {
	await page.goto(demo + "&ki=states");
	await page.getByRole("button", { name: /KI Vorschlag 5/ }).click();
	await expect(table(page).locator("tbody tr")).toHaveCount(5);
	await expect(suggestion(page).getByText("Freigegeben", { exact: true })).toBeVisible();
	await expect(table(page).getByText("Veraltet")).toHaveCount(0);
	await expect(table(page).getByText("Abgelehnt")).toHaveCount(0);
});

test("bei 390 px passen die Beträge aller Zeilen in den Viewport", async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 880 });
	await page.goto(demo);
	await page.getByRole("button", { name: /^Alle 9$/ }).click();
	await expect(table(page).getByRole("columnheader", { name: "KI-Vorschlag" })).toBeHidden();
	await expect(table(page).getByRole("columnheader", { name: "Verwendungszweck" })).toBeHidden();
	const amounts = table(page).locator(".col-amount");
	await expect(amounts).toHaveCount(9);
	for (const amount of await amounts.all()) {
		await expect(amount).toBeVisible();
		await expect(amount).toContainText("€");
		const box = await amount.boundingBox();
		expect(box.x).toBeGreaterThanOrEqual(0);
		expect(box.x + box.width).toBeLessThanOrEqual(390);
	}
	await expect(suggestion(page)).toBeVisible();
	const marks = table(page).locator(".ki-party-mark:visible");
	await expect(marks).toHaveCount(7);
	await expect(marks).toHaveText(["KI hoch", "KI mittel", "KI hoch", "KI hoch", "KI mittel", "KI niedrig", "KI veraltet"]);
	await expect(table(page).locator(".ki-party-mark .ki-meter:visible")).toHaveCount(6);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test("Zeilenlink öffnet auch gebuchte Zeilen, unbekannte IDs behalten die Standardauswahl", async ({ page }) => {
	await page.goto(demo + "&row=r9");
	await expect(table(page).locator(".selected")).toContainText("SINV-2026-0033");
	await expect(suggestion(page)).toContainText("Freigegeben und gebucht von");
	await page.goto(demo + "&row=unbekannt");
	await expect(table(page).locator(".selected")).toContainText("SINV-2026-0041");
	await expect(table(page).locator("tbody tr")).toHaveCount(8);
});

test("Tastatur wechselt Zeilen und öffnet, schließt und bestätigt Karten", async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	await page.goto(demo);
	await table(page).locator("tbody tr").first().focus();
	await page.keyboard.press("j");
	await expect(table(page).locator(".selected")).toContainText("Erika Beispiel");
	await page.keyboard.press("k");
	await expect(table(page).locator(".selected")).toContainText("SINV-2026-0041");
	await page.keyboard.press("r");
	await expect(suggestion(page).getByText("Was stimmt nicht?")).toBeVisible();
	await page.keyboard.press("Escape");
	await expect(suggestion(page).getByText("Was stimmt nicht?")).toBeHidden();
	await suggestion(page).getByRole("button", { name: /Übernehmen & buchen/ }).scrollIntoViewIfNeeded();
	await page.keyboard.press("Enter");
	await expect(page.getByText("Zahlung gebucht · SINV-2026-0041 ausgeglichen")).toBeVisible();
});

test("Teilbuchung kann aus Freigegeben einmal erneut ausgeführt werden", async ({ page }) => {
	await page.goto(demo + "&row=r2");
	await suggestion(page).getByRole("button", { name: /Beide übernehmen & buchen/ }).click();
	await expect(page.getByText(/Partei zugeordnet, Buchung fehlgeschlagen/)).toBeVisible();
	await expect(page.locator(".match-head")).toContainText("Erika Beispiel");
	await expect(suggestion(page).getByText("Freigegeben", { exact: true })).toBeVisible();
	await expect(suggestion(page).getByRole("button", { name: /Ablehnen/ })).toHaveCount(0);
	await suggestion(page).getByRole("button", { name: "Buchen", exact: true }).click();
	await expect(page.getByText("Zahlung gebucht · SINV-2026-0052 ausgeglichen")).toBeVisible();
	await expect(table(page).locator(".selected")).toContainText("Stadtwerke Beispielstadt");
});

test("Stale-Antwort zeigt den neuen Zustand und erlaubt eine neue Revision", async ({ page }) => {
	await page.goto(demo + "&row=r6&ki=stale");
	await page.getByRole("button", { name: /KI Vorschlag 6/ }).click();
	await suggestion(page).getByRole("button", { name: /Übernehmen & buchen/ }).click();
	await expect(page.getByText("Vorschlag ist veraltet, nichts gebucht.")).toBeVisible();
	await suggestion(page).getByRole("button", { name: "Neue Revision anfordern" }).click();
	await expect(suggestion(page).getByText("Agent prüft diese Zeile …")).toBeVisible();
	await expect(page.locator(".match-head")).toContainText("Miete Mai");
});

test("Enter bucht die fokussierte Tabellenzeile auch bei zuvor anderer Auswahl", async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 1100 });
	await page.goto(demo);
	const rows = table(page).locator("tbody tr");
	await expect(rows.first()).toHaveClass(/selected/);
	await rows.nth(1).focus();
	await expect(rows.nth(1)).toHaveClass(/selected/);
	await suggestion(page).getByRole("button", { name: /Beide übernehmen & buchen/ }).scrollIntoViewIfNeeded();
	await page.keyboard.press("Enter");
	await expect(page.getByText(/Partei zugeordnet, Buchung fehlgeschlagen/)).toBeVisible();
	await expect(suggestion(page).getByText("Freigegeben", { exact: true })).toBeVisible();
	await expect(rows.first()).toContainText("SINV-2026-0041");
	await expect(rows.first()).not.toContainText("Gebucht");
});

test("Anpassen führt nach manueller Parteizuordnung zur passenden vorausgewählten Rechnung", async ({ page }) => {
	await page.goto(demo + "&row=r2");
	await page.getByRole("button", { name: /KI Vorschlag 6/ }).click();
	await suggestion(page).getByRole("button", { name: "Anpassen" }).click();
	await page.getByRole("button", { name: "Erika Beispiel zuordnen" }).click();
	await expect(table(page).locator(".selected")).toContainText("Erika Beispiel");
	await expect(page.locator(".match-head")).toContainText("Erika Beispiel · Kunde");
	await expect(page.locator(".match-body .seg-btn.active")).toHaveText("Rechnung");
	await expect(page.locator(".match-body .invoice-card").filter({ hasText: "SINV-2026-0052" }).getByRole("checkbox")).toBeChecked();
});

test("kompakte Karte startet geschlossen und Details werden pro Zeile zurückgesetzt", async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(demo);
	const card = suggestion(page).locator(".ki-booking-card");
	const details = suggestion(page).getByRole("button", { name: /^Details/ });
	await expect(details).toHaveAttribute("aria-expanded", "false");
	expect((await card.boundingBox()).height).toBeLessThanOrEqual(320);
	await table(page).locator("tbody tr").nth(1).click();
	await expect(details).toHaveAttribute("aria-expanded", "true");
	await expect(suggestion(page).getByText("Buchung (Vorschau)")).toBeVisible();
	await details.click();
	await expect(details).toHaveAttribute("aria-expanded", "false");
	await table(page).locator("tbody tr").first().click();
	await expect(details).toHaveAttribute("aria-expanded", "false");
	await table(page).locator("tbody tr").nth(1).click();
	await expect(details).toHaveAttribute("aria-expanded", "true");
});

test("bei 1024 px führen Klick, Tastatur und Zeilenlink zum Panel", async ({ page }) => {
	await page.setViewportSize({ width: 1024, height: 640 });
	await page.goto(demo + "&row=r3");
	const panel = page.locator(".match-head");
	await expect(panel).toContainText("Abschlag Strom");
	await expect(panel).toBeInViewport();
	const rows = table(page).locator("tbody tr");
	await rows.first().click();
	await expect(panel).toContainText("Miete April");
	await expect(panel).toBeInViewport();
	await page.keyboard.press("j");
	await expect(panel).toContainText("Ueberweisung");
	await expect(panel).toBeInViewport();
	await page.keyboard.press("k");
	await expect(panel).toContainText("Miete April");
	await expect(panel).toBeInViewport();

	const accept = suggestion(page).getByRole("button", { name: /Übernehmen & buchen/ });
	await page.evaluate(() => window.scrollTo(0, 0));
	await expect(accept).not.toBeInViewport();
	await page.keyboard.press("Enter");
	await expect(accept).toBeInViewport();
	await expect(rows.first()).toHaveClass(/selected/);
	await expect(page.getByText(/Zahlung gebucht.*0041/)).toHaveCount(0);
	await page.keyboard.press("Enter");
	await expect(page.getByText(/Zahlung gebucht.*0041/)).toBeVisible();
});

test("bei 1024 px bleibt die mit Tab fokussierte Tabellenzeile im Bild", async ({ page }) => {
	await page.setViewportSize({ width: 1024, height: 640 });
	await page.goto(demo);
	const rows = table(page).locator("tbody tr");
	await rows.first().getByRole("link").focus();
	await page.keyboard.press("Tab");
	await expect(rows.nth(1)).toBeFocused();
	await expect(rows.nth(1)).toHaveClass(/selected/);
	await expect(rows.nth(1)).toBeInViewport();
	const { y, height } = await rows.nth(1).boundingBox();
	expect(y).toBeGreaterThanOrEqual(0);
	expect(y + height).toBeLessThanOrEqual(640);
	await expect(page.locator(".match-head")).not.toBeInViewport();
});

test("Enter bucht einen sichtbaren Button bei verdeckten Buchungsschritten nicht", async ({ page }) => {
	await page.setViewportSize({ width: 1024, height: 340 });
	await page.goto(demo + "&row=r2");
	const steps = suggestion(page).locator(".ki-steps");
	const accept = suggestion(page).getByRole("button", { name: /Beide übernehmen & buchen/ });
	await accept.scrollIntoViewIfNeeded();
	await expect(accept).toBeInViewport({ ratio: 1 });
	await expect(steps).not.toBeInViewport();
	await page.locator(".match-panel-wrap").evaluate((panel) => panel.focus({ preventScroll: true }));
	await page.keyboard.press("Enter");
	await expect(steps).toBeInViewport({ ratio: 1 });
	await expect(accept).not.toBeInViewport();
	await page.keyboard.press("Enter");
	await expect(accept).toHaveText(/Beide übernehmen & buchen/);
	await expect(page.getByText(/Partei zugeordnet, Buchung fehlgeschlagen/)).toHaveCount(0);
	await accept.click();
	await expect(page.getByText(/Partei zugeordnet, Buchung fehlgeschlagen/)).toBeVisible();
});

test("fordert bei Kein Vorschlag erneut an und zeigt den laufenden Agenten", async ({ page }) => {
	await page.goto(demo + "&row=r8");
	await suggestion(page).getByRole("button", { name: "Erneut anfordern" }).click();
	await expect(suggestion(page)).toContainText("Agent prüft diese Zeile …");
	await expect(table(page).locator(".selected")).toContainText("Agent prüft …");
	await expect(page.locator(".ki-banner")).toContainText("Startet automatisch nach dem CSV-Import · Selbst zuordnen geht jederzeit");
});

test("zeigt bei Angepasst gebucht den tatsächlichen Beleg und die Ablehnung", async ({ page }) => {
	await page.goto(demo + "&ki=states&row=r10");
	await expect(table(page).locator(".selected")).toContainText("Angepasst gebucht");
	await expect(table(page).locator(".selected")).toContainText("PE-2026-0063");
	await expect(suggestion(page).locator("del")).toHaveText("SINV-2026-0041");
	await expect(suggestion(page)).toContainText("Automatisch abgelehnt mit Grund „Angepasst gebucht: PE-2026-0063“");
	await expect(page.getByRole("button", { name: "Beleg lösen" })).toBeVisible();
});
