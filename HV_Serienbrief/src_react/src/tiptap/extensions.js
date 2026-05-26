// TipTap-Schema für den Serienbrief-Editor.
//
// Custom-Nodes für die Jinja-/Platzhalter-Welt (atomar, round-trippen über data-hv-token):
//   hvPlaceholder  – inline  – {{ ... }} / {{$ ... $}}
//   hvBaustein     – inline  – {{ baustein("X") }}
//   hvJinjaInline  – inline  – {% ... %} innerhalb von Fließtext
//   hvJinjaBlock   – block   – {% ... %} als eigene Zeile zwischen Blöcken
// Tabellen-Zeilen-Loop: HvTableRow trägt das Attribut loopExpr (data-hv-loop) – die Schleife
// ist Zeilen-Metadatum, KEIN Wrapper-Node, damit prosemirror-tables intakt bleibt.
//
// Markup-Erhalt (siehe Inventar): Bold/Italic/Underline parsen die im Bestand genutzten
// Inline-Styles (font-weight/font-style/text-decoration); Superscript erhält <sup>;
// Zellen behalten ihr style (text-align).

import { Node, Extension, mergeAttributes } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import TextAlign from "@tiptap/extension-text-align";
import Link from "@tiptap/extension-link";
import Image from "@tiptap/extension-image";
import TextStyle from "@tiptap/extension-text-style";
import Highlight from "@tiptap/extension-highlight";
import Superscript from "@tiptap/extension-superscript";
import Subscript from "@tiptap/extension-subscript";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableHeader from "@tiptap/extension-table-header";
import TableCell from "@tiptap/extension-table-cell";

function innerOfPlaceholder(token) {
	const m = /\{\{\s*([\s\S]+?)\s*\}\}/.exec(token || "");
	let inner = m ? m[1].trim() : token || "";
	inner = inner.replace(/^\$\s*/, "").replace(/\s*\$$/, "");
	return inner;
}

function bausteinLabel(token) {
	const m = /\{\{\s*baustein\(\s*["']([^"']+)["']\s*\)\s*\}\}/.exec(token || "");
	return m ? m[1] : token || "";
}

// NodeView für die (atomaren) Jinja-Knoten: Doppelklick öffnet einen Prompt zum Bearbeiten des
// Ausdrucks (z. B. BEDINGUNG -> mahnstufe == "2"). Serialisierung läuft weiter über renderHTML.
function makeJinjaNodeView(tag, className, kind) {
	return ({ node, editor, getPos }) => {
		let current = node;
		const dom = document.createElement(tag);
		dom.className = className;
		dom.setAttribute("data-hv-kind", kind);
		dom.textContent = node.attrs.token;
		dom.title = "Doppelklick: Jinja-Ausdruck bearbeiten";
		dom.addEventListener("dblclick", (e) => {
			e.preventDefault();
			e.stopPropagation();
			if (!editor.isEditable) return;
			const next = window.prompt(
				'Jinja-Ausdruck bearbeiten (z. B. {% if mahnstufe == "2" %}):',
				current.attrs.token
			);
			if (next == null) return;
			const token = next.trim();
			if (!/^\{%[\s\S]*%\}$/.test(token)) {
				window.alert("Der Ausdruck muss mit {% beginnen und mit %} enden.");
				return;
			}
			const pos = typeof getPos === "function" ? getPos() : null;
			if (pos == null) return;
			editor
				.chain()
				.focus()
				.command(({ tr }) => {
					tr.setNodeMarkup(pos, undefined, { ...current.attrs, token });
					return true;
				})
				.run();
		});
		return {
			dom,
			update: (updated) => {
				if (updated.type.name !== current.type.name) return false;
				current = updated;
				dom.textContent = updated.attrs.token;
				return true;
			},
			ignoreMutation: () => true,
		};
	};
}

const tokenAttr = {
	default: "",
	parseHTML: (el) => el.getAttribute("data-hv-token") || el.getAttribute("data-token") || "",
	renderHTML: (attrs) => ({ "data-hv-token": attrs.token }),
};

