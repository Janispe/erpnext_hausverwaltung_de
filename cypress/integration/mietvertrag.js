context("Mietvertrag", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
	});

	it("Listenansicht öffnet", () => {
		cy.go_to_list("Mietvertrag");
		cy.get(".frappe-list").should("exist");
	});

	it("Neu-Form öffnet ohne Fehler", () => {
		cy.new_form("Mietvertrag");
		cy.window().its("cur_frm").should("not.be.null");
		cy.get(".error-message:visible").should("not.exist");
	});

	context("Bestehender Mietvertrag", () => {
		let docName = null;

		before(() => {
			cy.login();
			cy.first_doc_name("Mietvertrag").then((name) => {
				docName = name;
			});
		});

		// Skip-Grund: cur_frm-Initialisierung der Mietvertrag-Form ist auf
		// produktiver Datenmenge zu langsam für stabile Cypress-Assertions
		// (Paperless-Link-Fetch, Staffelmieten-Sortierung, Custom-Button-Setup).
		// Reaktivieren wenn die Form-Init beschleunigt oder gegen leere Test-Daten
		// gelaufen wird.
		it.skip("Form öffnet und zeigt Custom Buttons", function () {
			if (!docName) this.skip();

			cy.visit(`/app/mietvertrag/${encodeURIComponent(docName)}`);
			cy.window({ timeout: 60000 }).should((win) => {
				expect(win.cur_frm).to.exist;
				expect(win.cur_frm.doc.name).to.eq(docName);
			});
			cy.get(".page-container:visible .inner-group-button").should("exist");
		});
	});

	context("API", () => {
		it("update_statuses_for_list ist aufrufbar", () => {
			cy.api_post("hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.update_statuses_for_list").then(
				(res) => {
					expect(res.status).to.not.eq(500);
				}
			);
		});

		it("get_mietvertrag_paperless_link erzeugt keinen 500er für nonexistent doc", () => {
			cy.api_post(
				"hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.get_mietvertrag_paperless_link",
				{ docname: "NONEXISTENT-MV-999" }
			).then((res) => {
				expect(res.status).to.not.eq(500);
			});
		});
	});
});
