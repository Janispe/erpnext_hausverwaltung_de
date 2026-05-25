// High-level Daten-API für den Serienbrief-Durchlauf-Viewer. Eingebettet (im
// Durchlauf-Formular-iframe) gehen die Aufrufe über die postMessage-Bridge an
// whitelisted Backend-Methoden; standalone (npm run dev:durchlauf) fallen sie auf
// die Mock-Daten aus data.js zurück.
//
// Normalisierung: Das Backend liefert deutsche Status ("Generiert", "Läuft", …) und
// teils andere Feldnamen; hier wird alles in die Form gebracht, die App.jsx erwartet
// (englische Status-Keys, vollständige Empfänger-Objekte gegen undefined-Crashes).

import { rpc, isEmbedded } from "../bridge.js";
import { DURCHLAUF, RECIPIENTS } from "./data.js";

export const embedded = isEmbedded();

// docname der Durchlauf-Instanz aus der iframe-URL (?docname=…).
export function getDocname() {
	try {
		return new URLSearchParams(window.location.search).get("docname") || "";
	} catch {
		return "";
	}
}

// Vorausgewählte Vorlage (?vorlage=…) für den „Neuer Durchlauf"-Modus.
export function getVorlageParam() {
	try {
		return new URLSearchParams(window.location.search).get("vorlage") || "";
	} catch {
		return "";
	}
}

// true → eingebettet ohne docname ⇒ „Neuer Durchlauf"-Modus.
export function isNewMode() {
	return embedded && !getDocname();
}

const STATUS_RUN = { Entwurf: "draft", "Läuft": "running", Generiert: "completed", Fehlgeschlagen: "failed" };
const STATUS_REC = {
	Ausstehend: "pending",
	Generiert: "generated",
	"Übersprungen": "skipped",
	Fehler: "error",
	Gesendet: "sent",
};

function normRecipient(r) {
	return {
		id: r.id,
		customer: r.name || r.id,
		address: r.address || "",
		status: STATUS_REC[r.status] || "pending",
		// Domänenfelder (saldo/mahnstufe) gibt es im Backend (Phase 1) nicht — leere
		// Defaults, damit die UI nicht auf undefined zugreift.
		saldo: r.saldo || "",
		mahnstufe: r.mahnstufe ?? null,
		email: r.recipient_email || null,
		has_email: !!r.has_email,
		pages: r.pages || 0,
		render_ms: r.render_ms || 0,
		generated_at: r.generated_on || null,
		warning: r.warning || "",
		error_msg: r.error_msg || "",
		skip_reason: r.skip_reason || "",
		missing_vars: [],
		pdf_ok: !!r.has_pdf,
		pdf_url: r.pdf_url || null,
		dokument: r.dokument || null,
	};
}

// Vollständiger Durchlauf-Datensatz: { durchlauf, recipients, overrides }.
export async function loadDurchlauf() {
	if (!embedded) {
		return { durchlauf: DURCHLAUF, recipients: RECIPIENTS, overrides: {}, mock: true };
	}
	const d = await rpc("durchlauf_data", { docname: getDocname() });
	const durchlauf = {
		id: d.docname,
		title: d.title || "",
		status: STATUS_RUN[d.status] || "draft",
		vorlage: { id: d.vorlage, title: d.vorlage_title || d.vorlage || "", kategorie: d.kategorie || "" },
		iteration_doctype: d.iteration_doctype || "",
		date: d.date || "",
		created_by: d.created_by || "",
		can_write: !!d.can_write,
		counts: d.counts || {},
		variables: (d.variables || []).map((v) => ({
			name: v.name,
			label: v.label,
			type: v.type,
			desc: v.desc,
			default: v.default ?? "",
			value: v.value ?? "",
		})),
	};
	return {
		durchlauf,
		recipients: (d.recipients || []).map(normRecipient),
		overrides: d.per_recipient_overrides || {},
		mock: false,
	};
}

// Lauf-Fortschritt (Polling während status === "running").
export async function getProgress() {
	if (!embedded) return { status: "completed", progress: "", counts: {} };
	const p = await rpc("run_progress", { docname: getDocname() });
	return { status: STATUS_RUN[p.status] || "draft", progress: p.progress || "", counts: p.counts || {} };
}

// Lauf als Hintergrund-Job starten.
export async function startRun() {
	if (!embedded) return { status: "Läuft", mock: true };
	return await rpc("start_run", { docname: getDocname() });
}

// Globale Variablenwerte + Pro-Empfänger-Overrides speichern.
export async function saveVariables(variables, perRecipientOverrides) {
	if (!embedded) return { ok: true, mock: true };
	const params = { docname: getDocname() };
	if (variables != null) params.variables = JSON.stringify(variables);
	if (perRecipientOverrides != null) params.per_recipient_overrides = JSON.stringify(perRecipientOverrides);
	return await rpc("set_variables", params);
}

export async function addRecipients(objekte) {
	if (!embedded) return { added: (objekte || []).length, mock: true };
	return await rpc("add_recipients", { docname: getDocname(), objekte: JSON.stringify(objekte || []) });
}

export async function removeRecipients(objekte) {
	if (!embedded) return { removed: true, mock: true };
	return await rpc("remove_recipients", { docname: getDocname(), objekte: JSON.stringify(objekte || []) });
}

export async function availableRecipients(query) {
	if (!embedded) return { items: [], doctype: "" };
	return await rpc("available_recipients", { docname: getDocname(), query: query || "" });
}

// Sammel-PDF aus den bereits generierten Dokumenten. → { file_url }.
export async function mergedPdf() {
	if (!embedded) return { file_url: "" };
	return await rpc("merged_pdf", { docname: getDocname() });
}

// Frappe-Formular neu laden (nach Empfänger-Änderung, Zeitstempel/Grid aktuell halten).
export async function reloadForm() {
	if (!embedded) return { ok: true };
	return await rpc("reload_form", {});
}

// --- Vollbild-Page: Anlegen / Titel / Navigation ------------------------------

// Vorlagen für den „Neuer Durchlauf"-Picker.
export async function listVorlagen(query) {
	if (!embedded) return { items: [] };
	return await rpc("list_vorlagen", { query: query || "" });
}

// Neuen Durchlauf-Entwurf aus einer Vorlage anlegen. → { docname }.
export async function createDurchlauf(title, vorlage) {
	if (!embedded) return { docname: "MOCK-NEW" };
	return await rpc("create", { title: title || "", vorlage });
}

// Titel des Durchlaufs ändern.
export async function updateTitle(title) {
	if (!embedded) return { ok: true };
	return await rpc("update", { docname: getDocname(), title });
}

// Page-Navigation (Host setzt die Desk-Route → iframe lädt neu).
export async function gotoDurchlauf(docname) {
	if (!embedded) return { ok: true };
	return await rpc("goto_durchlauf", { docname });
}
export async function gotoNew() {
	if (!embedded) return { ok: true };
	return await rpc("new_durchlauf", {});
}
