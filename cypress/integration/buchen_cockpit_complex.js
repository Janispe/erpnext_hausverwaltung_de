/**
 * Komplexer UI-Regressionsspec für das Buchungs-Cockpit.
 *
 * Fokus: Eingangsrechnung-Dialog als echter Frappe-Dialog mit Grid, Moduswechsel,
 * Vorlagen speichern/laden und finaler Purchase-Invoice-Erzeugung.
 */

const HV_API = "hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit";
const TEST_TAG = `__cy_cockpit_complex_${Date.now()}`;
const DRAFT_KEY_PI = "hv_buchen_cockpit_draft_pi_v1";

const createdPurchaseInvoices = [];
const createdTemplates = [];
const createdSuppliers = [];

const closeAllDialogs = () => {
	cy.window().then((win) => {
		const dialogs = (win.frappe?.ui?._all_dialogs || []).slice();
		dialogs.forEach((dialog) => {
			try {
				dialog.hide();
			} catch (e) {}
		});
		if (win.cur_dialog) {
			try {
				win.cur_dialog.hide();
			} catch (e) {}
		}
		try {
			win.$(".modal.fade.show").modal("hide").removeClass("show").hide();
			win.$(".modal-backdrop").remove();
			win.$("body").removeClass("modal-open").css("padding-right", "");
		} catch (e) {}
	});
	cy.get(".modal.fade.show", { timeout: 4000 }).should("not.exist");
};

const findEingangsrechnungDialog = (win) => {
	const dialogs = [
		win.__cy_eingangsrechnung_dialog,
		win.cur_dialog,
		...(win.frappe?.ui?._all_dialogs || []).slice().reverse(),
	].filter(Boolean);
	return dialogs.find((d) => d?.fields_dict?.positionen && d?.fields_dict?.lieferant);
};

const getEingangsrechnungDialog = () =>
	cy.window({ timeout: 10000 }).then((win) => {
		const dialog = findEingangsrechnungDialog(win);
		expect(dialog, "Eingangsrechnung-Dialog").to.exist;
		return dialog;
	});

const waitForEingangsrechnungDialogState = (assertions) =>
	cy.window({ timeout: 10000 }).should((win) => {
		const dialog = findEingangsrechnungDialog(win);
		expect(dialog, "Eingangsrechnung-Dialog").to.exist;
		assertions(dialog);
	});

const setRows = (dialog, rows) => {
	const gridField = dialog.fields_dict.positionen;
	gridField.df.data = rows.map((row) => ({ ...row }));
	gridField.grid.refresh();
};

const getRows = (dialog) =>
	(dialog.fields_dict.positionen.grid.df.data || []).filter((row) => row && !row.__islocal_empty);

const getGridField = (dialog, fieldname) => {
	const grid = dialog.fields_dict.positionen.grid;
	return (
		(grid.docfields || []).find((field) => field.fieldname === fieldname) ||
		(grid.df?.fields || []).find((field) => field.fieldname === fieldname)
	);
};

const openEingangsrechnungDialog = () => {
	cy.visit("/app");
	cy.get("body").should("have.attr", "data-ajax-state", "complete");
	closeAllDialogs();
	cy.window().then((win) => {
		expect(
			typeof win.hausverwaltung?.buchen_cockpit?.open_eingangsrechnung_dialog,
			"open_eingangsrechnung_dialog vorhanden"
		).to.eq("function");
		win.__cy_eingangsrechnung_dialog =
			win.hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog();
	});
	cy.get(".modal:visible", { timeout: 10000 }).should("exist");
	return getEingangsrechnungDialog();
};

