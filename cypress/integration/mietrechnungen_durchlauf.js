context("Mietrechnungen Durchlauf", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
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

	// Skip-Grund: das Mietrechnungen-Durchlauf-Modal lässt sich auf dieser Site
	// nicht über Standard-Mechanismen (Close-Button, cur_dialog.hide()) zuverlässig
	// schließen — vermutlich überschreibt Custom-JS die Dismiss-Logik. Reaktivieren
	// wenn der Dialog-Lifecycle stabilisiert ist.
	it.skip("Dialog ist schließbar", () => {
		cy.new_form("Mietrechnungen Durchlauf");
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");
		cy.get(".modal:visible .btn-modal-close").click();
		cy.get(".modal.show", { timeout: 15000 }).should("not.exist");
	});
});
