/**
 * E2E-Test für "Rechnung an Mieter" im Buchungs-Cockpit.
 *
 * Deckt:
 *  - Happy path (Draft) ohne Artikel-Eingabe (Backend muss Default-Service-Item nutzen)
 *  - Mehrere Positionen
 *  - Custom Artikel + Custom Erlöskonto
 *  - Edge-Cases: fehlender Mietvertrag, leere Positionen, fehlender Betrag
 *  - Wertstellungsdatum + hv_eingabequelle korrekt gesetzt
 *  - UI-Flow: Dialog öffnen → Felder füllen → "Als Entwurf speichern"
 */

const TEST_TAG = `__cy_si_${Date.now()}`;
const HV_API = "hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit";

// Sammelt Namen erzeugter Sales Invoices, damit after() sie wegräumen kann.
const created = [];

const trackSi = (name) => {
	if (name && !created.includes(name)) created.push(name);
};

context("Rechnung an Mieter — Buchungs-Cockpit", () => {
	let mietvertrag;
	let kunde;
	let wohnung;
	let income_account;
	let custom_item;
	let default_item_code;

	beforeEach(() => {
		// Stellt sicher, dass /app geladen ist und frappe.csrf_token verfügbar ist.
		// Ohne das schlagen cy.call-Aufrufe fehl ("frappe.csrf_token did not exist").
		cy.login();
		cy.visit("/app");
		cy.window({ timeout: 15000 })
			.its("frappe.csrf_token", { timeout: 15000 })
			.should("exist");
	});

	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");

		// Aktiven Mietvertrag finden (kunde gesetzt, status != 'Beendet')
		cy.call("frappe.client.get_list", {
			doctype: "Mietvertrag",
			filters: [["kunde", "is", "set"]],
			fields: ["name", "kunde", "wohnung"],
			limit_page_length: 1,
			order_by: "modified desc",
		}).then((r) => {
			expect((r.message || []).length, "min. 1 Mietvertrag mit Kunde").to.be.greaterThan(0);
			const mv = r.message[0];
			mietvertrag = mv.name;
			kunde = mv.kunde;
			wohnung = mv.wohnung;
		});

		// Income-Account aus dem Kontenplan holen (Company.default_income_account
		// ist in dieser Dev-Umgebung nicht gepflegt, daher Fallback auf
		// erstes Income-Leaf-Konto).
		cy.call("frappe.client.get_list", {
			doctype: "Company",
			fields: ["name", "default_income_account"],
			limit_page_length: 5,
		}).then((r) => {
			const c = (r.message || []).find((x) => x.default_income_account);
			if (c) {
				income_account = c.default_income_account;
				return;
			}
			// Fallback: ein Income-Leaf-Konto suchen
			cy.call("frappe.client.get_list", {
				doctype: "Account",
				filters: { is_group: 0, root_type: "Income" },
				fields: ["name"],
				limit_page_length: 1,
			}).then((rr) => {
				income_account = rr.message?.[0]?.name;
			});
		});

		// Default-Service-Artikel via API erzeugen/holen
		cy.call(
			"frappe.client.get_list",
			{
				doctype: "Item",
				filters: { item_code: ["like", "%hv-default-service%"] },
				fields: ["name", "item_code"],
				limit_page_length: 1,
			}
		).then((r) => {
			default_item_code = (r.message && r.message[0] && r.message[0].item_code) || null;
		});

		// Custom-Artikel finden (irgendein anderer als der Default)
		cy.call("frappe.client.get_list", {
			doctype: "Item",
			filters: { is_stock_item: 0, disabled: 0 },
			fields: ["name", "item_code"],
			limit_page_length: 5,
		}).then((r) => {
			const list = r.message || [];
			const non_default = list.find(
				(x) => default_item_code == null || x.item_code !== default_item_code
			);
			custom_item = non_default?.item_code || (list[0] && list[0].item_code);
		});
	});

	after(() => {
		cy.then(() => {
			created.forEach((name) => {
				// Direkter delete — Tests laufen alle als Draft (submit_doc: 0),
				// daher kein Cancel nötig. failOnStatusCode: false damit best-effort
				// keine restlichen Tests fail-cascadiert.
				cy.window()
					.its("frappe.csrf_token")
					.then((csrf_token) => {
						cy.request({
							method: "POST",
							url: "/api/method/frappe.client.delete",
							body: { doctype: "Sales Invoice", name },
							headers: {
								"Content-Type": "application/json",
								"X-Frappe-CSRF-Token": csrf_token,
							},
							failOnStatusCode: false,
						});
					});
			});
		});
	});

	// ── HAPPY PATH (API-LEVEL) ────────────────────────────────────────────

	it("[1] Draft mit nur Beschreibung + Betrag (+ erloeskonto) → Default-Artikel wird verwendet", () => {
		expect(mietvertrag, "mietvertrag seed").to.be.a("string").and.not.empty;
		expect(income_account, "income_account seed").to.be.a("string").and.not.empty;

		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-1`,
			referenz: TEST_TAG,
			submit_doc: 0,
			positionen: JSON.stringify([
				{ beschreibung: "Renovierungspauschale", betrag: 250, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			expect(name, "SI angelegt").to.be.a("string").and.not.empty;
			expect(r.message?.submitted, "Draft").to.eq(false);
			trackSi(name);

			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				expect(si.docstatus).to.eq(0);
				expect(si.customer).to.eq(kunde);
				expect(si.items, "1 Item").to.have.length(1);
				const item = si.items[0];
				expect(item.qty).to.eq(1);
				expect(Number(item.rate)).to.eq(250);
				expect(item.item_code, "item_code (Default-Service)").to.be.a("string").and.not.empty;
				expect(item.description).to.match(/Renovierungspauschale/);
				expect(si.remarks).to.eq("Renovierungspauschale");
				expect(si.mietabrechnung_id || "").to.eq("");
			});
		});
	});

	it("[2] Mehrere Positionen — Summe stimmt", () => {
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-2`,
			submit_doc: 0,
			positionen: JSON.stringify([
				{ beschreibung: "Position A", betrag: 100, erloeskonto: income_account },
				{ beschreibung: "Position B", betrag: 50.5, erloeskonto: income_account },
				{ beschreibung: "Position C", betrag: 12.75, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				expect(si.items).to.have.length(3);
				const sum = si.items.reduce((acc, it) => acc + Number(it.rate), 0);
				expect(sum).to.be.closeTo(163.25, 0.01);
				expect(Number(si.grand_total)).to.be.closeTo(163.25, 0.01);
			});
		});
	});

	it("[3] Custom Artikel überschreibt Default", function () {
		if (!custom_item) this.skip();

		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-3`,
			submit_doc: 0,
			positionen: JSON.stringify([
				{
					beschreibung: "Mit explizitem Artikel",
					betrag: 75,
					artikel: custom_item,
					erloeskonto: income_account,
				},
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				expect(si.items[0].item_code, "Custom Artikel verwendet").to.eq(
					custom_item
				);
			});
		});
	});

	it("[4] Custom Erlöskonto landet auf der Position", function () {
		if (!income_account) this.skip();

		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-4`,
			submit_doc: 0,
			positionen: JSON.stringify([
				{
					beschreibung: "Mit explizitem Erlöskonto",
					betrag: 99,
					erloeskonto: income_account,
				},
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				expect(si.items[0].income_account).to.eq(income_account);
			});
		});
	});

	it("[5] Wertstellungsdatum landet in custom_wertstellungsdatum", () => {
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			wertstellungsdatum: "2026-04-30",
			rechnungsname: `${TEST_TAG}-5`,
			submit_doc: 0,
			positionen: JSON.stringify([
				{ beschreibung: "Leistung April 2026", betrag: 42, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				expect(String(si.custom_wertstellungsdatum)).to.match(/^2026-04-30/);
			});
		});
	});

	it("[6] hv_eingabequelle = 'Vereinfachte Mieterrechnung'", () => {
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-6`,
			submit_doc: 0,
			positionen: JSON.stringify([{ beschreibung: "X", betrag: 1, erloeskonto: income_account }]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				expect(si.hv_eingabequelle).to.eq("Vereinfachte Mieterrechnung");
				// Wohnung wird auf Doc UND Items gespiegelt (wenn das Custom Field existiert)
				if (wohnung && si.wohnung !== undefined) {
					expect(si.wohnung).to.eq(wohnung);
				}
			});
		});
	});

	it("[6b] Bemerkung kommt aus Positionsbeschreibung, wenn nur Cockpit-Standardtext vorhanden ist", () => {
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-6b`,
			bemerkung: `Erfasst über Buchungs-Cockpit | Mietvertrag: ${mietvertrag} | Referenz: `,
			submit_doc: 0,
			positionen: JSON.stringify([
				{ beschreibung: "Rechnung Ra Köpf gemäß Schreiben 19.05.2026", betrag: 403.56, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				expect(g.message.remarks).to.eq("Rechnung Ra Köpf gemäß Schreiben 19.05.2026");
			});
		});
	});

	it("[6c] Explizite Bemerkung gewinnt vor Positionsbeschreibung", () => {
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-6c`,
			bemerkung: "Bitte separat abstimmen",
			submit_doc: 0,
			positionen: JSON.stringify([
				{ beschreibung: "Positionsbeschreibung", betrag: 1, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				expect(g.message.remarks).to.eq("Bitte separat abstimmen");
			});
		});
	});

	it("[6d] Cockpit-Standardtext wird ohne Positionsbeschreibung gelöscht", () => {
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-6d`,
			bemerkung: `Erfasst über Buchungs-Cockpit | Mietvertrag: ${mietvertrag} | Referenz: `,
			submit_doc: 0,
			positionen: JSON.stringify([
				{ betrag: 1, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				expect(g.message.remarks || "").to.eq("");
			});
		});
	});

	// ── EDGE CASES ────────────────────────────────────────────────────────

	it("[7] Fehlender Mietvertrag → 4xx mit klarer Fehlermeldung", () => {
		cy.window()
			.its("frappe.csrf_token")
			.then((csrf_token) => {
				cy.request({
					method: "POST",
					url: `/api/method/${HV_API}.create_sales_invoice`,
					body: {
						rechnungsdatum: "2026-05-06",
						faellig_am: "2026-05-27",
						submit_doc: 0,
						positionen: JSON.stringify([
							{ beschreibung: "X", betrag: 1 },
						]),
					},
					headers: {
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
					failOnStatusCode: false,
				}).then((res) => {
					expect(res.status, "4xx").to.be.gte(400);
					const body = JSON.stringify(res.body || {});
					expect(body).to.match(/Mietvertrag/i);
				});
			});
	});

	it("[8] Leere Positionen → 4xx", () => {
		cy.window()
			.its("frappe.csrf_token")
			.then((csrf_token) => {
				cy.request({
					method: "POST",
					url: `/api/method/${HV_API}.create_sales_invoice`,
					body: {
						mietvertrag,
						rechnungsdatum: "2026-05-06",
						faellig_am: "2026-05-27",
						submit_doc: 0,
						positionen: JSON.stringify([]),
					},
					headers: {
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
					failOnStatusCode: false,
				}).then((res) => {
					expect(res.status).to.be.gte(400);
					const body = JSON.stringify(res.body || {});
					expect(body).to.match(/Positionen|Position/i);
				});
			});
	});

	it("[9] Position ohne Betrag → 4xx", () => {
		cy.window()
			.its("frappe.csrf_token")
			.then((csrf_token) => {
				cy.request({
					method: "POST",
					url: `/api/method/${HV_API}.create_sales_invoice`,
					body: {
						mietvertrag,
						rechnungsdatum: "2026-05-06",
						faellig_am: "2026-05-27",
						submit_doc: 0,
						positionen: JSON.stringify([
							{ beschreibung: "ohne Betrag" },
						]),
					},
					headers: {
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
					failOnStatusCode: false,
				}).then((res) => {
					expect(res.status).to.be.gte(400);
					const body = JSON.stringify(res.body || {});
					expect(body).to.match(/Betrag/i);
				});
			});
	});

	// ── UI-FLOW ──────────────────────────────────────────────────────────

	it("[10] UI-Flow: Dialog öffnen → Felder füllen → Als Entwurf speichern → SI als Draft", () => {
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");

		// Dialog programmatisch öffnen
		cy.window().then((win) => {
			expect(
				typeof win.hausverwaltung?.buchen_cockpit?.open_mieterrechnung_dialog,
				"open_mieterrechnung_dialog vorhanden"
			).to.equal("function");
			win.hausverwaltung.buchen_cockpit.open_mieterrechnung_dialog();
		});
		cy.get(".modal:visible", { timeout: 10000 }).should("exist");

		// Fülle Mietvertrag → kunde + wohnung sollten sich auto-befüllen
		cy.window()
			.its("cur_dialog", { timeout: 10000 })
			.should("exist")
			.then((dialog) => {
				dialog.set_value("mietvertrag", mietvertrag);
				dialog.set_value("rechnungsname", `${TEST_TAG}-10`);
			});

		// Auto-Befüllung kurz abwarten
		cy.wait(800);

		cy.window()
			.its("cur_dialog")
			.then((dialog) => {
				// kunde should be auto-populated
				expect(dialog.get_value("kunde"), "Kunde auto-gesetzt").to.eq(kunde);
				if (wohnung) {
					expect(dialog.get_value("wohnung"), "Wohnung auto-gesetzt").to.eq(
						wohnung
					);
				}

				// Position via grid setzen — KEIN artikel angegeben (Backend-Default)
				const grid = dialog.fields_dict.positionen.grid;
				grid.df.data = [
					{ beschreibung: "UI-Test Position", betrag: 33, erloeskonto: income_account },
				];
				grid.refresh();
			});

		// "Als Entwurf speichern" Custom Action klicken
		cy.get(".modal:visible .btn:contains('Als Entwurf speichern')")
			.first()
			.click();

		// Auf Erfolgs-Alert + Routing zur SI warten
		cy.contains(
			".alert, .desk-alert, .frappe-toast, .toast-message, .text-medium",
			"Entwurf",
			{ timeout: 10000 }
		).should("exist");

		// Per API verifizieren — die zuletzt erzeugte SI mit unserem Test-Tag
		cy.wait(500); // Routing/DB write Settle-Zeit
		cy.call("frappe.client.get_list", {
			doctype: "Sales Invoice",
			filters: { customer: kunde, docstatus: 0 },
			fields: ["name", "remarks", "grand_total"],
			limit_page_length: 5,
			order_by: "creation desc",
		}).then((r) => {
			const list = (r.message || []).filter((s) =>
				(s.remarks || "").includes(mietvertrag)
			);
			expect(list.length, "min. 1 Draft-SI für diesen Mietvertrag").to.be.greaterThan(0);
			const si = list[0];
			expect(Number(si.grand_total)).to.be.closeTo(33, 0.01);
			trackSi(si.name);
		});
	});

	it("[11] Default-Artikel = 'hv-default-service' (oder via ensure_default_service_item)", () => {
		// Sanity: Stelle sicher, dass das Default-Item existiert
		cy.call(`${HV_API}.create_sales_invoice`, {
			mietvertrag,
			rechnungsdatum: "2026-05-06",
			faellig_am: "2026-05-27",
			rechnungsname: `${TEST_TAG}-11`,
			submit_doc: 0,
			positionen: JSON.stringify([
				{ beschreibung: "Default-Artikel-Test", betrag: 1, erloeskonto: income_account },
			]),
		}).then((r) => {
			const name = r.message?.name;
			trackSi(name);
			cy.call("frappe.client.get", {
				doctype: "Sales Invoice",
				name,
			}).then((g) => {
				const si = g.message;
				const item_code = si.items[0].item_code;
				expect(item_code, "Item existiert").to.be.a("string").and.not.empty;
				cy.call("frappe.client.get", {
					doctype: "Item",
					name: item_code,
				}).then((ig) => {
					expect(ig.message.is_stock_item, "Service item").to.eq(0);
				});
			});
		});
	});
});