context("Buchungs-Cockpit — komplexer Eingangsrechnungs-UI-Flow", () => {
	let supplier;
	let costCenter;
	let bkArt;
	let nichtUlArt;

	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 15000 }).its("frappe.csrf_token", { timeout: 15000 }).should("exist");

		cy.call("frappe.client.get_list", {
			doctype: "Supplier Group",
			fields: ["name"],
			limit_page_length: 1,
			order_by: "name asc",
		}).then((r) => {
			expect(r.message || [], "Supplier Group Seed").to.have.length.greaterThan(0);
			const supplierName = `${TEST_TAG} Supplier`;
			return cy.call("frappe.client.insert", {
				doc: {
					doctype: "Supplier",
					supplier_name: supplierName,
					supplier_group: r.message[0].name,
					supplier_type: "Company",
					companies: [{ company: "Hausverwaltung Peters" }],
				},
			});
		}).then((r) => {
			supplier = r.message.name;
			createdSuppliers.push(supplier);
		});

		cy.call("frappe.client.get_list", {
			doctype: "Cost Center",
			filters: { company: "Hausverwaltung Peters", is_group: 0 },
			fields: ["name"],
			limit_page_length: 1,
			order_by: "name asc",
		}).then((r) => {
			expect(r.message || [], "Cost Center Seed").to.have.length.greaterThan(0);
			costCenter = r.message[0].name;
		});

		cy.call("frappe.client.get_list", {
			doctype: "Betriebskostenart",
			filters: [
				["konto", "is", "set"],
				["artikel", "is", "set"],
			],
			fields: ["name", "konto", "artikel", "verteilung"],
			limit_page_length: 20,
			order_by: "name asc",
		}).then((r) => {
			const rows = r.message || [];
			expect(rows, "Betriebskostenart mit Konto+Artikel").to.have.length.greaterThan(0);
			bkArt = rows.find((row) => String(row.verteilung || "").toLowerCase() !== "einzeln") || rows[0];
		});

		cy.call("frappe.client.get_list", {
			doctype: "Kostenart nicht umlagefaehig",
			filters: [
				["konto", "is", "set"],
				["artikel", "is", "set"],
			],
			fields: ["name", "konto", "artikel"],
			limit_page_length: 20,
			order_by: "name asc",
		}).then((r) => {
			expect(r.message || [], "Kostenart nicht umlagefaehig mit Konto+Artikel")
				.to.have.length.greaterThan(0);
			nichtUlArt = r.message[0];
		});

		cy.then(() => {
			cy.window().then((win) => win.localStorage.removeItem(DRAFT_KEY_PI));
		});
	});

	after(() => {
		cy.then(() => {
			createdPurchaseInvoices.forEach((name) => {
				cy.window().its("frappe.csrf_token").then((csrfToken) => {
					cy.request({
						method: "POST",
						url: "/api/method/frappe.client.get",
						body: { doctype: "Purchase Invoice", name },
						headers: {
							"Content-Type": "application/json",
							"X-Frappe-CSRF-Token": csrfToken,
						},
						failOnStatusCode: false,
					}).then((getRes) => {
						if (getRes.status === 200 && Number(getRes.body?.message?.docstatus) === 1) {
							cy.request({
								method: "POST",
								url: "/api/method/frappe.client.cancel",
								body: { doctype: "Purchase Invoice", name },
								headers: {
									"Content-Type": "application/json",
									"X-Frappe-CSRF-Token": csrfToken,
								},
								failOnStatusCode: false,
							});
						}
						cy.request({
							method: "POST",
							url: "/api/method/frappe.client.delete",
							body: { doctype: "Purchase Invoice", name },
							headers: {
								"Content-Type": "application/json",
								"X-Frappe-CSRF-Token": csrfToken,
							},
							failOnStatusCode: false,
						});
					});
			});
		});

			createdTemplates.forEach((name) => {
				cy.window().its("frappe.csrf_token").then((csrfToken) => {
					cy.request({
						method: "POST",
						url: "/api/method/frappe.client.delete",
						body: { doctype: "Eingangsrechnung Vorlage", name },
						headers: {
							"Content-Type": "application/json",
							"X-Frappe-CSRF-Token": csrfToken,
						},
						failOnStatusCode: false,
					});
				});
			});

			createdSuppliers.forEach((name) => {
				cy.window().its("frappe.csrf_token").then((csrfToken) => {
					cy.request({
						method: "POST",
						url: "/api/method/frappe.client.delete",
						body: { doctype: "Supplier", name },
						headers: {
							"Content-Type": "application/json",
							"X-Frappe-CSRF-Token": csrfToken,
						},
						failOnStatusCode: false,
					});
				});
			});
		});
	});

	it("[1] restauriert Draft, wechselt Kostenart/Konto, speichert Konto-Vorlage und erzeugt PI-Draft", () => {
		const templateTitle = `${TEST_TAG}_konto_vorlage_${Date.now()}_${Cypress._.random(1000, 9999)}`;
		const initialRows = [
			{
				typ: "umlegbar",
				kostenart: bkArt.name,
				betriebskostenart: bkArt.name,
				kostenstelle: costCenter,
				betrag: 12.34,
			},
		];
		const kontoRows = [
			{
				typ: "umlegbar",
				kostenart: bkArt.konto,
				kostenstelle: costCenter,
				betrag: 80.12,
			},
			{
				typ: "nicht umlegbar",
				kostenart: nichtUlArt.konto,
				kostenstelle: costCenter,
				betrag: 19.88,
			},
		];

		cy.window().then((win) => {
			win.localStorage.setItem(
				DRAFT_KEY_PI,
				JSON.stringify({
					ts: Date.now(),
					data: {
						lieferant: supplier,
						rechnungsdatum: "2026-05-06",
						wertstellungsdatum: "2026-04-30",
						rechnungsname: `${TEST_TAG}-draft`,
						remarks: `${TEST_TAG} Draft Restore`,
						eingabemodus: "Kostenart",
						positionen: initialRows,
					},
				})
			);
		});

		openEingangsrechnungDialog();
		cy.contains(".hv-cockpit-draft-banner", "Entwurf", { timeout: 10000 }).should("exist");
		cy.get(".hv-cockpit-draft-banner .hv-draft-restore").click();

		waitForEingangsrechnungDialogState((dialog) => {
			expect(dialog.get_value("lieferant")).to.eq(supplier);
			expect(dialog.get_value("remarks")).to.eq(`${TEST_TAG} Draft Restore`);
			expect(dialog.get_value("eingabemodus")).to.eq("Kostenart");
			expect(getRows(dialog)[0].kostenart).to.eq(bkArt.name);
			expect(getRows(dialog)[0].betriebskostenart).to.eq(bkArt.name);
		});

		cy.wait(650);
		getEingangsrechnungDialog().then((dialog) => {
			dialog.set_value("eingabemodus", "Konto");
		});

		cy.wait(250);
		getEingangsrechnungDialog().then((dialog) => {
			expect(getGridField(dialog, "kostenart").label).to.eq("Konto");
			expect(getRows(dialog)[0].kostenart || "", "Kostenart nach Moduswechsel geleert").to.eq("");
			setRows(dialog, kontoRows);
		});

		cy.window().its("frappe.csrf_token").then((csrfToken) => {
			cy.request({
				method: "POST",
				url: "/api/method/frappe.client.delete",
				body: { doctype: "Eingangsrechnung Vorlage", name: templateTitle },
				headers: {
					"Content-Type": "application/json",
					"X-Frappe-CSRF-Token": csrfToken,
				},
				failOnStatusCode: false,
			});
		});

		cy.get(".modal:visible .btn").contains("Als Vorlage speichern").click();
		cy.get(".modal:visible", { timeout: 10000 })
			.last()
			.within(() => {
				cy.get('[data-fieldname="titel"] input').clear().type(templateTitle);
				cy.get(".btn-primary").contains("Speichern").click();
			});
		cy.contains(
			".alert, .desk-alert, .frappe-toast, .toast-message, .text-medium",
			templateTitle,
			{ timeout: 10000 }
		).should("exist");

		cy.call("frappe.client.get_list", {
			doctype: "Eingangsrechnung Vorlage",
			filters: { titel: templateTitle },
			fields: ["name", "eingabemodus", "lieferant"],
			limit_page_length: 1,
		}).then((r) => {
			expect(r.message || []).to.have.length(1);
			createdTemplates.push(r.message[0].name);
			expect(r.message[0].eingabemodus).to.eq("Konto");
			expect(r.message[0].lieferant).to.eq(supplier);
		});

		closeAllDialogs();
		openEingangsrechnungDialog();
		getEingangsrechnungDialog().then((dialog) => {
			dialog.set_value("lieferant", supplier);
			dialog.set_value("remarks", "wird von Vorlage ersetzt");
			setRows(dialog, [
				{
					typ: "umlegbar",
					kostenart: bkArt.name,
					kostenstelle: costCenter,
					betrag: 1,
				},
			]);
			dialog.set_value("aus_vorlage", templateTitle);
		});

		cy.contains(".modal:visible", "überschrieben", { timeout: 10000 }).should("exist");
		cy.contains(".modal:visible .btn", /^(No|Nein)$/).click({ force: true });
		closeAllDialogs();

		openEingangsrechnungDialog();
		getEingangsrechnungDialog().then((dialog) => {
			dialog.set_value("aus_vorlage", templateTitle);
		});
		cy.contains(
			".alert, .desk-alert, .frappe-toast, .toast-message, .text-medium",
			templateTitle,
			{ timeout: 10000 }
		).should("exist");

		cy.wait(600);
		getEingangsrechnungDialog().then((dialog) => {
			const rows = getRows(dialog);
			expect(dialog.get_value("eingabemodus")).to.eq("Konto");
			expect(getGridField(dialog, "kostenart").label).to.eq("Konto");
			expect(rows).to.have.length(2);
			expect(rows[0].kostenart).to.eq(bkArt.konto);
			expect(rows[0].betriebskostenart).to.eq(bkArt.name);
			expect(rows[1].kostenart).to.eq(nichtUlArt.konto);
			expect(rows[1].kostenart_nicht_ul).to.eq(nichtUlArt.name);
			dialog.set_value("rechnungsdatum", "2026-05-06");
			dialog.set_value("wertstellungsdatum", "2026-04-30");
			dialog.set_value("rechnungsname", `${TEST_TAG}-pi`);
		});

		cy.get(".modal:visible .btn").contains("Als Entwurf speichern").click();
		cy.contains(
			".alert, .desk-alert, .frappe-toast, .toast-message, .text-medium",
			"als Entwurf",
			{ timeout: 15000 }
		).should("exist");

		cy.call("frappe.client.get_list", {
			doctype: "Purchase Invoice",
			filters: { supplier, bill_no: `${TEST_TAG}-pi` },
			fields: ["name", "docstatus", "grand_total", "remarks"],
			limit_page_length: 1,
			order_by: "creation desc",
		}).then((r) => {
			expect(r.message || [], "Purchase Invoice angelegt").to.have.length(1);
			const pi = r.message[0];
			createdPurchaseInvoices.push(pi.name);
			expect(Number(pi.docstatus)).to.eq(0);
			expect(Number(pi.grand_total)).to.be.closeTo(100, 0.01);
			expect(pi.remarks || "").to.not.include("Erfasst über Buchungs-Cockpit");
			return cy.call("frappe.client.get", {
				doctype: "Purchase Invoice",
				name: pi.name,
			});
		}).then((g) => {
			const pi = g.message;
			expect(pi.hv_eingabequelle).to.eq("Vereinfachte Buchung");
			expect(String(pi.custom_wertstellungsdatum)).to.match(/^2026-04-30/);
			expect(pi.items).to.have.length(2);
			expect(pi.items[0].expense_account).to.eq(bkArt.konto);
			expect(pi.items[0].hv_umlagefaehig).to.eq("Betriebskostenart");
			expect(pi.items[0].hv_kostenart).to.eq(bkArt.name);
			expect(Number(pi.items[0].rate)).to.be.closeTo(80.12, 0.01);
			expect(pi.items[1].expense_account).to.eq(nichtUlArt.konto);
			expect(pi.items[1].hv_umlagefaehig).to.eq("Kostenart nicht umlagefaehig");
			expect(pi.items[1].hv_kostenart).to.eq(nichtUlArt.name);
			expect(Number(pi.items[1].rate)).to.be.closeTo(19.88, 0.01);
		});
	});

	it("[2] blockiert unvollständige Grid-Zeile sichtbar über den UI-Submit", () => {
		openEingangsrechnungDialog();
		getEingangsrechnungDialog().then((dialog) => {
			dialog.set_value("lieferant", supplier);
			dialog.set_value("rechnungsdatum", "2026-05-06");
			dialog.set_value("rechnungsname", `${TEST_TAG}-invalid`);
			dialog.set_value("eingabemodus", "Konto");
			setRows(dialog, [
				{
					typ: "umlegbar",
					kostenart: bkArt.konto,
					kostenstelle: costCenter,
				},
			]);
		});

		cy.get(".modal:visible .btn").contains("Als Entwurf speichern").click();
		cy.contains(
			".modal:visible, .msgprint-dialog, .frappe-msgprint, .modal-body",
			"Betrag fehlt",
			{ timeout: 10000 }
		).should("exist");

		cy.call("frappe.client.get_list", {
			doctype: "Purchase Invoice",
			filters: { supplier, bill_no: `${TEST_TAG}-invalid` },
			fields: ["name"],
			limit_page_length: 1,
		}).then((r) => {
			expect(r.message || []).to.have.length(0);
		});
	});
});
