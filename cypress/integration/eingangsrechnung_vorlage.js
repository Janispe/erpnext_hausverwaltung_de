/**
 * E2E-Test für Eingangsrechnung Vorlagen im Buchungs-Cockpit.
 *
 * Kern-Regressionstest: Bug, bei dem `apply_eingabemodus()` die
 * `kostenart`-Werte einer gerade per Vorlage gefüllten Positions-Tabelle
 * wieder leerte (apply_eingabemodus wurde NACH dem Setzen der Daten gerufen,
 * jetzt nur noch DAVOR).
 *
 * Strategie:
 *   1) Seed-Vorlage via Backend-API anlegen (deterministisch, kein UI-Test-Setup-Aufwand)
 *   2) Cockpit-Dialog öffnen, "Aus Vorlage übernehmen" setzen → onchange triggert
 *      `hv_apply_vorlage` (das Stück Code, das den Bug hatte)
 *   3) Asserten: Alle Positions-Felder inkl. kostenart sind gefüllt
 *   4) Bonus: Vorlage taucht in der Listenansicht auf
 */

const VORLAGE_TITEL = `__cy_vorlage_${Date.now()}`;

// Wartet bis Frappe `window.cur_dialog` gesetzt hat.
const getCurDialog = () =>
	cy.window({ timeout: 10000 }).its("cur_dialog", { timeout: 10000 }).should("exist");

const getEingangsrechnungDialog = () =>
	cy.window({ timeout: 10000 }).then((win) => {
		const dialogs = (win.frappe?.ui?._all_dialogs || []).slice().reverse();
		const dialog = dialogs.find((d) => d?.fields_dict?.positionen);
		expect(dialog, "Eingangsrechnung Dialog").to.exist;
		return dialog;
	});

const closeAllDialogs = () => {
	cy.window().then((win) => {
		const dialogs = (win.frappe?.ui?._all_dialogs || []).slice();
		dialogs.forEach((d) => {
			try {
				d.hide();
			} catch (e) {}
		});
		if (win.cur_dialog) {
			try {
				win.cur_dialog.hide();
			} catch (e) {}
		}
	});
	// Warten bis alle modals weg sind
	cy.get(".modal.fade.show", { timeout: 4000 }).should("not.exist");
};

