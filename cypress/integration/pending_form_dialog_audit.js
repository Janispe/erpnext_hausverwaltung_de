/** Targeted replacements for two historical it.skip cases; isolated site only. */
const auditCase = (key, title, run) => {
	if (!Cypress.env("pending_audit_case") || Cypress.env("pending_audit_case") === key) it(title, run);
};
context("Pending audit: Mietvertrag and Mietrechnungen-Durchlauf", { retries: 0 }, () => {
	beforeEach(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe.csrf_token").should("exist");
	});

	auditCase("form", "Mietvertrag: existing fixture form initializes and exposes real custom buttons", () => {
		cy.get_list("Mietvertrag", ["name", "kunde", "wohnung"], [
			["name", "like", "M1001%"], ["kunde", "is", "set"], ["wohnung", "is", "set"],
		]).then((result) => {
			const fixture = result.data[0];
			expect(fixture, "complete isolated sample lease").to.exist;
			cy.get_list("Mietvertrag", ["name", "wohnung"], [["kunde", "=", fixture.kunde]]).then((leases) => {
				expect(leases.data, "one lease per accounting customer").to.deep.eq([{ name: fixture.name, wohnung: fixture.wohnung }]);
			});
			cy.window().then((win) => win.frappe.set_route("Form", "Mietvertrag", fixture.name));
			cy.window({ timeout: 30000 }).should((win) => {
				expect(win.cur_frm?.doc?.name).to.eq(fixture.name);
				expect(win.cur_frm?.doc?.kunde).to.eq(fixture.kunde);
				expect(win.cur_frm?.doc?.wohnung).to.eq(fixture.wohnung);
			});
			cy.get(".page-container:visible").should("contain", "Staffelmieten sortieren").and("contain", "Sollstellungen prüfen");
			cy.get(".page-container:visible .inner-group-button").should("exist");
			cy.contains(".page-container:visible .inner-group-button .btn", /Accounting|Buchhaltung/).click();
			cy.get(".page-container:visible .dropdown-menu:visible").should("contain", "Mieterkonto");
			cy.get(".error-message:visible").should("not.exist");
			cy.writeFile("output/playwright/bugtesting-2026-10-04/pending-mietvertrag-readback.json", fixture);
		});
	});

	auditCase("dialog", "Mietrechnungen-Durchlauf: actual new-form dialog closes and stays closed", () => {
		const generatorCalls = [];
		cy.intercept("POST", "**/api/method/hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen", (request) => {
			generatorCalls.push(request.body);
			request.continue();
		});
		cy.window().then((win) => win.frappe.new_doc("Mietrechnungen Durchlauf"));
		cy.window({ timeout: 30000 }).should((win) => {
			expect(win.cur_frm?.doc?.doctype).to.eq("Mietrechnungen Durchlauf");
			expect(win.cur_frm?.doc?.__islocal).to.eq(1);
		});
		cy.get(".modal:visible", { timeout: 15000 }).should("contain", "Mietrechnungen erstellen");
		["company", "monat", "jahr"].forEach((field) => {
			cy.get(`.modal:visible [data-fieldname="${field}"]`).should("exist");
		});
		// Bootstrap can ignore hide during its fade-in transition. Frappe marks
		// the dialog ready in shown.bs.modal, after the visible animation.
		cy.window().should((win) => {
			expect(win.cur_dialog?.title).to.eq("Mietrechnungen erstellen");
			expect(win.cur_dialog?.display).to.eq(true);
		});
		cy.get(".modal:visible .btn-modal-close").click();
		cy.get(".modal:visible", { timeout: 5000 }).should("not.exist");
		cy.get(".modal-backdrop:visible").should("not.exist");
		cy.window().then((win) => win.cur_frm.refresh());
		cy.get(".modal:visible").should("not.exist");
		cy.then(() => expect(generatorCalls, "closing created no invoices").to.have.length(0));
		cy.window().then((win) => cy.writeFile("output/playwright/bugtesting-2026-10-04/pending-dialog-readback.json", {
			closed: win.cur_dialog === null,
			modal_count: win.document.querySelectorAll(".modal.show").length,
			backdrop_count: win.document.querySelectorAll(".modal-backdrop.show").length,
			generator_calls: generatorCalls.length,
		}));
	});
});
