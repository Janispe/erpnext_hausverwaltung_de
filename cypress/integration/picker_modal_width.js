/**
 * Diagnostiziert die Picker-Modal-Breite des MultiSelectDialog-Iterations-Pickers
 * im Serienbrief-Durchlauf-Flow. Soll laut Hausverwaltung Einstellungen 92vw sein,
 * aber der User berichtet, dass das Modal viel schmaler erscheint.
 */

context("Picker Modal Width Diagnose", () => {
	let vorlage_with_mietvertrag;

	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");

		// Boot-Info: hv_ui Settings korrekt geladen?
		cy.window().then((win) => {
			const hv_ui = win.frappe?.boot?.hv_ui;
			cy.log("frappe.boot.hv_ui:", JSON.stringify(hv_ui));
			expect(hv_ui, "frappe.boot.hv_ui muss vorhanden sein").to.exist;
			expect(
				hv_ui.picker_modal_width_vw,
				"picker_modal_width_vw setting"
			).to.be.greaterThan(0);
		});

		// Vorlage finden, die Mietvertrag als Iteration hat
		cy.call("frappe.client.get_list", {
			doctype: "Serienbrief Vorlage",
			filters: { haupt_verteil_objekt: "Mietvertrag" },
			limit_page_length: 1,
			fields: ["name"],
		}).then((r) => {
			expect(r.message[0], "Mietvertrag-Vorlage gefunden").to.exist;
			vorlage_with_mietvertrag = r.message[0].name;
		});
	});

	it("widen_modal-Helper ist global verfügbar", () => {
		cy.window().then((win) => {
			expect(
				typeof win.hausverwaltung?.ui?.widen_modal,
				"widen_modal Helper"
			).to.equal("function");
		});
	});

	it("MultiSelectDialog-Picker wird auf 92vw gestreckt im Serienbrief-Durchlauf-Flow (User-Reproduktion)", () => {
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		cy.window({ timeout: 30000 })
			.its("hausverwaltung.serienbrief.open_new_durchlauf_dialog")
			.should("be.a", "function");

		// Den Serienbrief-Durchlauf-Dialog öffnen
		cy.window().then((win) => {
			win.hausverwaltung.serienbrief.open_new_durchlauf_dialog({
				vorlage: vorlage_with_mietvertrag,
			});
		});
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");
		cy.wait(2000); // Vorlage laden + iteration_doctype setzen

		// iteration_doctype-Wert auslesen
		cy.window().then((win) => {
			const dlg = win.cur_dialog;
			cy.log(`cur_dialog title: ${dlg?.title}`);
			cy.log(`iteration_doctype value: ${dlg?.get_value("iteration_doctype")}`);
		});

		// Button klicken (öffnet Picker)
		cy.get('.modal:visible [data-fieldname="pick_objects_btn"] button, .modal:visible [data-fieldname="pick_objects_btn"]')
			.last()
			.click({ force: true });
		cy.wait(1500);

		// Jetzt muss zweiter Dialog (Picker) offen sein
		cy.window().then((win) => {
			const $allDialogs = win.$(".modal-dialog:visible");
			cy.log(`Anzahl sichtbare modal-dialog: ${$allDialogs.length}`);
			expect($allDialogs.length, "2 Dialoge offen (Parent + Picker)").to.be.gte(2);

			const $picker = $allDialogs.last();
			const widthPx = $picker.outerWidth();
			const inlineStyle = $picker.attr("style") || "";
			const computedMaxWidth = win.getComputedStyle($picker[0]).maxWidth;
			const viewportWidth = win.innerWidth;
			const target_vw = win.frappe?.boot?.hv_ui?.picker_modal_width_vw;
			const expectedMin = viewportWidth * (target_vw / 100) * 0.95;

			cy.log(`Viewport: ${viewportWidth}px (target: ${target_vw}vw)`);
			cy.log(`Picker width: ${widthPx}px (expected ≥ ${expectedMin}px)`);
			cy.log(`Picker inline: ${inlineStyle}`);
			cy.log(`Picker computed max-width: ${computedMaxWidth}`);
			cy.log(`Picker class: ${$picker.attr("class")}`);

			expect(
				widthPx,
				`Picker im Serienbrief-Flow: ${widthPx}px, sollte ≥ ${expectedMin}px sein`
			).to.be.greaterThan(expectedMin);
		});
	});

	it("MultiSelectDialog-Picker wird auf 92vw gestreckt (direkt, ohne Serienbrief-Wrapper)", () => {
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		cy.window({ timeout: 30000 }).its("frappe.boot.hv_ui").should("exist");

		// Direkter MultiSelectDialog-Aufruf wie im Serienbrief-Picker — wir
		// umgehen den Serienbrief-Dialog, um nur die widen_modal-Logik zu testen.
		cy.window().then((win) => {
			const picker = new win.frappe.ui.form.MultiSelectDialog({
				doctype: "Mietvertrag",
				target: null,
				setters: { status: null },
				add_filters_group: 1,
				action(selections) {},
			});
			win._cy_picker = picker;

			if (win.hausverwaltung?.ui?.widen_modal) {
				win.hausverwaltung.ui.widen_modal(picker.dialog || picker);
			}
		});

		// Warten bis Picker-Modal in DOM und widen_modal-Retries durch sind
		cy.get(".modal-dialog:visible", { timeout: 10000 }).should("exist");
		cy.wait(1000);

		cy.window().then((win) => {
			const $allDialogs = win.$(".modal-dialog:visible");
			const $picker = $allDialogs.last();
			const widthPx = $picker.outerWidth();
			const inlineStyle = $picker.attr("style") || "";
			const computedMaxWidth = win.getComputedStyle($picker[0]).maxWidth;
			const viewportWidth = win.innerWidth;
			const hv_ui = win.frappe?.boot?.hv_ui || {};
			const target_vw = hv_ui.picker_modal_width_vw;

			cy.log(`hv_ui: ${JSON.stringify(hv_ui)}`);
			cy.log(`Viewport: ${viewportWidth}px (target: ${target_vw}vw)`);
			cy.log(`Picker outerWidth: ${widthPx}px`);
			cy.log(`Picker inline style: ${inlineStyle}`);
			cy.log(`Picker computed max-width: ${computedMaxWidth}`);
			cy.log(`Picker class: ${$picker.attr("class")}`);

			const expectedMin = viewportWidth * (target_vw / 100) * 0.95;
			expect(
				widthPx,
				`Picker outerWidth (${widthPx}px) sollte ≥ ${expectedMin}px sein (${target_vw}vw von ${viewportWidth}px). Inline: "${inlineStyle}". Computed max-width: "${computedMaxWidth}".`
			).to.be.greaterThan(expectedMin);
		});
	});
});