context("Eingangsrechnung Vorlage — Buchungs-Cockpit", () => {
	let supplier;
	let cost_center;
	let bk_art;
	let nul_art;

	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");

		// Seed-Daten (erste Treffer)
		cy.call("frappe.client.get_list", {
			doctype: "Supplier",
			limit_page_length: 1,
			fields: ["name"],
		}).then((r) => {
			supplier = r.message[0].name;
		});
		cy.call("frappe.client.get_list", {
			doctype: "Cost Center",
			filters: { is_group: 0 },
			limit_page_length: 1,
			fields: ["name"],
		}).then((r) => {
			cost_center = r.message[0].name;
		});
		cy.call("frappe.client.get_list", {
			doctype: "Betriebskostenart",
			limit_page_length: 1,
			fields: ["name"],
		}).then((r) => {
			bk_art = r.message[0].name;
		});
		cy.call("frappe.client.get_list", {
			doctype: "Kostenart nicht umlagefaehig",
			limit_page_length: 1,
			fields: ["name"],
		}).then((r) => {
			nul_art = r.message[0].name;
		});

		// Vorlage via API seeden — wir testen den APPLY-Pfad, nicht das UI-Setup.
		// Falls vom letzten Run noch da: löschen.
		cy.call("frappe.client.get_list", {
			doctype: "Eingangsrechnung Vorlage",
			filters: { name: VORLAGE_TITEL },
			limit_page_length: 1,
		}).then((r) => {
			if ((r.message || []).length) {
				cy.call("frappe.client.delete", {
					doctype: "Eingangsrechnung Vorlage",
					name: VORLAGE_TITEL,
				});
			}
		});
		cy.then(() => {
			cy.call(
				"hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit.save_vorlage_from_cockpit",
				{
					titel: VORLAGE_TITEL,
					lieferant: supplier,
					eingabemodus: "Kostenart",
					remarks: "Cypress test seed",
					positionen: JSON.stringify([
						{
							typ: "umlegbar",
							kostenart: bk_art,
							kostenstelle: cost_center,
							betrag: 99.5,
						},
						{
							typ: "nicht umlegbar",
							kostenart: nul_art,
							kostenstelle: cost_center,
							betrag: 50,
						},
					]),
				}
			).then((r) => {
				expect(r.message?.name, "Vorlage angelegt").to.eq(VORLAGE_TITEL);
			});
		});
	});

	after(() => {
		// Best-effort cleanup. Wenn der Test-User keine delete-Permission hat
		// (kann bei frischen Migrates vorkommen), bleibt die Vorlage liegen —
		// kein Test-Failure, weil das nicht der Test-Subject ist.
		cy.window()
			.its("frappe.csrf_token")
			.then((csrf_token) => {
				cy.request({
					method: "POST",
					url: "/api/method/frappe.client.delete",
					body: { doctype: "Eingangsrechnung Vorlage", name: VORLAGE_TITEL },
					headers: {
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
					failOnStatusCode: false,
				});
			});
	});

	it("[1/3] Vorlage erscheint in der DocType-Listenansicht", () => {
		cy.go_to_list("Eingangsrechnung Vorlage");
		cy.get(".frappe-list").should("exist");
		cy.contains(".list-row, .list-row-container", VORLAGE_TITEL, {
			timeout: 10000,
		}).should("exist");
	});

	it("[2/3] Apply-Flow: Dialog öffnen → 'Aus Vorlage' setzen → Felder müssen gefüllt sein (Bug-Regression)", () => {
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		closeAllDialogs();

		cy.window().then((win) => {
			expect(
				typeof win.hausverwaltung?.buchen_cockpit?.open_eingangsrechnung_dialog,
				"open_eingangsrechnung_dialog vorhanden"
			).to.equal("function");
			win.hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog();
		});
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");

		// Vorlagen-Picker setzen → onchange triggert hv_apply_vorlage
		getCurDialog().then((dialog) => {
			expect(dialog.fields_dict.aus_vorlage, "aus_vorlage Feld").to.exist;
			expect(dialog.fields_dict.positionen, "positionen Feld").to.exist;
			dialog.set_value("aus_vorlage", VORLAGE_TITEL);
		});

		// Erfolgs-Alert "übernommen" — bestätigt async load_vorlage_for_cockpit roundtrip
		cy.contains(
			".alert, .desk-alert, .frappe-toast, .toast-message, .text-medium",
			VORLAGE_TITEL,
			{ timeout: 10000 }
		).should("exist");

		// Kurz warten, damit belt-and-suspenders-Re-Applies (50ms + 250ms) gelaufen sind.
		cy.wait(400);

		// === KERN-ASSERTIONS ===
		getCurDialog().then((dialog) => {
			const values = dialog.get_values(true) || {};

			expect(values.lieferant, "Lieferant gefüllt").to.eq(supplier);
			expect(values.eingabemodus, "Eingabemodus = Kostenart").to.eq("Kostenart");
			expect(values.remarks || "", "Anmerkungen").to.match(/Cypress/);

			// Grid-Daten direkt aus df.data lesen
			const rows = (dialog.fields_dict.positionen.grid.df.data || []).filter(
				(r) => r
			);
			expect(rows.length, "2 Positionen geladen").to.eq(2);

			// === REGRESSIONSTEST: kostenart darf NICHT leer sein nach Apply ===
			rows.forEach((row, i) => {
				expect(
					row.kostenart,
					`Position ${i}: kostenart MUSS nach Apply gefüllt sein (Bug-Regression)`
				)
					.to.be.a("string")
					.and.not.empty;
				expect(row.kostenstelle, `Position ${i}: kostenstelle`).to.eq(
					cost_center
				);
				expect(row.typ, `Position ${i}: typ`).to.match(
					/^(umlegbar|nicht umlegbar)$/
				);
				expect(Number(row.betrag), `Position ${i}: betrag > 0`).to.be.greaterThan(0);
			});

			// Spezifische Werte
			const r_umlegbar = rows.find((r) => r.typ === "umlegbar");
			const r_nicht_ul = rows.find((r) => r.typ === "nicht umlegbar");
			expect(r_umlegbar, "umlegbar row found").to.exist;
			expect(r_nicht_ul, "nicht_ul row found").to.exist;
			expect(r_umlegbar.kostenart, "umlegbar.kostenart").to.eq(bk_art);
			expect(r_umlegbar.betriebskostenart, "umlegbar.betriebskostenart").to.eq(
				bk_art
			);
			expect(r_nicht_ul.kostenart, "nicht_ul.kostenart").to.eq(nul_art);
			expect(
				r_nicht_ul.kostenart_nicht_ul,
				"nicht_ul.kostenart_nicht_ul"
			).to.eq(nul_art);
			expect(Number(r_umlegbar.betrag), "umlegbar.betrag").to.eq(99.5);
			expect(Number(r_nicht_ul.betrag), "nicht_ul.betrag").to.eq(50);
		});

		// Zusätzlich: Auch im DOM muss kostenart sichtbar sein (Autocomplete-Cell)
		// Selektor: 1. Body-Zeile, dritte Zelle (typ=2, kostenart=3 inkl. Checkbox-Spalte)
		cy.get(".modal:visible .grid-body .rows .grid-row").first().within(() => {
			cy.get('[data-fieldname="kostenart"] input, [data-fieldname="kostenart"] .static-area, [data-fieldname="kostenart"]')
				.should("exist");
		});

		closeAllDialogs();
	});

	it("[3/3] Confirm-Dialog: bei vorhandenen Daten wird vor Überschreiben gefragt", () => {
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		closeAllDialogs();

		cy.window().then((win) => {
			win.hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog();
		});
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");

		// Lieferant vorbelegen → Apply muss Bestätigungsdialog werfen
		getCurDialog().then((dialog) => {
			dialog.set_value("lieferant", supplier);
			dialog.set_value("aus_vorlage", VORLAGE_TITEL);
		});

		// Confirm-Dialog mit "überschrieben" auftauchen
		cy.contains(".modal:visible", "überschrieben", { timeout: 5000 }).should(
			"exist"
		);

		// "Ja" / "Yes" Button im Confirm-Dialog
		cy.get(".modal:visible .btn-primary:contains('Yes'), .modal:visible .btn-primary:contains('Ja')")
			.first()
			.click();

		// Erfolgs-Alert sollte erscheinen
		cy.contains(
			".alert, .desk-alert, .frappe-toast, .toast-message, .text-medium",
			VORLAGE_TITEL,
			{ timeout: 10000 }
		).should("exist");

	});
});
