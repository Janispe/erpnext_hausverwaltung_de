// High-level Daten-API für den Editor. Eingebettet (im Frappe-iframe) gehen die
// Aufrufe über die postMessage-Bridge an echte Backend-Methoden; standalone
// (npm run dev) fallen sie auf die Mock-Daten aus data.js zurück.

import { rpc, isEmbedded } from "./bridge.js";
import { TEMPLATE_TREE, CURRENT_TEMPLATE } from "./data.js";

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
		// Echte Vorlagen liefern HTML statt des Block-Modells. Der Editor rendert
		// htmlContent read-only (mit Chip-Dekoration), wenn gesetzt.
		htmlContent: t.html || "",
		blocks: [],
		mock: false,
	};
}
