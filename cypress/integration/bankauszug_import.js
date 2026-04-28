const API_BASE =
	"hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import";

context("Bankauszug Import", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
	});

	it("Listenansicht öffnet", () => {
		cy.go_to_list("Bankauszug Import");
		cy.get(".frappe-list").should("exist");
	});

	it("Neu-Form öffnet ohne Fehler", () => {
		cy.new_form("Bankauszug Import");
		cy.window().its("cur_frm").should("not.be.null");
		cy.get("body").should("not.contain", "Internal Server Error");
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
		it("parse_csv: kein 500 ohne docname", () => {
			cy.api_post(`${API_BASE}.parse_csv`, {}).then((res) => {
				expect(res.status).to.not.eq(500);
			});
		});

		it("manually_reconcile_row: kein 500 mit invalid args", () => {
			cy.api_post(`${API_BASE}.manually_reconcile_row`, {
				docname: "NONEXISTENT-BAI-999",
				row_idx: 0,
				invoice_allocations: [],
			}).then((res) => {
				expect(res.status).to.not.eq(500);
			});
		});

		it("create_standalone_payment_for_row: kein 500 mit invalid args", () => {
			cy.api_post(`${API_BASE}.create_standalone_payment_for_row`, {
				docname: "NONEXISTENT-BAI-999",
				row_idx: 0,
			}).then((res) => {
				expect(res.status).to.not.eq(500);
			});
		});
	});
});
