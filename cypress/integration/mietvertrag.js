context("Mietvertrag", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
	});

	it("Listenansicht öffnet", () => {
		cy.go_to_list("Mietvertrag");
		cy.get(".frappe-list").should("exist");
	});

	it("Neu-Form öffnet ohne Fehler", () => {
		cy.new_form("Mietvertrag");
		cy.window().its("cur_frm").should("not.be.null");
		cy.get("body").should("not.contain", "Internal Server Error");
	});

	context("Bestehender Mietvertrag", () => {
		let docName = null;

		before(() => {
			cy.login();
			cy.first_doc_name("Mietvertrag").then((name) => {
				docName = name;
			});
		});

		it("Form öffnet und zeigt Custom Buttons", function () {
			if (!docName) this.skip();

			cy.open_doc("Mietvertrag", docName);
			cy.window().its("cur_frm.doc.name").should("eq", docName);

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
