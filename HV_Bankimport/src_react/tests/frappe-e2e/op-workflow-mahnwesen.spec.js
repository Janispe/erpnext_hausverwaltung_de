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

	await page.locator("#login_email").fill(FRAPPE_USER);
	await page.locator("#login_password").fill(FRAPPE_PASSWORD);
	await page.getByRole("button", { name: /^(Login|Continue|Anmelden)$/ }).click();
	await expect(page).toHaveURL(/\/(app|desk)/);
}

function shellQuote(value) {
	return `'${String(value).replaceAll("'", "'\"'\"'")}'`;
}

function benchExecute(method, { args, kwargs } = {}) {
	const benchCmd = [
		`bench --site ${shellQuote(FRAPPE_SITE)} execute ${shellQuote(method)}`,
		args ? `--args ${shellQuote(JSON.stringify(args))}` : "",
		kwargs ? `--kwargs ${shellQuote(JSON.stringify(kwargs))}` : "",
	].filter(Boolean).join(" ");
	const cmd = `cd ${shellQuote(FRAPPE_BENCH_DIR)} && ${benchCmd}`;
	let out;
	try {
		out = execFileSync("docker", ["exec", FRAPPE_BACKEND_CONTAINER, "sh", "-lc", cmd], {
			encoding: "utf8",
			stdio: ["ignore", "pipe", "pipe"],
		}).trim();
	} catch (error) {
		throw new Error(`${error.message}\n${error.stderr || error.stdout || ""}`);
	}
	if (!out) return null;
	try {
		return JSON.parse(out);
	} catch {
		return out;
	}
}

function benchPython(script) {
	return benchExecute("__import__('builtins').exec", { args: [script, {}] });
}

function seedRealDunning(runId) {
	// Adapt the legacy fixture to current ERPNext autonaming and the 1:1 lease
	// invariant. These replacements are scoped to this one bench process.
	return benchPython(`import frappe, json
import hausverwaltung.cypress_fixtures as fixtures
run_id = ${JSON.stringify(runId)}
extra = {}
def own_customer(_run_id):
    contact = frappe.get_doc({"doctype":"Contact", "first_name":"HV UI", "last_name":"Mahnwesen Real " + run_id}).insert(ignore_permissions=True)
    apartment = frappe.get_doc({"doctype":"Wohnung", "name__lage_in_der_immobilie":"HV UI Mahnung " + run_id, "status":"Leerstehend"}).insert(ignore_permissions=True)
    lease = frappe.get_doc({"doctype":"Mietvertrag", "wohnung":apartment.name, "von":"2026-05-01", "vertragsabschluss_am":"2026-04-01", "mieter":[{"mieter":contact.name,"rolle":"Hauptmieter","eingezogen":"2026-05-01"}], "miete":[{"von":"2026-05-01","miete":123.45,"art":"Monatlich"}]}).insert(ignore_permissions=True)
    extra.update({"mietvertrag":lease.name,"wohnung":apartment.name,"contact":contact.name})
    return lease.kunde
def current_dunning_type(company, income_account, cost_center, template):
    actual_name = frappe.db.get_value("Dunning Type", {"dunning_type":"Zahlungserinnerung - HP", "company":company}, "name")
    if actual_name:
        doc = frappe.get_doc("Dunning Type", actual_name)
        extra["original_template"] = doc.hv_serienbrief_vorlage
        extra["type_was_created"] = False
    else:
        doc = frappe.get_doc({"doctype":"Dunning Type","dunning_type":"Zahlungserinnerung - HP","company":company,"dunning_fee":0,"rate_of_interest":0,"income_account":income_account,"cost_center":cost_center})
        extra["original_template"] = None
        extra["type_was_created"] = True
    doc.hv_serienbrief_vorlage = template
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return doc.name
fixtures._ensure_test_customer = own_customer
fixtures._ensure_dunning_type = current_dunning_type
result = fixtures.seed_real_op_dunning(run_id)
invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
invoice.db_set("remarks", "HV UI Mahnwesen Real " + run_id + " MV:" + extra["mietvertrag"])
if invoice.meta.has_field("wohnung"):
    invoice.db_set("wohnung", extra["wohnung"])
frappe.db.commit()
result.update(extra)
print(json.dumps(result, default=str))`);
}