// marks: "_" -> der Node erlaubt alle Marks (Bold/Italic/Underline/TextStyle für Schriftgröße & Farbe).
// ProseMirror rendert Marks um die NodeView-DOM, der serializeToTokens-Pfad ersetzt nur den
// Chip-Span durch den rohen Token, eine umschließende <strong>/<span style="font-size:…">-Hülle
// bleibt erhalten -> Markup landet 1:1 im PDF.
export const PlaceholderNode = Node.create({
	name: "hvPlaceholder",
	inline: true,
	group: "inline",
	atom: true,
	selectable: true,
	marks: "_",
	addAttributes() {
		return {
			token: tokenAttr,
			group: {
				default: "mieter",
				parseHTML: (el) => el.getAttribute("data-group") || "mieter",
				renderHTML: (attrs) => ({ "data-group": attrs.group }),
			},
		};
	},
	parseHTML() {
		return [
			{ tag: 'span[data-hv-kind="placeholder"]' },
			{
				tag: "span.chip[data-token]",
				getAttrs: (el) => (el.getAttribute("data-group") === "baustein" ? false : null),
			},
		];
	},
	renderHTML({ node, HTMLAttributes }) {
		return [
			"span",
			mergeAttributes(HTMLAttributes, { class: "chip", "data-hv-kind": "placeholder" }),
			innerOfPlaceholder(node.attrs.token),
		];
	},
});

export const BausteinNode = Node.create({
	name: "hvBaustein",
	inline: true,
	group: "inline",
	atom: true,
	selectable: true,
	marks: "_",
	addAttributes() {
		return { token: tokenAttr };
	},
	parseHTML() {
		return [
			{ tag: 'span[data-hv-kind="baustein"]', priority: 60 },
			{ tag: 'span.chip[data-group="baustein"][data-token]', priority: 60 },
		];
	},
	renderHTML({ node, HTMLAttributes }) {
		return [
			"span",
			mergeAttributes(HTMLAttributes, {
				class: "chip",
				"data-hv-kind": "baustein",
				"data-group": "baustein",
			}),
			`⧉ ${bausteinLabel(node.attrs.token)}`,
		];
	},
	// Doppelklick öffnet das Pfad-Mapping (Input-Pfade des Bausteins) via DOM-Event,
	// das die App abfängt. Serialisierung läuft weiter über renderHTML.
	addNodeView() {
		return ({ node }) => {
			// TipTap reuses NodeViews wenn der Node-Type gleich bleibt; bei Edits
			// kommt nur `update(updated)` mit den neuen Attrs. Der Click-Handler
			// muss daher gegen eine MUTABLE Referenz lesen, nicht gegen das
			// urspr\u00FCnglich captured `node` \u2014 sonst \u00F6ffnet sich der Popover des
			// alten Bausteins.
			let current = node;
			const dom = document.createElement("span");
			dom.className = "chip baustein-chip";
			dom.setAttribute("data-hv-kind", "baustein");
			dom.setAttribute("data-group", "baustein");
			dom.title = "Klick: Details / Input-Pfade";
			dom.textContent = "\u29C9 " + bausteinLabel(node.attrs.token) + " \u25BE";
			dom.addEventListener("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				const name = bausteinLabel(current.attrs.token);
				if (!name) return;
				const rect = dom.getBoundingClientRect();
				window.dispatchEvent(
					new CustomEvent("hv-baustein-popover", {
						detail: { name, rect: { left: rect.left, bottom: rect.bottom, top: rect.top } },
					})
				);
			});
			return {
				dom,
				ignoreMutation: () => true,
				update: (updated) => {
					if (updated.type.name !== "hvBaustein") return false;
					current = updated;
					dom.textContent = "\u29C9 " + bausteinLabel(updated.attrs.token) + " \u25BE";
					return true;
				},
			};
		};
	},
});

export const JinjaInlineNode = Node.create({
	name: "hvJinjaInline",
	inline: true,
	group: "inline",
	atom: true,
	selectable: true,
	addAttributes() {
		return { token: tokenAttr };
	},
	parseHTML() {
		return [
			{ tag: 'span[data-hv-kind="jinja-inline"]', priority: 60 },
			{ tag: "span.jinja-token[data-token]", priority: 60 },
		];
	},
	renderHTML({ node, HTMLAttributes }) {
		return [
			"span",
			mergeAttributes(HTMLAttributes, { class: "jinja-token", "data-hv-kind": "jinja-inline" }),
			node.attrs.token,
		];
	},
	addNodeView() {
		return makeJinjaNodeView("span", "jinja-token", "jinja-inline");
	},
});

export const JinjaBlockNode = Node.create({
	name: "hvJinjaBlock",
	group: "block",
	atom: true,
	selectable: true,
	addAttributes() {
		return { token: tokenAttr };
	},
	parseHTML() {
		return [{ tag: 'div[data-hv-kind="jinja-block"]' }];
	},
	renderHTML({ node, HTMLAttributes }) {
		return [
			"div",
			mergeAttributes(HTMLAttributes, { class: "jinja-block", "data-hv-kind": "jinja-block" }),
			node.attrs.token,
		];
	},
	addNodeView() {
		return makeJinjaNodeView("div", "jinja-block", "jinja-block");
	},
});

