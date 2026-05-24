// Jinja-Sicherheitsnetze für den Editor:
//  - validateJinjaBalance: warnt vor offenen/überzähligen {% if/for %}-Blöcken (nicht-blockierend).
//  - assertTokenPreservation: HARTER Check, dass beim Serialisieren kein Token verloren geht
//    oder hinzukommt (blockiert Speichern bei Verlust — z. B. exotische, nicht modellierte Loops).

import { tokenMultiset } from "./tokens.js";

const OPENERS = { if: "endif", for: "endfor", block: "endblock", with: "endwith" };
const CLOSERS = new Set(Object.values(OPENERS));
const NEUTRAL = new Set(["else", "elif", "endif", "endfor", "endblock", "endwith"]);

// Liefert { ok, errors: [string] }. errors leer => balanciert.
export function validateJinjaBalance(html) {
	const errors = [];
	const stack = [];
	const re = /\{%-?\s*(\w+)/g;
	let m;
	while ((m = re.exec(html || "")) !== null) {
		const tag = m[1];
		if (tag in OPENERS) {
			stack.push(tag);
		} else if (CLOSERS.has(tag)) {
			const expectedOpener = Object.keys(OPENERS).find((o) => OPENERS[o] === tag);
			const top = stack[stack.length - 1];
			if (!top) {
				errors.push(`{% ${tag} %} ohne zugehöriges {% ${expectedOpener} %}`);
			} else if (top !== expectedOpener) {
				errors.push(`{% ${tag} %} passt nicht zum offenen {% ${top} %}`);
				stack.pop();
			} else {
				stack.pop();
			}
		}
		// else/elif: keine Stack-Wirkung
		void NEUTRAL;
	}
	for (const open of stack) {
		errors.push(`{% ${open} %} ohne {% ${OPENERS[open]} %}`);
	}
	return { ok: errors.length === 0, errors };
}

// Vergleicht das Token-Multiset von Quelle (DB-HTML) und serialisiertem Ergebnis.
// Liefert { ok, lost: {token:count}, added: {token:count} }.
export function diffTokens(before, after) {
	const a = tokenMultiset(before);
	const b = tokenMultiset(after);
	const lost = {};
	const added = {};
	for (const k of Object.keys(a)) {
		const d = (a[k] || 0) - (b[k] || 0);
		if (d > 0) lost[k] = d;
	}
	for (const k of Object.keys(b)) {
		const d = (b[k] || 0) - (a[k] || 0);
		if (d > 0) added[k] = d;
	}
	return { ok: Object.keys(lost).length === 0 && Object.keys(added).length === 0, lost, added };
}
