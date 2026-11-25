import { expect, test, benchExecute, openForm, visiblePage } from "./frappe.js";

const fixture = "hausverwaltung.hausverwaltung.test_wohnungsabnahme.seed_mobile_test";
const photo = Buffer.from(
	"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAFCAIAAAD38zoCAAAAEUlEQVR4nGMwdgnFihjoIAEAw8Yf4Rhd924AAAAASUVORK5CYII=",
	"base64",
);

test("Wohnungsabnahme mobil erfassen, fortsetzen und als privates PDF öffnen", async ({ desk, playwright, baseURL }) => {
	const { old, new: incoming, prozess, day } = benchExecute(fixture);
	await openForm(desk, "Prozess Instanz", prozess);
	await visiblePage(desk).getByRole("button", { name: "Wohnungsabnahme" }).click();
	await expect(desk.getByText("Auszug", { exact: true }).filter({ visible: true })).toBeVisible();
	await desk.getByText("Einzug", { exact: true }).filter({ visible: true }).click();
	await desk.waitForURL("**/wohnungsabnahme?*");
	await expect(desk.getByRole("heading", { name: "Wohnungsabnahme · Einzug" })).toBeVisible();
	await expect(desk.getByText("Mietvertrag " + incoming, { exact: false })).toBeVisible();
	await desk.getByRole("link", { name: /Zurück zur Hausverwaltung/ }).click();
	await desk.waitForFunction(() => window.frappe?.csrf_token && window.frappe?.set_route);
	await openForm(desk, "Mietvertrag", old);
	await visiblePage(desk).getByRole("button", { name: "Wohnungsabnahme" }).click();
	await desk.getByText("Auszug", { exact: true }).filter({ visible: true }).click();
	await desk.waitForURL("**/wohnungsabnahme?*");
	await desk.setViewportSize({ width: 390, height: 844 });
	await expect(desk.getByRole("heading", { name: "Wohnungsabnahme · Auszug" })).toBeVisible();
	await expect(desk.getByText("Mietvertrag " + old, { exact: false })).toBeVisible();

	await desk.getByLabel("Abnahmedatum").fill(day);
	await desk.getByRole("button", { name: "Raum hinzufügen" }).click();
	await desk.getByLabel("Raum", { exact: true }).fill("Flur");
	await desk.getByLabel("Zustand", { exact: true }).fill("Besenrein");
	await desk.getByLabel("Mängel").fill("Kratzer an der Tür");
	await desk.getByLabel("Raumfoto aufnehmen oder auswählen").setInputFiles({
		name: "flur.png", mimeType: "image/png", buffer: photo,
	});
	await expect(desk.getByRole("status")).toContainText("Entwurf und Foto gespeichert.");
	await desk.getByRole("button", { name: "Schlüsselart hinzufügen" }).click();
	await desk.getByLabel("Schlüsselart").fill("Haustür");
	await desk.getByLabel("Anzahl").fill("2");
	await desk.getByLabel("Ablesedatum").fill(day);
	await desk.getByLabel("Zählerstand").fill("123,45");
	await desk.getByRole("button", { name: "Entwurf speichern" }).click();
	await expect(desk.getByRole("status")).toHaveText("Entwurf gespeichert.");

	await desk.reload();
	await expect(desk.getByRole("status")).toHaveText("Gespeicherter Entwurf");
	await expect(desk.getByLabel("Raum", { exact: true })).toHaveValue("Flur");
	await expect(desk.getByLabel("Zählerstand")).toHaveValue("123.45");
	const image = desk.getByRole("img", { name: "Raumfoto" });
	await expect(image).toBeVisible();
	const imageUrl = await image.getAttribute("src");
	expect(imageUrl).toMatch(/^\/private\/files\//);
	expect(await desk.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

	await desk.getByRole("button", { name: "Abschließen und PDF erstellen" }).click();
	const pdf = desk.getByRole("link", { name: "Protokoll-PDF öffnen" });
	await expect(pdf).toBeVisible({ timeout: 30_000 });
	const url = await pdf.getAttribute("href");
	const download = await desk.request.get(url);
	expect(download.ok(), await download.text().then((body) => body.slice(0, 80))).toBe(true);
	expect((await download.body()).subarray(0, 4).toString()).toBe("%PDF");
	await expect(desk.getByRole("button", { name: "Entwurf speichern" })).toBeHidden();

	const guest = await playwright.request.newContext({ baseURL });
	try {
		for (const privateUrl of [imageUrl, url]) {
			const response = await guest.get(privateUrl, { maxRedirects: 0 });
			expect(response.ok()).toBe(false);
		}
	} finally {
		await guest.dispose();
	}
});
