const FIX = "hausverwaltung.cypress_fixtures";

context("E2E: EÜR mit Wertprüfung gegen Echtdaten", () => {
	let env = null;
	let createdEurName = null;

	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");

		cy.api_post(`${FIX}.seed`).then((res) => {
			expect(
				res.status,
				`seed failed (${res.status}): ${JSON.stringify(res.body).slice(0, 400)}`
			).to.eq(200);
			env = res.body.message;
			cy.log(`Test-Env: ${JSON.stringify(env)}`);
		});
	});

	after(() => {
		if (createdEurName) {
			cy.api_post(`${FIX}.cleanup_test_eur`, { name: createdEurName }).then((res) => {
				cy.log(`cleanup: ${JSON.stringify(res.body && res.body.message)}`);
			});
		}
	});

	it("Test-Env hat Immobilie + Kostenstelle + Zeitraum", function () {
		if (!env) this.skip();
		expect(env.immobilie, env.reason || "").to.be.a("string").and.not.be.empty;
		expect(env.kostenstelle).to.be.a("string").and.not.be.empty;
		expect(env.von).to.match(/^\d{4}-\d{2}-\d{2}$/);
		expect(env.bis).to.match(/^\d{4}-\d{2}-\d{2}$/);
	});

	it("EÜR-Doc-Summen stimmen exakt mit Report-Output überein", function () {
		if (!env || !env.immobilie || !env.gl_entry_count) {
			this.skip();
		}

		cy.api_post(`${FIX}.get_expected_eur_totals`, {
			immobilie: env.immobilie,
			from_date: env.von,
			to_date: env.bis,
			company: env.company,
		}).then((res) => {
			expect(res.status).to.eq(200);
			const expected = res.body.message;
			cy.log(`expected: ${JSON.stringify(expected)}`);

			cy.visit("/app/einnahmen-ueberschuss-rechnung/new");
			cy.get("body").should("have.attr", "data-ajax-state", "complete");
			cy.window().its("cur_frm").should("not.be.null");

			cy.window().then((win) => {
				const frm = win.cur_frm;
				return Promise.all([
					frm.set_value("company", env.company),
					frm.set_value("immobilie", env.immobilie),
					frm.set_value("from_date", env.von),
					frm.set_value("to_date", env.bis),
					frm.set_value("umlage_method", "Kontenstruktur"),
					frm.set_value("include_non_euer_accounts", 1),
				]);
			});

			cy.save();

			cy.window().then((win) => {
				const doc = win.cur_frm.doc;
				createdEurName = doc.name;
				cy.log(
					`doc: einnahmen=${doc.summe_einnahmen} ausgaben=${doc.summe_ausgaben} ueberschuss=${doc.ueberschuss}`
				);

				// Exakter Vergleich: get_expected_eur_totals nutzt denselben
				// Report-Code wie die Doc, daher müssen die Werte auf den Cent
				// genau übereinstimmen. Toleranz nur für Float-Rundung.
				const tol = 0.01;

				expect(
					Math.abs(parseFloat(doc.summe_einnahmen) - expected.einnahmen),
					`summe_einnahmen=${doc.summe_einnahmen} vs erwartet=${expected.einnahmen}`
				).to.be.lessThan(tol);

				expect(
					Math.abs(parseFloat(doc.summe_ausgaben) - expected.ausgaben),
					`summe_ausgaben=${doc.summe_ausgaben} vs erwartet=${expected.ausgaben}`
				).to.be.lessThan(tol);

				expect(
					Math.abs(parseFloat(doc.ueberschuss) - expected.ueberschuss),
					`ueberschuss=${doc.ueberschuss} vs erwartet=${expected.ueberschuss}`
				).to.be.lessThan(tol);

				expect(
					doc.positionen,
					"positionen muss befüllt sein"
				).to.have.length.at.least(1);
			});
		});
	});

	it("Doc-interne Konsistenz: Überschuss = Einnahmen − Ausgaben", function () {
		if (!createdEurName) this.skip();

		cy.visit(`/app/einnahmen-ueberschuss-rechnung/${encodeURIComponent(createdEurName)}`);
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		cy.window()
			.its("cur_frm.doc")
			.then((doc) => {
				const computed =
					parseFloat(doc.summe_einnahmen) - parseFloat(doc.summe_ausgaben);
				expect(
					Math.abs(parseFloat(doc.ueberschuss) - computed),
					"ueberschuss == einnahmen - ausgaben"
				).to.be.lessThan(0.05);
			});
	});
});
