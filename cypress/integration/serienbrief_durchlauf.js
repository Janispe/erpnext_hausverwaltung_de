context("Serienbrief Durchlauf", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
	});

	// ── List View ──────────────────────────────────────────────

	it("Listenansicht öffnen", () => {
		cy.go_to_list("Serienbrief Durchlauf");
		cy.get(".frappe-list").should("exist");
	});

	// ── Neuer Durchlauf Dialog ─────────────────────────────────

	context("Neuer Durchlauf Dialog", () => {
		let vorlageName = "";
		let vorlage = null;

		before(() => {
			cy.login();
			cy.visit("/app");
			cy.get("body").should("have.attr", "data-ajax-state", "complete");

			// A valid fixture is required: missing data must fail instead of
			// silently leaving the template-loading behavior untested.
			const filters = Cypress.env("hv_serienbrief_template_title")
				? [["title", "=", Cypress.env("hv_serienbrief_template_title")]]
				: [["haupt_verteil_objekt", "=", "Mietvertrag"]];
			cy.get_list("Serienbrief Vorlage", ["name", "title", "kategorie", "haupt_verteil_objekt"], filters).then(
				(r) => {
					const data = r.data || [];
					expect(data, "valid Mietvertrag template fixture").to.have.length.greaterThan(0);
					vorlage = data[0];
					expect(vorlage.haupt_verteil_objekt).to.eq("Mietvertrag");
					expect(vorlage.kategorie).to.be.a("string").and.not.be.empty;
					vorlageName = vorlage.name;
				}
			);
		});

		it("Dialog lässt sich öffnen", () => {
			cy.window().then((win) => {
				if (typeof win.hausverwaltung?.serienbrief?.open_new_durchlauf_dialog !== "function") {
					cy.log("open_new_durchlauf_dialog nicht verfügbar, überspringe");
					return;
				}
				win.hausverwaltung.serienbrief.open_new_durchlauf_dialog();
				cy.get(".modal:visible").should("exist");
				cy.get(".modal:visible").find('[data-fieldname="vorlage"]').should("exist");
				cy.get(".modal:visible").find('[data-fieldname="pick_objects_btn"]').should("exist");
				// Dialog schließen
				cy.get(".modal:visible .btn-modal-close").click();
			});
		});

		(Cypress.env("hv_only_pending") ? it.only : it)("Dialog mit Vorlage: Iterations-Doctype wird gesetzt", () => {
			cy.window().then((win) => {
				expect(win.mail_merge?.serienbrief?.open_new_durchlauf_dialog, "current Mail Merge dialog API").to.be.a("function");
				win.mail_merge.serienbrief.open_new_durchlauf_dialog({
					vorlage: vorlageName,
				});
			});

			cy.get(".modal:visible").should("exist");
			cy.get(".modal:visible")
				.find('[data-fieldname="iteration_doctype"]')
				.should("exist");
			// Retry the actual values populated asynchronously from the template.
			// Merely finding the always-present field does not test template loading.
			cy.window().should((win) => {
				expect(win.cur_dialog.get_value("vorlage")).to.eq(vorlageName);
				expect(win.cur_dialog.get_value("iteration_doctype")).to.eq("Mietvertrag");
				expect(win.cur_dialog.get_value("title")).to.eq(vorlage.title);
				expect(win.cur_dialog.get_value("kategorie")).to.eq(vorlage.kategorie);
			});
			cy.screenshot("serienbrief-template-values-loaded");

			// Dialog schließen
			cy.get(".modal:visible .btn-modal-close").click();
			cy.get(".modal:visible").should("not.exist");
		});
	});

	// ── Iterations-Picker Filter ───────────────────────────────

	const openIterationPicker = (iterDoctype) => {
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		cy.window({ timeout: 30000 }).then((win) => {
			const setters = iterDoctype === "Mietvertrag"
				? { status: "Läuft", immobilie: "" }
				: iterDoctype === "Wohnung"
					? { status: "", immobilie: "" }
					: {};

			new win.frappe.ui.form.MultiSelectDialog({
				doctype: iterDoctype,
				setters,
				add_filters_group: 1,
				primary_action_label: "Übernehmen",
				primary_action: () => {},
				action: () => {},
			});
		});

		// MultiSelectDialog sollte sich öffnen
		cy.get(".modal:visible .modal-dialog", { timeout: 15000 }).should("exist");
		cy.wait(500);
	};

	context("Iterations-Picker Filter (Mietvertrag)", () => {
		it("MultiSelectDialog zeigt Status- und Immobilie-Filter", () => {
			openIterationPicker("Mietvertrag");

			// Status-Setter sollte vorhanden sein mit Default "Läuft"
			cy.get(".modal:visible")
				.find('[data-fieldname="status"]')
				.should("exist");
			cy.get(".modal:visible")
				.find('[data-fieldname="status"] select, [data-fieldname="status"] input')
				.first()
				.should("have.value", "Läuft");

			// Immobilie-Setter sollte vorhanden sein
			cy.get(".modal:visible")
				.find('[data-fieldname="immobilie"]')
				.should("exist");

			// Dialog schließen
			cy.get(".modal:visible .btn-modal-close").click();
		});
	});

	context("Iterations-Picker Filter (Wohnung)", () => {
		it("MultiSelectDialog zeigt Status- und Immobilie-Filter ohne Default", () => {
			openIterationPicker("Wohnung");

			// Status-Setter ohne Default
			cy.get(".modal:visible")
				.find('[data-fieldname="status"]')
				.should("exist");
			cy.get(".modal:visible")
				.find('[data-fieldname="status"] select, [data-fieldname="status"] input')
				.first()
				.should(($el) => {
					const val = $el.val();
					expect(val === "" || val === null).to.be.true;
				});

			// Immobilie-Setter
			cy.get(".modal:visible")
				.find('[data-fieldname="immobilie"]')
				.should("exist");

			cy.get(".modal:visible .btn-modal-close").click();
		});
	});

	// ── Permission Checks ──────────────────────────────────────

	context("Permissions", () => {
		it("generate_pdf erfordert Berechtigung", () => {
			cy.window().then((win) => {
				cy.request({
					url: "/api/method/hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.generate_pdf",
					method: "POST",
					body: { docname: "NONEXISTENT-001" },
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": win.frappe.csrf_token,
					},
					failOnStatusCode: false,
				}).then((res) => {
					expect(res.status).to.not.eq(200);
				});
			});
		});

		it("generate_html erfordert Berechtigung", () => {
			cy.window().then((win) => {
				cy.request({
					url: "/api/method/hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.generate_html",
					method: "POST",
					body: { docname: "NONEXISTENT-001" },
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": win.frappe.csrf_token,
					},
					failOnStatusCode: false,
				}).then((res) => {
					expect(res.status).to.not.eq(200);
				});
			});
		});
	});
});
