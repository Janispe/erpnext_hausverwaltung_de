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

const tokenAttr = {
	default: "",
	parseHTML: (el) => el.getAttribute("data-hv-token") || el.getAttribute("data-token") || "",
	renderHTML: (attrs) => ({ "data-hv-token": attrs.token }),
};

export const PlaceholderNode = Node.create({
	name: "hvPlaceholder",
	inline: true,
	group: "inline",
	atom: true,
	selectable: true,
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

// TextStyle-Zusätze: Schriftgröße + Textfarbe (ersetzt @tiptap/extension-color, weil wir die
// Farbe mit !important rendern müssen). Grund: Frappes Print-Bundle hat im PDF-Render eine
// globale Regel `@media print { *,*:before,*:after { color:#000 !important } }`, die jede
// Inline-Farbe ohne !important überschreibt. Inline-!important schlägt das universelle !important.
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
		Highlight.configure({ multicolor: true }),
		Image.configure({ inline: false, allowBase64: false }),
		Table.configure({ resizable: true }),
		HvTableRow,
		HvTableHeader,
		HvTableCell,
		PlaceholderNode,
		BausteinNode,
		JinjaInlineNode,
		JinjaBlockNode,
	];
}
