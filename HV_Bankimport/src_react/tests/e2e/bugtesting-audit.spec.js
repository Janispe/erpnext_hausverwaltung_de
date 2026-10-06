import { expect, test } from "@playwright/test";

// Accounting safety UI audit. All RPCs terminate in an in-browser fake host;
// no Frappe API, production site, or actual ledger can be changed by this spec.
const ASSETS = "/assets/hausverwaltung/bankimport_v2/";

async function openHost(page, options = {}) {
	await page.route("**/bugtesting-host", (route) => route.fulfill({
		contentType: "text/html",
		body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}iframe{border:0;width:100%;height:100vh;display:block}</style></head><body><iframe title="Audit Bankimport"></iframe><script type="module">
		import { MOCK_OVERVIEW, MOCK_OPEN_INVOICES } from "${ASSETS}src/data.js";
		const options = ${JSON.stringify(options)};
		const overview = structuredClone(MOCK_OVERVIEW);
		if(options.row) Object.assign(overview.rows[0], options.row);
		window.auditRequests = [];
		window.auditPending = [];
		window.auditOptions = options;
		window.addEventListener('message', event => {
		  const message = event.data;
		  if(message?.source !== 'hv-bankimport' || message.type !== 'rpc') return;
		  const { action, params } = message;
		  window.auditRequests.push({action, params});
		  let data;
		  if(action === 'overview') data = overview;
		  else if(action === 'open_invoices') data = {invoice_doctype: 'Sales Invoice', invoices: options.invoices || MOCK_OPEN_INVOICES.invoices, target_amount: Math.abs(overview.rows[0].betrag), allocation_mode: options.allocationMode || 'invoice_payment'};
		  else if(action === 'search_parties') data = {items: ['A','B','Erika Beispiel'].filter(x => x.toLowerCase().includes(params.txt.toLowerCase())).map(value => ({value,label:value}))};
		  else if(action === 'customer_split_invoices') data = {customer:params.customer, contract:'MV-'+params.customer, wohnung:'W-'+params.customer, invoices:[{name:'INV-'+params.customer,outstanding_amount:params.customer === 'A' ? 200 : -300,posting_date:'2026-01-01'}]};
		  else if(action === 'search_accounts') data = {items:[{value:'4970 Bankgebühren - HV',label:'4970 Bankgebühren - HV'}]};
		  else if(action === 'expected_cost_center') data = {cost_center:null};
		  else data = {ok:true};
		  const rejection = options.rejectAction === action;
		  if(options.failAction === action) data = {ok:false,message:'Audit: backend refused'};
		  const respond = () => event.source.postMessage({source:'hv-bankimport-host',type:'rpc-result',id:message.id,ok:!rejection,data,error:rejection ? 'Audit: API failed' : undefined}, event.origin);
		  if(options.delayAction === action) window.auditPending.push(respond); else respond();
		});
		document.querySelector('iframe').src = '${ASSETS}?import=BAI-1812-DEMO-0001';
		</script></body></html>`,
	}));
	await page.goto("/bugtesting-host");
	const frame = page.frameLocator("iframe");
	await expect(frame.getByRole("table")).toBeVisible();
	return frame;
}

async function requests(page, action) {
	return page.evaluate((key) => window.auditRequests.filter((item) => item.action === key), action);
}

async function openSplit(page, options = {}) {
	const frame = await openHost(page, { row: { betrag: -100, richtung: "Ausgang" }, ...options });
	await frame.getByRole("button", { name: "Mehrere Mieter", exact: true }).click();
	const dialog = frame.getByRole("dialog", { name: "Auf mehrere Mieter aufteilen" });
	for (const customer of ["A", "B"]) {
		await dialog.getByPlaceholder("Mieter hinzufügen").fill(customer);
		await dialog.locator(".link-search-item").filter({ hasText: new RegExp(`^${customer}$`) }).click();
		await expect(dialog.locator(".customer-split-group").filter({ hasText: `MV-${customer}` })).toBeVisible();
	}
	return { frame, dialog };
}

async function selectNet(dialog) {
	await dialog.getByRole("checkbox", { name: /INV-A/ }).check();
	await dialog.getByRole("checkbox", { name: /INV-B/ }).check();
}

test("current phase and search filters retain valid selection and assign a party", async ({ page }) => {
	const frame = await openHost(page);
	await frame.getByRole("button", { name: /Parteien zuordnen/ }).click();
	await expect(frame.getByText("Parteien zuordnen · Offen", { exact: true })).toBeVisible();
	await expect(frame.getByRole("row", { name: /Erika Beispiel/ })).toBeVisible();
	await frame.getByPlaceholder("Verwendungszweck, Auftraggeber, IBAN…").fill("no-result");
	await expect(frame.getByText("Keine Zeile ausgewählt", { exact: true })).toBeVisible();
	await frame.getByPlaceholder("Verwendungszweck, Auftraggeber, IBAN…").fill("Erika");
	await frame.getByPlaceholder("Mieter suchen…").fill("Erika");
	await frame.locator(".link-search-item").filter({ hasText: "Erika Beispiel" }).click();
	await expect(frame.getByText("Partei zugeordnet: Erika Beispiel.", { exact: true })).toBeVisible();
	expect((await requests(page, "assign_party"))[0].params.party).toBe("Erika Beispiel");
});

test("invoice booking remains physically clickable at the current viewport", async ({ page }) => {
	const frame = await openHost(page);
	await frame.locator(".invoice-card").filter({ hasText: "SINV-2026-0041" }).getByRole("checkbox").check();
	await frame.locator(".invoice-card").filter({ hasText: "SINV-2026-0038" }).getByRole("checkbox").check();
	await frame.getByRole("button", { name: "Zuordnen & buchen", exact: true }).click({ timeout: 6000 });
	await expect(frame.getByText("Die Zuweisung übersteigt den Bankbetrag.", { exact: true })).toBeVisible();
	await frame.locator(".invoice-card").filter({ hasText: "SINV-2026-0038" }).getByRole("checkbox").uncheck();
	await frame.getByRole("button", { name: "Zuordnen & buchen", exact: true }).click({ timeout: 6000 });
	await expect(frame.getByText("Zahlung gebucht und Bank Transaction abgeglichen.", { exact: true })).toBeVisible();
	expect(await requests(page, "reconcile")).toHaveLength(1);
});

for (const [label, amount] of [["fractional cents", "719.999"], ["one cent above the invoice and bank amount", "720.01"]]) {
	test(`invoice allocations reject ${label} before sending a booking request`, async ({ page }) => {
		const frame = await openHost(page);
		const invoice = frame.locator(".invoice-card").filter({ hasText: "SINV-2026-0041" });
		await invoice.getByRole("checkbox").check();
		await invoice.getByRole("spinbutton").fill(amount);
		await frame.getByRole("button", { name: "Zuordnen & buchen", exact: true }).click();
		await expect(frame.locator(".hv-toast")).toBeVisible();
		expect(await requests(page, "reconcile")).toHaveLength(0);
	});
}

for (const actionFailure of ["failAction", "rejectAction"]) {
	test(`invoice booking ${actionFailure} shows an error and retains the original row`, async ({ page }) => {
		const frame = await openHost(page, { [actionFailure]: "reconcile" });
		await frame.locator(".invoice-card").filter({ hasText: "SINV-2026-0041" }).getByRole("checkbox").check();
		const overviewCount = (await requests(page, "overview")).length;
		await frame.getByRole("button", { name: "Zuordnen & buchen", exact: true }).click();
		await expect(frame.getByText(actionFailure === "failAction" ? "Audit: backend refused" : "Audit: API failed", { exact: true })).toBeVisible();
		await expect(frame.getByText("Zahlung gebucht und Bank Transaction abgeglichen.", { exact: true })).not.toBeVisible();
		expect(await requests(page, "overview")).toHaveLength(overviewCount);
		await expect(frame.locator(".invoice-card").filter({ hasText: "SINV-2026-0041" }).getByRole("checkbox")).toBeChecked();
	});
}

test("a signed Customer charge and credit net to the bank amount and submit positive magnitudes", async ({ page }) => {
	const { frame, dialog } = await openSplit(page);
	await selectNet(dialog);
	await expect(dialog.getByText("Rest 0,00 €", { exact: true })).toBeVisible();
	await dialog.getByRole("button", { name: "Aufteilung buchen", exact: true }).click();
	await expect(dialog).not.toBeVisible();
	await expect(frame.getByText("Belege ausgeglichen und Bankumsatz vollständig abgeglichen.", { exact: true })).toBeVisible();
	const calls = await requests(page, "reconcile_customer_split");
	expect(calls).toHaveLength(1);
	expect(JSON.parse(calls[0].params.allocations)).toEqual([
		{ customer: "A", invoices: [{ name: "INV-A", allocated_amount: 200 }] },
		{ customer: "B", invoices: [{ name: "INV-B", allocated_amount: 300 }] },
	]);
});

test("Customer split prevents duplicate Customers and rejects fractional cents and wrong bank direction", async ({ page }) => {
	const { dialog } = await openSplit(page);
	await dialog.getByPlaceholder("Mieter hinzufügen").fill("A");
	await dialog.locator(".link-search-item").filter({ hasText: /^A$/ }).click();
	await expect(dialog.locator(".customer-split-group")).toHaveCount(2);
	await selectNet(dialog);
	await dialog.getByLabel("Teilbetrag INV-A", { exact: true }).fill("100.001");
	await dialog.getByLabel("Teilbetrag INV-B", { exact: true }).fill("200.001");
	await expect(dialog.getByRole("button", { name: "Aufteilung buchen", exact: true })).toBeDisabled();
	await dialog.getByLabel("Teilbetrag INV-A", { exact: true }).fill("200");
	await dialog.getByLabel("Teilbetrag INV-B", { exact: true }).fill("100");
	await expect(dialog.getByRole("button", { name: "Aufteilung buchen", exact: true })).toBeDisabled();
	expect(await requests(page, "reconcile_customer_split")).toHaveLength(0);
});

test("Customer split rejects overallocations and preserves a valid partial net payment", async ({ page }) => {
	const { dialog } = await openSplit(page);
	await selectNet(dialog);
	await dialog.getByLabel("Teilbetrag INV-A", { exact: true }).fill("200.01");
	await dialog.getByLabel("Teilbetrag INV-B", { exact: true }).fill("300.01");
	await expect(dialog.getByRole("button", { name: "Aufteilung buchen", exact: true })).toBeDisabled();
	await dialog.getByLabel("Teilbetrag INV-A", { exact: true }).fill("100");
	await dialog.getByLabel("Teilbetrag INV-B", { exact: true }).fill("200");
	await expect(dialog.getByRole("button", { name: "Aufteilung buchen", exact: true })).toBeEnabled();
	await dialog.getByRole("button", { name: "Abbrechen", exact: true }).click();
	await expect(dialog).not.toBeVisible();
	expect(await requests(page, "reconcile_customer_split")).toHaveLength(0);
});

for (const actionFailure of ["failAction", "rejectAction"]) {
	test(`Customer split booking ${actionFailure} keeps the dialog open and permits retry`, async ({ page }) => {
		const { frame, dialog } = await openSplit(page, { [actionFailure]: "reconcile_customer_split" });
		await selectNet(dialog);
		await dialog.getByRole("button", { name: "Aufteilung buchen", exact: true }).click();
		await expect(frame.getByText(actionFailure === "failAction" ? "Audit: backend refused" : "Audit: API failed", { exact: true })).toBeVisible();
		await expect(dialog).toBeVisible();
		await expect(dialog.getByRole("button", { name: "Aufteilung buchen", exact: true })).toBeEnabled();
		await expect(frame.getByText("Belege ausgeglichen und Bankumsatz vollständig abgeglichen.", { exact: true })).not.toBeVisible();
	});
}

test("Customer split loading failure disables booking and displays the API error", async ({ page }) => {
	const frame = await openHost(page, { rejectAction: "customer_split_invoices" });
	await frame.getByRole("button", { name: "Mehrere Mieter", exact: true }).click();
	const dialog = frame.getByRole("dialog", { name: "Auf mehrere Mieter aufteilen" });
	await dialog.getByPlaceholder("Mieter hinzufügen").fill("A");
	await dialog.locator(".link-search-item").filter({ hasText: /^A$/ }).click();
	await expect(dialog.getByRole("alert")).toHaveText("Audit: API failed");
	await expect(dialog.getByRole("button", { name: "Aufteilung buchen", exact: true })).toBeDisabled();
});

test("Customer split busy state prevents a second booking request", async ({ page }) => {
	const { dialog } = await openSplit(page, { delayAction: "reconcile_customer_split" });
	await selectNet(dialog);
	const book = dialog.locator(".dialog-actions button.primary");
	await book.click();
	await expect(book).toBeDisabled();
	await expect(dialog.getByRole("button", { name: "Abbrechen", exact: true })).toBeDisabled();
	await page.evaluate(() => window.auditPending.shift()());
	await expect(dialog).not.toBeVisible();
	expect(await requests(page, "reconcile_customer_split")).toHaveLength(1);
});

async function journalSplit(page) {
	const frame = await openHost(page);
	await frame.getByRole("button", { name: "Buchungssatz", exact: true }).click();
	await frame.getByRole("button", { name: "Aufteilen", exact: true }).click();
	await frame.getByPlaceholder("Konto suchen…").fill("4970");
	await frame.locator(".link-search-item").filter({ hasText: "4970 Bankgebühren - HV" }).click();
	return frame;
}

for (const [label, amount] of [["fractional cents", "719,999"], ["one cent missing", "719,99"]]) {
	test(`journal split rejects ${label} before sending a booking request`, async ({ page }) => {
		const frame = await journalSplit(page);
		await frame.locator(".amount-input").fill(amount);
		await frame.getByRole("button", { name: "Buchungssatz erstellen", exact: true }).click();
		await expect(frame.locator(".hv-toast")).toBeVisible();
		expect(await requests(page, "journal_entry")).toHaveLength(0);
	});
}

test("journal split handles German decimal input and sends an exact balanced split", async ({ page }) => {
	const frame = await journalSplit(page);
	await frame.locator(".amount-input").fill("720,00");
	await frame.getByRole("button", { name: "Buchungssatz erstellen", exact: true }).click();
	await expect(frame.getByText("Buchungssatz erstellt und abgeglichen.", { exact: true })).toBeVisible();
	const calls = await requests(page, "journal_entry");
	expect(calls).toHaveLength(1);
	expect(JSON.parse(calls[0].params.splits)).toEqual([{ account: "4970 Bankgebühren - HV", amount: 720 }]);
});

test("a rejected party assignment never reports success", async ({ page }) => {
	const frame = await openHost(page, { failAction: "assign_party" });
	await frame.getByRole("button", { name: /Parteien zuordnen/ }).click();
	await frame.getByPlaceholder("Mieter suchen…").fill("Erika");
	await frame.locator(".link-search-item").filter({ hasText: "Erika Beispiel" }).click();
	await expect(frame.locator(".hv-toast")).toHaveClass(/error/, { timeout: 1000 });
	await expect(frame.getByText("Audit: backend refused", { exact: true })).toBeVisible();
	await expect(frame.getByText("Partei zugeordnet: Erika Beispiel.", { exact: true })).not.toBeVisible();
});
