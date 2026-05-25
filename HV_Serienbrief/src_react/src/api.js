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
		// Pro-Baustein Input-Pfad-Overrides: { "<Baustein>": { "<Variable>": "<Pfad>" } }
		bausteinPaths: t.baustein_pfade || {},
		// Vorlagen-Variablen (Definition + Wert/Pfad), im Editor bearbeitbar.
		variables: t.variables || [],
		blocks: [],
		mock: false,
	};
}

// Vorlage duplizieren. Gibt { name, title } der neuen Kopie zurück.
export async function copyTemplate(id, newTitle) {
	if (!embedded) {
		return { name: `${id}-kopie`, title: newTitle || "Kopie", mock: true };
	}
	return await rpc("copy", { template: id, new_title: newTitle });
}

// Neues "Serienbrief Durchlauf"-Formular im Desk öffnen (Vorlage vorausgewählt).
// Navigiert das Eltern-Desk weg vom Editor — kein Rückgabewert nötig.
export async function openDurchlauf({ vorlage, title, iterationDoctype }) {
	if (!embedded) {
		return { ok: true, mock: true };
	}
	return await rpc("new_durchlauf", { vorlage, title, iteration_doctype: iterationDoctype });
}

// Editierten Inhalt zurück in die Vorlage speichern. Gibt { id, modified } zurück.
// bausteinPaths = Pro-Baustein Input-Pfad-Overrides (werden als JSON gespeichert).
export async function saveTemplate(id, html, bausteinPaths, variables) {
	if (!embedded) {
		return { id, modified: "gerade eben (Demo)", mock: true };
	}
	return await rpc("save", {
		name: id,
		html,
		baustein_pfade: JSON.stringify(bausteinPaths || {}),
		variables: JSON.stringify(variables || []),
	});
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
				inputs: b.inputs || [],
				outputs: b.outputs || [],
				standardpfade: b.standardpfade || [],
			})),
		};
	}
	// Embedded: rpc liefert items inkl. inputs/outputs/standardpfade.
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

// Bild in den Frappe-File-Store hochladen, gibt die /files/…-URL zurück. Base64 nur im
// Transit; gespeichert wird die URL (kein Base64-Bloat in der Vorlage). Standalone → null
// (Editor fällt dann auf URL-Eingabe zurück).
export async function uploadImage(file, templateName) {
	if (!embedded) return null;
	const dataUrl = await new Promise((resolve, reject) => {
		const r = new FileReader();
		r.onload = () => resolve(r.result);
		r.onerror = reject;
		r.readAsDataURL(file);
	});
	const base64 = String(dataUrl).split(",")[1] || "";
	const res = await rpc("upload_image", {
		filename: file.name,
		content_base64: base64,
		template: templateName || "",
	});
	return res && res.file_url;
}

// PDF-Vorschau rendern. Mit Empfänger → echte Daten (Durchlauf-Pfad, gespeicherte
// Vorlage); ohne → Split-Preview mit Beispielwerten. Gibt { pdf_base64, mode }.
export async function renderPreview({
	templateName,
	hauptVerteilObjekt,
	recipientId,
	html,
	variables,
	bausteinPaths,
	previewValues,
}) {
	if (!embedded) return { pdf_base64: "", mode: "mock" };
	// Live-Vorschau: aktueller (ungespeicherter) Editor-Stand wird serverseitig in-memory
	// auf die Vorlage angewandt und gerendert.
	const params = { template: templateName };
	if (html != null) params.html = html;
	if (variables != null) params.variables = JSON.stringify(variables);
	if (bausteinPaths != null) params.baustein_pfade = JSON.stringify(bausteinPaths);
	// Transiente Vorschau-Werte für Eingabe-Variablen (nicht gespeichert).
	if (previewValues && Object.keys(previewValues).length) {
		params.preview_values = JSON.stringify(previewValues);
	}
	if (recipientId && hauptVerteilObjekt) {
		params.iteration_doctype = hauptVerteilObjekt;
		params.iteration_objekt = recipientId;
	} else {
		params.split_preview = 1;
	}
	return await rpc("editor_preview", params);
}
