// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CustomerPayments, CustomerSplitDialog } from "./CustomerSplitDialog.jsx";
import * as api from "../api.js";

vi.mock("../api.js", async (importOriginal) => ({
	...await importOriginal(),
	getCustomerSplitInvoices: vi.fn(),
	reconcileCustomerSplit: vi.fn(),
	searchParties: vi.fn(),
}));
vi.mock("./LinkSearch.jsx", () => ({
	LinkSearch: ({ onPick }) => <>{["A", "B"].map((customer) =>
		<button key={customer} onClick={() => onPick({ value: customer })}>Add {customer}</button>)}</>,
}));

let root, container;
const button = (text) => [...document.querySelectorAll("button")].find((element) => element.textContent === text);
const click = async (element) => act(async () => element.click());
const change = async (name, value) => act(async () => {
	const input = document.querySelector(`[aria-label="Teilbetrag ${name}"]`);
	Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
	input.dispatchEvent(new Event("input", { bubbles: true }));
});

beforeEach(() => {
	globalThis.IS_REACT_ACT_ENVIRONMENT = true;
	vi.resetAllMocks();
	container = document.createElement("div");
	document.body.append(container);
	root = createRoot(container);
	api.getCustomerSplitInvoices.mockImplementation(async (_, __, customer) => ({
		customer, contract: `MV-${customer}`, wohnung: `W-${customer}`,
		invoices: [{ name: `INV-${customer}`, outstanding_amount: customer === "A" ? 200 : -300 }],
	}));
	api.reconcileCustomerSplit.mockResolvedValue({ ok: true });
});
afterEach(async () => {
	await act(async () => root.unmount());
	container.remove();
});

async function renderSplit(amount = -100, props = {}) {
	await act(async () => root.render(<CustomerSplitDialog
		docname="IMPORT" row={{ id: "ROW", betrag: amount }} onClose={vi.fn()} onActionDone={vi.fn()} notify={vi.fn()} {...props}
	/>));
	await click(button("Add A"));
	await click(button("Add B"));
	for (const checkbox of document.querySelectorAll('.customer-split-invoice input[type="checkbox"]')) await click(checkbox);
}

