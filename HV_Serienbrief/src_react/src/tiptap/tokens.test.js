import { describe, it, expect } from "vitest";
import { Editor } from "@tiptap/core";
import { buildExtensions } from "./extensions.js";
import { decorateForTiptap, serializeToTokens, tokenMultiset } from "./tokens.js";
import { validateJinjaBalance, diffTokens } from "./validateJinja.js";

// Voller Round-Trip: DB-HTML -> decorate -> echter TipTap-Parse -> getHTML -> serialize.
function roundTrip(dbHtml) {
	const editor = new Editor({
		element: document.createElement("div"),
		extensions: buildExtensions(),
		content: decorateForTiptap(dbHtml),
	});
	const out = serializeToTokens(editor.getHTML());
	editor.destroy();
	return out;
}

function expectTokensPreserved(dbHtml) {
	const out = roundTrip(dbHtml);
	const d = diffTokens(dbHtml, out);
	expect(d.lost).toEqual({});
	expect(d.added).toEqual({});
	// keine Escapes/Sentinel-Reste
	expect(out).not.toMatch(/&quot;|&amp;quot;/);
	expect(out).not.toMatch(/[\uE000\uE001]/);
	return out;
}

describe("Token-Round-Trip", () => {
	it("einfacher Platzhalter im Absatz", () => {
		expectTokensPreserved("<p>Sehr geehrte/r {{ mieter.nachname }},</p>");
	});

	it("custom {{$ $}}-Token", () => {
		expectTokensPreserved("<p>Wert: {{$ custom.spezialwert $}} Ende</p>");
	});

	it("Platzhalter in Mark (fett)", () => {
		expectTokensPreserved("<p>Offen: <strong>{{ saldo }}</strong></p>");
	});

	it("Marks um Chips bleiben nach Round-Trip erhalten", () => {
		// <strong>/<em>/<u> und Inline-Stil-Marks (textStyle: font-size) wrappen die atomare
		// Chip-NodeView; ohne `marks: "_"` auf dem Chip-Node würden sie beim Parse verschluckt.
		const bold = roundTrip("<p>Saldo: <strong>{{ saldo }}</strong> EUR</p>");
		expect(bold).toMatch(/<strong>\{\{\s*saldo\s*\}\}<\/strong>/);

		const italic = roundTrip("<p><em>{{ mieter.nachname }}</em></p>");
		expect(italic).toMatch(/<em>\{\{\s*mieter\.nachname\s*\}\}<\/em>/);

		const sized = roundTrip(
			'<p>Wert: <span style="font-size: 14pt">{{ saldo }}</span></p>'
		);
		expect(sized).toMatch(/font-size:\s*14pt[^>]*>\{\{\s*saldo\s*\}\}</);

		const bausteinFett = roundTrip(
			'<p><strong>{{ baustein("Anrede") }}</strong></p>'
		);
		expect(bausteinFett).toMatch(/<strong>\{\{\s*baustein\("Anrede"\)\s*\}\}<\/strong>/);
	});

	it("Umlaute und mehrere Platzhalter", () => {
		expectTokensPreserved(
			"<p>Wohnung {{ wohnung.bezeichnung }} in {{ immobilie.bezeichnung }} – Größe {{ wohnung.qm }} m²</p>"
		);
	});

	it("Baustein mit Quotes und Umlaut bleibt roh", () => {
		const out = expectTokensPreserved('<div>{{ baustein("Fußzeile Bankverbindung") }}</div>');
		expect(out).toContain('{{ baustein("Fußzeile Bankverbindung") }}');
	});

	it("Block-Level {% if %} zwischen Absätzen", () => {
		const out = expectTokensPreserved(
			"<p>Text vorher.</p>\n{% if first %}\n<p>Bedingter Absatz {{ saldo }}.</p>\n{% endif %}\n<p>Danach.</p>"
		);
		expect(out).toContain("{% if first %}");
		expect(out).toContain("{% endif %}");
	});

	it("Inline {% %} innerhalb eines Absatzes", () => {
		expectTokensPreserved("<p>A {% if x %}nur wenn x{% endif %} B</p>");
	});

	it("Tabellen-Zeilen-Loop bleibt erhalten", () => {
		const db =
			"<table><thead><tr><th>Rechnung</th><th style=\"text-align: right\">Offen</th></tr></thead>" +
			"<tbody>\n{% for row in payments %}\n" +
			'<tr><td>{{ row.sales_invoice }}</td><td style="text-align: right">{{ row.outstanding }}</td></tr>\n' +
			"{% endfor %}\n</tbody></table>";
		const out = expectTokensPreserved(db);
		expect(out).toContain("{% for row in payments %}");
		expect(out).toContain("{% endfor %}");
		// Reihenfolge: for vor <tr>, endfor danach
		expect(out).toMatch(/\{%\s*for row in payments\s*%\}[\s\S]*<tr[\s\S]*<\/tr>[\s\S]*\{%\s*endfor\s*%\}/);
	});

	it("Tabellen-Rahmen-Flag (data-hv-borders) round-trippt", () => {
		const withBorders = roundTrip(
			'<table data-hv-borders="1"><tbody><tr><td><p>A</p></td><td><p>B</p></td></tr></tbody></table>'
		);
		expect(withBorders).toContain("data-hv-borders");
		const without = roundTrip(
			"<table><tbody><tr><td><p>A</p></td><td><p>B</p></td></tr></tbody></table>"
		);
		expect(without).not.toContain("data-hv-borders");
	});

	it("legacy data-token Chip round-trippt (Abwärtskompatibilität)", () => {
		const legacy =
			'<p>Hallo <span class="chip" data-group="mieter" data-token="{{ mieter.vorname }}" contenteditable="false">mieter.vorname</span>!</p>';
		const out = serializeToTokens(
			new Editor({
				element: document.createElement("div"),
				extensions: buildExtensions(),
				content: legacy,
			}).getHTML()
		);
		expect(tokenMultiset(out)).toEqual({ "{{ mieter.vorname }}": 1 });
	});
});

