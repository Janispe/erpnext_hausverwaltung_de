import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

const FRAPPE_USER = process.env.FRAPPE_USER || "Administrator";
const FRAPPE_PASSWORD = process.env.FRAPPE_PASSWORD || "admin";
const FRAPPE_SITE = process.env.FRAPPE_SITE || "frontend";
const FRAPPE_BACKEND_CONTAINER = process.env.FRAPPE_BACKEND_CONTAINER || "hausverwaltung_peters-backend-1";
const FRAPPE_BENCH_DIR = process.env.FRAPPE_BENCH_DIR || "/home/frappe/frappe-bench";

const TODAY = "2026-06-11";
const TEMPLATE = "HV UI Mahnung Vorlage";

const openRows = [
	{
		art: "Forderungen",
		party_type: "Customer",
		party: "CUST-UI-MAHN",
		party_name: "Mieter UI Mahnwesen",
		buchungsdatum: "2026-05-15",
		faellig_am: "2026-06-01",
		belegart: "Sales Invoice",
		belegnummer: "SI-UI-MAHN-0001",
		rechnungsbetrag: 1420.5,
		bezahlt: 0,
		offen: 1420.5,
		kostenstelle: "W65-HP",
		bemerkungen: "Nebenkosten 05/2026 Wasserschaden Treppenhaus",
		status: "Overdue",
		zahlungsrichtung: "Geld bekommen",
		alter_tage: 10,
		can_write_off: true,
		mahnstufe: 1,
	},
	{
		art: "Forderungen",
		party_type: "Customer",
		party: "CUST-UI-MAHN",
		party_name: "Mieter UI Mahnwesen",
		buchungsdatum: "2026-05-20",
		faellig_am: "2026-06-05",
		belegart: "Sales Invoice",
		belegnummer: "SI-UI-MAHN-0002",
		rechnungsbetrag: 279.75,
		bezahlt: 20,
		offen: 259.75,
		kostenstelle: "W65-HP",
		bemerkungen: "Miete 06/2026 Teilzahlung fehlt",
		status: "Partly Paid",
		zahlungsrichtung: "Geld bekommen",
		alter_tage: 6,
		can_write_off: true,
		mahnstufe: 0,
	},
	{
		art: "Forderungen",
		party_type: "Customer",
		party: "CUST-UI-GUT",
		party_name: "Mieter UI Guthaben",
		buchungsdatum: "2026-06-03",
		faellig_am: "2026-06-03",
		belegart: "Sales Invoice",
		belegnummer: "SI-UI-GUTHABEN-0001",
		rechnungsbetrag: -84.3,
		bezahlt: 0,
		offen: -84.3,
		kostenstelle: "P12-HP",
		bemerkungen: "Gutschrift nach Mieterwechsel",
		status: "Credit Note Issued",
		zahlungsrichtung: "Geld bezahlen / erstatten",
		alter_tage: 8,
		can_write_off: false,
		mahnstufe: 0,
	},
	{
		art: "Forderungen",
		party_type: "Customer",
		party: "CUST-UI-PAID",
		party_name: "Mieter UI Ausgeglichen",
		buchungsdatum: "2026-06-01",
		faellig_am: "2026-06-02",
		belegart: "Sales Invoice",
		belegnummer: "SI-UI-PAID-0001",
		rechnungsbetrag: 110,
		bezahlt: 110,
		offen: 0,
		kostenstelle: "W65-HP",
		bemerkungen: "Ausgeglichener Kontrollposten",
		status: "Paid",
		zahlungsrichtung: "Ausgeglichen",
		alter_tage: 9,
		can_write_off: false,
		mahnstufe: 0,
	},
	{
		art: "Forderungen",
		party_type: "Customer",
		party: "CUST-UI-WO",
		party_name: "Mieter UI Abgeschrieben",
		buchungsdatum: "2026-06-01",
		faellig_am: "2026-06-03",
		belegart: "Sales Invoice",
		belegnummer: "SI-UI-WRITEOFF-0001",
		rechnungsbetrag: 310,
		bezahlt: 0,
		offen: 310,
		kostenstelle: "P12-HP",
		bemerkungen: "Abgeschriebener Kontrollposten",
		status: "Written Off",
		zahlungsrichtung: "Geld bekommen",
		alter_tage: 8,
		can_write_off: false,
		mahnstufe: 3,
	},
	{
		art: "Rechnungen",
		party_type: "Supplier",
		party: "SUP-UI-SKONTO",
		party_name: "Lieferant UI Skonto",
		buchungsdatum: "2026-06-04",
		faellig_am: "2026-06-20",
		belegart: "Purchase Invoice",
		belegnummer: "PI-UI-SKONTO-0001",
		rechnungsbetrag: 880,
		bezahlt: 0,
		offen: 880,
		kostenstelle: "W65-HP",
		bemerkungen: "Hausmeisterdienst Skonto bis 15.06. 2%",
		status: "Unpaid",
		zahlungsrichtung: "Geld bezahlen / erstatten",
		alter_tage: -9,
		can_write_off: false,
		mahnstufe: 0,
	},
];

