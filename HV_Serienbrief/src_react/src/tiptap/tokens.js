// Token-Round-Trip zwischen gespeichertem Vorlagen-HTML (rohe Jinja-Tokens) und
// dem TipTap-Schema (atomare Nodes). Zwei Richtungen:
//
//   DB-HTML  --decorateForTiptap-->  TipTap-parsbares HTML  --(TipTap)-->  Doc
//   Doc  --getHTML-->  Node-HTML  --serializeToTokens-->  DB-HTML
//
// Entwurfsregeln (siehe Plan + Inventar der echten Vorlagen):
//  - Inline-Tokens ({{ }}, {{$ $}}, {{ baustein("X") }}, inline {% %}) -> <span data-hv-*>.
//  - Block-Level {% %} (eigene Zeile zwischen Blockelementen) -> <div data-hv-kind="jinja-block">.
//  - Tabellen-Zeilen-Loop {% for X %}<tr>..</tr>{% endfor %} -> <tr data-hv-loop="X"> (robust:
//    Schleife als Zeilen-Attribut, NICHT als Wrapper-Node -> prosemirror-tables bleibt intakt).
//  - Abwärtskompatibel: parseHTML der Nodes liest auch das alte data-token-Chip-Format;
//    serializeToTokens berücksichtigt data-hv-token UND legacy data-token.
//  - Serialisierung gibt ROHE Tokens aus (keine HTML-Entity-Escapes), via Sentinel-Platzhalter.

// EIN kombinierter Token-Scanner. Reihenfolge: baustein vor generisch (beide {{ }});
// {{$ $}} vor generisch; {% %} zuletzt. Ein einzelner String.replace() re-scannt seinen
// Ersetzungstext NICHT -> die {{ }} in den erzeugten data-hv-token-Attributen werden nicht
// erneut gematcht.
const TOKEN_RE =
	/\{\{\s*baustein\(\s*["']([^"']+)["']\s*\)\s*\}\}|\{\{\$\s*([\s\S]+?)\s*\$\}\}|\{\{([^}]+)\}\}|\{%([^%]*)%\}/g;

const PREFIX_GROUP = {
	mieter: "mieter",
	hauptmieter: "mieter",
	empfaenger: "mieter",
	kunde: "mieter",
	objekt: "vertrag",
	eigentuemer: "verwalter",
	verwalter: "verwalter",
	wohnung: "wohnung",
	immobilie: "wohnung",
	mietvertrag: "vertrag",
	dunning: "vertrag",
	saldo: "vertrag",
	saldo_betrag: "vertrag",
	kaltmiete: "vertrag",
	nebenkosten: "vertrag",
	warmmiete: "vertrag",
	mahnstufe: "vertrag",
	datum: "datum",
	datum_iso: "datum",
	stichtag: "datum",
	frist_tage: "datum",
	bankkonto: "bank",
};

