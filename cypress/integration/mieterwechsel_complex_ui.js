/**
 * Komplexes UI-Szenario für einen Mieterwechsel.
 *
 * Deckt:
 *  - ausziehenden Altvertrag mit Enddatum
 *  - neuen Vertrag mit zwei Hauptmietern, Personenverlauf, Miete/BK/HK/Kaution
 *  - automatische Customer-Erzeugung
 *  - Statuswechsel Altvertrag/Neuvertrag
 *  - Wohnungs-UI mit aktuellem Mietvertrag und Vertrags-Historie
 */

const TEST_TAG = `__cy_mieterwechsel_${Date.now()}`;

const pad = (value) => String(value).padStart(2, "0");
const toDate = (year, monthIndex, day) => new Date(year, monthIndex, day);
const fmt = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const monthStart = (offsetMonths = 0) => {
	const now = new Date();
	return toDate(now.getFullYear(), now.getMonth() + offsetMonths, 1);
};
const monthEnd = (offsetMonths = 0) => {
	const now = new Date();
	return toDate(now.getFullYear(), now.getMonth() + offsetMonths + 1, 0);
};

const DATES = {
	zustandAb: fmt(monthStart(-18)),
	altAbschluss: fmt(monthStart(-19)),
	altVon: fmt(monthStart(-18)),
	altStaffel: fmt(monthStart(-6)),
	altBis: fmt(monthEnd(-1)),
	neuAbschluss: fmt(monthStart(-1)),
	neuVon: fmt(monthStart(0)),
	neuStaffel: fmt(monthStart(12)),
	neuBkStaffel: fmt(monthStart(7)),
};

const created = {
	mietvertraege: [],
	customers: [],
	contacts: [],
	wohnungszustaende: [],
	wohnungen: [],
};

const track = (bucket, name) => {
	if (name && !created[bucket].includes(name)) created[bucket].push(name);
	return name;
};

const deleteDoc = (doctype, name) => {
	if (!name) return cy.wrap(null);
	return cy.api_post("frappe.client.delete", { doctype, name }).then((res) => {
		cy.log(`cleanup ${doctype} ${name}: ${res.status}`);
	});
};

const insertDoc = (doc) =>
	cy.call("frappe.client.insert", { doc }).then((r) => {
		expect(r.message?.name, `${doc.doctype} angelegt`).to.be.a("string").and.not.be.empty;
		return r.message;
	});

const setMietvertragRows = (frm, { mieter, personen, miete, betriebskosten, heizkosten, kaution }) => {
	frm.clear_table("mieter");
	mieter.forEach((row) => frm.add_child("mieter", row));

	frm.clear_table("personen");
	personen.forEach((row) => frm.add_child("personen", row));

	frm.clear_table("miete");
	miete.forEach((row) => frm.add_child("miete", row));

	frm.clear_table("betriebskosten");
	betriebskosten.forEach((row) => frm.add_child("betriebskosten", row));

	frm.clear_table("heizkosten");
	heizkosten.forEach((row) => frm.add_child("heizkosten", row));

	frm.clear_table("kaution");
	kaution.forEach((row) => frm.add_child("kaution", row));

	frm.refresh_fields(["mieter", "personen", "miete", "betriebskosten", "heizkosten", "kaution"]);
};

const createMietvertragInUi = (payload) => {
	cy.visit("/app/mietvertrag/new");
	cy.get("body").should("have.attr", "data-ajax-state", "complete");
	cy.window({ timeout: 30000 }).its("cur_frm").should("exist");

	cy.window().then((win) => {
		const frm = win.cur_frm;
		return Promise.resolve()
			.then(() => frm.set_value("wohnung", payload.wohnung))
			.then(() => frm.set_value("vertragsabschluss_am", payload.vertragsabschluss_am))
			.then(() => frm.set_value("von", payload.von))
			.then(() => frm.set_value("bis", payload.bis || ""))
			.then(() => frm.set_value("bevorzugter_versandweg", payload.bevorzugter_versandweg))
			.then(() => frm.set_value("notizen", payload.notizen))
			.then(() => frm.set_value("kaution_notizen", payload.kaution_notizen))
			.then(() => {
				setMietvertragRows(frm, payload);
			});
	});

	cy.save();
	return cy.window().then((win) => {
		const doc = win.cur_frm.doc;
		track("mietvertraege", doc.name);
		track("customers", doc.kunde);
		return doc.name;
	});
};