const mahnRows = [
	{
		key: "CUST-UI-MAHN::MV-UI-01",
		customer: "CUST-UI-MAHN",
		customer_name: "Mieter UI Mahnwesen",
		wohnung: "W65-1L",
		mietvertrag: "MV-UI-01",
		offen: 1680.25,
		oldest_due_date: "2026-06-01",
		oldest_age_days: 10,
		next_level: 2,
		next_dunning_type: "1. Mahnung - HP",
		serienbrief_vorlage: TEMPLATE,
		draft_warning: true,
		invoices: [
			{
				sales_invoice: "SI-UI-MAHN-0001",
				posting_date: "2026-05-15",
				due_date: "2026-06-01",
				grand_total: 1420.5,
				outstanding_amount: 1420.5,
				status: "Overdue",
				cost_center: "W65-HP",
				remarks: "Nebenkosten 05/2026 Wasserschaden Treppenhaus",
			},
			{
				sales_invoice: "SI-UI-MAHN-0002",
				posting_date: "2026-05-20",
				due_date: "2026-06-05",
				grand_total: 279.75,
				outstanding_amount: 259.75,
				status: "Partly Paid",
				cost_center: "W65-HP",
				remarks: "Miete 06/2026 Teilzahlung fehlt",
			},
		],
		mahnungen: [
			{
				name: "DUN-UI-DRAFT-0002",
				docstatus: 0,
				status: "Draft",
				dunning_type: "1. Mahnung - HP",
				posting_date: "2026-06-09",
				serienbrief_vorlage: TEMPLATE,
				fee_sales_invoice: "SI-UI-FEE-0002",
			},
			{
				name: "DUN-UI-DRAFT-0001",
				docstatus: 0,
				status: "Draft",
				dunning_type: "Zahlungserinnerung - HP",
				posting_date: "2026-06-08",
				serienbrief_vorlage: TEMPLATE,
				fee_sales_invoice: null,
			},
		],
	},
	{
		key: "CUST-UI-ALT::MV-UI-02",
		customer: "CUST-UI-ALT",
		customer_name: "Mieter UI Ohne Vorlage",
		wohnung: "P12-3R",
		mietvertrag: "MV-UI-02",
		offen: 350,
		oldest_due_date: "2026-06-04",
		oldest_age_days: 7,
		next_level: 1,
		next_dunning_type: "Zahlungserinnerung - HP",
		serienbrief_vorlage: "",
		invoices: [
			{
				sales_invoice: "SI-UI-MAHN-0003",
				posting_date: "2026-05-21",
				due_date: "2026-06-04",
				grand_total: 350,
				outstanding_amount: 350,
				status: "Overdue",
				cost_center: "P12-HP",
				remarks: "Kautionsnachforderung ohne Default-Vorlage",
			},
		],
		mahnungen: [],
	},
];