function cleanupRealDunning(fixture) {
	return benchPython(`import frappe, json
import hausverwaltung.cypress_fixtures as fixtures
fixture = json.loads(${JSON.stringify(JSON.stringify(fixture))})
if frappe.db.exists("Dunning Type", fixture["dunning_type"]):
    frappe.db.set_value("Dunning Type", fixture["dunning_type"], "hv_serienbrief_vorlage", fixture.get("original_template"))
result = fixtures.cleanup_real_op_dunning(fixture["run_id"], sales_invoice=fixture["sales_invoice"], template=fixture.get("serienbrief_vorlage"))
for doctype, key in [("Mietvertrag","mietvertrag"),("Customer","customer"),("Wohnung","wohnung"),("Contact","contact")]:
    if frappe.db.exists(doctype, fixture[key]):
        frappe.delete_doc(doctype, fixture[key], force=True, ignore_permissions=True)
if fixture.get("type_was_created"):
    frappe.delete_doc("Dunning Type", fixture["dunning_type"], force=True, ignore_permissions=True)
frappe.db.commit()
print(json.dumps(result, default=str))`);
}

function readDunningInvariant(fixture) {
	return benchPython(`import frappe, json
fixture = json.loads(${JSON.stringify(JSON.stringify(fixture))})
leases = frappe.get_all("Mietvertrag", filters={"kunde":fixture["customer"]}, fields=["name","kunde","wohnung","von","bis"])
invoice = frappe.db.get_value("Sales Invoice", fixture["sales_invoice"], ["name","customer","grand_total","outstanding_amount","docstatus","remarks"], as_dict=True)
print(json.dumps({"leases":leases,"invoice":invoice},default=str))`);
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
	if (!raw) return Object.fromEntries(new URL(request.url()).searchParams);
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
			await fulfillJson(route, { columns: [], rows: state.openRows || openRows, today: TODAY });
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

		if (method.endsWith("mahnung_workflow.get_dunning_context")) {
			const party = args.party || "CUST-UI-ALT";
			const row = mahnRows.find((item) => item.customer === party) || mahnRows[0];
			await fulfillJson(route, {
				today: TODAY,
				basiszins: 1.27,
				absender: {
					firma: "Hausverwaltung Peters",
					telefon: "",
					email: "",
					iban: "DE00TEST0000000000",
					konto_erloese_mahn: "8950 — Mahngebühren-Erlöse",
				},
				mieter: [{
					id: party,
					name: row.customer_name,
					anrede: "Sehr geehrte Damen und Herren,",
					adresse: [row.customer_name],
					objekt: row.wohnung || "",
					einheit: "",
					kostenstelle: row.kostenstelle || "",
					email: "",
					verbrauchertyp: "privat",
					mahnstufe: row.mahnstufe || 0,
					empf_vorlage: "zahlungserinnerung_hp",
					historie: [],
					posten: (row.invoices || []).map((invoice) => ({
						beleg: invoice.sales_invoice,
						art: "Sales Invoice",
						bez: invoice.remarks || "Mietabrechnung",
						posting: invoice.posting_date,
						faellig: invoice.due_date,
						betrag: invoice.grand_total,
						bezahlt: invoice.grand_total - invoice.outstanding_amount,
						offen: invoice.outstanding_amount,
						overdue_days: invoice.age_days || 1,
					})),
				}],
				vorlagen: [{
					key: "zahlungserinnerung_hp",
					tpl_id: TEMPLATE,
					dunning_type: "Zahlungserinnerung - HP",
					serienbrief_vorlage: TEMPLATE,
					label: "Zahlungserinnerung - HP",
					kategorie: "Mahnungen",
					stufe_nr: 0,
					ton: "sachlich",
					gebuehr: 0,
					zinsen: false,
					variablen: [
						{ name: "frist_tage", type: "Zahl", default: "7", desc: "Zahlungsfrist in Tagen" },
						{ name: "kontonummer", type: "String", default: "DE00TEST0000000000", desc: "Empfänger-IBAN" },
						{ name: "ansprechpartner", type: "String", default: "UI Test Sachbearbeitung", desc: "Ansprechpartner" },
					],
					betreff: "Zahlungserinnerung — Objekt {objekt}",
					einleitung: "bitte gleichen Sie die unten aufgeführten offenen Forderungen bis zum {frist} aus.",
					schluss: "Sollten Sie die Zahlung zwischenzeitlich veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.",
				}],
			});
			return;
		}

		if (method.endsWith("mahnung_workflow.create_dunning")) {
			state.createdDunnings.push(args);
			await fulfillJson(route, {
				dunning: `DUN-UI-CREATED-${state.createdDunnings.length}`,
				summe: 286.11,
				draft: true,
				docstatus: 0,
				docs: [{ id: `DUN-UI-CREATED-${state.createdDunnings.length}`, desc: "Dunning-Draft · Zahlungserinnerung - HP", amount: 286.11 }],
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
			if (args.doctype === "Account") {
				await fulfillJson(route, [{ name: "1200 UI Bank - HP", account_type: "Bank", account_currency: "EUR" }]);
				return;
			}
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
	// The fixture dates and the initial month filter must refer to the same day.
	// setFixedTime leaves timers running (unlike a paused virtual clock).
	await page.clock.setFixedTime(new Date(`${TODAY}T12:00:00Z`));
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
		if (text.includes("Failed to load resource: the server responded with a status of 400")) return;
		if (text.includes("Failed to load resource: the server responded with a status of 500")) return;
		consoleErrors.push(text);
	});

	await login(page);
	await installOpWorkflowMocks(page, state);
	await page.goto("/app/op-workflow");

	await expect(page.getByRole("heading", { name: "Noch offene Rechnungen und Forderungen" })).toBeVisible();
	await expect(page.locator(".op-load-state")).toBeHidden();
	await page.evaluate(() => window.OP_ADAPTER.refresh({ company: "HV Bugtest" }));
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
	await page.getByRole("textbox", { name: "Fälligkeit von", exact: true }).fill("02.06.2026");
	await page.getByRole("textbox", { name: "Fälligkeit von", exact: true }).press("Tab");
	await expect(page.locator(".op-load-state.is-error")).toContainText(/Offene Posten konnten nicht geladen|OP UI Test Fehler/);
	await dismissFrappeModal(page);
	await page.getByRole("textbox", { name: "Fälligkeit von", exact: true }).fill("01.06.2026");
	await page.getByRole("textbox", { name: "Fälligkeit von", exact: true }).press("Tab");
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

	await expect(page).toHaveURL(/mahnung-workflow/);
	await expect(page.getByRole("heading", { name: "Mahnung erstellen" })).toBeVisible();
	await expect(page.locator(".mh-tenant-select")).toHaveValue("CUST-UI-ALT");
	await expect(page.getByText("SI-UI-MAHN-0003").first()).toBeVisible();
	await page.getByRole("button", { name: "Als Draft speichern" }).click();
	await expect(page.getByRole("heading", { name: "Mahnung-Draft erstellt" })).toBeVisible();
	expect(state.createdDunnings).toHaveLength(1);
	expect(state.createdDunnings[0]).toMatchObject({
		dunning_type: "Zahlungserinnerung - HP",
		serienbrief_vorlage: TEMPLATE,
	});
	expect(JSON.stringify(state.createdDunnings[0].sales_invoices)).toContain("SI-UI-MAHN-0003");
	expect(JSON.stringify(state.createdDunnings[0].serienbrief_werte)).toContain("UI Test Sachbearbeitung");

	await page.goto("/app/op-workflow");
	await expect(page.getByRole("heading", { name: "Noch offene Rechnungen und Forderungen" })).toBeVisible();
	await page.evaluate(() => window.OP_ADAPTER.refresh({ company: "HV Bugtest" }));
	await page.getByRole("button", { name: /Rechnungen/ }).click();
	await expect(page.getByText("PI-UI-SKONTO-0001")).toBeVisible();
	await page.getByRole("button", { name: "Zahlung anlegen" }).click();
	await expect(page.getByRole("heading", { name: "Zahlung an Lieferant anlegen" })).toBeVisible();
	await expect(page.getByText("Skonto bis 15.06. nutzen (2%)")).toBeVisible();
	await expect(page.getByRole("button", { name: /Zahlung als Draft anlegen/ })).toBeDisabled();
	await page.getByPlaceholder("z. B. Überweisungs-ID").fill("UI-SKONTO-REFERENZ");
	await page.getByRole("button", { name: /Zahlung als Draft anlegen/ }).click();
	await expect(page.getByText("Payment Entry PE-UI-SKONTO-0001 als Draft erstellt")).toBeVisible();
	expect(state.createdPayments).toHaveLength(1);
	expect(state.createdPayments[0]).toMatchObject({
		purchase_invoice: "PI-UI-SKONTO-0001",
		use_skonto: true,
		posting_date: TODAY,
		mode_of_payment: "Bank Draft",
		bank_account: "1200 UI Bank - HP",
		reference_no: "UI-SKONTO-REFERENZ",
		reference_date: TODAY,
	});
	expect(Number(state.createdPayments[0].skonto_amount)).toBe(17.6);

	await page.getByRole("button", { name: /Forderungen/ }).click();
	await page.locator(".op-chip", { hasText: "Guthaben" }).click();
	await page.getByRole("button", { name: "Guthaben auszahlen" }).click();
	await expect(page.getByRole("heading", { name: "Guthaben auszahlen" })).toBeVisible();
	await expect(page.getByRole("button", { name: /Auszahlung als Draft anlegen/ })).toBeDisabled();
	await page.getByPlaceholder("z. B. Überweisungs-ID").fill("UI-ERSTATTUNG-REFERENZ");
	await page.getByRole("button", { name: /Auszahlung als Draft anlegen/ }).click();
	await expect(page.getByText("Auszahlungs-Draft erstellt: PE-UI-REFUND-0001")).toBeVisible();
	expect(state.createdRefunds).toHaveLength(1);
	expect(state.createdRefunds[0]).toMatchObject({
		sales_invoice: "SI-UI-GUTHABEN-0001",
		mode_of_payment: "Bank Draft",
		bank_account: "1200 UI Bank - HP",
		reference_no: "UI-ERSTATTUNG-REFERENZ",
		reference_date: TODAY,
	});

	expect(pageErrors, "keine ungefangenen Page-Errors").toEqual([]);
	expect(consoleErrors, "keine unerwarteten Console-Errors").toEqual([]);
	expect(state.openItemsCalls.length).toBeGreaterThanOrEqual(3);
	expect(state.mahnCalls.length).toBeGreaterThanOrEqual(3);
});

