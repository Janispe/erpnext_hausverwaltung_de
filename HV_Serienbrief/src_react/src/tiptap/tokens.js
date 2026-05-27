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

// "Einfacher" Bedingungsausdruck: nur Bezeichner/Operatoren/Literale – keine Funktionsaufrufe,
// Filter oder Set-Konstrukte. Komplexe Ausdrücke (z. B. frappe.get_value(...), | selectattr)
// bleiben atomar, damit nichts kaputtgeht.
function isSimpleExpr(expr) {
	return !/[(|{}]/.test(expr);
}

const EXPR_KEYWORDS = new Set([
	"and", "or", "not", "in", "is", "none", "true", "false", "None", "True", "False",
]);

// Bedingungsausdruck verlustfrei in HTML partitionieren: Feld-Bezeichner -> Chip-Span,
// alles andere (Operatoren, Literale, Leerzeichen) -> escaped Text. Konkatenation ergibt
// exakt den Originalausdruck wieder (Round-Trip-Garantie).
function decorateExpr(expr) {
	const re = /[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*/g;
	let out = "";
	let last = 0;
	let m;
	while ((m = re.exec(expr)) !== null) {
		const id = m[0];
		const start = m.index;
		const after = expr[start + id.length];
		if (EXPR_KEYWORDS.has(id) || after === "(") continue; // Keyword/Funktion -> als Text lassen
		out += escapeHtml(expr.slice(last, start));
		out +=
			`<span data-hv-kind="field" data-group="${escapeAttr(groupForToken(id))}"` +
			` data-hv-name="${escapeAttr(id)}">${escapeHtml(id)}</span>`;
		last = start + id.length;
	}
	out += escapeHtml(expr.slice(last));
	return out;
}

// Schritt 2a: inline-Jinja-Spans, die in Wahrheit Block-Level sind, hochstufen.
// {% if EINFACH %} -> editierbarer hvIf-Block (Feld-Chips); alles andere -> atomarer jinja-block.
// Nur schlichte Delimiter (kein {%- / -%} Whitespace-Control) -> die bleiben atomar, sonst
// ginge die Trim-Semantik beim Zurückschreiben verloren.
const IF_RE = /^\{%\s*if\s+([\s\S]+?)\s*%\}$/;
function promoteBlockJinja(root, doc) {
	const spans = Array.from(root.querySelectorAll('span[data-hv-kind="jinja-inline"]'));
	for (const s of spans) {
		if (!isBlockContext(s)) continue;
		const token = s.getAttribute("data-hv-token") || "";
		const ifm = IF_RE.exec(token);
		if (ifm && isSimpleExpr(ifm[1])) {
			const div = doc.createElement("div");
			div.setAttribute("data-hv-kind", "if");
			div.innerHTML = decorateExpr(ifm[1]);
			s.replaceWith(div);
			continue;
		}
		const div = doc.createElement("div");
		div.setAttribute("data-hv-kind", "jinja-block");
		div.setAttribute("data-hv-token", token);
		s.replaceWith(div);
	}
}

// Schritt 2b: hvIf + zugehöriges {% endif %} (+ alles dazwischen, inkl.
// {% else %}/{% elif %}) zu einem hvIfBlock-Container zusammenfassen.
// Header-hvIf bleibt erstes Kind; das {% endif %}-Element wird entfernt
// (implizit durch das Container-Ende). Zwischenliegende {% else %}/{% elif %}-
// Blocks bleiben als normale hvJinjaBlocks im Body und werden visuell als
// Branch-Trenner markiert (data-hv-branch="else|elif"), damit CSS sie eigen
// stylen kann; im Token-Output sind sie unverändert.
// Nesting per Counter; querySelectorAll-Reverse iteriert innen-vor-außen.
const ENDIF_RE = /^\{%\s*endif\s*%\}$/;
const ELSE_RE = /^\{%\s*else\s*%\}$/;
const ELIF_RE = /^\{%\s*elif\b/;

function groupIfBlocks(root, doc) {
	const ifs = Array.from(root.querySelectorAll('[data-hv-kind="if"]'));
	for (let i = ifs.length - 1; i >= 0; i--) {
		const ifEl = ifs[i];
		const parent = ifEl.parentNode;
		if (!parent) continue;
		if (parent.getAttribute && parent.getAttribute("data-hv-kind") === "if-block") continue;

		let depth = 1;
		let endifEl = null;
		const branchMarks = []; // [{el, kind}] für die else/elif auf Top-Level dieses ifs
		let node = ifEl.nextSibling;
		while (node) {
			if (node.nodeType === 1) {
				const kind = node.getAttribute && node.getAttribute("data-hv-kind");
				if (kind === "if") {
					depth++;
				} else if (kind === "jinja-block") {
					const tok = (node.getAttribute("data-hv-token") || "").trim();
					if (ENDIF_RE.test(tok)) {
						depth--;
						if (depth === 0) {
							endifEl = node;
							break;
						}
					} else if (depth === 1 && ELSE_RE.test(tok)) {
						branchMarks.push({ el: node, kind: "else" });
					} else if (depth === 1 && ELIF_RE.test(tok)) {
						branchMarks.push({ el: node, kind: "elif" });
					}
				}
			}
			node = node.nextSibling;
		}
		if (!endifEl) continue;

		// Branch-Marker setzen (CSS-Hook), Token bleibt unverändert.
		for (const { el, kind } of branchMarks) {
			el.setAttribute("data-hv-branch", kind);
		}

		const container = doc.createElement("div");
		container.setAttribute("data-hv-kind", "if-block");
		parent.insertBefore(container, ifEl);
		let cur = ifEl;
		while (cur && cur !== endifEl) {
			const next = cur.nextSibling;
			container.appendChild(cur);
			cur = next;
		}
		endifEl.parentNode.removeChild(endifEl);
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
	groupIfBlocks(doc.body, doc); // hvIf + endif -> hvIfBlock-Container (collapsible)
	return doc.body.innerHTML;
}

// Inhalt eines hvIf-Blocks zum Bedingungsausdruck zusammensetzen: Feld-Chips -> bare name,
// Text -> Text. Verlustfreie Umkehr von decorateExpr.
function exprFromNodes(nodes) {
	let s = "";
	for (const n of nodes) {
		if (n.nodeType === 3) {
			s += n.textContent;
		} else if (n.nodeType === 1) {
			if (n.getAttribute && n.getAttribute("data-hv-kind") === "field") {
				s += n.getAttribute("data-hv-name") || "";
			} else {
				s += n.textContent || "";
			}
		}
	}
	return s.trim();
}

// Öffentlich: TipTap-getHTML() -> DB-HTML mit rohen Tokens.
// Sentinel-Strategie, damit rohe Tokens NICHT HTML-escaped werden.
const S_OPEN = "\uE000HVTOK";
const S_CLOSE = "\uE001";

// Läufe aus >=2 Leerzeichen in allen Textknoten zu geschützten Leerzeichen (U+00A0)
// machen — sonst kollabiert HTML sie beim Rendern. Einzelne Leerzeichen bleiben normal.
function preserveMultiSpaces(doc) {
	const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null);
	const texts = [];
	let n;
	while ((n = walker.nextNode())) texts.push(n);
	for (const t of texts) {
		if (t.nodeValue && / {2,}/.test(t.nodeValue)) {
			t.nodeValue = t.nodeValue.replace(/ {2,}/g, (m) => " ".repeat(m.length));
		}
	}
}

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

	// 1b) hvIfBlock-Container auflösen: Inhalt VOR den Container schieben, hinten
	// einen {% endif %}-Sentinel anhängen, Container entfernen. Der hvIf darin
	// wird vom anschließenden Pass (2) zum {% if X %}-Sentinel. Container in
	// Doc-Order verarbeiten -> äußere zuerst aufgeklappt, dann innere; jeder
	// schreibt sein eigenes endif an der richtigen Stelle.
	doc.querySelectorAll('[data-hv-kind="if-block"]').forEach((container) => {
		const parent = container.parentNode;
		if (!parent) return;
		while (container.firstChild) parent.insertBefore(container.firstChild, container);
		parent.insertBefore(doc.createTextNode("\n" + sentinel("{% endif %}")), container);
		parent.removeChild(container);
	});

	// 2) hvIf-Blöcke -> {% if <ausdruck> %}. Ausdruck = Inhalt (Feld-Chips -> bare name, Text -> Text).
	doc.querySelectorAll('[data-hv-kind="if"]').forEach((el) => {
		const expr = exprFromNodes(el.childNodes);
		el.replaceWith(doc.createTextNode(sentinel(`{% if ${expr} %}`)));
	});

	// 3) Block-Jinja-Divs -> roher Token (als Text-Sentinel)
	doc.querySelectorAll('[data-hv-kind="jinja-block"]').forEach((el) => {
		const raw = el.getAttribute("data-hv-token") || "";
		el.replaceWith(doc.createTextNode(sentinel(raw)));
	});

	// 4) Verbliebene Feld-Chips (z. B. außerhalb einer Bedingung) -> bare name
	doc.querySelectorAll('[data-hv-kind="field"]').forEach((el) => {
		el.replaceWith(doc.createTextNode(sentinel(el.getAttribute("data-hv-name") || "")));
	});

	// 5) Alle übrigen Token-Träger (neu data-hv-token + legacy data-token) -> roher Token
	doc.querySelectorAll("[data-hv-token],[data-token]").forEach((el) => {
		const raw = el.getAttribute("data-hv-token") || el.getAttribute("data-token") || "";
		el.replaceWith(doc.createTextNode(sentinel(raw)));
	});

	// 6) Mehrfach-Leerzeichen (>=2) in Textknoten -> geschützte Leerzeichen ( ),
	// damit gewollte Abstände ("[   ]"-Kästchen, Einrückungen) im PDF erhalten bleiben.
	// HTML faltet normalen Whitespace sonst zu EINEM Leerzeichen zusammen. Einzelne
	// Leerzeichen bleiben normal -> Fließtext bricht weiter um. Token-Sentinels enthalten
	// keine Mehrfach-Leerzeichen, werden also nicht berührt.
	preserveMultiSpaces(doc);

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