function escapeAttr(s) {
	return String(s)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function escapeHtml(s) {
	return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function groupForToken(inner) {
	const prefix = (inner || "").trim().split(/[.\s(]/)[0].toLowerCase();
	return PREFIX_GROUP[prefix] || "mieter";
}

// Display-Label des Bausteins aus dem Roh-Token ziehen.
export function bausteinName(token) {
	const m = /\{\{\s*baustein\(\s*["']([^"']+)["']\s*\)\s*\}\}/.exec(token || "");
	return m ? m[1] : "";
}

function span(kind, rawToken, group, displayText) {
	const groupAttr = group ? ` data-group="${escapeAttr(group)}"` : "";
	const cls = kind === "jinja-inline" ? "jinja-token" : "chip";
	return (
		`<span class="${cls}" data-hv-kind="${kind}"${groupAttr}` +
		` data-hv-token="${escapeAttr(rawToken)}">${displayText}</span>`
	);
}

// Schritt 1: alle Tokens inline in <span data-hv-*> wrappen (ein Replace-Pass).
function wrapInlineTokens(html) {
	if (!html) return "";
	return html.replace(TOKEN_RE, (m, bausteinArg, customInner, genericInner, jinjaInner) => {
		const raw = m.trim();
		if (bausteinArg !== undefined) {
			return span("baustein", raw, "baustein", `⧉&nbsp;${escapeHtml(bausteinArg)}`);
		}
		if (customInner !== undefined) {
			return span("placeholder", raw, groupForToken(customInner), escapeHtml(customInner.trim()));
		}
		if (genericInner !== undefined) {
			return span("placeholder", raw, groupForToken(genericInner), escapeHtml(genericInner.trim()));
		}
		// {% ... %}
		return span("jinja-inline", raw, null, escapeHtml(raw));
	});
}

const BLOCK_TAGS = new Set([
	"P", "DIV", "TABLE", "THEAD", "TBODY", "TR", "TD", "TH", "UL", "OL", "LI",
	"H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "HR", "BODY", "PRE", "FIGURE",
]);

function isBlockContext(el) {
	// Block-Promotion nur, wenn der Eltern-Container ein Block-Flow ist (nicht in <p>/<td>/Heading,
	// wo {% %} echt inline gemeint ist) und das span allein zwischen Block-Geschwistern steht.
	const parent = el.parentElement;
	if (!parent) return false;
	const pt = parent.tagName;
	if (!["BODY", "DIV", "TBODY", "THEAD", "TABLE"].includes(pt)) return false;
	// Geschwister links/rechts (Whitespace ignorieren) dürfen kein Inline-Text sein.
	const sibText = (node, dir) => {
		let n = dir === "prev" ? node.previousSibling : node.nextSibling;
		while (n) {
			if (n.nodeType === 3 && n.textContent.trim() === "") {
				n = dir === "prev" ? n.previousSibling : n.nextSibling;
				continue;
			}
			return n;
		}
		return null;
	};
	const prev = sibText(el, "prev");
	const next = sibText(el, "next");
	const okSide = (n) => n === null || (n.nodeType === 1 && BLOCK_TAGS.has(n.tagName)) || (n.nodeType === 1 && n.getAttribute && n.getAttribute("data-hv-kind"));
	return okSide(prev) && okSide(next);
}

// Schritt 2a: inline-Jinja-Spans, die in Wahrheit Block-Level sind, zu Block-Divs befördern.
function promoteBlockJinja(root, doc) {
	const spans = Array.from(root.querySelectorAll('span[data-hv-kind="jinja-inline"]'));
	for (const s of spans) {
		if (!isBlockContext(s)) continue;
		const div = doc.createElement("div");
		div.setAttribute("data-hv-kind", "jinja-block");
		div.setAttribute("data-hv-token", s.getAttribute("data-hv-token") || "");
		s.replaceWith(div);
	}
}

// Schritt 0 (string-basiert, VOR jedem DOM-Parse!): {% for X %}<tr>..</tr>{% endfor %}
// -> <tr data-hv-loop="X">..</tr>. Muss als String laufen, weil der HTML-Parser jeden
// Nicht-Tabellen-Knoten (Text/Span) aus <tbody> herausziehen würde (foster parenting) –
// dann wäre der Loop-Marker nicht mehr neben seiner Zeile. Erkennt Einzel-Zeilen-Loops
// (der reale Fall); Mehrzeilen-/exotische Loops bleiben unangetastet und werden vom
// Token-Erhalt-Check beim Speichern abgefangen.
const TABLE_LOOP_RE =
	/\{%-?\s*for\s+([\s\S]*?)\s*-?%\}\s*(<tr\b[\s\S]*?<\/tr>)\s*\{%-?\s*endfor\s*-?%\}/gi;

function foldTableLoopsString(html) {
	return html.replace(TABLE_LOOP_RE, (m, expr, trHtml) => {
		const e = escapeAttr(expr.trim());
		return trHtml.replace(/^<tr\b/i, `<tr data-hv-loop="${e}"`);
	});
}

function parseBody(html) {
	const doc = new DOMParser().parseFromString(`<body>${html || ""}</body>`, "text/html");
	return doc;
}

// Legacy-Quill-Ausrichtungsklassen (ql-align-center/right/justify) zu inline text-align
// normalisieren, damit TipTaps TextAlign sie erhält. Kommt im aktuellen Bestand nicht vor,
// aber Vorsorge gegen künftige (Quill-)Importe.
function normalizeLegacyClasses(root) {
	root.querySelectorAll('[class*="ql-align-"]').forEach((el) => {
		const m = /ql-align-(left|center|right|justify)/.exec(el.className || "");
		if (m) {
			if (!/text-align/i.test(el.getAttribute("style") || "")) {
				const sep = el.getAttribute("style") ? "; " : "";
				el.setAttribute("style", (el.getAttribute("style") || "") + sep + `text-align: ${m[1]}`);
			}
			el.classList.remove(`ql-align-${m[1]}`);
			if (!el.getAttribute("class")) el.removeAttribute("class");
		}
	});
}

// Öffentlich: DB-HTML -> TipTap-parsbares HTML.
export function decorateForTiptap(html) {
	if (!html) return "";
	const folded = foldTableLoopsString(html); // Tabellen-Loops zuerst (string!)
	const wrapped = wrapInlineTokens(folded); // restliche Tokens inline wrappen
	const doc = parseBody(wrapped);
	normalizeLegacyClasses(doc.body); // ql-align-* -> text-align (Vorsorge)
	promoteBlockJinja(doc.body, doc); // block-level {% %} zwischen Blöcken hochstufen
	return doc.body.innerHTML;
}

// Öffentlich: TipTap-getHTML() -> DB-HTML mit rohen Tokens.
// Sentinel-Strategie, damit rohe Tokens NICHT HTML-escaped werden.
const S_OPEN = "\uE000HVTOK";
const S_CLOSE = "\uE001";

export function serializeToTokens(html) {
	if (!html) return "";
	const doc = parseBody(html);
	const sentinels = [];
	const sentinel = (raw) => {
		const key = `${S_OPEN}${sentinels.length}${S_CLOSE}`;
		sentinels.push({ key, raw });
		return key;
	};

	// 1) Tabellen-Loop-Zeilen entfalten: <tr data-hv-loop="X"> -> {% for X %}<tr>..</tr>{% endfor %}
	doc.querySelectorAll("tr[data-hv-loop]").forEach((tr) => {
		const expr = tr.getAttribute("data-hv-loop") || "";
		tr.removeAttribute("data-hv-loop");
		const open = doc.createTextNode(sentinel(`{% for ${expr} %}`) + "\n");
		const close = doc.createTextNode("\n" + sentinel("{% endfor %}"));
		tr.parentNode.insertBefore(open, tr);
		if (tr.nextSibling) tr.parentNode.insertBefore(close, tr.nextSibling);
		else tr.parentNode.appendChild(close);
	});

	// 2) Block-Jinja-Divs -> roher Token (als Text-Sentinel)
	doc.querySelectorAll('[data-hv-kind="jinja-block"]').forEach((el) => {
		const raw = el.getAttribute("data-hv-token") || "";
		el.replaceWith(doc.createTextNode(sentinel(raw)));
	});

	// 3) Alle übrigen Token-Träger (neu data-hv-token + legacy data-token) -> roher Token
	doc.querySelectorAll("[data-hv-token],[data-token]").forEach((el) => {
		const raw = el.getAttribute("data-hv-token") || el.getAttribute("data-token") || "";
		el.replaceWith(doc.createTextNode(sentinel(raw)));
	});

	let out = doc.body.innerHTML;
	for (const { key, raw } of sentinels) {
		out = out.split(key).join(raw);
	}
	return out;
}

// Alle Tokens eines HTML/Text als Multiset (für den Erhalt-Check beim Speichern).
export function tokenMultiset(text) {
	const counts = {};
	const src = String(text || "");
	let m;
	TOKEN_RE.lastIndex = 0;
	while ((m = TOKEN_RE.exec(src)) !== null) {
		const key = m[0].replace(/\s+/g, " ").trim();
		counts[key] = (counts[key] || 0) + 1;
	}
	return counts;
}
