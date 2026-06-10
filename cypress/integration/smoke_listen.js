context("Smoke: Listenansichten öffnen", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
	});

	const doctypes = [
		"Immobilie",
		"Mietvertrag",
		"Eigentuemer",
		"Mietrechnungen Durchlauf",
		"Betriebskostenabrechnung Immobilie",
		"Betriebskostenabrechnung Mieter",
		"Bankauszug Import",
	];

	doctypes.forEach((doctype) => {
		it(`Liste "${doctype}" öffnet ohne Fehler`, () => {
			cy.go_to_list(doctype);
			cy.get(".frappe-list").should("exist");
			cy.get(".error-message:visible").should("not.exist");
		});
	});

	it('Seite "Serienbrief Vorlage" öffnet den Vorlagen-Browser ohne Fehler', () => {
		cy.visit("/app/serienbrief-vorlage");
		cy.location("pathname", { timeout: 10000 }).should("include", "serienbrief_browser");
		cy.get(".hv-serienbrief-browser-frame", { timeout: 30000 }).should("exist");
		cy.get(".error-message:visible").should("not.exist");
	});
});
