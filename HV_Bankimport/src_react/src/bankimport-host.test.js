import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, it, vi } from "vitest";

it("reicht den kodierten Zeilenlink beim Laden und beim erneuten Anzeigen an das iframe weiter", () => {
	const script = readFileSync(new URL("../../../hausverwaltung/hausverwaltung/page/bankimport_v2/bankimport_v2.js", import.meta.url), "utf8");
	const page = {};
	const body = { empty: () => body, css: () => body, append: vi.fn() };
	const frame = { css: () => frame, attr: vi.fn(), 0: { getBoundingClientRect: () => ({ top: 0 }) } };
	let query = { import: "Import 1 & 2", row: "Zeile / + 9" };
	let initialSrc;
	const window = { addEventListener: vi.fn(), innerHeight: 800 };
	runInNewContext(script, {
		window, URLSearchParams, __: (value) => value,
		frappe: {
			pages: { bankimport_v2: page },
			ui: { make_app_page: () => ({ body, wrapper: { on: vi.fn() } }) },
			utils: { get_query_params: () => query, debounce: (fn) => fn },
		},
		$: (value) => {
			if (value === window) return { on: vi.fn() };
			if (value === body) return body;
			initialSrc = value.match(/src="([^"]+)"/)[1];
			return frame;
		},
	});
	const params = (src) => new URL(src, "https://demo.invalid").searchParams;
	page.on_page_load({});
	expect(params(initialSrc).get("import")).toBe(query.import);
	expect(params(initialSrc).get("row")).toBe(query.row);
	query = { import: "Import neu", row: "r9#2" };
	page.on_page_show();
	const [attribute, src] = frame.attr.mock.calls[0];
	expect(attribute).toBe("src");
	expect(params(src).get("import")).toBe(query.import);
	expect(params(src).get("row")).toBe(query.row);
});
