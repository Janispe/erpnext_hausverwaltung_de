import { expect, test } from "@playwright/test";

async function openDemoImport(page) {
	await page.goto("/?import=BAI-1812-DEMO-0001");
	await expect(page.locator(".value", { hasText: "Wilhelmshavener (1812)" })).toBeVisible();
	await expect(page.getByRole("table")).toBeVisible();
}

test("Import-Picker filtert offene/abgeschlossene Importe und legt per CSV einen neuen Import an", async ({ page }) => {
	await page.goto("/");

	await expect(page.getByRole("heading", { name: "Bankauszug-Import wählen" })).toBeVisible();
	await expect(page.getByText("Wilhelmshavener (1812)")).toBeVisible();
	await expect(page.getByText("Sparkasse (1804)")).not.toBeVisible();

	await page.getByRole("button", { name: /Abgeschlossen 1/ }).click();
	await expect(page.getByText("Sparkasse (1804)")).toBeVisible();
	await expect(page.getByText("Wilhelmshavener (1812)")).not.toBeVisible();

	await page.getByPlaceholder("Import, Objekt, Zeitraum oder Status suchen...").fill("kein treffer");
	await expect(page.getByText("Keine Importe für diese Auswahl.")).toBeVisible();

	await page.getByRole("button", { name: "Neuer Import" }).click();
	await expect(page.getByRole("heading", { name: "Neuer Bankimport" })).toBeVisible();
	await page.getByLabel("Bankkonto").selectOption("Demo Bankkonto - Postbank");
	await page.getByLabel("CSV-Datei").setInputFiles({
		name: "kontoauszug-randfall.csv",
		mimeType: "text/csv",
		buffer: Buffer.from("Datum;Betrag;Text\n2026-04-01;1,23;Test\n"),
	});
	await page.getByRole("button", { name: /Importieren/ }).click();

	await expect(page.getByText("Bankauszug importiert.")).toBeVisible();
	await expect(page.getByText("Phase 3: 4/6 Belege zugeordnet")).toBeVisible();
});

test("komplexer Rechnungsflow validiert Ueberzahlung, Teilzahlung und Buchung", async ({ page }) => {
	await openDemoImport(page);

	await expect(page.locator(".invoice-card .doc-id", { hasText: "SINV-2026-0041" })).toBeVisible();
	await page.locator(".invoice-card").filter({ hasText: "SINV-2026-0041" }).getByRole("checkbox").check();
	await page.locator(".invoice-card").filter({ hasText: "SINV-2026-0038" }).getByRole("checkbox").check();
	await expect(page.getByText("Rest −360,00 €")).toBeVisible();

	await page.getByRole("button", { name: /Zuordnen & buchen/ }).click();
	await expect(page.getByText("Die Zuweisung übersteigt den Bankbetrag.")).toBeVisible();

	await page.locator(".invoice-card").filter({ hasText: "SINV-2026-0038" }).getByRole("checkbox").uncheck();
	await expect(page.getByText("Rest 0,00 €")).toBeVisible();
	await page.getByRole("button", { name: /Zuordnen & buchen/ }).click();
	await expect(page.getByText("Zahlung gebucht und Bank Transaction abgeglichen.")).toBeVisible();
});

test("Phase- und Suchfilter halten Detailauswahl konsistent und erlauben Partei-Zuordnung", async ({ page }) => {
	await openDemoImport(page);

	await page.getByRole("button", { name: /Parteien zuordnen/ }).click();
	await expect(page.getByText("Phase 1 · Alle Zeilen")).toBeVisible();
	await expect(page.getByRole("row", { name: /Erika Beispiel/ })).toBeVisible();
	await expect(page.getByText("Partei zuordnen")).toBeVisible();

	await page.getByPlaceholder("Verwendungszweck, Auftraggeber, IBAN…").fill("does-not-exist");
	await expect(page.getByText("Keine Zeilen in diesem Filter")).toBeVisible();
	await expect(page.getByText("Keine Zeile ausgewählt")).toBeVisible();

	await page.getByPlaceholder("Verwendungszweck, Auftraggeber, IBAN…").fill("Erika");
	await expect(page.getByRole("row", { name: /Erika Beispiel/ })).toBeVisible();
	await expect(page.getByText("Partei zuordnen")).toBeVisible();

	await page.getByPlaceholder("Mieter suchen…").fill("Erika");
	await expect(page.locator(".link-search-item", { hasText: "Erika Beispiel" })).toBeVisible();
	await page.locator(".link-search-item", { hasText: "Erika Beispiel" }).click();
	await expect(page.getByText("Partei zugeordnet: Erika Beispiel.")).toBeVisible();
});

test("globale Bank-Transaktion-Aktion fragt bei fehlender Partei nach und respektiert Abbruch", async ({ page }) => {
	await openDemoImport(page);

	page.once("dialog", async (dialog) => {
		expect(dialog.message()).toContain("Zeilen ohne Partei");
		await dialog.dismiss();
	});
	await page.getByRole("button", { name: /Bank-Transaktionen erstellen/ }).click();

	await expect(page.getByText("Bank-Transaktionen erstellt")).not.toBeVisible();
	await expect(page.getByRole("button", { name: /Bank-Transaktionen erstellen/ })).toBeEnabled();
});
