const API_BASE =
	"hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import";

context("Bankauszug Import", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
	});

	it("Listenansicht öffnet", () => {
		cy.go_to_list("Bankauszug Import");
		cy.get(".frappe-list").should("exist");
	});

	it("Neu-Form öffnet ohne Fehler", () => {
		cy.new_form("Bankauszug Import");
		cy.window().its("cur_frm").should("not.be.null");
		cy.get(".error-message:visible").should("not.exist");
	});

	context("Bestehender Import: Phase + Buttons", () => {
		let docName = null;

		before(() => {
			cy.login();
			cy.first_doc_name("Bankauszug Import").then((name) => {
				docName = name;
			});
		});

		it("Form öffnet und zeigt Aktionen-Gruppe", function () {
			if (!docName) this.skip();

			cy.open_doc("Bankauszug Import", docName);
			cy.window().its("cur_frm.doc.name").should("eq", docName);

			cy.window().its("cur_frm.__hv_phase").should("be.oneOf", [
				"empty",
				"phase1",
				"phase2",
				"done",
			]);

			cy.get(".page-container:visible .inner-group-button").should("exist");
		});
	});

	context("API Permissions (invalid args)", () => {
		// Frappe wickelt Python-TypeError/ValidationError als HTTP 500 ein.
		// Hier prüfen wir nur, dass der Endpoint überhaupt erreichbar ist und
		// nicht 200 mit fehlerhaftem Erfolg zurückgibt.
		it("parse_csv: ohne docname kein 200", () => {
			cy.api_post(`${API_BASE}.parse_csv`, {}).then((res) => {
				expect(res.status).to.not.eq(200);
			});
		});

		it("manually_reconcile_row: invalid args → kein 200", () => {
			cy.api_post(`${API_BASE}.manually_reconcile_row`, {
				docname: "NONEXISTENT-BAI-999",
				row_idx: 0,
				invoice_allocations: [],
			}).then((res) => {
				expect(res.status).to.not.eq(200);
			});
		});

		it("create_standalone_payment_for_row: invalid args → kein 200", () => {
			cy.api_post(`${API_BASE}.create_standalone_payment_for_row`, {
				docname: "NONEXISTENT-BAI-999",
				row_idx: 0,
			}).then((res) => {
				expect(res.status).to.not.eq(200);
			});
		});
	});
});
