// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { InvoiceMatch } from "./MatchPanel.jsx";
import * as api from "../api.js";

vi.mock("../api.js", async (original) => ({
	...await original(), getOpenInvoices: vi.fn(), reconcileInvoices: vi.fn(),
}));

let root, container, notify, invoices;
const review = {
	name: "ACC-SINV-2026-56320", customer: "Giese", contract: "MV-Giese", wohnung: "1.OG rechts",
	company: "COMP-1", posting_date: "2026-09-24", contract_start: "2012-04-01", contract_end: "2026-05-31",
	invoice_modified: "2026-09-24 12:00:00", contract_modified: "2026-06-01 12:00:00",
};
const click = async (element) => act(async () => element.click());
const bookButton = () => [...container.querySelectorAll("button")].find((button) => button.textContent.includes("Zuordnen & buchen"));
const selectors = () => container.querySelectorAll('.invoice-card .row1 input[type="checkbox"]');
const confirmInput = () => container.querySelector('[aria-label="Nachträgliche Abrechnung ACC-SINV-2026-56320 bestätigen"]');
async function amount(index, value) {
	await act(async () => {
		const input = container.querySelectorAll('.alloc-input')[index];
		Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
		input.dispatchEvent(new Event("input", { bubbles: true }));
	});
}
async function renderMatch() {
	await act(async () => root.render(<InvoiceMatch docname="IMPORT" row={{ id: "ROW", betrag: 50, party_type: "Customer", richtung: "Eingang" }} notify={notify} onActionDone={vi.fn()} />));
}
async function selectSplit() {
	await click(selectors()[0]);
	await amount(0, "25");
	await click(selectors()[1]);
}
beforeEach(() => {
	globalThis.IS_REACT_ACT_ENVIRONMENT = true;
	vi.resetAllMocks();
	notify = vi.fn();
	container = document.createElement("div");
	document.body.append(container);
	root = createRoot(container);
	invoices = [
		{ name: "ACC-SINV-2026-54479", posting_date: "2026-04-01", outstanding_amount: 100 },
		{ name: review.name, posting_date: review.posting_date, outstanding_amount: 100,
			after_contract_end_review: review, date_warning: "Diese Rechnung wurde nach Vertragsende erstellt. Bitte prüfen, ob sie eine nachträgliche Abrechnung dieses Mietverhältnisses betrifft." },
	];
	api.getOpenInvoices.mockImplementation(async () => ({ invoiceDoctype: "Sales Invoice", invoices }));
	api.reconcileInvoices.mockResolvedValue({ ok: true });
});
afterEach(async () => {
	await act(async () => root.unmount());
	container.remove();
});

describe("Manuelle Zuordnung nach Vertragsende", () => {
	it("requires explicit confirmation for the Giese 25/25 split and sends its snapshot", async () => {
		await renderMatch();
		await selectSplit();
		expect(container.textContent).toContain("31.05.26");
		expect(confirmInput().checked).toBe(false);
		expect(bookButton().disabled).toBe(true);
		await click(bookButton());
		expect(api.reconcileInvoices).not.toHaveBeenCalled();
		await click(confirmInput());
		expect(bookButton().disabled).toBe(false);
		await click(bookButton());
		expect(api.reconcileInvoices).toHaveBeenCalledWith("IMPORT", "ROW", [
			{ name: "ACC-SINV-2026-54479", reference_doctype: "Sales Invoice", allocated_amount: 25 },
			{ name: review.name, reference_doctype: "Sales Invoice", allocated_amount: 25 },
		], false, [{ ...review, allocated_amount: 25 }]);
	});
	it("invalidates confirmation after amount and selection changes", async () => {
		await renderMatch();
		await selectSplit();
		await click(confirmInput());
		await amount(1, "20");
		expect(confirmInput().checked).toBe(false);
		expect(bookButton().disabled).toBe(true);
		await amount(1, "25");
		await click(confirmInput());
		await click(selectors()[1]);
		await click(selectors()[1]);
		expect(confirmInput().checked).toBe(false);
	});
	it("keeps contradictory identity candidates disabled", async () => {
		invoices[1].allocation_blocked_reason = "Andere Wohnung";
		await renderMatch();
		expect(selectors()[1].disabled).toBe(true);
		expect(container.textContent).toContain("Andere Wohnung");
	});
	it("does not require a date confirmation for an ordinary invoice", async () => {
		await renderMatch();
		await click(selectors()[0]);
		expect(confirmInput()).toBeNull();
		await click(bookButton());
		expect(api.reconcileInvoices).toHaveBeenCalledWith("IMPORT", "ROW", [
			{ name: "ACC-SINV-2026-54479", reference_doctype: "Sales Invoice", allocated_amount: 50 },
		], false, []);
	});
	it("confirmation cannot bypass over-allocation", async () => {
		await renderMatch();
		await selectSplit();
		await amount(1, "30");
		await click(confirmInput());
		await click(bookButton());
		expect(api.reconcileInvoices).not.toHaveBeenCalled();
		expect(notify).toHaveBeenCalledWith("error", "Die Zuweisung übersteigt den Bankbetrag.");
	});
});