// Feld-Referenz INNERHALB einer Bedingung (bare identifier, z. B. mieter.anrede — NICHT {{ }}).
// Serialisiert über data-hv-name zu seinem nackten Namen.
export const FieldNode = Node.create({
	name: "hvField",
	inline: true,
	group: "inline",
	atom: true,
	selectable: true,
	marks: "_",
	addAttributes() {
		return {
			name: {
				default: "",
				parseHTML: (el) => el.getAttribute("data-hv-name") || "",
				renderHTML: (attrs) => ({ "data-hv-name": attrs.name }),
			},
			group: {
				default: "mieter",
				parseHTML: (el) => el.getAttribute("data-group") || "mieter",
				renderHTML: (attrs) => ({ "data-group": attrs.group }),
			},
		};
	},
	parseHTML() {
		return [{ tag: 'span[data-hv-kind="field"]' }];
	},
	renderHTML({ node, HTMLAttributes }) {
		return [
			"span",
			mergeAttributes(HTMLAttributes, { class: "chip field-chip", "data-hv-kind": "field" }),
			node.attrs.name,
		];
	},
});

// Inline-editierbarer {% if %}-Block: Inhalt = Bedingungsausdruck (Text + Feld-Chips).
// Serialisiert zu {% if <ausdruck> %}. Das zugehörige {% endif %} bleibt ein eigener
// (atomarer) hvJinjaBlock; der bedingte Text steht normal dazwischen.
export const IfNode = Node.create({
	name: "hvIf",
	group: "block",
	content: "inline*",
	defining: true,
	selectable: true,
	parseHTML() {
		return [{ tag: 'div[data-hv-kind="if"]' }];
	},
	renderHTML({ HTMLAttributes }) {
		return ["div", mergeAttributes(HTMLAttributes, { class: "jinja-if-block", "data-hv-kind": "if" }), 0];
	},
});

// Tabellen-Zeile mit optionalem Loop-Ausdruck (Schleife als Zeilen-Attribut).
export const HvTableRow = TableRow.extend({
	addAttributes() {
		return {
			...this.parent?.(),
			loopExpr: {
				default: null,
				parseHTML: (el) => el.getAttribute("data-hv-loop"),
				renderHTML: (attrs) => (attrs.loopExpr ? { "data-hv-loop": attrs.loopExpr } : {}),
			},
		};
	},
	addCommands() {
		return {
			setRowLoopExpr:
				(expr) =>
				({ state, dispatch }) => {
					const { $from } = state.selection;
					for (let d = $from.depth; d > 0; d--) {
						const node = $from.node(d);
						if (node.type.name === this.name) {
							if (dispatch) {
								const pos = $from.before(d);
								dispatch(
									state.tr.setNodeMarkup(pos, undefined, {
										...node.attrs,
										loopExpr: expr || null,
									})
								);
							}
							return true;
						}
					}
					return false;
				},
		};
	},
});

// Zellen sollen ihr inline style (im Bestand: text-align) behalten.
const styleAttr = {
	style: {
		default: null,
		parseHTML: (el) => el.getAttribute("style"),
		renderHTML: (attrs) => (attrs.style ? { style: attrs.style } : {}),
	},
};
export const HvTableCell = TableCell.extend({
	addAttributes() {
		return { ...this.parent?.(), ...styleAttr };
	},
});
export const HvTableHeader = TableHeader.extend({
	addAttributes() {
		return { ...this.parent?.(), ...styleAttr };
	},
});

// Tabelle mit optionalem Rahmen-Flag. ``borders`` round-trippt über data-hv-borders am
// <table> (Muster wie HvTableRow.loopExpr). Steuert per CSS, ob im Editor solide Rahmen
// statt der gestrichelten Hilfslinie gezeigt UND im PDF echte Rahmen gedruckt werden
// (Default randlos — Tabellen sind meist reine Layout-Hilfen).
export const HvTable = Table.extend({
	addAttributes() {
		return {
			...this.parent?.(),
			borders: {
				default: false,
				parseHTML: (el) => el.hasAttribute("data-hv-borders"),
				renderHTML: (attrs) => (attrs.borders ? { "data-hv-borders": "1" } : {}),
			},
		};
	},
});

