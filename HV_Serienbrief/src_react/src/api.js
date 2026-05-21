// High-level Daten-API für den Editor. Eingebettet (im Frappe-iframe) gehen die
// Aufrufe über die postMessage-Bridge an echte Backend-Methoden; standalone
// (npm run dev) fallen sie auf die Mock-Daten aus data.js zurück.

import { rpc, isEmbedded } from "./bridge.js";
import {
	TEMPLATE_TREE,
	CURRENT_TEMPLATE,
	PLACEHOLDER_GROUPS,
	TEXT_BAUSTEINE,
	SAMPLE_RECIPIENTS,
} from "./data.js";

export const embedded = isEmbedded();

// Vorlagen-Baum: { groups: [{key,label,count,templates:[{id,title,modified}]}], total }
export async function loadTree() {
	if (!embedded) {
		const total = TEMPLATE_TREE.reduce((n, c) => n + c.templates.length, 0);
		return { groups: TEMPLATE_TREE, total, mock: true };
	}
	const res = await rpc("tree");
	return { ...res, mock: false };
}

// Einzelne Vorlage. Eingebettet → echtes HTML aus der DB (als template.htmlContent).
// Standalone → die statische Demo-Vorlage (Block-Modell).
export async function loadTemplate(id) {
	if (!embedded) {
		return { ...CURRENT_TEMPLATE, mock: true };
	}
	const t = await rpc("template", { name: id });
	return {
		id: t.id,
		title: t.title,
		kategorie: t.kategorie_label || t.kategorie || "",
		haupt_verteil_objekt: t.haupt_verteil_objekt || "",
		content_type: t.content_type,
		content_position: t.content_position,
		modified: t.modified,
		modified_by: t.modified_by,
		canWrite: !!t.can_write,
		// Echte Vorlagen liefern HTML statt des Block-Modells. Der Editor rendert
		// htmlContent (mit Chip-Dekoration), editierbar wenn canWrite.
		htmlContent: t.html || "",
		blocks: [],
		mock: false,
	};
}

// Editierten Inhalt zurück in die Vorlage speichern. Gibt { id, modified } zurück.
export async function saveTemplate(id, html) {
	if (!embedded) {
		return { id, modified: "gerade eben (Demo)", mock: true };
	}
	return await rpc("save", { name: id, html });
}

// Bausteine (Serienbrief Textbaustein) für die Bausteine-Sidebar.
export async function loadBausteine() {
	if (!embedded) {
		return {
			items: TEXT_BAUSTEINE.map((b) => ({
				name: b.name,
				title: b.name,
				description: b.desc || "",
				preview: (b.preview || "").replace(/\n+/g, " · "),
			})),
		};
	}
	return await rpc("bausteine");
}

// Voller Platzhalter-Baum (Parität zum alten Formular-Picker): Gruppen mit
// rekursivem Feld-Baum, abgeleitet aus dem Iterationsobjekt + Variablen + Referenzen.
export async function loadPlaceholderTree(name) {
	if (!embedded) {
		// Mock: flache Gruppen in Baum-Form überführen
		return {
			groups: PLACEHOLDER_GROUPS.map((g) => ({
				key: g.key,
				label: g.label,
				icon: g.icon,
				tree: g.items.map((it) => ({ label: it.label, token: it.token, type: "", children: [] })),
			})),
		};
	}
	return await rpc("placeholder_tree", { name: name || "" });
}

// Echte Empfänger (z. B. Mietverträge) für den Vorschau-Picker.
export async function loadRecipients(doctype, query) {
	if (!embedded) {
		return { items: SAMPLE_RECIPIENTS.map((r) => ({ id: r.id, label: r.label })), doctype: "Mietvertrag" };
	}
	return await rpc("recipients", { doctype: doctype || "", query: query || "" });
}

// PDF-Vorschau rendern. Mit Empfänger → echte Daten (Durchlauf-Pfad, gespeicherte
// Vorlage); ohne → Split-Preview mit Beispielwerten. Gibt { pdf_base64, mode }.
export async function renderPreview({ templateName, hauptVerteilObjekt, recipientId }) {
	if (!embedded) return { pdf_base64: "", mode: "mock" };
	const params = { template: templateName };
	if (recipientId && hauptVerteilObjekt) {
		params.iteration_doctype = hauptVerteilObjekt;
		params.iteration_objekt = recipientId;
	} else {
		params.split_preview = 1;
	}
	return await rpc("preview", params);
}
