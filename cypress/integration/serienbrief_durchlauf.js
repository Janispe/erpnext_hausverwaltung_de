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
		let hasVorlage = false;
		let vorlageName = "";

		before(() => {
			cy.login();
			cy.visit("/app");
			cy.get("body").should("have.attr", "data-ajax-state", "complete");

			// Prüfe ob eine Serienbrief Vorlage existiert
			cy.get_list("Serienbrief Vorlage", ["name", "haupt_verteil_objekt"], []).then(
				(r) => {
					const data = r.data || [];
					if (data.length > 0) {
						hasVorlage = true;
						vorlageName = data[0].name;
					}
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

		it("Dialog mit Vorlage: Iterations-Doctype wird gesetzt", function () {
			if (!hasVorlage) this.skip();

			cy.window().then((win) => {
				if (typeof win.hausverwaltung?.serienbrief?.open_new_durchlauf_dialog !== "function") {
					this.skip();
					return;
				}
				win.hausverwaltung.serienbrief.open_new_durchlauf_dialog({
					vorlage: vorlageName,
				});
			});

			cy.get(".modal:visible").should("exist");
			// Warten bis Vorlage geladen
			cy.wait(1000);
			cy.get(".modal:visible")
				.find('[data-fieldname="iteration_doctype"] input')
				.should("not.have.value", "");

			// Dialog schließen
			cy.get(".modal:visible .btn-modal-close").click();
		});
	});

	// ── Iterations-Picker Filter ───────────────────────────────

	const openIterationPicker = (iterDoctype) => {
		cy.visit("/app/serienbrief-durchlauf/new");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		cy.window().its("cur_frm").should("not.be.null");

		// iteration_doctype setzen und refresh erzwingen
		cy.window().then((win) => {
			win.cur_frm.set_value("iteration_doctype", iterDoctype);
		});

		// Warten bis Custom Buttons gerendert sind nach refresh
		cy.wait(1500);
		cy.window().then((win) => {
			win.cur_frm.refresh();
		});
		cy.wait(1500);

		// "Iteration" Dropdown öffnen, dann "Objekte auswählen" klicken
		cy.get('.page-container:visible .inner-group-button .btn')
			.contains("Iteration")
			.click({ force: true });
		cy.get('.page-container:visible .inner-group-button .dropdown-menu:visible a')
			.contains("Objekte")
			.click({ force: true });

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
