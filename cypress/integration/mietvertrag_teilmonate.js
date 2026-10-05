/** Real form + server preview. Unsaved documents keep the UI tests side-effect free. */
const PREVIEW = "hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.vorschau_teilmonatsmiete";

context("Mietvertrag: Monatsmiete und Teilmonatsmiete", { retries: 0 }, () => {
	let invoiceCalls;
	before(() => {
		const host = new URL(Cypress.config("baseUrl")).hostname;
		expect(host, "explicitly isolated/local UI test site").to.be.oneOf(["127.0.0.1", "localhost", "fac.localhost"]);
	});
	beforeEach(() => {
		cy.viewport(Cypress.currentTest.title.includes("schmalen") ? 412 : 1400, 960);
		invoiceCalls = [];
		cy.intercept("POST", "**/api/method/hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.*", (request) => {
			invoiceCalls.push(request.url);
			request.continue();
		});
		cy.intercept("POST", `**/api/method/${PREVIEW}`).as("partMonthPreview");
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 30000 }).its("frappe.csrf_token").should("exist");
		cy.window().then((win) => win.frappe.new_doc("Mietvertrag"));
		cy.window({ timeout: 30000 }).should((win) => {
			expect(win.cur_frm?.doc?.doctype).to.eq("Mietvertrag");
			expect(win.cur_frm?.doc?.__islocal).to.eq(1);
		});
		cy.window().then(async (win) => {
			const frm = win.cur_frm;
			await frm.set_value({ von: "2027-01-16", bis: "2027-03-15" });
			frm.clear_table("miete");
			Object.assign(frm.add_child("miete"), { von: "2027-01-16", art: "Monatlich", miete: 620 });
			frm.clear_table("miete_teilmonate");
			frm.refresh_field("miete");
			await frm.script_manager.trigger("refresh");
		});
		cy.contains(".form-tabs .nav-link", "Miete und Betriebskosten").click();
	});

	function openDialog() {
		cy.get('.page-container:visible [data-fieldname="teilmonatsmiete_festlegen"] button').click();
		cy.window().should((win) => {
			expect(win.cur_dialog?.title).to.eq("Teilmonatsmiete festlegen");
			expect(win.cur_dialog?.display).to.eq(true);
		});
		cy.wait("@partMonthPreview").its("response.body.message.amount").should("eq", 320);
	}
	function field(name) {
		return cy.get(`.modal:visible [data-fieldname="${name}"] input`);
	}
	function mode(value) {
		return cy.get('.modal:visible [data-fieldname="berechnung"] select').select(value);
	}
	function previewAmount(amount) {
		cy.get("@partMonthPreview.all").should((requests) => {
			const response = requests[requests.length - 1]?.response;
			expect(response?.statusCode).to.eq(200);
			expect(response?.body.message.amount).to.eq(amount);
		});
		cy.get('[data-role="part-month-preview"]').should("contain", "2027-01");
	}
	function adopt() {
		cy.contains(".modal:visible .btn-primary", "In Mietvertrag übernehmen").click();
		cy.wait("@partMonthPreview").its("response.statusCode").should("eq", 200);
		cy.get(".modal:visible").should("not.exist");
		cy.then(() => expect(invoiceCalls, "editing does not create invoices").to.have.length(0));
	}

	it("zeigt Monatsmiete/Gültig ab und berechnet den Einzugsmonat mit echten Kalendertagen", () => {
		cy.window().then((win) => {
			const fields = win.cur_frm.get_field("miete").grid.docfields;
			expect(fields.find((df) => df.fieldname === "miete").label).to.eq("Monatsmiete");
			expect(fields.find((df) => df.fieldname === "von").label).to.eq("Gültig ab");
			expect(fields.find((df) => df.fieldname === "art").hidden).to.eq(1);
			expect(win.cur_frm.get_field("kaution").grid.docfields.find((df) => df.fieldname === "miete").label).to.eq("Betrag");
			expect(win.cur_frm.get_field("betriebskosten").grid.docfields.find((df) => df.fieldname === "art").hidden || 0).to.eq(0);
		});
		openDialog();
		cy.get('[data-role="part-month-preview"]').should("contain", "320");
		field("von").should("have.value", "16.01.2027");
		field("bis").should("have.value", "31.01.2027");
		adopt();
		cy.window().then((win) => {
			expect(win.cur_frm.doc.miete_teilmonate).to.have.length(1);
			expect(win.cur_frm.doc.miete_teilmonate[0]).to.include({
				von: "2027-01-16", bis: "2027-01-31", berechnung: "Automatisch anteilig", betrag: 0,
			});
		});
	});

	it("übernimmt einen vereinbarten Betrag statt der anteiligen Einzugsmiete", () => {
		openDialog();
		mode("Festbetrag");
		field("betrag").should("have.value", "");
		cy.contains(".modal:visible .btn-primary", "In Mietvertrag übernehmen").click();
		cy.get(".modal:visible").should("contain", "Bitte den vereinbarten Mietbetrag eingeben");
		cy.window().then((win) => expect(win.cur_frm.doc.miete_teilmonate || []).to.have.length(0));
		field("betrag").clear().type("300").blur();
		previewAmount(300);
		adopt();
		cy.window().then((win) => {
			expect(win.cur_frm.doc.miete[0].miete).to.eq(620);
			expect(win.cur_frm.doc.miete_teilmonate[0]).to.include({ berechnung: "Festbetrag", betrag: 300 });
		});
	});

	it("akzeptiert ausdrücklich 0 und überschreibt die bestehende Regel statt sie zu duplizieren", () => {
		openDialog();
		mode("Festbetrag");
		field("betrag").clear().type("0").blur();
		previewAmount(0);
		adopt();
		cy.get('.page-container:visible [data-fieldname="teilmonatsmiete_festlegen"] button').click();
		cy.window().should((win) => expect(win.cur_dialog?.display).to.eq(true));
		cy.wait("@partMonthPreview").its("response.body.message.amount").should("eq", 0);
		mode("Automatisch anteilig");
		previewAmount(320);
		adopt();
		cy.window().then((win) => {
			expect(win.cur_frm.doc.miete_teilmonate).to.have.length(1);
			expect(win.cur_frm.doc.miete_teilmonate[0].berechnung).to.eq("Automatisch anteilig");
		});
	});

	it("bietet den letzten Mietmonat an und zeigt bei kurzem Festzeitraum auch die übrigen Monatstage", () => {
		openDialog();
		cy.get('.modal:visible [data-fieldname="zeitraum"] select').select("Letzter Mietmonat");
		cy.wait("@partMonthPreview").its("response.body.message.amount").should("eq", 300);
		field("von").should("have.value", "01.03.2027");
		field("bis").should("have.value", "15.03.2027");
		cy.get('.modal:visible [data-fieldname="zeitraum"] select').select("Erster Mietmonat");
		cy.wait("@partMonthPreview");
		field("bis").click();
		cy.get('.datepicker--cell-day[data-date="20"][data-month="0"][data-year="2027"]:visible').click();
		field("bis").should("have.value", "20.01.2027");
		cy.window().should((win) => expect(win.cur_dialog.fields_dict.bis.value).to.eq("2027-01-20"));
		cy.wait("@partMonthPreview");
		mode("Festbetrag");
		field("betrag").should("have.value", "").type("100", { delay: 100 }).blur();
		previewAmount(320);
		cy.get('[data-role="part-month-preview"] tbody tr').should("have.length", 2);
		cy.get('[data-role="part-month-preview"]').should("contain", "Festbetrag");
		adopt();
		cy.window().then((win) => expect(win.cur_frm.doc.miete_teilmonate[0]).to.include({
			von: "2027-01-16", bis: "2027-01-20", berechnung: "Festbetrag", betrag: 100,
		}));
	});

	it("zeigt ältere Feststaffeln ohne sie als Monatsmieten umzudeuten", () => {
		cy.window().then(async (win) => {
			const frm = win.cur_frm;
			frm.doc.miete[0].art = "Gesamter Zeitraum";
			frm.doc.miete[0].miete = 300;
			await frm.script_manager.trigger("refresh");
			expect(frm.get_field("miete").grid.docfields.find((df) => df.fieldname === "art").hidden).to.eq(0);
			expect(frm.get_field("miete").df.description).to.contain("ältere Festbeträge");
			expect(frm.doc.miete[0]).to.include({ art: "Gesamter Zeitraum", miete: 300 });
		});
	});

	it("verhindert eine Teilmonatsregel ohne vereinbarte Monatsmiete", () => {
		cy.window().then(async (win) => {
			win.cur_frm.clear_table("miete");
			win.cur_frm.refresh_field("miete");
			await win.cur_frm.script_manager.trigger("refresh");
		});
		cy.get('.page-container:visible [data-fieldname="teilmonatsmiete_festlegen"] button').click();
		cy.wait("@partMonthPreview").then(({ response }) => {
			expect(response.statusCode).to.be.oneOf([417, 422]);
			expect(JSON.stringify(response.body)).to.contain("Monatsmiete");
		});
		cy.get(".modal:visible").last().should("contain", "Bitte zuerst").and("contain", "Monatsmiete");
		cy.window().should((win) => {
			expect(win.cur_dialog?.title).not.to.eq("Teilmonatsmiete festlegen");
			expect(win.cur_dialog?.display).to.eq(true);
		});
		cy.contains(".modal:visible", "Bitte zuerst").find(".btn-modal-close").click();
		cy.get(".modal:visible").should("have.length", 1);
		cy.contains(".modal:visible .btn-primary", "In Mietvertrag übernehmen").click();
		cy.wait("@partMonthPreview").its("response.statusCode").should("be.oneOf", [417, 422]);
		cy.get(".modal:visible").last().should("contain", "Bitte zuerst");
		cy.window().then((win) => {
			expect(win.cur_frm.doc.miete_teilmonate || []).to.have.length(0);
			expect(win.cur_frm.doc.__islocal).to.eq(1);
		});
		cy.then(() => expect(invoiceCalls, "rejected input does not create invoices").to.have.length(0));
	});

	it("ändert den Zeitraum einer geladenen Regel und erhält die übrigen Regeln", () => {
		let originalName;
		let otherName;
		cy.window().then((win) => {
			const frm = win.cur_frm;
			const firstRule = Object.assign(frm.add_child("miete_teilmonate"), {
				von: "2027-01-16", bis: "2027-01-31", berechnung: "Festbetrag", betrag: 300,
			});
			const otherRule = Object.assign(frm.add_child("miete_teilmonate"), {
				von: "2027-03-01", bis: "2027-03-15", berechnung: "Festbetrag", betrag: 0,
			});
			originalName = firstRule.name;
			otherName = otherRule.name;
			frm.refresh_field("miete_teilmonate");
		});
		cy.get('.page-container:visible [data-fieldname="teilmonatsmiete_festlegen"] button').click();
		cy.window().should((win) => expect(win.cur_dialog?.display).to.eq(true));
		cy.wait("@partMonthPreview").its("response.body.message.amount").should("eq", 300);
		field("bis").click();
		cy.get('.datepicker--cell-day[data-date="25"][data-month="0"][data-year="2027"]:visible').click();
		field("bis").should("have.value", "25.01.2027");
		previewAmount(420);
		adopt();
		cy.window().then((win) => {
			const rows = win.cur_frm.doc.miete_teilmonate;
			expect(rows).to.have.length(2);
			expect(rows.find((row) => row.name === originalName)).to.include({
				von: "2027-01-16", bis: "2027-01-25", berechnung: "Festbetrag", betrag: 300,
			});
			expect(rows.find((row) => row.name === otherName)).to.include({
				von: "2027-03-01", bis: "2027-03-15", berechnung: "Festbetrag", betrag: 0,
			});
		});
	});

	it("bleibt auf einem schmalen Bildschirm bedienbar", () => {
		cy.viewport(412, 915);
		openDialog();
		mode("Festbetrag");
		field("betrag").should("have.value", "").type("300", { delay: 100 }).blur();
		previewAmount(300);
		cy.get(".modal:visible .modal-dialog").then(($dialog) => {
			const rect = $dialog[0].getBoundingClientRect();
			expect(rect.left).to.be.at.least(0);
			expect(rect.right).to.be.at.most(412);
		});
		cy.screenshot("teilmonatsmiete-mobile", { capture: "viewport" });
		adopt();
	});
});
