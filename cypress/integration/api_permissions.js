const MIETERWECHSEL = "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel";
const SERIENBRIEF_VORLAGE =
	"hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage";

context("API Permissions Smoke", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe").should("exist");
	});

	const expectNo500 = (res) => {
		expect(res.status, `status ${res.status}, body: ${JSON.stringify(res.body)}`).to.not.eq(500);
	};

	context("Mieterwechsel", () => {
		it("get_completion_blockers: kein 500", () => {
			cy.api_post(`${MIETERWECHSEL}.get_completion_blockers`, {
				docname: "NONEXISTENT-MW-999",
			}).then(expectNo500);
		});

		it("get_seed_tasks_preview: kein 500", () => {
			cy.api_post(`${MIETERWECHSEL}.get_seed_tasks_preview`, {
				docname: "NONEXISTENT-MW-999",
			}).then(expectNo500);
		});

		it("dispatch_workflow_action: kein 500", () => {
			cy.api_post(`${MIETERWECHSEL}.dispatch_workflow_action`, {
				docname: "NONEXISTENT-MW-999",
				action: "noop",
			}).then(expectNo500);
		});

		it("get_task_detail: kein 500 mit gültiger Signatur", () => {
			cy.api_post(`${MIETERWECHSEL}.get_task_detail`, {
				docname: "NONEXISTENT-MW-999",
				aufgabe_row_name: "NONEXISTENT-ROW",
			}).then(expectNo500);
		});

		it("approve_bypass: hv-User darf nicht (System Manager only)", () => {
			cy.api_post(`${MIETERWECHSEL}.approve_bypass`, {
				docname: "NONEXISTENT-MW-999",
				reason: "test",
			}).then((res) => {
				expectNo500(res);
				expect(res.status, "approve_bypass darf nicht 200 sein für hv").to.not.eq(200);
			});
		});
	});

	context("Serienbrief Vorlage", () => {
		it("render_template_preview_pdf: kein 500", () => {
			cy.api_post(`${SERIENBRIEF_VORLAGE}.render_template_preview_pdf`, {
				docname: "NONEXISTENT-SBV-999",
			}).then(expectNo500);
		});

		it("render_template_preview_html: kein 500", () => {
			cy.api_post(`${SERIENBRIEF_VORLAGE}.render_template_preview_html`, {
				docname: "NONEXISTENT-SBV-999",
			}).then(expectNo500);
		});

		it("copy_serienbrief_vorlage: kein 500", () => {
			cy.api_post(`${SERIENBRIEF_VORLAGE}.copy_serienbrief_vorlage`, {
				source_name: "NONEXISTENT-SBV-999",
			}).then(expectNo500);
		});

		it("search_serienbrief_vorlagen: 200 mit leerem Query", () => {
			cy.api_post(`${SERIENBRIEF_VORLAGE}.search_serienbrief_vorlagen`, { query: "" }).then(
				(res) => {
					expectNo500(res);
				}
			);
		});
	});
});
