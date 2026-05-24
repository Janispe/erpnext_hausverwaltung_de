// Rollout-Gate: jagt ALLE echten Vorlagen durch die volle Pipeline
// (decorate -> echter TipTap-Parse -> getHTML -> serialize) und prüft zweierlei:
//  1) Token-Erhalt: kein {{ }} / {% %} / baustein geht verloren.
//  2) Markup-Erhalt: keine class / text-align / font-size geht verloren (die echten
//     Verlust-Kategorien). Benigne Normalisierungen (b->strong, div->p, thead->tbody,
//     style-span->mark) sind erlaubt.
// Liest die per bench gedumpte JSON; wird übersprungen, wenn sie fehlt.
//
// Dump:  docker exec -i <backend> bench --site frontend console < /tmp/hv_dump_templates.py
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Editor } from "@tiptap/core";
import { buildExtensions } from "./extensions.js";
import { decorateForTiptap, serializeToTokens } from "./tokens.js";
import { diffTokens } from "./validateJinja.js";

const JSON_PATH = resolve(process.cwd(), "../_tmp_templates.json");
const hasDump = existsSync(JSON_PATH);

// Zählt class-Werte, text-align- und font-size-Vorkommen (die verlustkritischen Dinge).
function markupInventory(html) {
	const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
	const inv = {};
	const bump = (k) => (inv[k] = (inv[k] || 0) + 1);
	doc.body.querySelectorAll("*").forEach((el) => {
		(el.getAttribute("class") || "").split(/\s+/).forEach((c) => c && bump(`class:${c}`));
		const style = el.getAttribute("style") || "";
		const ta = /text-align\s*:\s*([a-z]+)/i.exec(style);
		if (ta) bump(`text-align:${ta[1].toLowerCase()}`);
		if (/font-size\s*:/i.test(style)) bump("font-size");
	});
	return inv;
}

function droppedKeys(before, after) {
	const lost = {};
	for (const k of Object.keys(before)) {
		const d = before[k] - (after[k] || 0);
		if (d > 0) lost[k] = d;
	}
	return lost;
}

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

describe.skipIf(!hasDump)("Round-Trip aller echten Vorlagen", () => {
	const templates = hasDump ? JSON.parse(readFileSync(JSON_PATH, "utf-8")) : [];

	it(`${templates.length} Vorlagen verlieren keine Tokens`, () => {
		const offenders = [];
		for (const t of templates) {
			const d = diffTokens(t.html, roundTrip(t.html));
			if (!d.ok) offenders.push({ name: t.name, lost: d.lost, added: d.added });
		}
		if (offenders.length) console.error("TOKEN-VERLUST:", JSON.stringify(offenders, null, 2));
		expect(offenders).toEqual([]);
	});

	it(`${templates.length} Vorlagen verlieren keine class/text-align/font-size`, () => {
		const offenders = [];
		for (const t of templates) {
			const lost = droppedKeys(markupInventory(t.html), markupInventory(roundTrip(t.html)));
			if (Object.keys(lost).length) offenders.push({ name: t.name, lost });
		}
		if (offenders.length) console.error("MARKUP-VERLUST:", JSON.stringify(offenders, null, 2));
		expect(offenders).toEqual([]);
	});
});