describe("if-Bedingungen (inline hvIf)", () => {
	it("einfache truthy-Bedingung", () => {
		const out = expectTokensPreserved("<p>a</p>\n{% if first %}\n<p>x</p>\n{% endif %}\n<p>b</p>");
		expect(out).toContain("{% if first %}");
		expect(out).toContain("{% endif %}");
	});
	it("dotted field truthy", () => {
		const out = expectTokensPreserved("<p>a</p>\n{% if objekt.von %}\n<p>x</p>\n{% endif %}");
		expect(out).toContain("{% if objekt.von %}");
	});
	it("Vergleich == bleibt erhalten (Feld-Chip + Text)", () => {
		const out = expectTokensPreserved('<p>a</p>\n{% if mahnstufe == "2" %}\n<p>x</p>\n{% endif %}');
		expect(out).toContain('{% if mahnstufe == "2" %}');
	});
	it("komplexer Ausdruck/set bleibt atomar und erhalten", () => {
		expectTokensPreserved(
			'<p>a</p>\n{% set x = frappe.db.get_value("Y", n) %}\n{% if x %}\n<p>x</p>\n{% endif %}'
		);
	});
});

describe("if-Container (hvIfBlock)", () => {
	it("if + endif werden bei decorateForTiptap zu einem if-block-Container", () => {
		const decorated = decorateForTiptap(
			"<p>a</p>\n{% if first %}\n<p>x</p>\n{% endif %}\n<p>b</p>"
		);
		// Container existiert
		expect(decorated).toMatch(/data-hv-kind="if-block"/);
		// hvIf-Header ist im Container
		expect(decorated).toMatch(/data-hv-kind="if-block"[\s\S]*data-hv-kind="if"/);
		// endif-jinja-block ist NICHT mehr separat im Output
		expect(decorated).not.toMatch(/data-hv-token="\{%\s*endif\s*%\}"/);
	});
	it("verschachtelte ifs erzeugen verschachtelte Container", () => {
		const decorated = decorateForTiptap(
			"{% if a %}\n<p>x</p>\n{% if b %}\n<p>y</p>\n{% endif %}\n<p>z</p>\n{% endif %}"
		);
		// Zwei Container im Output
		const matches = decorated.match(/data-hv-kind="if-block"/g) || [];
		expect(matches.length).toBe(2);
	});
	it("if mit else: Container entsteht, else bekommt data-hv-branch", () => {
		const decorated = decorateForTiptap(
			"{% if a %}\n<p>x</p>\n{% else %}\n<p>y</p>\n{% endif %}"
		);
		expect(decorated).toMatch(/data-hv-kind="if-block"/);
		expect(decorated).toMatch(/data-hv-branch="else"/);
	});
	it("if/elif/else: Container mit beiden Branch-Markern", () => {
		const decorated = decorateForTiptap(
			"{% if a %}\n<p>x</p>\n{% elif b %}\n<p>y</p>\n{% else %}\n<p>z</p>\n{% endif %}"
		);
		expect(decorated).toMatch(/data-hv-kind="if-block"/);
		expect(decorated).toMatch(/data-hv-branch="elif"/);
		expect(decorated).toMatch(/data-hv-branch="else"/);
	});
	it("if/else Round-Trip preserved", () => {
		const out = expectTokensPreserved(
			"{% if a %}\n<p>x</p>\n{% else %}\n<p>y</p>\n{% endif %}"
		);
		expect(out).toContain("{% if a %}");
		expect(out).toContain("{% else %}");
		expect(out).toContain("{% endif %}");
	});
	it("verschachtelter if + endif Round-Trip", () => {
		expectTokensPreserved(
			"{% if a %}\n<p>x</p>\n{% if b %}\n<p>y</p>\n{% endif %}\n<p>z</p>\n{% endif %}"
		);
	});
});