const expectCurrencyClose = (value, expected, label) => {
	expect(Number(value || 0), label).to.be.closeTo(expected, 0.01);
};

context("Mieterwechsel — komplexer UI-Flow", () => {
	let wohnung;
	let altKontakt;
	let neuKontaktA;
	let neuKontaktB;
	let altVertrag;
	let neuVertrag;

	before(() => {
		cy.login();
		cy.visit("/app");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
		cy.window({ timeout: 15000 }).its("frappe.csrf_token").should("exist");

		insertDoc({
			doctype: "Wohnung",
			name__lage_in_der_immobilie: `${TEST_TAG} WE 7`,
			gebaeudeteil: "VH",
			status: "Leerstehend",
		})
			.then((doc) => {
				wohnung = track("wohnungen", doc.name);
				return insertDoc({
					doctype: "Wohnungszustand",
					wohnung,
					ab: DATES.zustandAb,
					"größe": 82.5,
					anzahl_zimmer: 3,
					betriebskostenabrechnung_durch_vermieter: 1,
					heizkostenabrechnung_durch_vermieter: 1,
					bad: "Mit Fenster",
					balkon: 1,
					wohnung_aktiv_genutzt: 1,
				});
			})
			.then((doc) => {
				track("wohnungszustaende", doc.name);
			});

		insertDoc({
			doctype: "Contact",
			first_name: "Alma",
			last_name: `Alt-${TEST_TAG}`,
			email_id: `alma.alt.${Date.now()}@example.test`,
		}).then((doc) => {
			altKontakt = track("contacts", doc.name);
		});

		insertDoc({
			doctype: "Contact",
			first_name: "Nora",
			last_name: `Neu-${TEST_TAG}`,
			email_id: `nora.neu.${Date.now()}@example.test`,
		}).then((doc) => {
			neuKontaktA = track("contacts", doc.name);
		});

		insertDoc({
			doctype: "Contact",
			first_name: "Milan",
			last_name: `Partner-${TEST_TAG}`,
			email_id: `milan.partner.${Date.now()}@example.test`,
		}).then((doc) => {
			neuKontaktB = track("contacts", doc.name);
		});
	});

	after(() => {
		cy.then(() => {
			[...created.mietvertraege].reverse().forEach((name) => deleteDoc("Mietvertrag", name));
			[...created.customers].reverse().forEach((name) => deleteDoc("Customer", name));
			[...created.wohnungszustaende].reverse().forEach((name) =>
				deleteDoc("Wohnungszustand", name)
			);
			[...created.wohnungen].reverse().forEach((name) => deleteDoc("Wohnung", name));
			[...created.contacts].reverse().forEach((name) => deleteDoc("Contact", name));
		});
	});

	it("legt Alt- und Neuvertrag im Formular an und zeigt den Mieterwechsel in der UI konsistent", () => {
		cy.then(() => {
			expect(wohnung, "Wohnung").to.be.a("string").and.not.be.empty;
			expect(altKontakt, "Alt-Kontakt").to.be.a("string").and.not.be.empty;
			expect(neuKontaktA, "Neu-Kontakt A").to.be.a("string").and.not.be.empty;
			expect(neuKontaktB, "Neu-Kontakt B").to.be.a("string").and.not.be.empty;
		});

		createMietvertragInUi({
			wohnung,
			vertragsabschluss_am: DATES.altAbschluss,
			von: DATES.altVon,
			bis: DATES.altBis,
			bevorzugter_versandweg: "Post",
			notizen: `Altvertrag endet wegen Mieterwechsel ${TEST_TAG}. Uebergabe im Vormonat.`,
			kaution_notizen: "Kaution nach Abnahme und Schlussabrechnung pruefen.",
			mieter: [
				{
					mieter: altKontakt,
					rolle: "Hauptmieter",
					eingezogen: DATES.altVon,
					ausgezogen: DATES.altBis,
				},
			],
			personen: [
				{ von: DATES.altVon, personen: 1 },
				{ von: DATES.altStaffel, personen: 2 },
			],
			miete: [
				{ von: DATES.altVon, miete: 700, art: "Monatlich" },
				{ von: DATES.altStaffel, miete: 735, art: "Monatlich" },
			],
			betriebskosten: [{ von: DATES.altVon, miete: 140, art: "Monatlich" }],
			heizkosten: [{ von: DATES.altVon, miete: 95, art: "Monatlich" }],
			kaution: [{ von: DATES.altVon, miete: 2100, art: "Gesamter Zeitraum" }],
		}).then((name) => {
			altVertrag = name;
		});

		createMietvertragInUi({
			wohnung,
			vertragsabschluss_am: DATES.neuAbschluss,
			von: DATES.neuVon,
			bis: "",
			bevorzugter_versandweg: "Email",
			notizen: `Neuabschluss aus Mieterwechsel ${TEST_TAG}: Einzug, Zaehler, Kaution und Vorauszahlungen angelegt.`,
			kaution_notizen: "Drei Nettokaltmieten, Zahlung in zwei Raten vereinbart.",
			mieter: [
				{ mieter: neuKontaktA, rolle: "Hauptmieter", eingezogen: DATES.neuVon },
				{ mieter: neuKontaktB, rolle: "Hauptmieter", eingezogen: DATES.neuVon },
			],
			personen: [{ von: DATES.neuVon, personen: 2 }],
			miete: [
				{ von: DATES.neuVon, miete: 760, art: "Monatlich" },
				{ von: DATES.neuStaffel, miete: 790, art: "Monatlich" },
			],
			betriebskosten: [
				{ von: DATES.neuVon, miete: 150, art: "Monatlich" },
				{ von: DATES.neuBkStaffel, miete: 165, art: "Monatlich" },
			],
			heizkosten: [{ von: DATES.neuVon, miete: 105, art: "Monatlich" }],
			kaution: [{ von: DATES.neuVon, miete: 2280, art: "Gesamter Zeitraum" }],
		}).then((name) => {
			neuVertrag = name;
		});

		cy.then(() => {
			expect(altVertrag, "Altvertrag").to.be.a("string").and.not.be.empty;
			expect(neuVertrag, "Neuvertrag").to.be.a("string").and.not.be.empty;
			expect(altVertrag).to.not.eq(neuVertrag);
		});

		cy.then(() => cy.open_doc("Mietvertrag", altVertrag));
		cy.window().its("cur_frm.doc").then((doc) => {
			expect(doc.wohnung).to.eq(wohnung);
			expect(doc.status).to.eq("Vergangenheit");
			expect(doc.bis).to.eq(DATES.altBis);
			expect(doc.kunde, "Alt-Customer").to.be.a("string").and.not.be.empty;
			expect(doc.mieter).to.have.length(1);
			expect(doc.personen).to.have.length(2);
			expectCurrencyClose(doc.bruttomiete, 970, "Alt-Bruttomiete zum Vertragsende");
		});
		cy.get(".page-container:visible").should("contain", "Mieterkonto");
		cy.get(".page-container:visible").should("contain", "Sollstellungen prüfen");

		cy.then(() => cy.open_doc("Mietvertrag", neuVertrag));
		cy.window().its("cur_frm.doc").then((doc) => {
			expect(doc.wohnung).to.eq(wohnung);
			expect(doc.status).to.eq("Läuft");
			expect(doc.kunde, "Neu-Customer").to.be.a("string").and.not.be.empty;
			expect(doc.mieter.map((row) => row.mieter)).to.include.members([neuKontaktA, neuKontaktB]);
			expect(doc.bevorzugter_versandweg).to.eq("Email");
			expect(doc.miete).to.have.length(2);
			expect(doc.betriebskosten).to.have.length(2);
			expect(doc.heizkosten).to.have.length(1);
			expectCurrencyClose(doc.bruttomiete, 1015, "Neu-Bruttomiete zum Start");
		});
		cy.get(".page-container:visible").should("contain", "Staffelmieten sortieren");

		cy.then(() => cy.open_doc("Wohnung", wohnung));
		cy.window().its("cur_frm.doc").then((doc) => {
			expect(doc.status).to.eq("Vermietet");
			expect(doc.aktueller_mietvertrag).to.eq(neuVertrag);
			expect(doc.mietvertraege_alle.map((row) => row.mietvertrag)).to.include.members([
				altVertrag,
				neuVertrag,
			]);
			expect(doc.mietvertraege_alle.map((row) => row.status)).to.include.members([
				"Vergangenheit",
				"Läuft",
			]);
		});
		cy.get(".page-container:visible").should("contain", neuVertrag);
		cy.get(".page-container:visible").should("contain", altVertrag);
	});
});
