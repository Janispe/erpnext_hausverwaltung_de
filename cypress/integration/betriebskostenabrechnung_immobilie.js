const API_BASE =
	"hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie";

context("Betriebskostenabrechnung Immobilie", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
	});

	it("Listenansicht öffnet", () => {
		cy.go_to_list("Betriebskostenabrechnung Immobilie");
		cy.get(".frappe-list").should("exist");
	});

	it("Neu-Form öffnet ohne Fehler", () => {
		cy.new_form("Betriebskostenabrechnung Immobilie");
		cy.window().its("cur_frm").should("not.be.null");
		cy.get(".error-message:visible").should("not.exist");
	});

	context("Submitted Doc: Versand-Dialog", () => {
		let docName = null;

		before(() => {
			cy.login();
			cy.first_doc_name("Betriebskostenabrechnung Immobilie", [["docstatus", "=", 1]]).then(
				(name) => {
					docName = name;
				}
			);
		});

		it("Custom Button 'Abrechnungen versenden' öffnet Dialog", function () {
			if (!docName) this.skip();

			cy.open_doc("Betriebskostenabrechnung Immobilie", docName);
			cy.window().its("cur_frm.doc.name").should("eq", docName);

			cy.get(".page-container:visible button")
				.contains("Abrechnungen versenden")
				.should("exist")
				.click({ force: true });

			cy.get(".modal:visible", { timeout: 10000 }).should("exist");
			cy.get(".modal:visible").find('[data-fieldname="mode"]').should("exist");
			cy.get(".modal:visible").find('[data-fieldname="serienbrief_vorlage"]').should("exist");

			cy.get(".modal:visible .btn-modal-close").click();
		});
	});

	context("API Permissions (nonexistent docname)", () => {
		const methods = [
			"get_mieter_abrechnungen",
			"get_verteilungsbasis",
			"dispatch_mieter_abrechnungen",
			"download_batch_print_html",
		];

		methods.forEach((m) => {
			it(`${m}: nonexistent doc → kein 200`, () => {
				cy.api_post(`${API_BASE}.${m}`, { docname: "NONEXISTENT-BKI-999" }).then((res) => {
					expect(res.status).to.not.eq(200);
				});
			});
		});
	});
});
