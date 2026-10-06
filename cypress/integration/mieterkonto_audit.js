// Standalone audit: all Frappe responses and downloads are simulated in-browser.
// Run with supportFile=false and a static local HTTP server.
const assets = "hausverwaltung/public/mieterkonto_workflow";

function mountAudit(options = {}) {
  cy.intercept("GET", "/mieterkonto-audit", {
    headers: { "content-type": "text/html; charset=utf-8" },
    body: '<html><body><div id="mk-workflow-root"></div></body></html>',
  });
  cy.visit("/mieterkonto-audit", {
    onBeforeLoad(win) {
      win.__ = (text) => text;
      win.MK_INITIAL = { customer: "A", from_date: "2026-01-01", to_date: "2026-05-31" };
      win.MK_CUSTOMERS = [{ name: "A" }, { name: "B" }];
      win.pendingReports = [];
      win.deferReports = false;
      win.rejectCustomer = "";
      win.frappe = {
        datetime: { get_today: () => "2026-05-31" },
        defaults: { get_user_default: () => "Testfirma" },
        router: { slug: (text) => text.toLowerCase().replaceAll(" ", "-") },
        call({ method, args }) {
          if (method.endsWith("search_mieter")) {
            return Promise.resolve({ message: [{ name: "A" }, { name: "B" }] });
          }
          if (method.endsWith("get_mieter_stammdaten")) {
            return Promise.resolve({ message: { name: `Mieter ${args.customer}`, customer_id: args.customer, aufteilung_aktuell: {} } });
          }
          if (args.filters.customer === win.rejectCustomer) return Promise.reject(new Error("Audit: Bericht fehlgeschlagen"));
          const rows = [
            { datum: "2026-05-10", wertstellungsdatum: "2026-01-10", belegart: "Sales Invoice", belegnummer: `INV-${args.filters.customer}-1`, art: "Forderung", beschreibung: 'A; "quoted"', betrag_summe: 12.5, kontostand: options.nullBalance ? null : 42 },
            { datum: "2026-04-01", wertstellungsdatum: "2026-04-01", belegart: "Payment Entry", belegnummer: `PE-${args.filters.customer}-2`, art: "Zahlung", beschreibung: "Zahlung", betrag_summe: -29.5, kontostand: 29.5 },
          ];
          if (args.filters.sortieren_nach_wertstellungsdatum) rows.reverse();
          const result = { message: { rows, summary: [{ label: "Kontostand", value: 42 }] } };
          if (!win.deferReports) return Promise.resolve(result);
          return new Promise((resolve, reject) => win.pendingReports.push({ resolve: () => resolve(result), reject }));
        },
      };
      // Suppress real downloads and retain the exact exported bytes and name.
      win.URL.createObjectURL = (blob) => { win.auditBlob = blob; return "blob:audit"; };
      win.URL.revokeObjectURL = () => {};
      win.HTMLAnchorElement.prototype.click = function () { win.auditDownload = this.download; };
    },
  });
  cy.readFile(`${assets}/mk-data-adapter.js`).then((source) => cy.window().then((win) => win.eval(source)));
  cy.readFile(`${assets}/mk-workflow.bundle.js`).then((source) => cy.window().then((win) => win.eval(source)));
  cy.get(".mk-table tbody .col-beleg a").should("have.length", 2);
}

function exportedCsv() {
  cy.contains("button", "Export CSV").click();
  return cy.window().then((win) => win.auditBlob.text());
}

describe("Mieterkonto CSV matches the successfully loaded report", () => {
  it("exports loaded Customer data, signed amounts and escaped descriptions", () => {
    mountAudit();
    exportedCsv().then((csv) => {
      expect(csv).to.contain('"A; ""quoted"""');
      expect(csv).to.contain(";12.5;42");
      expect(csv).to.contain(";-29.5;29.5");
      expect(csv).to.contain("INV-A-1");
    });
    cy.window().its("auditDownload").should("equal", "A_2026-01-01_2026-05-31.csv");
  });

  it("does not name old Customer A data as Customer B after B fails to load", () => {
    mountAudit();
    cy.window().then((win) => { win.rejectCustomer = "B"; });
    cy.get(".mk-mieter-search").clear().type("B");
    cy.contains(".mk-combobox-option", /^B$/).click();
    cy.contains("Audit: Bericht fehlgeschlagen").should("exist");
    cy.get(".mk-table tbody").should("contain", "INV-A-1");
    cy.contains("button", "Export CSV").should("be.disabled");
    cy.window().its("auditBlob").should("not.exist");
    cy.window().then((win) => { win.rejectCustomer = ""; });
    cy.get(".mk-mieter-search").clear().type("A");
    cy.contains(".mk-combobox-option", /^A$/).click();
    exportedCsv().then((csv) => expect(csv).to.contain("INV-A-1"));
    cy.window().its("auditDownload").should("equal", "A_2026-01-01_2026-05-31.csv");
  });

  it("keeps CSV columns tied to the loaded sort while the next report is pending", () => {
    mountAudit();
    cy.window().then((win) => { win.deferReports = true; });
    cy.contains("label", "Wertstellung anzeigen/sortieren").find("input").click();
    cy.contains("Mieterkonto-Daten werden geladen").should("exist");
    cy.get(".mk-table thead").should("not.contain", "Wertstellung");
    cy.contains("button", "Export CSV").should("be.disabled");
    cy.window().then((win) => { win.pendingReports[0].resolve(); });
    exportedCsv().then((csv) => expect(csv.split("\n")[0]).to.contain("Wertstellung"));
  });

  it("preserves an unknown running balance instead of exporting it as zero", () => {
    mountAudit({ nullBalance: true });
    cy.get(".mk-table tbody tr").filter(':contains("INV-A-1")').find(".col-saldo").should("have.text", "");
    exportedCsv().then((csv) => {
      const invoiceRow = csv.split("\n").find((row) => row.includes("INV-A-1"));
      expect(invoiceRow.split(";").at(-1)).to.equal("");
    });
  });
});
