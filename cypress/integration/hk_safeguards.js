// Needs the isolated HK fixture from cypress/fixtures/hk_safeguards.py.
// Uses the actual Frappe submit lifecycle and real confirmation dialog.
describe('Heizkosten Nullkosten-Bestätigung', () => {
  before(() => {
    expect(Cypress.config('baseUrl')).to.equal('http://127.0.0.1:18084');
    cy.login('Administrator', 'admin');
    cy.readFile('output/bugfix-2026-10-06/hk-ui-fixture.json').then(({head}) => {
      cy.visit(`/app/heizkostenabrechnung-immobilie/${encodeURIComponent(head)}`);
      cy.window().its('cur_frm.doc.name').should('equal', head);
    });
  });
  it('Abbrechen bucht nichts; ausdrückliche Bestätigung erlaubt reale Nullkosten', () => {
    cy.intercept('POST', '**/api/method/frappe.desk.form.save.savedocs').as('submitDoc');
    cy.get('.page-actions .primary-action:visible').click();
    cy.contains('.modal:visible button', /^(Yes|Ja)$/).click();
    cy.contains('.modal:visible', 'Die erfassten Heizkosten betragen null Euro').should('be.visible');
    cy.contains('.modal:visible button', /^(No|Nein)$/).click();
    cy.get('@submitDoc.all').should('have.length', 0);
    cy.window().its('cur_frm.doc.docstatus').should('equal', 0);
    cy.get('.page-actions .primary-action:visible').should('be.enabled').click();
    cy.contains('.modal:visible button', /^(Yes|Ja)$/).click();
    cy.contains('.modal:visible', 'Die erfassten Heizkosten betragen null Euro').should('be.visible');
    cy.contains('.modal:visible button', /^(Yes|Ja)$/).click();
    cy.wait('@submitDoc').its('response.statusCode').should('equal', 200);
    cy.window().its('cur_frm.doc.docstatus').should('equal', 1);
    cy.window().its('cur_frm.doc.nullkosten_bestaetigt').should('equal', 1);
    cy.screenshot('hk-nullkosten-bestaetigt');
  });
});
