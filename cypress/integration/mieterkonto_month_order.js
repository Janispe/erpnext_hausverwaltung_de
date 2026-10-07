// Standalone UI regression: no Frappe site or accounting data required.
// Run against any local HTTP server with --config supportFile=false.
const assets = "hausverwaltung/public/mieterkonto_workflow";
const postingRows = [
  ["2026-05-10", "2026-01-10"],
  ["2026-05-09", "2025-10-09"],
  ["2026-05-07", "2026-05-07"],
  ["2026-04-30", "2026-01-30"],
  ["2026-04-01", "2026-04-01"],
  ["2026-01-01", "2026-01-01"],
].map(([datum, wertstellungsdatum], index) => ({
  datum, wertstellungsdatum, belegart: "Sales Invoice",
  belegnummer: `TEST-${index}`, art: "Forderung", beschreibung: `Buchung ${index}`,
  betrag_summe: 10, kontostand: 100 - index * 10,
}));
const valueRows = [...postingRows].sort((a, b) => b.wertstellungsdatum.localeCompare(a.wertstellungsdatum));
const postingMonths = ["Mai 2026", "April 2026", "Januar 2026"];
const valueMonths = ["Mai 2026", "April 2026", "Januar 2026", "Oktober 2025"];

function expectMonths(months) {
  cy.get(".mk-month-bar > span:first-child").should(($labels) => {
    expect([...$labels].map((el) => el.textContent)).to.deep.equal(months);
  });
  cy.get(".mk-table tbody .col-beleg a").should("have.length", postingRows.length);
}

function toggle() {
  cy.contains("label", "Wertstellung anzeigen/sortieren").find("input").click();
}

describe("Mieterkonto month order during asynchronous sorting", () => {
  beforeEach(() => {
    cy.intercept("GET", "/mieterkonto-sort-test", {
      headers: { "content-type": "text/html; charset=utf-8" },
      body: '<html><body><div id="mk-workflow-root"></div></body></html>',
    });
    cy.visit("/mieterkonto-sort-test", {
      onBeforeLoad(win) {
        win.__ = (text) => text;
        win.MK_INITIAL = { customer: "TEST", from_date: "2025-06-01", to_date: "2026-05-31" };
        win.pendingReports = [];
        win.deferReports = false;
        win.frappe = {
          datetime: { get_today: () => "2026-05-31" },
          defaults: { get_user_default: () => "Testfirma" },
          router: { slug: (text) => text.toLowerCase().replaceAll(" ", "-") },
          call({ method, args }) {
            if (method.endsWith("search_mieter")) return Promise.resolve({ message: [] });
            if (method.endsWith("get_mieter_stammdaten")) {
              return Promise.resolve({ message: { name: "Testmieter", customer_id: "TEST", aufteilung_aktuell: {} } });
            }
            const rows = args.filters.sortieren_nach_wertstellungsdatum ? valueRows : postingRows;
            const result = { message: { rows, summary: [] } };
            if (!win.deferReports) return Promise.resolve(result);
            return new Promise((resolve, reject) => {
              win.pendingReports.push({ resolve: () => resolve(result), reject });
            });
          },
        };
      },
    });
    cy.readFile(`${assets}/mk-data-adapter.js`).then((source) => cy.window().then((win) => win.eval(source)));
    cy.readFile(`${assets}/mk-workflow.bundle.js`).then((source) => cy.window().then((win) => win.eval(source)));
    expectMonths(postingMonths);
    cy.window().then((win) => { win.deferReports = true; });
  });

  it("switches month headers with the completed report, without orphaned headers", () => {
    toggle();
    cy.contains("Mieterkonto-Daten werden geladen").should("exist");
    expectMonths(postingMonths);
    cy.window().then((win) => win.pendingReports.shift().resolve());
    expectMonths(valueMonths);
    cy.get(".mk-table thead").should("contain", "Wertstellung");
    toggle();
    expectMonths(valueMonths);
    cy.window().then((win) => win.pendingReports.shift().resolve());
    expectMonths(postingMonths);
    cy.get(".mk-table thead").should("not.contain", "Wertstellung");
  });

  it("keeps the loaded month order when fetching the new order fails", () => {
    toggle();
    cy.window().then((win) => win.pendingReports.shift().reject(new Error("Testfehler")));
    cy.contains("Testfehler").should("exist");
    expectMonths(postingMonths);
    cy.get(".mk-table thead").should("not.contain", "Wertstellung");
  });

  it("ignores an obsolete response after a rapid toggle back", () => {
    toggle();
    toggle();
    cy.window().then((win) => win.pendingReports[1].resolve());
    expectMonths(postingMonths);
    cy.window().then((win) => win.pendingReports[0].resolve());
    expectMonths(postingMonths);
    cy.get(".mk-table thead").should("not.contain", "Wertstellung");
  });
});
