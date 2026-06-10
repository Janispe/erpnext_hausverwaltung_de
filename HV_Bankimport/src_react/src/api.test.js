import { describe, expect, it } from "vitest";
import {
	createImport,
	getDeleteImpact,
	isMissingRowError,
	listBankAccounts,
	listImports,
	loadOverview,
	searchAccounts,
	searchParties,
} from "./api.js";

describe("Bankimport standalone API fallback", () => {
	it("liefert Mock-Importe und erkennt offene/abgeschlossene Testdaten", async () => {
		const { items, mock } = await listImports();
		expect(mock).toBe(true);
		expect(items).toHaveLength(2);
		expect(items.some((item) => item.offene_buchungen > 0)).toBe(true);
		expect(items.some((item) => item.offene_buchungen === 0)).toBe(true);
	});

	it("stellt Bankkonto- und Importanlage-Fallback fuer den Upload-Dialog bereit", async () => {
		const accounts = await listBankAccounts();
		expect(accounts.items[0].value).toContain("Demo Bankkonto");

		const created = await createImport({
			bankAccount: accounts.items[0].value,
			filename: "kontoauszug.csv",
			fileData: "data:text/csv;base64,QQ==",
		});
		expect(created).toMatchObject({ name: "BAI-DEMO-0001", mock: true });
	});

	it("filtert Suchdaten case-insensitive und gibt leere Treffer sauber zurueck", async () => {
		expect((await searchParties("Customer", "max")).items.map((item) => item.value)).toEqual(["Max Mustermann"]);
		expect((await searchParties("Supplier", "nicht vorhanden")).items).toEqual([]);
		expect((await searchAccounts("bank")).items[0].value).toContain("Bankgebühren");
	});

	it("liefert konsistente Loeschwirkung fuer den aktuellen Mock-Import", async () => {
		const overview = await loadOverview("BAI-1812-DEMO-0001");
		const impact = await getDeleteImpact("BAI-1812-DEMO-0001");

		expect(impact.mock).toBe(true);
		expect(impact.rows).toBe(overview.rows.length);
		expect(impact.requiresCascade).toBe(false);
	});
});

describe("isMissingRowError", () => {
	it("erkennt stale-row Backendmeldungen mit variablen Dokumentnamen", () => {
		expect(isMissingRowError("Zeile row-7 wurde im Dokument BAI-1 nicht gefunden")).toBe(true);
		expect(isMissingRowError(new Error("Zeile abc wurde im Dokument Import-99 nicht gefunden"))).toBe(true);
	});

	it("ignoriert normale Validierungsfehler", () => {
		expect(isMissingRowError("Bitte mindestens eine Rechnung auswählen.")).toBe(false);
		expect(isMissingRowError(null)).toBe(false);
	});
});