test("OP-Skonto-Vorschau erhält die Rechnungs-Cents bei halben Centbeträgen", async ({ page }, testInfo) => {
	await page.clock.setFixedTime(new Date(`${TODAY}T12:00:00Z`));
	const state = {
		openItemsCalls: [], mahnCalls: [], createdDunnings: [], createdBulkDunnings: [],
		createdPayments: [], createdRefunds: [], writeOffs: [], failNextOpenItems: false,
		openRows: openRows.map((row) => row.belegart === "Purchase Invoice"
			? { ...row, offen: 880.25, rechnungsbetrag: 880.25 } : row),
	};
	await login(page);
	await installOpWorkflowMocks(page, state);
	await page.goto("/app/op-workflow");
	await expect(page.getByRole("heading", { name: "Noch offene Rechnungen und Forderungen" })).toBeVisible();
	await page.evaluate(() => window.OP_ADAPTER.refresh({ company: "HV Bugtest" }));
	await page.getByRole("button", { name: /Rechnungen/ }).click();
	await page.getByRole("button", { name: "Zahlung anlegen" }).click();
	await expect(page.getByRole("heading", { name: "Zahlung an Lieferant anlegen" })).toBeVisible();
	const texts = await page.locator(".op-preview-row .op-preview-val").allTextContents();
	const amounts = texts.map((value) => Number(value.replace(/[\s€−]/g, "").replaceAll(".", "").replace(",", ".")));
	await page.screenshot({ path: testInfo.outputPath("skonto-preview.png") });
	await page.getByPlaceholder("z. B. Überweisungs-ID").fill("UI-HALBCENT-SKONTO");
	await page.getByRole("button", { name: /Zahlung als Draft anlegen/ }).click();
	expect(state.createdPayments).toHaveLength(1);
	await testInfo.attach("skonto-cent-readback", {
		body: Buffer.from(JSON.stringify({ texts, amounts, rpc: state.createdPayments[0] }, null, 2)),
		contentType: "application/json",
	});
	expect(amounts).toHaveLength(3);
	expect(Math.round((amounts[1] + amounts[2]) * 100), "angezeigter Skonto + Auszahlung = Rechnungsbetrag").toBe(Math.round(amounts[0] * 100));
	expect(Number(state.createdPayments[0].skonto_amount), "RPC-Skonto entspricht angezeigtem Centbetrag").toBe(amounts[1]);
});