describe("Mehrfach-Leerzeichen -> geschützte Leerzeichen", () => {
	const NBSP = String.fromCharCode(160);
	it("Lauf aus >=2 Leerzeichen wird zu nbsp (Kästchen bleibt erhalten)", () => {
		const out = serializeToTokens("<p>[      ] Auszug</p>");
		// 6 reguläre Leerzeichen -> 6 nbsp (als &nbsp; oder U+00A0 serialisiert)
		const normalized = out.replace(/&nbsp;/g, NBSP);
		expect(normalized).toContain(`[${NBSP.repeat(6)}]`);
		expect(normalized).toContain("Auszug");
	});
	it("einzelne Leerzeichen bleiben normal (Umbruch erhalten)", () => {
		const out = serializeToTokens("<p>Hallo Welt</p>");
		expect(out).toContain("Hallo Welt");
		expect(out).not.toContain(NBSP);
		expect(out).not.toContain("&nbsp;");
	});
});

describe("validateJinjaBalance", () => {
	it("balanciert", () => {
		expect(validateJinjaBalance("{% if a %}x{% endif %}").ok).toBe(true);
		expect(validateJinjaBalance("{% for r in xs %}y{% endfor %}").ok).toBe(true);
		expect(validateJinjaBalance("{% if a %}{% else %}{% endif %}").ok).toBe(true);
	});
	it("offener Block", () => {
		const r = validateJinjaBalance("{% if a %}x");
		expect(r.ok).toBe(false);
		expect(r.errors.length).toBe(1);
	});
	it("überzähliges endif", () => {
		expect(validateJinjaBalance("x{% endif %}").ok).toBe(false);
	});
	it("falsche Verschachtelung", () => {
		expect(validateJinjaBalance("{% if a %}{% endfor %}").ok).toBe(false);
	});
});
