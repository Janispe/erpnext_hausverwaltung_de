// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { App } from "../App.jsx";
import { createKiMockOverview } from "../data.js";
import { KiCell } from "./KiCell.jsx";
import { KiSuggestion } from "./KiSuggestion.jsx";
import { KiBulkDialog } from "./KiBulkDialog.jsx";

let container, root;
const render = async (node) => act(async () => root.render(node));
const button = (text) => [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === text);
const click = async (text) => act(async () => button(text).click());

beforeEach(() => {
	globalThis.IS_REACT_ACT_ENVIRONMENT = true;
	container = document.createElement("div");
	document.body.append(container);
	root = createRoot(container);
});
afterEach(async () => {
	await act(async () => root.unmount());
	container.remove();
	delete HTMLDialogElement.prototype.showModal;
});

it.each([
	[undefined, 0, "SINV-2026-0041", "Prüfung offen", "hoch"],
	[undefined, 1, "Erika Beispiel → SINV-2026-0052", "Partei und Rechnung · 2 Schritte", "mittel"],
	["states", 0, "Freigegeben", "Freigegeben von M. Krüger"],
	["states", 3, "Abgelehnt", "Abgelehnt von M. Krüger"],
	[undefined, 6, "! Veraltet", "Neue Revision anfordern"],
	[undefined, 7, "Kein Vorschlag", "Ohne Auftraggeber"],
	["running", 7, "Agent prüft", "Agent prüft diese Zeile"],
	[undefined, 8, "übernommen", "Freigegeben und gebucht von M. Krüger"],
])("zeigt Zustand %s für Zeile %i in Tabelle und Panel", async (variant, index, cellText, panelText, confidence) => {
	const data = createKiMockOverview(variant);
	const row = data.rows[index];
	await render(<>
		<table><tbody><tr><KiCell ki={row.ki} /></tr></tbody></table>
		<KiSuggestion meta={data.import.ki} row={row} />
	</>);
	const cell = container.querySelector("td");
	const panel = container.querySelector("section");
	expect(cell.textContent).toContain(cellText);
	expect(panel.textContent).toContain(panelText);
	if (confidence) {
		expect(cell.querySelector(".ki-confidence").textContent).toContain(confidence);
		expect(panel.querySelector(".ki-confidence").textContent).toContain(confidence);
	}
});

it("benötigt eine Begründung für die Ablehnung und lässt Prüferaktionen ohne Rechte weg", async () => {
	const data = createKiMockOverview();
	await render(<KiSuggestion meta={data.import.ki} row={data.rows[0]} />);
	await click("Ablehnen …");
	expect(button("Ablehnen").disabled).toBe(true);
	await render(<KiSuggestion meta={{ ...data.import.ki, canAccept: false }} row={data.rows[0]} />);
	expect(container.textContent).toContain("Nur Prüfer können Vorschläge übernehmen.");
	expect(container.querySelector("[data-ki-key]")).toBeNull();
	expect(button("Anpassen")).toBeDefined();
});

it("öffnet den Sammeldialog leer und wählt hohe Vorschläge nur auf Klick", async () => {
	const { import: meta, rows } = createKiMockOverview();
	meta.ki.counts = { Stale: 1, none: 1 };
	Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
		configurable: true, value() { this.open = true; },
	});
	await render(<KiBulkDialog meta={meta} rows={rows} />);
	expect(button("0 übernehmen und buchen").disabled).toBe(true);
	expect(container.querySelectorAll("input:checked")).toHaveLength(0);
	expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(6);
	expect(container.querySelector('[aria-label="ACC-PINV-2026-0090"]')).toBeNull();
	await click("Hohe Sicherheit");
	expect(container.querySelectorAll("input:checked")).toHaveLength(3);
	expect(container.querySelector("[aria-live]").textContent).toMatch(/3 ausgewählt · Eingang .*720,00.* · Ausgang .*102,40/);
	expect(button("3 übernehmen und buchen").disabled).toBe(false);
});

it("rendert die bestehende Importansicht ohne KI, wenn meta.ki fehlt", async () => {
	await render(<App />);
	const demo = container.querySelector(".ip-table tbody tr");
	await act(async () => demo.click());
	expect(container.querySelector(".tx-table")).not.toBeNull();
	expect(container.querySelector(".match-panel")).not.toBeNull();
	expect(container.querySelector(".ki-col, .ki-banner, .ki-mark, .ki-section")).toBeNull();
});
