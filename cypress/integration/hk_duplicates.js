// Seed using cypress/fixtures/hk_safeguards.py with HV_HK_UI_DUPLICATE=1.
// Store stdout in output/bugfix-2026-10-06/hk-duplicate-ui-fixture.json.
describe('Heizkosten Doppelbuchung und Admin-Korrektur', () => {
  let fixture;
  before(() => {
    expect(Cypress.config('baseUrl')).to.equal('http://127.0.0.1:18084');
    cy.login('Administrator', 'admin');
    cy.readFile('output/bugfix-2026-10-06/hk-duplicate-ui-fixture.json').then((data) => { fixture = data; });
  });
  it('blockiert Doppelbuchung und erzeugt nach bestätigtem Storno einen Änderungsentwurf', () => {
    cy.visit(`/app/heizkostenabrechnung-immobilie/${encodeURIComponent(fixture.duplicate)}`);
    cy.window().its('cur_frm.doc.name').should('equal', fixture.duplicate);
    cy.intercept('POST', '**/api/method/frappe.desk.form.save.savedocs').as('saveDoc');
    cy.get('.page-actions .primary-action:visible').click();
    cy.contains('.modal:visible button', /^(Yes|Ja)$/).click();
    cy.contains('.modal:visible', 'Doppelte Heizkostenabrechnung verhindert').should('be.visible');
    cy.get('@saveDoc.all').should('have.length', 0);
    cy.window().its('cur_frm.doc.docstatus').should('equal', 0);
    cy.screenshot('hk-doppelbuchung-blockiert');
    cy.visit(`/app/heizkostenabrechnung-immobilie/${encodeURIComponent(fixture.head)}`);
    cy.window().its('cur_frm.doc.docstatus').should('equal', 1);
    cy.contains('.page-actions button:visible', 'Korrekturentwurf erstellen').click();
    cy.contains('.modal:visible', 'Heizkostenabrechnung kontrolliert berichtigen').should('be.visible');
    cy.get('.modal:visible [data-fieldname="reason"] textarea').type('Wärmedienst korrigiert die Kosten');
    cy.intercept('POST', '**/api/method/**.create_correction_draft').as('correct');
    cy.contains('.modal:visible button', 'Stornieren und Entwurf erstellen').click();
    cy.wait('@correct').then(({response}) => {
      expect(response.statusCode, JSON.stringify(response.body)).to.equal(200);
      expect(response.body.message.amended_from).to.equal(fixture.head);
      cy.window().its('cur_frm.doc.name').should('equal', response.body.message.name);
    });
    cy.window().its('cur_frm.doc.docstatus').should('equal', 0);
    cy.window().its('cur_frm.doc.amended_from').should('equal', fixture.head);
    cy.window().its('cur_frm.doc.mieter_positionen').should('have.length', 1);
    cy.window().its('cur_frm.doc.mieter_positionen.0.kosten_gesamt').should('equal', 100);
    cy.screenshot('hk-admin-korrekturentwurf');
  });
});