describe("Customer settlement dialog", () => {
	it("nets a charge and credit and submits positive magnitudes", async () => {
		await renderSplit();
		expect(button(" Aufteilung buchen").disabled).toBe(false);
		expect(document.querySelector(".customer-split-summary").textContent).toContain("100,00");
		await click(button(" Aufteilung buchen"));
		expect(api.reconcileCustomerSplit).toHaveBeenCalledWith("IMPORT", "ROW", [
			{ customer: "A", invoices: [{ name: "INV-A", allocated_amount: 200 }] },
			{ customer: "B", invoices: [{ name: "INV-B", allocated_amount: 300 }] },
		], null, []);
	});
	it("rejects the opposite bank direction", async () => {
		await renderSplit(100);
		expect(button(" Aufteilung buchen").disabled).toBe(true);
	});
	it("assigns a ten-cent surplus to an explicitly selected Customer", async () => {
		api.getCustomerSplitInvoices.mockImplementation(async (_, __, customer) => ({
			customer, contract: `MV-${customer}`, wohnung: `W-${customer}`,
			invoices: [{ name: `INV-${customer}`, outstanding_amount: customer === "A" ? 200 : -10 }],
		}));
		await renderSplit(190.10);
		expect(button(" Aufteilung buchen").disabled).toBe(true);
		const select = document.querySelector('[aria-label="Vorauszahlung für"]');
		expect(select.textContent).toContain("B · W-B");
		await act(async () => {
			select.value = "B";
			select.dispatchEvent(new Event("change", { bubbles: true }));
		});
		expect(button(" Aufteilung buchen").disabled).toBe(false);
		await click(button(" Aufteilung buchen"));
		expect(api.reconcileCustomerSplit).toHaveBeenCalledWith("IMPORT", "ROW", [
			{ customer: "A", invoices: [{ name: "INV-A", allocated_amount: 200 }] },
			{ customer: "B", invoices: [{ name: "INV-B", allocated_amount: 10 }] },
		], "B", []);
	});
	it("requires confirmation of a late credit and resets it when the allocated amount changes", async () => {
		const review = { name: "INV-A", contract: "MV-A", wohnung: "W-A", posting_date: "2026-08-05", contract_end: "2025-04-15" };
		api.getCustomerSplitInvoices.mockImplementation(async (_, __, customer) => ({
			customer, contract: `MV-${customer}`, wohnung: `W-${customer}`,
			invoices: [{ name: `INV-${customer}`, outstanding_amount: customer === "A" ? -88.06 : 7.21,
				...(customer === "A" ? { after_contract_end_review: review, date_warning: "Nachträgliche Abrechnung prüfen" } : {}) }],
		}));
		await renderSplit(-80.75);
		await change("INV-A", "87.96");
		const confirmation = document.querySelector('[aria-label="Nachträgliche Abrechnung INV-A bestätigen"]');
		expect(button(" Aufteilung buchen").disabled).toBe(true);
		await click(confirmation);
		expect(button(" Aufteilung buchen").disabled).toBe(false);
		await change("INV-A", "87.95");
		await change("INV-A", "87.96");
		expect(confirmation.checked).toBe(false);
		expect(button(" Aufteilung buchen").disabled).toBe(true);
		await click(confirmation);
		await click(button(" Aufteilung buchen"));
		expect(api.reconcileCustomerSplit).toHaveBeenCalledWith("IMPORT", "ROW", [
			{ customer: "A", invoices: [{ name: "INV-A", allocated_amount: 87.96 }] },
			{ customer: "B", invoices: [{ name: "INV-B", allocated_amount: 7.21 }] },
		], null, [{ ...review, allocated_amount: 87.96 }]);
	});
	it("shows identity mismatches and prevents selecting those invoices", async () => {
		api.getCustomerSplitInvoices.mockImplementation(async (_, __, customer) => ({
			customer, invoices: [{ name: `INV-${customer}`, outstanding_amount: 50, allocation_blocked_reason: "Falsche Wohnung" }],
		}));
		await act(async () => root.render(<CustomerSplitDialog docname="IMPORT" row={{ id: "ROW", betrag: 100 }} />));
		await click(button("Add A"));
		expect(document.querySelector('.customer-split-invoice input[type="checkbox"]').disabled).toBe(true);
		expect(document.querySelector('[role="alert"]').textContent).toBe("Falsche Wohnung");
	});
	it("does not offer an advance for outgoing payments or underpayments", async () => {
		await renderSplit(-99.90);
		expect(document.querySelector('[aria-label="Vorauszahlung für"]')).toBeNull();
		expect(button(" Aufteilung buchen").disabled).toBe(true);
		await change("INV-B", "100");
		expect(document.querySelector('[aria-label="Vorauszahlung für"]')).toBeNull();
	});
	it("clears the advance Customer when that Customer is removed", async () => {
		api.getCustomerSplitInvoices.mockImplementation(async (_, __, customer) => ({
			customer, invoices: [{ name: `INV-${customer}`, outstanding_amount: customer === "A" ? 200 : -10 }],
		}));
		await renderSplit(190.10);
		const select = document.querySelector('[aria-label="Vorauszahlung für"]');
		await act(async () => {
			select.value = "B";
			select.dispatchEvent(new Event("change", { bubbles: true }));
		});
		await click(document.querySelector('[aria-label="Mieter B entfernen"]'));
		await click(button("Add B"));
		await click(document.querySelectorAll('input[type="checkbox"]')[1]);
		expect(document.querySelector('[aria-label="Vorauszahlung für"]').value).toBe("");
		expect(button(" Aufteilung buchen").disabled).toBe(true);
	});
	it("accepts partial netting but rejects overallocations and fractional cents", async () => {
		await renderSplit();
		await change("INV-A", "100");
		await change("INV-B", "200");
		expect(button(" Aufteilung buchen").disabled).toBe(false);
		await change("INV-A", "200.01");
		await change("INV-B", "300.01");
		expect(button(" Aufteilung buchen").disabled).toBe(true);
		await change("INV-A", "100.001");
		await change("INV-B", "200.001");
		expect(button(" Aufteilung buchen").disabled).toBe(true);
	});
	it("keeps the dialog open when booking fails", async () => {
		const onClose = vi.fn(), notify = vi.fn();
		api.reconcileCustomerSplit.mockRejectedValue(new Error("stale invoice"));
		await renderSplit(-100, { onClose, notify });
		await click(button(" Aufteilung buchen"));
		expect(onClose).not.toHaveBeenCalled();
		expect(notify).toHaveBeenCalledWith("error", "stale invoice");
	});
	it("displays the shared journal for both Customers", async () => {
		await act(async () => root.render(<CustomerPayments row={{ customerPayments: [
			{ customer: "A", journal_entry: "JE-1", amount: 200 },
			{ customer: "B", journal_entry: "JE-1", amount: -300 },
		] }} />));
		expect(document.querySelectorAll('a[href*="journal-entry/JE-1"]')).toHaveLength(2);
		expect(container.textContent).toContain("300,00");
	});
});
