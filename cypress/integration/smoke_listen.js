context("Smoke: Listenansichten öffnen", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
	});

	const doctypes = [
		"Immobilie",
		"Mietvertrag",
		"Mieterwechsel",
		"Eigentuemer",
		"Mietrechnungen Durchlauf",
		"Betriebskostenabrechnung Immobilie",
		"Betriebskostenabrechnung Mieter",
		"Bankauszug Import",
		"Serienbrief Vorlage",
	];

	doctypes.forEach((doctype) => {
		it(`Liste "${doctype}" öffnet ohne Fehler`, () => {
			cy.go_to_list(doctype);
			cy.get(".frappe-list").should("exist");
			cy.get(".error-message:visible").should("not.exist");
		});
	});
});