test("OP-Workflow erstellt echte Mahnung als Dunning-Draft in der Datenbank", async ({ page }, testInfo) => {
	const runId = `${Date.now()}`;
	let fixture = null;

	try {
		benchExecute("hausverwaltung.cypress_fixtures.cleanup_real_op_dunning", {
			kwargs: { run_id: runId },
		});
		fixture = seedRealDunning(runId);

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

		await expect(page).toHaveURL(/mahnung-workflow/);
		await expect(page.getByRole("heading", { name: "Mahnung erstellen" })).toBeVisible();
		await expect(page.locator(".mh-tenant-select")).toHaveValue(fixture.customer);
		await expect(page.getByText(fixture.sales_invoice).first()).toBeVisible();
		await page.getByRole("button", { name: "Als Draft speichern" }).click();

		await expect(page.getByRole("heading", { name: "Mahnung-Draft erstellt" })).toBeVisible();
		await expect.poll(() => dunningsForInvoice(fixture.sales_invoice).length, {
			message: "Dunning wurde in der DB angelegt",
			timeout: 15000,
		}).toBe(1);

		const [dunning] = dunningsForInvoice(fixture.sales_invoice);
		const invariant = readDunningInvariant(fixture);
		await testInfo.attach("database-readback", { body: Buffer.from(JSON.stringify({ fixture, dunning, invariant }, null, 2)), contentType: "application/json" });
		expect(invariant.leases).toEqual([expect.objectContaining({ name: fixture.mietvertrag, kunde: fixture.customer, wohnung: fixture.wohnung })]);
		expect(Number(invariant.invoice.grand_total)).toBe(123.45);
		expect(Number(invariant.invoice.outstanding_amount)).toBe(123.45);
		expect(invariant.invoice.customer).toBe(fixture.customer);
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
			cleanupRealDunning(fixture);
		}
	}
});