async function login(page) {
	await page.goto("/app");
	if (!page.url().includes("/login")) return;

	await page.getByRole("textbox", { name: "Email" }).fill(FRAPPE_USER);
	await page.getByRole("textbox", { name: "Password" }).fill(FRAPPE_PASSWORD);
	await page.getByRole("button", { name: "Login" }).click();
	await expect(page).toHaveURL(/\/(app|desk)/);
}

function shellQuote(value) {
	return `'${String(value).replaceAll("'", "'\"'\"'")}'`;
}

function benchExecute(method, { args, kwargs } = {}) {
	const benchCmd = [
		`bench --site ${shellQuote(FRAPPE_SITE)} execute ${method}`,
		args ? `--args ${shellQuote(JSON.stringify(args))}` : "",
		kwargs ? `--kwargs ${shellQuote(JSON.stringify(kwargs))}` : "",
	].filter(Boolean).join(" ");
	const cmd = `cd ${shellQuote(FRAPPE_BENCH_DIR)} && ${benchCmd}`;
	const out = execFileSync("docker", ["exec", FRAPPE_BACKEND_CONTAINER, "sh", "-lc", cmd], {
		encoding: "utf8",
		stdio: ["ignore", "pipe", "pipe"],
	}).trim();
	if (!out) return null;
	try {
		return JSON.parse(out);
	} catch {
		return out;
	}
}

function dunningsForInvoice(salesInvoice) {
	return benchExecute("hausverwaltung.cypress_fixtures.get_dunnings_for_sales_invoice", {
		kwargs: {
			sales_invoice: salesInvoice,
		},
	}) || [];
}

function parseRequestBody(request) {
	const raw = request.postData() || "";
	if (!raw) return {};
	try {
		return JSON.parse(raw);
	} catch {
		return Object.fromEntries(new URLSearchParams(raw));
	}
}

function coerceFrappeValue(value) {
	if (Array.isArray(value)) return value.map(coerceFrappeValue);
	if (value && typeof value === "object") {
		return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, coerceFrappeValue(item)]));
	}
	if (value === "true") return true;
	if (value === "false") return false;
	if (value === "null") return null;
	return value;
}

function requestArgs(body) {
	if (typeof body.args === "string") {
		try {
			return coerceFrappeValue(JSON.parse(body.args));
		} catch {
			return coerceFrappeValue(body);
		}
	}
	if (body.args && typeof body.args === "object") return coerceFrappeValue(body.args);
	const { cmd, ...rest } = body;
	return coerceFrappeValue(rest);
}

async function fulfillJson(route, message, status = 200) {
	await route.fulfill({
		status,
		contentType: "application/json",
		body: JSON.stringify({ message }),
	});
}

async function dismissFrappeModal(page) {
	await page.waitForTimeout(500);
	await page.evaluate(() => {
		document.querySelectorAll(".modal.fade.show, .modal-backdrop").forEach((el) => el.remove());
		document.body.classList.remove("modal-open");
		document.body.style.removeProperty("padding-right");
	});
	await expect(page.locator(".modal.fade.show")).toHaveCount(0);
}

