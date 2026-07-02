import { describe, expect, it } from "vitest";
import {
	fmtDate,
	fmtDateTime,
	fmtEUR,
	fmtIban,
	partyDisplayLabel,
	partyTypeLabel,
	rowPhase,
	STATUS_PILL,
} from "./helpers.jsx";

describe("Bankimport helper formatting", () => {
	it("formatiert Euro-Betraege deutsch und stabil fuer Randwerte", () => {
		expect(fmtEUR(720)).toBe("720,00 €");
		expect(fmtEUR(-89.9)).toBe("−89,90 €");
		expect(fmtEUR("1000.5")).toBe("1.000,50 €");
		expect(fmtEUR(null)).toBe("0,00 €");
		expect(fmtEUR("keine zahl")).toBe("0,00 €");
	});

	it("normalisiert Datumswerte ohne Zeitzonenverschiebung", () => {
		expect(fmtDate("2026-04-03")).toBe("03.04.26");
		expect(fmtDate("2026-04-03 22:15:00")).toBe("03.04.26");
		expect(fmtDate("")).toBe("—");
		expect(fmtDate("03.04.2026")).toBe("03.04.2026");
	});

	it("formatiert Datum/Uhrzeit und toleriert fehlende Uhrzeit", () => {
		expect(fmtDateTime("2026-04-03 22:15:59")).toBe("03.04.26 22:15");
		expect(fmtDateTime("2026-04-03T05:07:00")).toBe("03.04.26 05:07");
		expect(fmtDateTime("2026-04-03")).toBe("03.04.26");
		expect(fmtDateTime(null)).toBe("—");
	});

	it("gruppiert IBANs und entfernt bestehende Leerraeume", () => {
		expect(fmtIban("DE89 1001 0010 0123 4567 89")).toBe("DE89 1001 0010 0123 4567 89");
		expect(fmtIban("DE89100100100123456789")).toBe("DE89 1001 0010 0123 4567 89");
		expect(fmtIban("")).toBe("");
	});
});

describe("Bankimport phase/status edge cases", () => {
	it("nimmt Backend-Phase vor Status-Fallback", () => {
		expect(rowPhase({ phase: 1, rowStatus: "done" })).toBe(1);
		expect(rowPhase({ rowStatus: "phase1-no-party" })).toBe(1);
		expect(rowPhase({ rowStatus: "needs_review" })).toBe(3);
		expect(rowPhase({ rowStatus: "unknown" })).toBe(3);
	});

	it("deckt kritische Statuslabels ab", () => {
		expect(STATUS_PILL["phase1-no-party"].lbl).toBe("Partei fehlt");
		expect(STATUS_PILL.error.cls).toBe("danger");
		expect(STATUS_PILL.done.lbl).toBe("Gebucht");
	});

	it("unterscheidet fehlende von bewusst leerer Partei", () => {
		expect(partyDisplayLabel({ rowStatus: "phase1-no-party" })).toBe("Partei fehlt");
		expect(partyDisplayLabel({ bankTransaction: "BT-1" })).toBe("Ohne Partei");
		expect(partyDisplayLabel({ journalEntry: "JE-1" })).toBe("Ohne Partei");
		expect(partyDisplayLabel({ party: "Kunde A" })).toBe("Kunde A");
	});

	it("uebersetzt technische Party-Typen fuer die UI", () => {
		expect(partyTypeLabel("Customer")).toBe("Kunde");
		expect(partyTypeLabel("Supplier")).toBe("Lieferant");
		expect(partyTypeLabel("Eigentuemer")).toBe("Eigentümer");
		expect(partyTypeLabel("")).toBe("");
	});
});
