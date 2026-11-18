import { readFile } from "node:fs/promises";
import { call, expect, test } from "./frappe.js";

const rpc = "**/api/method/hausverwaltung.hausverwaltung.page.mieterkonto_workflow.mieterkonto_workflow";
const rowsFor = (customer) => [
	{ datum: "2026-05-10", wertstellungsdatum: "2026-01-10", belegart: "Sales Invoice",
		belegnummer: `INV-${customer}-1`, art: "Forderung", beschreibung: 'A; "quoted"', betrag_summe: 12.5, kontostand: 42 },
	{ datum: "2026-04-01", wertstellungsdatum: "2026-04-01", belegart: "Payment Entry",
		belegnummer: `PE-${customer}-2`, art: "Zahlung", beschreibung: "Zahlung", betrag_summe: -29.5, kontostand: 29.5 },
];

function requestArgs(request) {
	return new URLSearchParams(request.postData() || new URL(request.url()).search);
}

async function mount(page, rows = rowsFor) {
	let defer = false;
	let rejectCustomer;
	const pending = [];
	await page.route(`${rpc}.search_mieter*`, (route) => {
		const query = requestArgs(route.request()).get("query") || "";
		return route.fulfill({ json: { message: ["A", "B"].filter((name) => !query || name.includes(query))
			.map((name) => ({ name, customer_id: name })) } });
	});
	await page.route(`${rpc}.get_mieter_stammdaten*`, (route) => {
		const customer = requestArgs(route.request()).get("customer");
		return route.fulfill({ json: { message: { name: customer, customer_id: customer, aufteilung_aktuell: {} } } });
	});
	await page.route(`${rpc}.get_mieterkonto*`, async (route) => {
		const filters = JSON.parse(requestArgs(route.request()).get("filters"));
		const ordered = rows(filters.customer);
		if (filters.sortieren_nach_wertstellungsdatum) {
			ordered.sort((a, b) => b.wertstellungsdatum.localeCompare(a.wertstellungsdatum));
		}
		const reject = () => route.fulfill({ status: 417, json: { exc_type: "ValidationError" } });
		if (filters.customer === rejectCustomer) return reject();
		const resolve = () => route.fulfill({ json: { message: { rows: ordered, summary: [] } } });
		if (defer) {
			await new Promise((done) => pending.push({
				resolve: async () => { await resolve(); done(); },
				reject: async () => { await reject(); done(); },
			}));
			return;
		}
		return resolve();
	});
	await page.goto("/app/mieterkonto-workflow?customer=A");
	await expect(page.locator(".mk-table tbody .col-beleg a")).toHaveCount(rows("A").length);
	return {
		pending,
		deferReports: () => { defer = true; },
		rejectReportsFor: (customer) => { rejectCustomer = customer; },
	};
}

const table = (page) => page.locator(".mk-table");
const csvButton = (page) => page.getByRole("button", { name: "Export CSV" });
const toggleSort = (page) => page.getByLabel("Wertstellung anzeigen/sortieren").click();

async function exportCsv(page) {
	const [download] = await Promise.all([page.waitForEvent("download"), csvButton(page).click()]);
	return { csv: await readFile(await download.path(), "utf8"), filename: download.suggestedFilename() };
}

async function selectCustomer(page, customer) {
	await page.locator(".mk-mieter-search").fill(customer);
	await page.locator(".mk-combobox-option").filter({ hasText: new RegExp(`^${customer}$`) }).click();
}

test("CSV enthält Kundendaten, Vorzeichen, Anführungszeichen und einen leeren unbekannten Saldo", async ({ desk }) => {
	await mount(desk, (customer) => rowsFor(customer).map((row, index) =>
		index === 0 ? { ...row, kontostand: null } : row));
	const { csv, filename } = await exportCsv(desk);
	expect(filename).toMatch(/^A_\d{4}-01-01_\d{4}-\d{2}-\d{2}\.csv$/);
	expect(csv).toContain('"A; ""quoted"""');
	expect(csv).toContain(";-29.5;29.5");
	expect(csv.split(/\r?\n/).find((line) => line.includes("INV-A-1"))).toMatch(/;12\.5;$/);
});

test("Fehlgeschlagener Kundenwechsel exportiert keine alten Daten unter neuem Namen", async ({ desk }) => {
	const reports = await mount(desk);
	reports.rejectReportsFor("B");
	await selectCustomer(desk, "B");
	await expect(csvButton(desk)).toBeDisabled();
	await expect(table(desk)).toContainText("INV-A-1");
	reports.rejectReportsFor(null);
	await selectCustomer(desk, "A");
	expect((await exportCsv(desk)).csv).toContain("INV-A-1");
});

test("CSV-Spalten bleiben während einer ausstehenden Sortierung bei den geladenen Daten", async ({ desk }) => {
	const reports = await mount(desk);
	reports.deferReports();
	await toggleSort(desk);
	await expect(csvButton(desk)).toBeDisabled();
	await expect(table(desk).locator("thead")).not.toContainText("Wertstellung");
	await expect.poll(() => reports.pending.length).toBe(1);
	await reports.pending[0].resolve();
	expect((await exportCsv(desk)).csv.split("\n")[0]).toContain("Wertstellung");
});

