// Dekoriert echtes Vorlagen-HTML für die Anzeige/Bearbeitung im Editor und
// serialisiert es wieder zurück.
//
// Anzeige:  Jinja-Tokens ({{ }} / {% %}) werden in farbige, atomare Chips/Marker
//           verwandelt. Jeder Chip trägt den Roh-Token in data-token und ist
//           contenteditable=false, verhält sich also beim Editieren als ein Stück.
// Speichern: serializeEditableHtml() ersetzt jeden Chip wieder durch seinen
//           data-token, sodass exakt das ursprüngliche Token-Format zurückkommt.
//
// Das HTML stammt aus den eigenen `Serienbrief Vorlage`-Records (admin-authored).

const PREFIX_GROUP = {
	mieter: "mieter",
	hauptmieter: "mieter",
	verwalter: "verwalter",
	wohnung: "wohnung",
	immobilie: "wohnung",
	mietvertrag: "vertrag",
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

function escapeHtml(s) {
	return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Für Attributwerte in doppelten Anführungszeichen (data-token="…")
function escapeAttr(s) {
	return escapeHtml(s).replace(/"/g, "&quot;");
}

function groupForToken(inner) {
	const prefix = (inner || "").trim().split(/[.\s(]/)[0].toLowerCase();
	return PREFIX_GROUP[prefix] || "mieter";
}

function chip(rawToken, group, displayText) {
	return (
		`<span class="chip" data-group="${group}" data-token="${escapeAttr(rawToken)}"` +
		` contenteditable="false">${displayText}</span>`
	);
}

export function decorateTemplateHtml(html) {
	if (!html) return "";
	let out = html;

	// 1) Baustein-Aufrufe: {{ baustein("Name") }} → eigener Baustein-Chip
	out = out.replace(/\{\{\s*baustein\(\s*["']([^"']+)["']\s*\)\s*\}\}/g, (m, name) =>
		chip(m.trim(), "baustein", `⧉&nbsp;${escapeHtml(name)}`)
	);

	// 2) Generische Platzhalter: {{ ... }} → farbiger Chip nach Präfix
	out = out.replace(/\{\{([^}]+)\}\}/g, (m, inner) =>
		chip(m.trim(), groupForToken(inner), escapeHtml(m.trim()))
	);

	// 3) Logik-Tags: {% if ... %} / {% endif %} → dezenter Jinja-Marker
	out = out.replace(
		/\{%([^%]*)%\}/g,
		(m) =>
			`<span class="jinja-token" data-token="${escapeAttr(m.trim())}"` +
			` contenteditable="false">${escapeHtml(m.trim())}</span>`
	);

	return out;
}

// Editierten contenteditable-DOM zurück in speicherbares HTML wandeln:
// jeden dekorierten Chip durch seinen Roh-Token (data-token) ersetzen.
export function serializeEditableHtml(rootEl) {
	if (!rootEl) return "";
	const clone = rootEl.cloneNode(true);
	clone.querySelectorAll("[data-token]").forEach((span) => {
		const token = span.getAttribute("data-token") || "";
		span.replaceWith(document.createTextNode(token));
	});
	return clone.innerHTML;
}