test("Geführter Mahnungsworkflow erstellt echten Dunning-Draft in der Datenbank", async ({ page }, testInfo) => {
	const runId = `${Date.now()}`;
	let fixture = null;

	try {
		benchExecute("hausverwaltung.cypress_fixtures.cleanup_real_op_dunning", {
			kwargs: { run_id: runId },
		});
		fixture = seedRealDunning(runId);

		expect(fixture?.sales_invoice, "Seed Sales Invoice").toBeTruthy();
		expect(dunningsForInvoice(fixture.sales_invoice), "vor UI-Aktion keine Mahnung").toHaveLength(0);

		await login(page);
		await page.goto(`/app/mahnung-workflow?party=${encodeURIComponent(fixture.customer)}&invoices=${encodeURIComponent(fixture.sales_invoice)}`);
		await expect(page.getByRole("heading", { name: "Mahnung erstellen" })).toBeVisible();
		await expect(page.locator(".mh-tenant-select")).toHaveValue(fixture.customer);
		await expect(page.getByText(fixture.sales_invoice).first()).toBeVisible();

		await page.getByRole("button", { name: "Als Draft speichern" }).click();
		await expect(page.getByRole("heading", { name: "Mahnung-Draft erstellt" })).toBeVisible();
		await expect.poll(() => dunningsForInvoice(fixture.sales_invoice).length, {
			message: "Dunning wurde in der DB angelegt",
			timeout: 15000,
		}).toBe(1);

		const [dunning] = dunningsForInvoice(fixture.sales_invoice);
		const invariant = readDunningInvariant(fixture);
		await testInfo.attach("database-readback", { body: Buffer.from(JSON.stringify({ fixture, dunning, invariant }, null, 2)), contentType: "application/json" });
		expect(invariant.leases).toEqual([expect.objectContaining({ name: fixture.mietvertrag, kunde: fixture.customer, wohnung: fixture.wohnung })]);
		expect(Number(invariant.invoice.grand_total)).toBe(123.45);
		expect(Number(invariant.invoice.outstanding_amount)).toBe(123.45);
		expect(invariant.invoice.customer).toBe(fixture.customer);
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
			cleanupRealDunning(fixture);
		}
	}
});