const statusRows = () => [
	["Paid", "Forderung"], ["Unpaid", "Forderung"], ["Partly Paid", "Forderung"],
	["Written Off", "Forderung"], [null, "Forderung"], ["Paid", "Zahlung"],
].map(([status, art], index) => ({
	datum: "2026-05-10", wertstellungsdatum: "2026-05-01", belegnummer: `STATUS-${index}`,
	belegart: art === "Forderung" ? "Sales Invoice" : "Payment Entry",
	beschreibung: `Status ${index}`, status, art, offen: index === 1 ? 10 : 0,
	betrag_summe: art === "Forderung" ? 10 : -10, kontostand: 0,
}));

test("Nur bezahlte Rechnungen tragen das Statusmerkmal in allen Mieterkonto-Ansichten", async ({ desk }) => {
	await mount(desk, statusRows);
	for (const tab of [null, "Verlauf", "Dashboard"]) {
		if (tab) await desk.getByRole("button", { name: tab, exact: true }).click();
		const paid = desk.locator(".mk-pill-paid");
		await expect(paid).toHaveText("bezahlt");
		await expect(paid.locator("..")).toContainText("Status 0");
	}
});

test("Klassischer Mieterkonto-Report markiert nur bezahlte Forderungen", async ({ desk }) => {
	const { script } = await call(desk, "frappe.desk.query_report.get_script", { report_name: "Mieterkonto" });
	const [paid, ...other] = await desk.evaluate((script) => {
		frappe.query_reports ||= {};
		window.eval(script);
		const formatter = frappe.query_reports.Mieterkonto.formatter;
		const render = (art, status) => formatter("Miete", null, { fieldname: "beschreibung" },
			{ art, status }, (value) => value);
		return [
			render("Forderung", "Paid"),
			...["Unpaid", "Partly Paid", "Written Off", null].map((status) => render("Forderung", status)),
			render("Zahlung", "Paid"),
		];
	}, script);
	expect(paid).toContain("bezahlt");
	expect(other).toEqual(Array(5).fill("Miete"));
});

const postingRows = () => [
	["2026-05-10", "2026-01-10"], ["2026-05-09", "2025-10-09"], ["2026-05-07", "2026-05-07"],
	["2026-04-30", "2026-01-30"], ["2026-04-01", "2026-04-01"], ["2026-01-01", "2026-01-01"],
].map(([datum, wertstellungsdatum], index) => ({
	datum, wertstellungsdatum, belegart: "Sales Invoice", belegnummer: `TEST-${index}`,
	art: "Forderung", beschreibung: `Buchung ${index}`, betrag_summe: 10, kontostand: 100 - index * 10,
}));
const postingMonths = ["Mai 2026", "April 2026", "Januar 2026"];
const valueMonths = [...postingMonths, "Oktober 2025"];

async function expectMonths(page, months) {
	await expect(page.locator(".mk-month-bar > span:first-child")).toHaveText(months);
	await expect(table(page).locator("tbody .col-beleg a")).toHaveCount(postingRows().length);
}

test("Monatsköpfe wechseln erst mit dem vollständig geladenen Bericht", async ({ desk }) => {
	const reports = await mount(desk, postingRows);
	reports.deferReports();
	await toggleSort(desk);
	await expectMonths(desk, postingMonths);
	await expect.poll(() => reports.pending.length).toBe(1);
	await reports.pending[0].resolve();
	await expectMonths(desk, valueMonths);
	await expect(table(desk).locator("thead")).toContainText("Wertstellung");
	await toggleSort(desk);
	await expectMonths(desk, valueMonths);
	await expect.poll(() => reports.pending.length).toBe(2);
	await reports.pending[1].resolve();
	await expectMonths(desk, postingMonths);
});

test("Monatsreihenfolge bleibt bei Serverfehler erhalten", async ({ desk }) => {
	const reports = await mount(desk, postingRows);
	reports.deferReports();
	await toggleSort(desk);
	await expect.poll(() => reports.pending.length).toBe(1);
	await reports.pending[0].reject();
	await expect(desk.getByText("Mieterkonto-Daten werden geladen")).toBeHidden();
	await expectMonths(desk, postingMonths);
	await expect(table(desk).locator("thead")).not.toContainText("Wertstellung");
});

test("Überholte Antwort nach schnellem Zurückschalten ändert keine Monatsreihenfolge", async ({ desk }) => {
	const reports = await mount(desk, postingRows);
	await desk.evaluate(() => {
		const adapter = window.MK_ADAPTER;
		const load = adapter.load;
		adapter.load = async (...args) => {
			const result = await load.apply(adapter, args);
			if (args[3].sortByWertstellung) {
				// Let the awaiting UI consume the result and commit any React update.
				requestAnimationFrame(() => requestAnimationFrame(() => {
					document.documentElement.dataset.staleReportProcessed = "true";
				}));
			}
			return result;
		};
	});
	reports.deferReports();
	await toggleSort(desk);
	await expect.poll(() => reports.pending.length).toBe(1);
	await toggleSort(desk);
	await expect.poll(() => reports.pending.length).toBe(2);
	await reports.pending[1].resolve();
	await expect(csvButton(desk)).toBeEnabled();
	await reports.pending[0].resolve();
	await expect(desk.locator("html")).toHaveAttribute("data-stale-report-processed", "true");
	await expectMonths(desk, postingMonths);
	await expect(table(desk).locator("thead")).not.toContainText("Wertstellung");
});
