context("Mietrechnungen Durchlauf", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
	});

	it("Listenansicht öffnet", () => {
		cy.go_to_list("Mietrechnungen Durchlauf");
		cy.get(".frappe-list").should("exist");
	});

	it("Neu-Form öffnet automatisch den Erstellen-Dialog", () => {
		cy.new_form("Mietrechnungen Durchlauf");
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");

		cy.get(".modal:visible").find('[data-fieldname="company"]').should("exist");
		cy.get(".modal:visible").find('[data-fieldname="monat"]').should("exist");
		cy.get(".modal:visible").find('[data-fieldname="jahr"]').should("exist");
	});

	it("Dialog ist schließbar", () => {
		cy.new_form("Mietrechnungen Durchlauf");
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");
		cy.get(".modal:visible .btn-modal-close").click();
		cy.get(".modal:visible").should("not.exist");
	});
});
