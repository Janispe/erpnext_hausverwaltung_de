// High-level Daten-API für den Vorlagen-Browser. Eingebettet (im Frappe-iframe)
// gehen die Aufrufe über die postMessage-Bridge an whitelisted Backend-Methoden;
// standalone (npm run dev:browser) fallen sie auf die Mock-Daten aus data.js zurück.
//
// Die Aktions-Namen ("browser_data", "set_favorite", …) sind kurze Bezeichner, die
// die Host-Page (page/serienbrief_browser/serienbrief_browser.js) auf echte Methoden
// mappt — kein freier Methodenname aus dem iframe.

import { rpc, isEmbedded } from "../bridge.js";
import { BROWSER_FOLDERS, BROWSER_TEMPLATES } from "./data.js";

export const embedded = isEmbedded();

// Ordnerbaum (Kategorie) + alle Vorlagen mit Metadaten.
// → { folders:[{id,title,parent,is_group,color,count}], templates:[…], total }
export async function loadBrowserData() {
	if (!embedded) {
		const counts = {};
		BROWSER_TEMPLATES.forEach((t) => {
			counts[t.folder] = (counts[t.folder] || 0) + 1;
		});
		const folders = BROWSER_FOLDERS.map((f) => ({
			...f,
			parent: f.parent || null,
			count: counts[f.id] || f.count || 0,
		}));
		return { folders, templates: BROWSER_TEMPLATES, total: BROWSER_TEMPLATES.length, mock: true };
	}
	const res = await rpc("browser_data");
	return { ...res, mock: false };
}

// Favorit-Flag setzen/entfernen. → { name, favorite }
export async function setFavorite(id, favorite) {
	if (!embedded) return { name: id, favorite: !!favorite, mock: true };
	return await rpc("set_favorite", { template: id, favorite: favorite ? 1 : 0 });
}

// Vorlagen in einen anderen Ordner verschieben. → { moved:[…], kategorie }
export async function moveTemplates(ids, kategorie) {
	if (!embedded) return { moved: ids, kategorie, mock: true };
	return await rpc("move", { templates: JSON.stringify(ids), kategorie });
}

// Vorlage duplizieren. → { name, title }
export async function copyTemplate(id, newTitle) {
	if (!embedded) return { name: `${id}-kopie`, title: newTitle || "Kopie", mock: true };
	return await rpc("copy", { template: id, new_title: newTitle });
}

// Neue Vorlage anlegen. → { name, title }
export async function createTemplate(title, kategorie, hauptVerteilObjekt = "Mietvertrag") {
	if (!embedded) return { name: title, title, kategorie, haupt_verteil_objekt: hauptVerteilObjekt, mock: true };
	return await rpc("create_template", {
		title,
		kategorie,
		haupt_verteil_objekt: hauptVerteilObjekt,
	});
}

// Vorlage löschen. → { name }
export async function deleteTemplate(id) {
	if (!embedded) return { name: id, mock: true };
	return await rpc("delete", { template: id });
}

// Neuen Ordner anlegen. → { id, title, parent, color }
export async function createFolder(title, parent, color) {
	if (!embedded) return { id: title, title, parent: parent || null, color: color || null, mock: true };
	return await rpc("create_folder", { title, parent: parent || "", color: color || "" });
}

// Neues "Serienbrief Durchlauf"-Formular im Desk öffnen (Vorlage vorausgewählt).
// Navigiert das Eltern-Desk weg vom Browser — kein Rückgabewert nötig.
export async function openDurchlauf({ vorlage, title, iterationDoctype }) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("new_durchlauf", { vorlage, title, iteration_doctype: iterationDoctype });
}

// Vorlage im Serienbrief-Editor öffnen (Desk-Navigation).
export async function openEditor(id) {
	if (!embedded) return { ok: true, mock: true };
	return await rpc("open_editor", { template: id });
}

// Echte Empfänger (z. B. Mietverträge) für den Vorschau-Picker.
export async function loadRecipients(doctype, query) {
	if (!embedded) return { items: [], doctype: doctype || "" };
	return await rpc("recipients", { doctype: doctype || "", query: query || "" });
}

// PDF-Vorschau der gespeicherten Vorlage rendern. Mit Empfänger → echte Daten
// (Durchlauf-Pfad); ohne → Split-Preview mit Beispielwerten. → { pdf_base64, mode }.
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