async function installOpWorkflowMocks(page, state) {
	await page.route("**/api/method/**", async (route) => {
		const url = new URL(route.request().url());
		const method = decodeURIComponent(url.pathname.replace(/^\/api\/method\//, ""));
		const body = parseRequestBody(route.request());
		const args = requestArgs(body);

		if (method.endsWith("op_workflow.get_open_items")) {
			state.openItemsCalls.push(args);
			if (state.failNextOpenItems) {
				state.failNextOpenItems = false;
				await route.fulfill({
					status: 500,
					contentType: "application/json",
					body: JSON.stringify({
						exc_type: "ValidationError",
						_server_messages: JSON.stringify([JSON.stringify({ message: "OP UI Test Fehler" })]),
					}),
				});
				return;
			}
			await fulfillJson(route, { columns: [], rows: openRows, today: TODAY });
			return;
		}

		if (method.endsWith("op_workflow.get_mahnkandidaten")) {
			state.mahnCalls.push(args);
			await fulfillJson(route, { rows: mahnRows, today: TODAY });
			return;
		}

		if (method.endsWith("op_workflow.list_dunning_types")) {
			await fulfillJson(route, ["Zahlungserinnerung - HP", "1. Mahnung - HP", "2. Mahnung - HP", "Letzte Mahnung - HP"]);
			return;
		}

		if (method.endsWith("op_workflow.list_serienbrief_vorlagen")) {
			await fulfillJson(route, [TEMPLATE, "HV UI Eskalation Vorlage"]);
			return;
		}

		if (method.includes("get_serienbrief_value_fields") || method.endsWith("op_workflow.get_serienbrief_vorlage_variables")) {
			await fulfillJson(route, {
				template: TEMPLATE,
				fields: [
					{
						key: "ansprechpartner",
						label: "Ansprechpartner",
						variable: "ansprechpartner",
						variable_type: "String",
						optional: false,
						value: "",
						source: "default",
					},
					{
						key: "__path__:objekt.iban",
						label: "objekt.iban",
						variable_type: "String",
						optional: true,
						value: "DE00TEST0000000000",
						kind: "path",
						source: "auto",
					},
				],
			});
			return;
		}

		if (method.endsWith("op_workflow.create_dunning")) {
			state.createdDunnings.push(args);
			await fulfillJson(route, {
				dunning: `DUN-UI-CREATED-${state.createdDunnings.length}`,
				summe: 286.11,
				serienbrief_vorlage: TEMPLATE,
			});
			return;
		}

		if (method.endsWith("op_workflow.create_bulk_dunning")) {
			state.createdBulkDunnings.push(args);
			await fulfillJson(route, {
				created: [{ customer: "CUST-UI-MAHN", dunning: "DUN-UI-BULK-0001", summe: 1685.25 }],
				errors: [],
			});
			return;
		}

		if (method.endsWith("op_workflow.create_payment_entry")) {
			state.createdPayments.push(args);
			await fulfillJson(route, { payment_entry: "PE-UI-SKONTO-0001" });
			return;
		}

		if (method.endsWith("op_workflow.create_refund_payment")) {
			state.createdRefunds.push(args);
			await fulfillJson(route, { payment_entry: "PE-UI-REFUND-0001" });
			return;
		}

		if (method.endsWith("op_workflow.write_off_invoice")) {
			state.writeOffs.push(args);
			await fulfillJson(route, { journal_entry: "JE-UI-WRITEOFF-0001" });
			return;
		}

		if (method.endsWith("op_workflow.set_stundung_comment")) {
			await fulfillJson(route, { ok: true });
			return;
		}

		if (method.includes("frappe.client.get_list") || method.includes("frappe.desk.reportview.get")) {
			await fulfillJson(route, [
				{ name: "W65-HP", cost_center_name: "Warthestr. 65" },
				{ name: "P12-HP", cost_center_name: "Parkstr. 12" },
			]);
			return;
		}

		await route.fallback();
	});
}

test("OP-Workflow deckt komplexe Mahnwesen- und Offene-Posten-UI-Kanten ab", async ({ page }) => {
	const state = {
		openItemsCalls: [],
		mahnCalls: [],
		createdDunnings: [],
		createdBulkDunnings: [],
		createdPayments: [],
		createdRefunds: [],
		writeOffs: [],
		failNextOpenItems: false,
	};
	const pageErrors = [];
	const consoleErrors = [];

	page.on("pageerror", (error) => pageErrors.push(error.message));
	page.on("console", (message) => {
		if (message.type() !== "error") return;
		const text = message.text();
		if (text.includes("op data load failed")) return;
		if (text.includes("Error connecting to socket.io: Invalid origin")) return;
		if (text.includes("Failed to load resource: the server responded with a status of 500")) return;
		consoleErrors.push(text);
	});

	await login(page);
	await installOpWorkflowMocks(page, state);
	await page.goto("/app/op-workflow");

	await expect(page.getByRole("heading", { name: "Noch offene Rechnungen und Forderungen" })).toBeVisible();
	await expect(page.locator(".op-load-state")).toBeHidden();
	await expect(page.getByText("Mieter UI Mahnwesen").first()).toBeVisible();
	await expect(page.getByText("SI-UI-MAHN-0001")).toBeVisible();
	await expect(page.getByText("1.420,50").first()).toBeVisible();
	await expect(page.getByText("Mieter UI Abgeschrieben")).toBeHidden();
	await expect(page.getByText("Mieter UI Ausgeglichen")).toBeHidden();

	await page.getByRole("button", { name: /Beides/ }).click();
	await expect(page.getByText("PI-UI-SKONTO-0001")).toBeVisible();
	await page.locator(".op-search").fill("Wasserschaden");
	await expect(page.getByText("SI-UI-MAHN-0001")).toBeVisible();
	await expect(page.getByText("SI-UI-MAHN-0002")).toBeHidden();
	await page.locator(".op-search").fill("");

	await page.locator(".op-chip", { hasText: "Guthaben" }).click();
	await expect(page.getByText("SI-UI-GUTHABEN-0001")).toBeVisible();
	await page.locator(".op-chip", { hasText: /^Alle / }).first().click();

	await page.locator("label.mk-toggle", { hasText: "Auch ausgeglichene" }).locator("input").check();
	await expect(page.getByText("SI-UI-PAID-0001")).toBeVisible();
	await page.locator("label.mk-toggle", { hasText: "Abgeschriebene" }).locator("input").check();
	await expect(page.getByText("SI-UI-WRITEOFF-0001")).toBeVisible();

	state.failNextOpenItems = true;
	await page.locator('input[type="date"]').first().fill("2026-06-02");
	await expect(page.locator(".op-load-state.is-error")).toContainText(/Offene Posten konnten nicht geladen|OP UI Test Fehler/);
	await dismissFrappeModal(page);
	await page.locator('input[type="date"]').first().fill("2026-06-01");
	await expect(page.locator(".op-load-state.is-error")).toBeHidden();
	await dismissFrappeModal(page);

	await page.locator(".op-view-tab", { hasText: "Mahnwesen" }).click();
	await expect(page.getByRole("heading", { name: "Mahnwesen" })).toBeVisible();
	await expect(page.getByText("2 Kandidaten")).toBeVisible();
	await expect(page.getByText("Mieter UI Mahnwesen").first()).toBeVisible();
	await expect(page.getByText("gesamt 1.680,25")).toBeVisible();

	const candidateRow = page.locator("tr", { hasText: "Mieter UI Mahnwesen" }).first();
	await candidateRow.locator(".op-row-toggle").click();
	await expect(page.getByText("Mehrere offene Drafts")).toBeVisible();
	await expect(page.getByText("DUN-UI-DRAFT-0002")).toBeVisible();
	await expect(page.getByText("SI-UI-MAHN-0002")).toBeVisible();
	await expect(page.getByText("SI-UI-MAHN-0001")).toBeHidden();

	await page.getByRole("button", { name: "Alle Rechnungen" }).click();
	await expect(page.getByText("SI-UI-MAHN-0001")).toBeVisible();
	await expect(candidateRow.getByRole("button", { name: "Drafts prüfen" })).toBeVisible();

	const noTemplateRow = page.locator("tr", { hasText: "Mieter UI Ohne Vorlage" }).first();
	await noTemplateRow.locator(".op-row-toggle").click();
	await page.locator('tr:has-text("Mieter UI Ohne Vorlage") + tr .op-mahn-detail input[type="checkbox"]').first().check();
	await expect(noTemplateRow.getByRole("button", { name: "Mahnung erstellen" })).toBeEnabled();
	await noTemplateRow.getByRole("button", { name: "Mahnung erstellen" }).click();

	await expect(page.getByRole("heading", { name: "Zahlungserinnerung erstellen" })).toBeVisible();
	await expect(page.getByText("Bitte zuerst eine Serienbrief-Vorlage wählen.")).toBeVisible();
	await expect(page.getByRole("button", { name: /Mahnung als Draft anlegen/ })).toBeDisabled();
	await page.locator(".op-field", { hasText: "Serienbrief-Vorlage" }).locator("select").selectOption(TEMPLATE);
	await page.getByRole("button", { name: /Serienbrief-Werte/ }).click();
	await expect(page.getByText("Pflichtwerte fehlen: Ansprechpartner")).toBeVisible();
	await expect(page.getByRole("button", { name: /Mahnung als Draft anlegen/ })).toBeDisabled();
	await page.locator(".op-template-var", { hasText: "Ansprechpartner" }).locator("input").fill("UI Test Sachbearbeitung");
	await expect(page.getByText("Pflichtwerte fehlen: Ansprechpartner")).toBeHidden();
	await page.getByRole("button", { name: /Mahnung als Draft anlegen/ }).click();
	await expect(page.getByText("Mahnung-Draft erstellt: DUN-UI-CREATED-1")).toBeVisible();
	expect(state.createdDunnings).toHaveLength(1);
	expect(state.createdDunnings[0]).toMatchObject({
		sales_invoice: "SI-UI-MAHN-0003",
		dunning_type: "Zahlungserinnerung - HP",
		serienbrief_vorlage: TEMPLATE,
	});
	expect(JSON.stringify(state.createdDunnings[0].serienbrief_werte)).toContain("UI Test Sachbearbeitung");

	await page.locator(".op-view-tab", { hasText: "Offene Posten" }).click();
	await page.getByRole("button", { name: /Rechnungen/ }).click();
	await expect(page.getByText("PI-UI-SKONTO-0001")).toBeVisible();
	await page.getByRole("button", { name: "Zahlung anlegen" }).click();
	await expect(page.getByRole("heading", { name: "Zahlung an Lieferant anlegen" })).toBeVisible();
	await expect(page.getByText("Skonto bis 15.06. nutzen (2%)")).toBeVisible();
	await page.getByRole("button", { name: /Zahlung als Draft anlegen/ }).click();
	await expect(page.getByText("Payment Entry Draft erstellt: PE-UI-SKONTO-0001")).toBeVisible();
	expect(state.createdPayments).toHaveLength(1);
	expect(state.createdPayments[0]).toMatchObject({
		purchase_invoice: "PI-UI-SKONTO-0001",
		use_skonto: true,
		mode_of_payment: "SEPA-Überweisung",
	});

	await page.getByRole("button", { name: /Forderungen/ }).click();
	await page.locator(".op-chip", { hasText: "Guthaben" }).click();
	await page.getByRole("button", { name: "Guthaben auszahlen" }).click();
	await expect(page.getByRole("heading", { name: "Guthaben auszahlen" })).toBeVisible();
	await page.getByRole("button", { name: /Auszahlung als Draft anlegen/ }).click();
	await expect(page.getByText("Auszahlungs-Draft erstellt: PE-UI-REFUND-0001")).toBeVisible();
	expect(state.createdRefunds).toHaveLength(1);
	expect(state.createdRefunds[0]).toMatchObject({ sales_invoice: "SI-UI-GUTHABEN-0001" });

	expect(pageErrors, "keine ungefangenen Page-Errors").toEqual([]);
	expect(consoleErrors, "keine unerwarteten Console-Errors").toEqual([]);
	expect(state.openItemsCalls.length).toBeGreaterThanOrEqual(3);
	expect(state.mahnCalls.length).toBeGreaterThanOrEqual(3);
});

test("OP-Workflow erstellt echte Mahnung als Dunning-Draft in der Datenbank", async ({ page }) => {
	const runId = `${Date.now()}`;
	let fixture = null;

	try {
		benchExecute("hausverwaltung.cypress_fixtures.cleanup_real_op_dunning", {
			kwargs: { run_id: runId },
		});
		fixture = benchExecute("hausverwaltung.cypress_fixtures.seed_real_op_dunning", {
			kwargs: { run_id: runId },
		});

		expect(fixture?.sales_invoice, "Seed Sales Invoice").toBeTruthy();
		expect(fixture?.customer_name, "Seed Customer").toContain(runId);
		expect(dunningsForInvoice(fixture.sales_invoice), "vor UI-Aktion keine Mahnung").toHaveLength(0);

		await login(page);
		await page.goto("/app/op-workflow?view=mahnwesen");
		await expect(page.getByRole("heading", { name: "Mahnwesen" })).toBeVisible();

		await page.locator(".op-search").fill(runId);
		await expect(page.getByText(fixture.customer_name).first()).toBeVisible();

		const candidateRow = page.locator("tr", { hasText: fixture.customer_name }).first();
		await candidateRow.locator(".op-row-toggle").click();
		await expect(page.getByText(fixture.sales_invoice).first()).toBeVisible();
		await page.locator(`tr:has-text("${fixture.customer_name}") + tr .op-mahn-detail input[type="checkbox"]`).first().check();
		await expect(candidateRow.getByRole("button", { name: "Mahnung erstellen" })).toBeEnabled();
		await candidateRow.getByRole("button", { name: "Mahnung erstellen" }).click();

		await expect(page.getByRole("heading", { name: "Zahlungserinnerung erstellen" })).toBeVisible();
		if (!fixture.serienbrief_vorlage) {
			const select = page.locator(".op-field", { hasText: "Serienbrief-Vorlage" }).locator("select");
			await expect(select).toBeVisible();
			await select.selectOption({ index: 1 });
		}
		await page.getByRole("button", { name: /Serienbrief-Werte/ }).click();
		const requiredValue = page.locator(".op-template-var", { hasText: "Ansprechpartner" }).locator("input, textarea").first();
		if (await requiredValue.count()) {
			await requiredValue.fill("Real DB Playwright");
		}
		await expect(page.getByRole("button", { name: /Mahnung als Draft anlegen/ })).toBeEnabled();
		await page.getByRole("button", { name: /Mahnung als Draft anlegen/ }).click();

		await expect(page.getByText(/Mahnung-Draft erstellt:/)).toBeVisible();
		await expect.poll(() => dunningsForInvoice(fixture.sales_invoice).length, {
			message: "Dunning wurde in der DB angelegt",
			timeout: 15000,
		}).toBe(1);

		const [dunning] = dunningsForInvoice(fixture.sales_invoice);
		expect(dunning).toMatchObject({
			docstatus: 0,
			sales_invoice: fixture.sales_invoice,
			customer: fixture.customer,
			dunning_type: fixture.dunning_type,
		});
		expect(Number(dunning.outstanding_amount)).toBeCloseTo(Number(fixture.outstanding_amount), 2);
		if (fixture.serienbrief_vorlage) {
			expect(dunning.hv_serienbrief_vorlage).toBe(fixture.serienbrief_vorlage);
		}
	} finally {
		if (fixture) {
			benchExecute("hausverwaltung.cypress_fixtures.cleanup_real_op_dunning", {
				kwargs: {
					run_id: runId,
					sales_invoice: fixture.sales_invoice,
					customer: fixture.customer,
					template: fixture.serienbrief_vorlage,
				},
			});
		}
	}
});
