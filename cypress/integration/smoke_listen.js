context("Smoke: Listenansichten öffnen", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
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
		"Vorgang",
		"Serienbrief Vorlage",
	];

	doctypes.forEach((doctype) => {
		it(`Liste "${doctype}" öffnet ohne Fehler`, () => {
			cy.go_to_list(doctype);
			cy.get(".frappe-list").should("exist");
			cy.get("body").should("not.contain", "Internal Server Error");
			cy.get("body").should("not.contain", "Server Error");
		});
	});
});
