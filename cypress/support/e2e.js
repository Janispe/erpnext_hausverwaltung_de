import "./commands";
import "@testing-library/cypress/add-commands";

Cypress.on("uncaught:exception", () => {
	return false;
});