// TextStyle-Zusätze: Schriftgröße + Textfarbe (ersetzt @tiptap/extension-color, weil wir die
// Farbe mit !important rendern müssen). Grund: Frappes Print-Bundle hat im PDF-Render eine
// globale Regel `@media print { *,*:before,*:after { color:#000 !important } }`, die jede
// Inline-Farbe ohne !important überschreibt. Inline-!important schlägt das universelle !important.
//
// fontSize-Werte werden in **pt** ausgegeben (z.B. "11pt") — passt 1:1 zum PDF-Render
// (Print-CSS = 11pt). Bestandsdaten mit `font-size: 15px` bleiben dank generischem
// `el.style.fontSize`-Parser unverändert lesbar; nur neue Eingaben sind in pt.
const TextStyleExtras = Extension.create({
	name: "hvTextStyleExtras",
	addGlobalAttributes() {
		return [
			{
				types: ["textStyle"],
				attributes: {
					fontSize: {
						default: null,
						parseHTML: (el) => el.style.fontSize || null,
						renderHTML: (attrs) =>
							attrs.fontSize ? { style: `font-size: ${attrs.fontSize}` } : {},
					},
					color: {
						default: null,
						parseHTML: (el) => (el.style.color ? el.style.color : null),
						renderHTML: (attrs) =>
							attrs.color ? { style: `color: ${attrs.color} !important` } : {},
					},
				},
			},
		];
	},
	addCommands() {
		return {
			setFontSize:
				(size) =>
				({ chain }) =>
					chain().setMark("textStyle", { fontSize: size }).run(),
			unsetFontSize:
				() =>
				({ chain }) =>
					chain().setMark("textStyle", { fontSize: null }).removeEmptyTextStyle().run(),
			setColor:
				(color) =>
				({ chain }) =>
					chain().setMark("textStyle", { color }).run(),
			unsetColor:
				() =>
				({ chain }) =>
					chain().setMark("textStyle", { color: null }).removeEmptyTextStyle().run(),
		};
	},
});

// Zeilenabstand auf paragraph-/heading-Ebene. Setzt `style="line-height: X"` direkt aufs
// <p>/<h*> — Inline-Style überschreibt das Print-CSS (`.serienbrief-page p { line-height: 1.35 }`)
// durch höhere Spezifität, daher kein !important nötig. Werte sind einheitenlos (Word-Konvention
// 1.0 / 1.15 / 1.35 / 1.5 / 2.0).
const ParagraphExtras = Extension.create({
	name: "hvParagraphExtras",
	addGlobalAttributes() {
		return [
			{
				types: ["paragraph", "heading"],
				attributes: {
					lineHeight: {
						default: null,
						parseHTML: (el) => el.style.lineHeight || null,
						renderHTML: (attrs) =>
							attrs.lineHeight ? { style: `line-height: ${attrs.lineHeight}` } : {},
					},
				},
			},
		];
	},
	addCommands() {
		return {
			setLineHeight:
				(value) =>
				({ chain, editor }) => {
					const types = ["paragraph", "heading"];
					let c = chain();
					for (const t of types) {
						if (editor.can().updateAttributes(t, { lineHeight: value })) {
							c = c.updateAttributes(t, { lineHeight: value });
						}
					}
					return c.run();
				},
			unsetLineHeight:
				() =>
				({ chain, editor }) => {
					const types = ["paragraph", "heading"];
					let c = chain();
					for (const t of types) {
						if (editor.can().updateAttributes(t, { lineHeight: null })) {
							c = c.updateAttributes(t, { lineHeight: null });
						}
					}
					return c.run();
				},
		};
	},
});

// Komplette Extension-Liste. onImageRequest() öffnet den Upload-Flow (vom Editor injiziert).
export function buildExtensions() {
	return [
		StarterKit.configure({
			heading: { levels: [1, 2, 3] },
		}),
		Underline,
		Superscript,
		Subscript,
		TextAlign.configure({ types: ["heading", "paragraph"] }),
		Link.configure({ openOnClick: false, autolink: false }),
		TextStyle,
		TextStyleExtras,
		ParagraphExtras,
		Highlight.configure({ multicolor: true }),
		Image.configure({ inline: false, allowBase64: false }),
		HvTable.configure({ resizable: true }),
		HvTableRow,
		HvTableHeader,
		HvTableCell,
		PlaceholderNode,
		BausteinNode,
		FieldNode,
		IfNode,
		JinjaInlineNode,
		JinjaBlockNode,
	];
}
